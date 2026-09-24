"""Layer 1c: coreference resolution.

Pronouns ("he", "they", "it") and vague descriptors ("the physician", "the
treating facility") are linguistic pointers, NOT entities. Extracting them as
nodes produces a graph full of useless disconnected "He"/"The Doctor" nodes.
Resolving them first means factual relationships attach to the correct canonical
entity node.

DESIGN: resolution is NON-DESTRUCTIVE. We do not rewrite the immutable raw
corpus. Instead we produce:
  - `CorefLink` records: (mention_span -> antecedent surface + class), so a
    relationship extracted at a pronoun's position is re-attached to the real
    entity while the evidence span still points at the true raw characters; and
  - `resolved_view()`: a derived text view with pronouns substituted, PLUS an
    offset map back to raw offsets, for handing to an LLM that reads better with
    explicit names.
This keeps span-grounding and the corpus-immutability invariant intact.

Backends: `FastCorefResolver` (real, activates when `fastcoref` is installed) and
`RuleBasedCorefResolver` (deterministic; nearest compatible antecedent with
gender/number/type agreement). Selected via CFG.COREF_BACKEND.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .settings import CFG


@dataclass
class CorefLink:
    start: int              # absolute char offset of the anaphor (pronoun/descriptor)
    end: int
    surface: str            # the anaphor text as it appears
    antecedent_surface: str  # resolved canonical mention text
    antecedent_start: int
    antecedent_end: int
    antecedent_class: str | None
    kind: str               # 'pronoun' | 'descriptor'
    backend: str
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Pronoun agreement features (rule-based backend)
# ---------------------------------------------------------------------------
_MASC = {"he", "him", "his"}
_FEM = {"she", "her", "hers"}
_PLUR = {"they", "them", "their", "theirs"}
_NEUT = {"it", "its"}

_PERSON_CLASSES = {"claimant", "attorney", "adjuster", "person", "medical_provider"}
_ORG_CLASSES = {"repair_shop", "organization", "law_firm", "medical_provider"}

_DESCRIPTOR_CLASS = {
    "the physician": "medical_provider", "the doctor": "medical_provider",
    "the provider": "medical_provider", "the treating facility": "medical_provider",
    "the facility": "medical_provider", "the clinic": "medical_provider",
    "the hospital": "medical_provider", "said provider": "medical_provider",
    "the claimant": "claimant", "the clmt": "claimant", "the insured": "claimant",
    "the attorney": "attorney", "the atty": "attorney", "the counsel": "attorney",
    "the shop": "repair_shop",
    "the adjuster": "adjuster", "the carrier": "adjuster",
}


class CorefResolver(ABC):
    """Resolve anaphora to antecedent entity mentions.

    Implementations receive the document text plus the entity mentions already
    detected in it (each a dict with start/end/text/label) and return CorefLinks.

    To swap in a neural resolver, implement `resolve()` and return the same
    CorefLink shape with absolute document offsets. Nothing else changes.
    """

    name = "abstract"

    @abstractmethod
    def resolve(self, text: str, mentions: list[dict]) -> list[CorefLink]: ...


class RuleBasedCorefResolver(CorefResolver):
    """Deterministic nearest-compatible-antecedent resolver.

    For each pronoun / vague descriptor, walk backwards up to
    COREF_MAX_ANTECEDENT_CHARS and bind to the closest preceding entity mention
    whose class is compatible (person pronouns -> person mentions; 'it/its' ->
    organization; descriptors -> their mapped class).
    """

    name = "rulebased"

    def __init__(self):
        pron = sorted(CFG.COREF_PRONOUNS, key=len, reverse=True)
        self._pron_re = re.compile(r"\b(" + "|".join(map(re.escape, pron)) + r")\b", re.I)
        desc = sorted(CFG.COREF_DESCRIPTORS, key=len, reverse=True)
        self._desc_re = re.compile(r"(" + "|".join(map(re.escape, desc)) + r")", re.I)

    def resolve(self, text: str, mentions: list[dict]) -> list[CorefLink]:
        ms = sorted(mentions, key=lambda m: m["start"])
        links: list[CorefLink] = []

        def antecedent_for(pos: int, allowed: set[str] | None):
            best = None
            for m in ms:
                if m["end"] > pos:
                    break
                if pos - m["end"] > CFG.COREF_MAX_ANTECEDENT_CHARS:
                    continue
                cls = (m.get("label") or "").lower()
                if allowed is not None and cls and cls not in allowed:
                    continue
                best = m
            return best

        for m in self._pron_re.finditer(text):
            w = m.group(0).lower()
            if w in _MASC or w in _FEM:
                allowed = _PERSON_CLASSES
            elif w in _PLUR:
                allowed = None            # could be people or an org
            elif w in _NEUT:
                allowed = _ORG_CLASSES
            else:
                allowed = None
            ant = antecedent_for(m.start(), allowed)
            if ant:
                links.append(CorefLink(
                    start=m.start(), end=m.end(), surface=m.group(0),
                    antecedent_surface=ant["text"], antecedent_start=ant["start"],
                    antecedent_end=ant["end"], antecedent_class=ant.get("label"),
                    kind="pronoun", backend=self.name, confidence=0.75,
                ))

        for m in self._desc_re.finditer(text):
            key = m.group(0).lower()
            allowed_cls = _DESCRIPTOR_CLASS.get(key)
            allowed = {allowed_cls} if allowed_cls else None
            ant = antecedent_for(m.start(), allowed)
            if ant:
                links.append(CorefLink(
                    start=m.start(), end=m.end(), surface=m.group(0),
                    antecedent_surface=ant["text"], antecedent_start=ant["start"],
                    antecedent_end=ant["end"], antecedent_class=ant.get("label"),
                    kind="descriptor", backend=self.name, confidence=0.7,
                ))
        links.sort(key=lambda l: l.start)
        return links


class FastCorefResolver(CorefResolver):
    """Adapter for the `fastcoref` neural resolver (production path).

    Activates only when `fastcoref` is importable and its weights are available.
    Maps fastcoref clusters onto CorefLinks: the first mention of each cluster is
    the antecedent, later mentions become links to it.
    """

    name = "fastcoref"

    def __init__(self):
        from fastcoref import FCoref  # noqa: F401  (import error -> caller falls back)
        self._model = FCoref()

    def resolve(self, text: str, mentions: list[dict]) -> list[CorefLink]:
        preds = self._model.predict(texts=[text])[0]
        links: list[CorefLink] = []
        for cluster in preds.get_clusters(as_strings=False):
            if len(cluster) < 2:
                continue
            a_start, a_end = cluster[0]
            antecedent = text[a_start:a_end]
            cls = None
            for m in mentions:
                if m["start"] <= a_start and m["end"] >= a_end:
                    cls = m.get("label")
                    break
            for (s, e) in cluster[1:]:
                surf = text[s:e]
                kind = "pronoun" if surf.lower() in CFG.COREF_PRONOUNS else "descriptor"
                links.append(CorefLink(
                    start=s, end=e, surface=surf, antecedent_surface=antecedent,
                    antecedent_start=a_start, antecedent_end=a_end,
                    antecedent_class=cls, kind=kind, backend=self.name, confidence=0.9,
                ))
        links.sort(key=lambda l: l.start)
        return links


def get_resolver(backend: str | None = None) -> CorefResolver:
    """Select a resolver. 'auto' prefers fastcoref, falls back to rule-based."""
    b = (backend or CFG.COREF_BACKEND).lower()
    if b in ("auto", "fastcoref"):
        try:
            return FastCorefResolver()
        except Exception:
            if b == "fastcoref":
                raise
    return RuleBasedCorefResolver()


def is_anaphor(surface: str) -> bool:
    """True if this surface is a pronoun/vague descriptor (never a graph node)."""
    s = surface.strip().lower()
    return s in CFG.COREF_PRONOUNS or s in CFG.COREF_DESCRIPTORS


def resolved_view(text: str, links: list[CorefLink]) -> tuple[str, list[tuple[int, int]]]:
    """Build a derived text with anaphora substituted, plus an offset map.

    Returns (resolved_text, offset_map) where offset_map[i] = (raw_start, raw_end)
    for the i-th character region; concretely we return a list of
    (resolved_offset, raw_offset) checkpoints usable to project a resolved-text
    span back to raw document coordinates via `project_span`.
    """
    out = []
    checkpoints: list[tuple[int, int]] = []
    raw_pos = 0
    res_pos = 0
    for link in sorted(links, key=lambda l: l.start):
        if link.start < raw_pos:
            continue
        seg = text[raw_pos:link.start]
        out.append(seg)
        checkpoints.append((res_pos, raw_pos))
        res_pos += len(seg)
        raw_pos = link.start
        # substitute
        out.append(link.antecedent_surface)
        checkpoints.append((res_pos, raw_pos))
        res_pos += len(link.antecedent_surface)
        raw_pos = link.end
    out.append(text[raw_pos:])
    checkpoints.append((res_pos, raw_pos))
    return "".join(out), checkpoints


def project_span(res_start: int, res_end: int, checkpoints: list[tuple[int, int]],
                 raw_len: int) -> tuple[int, int]:
    """Project a span in resolved-view coordinates back to raw document offsets."""
    raw_s = raw_e = 0
    for (rs, raw) in checkpoints:
        if rs <= res_start:
            raw_s = raw + (res_start - rs)
        if rs <= res_end:
            raw_e = raw + (res_end - rs)
    raw_s = max(0, min(raw_s, raw_len))
    raw_e = max(raw_s, min(raw_e, raw_len))
    return raw_s, raw_e
