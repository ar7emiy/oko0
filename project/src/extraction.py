"""Notebook 03 engine: deterministic template parsing + (Gemini|heuristic)
narrative/email extraction, span-fidelity validation, and the scan-coverage
ledger.

Two extractors, both of which record EVERY span they process into scan_ledger
(independent of whether an entity was found) so notebook 07 can prove 100%
character coverage:

  extractor="template" (pass_id T1): deterministic per-fingerprint label:value
      parsing of template_block segments; placeholder blocklist; "same as above"
      resolution; per-field type validators.
  extractor="genai"    (pass_id N1): narrative/email/header/signature/quoted/
      boilerplate segments. Online -> Gemini JSON-schema constrained output.
      Offline -> deterministic heuristic (see DECISIONS "Offline determinism").
      Signatures bind attributes to the sender name in that segment; quoted
      segments inherit dup_group_id and set inside_quoted.

Every assertion carries span offsets, polarity and (where present) effective
dates. The SPAN-FIDELITY VALIDATOR fuzzy-locates each object value inside its
claimed source span; failures are marked grounded=0 and excluded downstream
(retained for audit).
"""
from __future__ import annotations

import difflib
import re

from . import contracts, genai, textnorm
from .repository import Repository
from .settings import CFG

TEMPLATE_PASS = "T1"
NARRATIVE_PASS = "N1"

# ---------------------------------------------------------------------------
# Label semantics for the template parser
# ---------------------------------------------------------------------------
NAME_LABELS = {
    "claimant": "claimant", "claimantname": "claimant", "clmtname": "claimant",
    "clmtatty": "attorney", "attorney": "attorney", "counsel": "attorney",
    "attyname": "attorney", "provider": "medical_provider",
    "treatingphysician": "medical_provider", "dr": "medical_provider",
    "providernm": "medical_provider",
}
ATTR_LABELS = {
    "phone": "has_phone", "ph": "has_phone", "tel": "has_phone", "contact": "has_phone",
    "email": "has_email", "mail": "has_email", "dob": "has_dob", "birthdate": "has_dob",
    "dateofbirth": "has_dob", "address": "has_address", "addr": "has_address",
    "mailingaddress": "has_address", "npi": "has_npi", "npinum": "has_npi",
    "tin": "has_tin", "taxid": "has_tin", "tinnum": "has_tin",
}
LABEL_LINE_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 ._#/&-]{0,40}?)\s*[:=]\s?(?P<val>.*)$")
LABEL_DASH_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 ._#/&]{0,40}?)\s+-\s?(?P<val>.*)$")


def _norm_label(lab: str) -> str:
    return re.sub(r"[^a-z]", "", lab.lower())


_SHOP_WORDS = ("auto body", "collision", "automotive", "car care", "body works", "repair")
_PROV_WORDS = ("orthopedic", "physical therapy", "imaging", "medical group",
               "chiropractic", "neurology", "dr.")


def refine_org_class(surface: str, default: str) -> str:
    """Disambiguate org mentions surfaced under a generic 'provider' label."""
    low = surface.lower()
    if any(w in low for w in _SHOP_WORDS):
        return "repair_shop"
    if any(w in low for w in _PROV_WORDS):
        return "medical_provider"
    return default


def _is_placeholder(val: str) -> bool:
    v = val.strip().lower()
    return (not v) or v in CFG.PLACEHOLDER_BLOCKLIST or bool(re.fullmatch(r"[x_\-]+", v))


def _validate(attr: str, val: str) -> bool:
    v = val.strip()
    if attr == "has_phone":
        return bool(textnorm.PHONE_RE.search(v))
    if attr == "has_email":
        return bool(textnorm.EMAIL_RE.search(v))
    if attr == "has_npi":
        m = textnorm.NPI_RE.search(v)
        return bool(m) and textnorm.npi_is_valid(m.group(0))
    if attr == "has_tin":
        return bool(textnorm.TIN_RE.search(v))
    if attr == "has_dob":
        return bool(re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", v))
    if attr == "has_address":
        return bool(re.search(r"\d+\s+\w+", v))
    return bool(v)


# ---------------------------------------------------------------------------
# Span-fidelity validator
# ---------------------------------------------------------------------------
def span_grounded(raw_text: str, span_start: int, span_end: int, value: str) -> int:
    """1 if `value` fuzzy-locates within the claimed span (with small slack)."""
    if not value:
        return 0
    lo = max(0, span_start - 5)
    hi = min(len(raw_text), span_end + 5)
    window = raw_text[lo:hi].lower()
    v = value.strip().lower()
    if not v:
        return 0
    if v in window:
        return 1
    # sliding fuzzy match
    n = len(v)
    best = 0.0
    for i in range(0, max(1, len(window) - n + 1)):
        best = max(best, difflib.SequenceMatcher(None, v, window[i:i + n]).ratio())
        if best >= CFG.SPAN_FIDELITY_MIN_RATIO:
            return 1
    return 1 if best >= CFG.SPAN_FIDELITY_MIN_RATIO else 0


# ---------------------------------------------------------------------------
# Template parser
# ---------------------------------------------------------------------------
def parse_template_block(doc_id: str, raw_text: str, seg: dict, id_gen) -> tuple[list[dict], list[dict]]:
    """Return (mention_rows, assertion_rows) for a template_block segment."""
    block = raw_text[seg["char_start"]:seg["char_end"]]
    mentions, assertions = [], []
    current_subject = None          # mention_id
    current_subject_class = None
    last_attr_value: dict[str, str] = {}

    line_pos = seg["char_start"]
    for line in block.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        m = LABEL_LINE_RE.match(stripped) or LABEL_DASH_RE.match(stripped)
        if not m:
            line_pos += len(line)
            continue
        label = _norm_label(m.group("label"))
        val = m.group("val").strip()
        val_off = line_pos + m.start("val")

        if label in NAME_LABELS and val and not _is_placeholder(val):
            klass = refine_org_class(val, NAME_LABELS[label])
            mid = id_gen("m")
            mentions.append(contracts.Mention(
                mention_id=mid, doc_id=doc_id, segment_id=seg["segment_id"],
                entity_class=klass, surface=val, norm_surface=textnorm.normalize_name(val),
                char_start=val_off, char_end=val_off + len(val),
                extractor="template", dup_group_id=seg.get("dup_group_id"),
                inside_quoted=0,
            ).__dict__)
            assertions.append(_mk_assertion(id_gen, mid, "has_name", val, val,
                                             doc_id, val_off, val_off + len(val),
                                             "asserted", "template", TEMPLATE_PASS, raw_text))
            current_subject, current_subject_class = mid, klass
            last_attr_value = {}
        elif label in ATTR_LABELS and current_subject is not None:
            attr = ATTR_LABELS[label]
            raw_val = val
            resolved = val
            if raw_val.strip().lower() in ("same as above", "same"):
                if attr in last_attr_value:
                    resolved = last_attr_value[attr]
                else:
                    line_pos += len(line)
                    continue
            if _is_placeholder(raw_val) and raw_val.strip().lower() not in ("same as above", "same"):
                line_pos += len(line)
                continue
            if not _validate(attr, resolved):
                line_pos += len(line)
                continue
            last_attr_value[attr] = resolved
            assertions.append(_mk_assertion(
                id_gen, current_subject, attr, raw_val,
                textnorm.normalize_identifier(_attr_kind(attr), resolved),
                doc_id, val_off, val_off + len(val), "asserted",
                "template", TEMPLATE_PASS, raw_text))
        line_pos += len(line)
    return mentions, assertions


def _attr_kind(attr: str) -> str:
    return {"has_phone": "phone", "has_email": "email", "has_npi": "npi",
            "has_tin": "tin", "has_ssn": "ssn"}.get(attr, "text")


def _mk_assertion(id_gen, subj, predicate, raw, norm, doc_id, s, e, polarity,
                  extractor, pass_id, raw_text, obj_mention=None, eff_from=None,
                  eff_to=None, temporal_conf=None, confidence=1.0) -> dict:
    grounded = span_grounded(raw_text, s, e, raw if raw else norm)
    return contracts.Assertion(
        assertion_id=id_gen("a"), subject_mention_id=subj, predicate=predicate,
        object_value_raw=raw, object_value_norm=norm, object_mention_id=obj_mention,
        polarity=polarity, source_doc_id=doc_id, source_span_start=s, source_span_end=e,
        extractor=extractor, pass_id=pass_id, effective_from=eff_from, effective_to=eff_to,
        temporal_conf=temporal_conf, grounded=grounded, confidence=confidence,
    ).__dict__


# ---------------------------------------------------------------------------
# Heuristic (offline) narrative/email extractor
# ---------------------------------------------------------------------------
NAME_TOKEN = r"[A-Z][a-zA-Z'’\-]+"
PERSON_RE = re.compile(rf"(?:Dr\.\s+)?{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{0,2}}(?:\s+(?:Jr|Sr|II|III))?")
FLIP_RE = re.compile(rf"({NAME_TOKEN}),\s+({NAME_TOKEN})")
NEG_CUES = ("denies", "denied", "no ", "not ", "without")
ALLEGE_CUES = ("suspect", "alleg", "claims to", "purport")
REPORT_CUES = ("reported", "per records", "states", "advised", "per report")
RETRACT_CUES = ("wrong", "correct is", "correction", "prior note listed")
STOP_NAMES = {"Claim", "Please", "Following", "Per", "Client", "Direct", "From",
              "Sent", "Subject", "Records", "Desk", "Re", "See", "Kindly", "We",
              "Confidentiality", "Notice", "Law", "Group", "Offices", "Legal",
              "Trial", "Injury", "Partners", "Attorneys", "Department", "Claims",
              "Mon", "Tue", "Wed", "Thu", "Fri", "Jan", "Feb", "Mar", "Apr",
              "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Status",
              "Attaching", "Client", "Provider", "Physician", "Available"}
# tokens that are organizational/boilerplate fragments, not person-name tokens
_FRAGMENT_TOKENS = STOP_NAMES | {"LLP", "PLLC", "Inc", "LLC", "Vance", "Harbor"}


def _polarity_for(context: str) -> str:
    low = context.lower()
    if any(c in low for c in RETRACT_CUES):
        return "retracted"
    if any(c in low for c in ALLEGE_CUES):
        return "alleged"
    if any(c in low for c in NEG_CUES):
        return "negated"
    if any(c in low for c in REPORT_CUES):
        return "reported"
    return "asserted"


_ATTORNEY_CUES = ("atty", "attorney", "counsel", "esq", "law group", "law offices",
                  "llp", "legal", "trial group", "injury attorneys", "legal partners")
_ADJUSTER_DOMAINS = ("@ourinsco.com",)


def _infer_class(context: str, surface: str) -> str:
    """Infer entity class from the local context window (both sides of the name)."""
    low = context.lower()
    if surface.startswith("Dr.") or "physician" in low or "provider" in low or "npi" in low:
        return "medical_provider"
    if any(d in low for d in _ADJUSTER_DOMAINS) or "claims department" in low or "adjuster" in low:
        return "adjuster"
    if any(c in low for c in _ATTORNEY_CUES):
        return "attorney"
    # a non-insurer email domain appearing right by the name -> external counsel
    import re as _re
    for m in _re.finditer(r"@([a-z0-9.\-]+)", low):
        dom = m.group(1)
        if dom not in ("ourinsco.com", "example.com"):
            return "attorney"
    return "claimant"


def heuristic_extract_segment(doc_id: str, raw_text: str, seg: dict, id_gen) -> tuple[list[dict], list[dict]]:
    base = seg["char_start"]
    seg_text = raw_text[base:seg["char_end"]]
    inside_quoted = 1 if seg["kind"] == "email_quoted" else 0
    mentions, assertions = [], []

    # ---- entity mentions (persons / orgs) ----
    name_spans = []
    for m in FLIP_RE.finditer(seg_text):
        surface = m.group(0)
        name_spans.append((m.start(), m.end(), surface))
    for m in PERSON_RE.finditer(seg_text):
        surface = m.group(0)
        toks = surface.replace("Dr.", "").split()
        first = toks[0] if toks else surface
        if first in STOP_NAMES:
            continue
        if len(surface.split()) < 2 and not surface.startswith("Dr."):
            continue
        # skip surfaces that are entirely org/boilerplate fragments (not a person)
        alpha = [t for t in toks if t.isalpha()]
        if alpha and all(t in _FRAGMENT_TOKENS for t in alpha) and not surface.startswith("Dr."):
            continue
        # skip if overlapping an already-added flip name
        if any(s <= m.start() < e for s, e, _ in name_spans):
            continue
        name_spans.append((m.start(), m.end(), surface))

    name_spans.sort()
    first_mention_id = None
    for (s, e, surface) in name_spans:
        ctx = seg_text[max(0, s - 40):min(len(seg_text), e + 90)]
        klass = refine_org_class(surface, _infer_class(ctx, surface))
        mid = id_gen("m")
        first_mention_id = first_mention_id or mid
        mentions.append(contracts.Mention(
            mention_id=mid, doc_id=doc_id, segment_id=seg["segment_id"],
            entity_class=klass, surface=surface,
            norm_surface=textnorm.normalize_name(surface),
            char_start=base + s, char_end=base + e, extractor="genai",
            dup_group_id=seg.get("dup_group_id"), inside_quoted=inside_quoted,
        ).__dict__)
        pol = _polarity_for(seg_text[max(0, s - 30):min(len(seg_text), e + 30)])
        assertions.append(_mk_assertion(id_gen, mid, "has_name", surface, surface,
                                         doc_id, base + s, base + e, pol,
                                         "genai", NARRATIVE_PASS, raw_text,
                                         confidence=0.7))

    # subject for attribute binding: nearest preceding name mention
    def subject_for(pos: int) -> str | None:
        cand = [(mn["char_start"], mn["mention_id"]) for mn in mentions if mn["char_start"] <= base + pos]
        return max(cand)[1] if cand else first_mention_id

    # ---- identifiers -> attribute assertions ----
    id_patterns = [
        ("has_email", textnorm.EMAIL_RE, "email"),
        ("has_phone", textnorm.PHONE_RE, "phone"),
        ("has_npi", textnorm.NPI_RE, "npi"),
        ("has_tin", textnorm.TIN_RE, "tin"),
        ("has_ssn", textnorm.SSN_RE, "ssn"),
    ]
    for attr, pat, kind in id_patterns:
        for m in pat.finditer(seg_text):
            val = m.group(0)
            if attr == "has_npi" and not textnorm.npi_is_valid(val):
                continue
            subj = subject_for(m.start())
            if subj is None:
                continue
            pol = _polarity_for(seg_text[max(0, m.start() - 30):m.end() + 10])
            assertions.append(_mk_assertion(
                id_gen, subj, attr, val, textnorm.normalize_identifier(kind, val),
                doc_id, base + m.start(), base + m.end(), pol, "genai",
                NARRATIVE_PASS, raw_text, confidence=0.8))

    # ---- DOB (with retraction handling) ----
    for m in re.finditer(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", seg_text):
        subj = subject_for(m.start())
        if subj is None:
            continue
        pol = _polarity_for(seg_text[max(0, m.start() - 40):m.end() + 5])
        assertions.append(_mk_assertion(
            id_gen, subj, "has_dob", m.group(0), m.group(0),
            doc_id, base + m.start(), base + m.end(), pol, "genai",
            NARRATIVE_PASS, raw_text, confidence=0.7))

    # ---- allegation free-text ----
    for m in re.finditer(r"(suspect[^.;\n]*|alleg[^.;\n]*)", seg_text, re.I):
        subj = subject_for(m.start())
        if subj is None:
            continue
        assertions.append(_mk_assertion(
            id_gen, subj, "allegation", m.group(0).strip(), m.group(0).strip().lower(),
            doc_id, base + m.start(), base + m.end(), "alleged", "genai",
            NARRATIVE_PASS, raw_text, confidence=0.6))

    return mentions, assertions


# ---------------------------------------------------------------------------
# Gemini (online) narrative/email extractor
# ---------------------------------------------------------------------------
def _genai_job(doc_id: str, raw_text: str, seg: dict) -> dict:
    """Build a batchable genai job {prompt, offline_handler} for one segment."""
    base = seg["char_start"]
    seg_text = raw_text[base:seg["char_end"]]
    prompt = (
        "You are extracting entity assertions from a single segment of a legacy "
        "insurance claim note. Return assertions with evidence spans measured as "
        "character offsets WITHIN the segment text provided below. Classes: "
        f"{list(contracts.ENTITY_CLASSES)}. Predicates: {list(contracts.PREDICATES)}. "
        f"Polarities: {list(contracts.POLARITIES)}. Only extract what is present.\n\n"
        f"SEGMENT (kind={seg['kind']}):\n<<<\n{seg_text}\n>>>"
    )

    def offline():  # deterministic fallback reuses the heuristic, shaped to schema
        mts, asrt = heuristic_extract_segment(doc_id, raw_text, seg, _NoopIdGen())
        items = []
        for a in asrt:
            items.append({
                "entity_surface": a["object_value_raw"] if a["predicate"] == "has_name" else "",
                "entity_class": "claimant", "predicate": a["predicate"],
                "object_value": a["object_value_raw"], "polarity": a["polarity"],
                "evidence_span_start": a["source_span_start"] - base,
                "evidence_span_end": a["source_span_end"] - base,
                "confidence": a["confidence"] or 0.7,
            })
        return {"assertions": items}

    return {"prompt": prompt, "offline_handler": offline}


class _NoopIdGen:
    def __call__(self, prefix):
        return "tmp"


def _materialize_genai(doc_id, raw_text, seg, base, data, id_gen):
    mentions, assertions = [], []
    inside_quoted = 1 if seg["kind"] == "email_quoted" else 0
    surf_to_mid: dict[tuple, str] = {}
    for a in data.get("assertions", []):
        s = base + int(a.get("evidence_span_start", 0))
        e = base + int(a.get("evidence_span_end", 0))
        s, e = max(seg["char_start"], s), min(seg["char_end"], max(s + 1, e))
        surface = a.get("entity_surface") or ""
        klass = a.get("entity_class", "claimant")
        key = (surface, klass)
        if surface and key not in surf_to_mid:
            mid = id_gen("m")
            surf_to_mid[key] = mid
            mentions.append(contracts.Mention(
                mention_id=mid, doc_id=doc_id, segment_id=seg["segment_id"],
                entity_class=klass, surface=surface,
                norm_surface=textnorm.normalize_name(surface),
                char_start=s, char_end=e, extractor="genai",
                dup_group_id=seg.get("dup_group_id"), inside_quoted=inside_quoted,
            ).__dict__)
        subj = surf_to_mid.get(key)
        if subj is None:
            continue
        assertions.append(_mk_assertion(
            id_gen, subj, a.get("predicate", "has_name"),
            a.get("object_value", surface), a.get("object_value", surface),
            doc_id, s, e, a.get("polarity", "asserted"), "genai",
            NARRATIVE_PASS, raw_text, eff_from=a.get("effective_from"),
            eff_to=a.get("effective_to"), temporal_conf=a.get("temporal_conf"),
            confidence=a.get("confidence", 0.7)))
    return mentions, assertions


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(repo: Repository) -> dict:
    from .settings import genai_mode
    segs = repo.table("segments")
    docs = {r["doc_id"]: None for _, r in segs.iterrows()}
    from .settings import Paths
    texts = {f.stem: f.read_text() for f in Paths.raw_notes.glob("*.txt")}

    counter = {"m": 0, "a": 0}

    def id_gen(prefix):
        counter[prefix] += 1
        return f"{prefix}{counter[prefix]:07d}"

    all_mentions, all_assertions, ledger = [], [], []
    online = genai_mode() == "online"

    # Pass 1: deterministic template parse now; collect genai segments (in order).
    genai_segs = []   # (doc_id, raw, seg)
    for doc_id, g in segs.groupby("doc_id"):
        raw = texts[doc_id]
        for _, seg in g.sort_values("char_start").iterrows():
            seg = seg.to_dict()
            if seg["kind"] == "template_block":
                mts, asr = parse_template_block(doc_id, raw, seg, id_gen)
                all_mentions.extend(mts)
                all_assertions.extend(asr)
                ledger.append(contracts.ScanSpan(doc_id, seg["char_start"], seg["char_end"],
                                                 "template", TEMPLATE_PASS).__dict__)
            else:
                genai_segs.append((doc_id, raw, seg))
                ledger.append(contracts.ScanSpan(doc_id, seg["char_start"], seg["char_end"],
                                                 "genai", NARRATIVE_PASS).__dict__)

    # Pass 2: genai segments. Online -> BATCHED (parallel + cached) Gemini calls;
    # offline -> direct deterministic heuristic (richer than the schema round-trip).
    if online:
        jobs = [_genai_job(d, r, s) for (d, r, s) in genai_segs]
        datas = genai.generate_json_batch(jobs, contracts.extraction_schema(), task="extraction")
        for (d, r, s), data in zip(genai_segs, datas):
            mts, asr = _materialize_genai(d, r, s, s["char_start"], data, id_gen)
            all_mentions.extend(mts)
            all_assertions.extend(asr)
    else:
        for (d, r, s) in genai_segs:
            mts, asr = heuristic_extract_segment(d, r, s, id_gen)
            all_mentions.extend(mts)
            all_assertions.extend(asr)

    repo.add_mentions(all_mentions)
    repo.add_assertions(all_assertions)
    repo.add_scan_spans(ledger)

    n_grounded = sum(1 for a in all_assertions if a["grounded"] == 1)
    return {
        "n_mentions": len(all_mentions),
        "n_assertions": len(all_assertions),
        "n_grounded": n_grounded,
        "n_ungrounded": len(all_assertions) - n_grounded,
        "n_ledger_spans": len(ledger),
        "mode": "online" if online else "offline",
    }
