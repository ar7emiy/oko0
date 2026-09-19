"""Structural type of a name: person, organization, or unknown.

WHY NOT A CONTEXT CLASSIFIER
----------------------------
v0 derived a five-value `entity_class` from surrounding context. Measured, it
disagreed with itself on **69% of real entities** and on **30% of identical
surface strings** -- the exact text "lucas martinez" came back as attorney,
claimant, medical_provider AND repair_shop. Context encodes **role**, which
genuinely varies sentence to sentence, so it can never answer a question that
must stay constant.

Type must be stable, so it is computed from the name text alone. Identical
strings type identically, by construction.

WHY THE VOCABULARY IS LEARNED, NOT LISTED
-----------------------------------------
The first version of this module hardcoded a list of business words (`center`,
`therapy`, `collision`, ...). Measured against realistic adversarial names it
failed in **both** directions:

    Dr. Paul Frame      -> organization   (13 of 14 real people mistyped)
    Dr. Lisa Spine      -> organization
    Marcus Law          -> organization
    Ashford Acupuncture -> person         (6 of 6 unlisted specialties missed)

Any hand-written list is a snapshot of one corpus. The next client has
acupuncture, podiatry, naturopathy and a surname you did not think of.

So only genuinely CLOSED vocabulary is hardcoded here -- legal forms defined by
statute, and personal titles. The open-ended part (business/head nouns) is
LEARNED from the corpus by `learn_head_nouns`.

RECORDED ERROR: the first learning signal was wrong
---------------------------------------------------
The first version of `learn_head_nouns` used recurrence in trailing position:
"a head noun recurs as the trailing token across many otherwise-different names;
a surname does not behave that way." **That claim was false**, and measuring it
said so immediately -- the lexicon it learned was

    anderson, brown, clark, davis, garcia, gonzalez, jones, martinez, miller,
    smith, taylor, williams, wilson, ...   (52 tokens, mostly surnames)

because "Anderson" trails William, Samuel and Andrew for exactly the same reason
"Center" trails Thomas, Lopez and Vance. Typing accuracy on the 468 labeled
entities was **22%**; person recall was **10.4%**.

The separating signal is POSITION, not frequency. A head noun is grammatically
incapable of leading a name -- there is no "Center Thomas". A surname leads one
freely: "Anderson Automotive", "Vance Chiropractic". Measured over the corpus:

    center 0 leads / 13 trails      anderson 1 lead / 15 trails
    automotive 0 / 10               davis    2 / 11
    therapy 0 / 4                   vance    5 / 8

Requiring **zero** leading occurrences cut the lexicon 52 -> 17 and took typing
to **88.7%** (person recall 88.1%, org recall unchanged at 92.4%). Relaxing it
to "leads at most once" gave back 60.9% -- so it is the strict form that works.

TYPE IS NEVER A VETO
--------------------
Even a perfect lexicon mistypes something, so type selects the comparison
STRATEGY -- it does not decide whether two names may be compared at all. v0
learned this the expensive way: its `person_vs_org` veto was wrong 70% of the
time and blocked 898 correct merges. See `comparison_strategy`.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# --- CLOSED vocabulary: safe to hardcode ------------------------------------
# Legal forms are defined by statute, finite, and not client-specific.
_LEGAL_FORMS = {
    "llp", "llc", "inc", "pc", "pllc", "ltd", "corp", "plc", "lp", "pa",
}

# Personal titles and post-nominals. Small, stable, and near-decisive.
_PERSON_TITLES = {"dr", "mr", "mrs", "ms", "miss", "prof", "rev", "hon", "sgt",
                  "officer", "atty"}
_PERSON_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "do", "esq", "phd",
                    "rn", "np", "dds", "dc", "lcsw", "pt"}

# --- OPEN vocabulary: a seed only, superseded by the learned lexicon ---------
# Deliberately tiny. It exists so the module is not useless before a corpus has
# been scanned; it is NOT meant to be exhaustive, and growing it by hand is the
# failure mode this design rejects. Pass a learned lexicon instead.
_SEED_HEAD_NOUNS = {
    "group", "associates", "partners", "center", "centre", "clinic", "services",
    "institute", "hospital", "company", "agency", "firm",
}

_WORD = re.compile(r"[A-Za-z&'’.\-]+")


def _tokens(name: str) -> list[str]:
    return [t.strip(".,'’").lower()
            for t in _WORD.findall(name or "") if t.strip(".,'’")]


def learn_head_nouns(names, min_distinct: int = 3,
                     max_leading: int = 0) -> set[str]:
    """Derive this corpus's organisation head nouns from the names themselves.

    THE SIGNAL, and why it needs no domain knowledge: an organisation head noun
    is a word that can only ever END a name. English will not produce "Center
    Thomas" or "Automotive Vance". A surname has no such restriction -- it leads
    ("Anderson Automotive") as readily as it trails ("William Anderson").

    So a token qualifies when it (a) ends at least `min_distinct` DIFFERENT
    multi-word names, and (b) leads no more than `max_leading` of them. The
    default of zero is deliberate and measured: at 0 the lexicon is 17 tokens
    and typing is 88.7% correct; at 1 it is 32 tokens and 60.9%. Recurrence
    alone -- the first thing I tried -- scores 22%. See the module docstring.

    This is what makes the system tunable to a client rather than to this
    fixture: run it over their names and it discovers their vocabulary --
    acupuncture, podiatry, whatever they actually have, with no list to edit.

    KNOWN RESIDUAL: a surname that happens never to lead a name in the corpus at
    hand is admitted anyway. Six are, here (`garcia`, `gonzalez`, `hernandez`,
    `jones`, `patel`, `rossi`), and they are most of the remaining 11% of typing
    error. This is a small-sample artifact that weakens as the corpus grows --
    but it is the reason `entity_type` must never become a veto.
    """
    trailing_partners: dict[str, set[str]] = defaultdict(set)
    leading = Counter()
    for name in names:
        toks = _tokens(name)
        if len(toks) < 2:
            continue
        leading[toks[0]] += 1
        trailing_partners[toks[-1]].add(" ".join(toks[:-1]))

    return {tok for tok, partners in trailing_partners.items()
            if len(partners) >= min_distinct and leading[tok] <= max_leading}


def entity_type(name: str, head_nouns: set[str] | None = None) -> str:
    """'person' | 'organization' | 'unknown', from the name string alone.

    `head_nouns` is the learned lexicon; without one a small seed is used and
    accuracy on unfamiliar business vocabulary will be poor -- by design, rather
    than by pretending a hardcoded list generalises.
    """
    raw = (name or "").strip()
    toks = _tokens(raw)
    if not toks:
        return "unknown"

    # TITLES FIRST. A title is near-decisive for a person, and checking it after
    # the organisation test is precisely how "Dr. Paul Frame" and "Dr. Lisa
    # Spine" were typed as organisations -- the org check consumed them before
    # the title was ever consulted.
    if toks[0] in _PERSON_TITLES or toks[-1] in _PERSON_SUFFIXES:
        return "person"

    # Legal form is conclusive and closed.
    if any(t in _LEGAL_FORMS for t in toks):
        return "organization"

    # An ampersand joins two named parties into one body: "Okafor Frame & Paint",
    # "Harbor & Vance". People are not named with one.
    if "&" in raw:
        return "organization"

    lex = head_nouns if head_nouns is not None else _SEED_HEAD_NOUNS
    # Only the TRAILING token is tested against the lexicon. A head noun is a
    # head noun by position; testing every token is what made "Marcus Law" and
    # "Michael Body" organisations.
    if len(toks) >= 2 and toks[-1] in lex:
        return "organization"

    plain = [t for t in toks if t.isalpha()]
    if len(plain) in (2, 3) and len(plain) == len(toks):
        return "person"

    # A bare token ("Lopez", "Whitfield") is genuinely ambiguous -- surname, or
    # a firm's short form. Saying so is the point; guessing is what this module
    # exists to avoid.
    return "unknown"


def comparison_strategy(type_a: str, type_b: str) -> str:
    """How to compare two names -- NOT whether they may be compared.

    Returns 'person', 'organization', or 'generic'.

    THIS DELIBERATELY HAS NO VETO. An earlier version exposed `may_compare`,
    which refused person-vs-organisation outright; that is v0's `person_vs_org`
    constraint, measured wrong 70% of the time and responsible for blocking 898
    correct merges. Combined with a mistyped name it is unrecoverable -- the
    entity can never be linked to itself, and no amount of evidence overrides a
    veto.

    A mistype should cost accuracy, not possibility. So a mismatch falls back to
    the generic strategy, and the identity decision is made on evidence.
    """
    if type_a == type_b and type_a in ("person", "organization"):
        return type_a
    if "unknown" in (type_a, type_b):
        known = type_b if type_a == "unknown" else type_a
        return known if known in ("person", "organization") else "generic"
    return "generic"
