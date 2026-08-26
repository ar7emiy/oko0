"""Notebook 02 engine: segmentation, template fingerprinting, near-dup detection.

- Ingest raw notes into the documents table (claim_id + category derived FROM
  TEXT only -- never from the manifest, so the leakage guard stays clean).
- Segment each note into contiguous, fully-tiling spans with char offsets:
  template_block | narrative | email_header | email_body | email_signature |
  email_quoted | boilerplate.
- Template fingerprint = hash of the label sequence in a template_block.
- Near-duplicate detection via MinHash over 5-word shingles -> dup_group_id,
  earliest copy flagged canonical.
"""
from __future__ import annotations

import hashlib
import re

from datasketch import MinHash, MinHashLSH

from .repository import Repository
from .settings import CFG, Paths

CLAIM_RE = re.compile(r"\bCLM\d{4}\b")
CATEGORY_HEADER_RE = re.compile(r"^\[([A-Z_]+)\]")
LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ._#/&-]{0,40})\s*[:=]\s|^\s*([A-Za-z][A-Za-z0-9 ._#/&]{0,40})\s+-\s")
EMAIL_HEADER_RE = re.compile(r"^\s*(From|Sent|To|Cc|Bcc|Subject|Date)\s*:", re.I)
QUOTE_RE = re.compile(r"^\s*>+")
SIG_MARK_RE = re.compile(r"^\s*--\s*$")
BOILER_RE = re.compile(r"CONFIDENTIALITY NOTICE|intended recipient|privileged", re.I)

CATEGORY_KEYWORDS = {
    "medical_management": ["tx", "treatment", "records", "physician", "provider", "npi", "surgery"],
    "legal_litigation": ["demand", "counsel", "attorney", "litigation", "suit", "deposition"],
    "siu_investigation": ["suspect", "siu", "fraud", "investigat", "inflating"],
    "repair_estimate": ["repair", "parts", "estimate", "shop", "collision", "body"],
    "payment": ["payment", "paid", "check", "issued", "reserve"],
    "subrogation": ["subro", "subrogation", "recovery", "lien"],
    "plan_of_action": ["poa", "plan of action", "spoke w", "follow up", "next call"],
    "general_correspondence": ["correspondence", "email", "letter"],
}


def ingest_documents(repo: Repository) -> int:
    rows = []
    for f in sorted(Paths.raw_notes.glob("*.txt")):
        text = f.read_text()
        doc_id = f.stem
        m = CLAIM_RE.search(text)
        claim_id = m.group(0) if m else "UNKNOWN"
        stored = ""
        mh = CATEGORY_HEADER_RE.match(text)
        if mh:
            stored = mh.group(1).lower()
        rows.append({
            "doc_id": doc_id, "claim_id": claim_id,
            "category": stored or None,
            "category_implied": classify_category(text),
            "n_chars": len(text), "seq_in_claim": None, "created_ts": None,
        })
    repo.add_documents(rows)
    return len(rows)


def classify_category(text: str) -> str:
    low = text.lower()
    best, best_score = "general_correspondence", 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = sum(low.count(k) for k in kws)
        if score > best_score:
            best, best_score = cat, score
    return best


# ---------------------------------------------------------------------------
# Segmentation (line-based, fully tiling)
# ---------------------------------------------------------------------------
def _line_spans(text: str):
    """Yield (start, end, line_text_including_newline)."""
    pos = 0
    for line in text.splitlines(keepends=True):
        yield pos, pos + len(line), line
        pos += len(line)


def _classify_line(line: str, in_sig: bool) -> str:
    s = line.rstrip("\n")
    if QUOTE_RE.match(s):
        return "email_quoted"
    if BOILER_RE.search(s):
        return "boilerplate"
    if EMAIL_HEADER_RE.match(s):
        return "email_header"
    if SIG_MARK_RE.match(s):
        return "email_signature"
    if in_sig:
        return "email_signature"
    if LABEL_RE.match(s) and (":" in s or "=" in s or " - " in s):
        return "template_block"
    return "narrative"


def segment_document(text: str) -> list[dict]:
    """Return contiguous segments tiling the whole document."""
    segs: list[dict] = []
    cur_kind = None
    cur_start = 0
    cur_end = 0
    in_sig = False
    for start, end, line in _line_spans(text):
        if SIG_MARK_RE.match(line.rstrip("\n")):
            in_sig = True
        kind = _classify_line(line, in_sig)
        # email_body: narrative lines that sit between a header and a signature
        if kind == cur_kind:
            cur_end = end
        else:
            if cur_kind is not None:
                segs.append({"kind": cur_kind, "char_start": cur_start, "char_end": cur_end})
            cur_kind, cur_start, cur_end = kind, start, end
    if cur_kind is not None:
        segs.append({"kind": cur_kind, "char_start": cur_start, "char_end": cur_end})

    # Promote narrative sitting immediately after an email_header to email_body.
    for i, seg in enumerate(segs):
        if seg["kind"] == "narrative" and i > 0 and segs[i - 1]["kind"] in ("email_header", "email_body"):
            seg["kind"] = "email_body"
    # merge adjacent same-kind after promotion
    merged: list[dict] = []
    for seg in segs:
        if merged and merged[-1]["kind"] == seg["kind"] and merged[-1]["char_end"] == seg["char_start"]:
            merged[-1]["char_end"] = seg["char_end"]
        else:
            merged.append(dict(seg))
    return merged


def template_fingerprint(text: str, seg: dict) -> str | None:
    if seg["kind"] != "template_block":
        return None
    block = text[seg["char_start"]:seg["char_end"]]
    labels = []
    for line in block.splitlines():
        m = LABEL_RE.match(line)
        if m:
            lab = (m.group(1) or m.group(2) or "").strip().lower()
            lab = re.sub(r"[^a-z]", "", lab)
            if lab:
                labels.append(lab)
    if len(labels) < CFG.TEMPLATE_MIN_LABELS:
        return None
    return hashlib.sha1(("|".join(labels)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Near-duplicate detection (MinHash over 5-word shingles)
# ---------------------------------------------------------------------------
def _shingles(text: str, w: int):
    toks = re.findall(r"\w+", text.lower())
    if len(toks) < w:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + w]) for i in range(len(toks) - w + 1)}


def _minhash(text: str) -> MinHash:
    m = MinHash(num_perm=CFG.MINHASH_NUM_PERM)
    for sh in _shingles(text, CFG.MINHASH_SHINGLE_WORDS):
        m.update(sh.encode())
    return m


def assign_dup_groups(seg_records: list[dict], texts: dict[str, str]) -> None:
    """Mutates seg_records adding dup_group_id + is_canonical_dup.

    seg_records: list of {segment_id, doc_id, kind, char_start, char_end, order}
    """
    lsh = MinHashLSH(threshold=CFG.MINHASH_JACCARD_THRESHOLD, num_perm=CFG.MINHASH_NUM_PERM)
    mh_by_id = {}
    eligible = []
    for r in seg_records:
        seg_text = texts[r["doc_id"]][r["char_start"]:r["char_end"]]
        toks = re.findall(r"\w+", seg_text)
        if len(toks) < CFG.MINHASH_SHINGLE_WORDS:
            r["dup_group_id"] = r["segment_id"]  # singleton
            r["is_canonical_dup"] = 1
            continue
        m = _minhash(seg_text)
        mh_by_id[r["segment_id"]] = m
        lsh.insert(r["segment_id"], m)
        eligible.append(r)

    # union-find over LSH neighbors
    parent = {r["segment_id"]: r["segment_id"] for r in eligible}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in eligible:
        for nb in lsh.query(mh_by_id[r["segment_id"]]):
            if nb != r["segment_id"]:
                union(r["segment_id"], nb)

    groups: dict[str, list[dict]] = {}
    for r in eligible:
        groups.setdefault(find(r["segment_id"]), []).append(r)
    for _, members in groups.items():
        members.sort(key=lambda r: (r["order"], r["char_start"]))
        gid = members[0]["segment_id"]
        for i, r in enumerate(members):
            r["dup_group_id"] = gid
            r["is_canonical_dup"] = 1 if i == 0 else 0


def run(repo: Repository) -> dict:
    """Full profiling pass -> populates documents + segments tables."""
    n_docs = ingest_documents(repo)
    texts = {f.stem: f.read_text() for f in Paths.raw_notes.glob("*.txt")}

    seg_records = []
    order = 0
    for doc_id in sorted(texts):
        text = texts[doc_id]
        for j, seg in enumerate(segment_document(text)):
            sid = f"{doc_id}_s{j:03d}"
            seg_records.append({
                "segment_id": sid, "doc_id": doc_id, "kind": seg["kind"],
                "char_start": seg["char_start"], "char_end": seg["char_end"],
                "template_fingerprint": template_fingerprint(text, seg),
                "order": order,
            })
            order += 1

    assign_dup_groups(seg_records, texts)

    rows = [{k: r[k] for k in ("segment_id", "doc_id", "kind", "char_start",
                               "char_end", "template_fingerprint", "dup_group_id",
                               "is_canonical_dup")} for r in seg_records]
    repo.add_segments(rows)

    n_fp = len({r["template_fingerprint"] for r in seg_records if r["template_fingerprint"]})
    n_dupgroups = len({r["dup_group_id"] for r in seg_records})
    n_dups = sum(1 for r in seg_records if r.get("is_canonical_dup") == 0)
    return {"n_docs": n_docs, "n_segments": len(seg_records),
            "n_template_fingerprints": n_fp, "n_dup_groups": n_dupgroups,
            "n_noncanonical_dups": n_dups}
