"""Layer 1d: token-level NER ensemble (the UNION strategy).

The premise: a single LLM pass misses entities through attention drift and
positional bias -- it filters out low-salience details (a paralegal named once,
a footer clinic, a lone diagnostic code). So we run independent extractors over
every chunk and take their UNION, tracking which extractor found each span:

  1. token_ner   -- span-level scanner that reads every literal token.
                    `GlinerBackend` (real, zero-shot GLiNER) when available;
                    `DeterministicTokenNER` otherwise. Recall-first.
  2. gazetteer   -- deterministic regex/checksum for structured codes.
  3. llm         -- semantic extraction (Gemini structured output), which
                    contributes context, entity descriptions and relationships
                    that token-level models cannot infer.

Union semantics: overlapping spans are merged (longest span wins) and their
provenance sets are unioned, so every surviving span records exactly which
extractors saw it. That provenance is what makes the recall ablation possible.

Anaphora (pronouns / vague descriptors) are NEVER emitted as entities; they are
routed to coref instead.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from . import contracts, coref, gazetteers, genai, textnorm
from .settings import CFG


@dataclass
class SpanCandidate:
    start: int                       # absolute document offset
    end: int
    text: str
    label: str
    extractors: set = field(default_factory=set)   # provenance: which found it
    score: float = 0.0
    description: str = ""             # LLM-authored context (Layer 2 uses this)
    chunk_ids: set = field(default_factory=set)

    def key(self):
        return (self.start, self.end)


# ---------------------------------------------------------------------------
# Token-level NER backends
# ---------------------------------------------------------------------------
class TokenNERBackend(ABC):
    """Span-level NER over raw text.

    Contract: `extract(text, base_offset)` returns SpanCandidates with ABSOLUTE
    document offsets (caller passes the chunk's char_start as base_offset).

    To swap in GLiNER/spaCy/a fine-tuned tagger, implement this one method; the
    ensemble, sweep, ER and graph layers are unchanged.
    """

    name = "abstract"

    @abstractmethod
    def extract(self, text: str, base_offset: int = 0) -> list[SpanCandidate]: ...


class GlinerBackend(TokenNERBackend):
    """Zero-shot GLiNER adapter (production path).

    Activates only when `gliner` is installed AND its weights are reachable.
    GLiNER scans every token, so it rarely misses a literal name/number span --
    exactly the safety net the LLM lacks.
    """

    name = "gliner"

    def __init__(self, model_name: str | None = None, threshold: float | None = None):
        from gliner import GLiNER  # noqa: F401 (ImportError -> caller falls back)
        self._model = GLiNER.from_pretrained(model_name or CFG.GLINER_MODEL)
        self._threshold = threshold if threshold is not None else CFG.GLINER_THRESHOLD
        self._labels = list(CFG.NER_LABELS)

    def extract(self, text: str, base_offset: int = 0) -> list[SpanCandidate]:
        ents = self._model.predict_entities(text, self._labels, threshold=self._threshold)
        out = []
        for e in ents:
            if coref.is_anaphor(e["text"]):
                continue
            out.append(SpanCandidate(
                start=base_offset + e["start"], end=base_offset + e["end"],
                text=e["text"], label=e["label"], extractors={self.name},
                score=float(e.get("score", 0.0)),
            ))
        return out


class DeterministicTokenNER(TokenNERBackend):
    """Deterministic high-recall span scanner (offline stand-in for GLiNER).

    Plays the same architectural role: it reads every literal token and emits
    name-shaped spans regardless of salience, so entities the LLM's attention
    skips are still caught. Recall-first by design -- precision is recovered by
    entity resolution and the verification sweep, not here.

    Detects: capitalized name sequences (incl. `Dr.` titles and Jr/Sr suffixes),
    `Last, First` order flips, and organization names ending in a known suffix.
    """

    name = "token_ner"

    # NOTE: these use [ \t] rather than \s so a name span can NEVER cross a
    # newline. In legacy notes a name is routinely followed on the next line by a
    # firm or a label ("Hassan Williams\nWhitfield Trial Group"); a \s-based
    # pattern swallows both into one span, which corrupts the surface, breaks
    # entity resolution, and gets the mention dropped by the name-shape filter.
    _NAME_TOK = r"[A-Z][a-zA-Z'’\-]+"
    _SP = r"[ \t]+"
    _RE_TITLED = re.compile(rf"\bDr\.?{_SP}{_NAME_TOK}(?:{_SP}{_NAME_TOK}){{0,2}}")
    _RE_FLIP = re.compile(rf"\b({_NAME_TOK}),{_SP}({_NAME_TOK})(?:{_SP}(Jr|Sr|II|III))?")
    _RE_SEQ = re.compile(
        rf"\b{_NAME_TOK}(?:{_SP}{_NAME_TOK}){{1,3}}(?:{_SP}(?:Jr|Sr|II|III))?\b")
    _RE_INITIAL = re.compile(rf"\b[A-Z]\.{_SP}{_NAME_TOK}\b")

    # Verbs/adverbs that open a sentence get capitalized, so a greedy
    # capitalized-sequence match swallows them into the following name
    # ("Contacted James Moore"). They are trimmed from the START of a span
    # rather than rejecting it, so the real name survives.
    _LEADING_NOISE = {
        "Contacted", "Spoke", "Reached", "Called", "Received", "Sent", "Left",
        "Confirmed", "Advised", "Requested", "Reviewed", "Discussed", "Emailed",
        "Followed", "Following", "Per", "Attached", "Forwarded", "Submitted",
        "Completed", "Performed", "Issued", "Filed", "Provider", "Counsel",
        "Treatment", "Status", "Financial", "Investigation", "Correspondence",
        "Mailing", "Billing", "Coverage", "Note", "File", "Diary", "Reserves",
        "Expense", "Nothing", "Awaiting", "Documentation", "No", "Will",
    }

    # tokens that are structural noise in legacy notes, never a name on their own
    _STOP = {
        "Claim", "Claimant", "Clmt", "Atty", "Attorney", "Counsel", "Provider",
        "Physician", "Email", "Phone", "Address", "Mailing", "Contact", "Birthdate",
        "From", "Sent", "To", "Subject", "Direct", "Date", "Of", "Birth", "Please",
        "Following", "Per", "Client", "Records", "Desk", "Re", "See", "Kindly", "We",
        "Confidentiality", "Notice", "This", "If", "You", "The", "Status", "Available",
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Jan", "Feb", "Mar", "Apr",
        "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Law", "Group",
        "Department", "Claims", "Notify", "Sender", "Delete", "Message", "Intended",
        "Recipient", "Sole", "Use", "Attachments", "POA", "NPI", "TIN", "DOB",
    }

    def extract(self, text: str, base_offset: int = 0) -> list[SpanCandidate]:
        found: dict[tuple[int, int], SpanCandidate] = {}

        def add(s, e, label, score):
            # trim leading sentence-opening words, keeping offsets exact
            while True:
                surface = text[s:e]
                stripped = surface.lstrip()
                s += len(surface) - len(stripped)
                first = stripped.split(" ")[0] if stripped else ""
                if first in self._LEADING_NOISE and len(stripped.split()) > 1:
                    s += len(first)
                    continue
                break
            surface = text[s:e].strip()
            if not surface or coref.is_anaphor(surface):
                return
            toks = [t for t in re.split(r"[\s,]+", surface) if t]
            alpha = [t.strip(".") for t in toks if t.strip(".").isalpha()]
            # reject spans made only of structural stopwords
            if alpha and all(t in self._STOP for t in alpha):
                return
            key = (base_offset + s, base_offset + e)
            cand = SpanCandidate(start=key[0], end=key[1], text=surface,
                                 label=label, extractors={self.name}, score=score)
            prev = found.get(key)
            if prev is None or score > prev.score:
                found[key] = cand

        for m in self._RE_TITLED.finditer(text):
            add(m.start(), m.end(), "medical_provider", 0.9)
        for m in self._RE_FLIP.finditer(text):
            add(m.start(), m.end(), "person", 0.85)
        for m in self._RE_INITIAL.finditer(text):
            add(m.start(), m.end(), "person", 0.7)
        for m in self._RE_SEQ.finditer(text):
            surface = m.group(0)
            label = "organization" if any(
                surface.endswith(sfx) or f" {sfx}" in surface
                for sfx in gazetteers.ORG_SUFFIXES) else "person"
            left = text[max(0, m.start() - 40):m.start()]
            role = gazetteers.role_from_context(left)
            if role and label == "person":
                label = role
            add(m.start(), m.end(), label, 0.75)

        # drop spans strictly contained in a longer detected span
        spans = sorted(found.values(), key=lambda c: (c.start, -(c.end - c.start)))
        out = []
        for c in spans:
            if any(o is not c and o.start <= c.start and c.end <= o.end
                   and (o.end - o.start) > (c.end - c.start) for o in spans):
                continue
            out.append(c)
        return out


def get_token_ner(backend: str | None = None) -> TokenNERBackend:
    b = (backend or CFG.NER_BACKEND).lower()
    if b in ("auto", "gliner"):
        try:
            return GlinerBackend()
        except Exception:
            if b == "gliner":
                raise
    return DeterministicTokenNER()


# ---------------------------------------------------------------------------
# LLM extractor (semantic pass)
# ---------------------------------------------------------------------------
def llm_extract_chunk(chunk_text: str, base_offset: int, chunk_kind: str = "note") -> list[SpanCandidate]:
    """Gemini structured extraction over one chunk (offline: salience-biased stub).

    The offline handler deliberately SIMULATES the documented LLM failure mode --
    it returns only high-salience spans (the first few, plus anything with an
    explicit role cue) and drops low-salience detail. That makes the ablation an
    honest test of whether the union strategy recovers what an LLM-only pass
    misses, rather than a rigged comparison.
    """
    prompt = (
        "Extract every entity mention from this insurance claim note chunk. "
        "Return character offsets WITHIN the chunk. Never return pronouns or "
        f"vague descriptors. Labels: {list(CFG.NER_LABELS)}.\n\n"
        f"CHUNK:\n<<<\n{chunk_text}\n>>>"
    )

    def offline():
        det = DeterministicTokenNER().extract(chunk_text, 0)
        items = []
        for i, c in enumerate(det):
            left = chunk_text[max(0, c.start - 40):c.start].lower()
            cued = any(cue in left for cues in gazetteers.ROLE_CUES.values() for cue in cues)
            # salience bias: keep early mentions and explicitly-cued ones; drop
            # the long tail the way a single LLM pass does
            if i < 3 or cued:
                items.append({
                    "text": c.text, "label": c.label,
                    "start": c.start, "end": c.end,
                    "description": f"{c.label} mentioned in claim note",
                    "confidence": 0.8,
                })
        return {"entities": items}

    data = genai.generate_json(prompt, _llm_ner_schema(), task="ner_extract",
                               offline_handler=offline)
    out = []
    for e in data.get("entities", []):
        try:
            s, t = int(e["start"]), int(e["end"])
        except (KeyError, TypeError, ValueError):
            continue
        s = max(0, min(s, len(chunk_text)))
        t = max(s, min(t, len(chunk_text)))
        surface = e.get("text") or chunk_text[s:t]
        if coref.is_anaphor(surface):
            continue
        out.append(SpanCandidate(
            start=base_offset + s, end=base_offset + t, text=surface,
            label=e.get("label", "person"), extractors={"llm"},
            score=float(e.get("confidence", 0.7)),
            description=e.get("description", ""),
        ))
    return out


def _llm_ner_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "label": {"type": "string", "enum": list(CFG.NER_LABELS)},
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                        "description": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["text", "label", "start", "end"],
                },
            }
        },
        "required": ["entities"],
    }


# ---------------------------------------------------------------------------
# Union
# ---------------------------------------------------------------------------
def _overlaps(a: SpanCandidate, b: SpanCandidate) -> bool:
    return a.start < b.end and b.start < a.end


def union_spans(groups: list[list[SpanCandidate]]) -> list[SpanCandidate]:
    """Merge candidate lists from all extractors, unioning provenance.

    Overlapping spans collapse to the LONGEST span; the survivor inherits the
    union of every contributing extractor's provenance and the best description.
    """
    allc: list[SpanCandidate] = [c for g in groups for c in g]
    allc.sort(key=lambda c: (c.start, -(c.end - c.start)))
    merged: list[SpanCandidate] = []
    for c in allc:
        hit = None
        for m in merged:
            if _overlaps(c, m):
                hit = m
                break
        if hit is None:
            merged.append(SpanCandidate(
                start=c.start, end=c.end, text=c.text, label=c.label,
                extractors=set(c.extractors), score=c.score,
                description=c.description, chunk_ids=set(c.chunk_ids)))
            continue
        hit.extractors |= c.extractors
        hit.chunk_ids |= c.chunk_ids
        if not hit.description and c.description:
            hit.description = c.description
        # longest span wins; keep the more specific (non-generic) label
        if (c.end - c.start) > (hit.end - hit.start):
            hit.start, hit.end, hit.text = c.start, c.end, c.text
            if c.label not in ("person", "organization"):
                hit.label = c.label
        elif hit.label in ("person", "organization") and c.label not in ("person", "organization"):
            hit.label = c.label
        hit.score = max(hit.score, c.score)
    return merged


def extract_chunk(chunk, token_ner: TokenNERBackend, use_llm: bool = True,
                  use_gazetteer: bool = True, use_token_ner: bool = True) -> list[SpanCandidate]:
    """Run the enabled extractors over one chunk and union their spans.

    The `use_*` switches exist so the ablation can measure each extractor's
    marginal recall contribution.
    """
    groups: list[list[SpanCandidate]] = []
    if use_token_ner:
        groups.append(token_ner.extract(chunk.text, chunk.char_start))
    if use_gazetteer:
        groups.append([
            SpanCandidate(start=h.start, end=h.end, text=h.text, label=h.label,
                          extractors={"gazetteer"}, score=1.0 if h.valid else 0.5)
            for h in gazetteers.scan(chunk.text, chunk.char_start) if h.valid
        ])
    if use_llm:
        groups.append(llm_extract_chunk(chunk.text, chunk.char_start))
    spans = union_spans(groups)
    for s in spans:
        s.chunk_ids.add(chunk.chunk_id)
    return spans
