"""Layer 0: segmentation, template fingerprinting, near-duplicate detection.

- Ingest raw notes into the documents table. claim_id / occurrence_id come from
  the source system (filename + the client's occurrence table), never from the
  note body -- a text-derived identity would be inferred evidence masquerading
  as a structural fact.
- Segment each note into contiguous, fully-tiling spans with char offsets. Two
  kinds only: `quoted` (a re-sent chain, so a mention inside it is not a new
  sighting) and `body`. The previous seven-kind vocabulary computed five kinds
  no consumer ever read, using the most fragile rules in the module.
- Each segment additionally carries ADVISORY signals, never gates:
    * `boilerplate_score` -- disclaimer-likeness, scored over a cue bundle
      rather than three literal phrases, so a differently-worded footer is
      still recognised and a misjudgement discounts rather than deletes.
    * `casing_regime` / `case_informative` -- whether capitalization carries
      any signal in this span, so capitalization-dependent detectors can be
      routed around instead of silently returning nonsense.
- Template fingerprint = hash of the label sequence in a form-like segment.
- Near-duplicate detection via MinHash over 5-word shingles -> dup_group_id,
  earliest copy flagged canonical. This is content-based, not rule-based, and
  is the part of this module that generalizes cleanly to real notes.
"""
from __future__ import annotations

import hashlib
import re

from datasketch import MinHash, MinHashLSH

from . import casing
from .repository import Repository
from .settings import CFG, Paths

CATEGORY_HEADER_RE = re.compile(r"^\[([A-Z_]+)\]")
LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ._#/&-]{0,40})\s*[:=]\s|^\s*([A-Za-z][A-Za-z0-9 ._#/&]{0,40})\s+-\s")
QUOTE_RE = re.compile(r"^\s*>+")
# Disclaimer cue vocabulary, scored rather than matched exactly. Still English
# and still a list -- but a miss now costs a lower score, not a deleted name.
_BOILER_CUES = (
    "confidentiality", "intended recipient", "privileged", "unauthorized",
    "disclosure", "dissemination", "if you have received this", "in error",
    "delete this", "notify the sender", "attorney-client", "work product",
    "confidential and may be", "for the sole use",
)

def _doc_index() -> dict:
    """Structural note->claim/occurrence metadata from the source system.

    Not ground truth: a real claim system always knows which file a note was
    filed on. Entity identity is what must be inferred from text.
    """
    import json
    p = Paths.data / "doc_index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def note_files(doc_ids: list[str] | None = None) -> list:
    """The note files to process: all of them, or just the named ones.

    Doc scoping is what makes an incremental ingest possible at all -- every
    stage used to glob the whole corpus, so adding one note meant reprocessing
    every note. See src/ingest.py.
    """
    if doc_ids is None:
        return sorted(Paths.raw_notes.glob("*.txt"))
    want = list(dict.fromkeys(doc_ids))       # de-dup, keep arrival order
    return [Paths.raw_notes / f"{d}.txt" for d in want
            if (Paths.raw_notes / f"{d}.txt").exists()]


def ingest_documents(repo: Repository, doc_ids: list[str] | None = None) -> int:
    idx = _doc_index()
    rows = []
    for f in note_files(doc_ids):
        text = f.read_text(encoding="utf-8")
        doc_id = f.stem
        meta = idx.get(doc_id, {})
        # Structural identity comes from the source system -- the filename
        # ([ClaimNumber]_[NoteID].txt) joined against the client's occurrence
        # table. It is NEVER recovered from the note body: the previous
        # `CLM\d{4}` / `OCC\d{4}` text fallback only ever matched our own
        # synthetic corpus, and on real data would silently mint an identity
        # out of whatever four digits happened to follow those letters.
        claim_id = meta.get("claim_id") or "UNKNOWN"
        occurrence_id = meta.get("occurrence_id")
        stored = ""
        mh = CATEGORY_HEADER_RE.match(text)
        if mh:
            stored = mh.group(1).lower()
        rows.append({
            "doc_id": doc_id, "claim_id": claim_id,
            "occurrence_id": occurrence_id,
            "category": stored or None,
            "category_implied": None,   # see research.corpus_heuristics
            "n_chars": len(text), "seq_in_claim": None, "created_ts": None,
        })
    repo.add_documents(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Segmentation (line-based, fully tiling)
# ---------------------------------------------------------------------------
def _line_spans(text: str):
    """Yield (start, end, line_text_including_newline)."""
    pos = 0
    for line in text.splitlines(keepends=True):
        yield pos, pos + len(line), line
        pos += len(line)


def boilerplate_score(text: str) -> float:
    """0..1 disclaimer-likeness of a block of text.

    Replaces the previous three-literal-phrase whitelist
    (`CONFIDENTIALITY NOTICE` / `intended recipient` / `privileged`), which
    matched our own generator's disclaimer and little else. Real disclaimers
    vary by carrier, firm and jurisdiction, so this scores a bundle of
    features that co-occur in legal footers instead of demanding an exact
    phrase.

    ADVISORY ONLY. Nothing may drop a candidate because this is high; it is a
    feature for ranking. A hard gate here meant one misclassified segment
    silently deleted every real name inside it, with no trace in the output.
    """
    low = (text or "").lower()
    if not low.strip():
        return 0.0
    hits = sum(1 for cue in _BOILER_CUES if cue in low)
    score = min(1.0, hits / 3.0)
    # Legal footers are overwhelmingly lower-case prose with no digits and a
    # long mean sentence; a light shape prior separates them from a narrative
    # that merely mentions "privileged".
    if hits and not any(ch.isdigit() for ch in low):
        score = min(1.0, score + 0.15)
    return round(score, 3)


def _classify_line(line: str) -> str:
    """Quoted-chain line, or ordinary body. Nothing else has a consumer.

    Stateless by design. The previous version carried an `in_sig` latch that
    was set on a bare '--' line and never cleared, so a single stray divider
    retyped the whole remainder of a note as signature.
    """
    return "quoted" if QUOTE_RE.match(line.rstrip("\n")) else "body"


def segment_document(text: str) -> list[dict]:
    """Contiguous segments tiling the whole document.

    Two kinds only ('quoted' | 'body'). Each segment additionally carries an
    advisory `boilerplate_score` and its casing profile, so downstream can
    weigh a disclaimer-ish region or refuse to trust capitalization in an ALL
    CAPS block without either being able to erase a span.
    """
    segs: list[dict] = []
    cur_kind = None
    cur_start = cur_end = 0
    for start, end, line in _line_spans(text):
        kind = _classify_line(line)
        if kind == cur_kind:
            cur_end = end
        else:
            if cur_kind is not None:
                segs.append({"kind": cur_kind, "char_start": cur_start, "char_end": cur_end})
            cur_kind, cur_start, cur_end = kind, start, end
    if cur_kind is not None:
        segs.append({"kind": cur_kind, "char_start": cur_start, "char_end": cur_end})

    for seg in segs:
        block = text[seg["char_start"]:seg["char_end"]]
        seg["boilerplate_score"] = boilerplate_score(block)
        prof = casing.profile(block)
        seg["casing_regime"] = prof.regime
        seg["case_informative"] = 1 if prof.case_informative else 0
    return segs


def template_fingerprint(text: str, seg: dict) -> str | None:
    # Label-sequence hash for any segment that looks form-like. Previously
    # gated on a 'template_block' kind produced by a regex that also fired on
    # ordinary narrative openers ("Update: spoke with counsel").
    if seg["kind"] == "quoted":
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


def assign_dup_groups(seg_records: list[dict], texts: dict[str, str],
                      prior: list[dict] | None = None) -> None:
    """Mutates seg_records adding dup_group_id + is_canonical_dup.

    seg_records: list of {segment_id, doc_id, kind, char_start, char_end, order}

    `prior` is already-stored segments as {segment_id, dup_group_id, text}. They
    are indexed for matching but never re-assigned, which is what lets an
    incrementally ingested note be recognised as quoting a note that arrived
    weeks earlier. Without it, dup detection would only ever see inside the
    current batch, and a one-note batch can contain no duplicates by definition.

    Cost note: the caller has to supply prior text, so this is O(corpus) hashing
    per ingest. That is cheap next to NER and the LLM lane, but it is the one
    part of an incremental ingest that is not O(new notes) -- worth revisiting
    with a stored minhash column if the corpus gets large.
    """
    lsh = MinHashLSH(threshold=CFG.MINHASH_JACCARD_THRESHOLD, num_perm=CFG.MINHASH_NUM_PERM)
    mh_by_id = {}
    eligible = []

    prior_group: dict[str, str] = {}
    for pr in (prior or []):
        toks = re.findall(r"\w+", pr["text"])
        if len(toks) < CFG.MINHASH_SHINGLE_WORDS:
            continue
        key = f"PRIOR::{pr['segment_id']}"
        lsh.insert(key, _minhash(pr["text"]))
        prior_group[key] = pr.get("dup_group_id") or pr["segment_id"]
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

    hit_prior: dict[str, str] = {}      # new segment_id -> existing dup_group_id
    for r in eligible:
        for nb in lsh.query(mh_by_id[r["segment_id"]]):
            if nb == r["segment_id"]:
                continue
            if nb.startswith("PRIOR::"):
                hit_prior.setdefault(r["segment_id"], prior_group[nb])
            else:
                union(r["segment_id"], nb)

    groups: dict[str, list[dict]] = {}
    for r in eligible:
        groups.setdefault(find(r["segment_id"]), []).append(r)
    for _, members in groups.items():
        members.sort(key=lambda r: (r["order"], r["char_start"]))
        # If any member matched a segment that was already stored, the whole
        # group belongs to that older group and none of it is canonical -- the
        # canonical copy is the one that arrived first, which is not in this
        # batch.
        adopted = next((hit_prior[m["segment_id"]] for m in members
                        if m["segment_id"] in hit_prior), None)
        gid = adopted or members[0]["segment_id"]
        for i, r in enumerate(members):
            r["dup_group_id"] = gid
            r["is_canonical_dup"] = 0 if adopted else (1 if i == 0 else 0)


def _prior_segments(repo: Repository, exclude_docs: set) -> list[dict]:
    """Already-stored segments, with their text, for cross-batch dup matching.

    Re-reads the note files because the segment text itself is not stored -- only
    its offsets. Cheap relative to extraction, and the alternative is a stored
    minhash column.
    """
    try:
        segs = repo.table("segments")
    except Exception:
        return []
    if segs.empty:
        return []
    cache: dict[str, str] = {}
    out = []
    for _, r in segs.iterrows():
        doc = r["doc_id"]
        if doc in exclude_docs:
            continue
        if doc not in cache:
            f = Paths.raw_notes / f"{doc}.txt"
            cache[doc] = f.read_text(encoding="utf-8") if f.exists() else ""
        text = cache[doc][int(r["char_start"]):int(r["char_end"])]
        if text:
            out.append({"segment_id": r["segment_id"],
                        "dup_group_id": r["dup_group_id"], "text": text})
    return out


def run(repo: Repository, doc_ids: list[str] | None = None) -> dict:
    """Profiling pass -> populates documents + segments.

    `doc_ids=None` profiles the whole corpus (the backfill path). Passing ids
    profiles only those notes, which is what an arriving note needs.
    """
    if doc_ids is not None:
        # Re-ingesting a note must replace its rows, not collide with them.
        # The whole-corpus path does not need this because backfill resets the
        # database first; the incremental path has no such clean slate.
        # Segments reference documents, so they go first.
        marks = ",".join("?" for _ in doc_ids)
        repo.conn.execute("PRAGMA foreign_keys=OFF")
        repo.conn.execute(f"DELETE FROM segments WHERE doc_id IN ({marks})", doc_ids)
        repo.conn.execute(f"DELETE FROM documents WHERE doc_id IN ({marks})", doc_ids)
        repo.conn.commit()
        repo.conn.execute("PRAGMA foreign_keys=ON")

    n_docs = ingest_documents(repo, doc_ids)
    texts = {f.stem: f.read_text(encoding="utf-8") for f in note_files(doc_ids)}

    # Incremental ingest compares against what is already stored, so a note that
    # quotes an older note is still recognised as a duplicate of it.
    prior = None
    if doc_ids is not None:
        prior = _prior_segments(repo, exclude_docs=set(texts))

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
                "boilerplate_score": seg["boilerplate_score"],
                "casing_regime": seg["casing_regime"],
                "case_informative": seg["case_informative"],
                "order": order,
            })
            order += 1

    assign_dup_groups(seg_records, texts, prior=prior)

    rows = [{k: r[k] for k in ("segment_id", "doc_id", "kind", "char_start",
                               "char_end", "template_fingerprint", "dup_group_id",
                               "is_canonical_dup", "boilerplate_score",
                               "casing_regime", "case_informative")} for r in seg_records]
    repo.add_segments(rows)

    n_fp = len({r["template_fingerprint"] for r in seg_records if r["template_fingerprint"]})
    n_dupgroups = len({r["dup_group_id"] for r in seg_records})
    n_dups = sum(1 for r in seg_records if r.get("is_canonical_dup") == 0)
    n_case_blind = sum(1 for r in seg_records if r["case_informative"] == 0)
    n_boiler = sum(1 for r in seg_records if r["boilerplate_score"] >= 0.5)
    return {"n_docs": n_docs, "n_segments": len(seg_records),
            "n_case_blind_segments": n_case_blind,
            "n_likely_boilerplate_segments": n_boiler,
            "n_template_fingerprints": n_fp, "n_dup_groups": n_dupgroups,
            "n_noncanonical_dups": n_dups}
