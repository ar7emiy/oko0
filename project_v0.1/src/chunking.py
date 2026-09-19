"""Layer 1a: overlapping chunking with absolute char-offset preservation.

Aggressive overlap chunking (CHUNK_TOKENS with CHUNK_OVERLAP_RATIO sliding
window) so every sentence is read at least twice across chunk boundaries --
this is the mitigation for chunk-boundary truncation, one of the named causes of
missed entities.

INVARIANT: every chunk records its absolute `char_start` in the source document,
so any span an extractor reports inside a chunk maps back to a true raw-document
offset. This is what keeps span-grounding (and the audit's span-level recall)
valid after chunking.

Token counting: no tiktoken dependency in this environment, so tokens are
approximated as words * TOKENS_PER_WORD (documented in config). The chunker
splits on word boundaries, never mid-word, so offsets stay exact regardless of
how tokens are estimated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .settings import CFG


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    claim_id: str
    text: str
    char_start: int          # absolute offset in the raw document
    char_end: int
    index: int               # ordinal within the document
    n_words: int
    est_tokens: float

    def to_meta(self) -> dict:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "claim_id": self.claim_id, "char_start": self.char_start,
                "char_end": self.char_end, "index": self.index}


_WORD_RE = re.compile(r"\S+")


def words_per_chunk() -> int:
    """Target words per chunk given the token budget and tokens-per-word ratio."""
    return max(1, int(CFG.CHUNK_TOKENS / CFG.TOKENS_PER_WORD))


def chunk_document(doc_id: str, claim_id: str, text: str) -> list[Chunk]:
    """Split `text` into overlapping chunks carrying absolute char offsets.

    Guarantees:
      - chunks are ordered and cover the whole document (union of spans == doc)
      - no chunk splits a word
      - consecutive chunks overlap by ~CHUNK_OVERLAP_RATIO of the window
    """
    spans = [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    if not spans:
        return [Chunk(f"{doc_id}_c000", doc_id, claim_id, text, 0, len(text), 0, 0, 0.0)]

    win = words_per_chunk()
    step = max(1, int(win * (1.0 - CFG.CHUNK_OVERLAP_RATIO)))

    chunks: list[Chunk] = []
    i = 0
    idx = 0
    n = len(spans)
    while i < n:
        j = min(i + win, n)
        # extend the final chunk to the end of the document so coverage is total
        start_char = spans[i][0] if idx > 0 else 0
        end_char = spans[j - 1][1] if j < n else len(text)
        if idx > 0 and chunks:
            # keep contiguity of the covered union: start no later than prev end
            start_char = min(start_char, chunks[-1].char_end)
        seg = text[start_char:end_char]
        nw = j - i
        chunks.append(Chunk(
            chunk_id=f"{doc_id}_c{idx:03d}", doc_id=doc_id, claim_id=claim_id,
            text=seg, char_start=start_char, char_end=end_char, index=idx,
            n_words=nw, est_tokens=round(nw * CFG.TOKENS_PER_WORD, 1),
        ))
        idx += 1
        if j >= n:
            break
        i += step
    return chunks


def chunk_corpus(docs: dict[str, tuple[str, str]]) -> list[Chunk]:
    """docs: {doc_id: (claim_id, text)} -> flat list of chunks."""
    out: list[Chunk] = []
    for doc_id in sorted(docs):
        claim_id, text = docs[doc_id]
        out.extend(chunk_document(doc_id, claim_id, text))
    return out


def coverage_report(text: str, chunks: list[Chunk]) -> dict:
    """Verify the chunk set fully covers the document and measure re-read depth."""
    n = len(text)
    depth = [0] * n
    for c in chunks:
        for k in range(max(0, c.char_start), min(c.char_end, n)):
            depth[k] += 1
    covered = sum(1 for d in depth if d >= 1)
    reread = sum(1 for d in depth if d >= 2)
    return {
        "n_chars": n,
        "coverage": covered / n if n else 1.0,
        "reread_fraction": reread / n if n else 0.0,
        "max_depth": max(depth) if depth else 0,
        "n_chunks": len(chunks),
    }
