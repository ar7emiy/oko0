"""Layer 1e: relation extraction (subject -> predicate -> object) from prose.

This closes the gap diagnosed in the ERD pass: the schema has always been a
triple store (`assertions` is literally subject/predicate/object) and the graph
has always been triple-shaped (`GraphEdge` is src/predicate/dst), but NOTHING
produced relational triples. The pipeline could emit exactly 9 predicates --
`has_name`, seven identifier bindings, and `allegation` -- all of which attach
a value to ONE entity. Six declared predicates (`represents`, `affiliated_with`,
`works_on_claim`, `has_role`, `has_firm`, `has_title`) were never produced by
any code path, and the graph's role edges were synthesized from `entity_class`
plus shared-claim membership rather than read from the text.

Design decisions, and why:

  * OPEN predicate vocabulary. The model returns whatever verb the text
    supports; we normalize toward canonical forms and keep the surface form.
    A closed enum here would silently drop "referred X to Y", "supervises",
    "is the daughter of" -- all of which appear in real notes and none of
    which fit the five-value `CANONICAL_PREDICATES` relational subset.
  * SPAN-GROUNDED, like everything else. Every relation carries the character
    span of the EVIDENCE (the clause that proves it), which is generally not
    the subject's span. Ungrounded relations are rejected, not stored with a
    warning, because an assertion whose evidence cannot be located is not
    auditable and this system's entire value proposition is auditability.
  * POLARITY IS REQUIRED, never defaulted. "our client is NOT alleging
    permanent impairment" stored as `asserted` inverts the meaning of the
    note. The model must choose from POLARITIES; an unrecognized value is
    coerced to 'asserted' AND flagged, rather than silently accepted.
  * Subjects and objects are bound to EXISTING mentions by span overlap where
    possible. A relation naming someone the extractor never found is kept with
    a NULL mention id rather than dropped -- the same reasoning as the orphan
    identifier path, and for the same reason: it is evidence that our own
    recall missed something.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import contracts, genai
from .settings import CFG, genai_mode, genai_mode_is_forced


class RelationExtractorUnavailable(RuntimeError):
    """Raised when relation extraction cannot run for real.

    Deliberately fatal, for the same reason the NER and LLM lanes are: a
    silent stand-in produces output shaped like a real run and quietly
    invalidates anything measured from it.
    """


# Surface predicate forms folded toward a canonical spelling. This is a
# NORMALIZATION table, not a whitelist -- an unlisted predicate passes through
# unchanged. It grows as real notes reveal new phrasings.
PREDICATE_NORMALIZATION = {
    # representation
    "represented_by": "REPRESENTED_BY", "is_represented_by": "REPRESENTED_BY",
    "retained": "REPRESENTED_BY", "counsel_for": "REPRESENTS",
    "represents": "REPRESENTS", "attorney_for": "REPRESENTS",
    # treatment
    "treated_by": "TREATED_BY", "is_treated_by": "TREATED_BY",
    "went_to": "TREATED_BY", "was_seen_at": "TREATED_BY", "visited": "TREATED_BY",
    "seen_by": "TREATED_BY", "treats": "TREATED_BY",
    "referred_to": "REFERRED_TO", "referred": "REFERRED_TO",
    # repair
    "repaired_by": "REPAIRED_BY", "repairs": "REPAIRED_BY",
    "vehicle_repaired_by": "REPAIRED_BY", "towed_to": "REPAIRED_BY",
    # employment / affiliation
    "employed_by": "EMPLOYED_BY", "works_for": "EMPLOYED_BY",
    "employed_at": "EMPLOYED_BY", "employer_of": "EMPLOYS",
    "affiliated_with": "AFFILIATED_WITH", "works_at": "AFFILIATED_WITH",
    "member_of": "AFFILIATED_WITH", "partner_at": "AFFILIATED_WITH",
    "supervises": "SUPERVISES", "supervisor_of": "SUPERVISES",
    # adjusting / handling
    "adjuster_on": "ADJUSTER_ON", "adjusts": "ADJUSTER_ON",
    "handled_by": "ADJUSTER_ON", "handles": "ADJUSTER_ON",
}

# Bulk provenance is not a relationship. Mirrors graph_store.BANNED_PREDICATES
# so a rejected predicate is rejected at extraction time rather than at graph
# build time, where the evidence span has already been discarded.
BANNED_PREDICATES = {"MENTIONED_IN", "HAS_NOTE", "APPEARS_IN", "REFERENCED_BY",
                     "IS_IN_DOCUMENT", "NOTED_IN"}

# Identifier bindings are NOT relations. The gazetteer lane owns them and
# actually validates them (a real Luhn check for NPI); re-extracting them here
# produces an unvalidated duplicate that would then have to be reconciled.
# Routed away rather than silently dropped -- the count is reported.
IDENTIFIER_PREDICATE_RE = re.compile(
    r"^(HAS_)?(NPI|TIN|SSN|EIN|PHONE|PHONE_NUMBER|EMAIL|EMAIL_ADDRESS|"
    r"ADDRESS|DOB|DATE_OF_BIRTH|ZIP|POLICY_NUMBER|CLAIM_NUMBER)$")

# Predicates too vague to be a useful edge. "IS", "REPORTS", "USED" carry no
# relational semantics on their own; keeping them would inflate the graph with
# edges nobody can query meaningfully.
DEGENERATE_PREDICATES = {"IS", "IS_ON", "IS_A", "WAS", "HAS", "REPORTS",
                         "USED", "FILED", "ARRANGED", "PERFORMED", "MADE",
                         "PROVIDED", "RECEIVED", "SENT", "CONTACTED"}


def normalize_predicate(predicate: str) -> str:
    """Fold a surface predicate toward canonical form; unknowns pass through."""
    raw = (predicate or "").strip().lower().replace(" ", "_").replace("-", "_")
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        return ""
    canon = PREDICATE_NORMALIZATION.get(raw)
    return canon if canon else raw.upper()


@dataclass
class RelationCandidate:
    """One extracted subject -> predicate -> object triple, span-grounded."""

    subject_text: str
    predicate: str                  # normalized
    predicate_raw: str              # exactly what the model returned
    object_text: str
    polarity: str                   # one of contracts.POLARITIES
    evidence_start: int             # ABSOLUTE document offsets
    evidence_end: int
    evidence_text: str = ""
    confidence: float = 0.0
    subject_mention_id: str | None = None   # bound later by span overlap
    object_mention_id: str | None = None
    flags: list = field(default_factory=list)

    def key(self):
        return (self.subject_text.lower(), self.predicate,
                self.object_text.lower(), self.evidence_start)


def relation_schema() -> dict:
    """Constrained-output schema for relation extraction.

    `predicate` is deliberately a free string, NOT an enum: the whole point is
    an open vocabulary. `polarity` IS an enum, because downstream survivorship
    logic branches on it structurally and an unknown value has no defined
    behaviour (see the vocabulary rule in DECISIONS).
    """
    return {
        "type": "object",
        "properties": {
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                        "polarity": {"type": "string",
                                     "enum": list(contracts.POLARITIES)},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["subject", "predicate", "object", "polarity",
                                 "evidence"],
                },
            }
        },
        "required": ["relations"],
    }


PROMPT = """You are reading one chunk of an insurance claim adjuster's note.

Extract every RELATIONSHIP between two named parties, or between a party and a
concrete thing (a firm, a shop, a facility, an amount, a location).

Rules:
- subject and object must be TEXT THAT APPEARS IN THE CHUNK, copied exactly.
- predicate: use a short snake_case verb phrase that fits the text. Do NOT pick
  from a fixed list. If the note says someone was referred, use "referred_to".
  If someone supervises another, use "supervises". Invent the predicate the
  sentence actually supports.
- polarity is REQUIRED and must be one of: asserted, negated, alleged,
  reported, retracted.
    * negated  -> the note says it is NOT so ("is not an attorney",
                  "NOT alleging permanent impairment")
    * alleged  -> suspected or claimed, not established ("it is alleged that")
    * reported -> stated by a third party, not verified by the adjuster
    * retracted-> a previously stated fact the note now withdraws
    * asserted -> the adjuster states it as fact
  Choosing "asserted" for a negated statement inverts its meaning. Read carefully.
- evidence: copy the EXACT substring of the chunk that proves the relation.
  It must appear verbatim in the chunk. Keep it short - one clause is ideal.
- Do NOT emit relationships whose only content is that something was mentioned
  in this document. Provenance is recorded separately.
- subject and object must be a NAMED party or a CONCRETE thing. Never a
  pronoun ("he", "she", "they") and never a bare role descriptor
  ("the claimant", "the insured", "her supervisor", "the treating physician").
  If the chunk names the party anywhere, use the NAME. If it refers to someone
  only by role ("the claimant") AND that role matches a party in the
  PARTIES ALREADY IDENTIFIED list below, use that party's name. Only if you
  can resolve them neither way, emit the descriptor as-is -- never drop a real
  relationship just because the name appears elsewhere.
- Use the fullest form of the name that appears ("Dr. Alicia Reyes", not "Dr.
  Reyes") when the chunk contains it.
- Do NOT extract identifiers as relations. A phone number, NPI, TIN, SSN,
  email or address attached to a party is handled elsewhere. Skip those.
- The predicate must carry real relational meaning. "supervises", "referred_to",
  "employed_by" are good. Bare "is", "has", "reports", "performed" are not --
  either make the predicate specific or skip the relation.

{roster}
CHUNK:
<<<
{chunk}
>>>
"""


def extract_relations(chunk_text: str, base_offset: int = 0,
                      known_parties: list[str] | None = None) -> list[RelationCandidate]:
    """Extract span-grounded relations from one chunk.

    `base_offset` is the chunk's absolute char_start, so returned spans are
    absolute document offsets like every other span in the system.

    `known_parties` are names already resolved elsewhere on this CLAIM. Without
    them, a note that says "the claimant is employed by X" is unresolvable:
    the claimant is frequently named only in the first note of the claim, and
    every subsequent note refers to them by role. Chunk-local extraction
    therefore cannot bind the relation to anyone, which is a property of where
    the chunk boundary fell rather than of the text. Passing the claim's known
    parties is the cheap form of the coreference context that `coref.py` and
    the `coref_links` table exist to provide.
    """
    if genai_mode() == "offline":
        if not genai_mode_is_forced():
            raise RelationExtractorUnavailable(
                "No GenAI API key is set, so relation extraction cannot run. "
                "Refusing to substitute a stand-in: relation extraction has no "
                "deterministic equivalent, and returning an empty list would be "
                "indistinguishable from 'this note contains no relationships'. "
                "Set an API key, or set GENAI_MODE=offline to knowingly run "
                "with relations disabled."
            )
        return []

    roster = ""
    if known_parties:
        names = "\n".join(f"  - {n}" for n in sorted(set(known_parties)))
        roster = (
            "\nPARTIES ALREADY IDENTIFIED ON THIS CLAIM (use these names when the\n"
            "chunk refers to someone by role instead of by name):\n"
            f"{names}\n"
        )

    data = genai.generate_json(
        PROMPT.format(chunk=chunk_text, roster=roster), relation_schema(),
        task="relation_extract")

    out: list[RelationCandidate] = []
    rejected = {"banned": 0, "identifier_binding": 0, "degenerate_predicate": 0,
                "descriptor_flagged": 0, "ungrounded_evidence": 0}
    for r in data.get("relations", []):
        subj = (r.get("subject") or "").strip()
        obj = (r.get("object") or "").strip()
        pred_raw = (r.get("predicate") or "").strip()
        evidence = (r.get("evidence") or "").strip()
        if not subj or not pred_raw or not evidence:
            continue

        pred = normalize_predicate(pred_raw)
        if not pred or pred in BANNED_PREDICATES:
            rejected["banned"] += 1
            continue
        if IDENTIFIER_PREDICATE_RE.match(pred):
            # Belongs to the gazetteer/identifier lane, which validates it.
            rejected["identifier_binding"] += 1
            continue
        if pred in DEGENERATE_PREDICATES:
            rejected["degenerate_predicate"] += 1
            continue
        # A descriptor argument ("the claimant") is KEPT and flagged, not
        # dropped: the party is often named in another chunk or an earlier
        # note, which is precisely what coref resolution is for. Dropping here
        # would discard a real relationship because of where it happened to
        # fall relative to a chunk boundary.
        descriptor_flags = []
        if _is_descriptor(subj):
            descriptor_flags.append("subject_is_descriptor")
        if _is_descriptor(obj):
            descriptor_flags.append("object_is_descriptor")
        if descriptor_flags:
            rejected["descriptor_flagged"] += 1

        # Ground the evidence: it must be locatable in the chunk verbatim.
        # An assertion whose evidence cannot be found is not auditable, and an
        # unauditable assertion is worse than a missing one -- it looks real.
        idx = chunk_text.find(evidence)
        flags = []
        if idx < 0:
            idx, evidence, flags = _relocate_evidence(chunk_text, evidence)
            if idx < 0:
                rejected["ungrounded_evidence"] += 1
                continue          # genuinely ungrounded -> rejected
            flags.append("evidence_fuzzy_located")

        polarity = (r.get("polarity") or "").strip().lower()
        if polarity not in contracts.POLARITIES:
            flags.append(f"polarity_unrecognized:{polarity or 'empty'}")
            polarity = "asserted"

        out.append(RelationCandidate(
            subject_text=subj, predicate=pred, predicate_raw=pred_raw,
            object_text=obj, polarity=polarity,
            evidence_start=base_offset + idx,
            evidence_end=base_offset + idx + len(evidence),
            evidence_text=evidence,
            confidence=float(r.get("confidence") or 0.7),
            flags=flags + descriptor_flags,
        ))
    extract_relations.last_rejected = rejected
    return out


# Bare role descriptors that name no one. A relation with one of these as an
# argument cannot be bound to a mention, so it records a fact about nobody.
_DESCRIPTOR_RE = re.compile(
    r"^(the\s+)?(claimant|insured|client|patient|customer|policyholder|"
    r"plaintiff|defendant|adjuster|attorney|counsel|provider|physician|doctor|"
    r"treating\s+\w+|supervisor|employer|witness|driver|owner|shop|facility|"
    r"her|his|their|our)\s*\w*$", re.I)


def _is_descriptor(text: str) -> bool:
    """True if `text` is a bare role descriptor rather than a named party."""
    t = (text or "").strip().strip(".,;:").lower()
    if not t:
        return True
    if _DESCRIPTOR_RE.match(t):
        return True
    # "her supervisor", "the treating physician", "his attorney"
    return bool(re.match(r"^(the|her|his|their|its|our|a|an)\s+\w+$", t, re.I))


def _relocate_evidence(chunk_text: str, evidence: str) -> tuple[int, str, list]:
    """Locate near-verbatim evidence the model reworded only in whitespace.

    Models normalize runs of whitespace when copying, and occasionally alter
    case. We retry on those two axes ONLY. We deliberately do not fuzzy-match
    on content: a model that paraphrased its evidence has not shown us where
    the fact lives, and accepting a paraphrase makes the span meaningless.

    Returns EXACT original offsets. An earlier version padded the end by a
    fixed 8 characters, which made every relocated span disagree with its own
    stored text.
    """
    collapsed = re.sub(r"\s+", " ", evidence).strip()
    if not collapsed:
        return -1, evidence, []

    # Build the collapsed form of the chunk while recording, for each collapsed
    # character, its index in the original string.
    flat_chars, index_map = [], []
    prev_space = False
    for i, ch in enumerate(chunk_text):
        if ch.isspace():
            if prev_space:
                continue
            flat_chars.append(" ")
            index_map.append(i)
            prev_space = True
        else:
            flat_chars.append(ch)
            index_map.append(i)
            prev_space = False
    flat = "".join(flat_chars)

    j = flat.find(collapsed)
    if j < 0:
        j = flat.lower().find(collapsed.lower())
    if j < 0:
        return -1, evidence, []

    start = index_map[j]
    end_flat = j + len(collapsed) - 1
    end = index_map[end_flat] + 1
    return start, chunk_text[start:end], []


def bind_to_mentions(relations: list[RelationCandidate],
                     mentions: list[dict]) -> dict:
    """Attach mention ids to relation subjects/objects by surface match.

    A relation naming a party the extractor never found is KEPT with a NULL
    mention id, not dropped. Same reasoning as the orphan identifier path: it
    is a record of something our own recall missed, and discarding it destroys
    the only evidence that the miss happened.
    """
    by_surface: dict[str, str] = {}
    for m in mentions:
        surf = (m.get("surface") or "").strip().lower()
        if surf:
            by_surface.setdefault(surf, m["mention_id"])

    stats = {"subject_bound": 0, "object_bound": 0,
             "subject_unbound": 0, "object_unbound": 0}
    for rel in relations:
        s = by_surface.get(rel.subject_text.lower())
        if s is None:
            s = _partial_surface_match(rel.subject_text, by_surface)
        rel.subject_mention_id = s
        stats["subject_bound" if s else "subject_unbound"] += 1

        o = by_surface.get(rel.object_text.lower())
        if o is None:
            o = _partial_surface_match(rel.object_text, by_surface)
        rel.object_mention_id = o
        stats["object_bound" if o else "object_unbound"] += 1
        if s is None:
            rel.flags.append("subject_not_in_mentions")
        if o is None:
            rel.flags.append("object_not_in_mentions")
    return stats


def _partial_surface_match(text: str, by_surface: dict) -> str | None:
    """Match 'Dr. Alicia Reyes' to a mention of 'Alicia Reyes', and vice versa."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for surf, mid in by_surface.items():
        if surf and (surf in t or t in surf) and abs(len(surf) - len(t)) <= 12:
            return mid
    return None


# ---------------------------------------------------------------------------
# Identifier binding
# ---------------------------------------------------------------------------
# WHY THIS IS A SEPARATE LANE, NOT A RELATION
#
# The gazetteer FINDS and VALIDATES identifiers -- a Luhn check on an NPI is
# decidable, and not something to ask a model for. Deciding WHO an identifier
# belongs to is local semantic reading: the model's strength, and what
# pipeline_v2.subject_for's line-distance rule crudely approximates.
#
# That split was measured before it was built. Against ground truth:
#
#     line rule (same line / previous line)   precision 0.747   recall 0.371
#     LLM (gazetteer finds, LLM binds)        precision 0.973
#
# and of 176 identifiers the line rule left unbound, 144 had their owner named
# within 300 characters -- so 82% of its "orphans" were misses, not orphans.
#
# The error KINDS differ more than the rates. The LLM's mistakes are
# person-vs-their-own-firm (an office address attributed to the firm rather than
# the attorney, which is arguably correct). The line rule's are category errors:
# an attorney's email bound to the claimant, a provider's address to the
# claimant, the claimant's phone to a repair shop. The clearest case is
# fatima.martin@harborvance.com bound to "Grace Martin" -- an email whose
# local-part names its owner, attached to a different person who merely sat
# closer on the page.


@dataclass
class IdentifierBinding:
    """One identifier attached to one named party, with evidence."""
    kind: str
    value: str
    owner_text: str                  # "" => the model declined to guess
    evidence_start: int
    evidence_end: int
    evidence_text: str
    confidence: float = 0.7
    method: str = "llm"              # llm | line_rule | unbound
    flags: list = field(default_factory=list)


def identifier_binding_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "bindings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "identifier": {"type": "string"},
                        "owner": {"type": "string"},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["identifier", "owner"],
                },
            }
        },
        "required": ["bindings"],
    }


BINDING_PROMPT = """For each identifier listed below, say which party in the text it belongs to.

Rules:
- Use the party's NAME exactly as it appears in the text. Never a role
  descriptor ("the claimant", "the adjuster") and never a pronoun.
- An identifier belongs to the party it IDENTIFIES, not the nearest name. An
  email whose local-part is a person's name belongs to that person even if
  another name sits closer on the page.
- In a quoted email chain, a sender's address belongs to the SENDER, not to
  whoever is being written to.
- If the text does not make the owner clear, set owner to "" rather than
  guessing. An unbound identifier is kept and stays searchable; a wrongly bound
  one corrupts the party it was attached to.
- evidence: the exact substring of the text that shows the ownership.

IDENTIFIERS FOUND IN THIS TEXT:
{ids}

TEXT:
<<<
{chunk}
>>>
"""


def _binding_rows(text: str, base_offset: int, hits: list, data: dict) -> list:
    """Shared parse for the single-chunk and batched forms."""
    by_value = {h.text.strip().lower(): h for h in hits}
    out = []
    for b in (data or {}).get("bindings", []):
        val = (b.get("identifier") or "").strip()
        hit = by_value.get(val.lower())
        if hit is None:
            continue          # an identifier the gazetteer did not find: ignore
        owner = (b.get("owner") or "").strip()
        evidence = (b.get("evidence") or "").strip()

        # Same rule the relation lane applies: an assertion whose evidence
        # cannot be located is not auditable. Keep it, but say so.
        flags = []
        idx = text.find(evidence) if evidence else -1
        if idx < 0:
            idx, evidence, reloc = _relocate_evidence(text, evidence or val)
            flags.extend(reloc)
            if idx < 0:
                idx, evidence = max(0, text.find(val)), val
                flags.append("evidence_ungrounded")
            else:
                flags.append("evidence_fuzzy_located")

        out.append(IdentifierBinding(
            kind=hit.label, value=hit.text, owner_text=owner,
            evidence_start=base_offset + idx,
            evidence_end=base_offset + idx + len(evidence),
            evidence_text=evidence,
            confidence=float(b.get("confidence") or 0.7),
            method="llm" if owner else "unbound",
            flags=flags,
        ))
    return out


def bind_identifiers(chunk_text: str, base_offset: int,
                     hits: list) -> list[IdentifierBinding]:
    """Ask which party each gazetteer-found identifier belongs to.

    A declined owner is returned with method="unbound" rather than dropped, so
    the decline is visible rather than looking like an absent identifier.
    """
    if not hits:
        return []
    if genai_mode() == "offline":
        if not genai_mode_is_forced():
            raise RelationExtractorUnavailable(
                "No GenAI API key is set, so identifier binding cannot run. "
                "Refusing to fall back to line proximity silently: measured "
                "against ground truth, that rule binds one in four identifiers "
                "to the WRONG party (precision 0.747), and a wrong identifier "
                "corrupts the entity it lands on. Set a key, or set "
                "GENAI_MODE=offline to accept the weaker rule knowingly."
            )
        return []

    idlist = "\n".join(f"  - {h.label}: {h.text}" for h in hits)
    data = genai.generate_json(
        BINDING_PROMPT.format(ids=idlist, chunk=chunk_text),
        identifier_binding_schema(), task="identifier_binding")
    return _binding_rows(chunk_text, base_offset, hits, data)


def bind_identifiers_many(chunks, hits_by_chunk: dict) -> dict:
    """Binding over many chunks through the thread pool.

    Only chunks that actually contain identifiers are sent, so the marginal cost
    over the existing LLM lane is well below one extra call per chunk.
    """
    todo = [c for c in chunks if hits_by_chunk.get(c.chunk_id)]
    if not todo or genai_mode() == "offline":
        return {}

    jobs = []
    for c in todo:
        idlist = "\n".join(f"  - {h.label}: {h.text}"
                           for h in hits_by_chunk[c.chunk_id])
        jobs.append({"prompt": BINDING_PROMPT.format(ids=idlist, chunk=c.text),
                     "offline_handler": None})
    results = genai.generate_json_batch(
        jobs, identifier_binding_schema(), task="identifier_binding")
    return {c.chunk_id: _binding_rows(c.text, c.char_start,
                                      hits_by_chunk[c.chunk_id], data)
            for c, data in zip(todo, results)}
