"""Layer 1c: coreference resolution.

Pronouns ("he", "they", "it") and vague descriptors ("the physician", "the
treating facility") are linguistic pointers, NOT entities. Extracting them as
nodes produces a graph full of useless disconnected "He"/"The Doctor" nodes.
Resolving them first means factual relationships attach to the correct canonical
entity node.

DESIGN: resolution is NON-DESTRUCTIVE. We do not rewrite the immutable raw
corpus. Instead we produce:
  - `CorefLink` records: (mention_span -> antecedent surface + type), so a
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
    antecedent_type: str | None   # 'person'|'organization'|'unknown'; never a role
    kind: str               # 'pronoun' | 'descriptor'
    backend: str
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Pronoun agreement features (rule-based backend)
# ---------------------------------------------------------------------------
_MASC = {"he", "him", "his"}
_FEM = {"she", "her", "hers"}
_PLUR = {"they", "them", "their", "theirs"}   # no type constraint: people or an org
_NEUT = {"it", "its"}

# AGREEMENT IS ON TYPE, NOT ROLE.
#
# This used to filter antecedents by `entity_class` against two hand-written role
# lists (`claimant, attorney, adjuster, medical_provider, ...`). That was wrong
# three ways, and the review comments that prompted this rewrite named all three:
#
#  1. It could not be complete. A note mentions a mechanic, a witness, a nurse, a
#     truck driver. None are on the list, so every one of them was refused as an
#     antecedent for "he" -- silently, as a correctness bug rather than a gap.
#  2. The same role has many surface names. An adjuster is a "claim handler", a
#     "claims examiner", a "resolution manager", depending on the carrier. A list
#     of role words is a list of one carrier's vocabulary.
#  3. `entity_class` does not exist in v0.1. It was deleted from the schema for
#     disagreeing with itself on 69% of entities. This module was still filtering
#     on it -- a carried-over consumer of a field nobody writes any more.
#
# Pronoun agreement never needed role in the first place. "He" requires a PERSON;
# it does not care whether that person is a claimant or a witness. So the filter
# is `entity_type` -- two values plus `unknown`, computed from the name string,
# with no list to maintain. Mechanics, witnesses and nurses are all `person` and
# resolve correctly without anyone adding a word.
#
# `unknown` is deliberately never filtered out: coreference measured ~43%
# accurate, and a low-accuracy component must not hold a veto over a mention it
# could not type. See `antecedent_for`.
_PERSON_PRONOUNS = _MASC | _FEM
_ORG_PRONOUNS = _NEUT

# Descriptors whose head noun settles the TYPE. Kept deliberately short: these
# are the few common nouns that are decisive on their own, not an attempt to
# enumerate professions. A descriptor that is not listed simply carries no type
# constraint -- under-constraining a 43%-accurate component is safe, while a
# wrong constraint is not. Organisation descriptors are additionally recognised
# from the LEARNED head-noun lexicon (see `entity_type.learn_head_nouns`), so
# "the acupuncture clinic" works without anyone listing acupuncture.
_DESCRIPTOR_TYPE = {
    "the physician": "person", "the doctor": "person",
    "the provider": "person", "the treating facility": "organization",
    "the facility": "organization", "the clinic": "organization",
    "the hospital": "organization", "said provider": "person",
    "the claimant": "person", "the clmt": "person", "the insured": "person",
    "the attorney": "person", "the atty": "person", "the counsel": "person",
    "the shop": "organization", "the carrier": "organization",
    "the adjuster": "person",
}


def descriptor_type(descriptor: str, head_nouns: set[str] | None = None) -> str | None:
    """Type a definite descriptor, or None when it does not settle one.

    The listed entries above are the closed part. Everything else is decided by
    the LEARNED lexicon: "the <X>" where X is a known organisation head noun is
    an organisation. That is what stops the list needing to grow -- a corpus
    containing acupuncture clinics teaches the lexicon "acupuncture", and "the
    acupuncture clinic" then types itself.

    Returning None is the normal outcome for an unrecognised descriptor and
    means "no constraint", not "no antecedent".
    """
    key = (descriptor or "").strip().lower()
    if key in _DESCRIPTOR_TYPE:
        return _DESCRIPTOR_TYPE[key]
    if head_nouns:
        tokens = [t for t in re.findall(r"[A-Za-z]+", key) if t]
        if tokens and tokens[-1] in head_nouns:
            return "organization"
    return None


class CorefResolver(ABC):
    """Resolve anaphora to antecedent entity mentions.

    Implementations receive the document text plus the entity mentions already
    detected in it (each a dict with start/end/text/entity_type) and return
    CorefLinks.

    To swap in a neural resolver, implement `resolve()` and return the same
    CorefLink shape with absolute document offsets. Nothing else changes.
    """

    name = "abstract"

    @abstractmethod
    def resolve(self, text: str, mentions: list[dict],
                head_nouns: set[str] | None = None) -> list[CorefLink]: ...


class RuleBasedCorefResolver(CorefResolver):
    """Deterministic nearest-compatible-antecedent resolver.

    For each pronoun / vague descriptor, walk backwards up to
    COREF_MAX_ANTECEDENT_CHARS and bind to the closest preceding entity mention
    whose entity_type does not contradict (person pronouns -> person mentions;
    'it/its' -> organization; 'they' -> unconstrained). An `unknown` mention is
    always eligible -- see `antecedent_for`.
    """

    name = "rulebased"

    def __init__(self):
        pron = sorted(CFG.COREF_PRONOUNS, key=len, reverse=True)
        self._pron_re = re.compile(r"\b(" + "|".join(map(re.escape, pron)) + r")\b", re.I)
        self._desc_cache: dict[frozenset[str], re.Pattern] = {}

    def _descriptor_re(self, head_nouns: set[str] | None) -> re.Pattern:
        """Descriptor detector, EXTENDED BY THE CORPUS rather than by hand.

        `CFG.COREF_DESCRIPTORS` is a seed. On its own it has the defect the
        review called out: a note saying "the acupuncture clinic" is not merely
        mistyped, it is never detected at all, because the phrase is not on the
        list -- and the only remedy is a human adding a line.

        So the detector also admits `the|said|this <X>` for every X in the
        LEARNED head-noun lexicon. A corpus containing acupuncture clinics
        teaches "acupuncture", and the descriptor becomes visible with no edit.
        The seed list stays for the phrases whose head noun is not itself an
        organisation word ("the claimant", "the insured").
        """
        key = frozenset(head_nouns or ())
        cached = self._desc_cache.get(key)
        if cached is not None:
            return cached

        seeds = sorted(CFG.COREF_DESCRIPTORS, key=len, reverse=True)
        parts = [r"\b(?:" + "|".join(map(re.escape, seeds)) + r")\b"]
        if key:
            # A run of head nouns, so "the acupuncture clinic" is captured whole
            # rather than truncated to "the acupuncture". The span must cover the
            # phrase it claims to cover.
            noun = r"(?:" + "|".join(map(re.escape, sorted(key))) + r")"
            parts.append(rf"\b(?:the|said|this)\s+(?:{noun}\s+)*{noun}\b")
        rx = re.compile("(" + "|".join(parts) + ")", re.I)
        self._desc_cache[key] = rx
        return rx

    def resolve(self, text: str, mentions: list[dict],
                head_nouns: set[str] | None = None) -> list[CorefLink]:
        ms = sorted(mentions, key=lambda m: m["start"])
        links: list[CorefLink] = []

        def antecedent_for(pos: int, want_type: str | None):
            """Nearest preceding mention whose type does not contradict.

            `unknown` never contradicts. A mention this system could not type is
            still a candidate -- otherwise a typing miss becomes a coreference
            miss, and two ~88%-accurate stages multiply into one bad one.
            """
            best = None
            for m in ms:
                if m["end"] > pos:
                    break
                if pos - m["end"] > CFG.COREF_MAX_ANTECEDENT_CHARS:
                    continue
                got = (m.get("entity_type") or "unknown").lower()
                if want_type and got not in (want_type, "unknown"):
                    continue
                best = m
            return best

        for m in self._pron_re.finditer(text):
            w = m.group(0).lower()
            if w in _PERSON_PRONOUNS:
                want = "person"
            elif w in _ORG_PRONOUNS:
                want = "organization"
            else:
                want = None               # "they" -- people or an org
            ant = antecedent_for(m.start(), want)
            if ant:
                links.append(CorefLink(
                    start=m.start(), end=m.end(), surface=m.group(0),
                    antecedent_surface=ant["text"], antecedent_start=ant["start"],
                    antecedent_end=ant["end"], antecedent_type=ant.get("entity_type"),
                    kind="pronoun", backend=self.name, confidence=0.75,
                ))

        for m in self._descriptor_re(head_nouns).finditer(text):
            ant = antecedent_for(m.start(),
                                 descriptor_type(m.group(0), head_nouns))
            if ant:
                links.append(CorefLink(
                    start=m.start(), end=m.end(), surface=m.group(0),
                    antecedent_surface=ant["text"], antecedent_start=ant["start"],
                    antecedent_end=ant["end"], antecedent_type=ant.get("entity_type"),
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

    def resolve(self, text: str, mentions: list[dict],
                head_nouns: set[str] | None = None) -> list[CorefLink]:
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
                    ant_type = m.get("entity_type")
                    break
            for (s, e) in cluster[1:]:
                surf = text[s:e]
                kind = "pronoun" if surf.lower() in CFG.COREF_PRONOUNS else "descriptor"
                links.append(CorefLink(
                    start=s, end=e, surface=surf, antecedent_surface=antecedent,
                    antecedent_start=a_start, antecedent_end=a_end,
                    antecedent_type=ant_type, kind=kind, backend=self.name, confidence=0.9,
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
