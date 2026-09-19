"""Locating a quoted phrase in a note.

Positions are Python string indices into the note text: Unicode code points,
0-based, end-exclusive. A quote that doesn't match exactly is retried with
typography normalized (curly quotes, dashes, runs of whitespace), then without
case. Any match found that way is mapped back to the note's exact original
characters, so a stored quote is always a verbatim slice of the note.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
}
_DASHES = {c: "-" for c in "‐‑‒–—―−"}
_SPACES = set(" \t\r\n\f\v" + "\u00a0\u2002\u2003\u2009\u200a\u202f\u3000")
_ELLIPSIS = "…"


def _normalize(text: str, fold_case: bool) -> tuple[str, list[int]]:
    """Normalized text plus, for each output character, the source index it came from."""
    out: list[str] = []
    origin: list[int] = []
    in_space = False
    for i, ch in enumerate(text):
        if ch in _SPACES:
            if not in_space:
                out.append(" ")
                origin.append(i)
            in_space = True
            continue
        in_space = False
        if ch == _ELLIPSIS:
            rep = "..."
        else:
            rep = _QUOTES.get(ch) or _DASHES.get(ch) or ch
        if fold_case:
            rep = rep.casefold()
        for r in rep:
            out.append(r)
            origin.append(i)
    return "".join(out), origin


def _find_all(haystack: str, needle: str) -> list[int]:
    hits, start = [], 0
    while needle:
        i = haystack.find(needle, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    return hits


def _clean_quote(quote: str, fold_case: bool) -> str:
    norm, _ = _normalize(quote.strip(), fold_case)
    return norm.strip()


def _candidates(text: str, quote: str, fold_case: bool) -> list[tuple[int, int]]:
    norm_text, origin = _normalize(text, fold_case)
    needle = _clean_quote(quote, fold_case)
    spans = []
    for ns in _find_all(norm_text, needle):
        ne = ns + len(needle)
        spans.append((origin[ns], origin[ne - 1] + 1))
    return spans


@dataclass
class Located:
    status: str                       # exact | normalized | case | ambiguous | not_found
    start: int | None = None
    end: int | None = None
    candidates: list[tuple[int, int]] = field(default_factory=list)
    how: str = ""                     # how a repeated quote was pinned down, shown to the reviewer

    @property
    def found(self) -> bool:
        return self.start is not None


def _preceding_matches(text: str, start: int, before: str) -> bool:
    want = _clean_quote(before, fold_case=True)
    if not want:
        return False
    window = text[max(0, start - len(before) * 3 - 40):start]
    have, _ = _normalize(window, fold_case=True)
    return have.rstrip().endswith(want)


def _whole_words(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Spans that don't start or end in the middle of a word: "he" in "he said", not in "the"."""
    def clean(s: int, e: int) -> bool:
        if text[s].isalnum() and s > 0 and text[s - 1].isalnum():
            return False
        if text[e - 1].isalnum() and e < len(text) and text[e].isalnum():
            return False
        return True
    whole = [sp for sp in spans if clean(*sp)]
    return whole or spans


def locate(text: str, quote: str, *, before: str | None = None, occurrence: int | None = None,
           prefer: tuple[int, int] | None = None) -> Located:
    """Find `quote` in `text`, pinning down repeats with `before`, `occurrence`, or a preferred range."""
    quote = (quote or "").strip()
    if not quote:
        return Located("not_found")
    spans = [(s, s + len(quote)) for s in _find_all(text, quote)]
    status = "exact"
    if not spans:
        spans, status = _candidates(text, quote, fold_case=False), "normalized"
    if not spans:
        spans, status = _candidates(text, quote, fold_case=True), "case"
    if not spans:
        return Located("not_found")
    spans = _whole_words(text, spans)
    if len(spans) == 1:
        return Located(status, spans[0][0], spans[0][1], spans)

    if before:
        narrowed = [s for s in spans if _preceding_matches(text, s[0], before)]
        if len(narrowed) == 1:
            return Located(status, narrowed[0][0], narrowed[0][1], spans, how="the words before it")
    if occurrence is not None and 1 <= occurrence <= len(spans):
        chosen = spans[occurrence - 1]
        return Located(status, chosen[0], chosen[1], spans, how=f"occurrence {occurrence}")
    if prefer is not None:
        inside = [s for s in spans if prefer[0] <= s[0] < prefer[1]]
        if len(inside) == 1:
            return Located(status, inside[0][0], inside[0][1], spans, how="the note part it was drafted from")
    return Located("ambiguous", None, None, spans)
