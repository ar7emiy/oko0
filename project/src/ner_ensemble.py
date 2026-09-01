"""Layer 1d: token-level NER ensemble (the UNION strategy).

The premise: a single LLM pass misses entities through attention drift and
positional bias -- it filters out low-salience details (a paralegal named once,
a footer clinic, a lone diagnostic code). So we run independent extractors over
every chunk and take their UNION, tracking which extractor found each span:

  1. token_ner   -- span-level scanner that reads every literal token.
                    `GlinerBackend` (zero-shot GLiNER) is the production
                    backend and is REQUIRED; there is no silent fallback.
                    Recall-first.
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
from .settings import CFG, genai_mode, genai_mode_is_forced


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


class LLMExtractorUnavailable(RuntimeError):
    """Raised when the semantic extraction lane cannot run for real."""


class NERBackendUnavailable(RuntimeError):
    """Raised when the configured production NER backend cannot be loaded.

    Deliberately fatal. The predecessor of this code fell back to a
    corpus-fitted regex scanner whenever GLiNER was missing, which meant a run
    with no model weights produced output shaped exactly like a real run and
    every number measured from it was silently a regex number.
    """


def get_token_ner(backend: str | None = None) -> TokenNERBackend:
    """Return the token-NER backend. Never silently degrades.

    'gliner'        -- production. Raises NERBackendUnavailable if unusable.
    'deterministic' -- research/offline regex scanner. Must be asked for by
                       name; it is corpus-fitted and capitalization-dependent.
    """
    b = (backend or CFG.NER_BACKEND).lower()
    if b == "gliner":
        try:
            return GlinerBackend()
        except Exception as e:
            raise NERBackendUnavailable(
                f"GLiNER backend unavailable ({type(e).__name__}: {e}). "
                "Install `gliner` and make its weights reachable, or set "
                "NER_BACKEND='deterministic' to run the research scanner "
                "KNOWINGLY -- its output is not comparable to a model run."
            ) from e
    if b == "deterministic":
        from .research.deterministic_ner import DeterministicTokenNER
        return DeterministicTokenNER()
    raise ValueError(
        f"Unknown NER_BACKEND {b!r}. Use 'gliner' (production) or "
        "'deterministic' (research/offline). 'auto' was removed: it hid which "
        "backend actually served a run."
    )

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

    if genai_mode() == "offline":
        if not genai_mode_is_forced():
            raise LLMExtractorUnavailable(
                "No GenAI API key is set, so the semantic extraction lane cannot "
                "run. Refusing to substitute a stand-in silently: the previous "
                "behaviour returned the deterministic regex scanner's output "
                "under the 'llm' provenance tag, which made the three-extractor "
                "union effectively two extractors and quietly invalidated every "
                "recall number measured from it. Set an API key, or set "
                "GENAI_MODE=offline to run the labelled research stub knowingly."
            )
        from .research.llm_stub import salience_biased_stub
        offline = lambda: salience_biased_stub(chunk_text)   # noqa: E731
    else:
        offline = None

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
        # Score by what actually backs the hit, not by the fact that a regex
        # matched: a check-digit-verified NPI is not the same evidence as a
        # 9-digit string that merely looks like a TIN.
        _GAZ_SCORE = {"checksum": 1.0, "format": 0.8, "none": 0.6}
        groups.append([
            SpanCandidate(start=h.start, end=h.end, text=h.text, label=h.label,
                          extractors={"gazetteer"},
                          score=_GAZ_SCORE.get(h.validation, 0.6))
            for h in gazetteers.scan(chunk.text, chunk.char_start) if h.valid
        ])
    if use_llm:
        groups.append(llm_extract_chunk(chunk.text, chunk.char_start))
    spans = union_spans(groups)
    for s in spans:
        s.chunk_ids.add(chunk.chunk_id)
    return spans
