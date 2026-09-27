# ---- Matching core v1.1: parameters and field definitions ---------------------------------
# Ported pieces carry a header naming their source in goko-v2-poc/goko_v2_poc.ipynb.
import math, re, unicodedata, hashlib, json
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import numpy as np
import pandas as pd
import jellyfish
import recordlinkage as rl
from rapidfuzz import fuzz as _rf_fuzz
from rapidfuzz.distance import JaroWinkler as _rf_jw, Levenshtein as _rf_lev

CORE_VERSION = "1.1"


@dataclass
class CoreParams:
    """Every number the core uses. The caller's run configuration embeds one of these and the
    manifest dumps it: there are no thresholds anywhere else in the core."""
    # name similarity: several measures, combined into graded levels (v1.1)
    jw_close: float = 0.92          # Jaro-Winkler at or above: a spelling variant (goko cell 18)
    lev_close: float = 0.85         # normalized Levenshtein similarity at or above: a spelling variant
    tsr_close: float = 90.0         # rapidfuzz token_sort_ratio at or above: reordered parts
    jw_sound: float = 0.85          # Jaro-Winkler at or above (below close): sounds alike
    lev_sound: float = 0.75         # normalized Levenshtein at or above (below close): sounds alike
    org_rare_idf: float = 10.0      # bits: a word fewer than ~1 in 1,000 organizations use
    org_distinct_min_len: int = 4   # a distinctive org word has at least this many letters
    org_close_sim: float = 0.75     # rarity-weighted share of the name's words that agree (v1.1)
    org_close_tsr: float = 85.0     # rapidfuzz token_set_ratio at or above, with org_close_sim
    surname_floor: int = 50         # count for a surname below the Census cutoff (goko cell 16)
    firstname_floor: int = 20       # count for a first name below the SSA cutoff
    org_df_floor: int = 1           # organizations using a word absent from NPPES
    own_org_min_count: int = 5      # the reference population's own word share counts from this many users
    flat_freq: float = 1e-3         # used only when an outside table is missing; stamped FLAT
    alpha: float = 5.0              # shrinkage of an m estimate toward the next source (prior chain)
    n_min: int = 50                 # informative pairs below which simulation joins the chain
    em_max_iter: int = 300
    em_tol: float = 1e-8
    em_prior_strength: float = 20.0  # Dirichlet (multi-level Beta) pseudo-pairs on m in EM (v1.1)
    m_floor: float = 0.005          # no level's m below this: bounds every disagreement weight (v1.1)
    bits_min: float = -10.0         # no single field counts below this many bits (v1.1)
    bits_max: float = 40.0          # ... or above this many
    unstable_ci_bits: float = 3.0   # bootstrap 95% interval wider than this (bits): flagged unstable
    unstable_pass_bits: float = 3.0  # training passes disagreeing by more than this (bits): flagged
    u_pseudo: float = 0.5           # pseudo-count for a level never seen among random pairs
    prior_pseudo: float = 0.5       # pseudo-count for a prior group with no strict pair
    junk_holders: int = 25          # a value held under more names than this is junk
    u_floor: float = 1e-12
    dob_min_year: int = 1900
    dob_max_year: int = 2026        # dates after this year are invalid (fixed for determinism)
    coparty_min_p: float = 0.9      # a business link must reach this to anchor a co-party
    ci_z: float = 1.96              # 95% intervals


# Fields per part, and their levels best-first. Every field also has a NULL level (-1): one
# side has nothing to compare. It is Splink's null level: excluded from m and u, worth 0 bits.
EMPTY = -1
FIELD_LEVELS = {
    "name": ["exact", "first_nick", "first_close", "last_close_first_agrees",
             "last_sound_first_agrees", "initial_agrees", "swapped", "first_empty",
             "last_fuzzy_first_weak", "first_differs", "else"],
    "middle": ["exact", "initial", "differs"],
    "org": ["exact", "dba", "short_form", "close", "rare_shared", "common_shared", "sibling", "none"],
    "dob": ["exact", "swap_or_typo", "year_month", "year", "differs"],
    "address": ["exact", "street", "zip", "city_state", "state", "differs"],
    "ssn": ["exact", "near", "differs"],
    "npi": ["exact", "near", "differs"],
    "dl": ["exact", "near", "differs"],
    "tin": ["exact", "near", "differs"],
    "license": ["exact", "differs"],
    "email": ["exact", "differs"],
    "vin": ["exact", "differs"],
    "plate": ["exact", "differs"],
    "cnpi": ["exact", "differs"],
    "phone": ["exact_owned_single", "exact_shared", "differs"],
    "spec_cat": ["specialty", "category_id", "category_weak", "differs"],
    "co_party": ["anchored", "not_anchored"],
}
PART_FIELDS = {
    "person": ["name", "middle", "dob", "address", "ssn", "npi", "dl", "license", "email",
               "vin", "plate", "phone", "spec_cat", "co_party"],
    "business": ["org", "address", "tin", "cnpi", "email", "phone", "spec_cat"],
}
COMPARED_FIELDS = {p: [f for f in fs if f != "co_party"] for p, fs in PART_FIELDS.items()}
# Correlated fields are compared as one graded group each, never as independent fields, so
# nothing is counted twice: first + last name (one `name` level; `middle` is compared only when
# the surnames agree, with its u taken among such pairs), organization aliases, the address
# (number/street/unit/ZIP/city/state), and specialty + category.
FIELD_GROUPS = {"name": ["first", "last", "middle (conditional on the surname)"],
                "org": ["every alias, d/b/a"],
                "address": ["number", "street", "unit", "zip", "city", "state"],
                "spec_cat": ["specialty", "category"]}
# Levels that mean "agrees": their bits never go below 0, so an extra agreeing field can
# never lower p.
AGREEMENT_LEVELS = {
    "name": {"exact", "first_nick", "first_close", "last_close_first_agrees",
             "last_sound_first_agrees", "initial_agrees", "swapped"},
    "middle": {"exact", "initial"}, "org": {"exact", "dba", "short_form", "close", "rare_shared"},
    "dob": {"exact", "swap_or_typo"}, "address": {"exact", "street"},
    "ssn": {"exact", "near"}, "npi": {"exact", "near"}, "dl": {"exact", "near"},
    "tin": {"exact", "near"}, "license": {"exact"}, "email": {"exact"}, "vin": {"exact"},
    "plate": {"exact"}, "cnpi": {"exact"}, "phone": {"exact_owned_single", "exact_shared"},
    "spec_cat": {"specialty", "category_id", "category_weak"}, "co_party": {"anchored"},
}
# Levels that mean "disagrees": their bits never go above 0 (a sparse level can otherwise come
# out with m > u by chance, and a disagreement must never count for a match).
DISAGREEMENT_LEVELS = {
    "name": {"else"}, "middle": {"differs"}, "org": {"sibling", "none"}, "dob": {"differs"},
    "address": {"differs"}, "ssn": {"differs"}, "npi": {"differs"}, "dl": {"differs"},
    "tin": {"differs"}, "license": {"differs"}, "email": {"differs"}, "vin": {"differs"},
    "plate": {"differs"}, "cnpi": {"differs"}, "phone": {"differs"}, "spec_cat": {"differs"},
}
# Levels whose bits are forced to 0: no evidence either way, by declaration.
ZERO_LEVELS = {"co_party": {"not_anchored"}}
IDENTIFIER_FIELDS = ["ssn", "npi", "dl", "tin", "license", "email", "vin", "plate", "cnpi", "phone"]
VETO_FIELDS = ["ssn", "npi", "dl", "tin"]          # one per party: two single-holder values veto
NEAR_FIELDS = {"ssn", "npi", "dl", "tin"}
NAME_FIELDS = {"name", "org"}
BASIS_ORDER = ["identifier", "address", "dob", "co_party", "contextual", "name_only", "none"]


def level_code(field_, level):
    return FIELD_LEVELS[field_].index(level)
