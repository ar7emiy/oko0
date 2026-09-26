"""Offline stand-in for the semantic extraction lane (RESEARCH ONLY).

This is NOT a language model and its output must never be reported as one.

It runs the deterministic regex scanner and then discards most of its output
to imitate the documented single-pass LLM failure mode: keep the first few
mentions and anything with an explicit role cue nearby, drop the long tail.

The important consequence, stated plainly because it was previously implicit:
the spans this returns are a SUBSET of the token-NER lane's spans. When this
stub is in use the three-extractor union is really a two-extractor union, and
the "llm" provenance tag on a span means only that the span survived a
salience filter. Any recall or ablation number produced with this stub active
measures the filter, not a model.

Reachable only when GENAI_MODE=offline is set deliberately; a keyless run
raises instead.
"""
from __future__ import annotations

from .. import gazetteers
from .deterministic_ner import DeterministicTokenNER

# How many leading mentions survive the imitated salience bias.
KEEP_LEADING = 3


def salience_biased_stub(chunk_text: str) -> dict:
    """Return the `{"entities": [...]}` shape the real schema produces."""
    det = DeterministicTokenNER().extract(chunk_text, 0)
    items = []
    for i, c in enumerate(det):
        left = chunk_text[max(0, c.start - 40):c.start].lower()
        cued = any(cue in left
                   for cues in gazetteers.ROLE_CUES.values() for cue in cues)
        if i < KEEP_LEADING or cued:
            items.append({
                "text": c.text, "label": c.label,
                "start": c.start, "end": c.end,
                "description": f"{c.label} mentioned in claim note",
                "confidence": 0.8,
            })
    return {"entities": items}
