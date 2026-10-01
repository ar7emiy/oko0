"""Invariants for `entity_type`, and the measurements that justify it.

Run directly: `python tests/test_entity_type.py`

The thresholds below are floors taken from a real measurement, not aspirations.
Each one exists because a plausible-sounding alternative failed it -- the
numbers are in the module docstring of `src/entity_type.py`.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.entity_type import (comparison_strategy, entity_type,  # noqa: E402
                             learn_head_nouns)
from src.settings import Paths  # noqa: E402

# Realistic people whose surname is an ordinary business word. The hardcoded
# lexicon this module replaced typed 13 of these 14 as organisations.
ADVERSARIAL_PEOPLE = [
    "Dr. Paul Frame", "Marcus Law", "Sarah Glass", "Dr. Amy Carr",
    "Michael Body", "Jennifer Service", "Robert Shop", "Dr. Lisa Spine",
    "Angela Health", "Tom Motors", "Dr. Priya Care", "David Legal",
    "Susan Practice", "Dr. John Surgery",
]

# Specialties absent from any list I would have written by hand. They must be
# learned from the corpus, which is the entire point of `learn_head_nouns`.
UNLISTED_SPECIALTIES = [
    "Ashford Acupuncture", "Bristol Acupuncture", "Kelso Acupuncture",
    "Vance Optometry", "Riverton Optometry", "Lakewood Optometry",
    "Doran Podiatry", "Feld Podiatry", "Ames Podiatry",
]


def _corpus_names() -> list[str]:
    man = json.loads(Paths.manifest_json.read_text(encoding="utf-8"))
    return [e["canonical"]["name"] for e in man["entities"]]


def _ground_truth() -> dict[str, str]:
    """Type labels the generator implies, never read by the pipeline itself.

    The corpus writes name variants per entity: a `short` form belongs to an
    organisation, while `flip`/`initials`/`nickname`/`last_only` are personal
    name behaviours. That yields an independent label for 468 entities.
    """
    man = json.loads(Paths.manifest_json.read_text(encoding="utf-8"))
    variants: dict[str, set[str]] = defaultdict(set)
    for p in man["placements"]:
        if p["kind"] == "entity" and p.get("variant_kind"):
            variants[p["gt_id"]].add(p["variant_kind"])
    person_variants = {"flip", "initials", "nickname", "last_only"}
    name_of = {e["gt_entity_id"]: e["canonical"]["name"] for e in man["entities"]}
    return {
        name_of[gid]: ("organization" if "short" in kinds else "person")
        for gid, kinds in variants.items()
        if "short" in kinds or kinds & person_variants
    }


def test_titles_beat_business_surnames() -> None:
    """A person whose surname reads as a business word is still a person."""
    lex = learn_head_nouns(_corpus_names())
    wrong = [n for n in ADVERSARIAL_PEOPLE if entity_type(n, lex) != "person"]
    assert not wrong, f"typed as non-person: {wrong}"


def test_unseen_vocabulary_is_learned() -> None:
    """Vocabulary nobody listed is discovered from three sightings."""
    lex = learn_head_nouns(_corpus_names() + UNLISTED_SPECIALTIES)
    for name in ("Ashford Acupuncture", "Vance Optometry", "Doran Podiatry"):
        assert entity_type(name, lex) == "organization", name


def test_lexicon_excludes_surnames() -> None:
    """The leading-position rule is what keeps surnames out. Guard it.

    Recurrence alone admitted `anderson`, `davis`, `miller`, `smith` and 48
    others, and cost 66 points of accuracy.
    """
    lex = learn_head_nouns(_corpus_names())
    leaked = {"anderson", "brown", "davis", "miller", "smith", "wilson",
              "williams", "taylor", "martinez", "clark"} & lex
    assert not leaked, f"surnames leaked into the lexicon: {sorted(leaked)}"


def test_typing_accuracy_against_ground_truth() -> None:
    """Floors from measurement: 88.7% overall, 88.1% person, 92.4% org."""
    lex = learn_head_nouns(_corpus_names())
    gt = _ground_truth()
    hits = Counter()
    totals = Counter()
    for name, want in gt.items():
        totals[want] += 1
        totals["all"] += 1
        if entity_type(name, lex) == want:
            hits[want] += 1
            hits["all"] += 1
    assert hits["all"] / totals["all"] >= 0.88, hits["all"] / totals["all"]
    assert hits["person"] / totals["person"] >= 0.87
    assert hits["organization"] / totals["organization"] >= 0.90


def test_type_is_deterministic() -> None:
    """Rule 5. Identical strings must type identically, always."""
    lex = learn_head_nouns(_corpus_names())
    for name in ADVERSARIAL_PEOPLE + UNLISTED_SPECIALTIES:
        assert len({entity_type(name, lex) for _ in range(5)}) == 1


def test_type_is_never_a_veto() -> None:
    """Rule 1, and v0's costliest constraint: a mismatch must stay comparable.

    v0's `person_vs_org` veto was wrong 70% of the time and blocked 898 correct
    merges. A mistype must cost accuracy, never possibility -- so every pair
    resolves to a strategy and none to a refusal.
    """
    kinds = ("person", "organization", "unknown")
    for a in kinds:
        for b in kinds:
            assert comparison_strategy(a, b) in ("person", "organization",
                                                 "generic")
    assert comparison_strategy("person", "organization") == "generic"


def test_declines_when_genuinely_ambiguous() -> None:
    """Rule 6. A bare token is a surname or a firm's short form. Say so."""
    lex = learn_head_nouns(_corpus_names())
    for name in ("Lopez", "Whitfield", "Vance"):
        assert entity_type(name, lex) == "unknown", name


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
