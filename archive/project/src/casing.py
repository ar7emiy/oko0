"""Casing regime detection.

Legacy claim notes are not reliably title-cased. A note may arrive ALL CAPS
(green-screen / mainframe origin), entirely lowercase (fast typing, mobile
entry), or mixed within one document -- an upper-cased header block over a
normally-cased body.

That matters because capitalization is *load-bearing* for several detectors:
a capitalized-token-run scanner finds nothing in lowercase text, and in ALL
CAPS text it matches every sentence. It does not fail loudly; it fails
silently, either dropping every name or proposing every phrase as one.

This module's job is to say, per document and per span, whether
capitalization carries information at all -- so callers can route around it
rather than trusting a signal that is not there.

Deliberately NOT a truecaser. Restoring case correctly needs a model, and a
heuristic "fix" would fabricate evidence at exact character offsets the rest
of the system treats as ground truth. Detect and route; never invent case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# A "casing-bearing word": at least two letters, so single initials and
# stray capitals do not swing the statistics.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]+")

# Below this many casing-bearing words there is not enough evidence to judge.
MIN_WORDS_FOR_JUDGEMENT = 12

# Fraction of words that are ALL CAPS above which the text reads as upper-case.
UPPER_REGIME_FRAC = 0.60

# Fraction of words carrying ANY leading capital below which the text reads as
# lower-case. Ordinary English prose sits far above this: sentence openers and
# proper nouns alone put it around 0.10-0.25.
LOWER_REGIME_FRAC = 0.02


@dataclass(frozen=True)
class CasingProfile:
    """What casing regime a piece of text is in, and whether to trust it."""

    regime: str            # 'mixed' | 'upper' | 'lower' | 'sparse'
    case_informative: bool  # False => capitalization carries no signal here
    n_words: int
    upper_frac: float      # ALL-CAPS words / casing-bearing words
    capitalized_frac: float  # words with a leading capital / casing-bearing words
    lower_frac: float      # entirely-lowercase words / casing-bearing words

    def as_dict(self) -> dict:
        return asdict(self)


def profile(text: str) -> CasingProfile:
    """Classify the casing regime of `text`."""
    words = _WORD_RE.findall(text or "")
    n = len(words)
    if n == 0:
        return CasingProfile("sparse", False, 0, 0.0, 0.0, 0.0)

    n_upper = sum(1 for w in words if w.isupper())
    n_cap = sum(1 for w in words if w[0].isupper())
    n_lower = sum(1 for w in words if w.islower())
    upper_frac = n_upper / n
    cap_frac = n_cap / n
    lower_frac = n_lower / n

    if n < MIN_WORDS_FOR_JUDGEMENT:
        regime, informative = "sparse", False
    elif upper_frac >= UPPER_REGIME_FRAC:
        regime, informative = "upper", False
    elif cap_frac <= LOWER_REGIME_FRAC:
        regime, informative = "lower", False
    else:
        regime, informative = "mixed", True

    return CasingProfile(regime, informative, n, round(upper_frac, 4),
                         round(cap_frac, 4), round(lower_frac, 4))


def is_case_informative(text: str) -> bool:
    """Shorthand: may a capitalization-dependent detector be trusted here?"""
    return profile(text).case_informative


def profile_spans(text: str, spans: list[tuple[int, int]]) -> list[CasingProfile]:
    """Profile each (start, end) span separately.

    A document-level verdict hides the common legacy shape: an ALL CAPS header
    block above a normally-cased narrative. Profiling per segment lets the
    header be routed differently from the body it sits on.
    """
    return [profile(text[s:e]) for s, e in spans]


def document_report(text: str, spans: list[tuple[int, int]] | None = None) -> dict:
    """Document verdict plus the per-span breakdown, for the profiling table."""
    doc = profile(text)
    out = {"doc": doc.as_dict()}
    if spans:
        per = profile_spans(text, spans)
        out["spans"] = [p.as_dict() for p in per]
        out["n_spans_case_blind"] = sum(1 for p in per if not p.case_informative)
    return out
