"""Deterministic capitalized-run name scanner (RESEARCH / OFFLINE ONLY).

Not a production NER backend. It encodes one weak English regularity -- runs of
capitalized tokens tend to be names -- plus two hand-curated word lists
(`_LEADING_NOISE`, `_STOP`) derived from the synthetic corpus's phrasing. The
regularity transfers; the lists do not.

Two hard limits, both silent rather than loud:

  * It is entirely capitalization-dependent. On ALL CAPS text every sentence
    matches; on lowercase text nothing does. Callers MUST gate it on
    `casing.is_case_informative`, or it will produce confident nonsense.
  * `_RE_SEQ` matches any 2-4 capitalized tokens, so ordinary title-case
    phrases ("Physical Therapy", "Blue Cross", "Monday Morning") become
    person/organization candidates. Precision is not recovered here.

Retained so the ablation can measure what a pattern-only lane contributes, and
so the offline test harness has something deterministic to run.
"""
from __future__ import annotations

import re

from .. import coref, gazetteers
from ..ner_ensemble import SpanCandidate, TokenNERBackend


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
