"""Bridge: Layer 1 (hybrid ensemble) -> the mentions/assertions tables.

This replaces the single-pass extractor as the input to Layer 2 (ER), Layer 3
(graph) and Layer 4 (agent), so the whole stack runs on high-recall output.

Per chunk:  token_ner ∪ gazetteer ∪ llm  ->  sweep  ->  coref  ->  filter  ->  persist

Filtering is where recall-first extraction pays its precision debt. Three guards,
all evidence-based rather than model-based:
  * anaphora are never entities (routed to coref links instead);
  * spans inside a boilerplate/disclaimer segment cannot be NAME entities;
  * a name span must look like a name (no all-caps legalese, no header labels).
Identifier spans (email/phone/npi/tin/ssn/dob/address) become assertions bound to
the nearest preceding name mention, exactly as before, so Layer 2's blocking
passes and Layer 3's shared-identifier edges keep working.

The scan-coverage ledger is still written for every chunk, so the 100%-character
coverage proof survives the architecture change.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import chunking, contracts, coref, gazetteers, ner_ensemble, sweep, textnorm
from .repository import Repository
from .settings import CFG, Paths

CHUNK_PASS = "L1"

# NER label -> contracts.ENTITY_CLASSES
LABEL_TO_CLASS = {
    "person": "claimant",
    "organization": "medical_provider",
    "medical_provider": "medical_provider",
    "law_firm": "attorney",
    "attorney": "attorney",
    "repair_shop": "repair_shop",
    "adjuster": "adjuster",
    "claimant": "claimant",
}
IDENTIFIER_LABEL_TO_PREDICATE = {
    "email": "has_email", "phone": "has_phone", "npi": "has_npi",
    "tin": "has_tin", "ssn": "has_ssn", "date": "has_dob",
    "date_written": "has_dob", "address": "has_address",
}
NAME_LABELS = set(LABEL_TO_CLASS)

_ALLCAPS_LEGALESE = re.compile(r"^[A-Z][A-Z\s&'/.-]{6,}$")
_HEADER_LABEL = re.compile(
    r"^(From|Sent|To|Cc|Subject|Date|Claim|Claimant|Clmt|Atty|Attorney|Counsel|"
    r"Provider|Physician|Treating|Mailing|Email|Phone|Address|Contact|Birthdate|"
    r"DOB|NPI|TIN|Direct|Confidentiality|Notice)\b",
    re.I)


def _is_plausible_name(surface: str) -> bool:
    s = surface.strip()
    if len(s) < 3 or "\n" in s:
        return False
    if _ALLCAPS_LEGALESE.match(s):        # CONFIDENTIALITY NOTICE, etc.
        return False
    if _HEADER_LABEL.match(s):            # template/email header labels
        return False
    toks = [t for t in re.split(r"[\s,]+", s) if t]
    if len(toks) < 2 and not s.lower().startswith("dr"):
        return False
    # must contain at least two capitalized alphabetic tokens
    caps = [t for t in toks if t[:1].isupper() and t.strip(".").isalpha()]
    return len(caps) >= 2 or s.lower().startswith("dr")


def _boilerplate_ranges(repo: Repository) -> dict[str, list[tuple[int, int]]]:
    """Char ranges of boilerplate/disclaimer segments, per doc (from Layer 0 profiling)."""
    segs = repo.table("segments")
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for _, s in segs[segs["kind"] == "boilerplate"].iterrows():
        out[s["doc_id"]].append((int(s["char_start"]), int(s["char_end"])))
    return out


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for (a, b) in ranges)


def run(repo: Repository, limit_docs: int | None = None,
        use_llm: bool = True, use_sweep: bool = True) -> dict:
    """Run Layer 1 over the corpus and repopulate mentions/assertions/scan_ledger."""
    docs_df = repo.table("documents")
    claim_of = {r["doc_id"]: r["claim_id"] for _, r in docs_df.iterrows()}
    files = sorted(Paths.raw_notes.glob("*.txt"))
    if limit_docs:
        files = files[:limit_docs]
    texts = {f.stem: f.read_text() for f in files}
    doc_map = {d: (claim_of.get(d, "UNKNOWN"), t) for d, t in texts.items()}

    chunks = chunking.chunk_corpus(doc_map)
    token_ner = ner_ensemble.get_token_ner()
    resolver = coref.get_resolver()
    boiler = _boilerplate_ranges(repo)

    # segments give each mention a dup_group_id (quoted-copy handling downstream)
    segs = repo.table("segments")
    seg_by_doc: dict[str, list[dict]] = defaultdict(list)
    for _, s in segs.iterrows():
        seg_by_doc[s["doc_id"]].append(s.to_dict())

    # ---- Layer 1 per chunk ------------------------------------------------
    spans_by_doc: dict[str, list] = defaultdict(list)
    ledger = []
    n_sweep_added = 0
    for ch in chunks:
        spans = ner_ensemble.extract_chunk(ch, token_ner, use_llm=use_llm,
                                           use_gazetteer=True, use_token_ner=True)
        if use_sweep:
            extra = sweep.sweep_chunk(ch, spans)
            n_sweep_added += len(extra)
            spans = ner_ensemble.union_spans([spans, extra])
        spans_by_doc[ch.doc_id].extend(spans)
        ledger.append(contracts.ScanSpan(ch.doc_id, ch.char_start, ch.char_end,
                                         "layer1_ensemble", CHUNK_PASS).__dict__)

    # ---- per doc: merge, coref, filter, persist ---------------------------
    counter = {"m": 0, "a": 0}

    def nid(p):
        counter[p] += 1
        return f"{p}{counter[p]:07d}"

    mentions, assertions, coref_links = [], [], []
    n_dropped_boiler = n_dropped_shape = 0

    for doc_id in sorted(spans_by_doc):
        raw = texts[doc_id]
        merged = ner_ensemble.union_spans([spans_by_doc[doc_id]])
        merged.sort(key=lambda c: c.start)
        bl = boiler.get(doc_id, [])

        def seg_for(pos: int):
            for s in seg_by_doc.get(doc_id, []):
                if s["char_start"] <= pos < s["char_end"]:
                    return s
            return None

        # 1) name mentions
        doc_mentions = []
        for c in merged:
            if c.label not in NAME_LABELS:
                continue
            if _in_ranges(c.start, bl):
                n_dropped_boiler += 1
                continue
            if not _is_plausible_name(c.text):
                n_dropped_shape += 1
                continue
            seg = seg_for(c.start)
            left = raw[max(0, c.start - 50):c.start]
            right = raw[c.end:min(len(raw), c.end + 70)]
            klass = _classify(c.text, c.label, left, right)
            mid = nid("m")
            row = contracts.Mention(
                mention_id=mid, doc_id=doc_id,
                segment_id=seg["segment_id"] if seg else None,
                entity_class=klass, surface=c.text,
                norm_surface=textnorm.normalize_name(c.text),
                char_start=c.start, char_end=c.end,
                extractor="+".join(sorted(c.extractors)),
                dup_group_id=seg.get("dup_group_id") if seg else None,
                inside_quoted=1 if (seg and seg["kind"] == "email_quoted") else 0,
            ).__dict__
            mentions.append(row)
            doc_mentions.append((c.start, mid))
            assertions.append(_assn(nid, mid, "has_name", c.text, c.text, doc_id,
                                    c.start, c.end, "asserted",
                                    "+".join(sorted(c.extractors)), raw))

        doc_mentions.sort()

        def subject_for(pos: int):
            """Bind an identifier to a name only on STRONG proximity evidence.

            A loose 'nearest preceding mention anywhere' rule mis-binds across
            email headers and quoted chains ("From: A <a@x>\\nTo: B <b@y>"),
            attaching B's address to A. Those wrong identifiers then look like
            conflicting validated ids and the cluster-consistency rule splits one
            real person into many entities. So we require the name and the
            identifier to sit on the SAME LINE, or on the immediately preceding
            line (the signature-block case: name on one line, contact below).
            No qualifying name -> no assertion, rather than a wrong one.
            """
            line_start = raw.rfind("\n", 0, pos) + 1
            prev_line_start = raw.rfind("\n", 0, max(0, line_start - 1)) + 1
            best = None
            for (s, mid) in doc_mentions:
                if s > pos:
                    break
                if s >= line_start:                 # same line
                    best = mid
                elif s >= prev_line_start and (pos - s) <= 120:
                    best = mid                      # immediately preceding line
            return best

        # 2) identifier spans -> assertions, bound only on strong proximity
        n_unbound = 0
        for c in merged:
            pred = IDENTIFIER_LABEL_TO_PREDICATE.get(c.label)
            if not pred:
                continue
            subj = subject_for(c.start)
            if subj is None:
                n_unbound += 1
                continue
            kind = {"has_email": "email", "has_phone": "phone", "has_npi": "npi",
                    "has_tin": "tin", "has_ssn": "ssn"}.get(pred, "text")
            pol = _polarity(raw, c.start, c.end)
            assertions.append(_assn(nid, subj, pred, c.text,
                                    textnorm.normalize_identifier(kind, c.text),
                                    doc_id, c.start, c.end, pol, "gazetteer", raw))

        # 2b) allegation free-text -> assertions (kept separate from facts)
        for am in re.finditer(r"(suspect[^.;\n]*|alleg[^.;\n]*)", raw, re.I):
            subj = subject_for(am.start()) or (doc_mentions[0][1] if doc_mentions else None)
            if subj is None:
                continue
            txt = am.group(0).strip()
            assertions.append(_assn(nid, subj, "allegation", txt, txt.lower(), doc_id,
                                    am.start(), am.start() + len(txt), "alleged",
                                    "layer1_ensemble", raw))

        # 3) coreference: anaphora -> antecedent (links, not nodes)
        ment_dicts = [{"start": m["char_start"], "end": m["char_end"],
                       "text": m["surface"], "label": m["entity_class"]}
                      for m in mentions if m["doc_id"] == doc_id]
        for link in resolver.resolve(raw, ment_dicts):
            coref_links.append({"doc_id": doc_id, "start": link.start, "end": link.end,
                                "surface": link.surface,
                                "antecedent": link.antecedent_surface,
                                "antecedent_class": link.antecedent_class,
                                "kind": link.kind, "backend": link.backend})

    # ---- persist ----------------------------------------------------------
    repo.conn.execute("PRAGMA foreign_keys=OFF")
    for t in ("assertions", "mentions", "scan_ledger", "candidate_pairs",
              "entity_members", "entity_versions", "entity_attributes",
              "dossiers", "entities"):
        repo.conn.execute(f"DELETE FROM {t}")
    repo.conn.commit()
    repo.conn.execute("PRAGMA foreign_keys=ON")

    repo.add_mentions(mentions)
    repo.add_assertions(assertions)
    repo.add_scan_spans(ledger)

    return {
        "n_chunks": len(chunks), "n_mentions": len(mentions),
        "n_assertions": len(assertions), "n_coref_links": len(coref_links),
        "n_sweep_added": n_sweep_added,
        "dropped_boilerplate": n_dropped_boiler, "dropped_shape": n_dropped_shape,
        "token_ner_backend": token_ner.name, "coref_backend": resolver.name,
        "coref_sample": coref_links[:5],
    }


_ADJUSTER_DOMAIN = "@ourinsco.com"


def _classify(surface: str, label: str, left: str, right: str) -> str:
    """Infer entity class from the surface plus BOTH sides of its context.

    Right-context matters: in email headers the discriminating signal (the
    carrier's own domain, the firm name in a signature) follows the name.
    """
    low = surface.lower()
    l, r = left.lower(), right.lower()

    # 1) surface-intrinsic signals are strongest
    if any(w in low for w in ("auto body", "collision", "automotive", "car care",
                              "body works", "repair")):
        return "repair_shop"
    if low.startswith("dr") or any(w in low for w in (
            "orthopedic", "physical therapy", "imaging", "medical group",
            "chiropractic", "neurology", "clinic", "hospital")):
        return "medical_provider"
    if any(w in low for w in ("law group", "llp", "legal", "trial group",
                              "attorneys", "law offices")):
        return "attorney"

    # 2) our own carrier domain on either side -> internal adjuster / client rep
    if _ADJUSTER_DOMAIN in r or _ADJUSTER_DOMAIN in l:
        return "adjuster"
    if "claims department" in r or "adjuster" in l or "claim rep" in l:
        return "adjuster"

    # 3) an external firm domain or firm name following the name -> attorney
    if re.search(r"@(?!ourinsco\.com|example\.com)[a-z0-9.\-]+\.[a-z]{2,}", r):
        return "attorney"
    if any(w in r for w in ("law group", "llp", "legal partners", "trial group",
                            "injury attorneys", "law offices")):
        return "attorney"

    # 4) explicit left-side role cue (template labels: "Clmt Atty - <name>")
    role = gazetteers.role_from_context(left)
    if role:
        return role

    return LABEL_TO_CLASS.get(label, "claimant")


def _polarity(raw: str, s: int, e: int) -> str:
    ctx = raw[max(0, s - 40):e + 10].lower()
    if any(c in ctx for c in ("wrong", "correct is", "prior note listed")):
        return "retracted"
    if any(c in ctx for c in ("suspect", "alleg")):
        return "alleged"
    if any(c in ctx for c in ("denies", "denied", "no ", "not ")):
        return "negated"
    if any(c in ctx for c in ("reported", "per records", "states", "advised")):
        return "reported"
    return "asserted"


def _assn(nid, subj, pred, raw_v, norm_v, doc_id, s, e, pol, extractor, raw_text):
    from .extraction import span_grounded
    return contracts.Assertion(
        assertion_id=nid("a"), subject_mention_id=subj, predicate=pred,
        object_value_raw=raw_v, object_value_norm=norm_v, polarity=pol,
        source_doc_id=doc_id, source_span_start=s, source_span_end=e,
        extractor=extractor, pass_id=CHUNK_PASS,
        grounded=span_grounded(raw_text, s, e, raw_v), confidence=0.85,
    ).__dict__
