"""Corpus-fitted heuristics retired from the production path (RESEARCH ONLY).

Each of these was tuned against the synthetic corpus and encodes our own
generator's phrasing rather than a property of insurance notes. They are kept
here so their contribution can still be measured, and so the reasoning behind
removing them is not lost with the code.

Nothing in the pipeline imports this module.
"""
from __future__ import annotations

import re

# --- Retired: note-category classifier -----------------------------------
# Keyword-count classification into eight fixed categories. The keyword lists
# were written against generated notes; the category set is not one the client
# uses, and nothing downstream read `category_implied`.
CATEGORY_KEYWORDS = {
    "medical_management": ["tx", "treatment", "records", "physician", "provider", "npi", "surgery"],
    "legal_litigation": ["demand", "counsel", "attorney", "litigation", "suit", "deposition"],
    "siu_investigation": ["suspect", "siu", "fraud", "investigat", "inflating"],
    "repair_estimate": ["repair", "parts", "estimate", "shop", "collision", "body"],
    "payment": ["payment", "paid", "check", "issued", "reserve"],
    "subrogation": ["subro", "subrogation", "recovery", "lien"],
    "plan_of_action": ["poa", "plan of action", "spoke w", "follow up", "next call"],
    "general_correspondence": ["correspondence", "email", "letter"],
}


def classify_category(text: str) -> str:
    low = text.lower()
    best, best_score = "general_correspondence", 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = sum(low.count(k) for k in kws)
        if score > best_score:
            best, best_score = cat, score
    return best


# --- Retired: synthetic-corpus identity patterns -------------------------
# `CLM0001` / `OCC0001` are shapes our generator invented. Real claim and
# occurrence numbers arrive from the client's records (filename + join table),
# so recovering them from note text is both unnecessary and unsafe.
CLAIM_RE = re.compile(r"\bCLM\d{4}\b")
OCC_RE = re.compile(r"\bOCC\d{4}\b")
CATEGORY_HEADER_RE = re.compile(r"^\[([A-Z_]+)\]")

# --- Retired: line-shape segmentation rules ------------------------------
# `SIG_MARK_RE` matched only a bare '--' line (the Usenet signature
# convention, which Outlook does not emit) and drove a latch that was never
# cleared. `EMAIL_HEADER_RE` is the one rule here that does generalize, but it
# fed only segment kinds nothing consumed.
SIG_MARK_RE = re.compile(r"^\s*--\s*$")
EMAIL_HEADER_RE = re.compile(r"^\s*(From|Sent|To|Cc|Bcc|Subject|Date)\s*:", re.I)

# --- Retired: exact-phrase boilerplate whitelist -------------------------
# Superseded by `profiling.boilerplate_score`, which scores a cue bundle
# instead of demanding one of three literal phrases.
BOILER_RE = re.compile(r"CONFIDENTIALITY NOTICE|intended recipient|privileged", re.I)
