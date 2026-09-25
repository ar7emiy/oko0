# %% [markdown]
# ## Matching core v1.0
#
# **This section is the matching core.** It is identical code in [B] (this notebook) and,
# later, in [A] (goko-v2-poc). The self-test section hashes every code cell between this
# heading and the "End of the matching core" marker and compares the hash with the recorded
# value, so any drift between the two systems is caught. Change it only deliberately: bump
# `CORE_VERSION`, re-record the hash, and copy the section to [A].
#
# **Contract.** Plain tables in, plain tables out. Nothing here reads a file, writes a
# spreadsheet or knows about note text. The caller builds a *party frame* per side, one row per
# party, with these columns (empty string when unknown):
#
# | Column | Meaning |
# |---|---|
# | `party_id`, `part` | stable id; `person` or `business` |
# | `first`, `middle`, `last` | cleaned name parts (`clean_person`) |
# | `first_roots`, `last_nysiis`, `name_key` | nickname roots (`|`-joined), NYSIIS of the surname, `FIRST LAST` |
# | `holder_key` | who holds a value, for single-holder counts: `LAST|F` (surname and first initial) for a person, the first alias for a business |
# | `org_aliases`, `name_key` (business) | `|`-joined aliases from `org_aliases`; first alias is the name key |
# | `dob`, `dob_int` | ISO date; `YYYYMMDD` as int (0 = none) |
# | `addr_full`, `addr_street`, `zip`, `city_state`, `state` | address keys (`address_keys`) |
# | `id_ssn` `id_npi` `id_dl` `id_tin` `id_license` `id_email` `id_vin` `id_plate` `id_cnpi` | valid, non-junk identifier values |
# | `phone_own`, `phone_row` | a phone the party owns; a phone its row holds |
# | `specialty`, `category`, `cat_strength` | canonical specialty; category; `strong` or `weak` |
# | `tie` | `party_id` of the other part of the same row, or empty |
#
# Pairs are positional: `il[i]` indexes the left frame, `ir[i]` the right one. The right frame
# is the reference population whose value frequencies give per-value `u` (the watchlist in [B]).
#
# **Where Splink would do better (whole core).** Splink compiles comparisons to SQL and runs
# them in DuckDB or Spark, so 1M x 300k is routine and multi-core by default; here numpy and
# per-unique-value Python loops do the work on one core. Splink's comparison library has
# tested levels for names, dates and addresses; the levels below are hand-written. Splink
# draws a waterfall chart per pair; the evidence table below is its tabular equivalent.

# %%
# ---- Matching core v1.0: parameters and field definitions ---------------------------------
# Ported pieces carry a header naming their source in goko-v2-poc/goko_v2_poc.ipynb.
import math, re, unicodedata, hashlib, json
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import numpy as np
import pandas as pd
import jellyfish
import recordlinkage as rl

CORE_VERSION = "1.0"


@dataclass
class CoreParams:
    """Every number the core uses. The caller's run configuration embeds one of these and the
    manifest dumps it: there are no thresholds anywhere else in the core."""
    jw_close: float = 0.92          # Jaro-Winkler at or above: a spelling variant (goko cell 18)
    org_rare_idf: float = 10.0      # bits: a word fewer than ~1 in 1,000 organizations use
    org_distinct_min_len: int = 4   # a distinctive org word has at least this many letters
    surname_floor: int = 50         # count for a surname below the Census cutoff (goko cell 16)
    firstname_floor: int = 20       # count for a first name below the SSA cutoff
    org_df_floor: int = 1           # organizations using a word absent from NPPES
    own_org_min_count: int = 5      # the reference population's own word share counts from this many users
    flat_freq: float = 1e-3         # used only when an outside table is missing; stamped FLAT
    alpha: float = 5.0              # shrinkage of an m estimate toward the next source
    n_min: int = 50                 # informative pairs below which simulation joins the chain
    em_max_iter: int = 300
    em_tol: float = 1e-8
    u_pseudo: float = 0.5           # pseudo-count for a level never seen among random pairs
    prior_pseudo: float = 0.5       # pseudo-count for a prior group with no strict pair
    junk_holders: int = 25          # a value held under more names than this is junk
    u_floor: float = 1e-12
    dob_min_year: int = 1900
    dob_max_year: int = 2026        # dates after this year are invalid (fixed for determinism)
    coparty_min_p: float = 0.9      # a business link must reach this to anchor a co-party
    ci_z: float = 1.96              # 95% intervals


# Fields per part, and their levels best-first. Every field also has an EMPTY level (-1),
# worth 0 bits: one side has nothing to compare.
EMPTY = -1
FIELD_LEVELS = {
    "name": ["exact", "first_nick_or_close", "last_close_first_agrees", "initial_agrees",
             "swapped", "first_empty", "first_differs", "else"],
    "middle": ["exact", "initial", "differs"],
    "org": ["exact", "dba", "short_form", "rare_shared", "common_shared", "sibling", "none"],
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
# Levels that mean "agrees": their bits never go below 0, so an extra agreeing field can
# never lower p.
AGREEMENT_LEVELS = {
    "name": {"exact", "first_nick_or_close", "last_close_first_agrees", "initial_agrees", "swapped"},
    "middle": {"exact", "initial"}, "org": {"exact", "dba", "short_form", "rare_shared"},
    "dob": {"exact", "swap_or_typo"}, "address": {"exact", "street"},
    "ssn": {"exact", "near"}, "npi": {"exact", "near"}, "dl": {"exact", "near"},
    "tin": {"exact", "near"}, "license": {"exact"}, "email": {"exact"}, "vin": {"exact"},
    "plate": {"exact"}, "cnpi": {"exact"}, "phone": {"exact_owned_single", "exact_shared"},
    "spec_cat": {"specialty", "category_id", "category_weak"}, "co_party": {"anchored"},
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

# %%
# ---- Matching core v1.0: normalizers ------------------------------------------------------
# Ported from goko-v2-poc/goko_v2_poc.ipynb cell "## 16" (parse_person, _undot, _words,
# org_aliases, ORG_ABBREV, ORG_LEGAL, TITLES, CREDENTIALS, name_like) and cell "## 18"
# (_rejoin, _org_alias_bits, _distinctive, declared d/b/a). Adapted: names arrive in parts.

TITLES = {"DR", "DOCTOR", "MR", "MRS", "MS", "MISS", "HON", "JUDGE", "PROF"}
CREDENTIALS = {"MD", "DO", "DC", "DPM", "DDS", "DMD", "PHD", "PT", "DPT", "NP", "PA", "RN",
               "LPN", "LAC", "ESQ", "JD", "CPA", "OT", "OTR", "FACS", "FACP", "MPH", "LCSW",
               "PSYD"}
BARE_CREDENTIALS = CREDENTIALS - {"DO", "PA", "PT", "OT"}
NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV"}
ORG_LEGAL = {"PC", "PLLC", "LLC", "INC", "CORP", "CORPORATION", "CO", "LTD", "LLP", "LP",
             "PA", "COMPANY", "INCORPORATED", "THE", "AND", "OF"}
ORG_ABBREV = {"INS": "INSURANCE", "MED": "MEDICAL", "CTR": "CENTER", "CNTR": "CENTER",
              "SVCS": "SERVICES", "SVC": "SERVICES", "ASSOC": "ASSOCIATES", "ASSN": "ASSOCIATION",
              "HOSP": "HOSPITAL", "MGMT": "MANAGEMENT", "INTL": "INTERNATIONAL", "NATL": "NATIONAL",
              "DIAG": "DIAGNOSTIC", "REHAB": "REHABILITATION", "PHYS": "PHYSICAL", "THER": "THERAPY",
              "CHIRO": "CHIROPRACTIC", "GRP": "GROUP", "SVS": "SERVICES", "LAB": "LABORATORY",
              "LABS": "LABORATORIES", "PHARM": "PHARMACY", "TRANS": "TRANSPORTATION"}
ROLE_WORDS_UP = {"DEFENDANT", "DEFENDANTS", "PLAINTIFF", "PLAINTIFFS", "ANSWERING", "CLAIMANT",
                 "CLAIMANTS", "INSURED", "COUNSEL", "ATTORNEY", "RESPONDENT", "PETITIONER", "THE",
                 "HIS", "HER", "THEIR"}
_DBA_RE = re.compile(r"\b(?:d\s*/\s*b\s*/\s*a|dba|a\s*/\s*k\s*/\s*a|aka|f\s*/\s*k\s*/\s*a|fka|"
                     r"doing business as|trading as|t\s*/\s*a)\b", re.I)


def fold(s):
    """Uppercase ASCII: accents dropped ('JOSÉ' -> 'JOSE'), whitespace collapsed."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def _undot(s):
    """'M.D.' -> 'MD', 'P.C.' -> 'PC', then any remaining dot is a space ('A.' -> 'A')."""
    s = re.sub(r"\b((?:[A-Za-z]{1,2}\.){2,})", lambda m: m.group(1).replace(".", ""), s)
    return s.replace(".", " ")


def _words(s):
    return [w.upper() for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", s)]


def parse_person(name):
    """goko cell 16: split a full name into first / middle initial / last, with credentials.
    Handles 'Dr. A. Monroe', 'WILLIAM A. WEINER, D.O.', 'Moy, Marvin' and 'Mr. Pierre'."""
    s = _undot(fold(name))
    head, _, tail = s.partition(",")
    hw, tw = _words(head), _words(tail)
    creds = {w for w in tw if w in CREDENTIALS} | {w for w in hw[1:] if w in BARE_CREDENTIALS}
    title = next((w for w in hw if w in TITLES), None)
    drop = TITLES | CREDENTIALS | NAME_SUFFIXES | ROLE_WORDS_UP
    core_h = [w.strip("'-") for w in hw if w not in drop]
    core_t = [w.strip("'-") for w in tw if w not in drop]
    core = core_t + core_h if (len(core_h) == 1 and core_t) else core_h
    core = [w for w in core if w]
    first = middle = last = ""
    if len(core) == 1:
        last = core[0]
    elif len(core) >= 2:
        first, last = core[0], core[-1]
        middle = core[1][0] if len(core) > 2 else ""
    return {"first": first, "middle": middle, "last": last, "creds": sorted(creds), "title": title}


def _clean_part(s, drop_creds=True):
    words = [w.replace("'", "").strip("-") for w in _words(_undot(fold(s)))]
    drop = TITLES | NAME_SUFFIXES | (BARE_CREDENTIALS if drop_creds else set())
    return " ".join(w for w in words if w and w not in drop)


def clean_person(first, middle, last):
    """Cleaned (first, middle, last) from name parts as a form holds them.

    'Dr. John' -> 'JOHN'; 'SMITH JR' -> 'SMITH'; "O'Brien" -> 'OBRIEN'. A full name typed into
    one box is split with parse_person: 'SMITH, JOHN' in last, or 'JOHN SMITH' in first with
    no last."""
    f, m, l = fold(first), fold(middle), fold(last)
    if not l and f and len(_words(f)) >= 2 and not m:
        p = parse_person(f)
        f, m, l = p["first"], p["middle"], p["last"]
    elif l and not f and "," in l:
        p = parse_person(l)
        f, m, l = p["first"], p["middle"], p["last"]
    return _clean_part(f), _clean_part(m), _clean_part(l)


def org_aliases(name):
    """goko cell 16: name variants of one organization: d/b/a parts split, legal suffixes
    stripped, abbreviations expanded. Returns a list of word lists."""
    out = []
    for p in _DBA_RE.split(fold(name)):
        toks = re.findall(r"[A-Z0-9]+", _undot(p).upper().replace("'", "").replace("&", " AND "))
        joined, i = [], 0
        while i < len(toks):                     # OCR splits a suffix ('COMP ANY'): rejoin it
            if i + 1 < len(toks) and toks[i] + toks[i + 1] in ORG_LEGAL:
                joined.append(toks[i] + toks[i + 1]); i += 2
            else:
                joined.append(toks[i]); i += 1
        toks = [ORG_ABBREV.get(t, t) for t in joined]
        toks = [t for t in toks if len(t) > 1 and t not in ORG_LEGAL and t not in ROLE_WORDS_UP]
        if toks and toks not in out:
            out.append(toks)
    # a short form that is a subset of a longer alias adds nothing (goko build_mention)
    keep = [a for a in out if not any(set(a) < set(b) for b in out)] or out
    return keep


def org_alias_string(name):
    """'|'-joined aliases, each alias its words joined by a space: the party-frame form."""
    return "|".join(" ".join(a) for a in org_aliases(name))


# ---- identifiers ---------------------------------------------------------------------------
def _digits(s):
    return re.sub(r"\D", "", fold(s))


def _all_same(d):
    return len(set(d)) <= 1


_SEQ = {"123456789", "987654321", "1234567890", "0123456789", "012345678"}


def norm_ssn(s):
    """(value, valid, reason). Invalid: not 9 digits, area 000/666/9xx, group 00, serial 0000,
    one repeated digit, or a sequence."""
    d = _digits(s)
    if not d:
        return "", False, ""
    if len(d) != 9:
        return d, False, "length"
    if d[:3] in ("000", "666") or d[0] == "9" or d[3:5] == "00" or d[5:] == "0000":
        return d, False, "range"
    if _all_same(d) or d in _SEQ:
        return d, False, "placeholder"
    return d, True, ""


_BAD_EIN_PREFIX = {"00", "07", "08", "09", "17", "18", "19", "28", "29", "49", "69", "70", "78",
                   "79", "89", "96", "97"}


def norm_tin(s):
    d = _digits(s)
    if not d:
        return "", False, ""
    if len(d) != 9:
        return d, False, "length"
    if _all_same(d) or d in _SEQ:
        return d, False, "placeholder"
    if d[:2] in _BAD_EIN_PREFIX:
        return d, False, "prefix"
    return d, True, ""


def npi_luhn_ok(d):
    """NPI check digit: Luhn over '80840' + the first nine digits."""
    if len(d) != 10 or not d.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + d[:9])):
        v = int(ch)
        if i % 2 == 0:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    return (10 - total % 10) % 10 == int(d[9])


def norm_npi(s):
    d = _digits(s)
    if not d or not d.strip("0"):
        return "", False, ""                       # LEIE writes 0000000000 for "none"
    if len(d) != 10:
        return d, False, "length"
    if not npi_luhn_ok(d):
        return d, False, "check_digit"
    return d, True, ""


def norm_phone(s):
    d = _digits(s)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if not d:
        return "", False, ""
    if len(d) != 10:
        return d, False, "length"
    if d[0] in "01" or d[3] in "01":
        return d, False, "range"
    if _all_same(d) or d in _SEQ or (d[3:6] == "555" and d[6:8] == "01"):
        return d, False, "placeholder"
    return d, True, ""


_JUNK_EMAIL_LOCAL = {"none", "na", "n/a", "noemail", "no", "unknown", "test", "noreply",
                     "nomail", "declined", "null", "email"}


def norm_email(s):
    e = str(s or "").strip().lower()
    if not e or e in ("nan",):
        return "", False, ""
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e):
        return e, False, "format"
    local, dom = e.split("@", 1)
    if local in _JUNK_EMAIL_LOCAL or dom.split(".")[0] in ("none", "na", "unknown", "noemail"):
        return e, False, "placeholder"
    return e, True, ""


def _alnum(s):
    return re.sub(r"[^A-Z0-9]", "", fold(s))


US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "PUERTO RICO": "PR", "GUAM": "GU", "VIRGIN ISLANDS": "VI", "AMERICAN SAMOA": "AS",
    "NORTHERN MARIANA ISLANDS": "MP"}
STATE_CODES = set(US_STATES.values()) | {"AA", "AE", "AP"}


def norm_state(s):
    t = re.sub(r"[^A-Z ]", "", fold(s)).strip()
    if t in STATE_CODES:
        return t
    return US_STATES.get(t, "")


def _qualified(number, state, min_len=4):
    """'STATE:NUMBER' (or ':NUMBER' when no state). Invalid when too short or one repeated
    character."""
    n = _alnum(number)
    if not n:
        return "", False, ""
    st = norm_state(state)
    v = f"{st}:{n}"
    if len(n) < min_len:
        return v, False, "length"
    if _all_same(n) or not n.strip("0"):
        return v, False, "placeholder"
    return v, True, ""


def norm_dl(number, state):
    return _qualified(number, state, 4)


def norm_license(number, state):
    return _qualified(number, state, 3)


def norm_plate(number, state):
    return _qualified(number, state, 2)


_VIN_MAP = {**{str(i): i for i in range(10)},
            "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "J": 1, "K": 2,
            "L": 3, "M": 4, "N": 5, "P": 7, "R": 9, "S": 2, "T": 3, "U": 4, "V": 5, "W": 6,
            "X": 7, "Y": 8, "Z": 9}
_VIN_W = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def vin_check_ok(v):
    if len(v) != 17 or any(c not in _VIN_MAP for c in v):
        return False
    r = sum(_VIN_MAP[c] * w for c, w in zip(v, _VIN_W)) % 11
    return v[8] == ("X" if r == 10 else str(r))


def norm_vin(s):
    v = _alnum(s)
    if not v:
        return "", False, ""
    if len(v) != 17 or set(v) & set("IOQ"):
        return v, False, "format"
    if not vin_check_ok(v):
        return v, False, "check_digit"
    return v, True, ""


_PLACEHOLDER_DOB = {"1900-01-01", "1901-01-01", "1899-12-31", "1800-01-01", "9999-12-31",
                    "1111-11-11", "1910-01-01"}


def norm_dob(s, params=None):
    """(ISO date, valid, reason). Accepts ISO, US m/d/y (2-digit years pivot at the max year),
    YYYYMMDD. Placeholders (1900-01-01 ...), impossible and future dates are invalid."""
    p = params or CoreParams()
    t = str(s or "").strip()
    if not t or t.lower() == "nan":
        return "", False, ""
    t = t.split("T")[0].split(" ")[0]
    y = m = d = None
    if re.fullmatch(r"\d{8}", t):
        y, m, d = int(t[:4]), int(t[4:6]), int(t[6:])
    elif re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", t):
        y, m, d = (int(x) for x in re.split(r"[-/.]", t))
    elif re.fullmatch(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", t):
        m, d, y = (int(x) for x in re.split(r"[-/.]", t))
        if y < 100:
            y += 1900 if y > p.dob_max_year % 100 else 2000
    else:
        return t, False, "format"
    try:
        iso = pd.Timestamp(year=y, month=m, day=d).strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return t, False, "impossible"
    if iso in _PLACEHOLDER_DOB:
        return iso, False, "placeholder"
    if y < p.dob_min_year or y > p.dob_max_year:
        return iso, False, "range"
    return iso, True, ""


# ---- addresses -----------------------------------------------------------------------------
STREET_TYPES = {"STREET": "ST", "STR": "ST", "ST": "ST", "AVENUE": "AVE", "AV": "AVE", "AVE": "AVE",
                "BOULEVARD": "BLVD", "BLVD": "BLVD", "ROAD": "RD", "RD": "RD", "DRIVE": "DR",
                "DR": "DR", "LANE": "LN", "LN": "LN", "COURT": "CT", "CT": "CT", "PLACE": "PL",
                "PL": "PL", "TERRACE": "TER", "TER": "TER", "PARKWAY": "PKWY", "PKWY": "PKWY",
                "HIGHWAY": "HWY", "HWY": "HWY", "CIRCLE": "CIR", "CIR": "CIR", "WAY": "WAY",
                "TRAIL": "TRL", "TRL": "TRL", "SQUARE": "SQ", "SQ": "SQ", "PLAZA": "PLZ",
                "PLZ": "PLZ", "COVE": "CV", "CV": "CV", "EXPRESSWAY": "EXPY", "EXPY": "EXPY",
                "TURNPIKE": "TPKE", "TPKE": "TPKE", "ALLEY": "ALY", "ALY": "ALY", "LOOP": "LOOP",
                "PIKE": "PIKE", "ROW": "ROW", "WALK": "WALK", "PATH": "PATH", "RUN": "RUN",
                "CROSSING": "XING", "XING": "XING", "POINT": "PT", "PT": "PT", "RIDGE": "RDG",
                "RDG": "RDG"}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
              "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW", "N": "N", "S": "S",
              "E": "E", "W": "W", "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW"}
UNIT_WORDS = {"APT", "APARTMENT", "UNIT", "STE", "SUITE", "RM", "ROOM", "FL", "FLOOR", "BLDG",
              "LOT", "SPC", "SPACE", "TRLR", "DEPT", "#"}
_CITY_PREFIX = {"ST": "SAINT", "FT": "FORT", "MT": "MOUNT"}


def _addr_words(s):
    return re.sub(r"[^A-Z0-9# ]", " ", _undot(fold(s)).replace("-", " - ")).split()


def norm_street_parts(number, direction, name, stype, unit):
    """Normalized (number, direction, name, type, unit). A type or direction left inside the
    name ('MAIN STREET', 'W TAYLOR') is moved to its own part."""
    num = re.sub(r"[^A-Z0-9\-]", "", fold(number))
    words = [w for w in _addr_words(name) if w != "-"]
    d = DIRECTIONS.get(fold(direction).replace(".", ""), "")
    t = STREET_TYPES.get(fold(stype).replace(".", ""), fold(stype).replace(".", ""))
    if words and not d and words[0] in DIRECTIONS and len(words) > 1:
        d = DIRECTIONS[words[0]]; words = words[1:]
    if words and not t and words[-1] in STREET_TYPES and len(words) > 1:
        t = STREET_TYPES[words[-1]]; words = words[:-1]
    if words and words[-1] in DIRECTIONS and len(words) > 1:      # post-direction: 'AVE W'
        words = words[:-1]
    u = [w for w in _addr_words(unit) if w not in UNIT_WORDS and w != "-"]
    return num, d, " ".join(words), t, "".join(u)


def parse_street_line(line):
    """'2161 UNIVERSITY AVENUE W, STE 5' -> ('2161', '', 'UNIVERSITY', 'AVE', '5').
    'P O BOX 2161' -> ('2161', '', 'PO BOX', '', '')."""
    s = fold(line)
    if not s:
        return "", "", "", "", ""
    box = re.match(r"^(?:P\s*\.?\s*O\.?\s*BOX|POST OFFICE BOX|BOX)\s*#?\s*([A-Z0-9\-]+)", s)
    if box:
        return box.group(1), "", "PO BOX", "", ""
    main, _, rest = s.partition(",")
    unit = rest.strip()
    m = re.search(r"\s(?:APT|APARTMENT|UNIT|STE|SUITE|RM|ROOM|FL|FLOOR|BLDG|LOT|SPC|#)\s*\.?\s*#?\s*([A-Z0-9\-]+)\s*$", main)
    if m:
        unit = unit or m.group(1)
        main = main[:m.start()]
    elif "#" in main:
        main, _, u2 = main.partition("#")
        unit = unit or u2.strip()
    mnum = re.match(r"^\s*(\d+[A-Z]?(?:-\d+[A-Z]?)?)\s+(.*)$", main.strip())
    num, rest_name = (mnum.group(1), mnum.group(2)) if mnum else ("", main.strip())
    ws = rest_name.split()
    d = ""
    if len(ws) > 2 and ws[0] in ("N", "S") and ws[1] in ("E", "W"):      # 'N W 45TH' -> NW
        ws = [ws[0] + ws[1]] + ws[2:]
    if len(ws) > 1 and ws[0].replace(".", "") in DIRECTIONS:
        d = DIRECTIONS[ws[0].replace(".", "")]; ws = ws[1:]
    t = ""
    if len(ws) > 1 and ws[-1].replace(".", "") in DIRECTIONS:
        ws = ws[:-1]
    if len(ws) > 1 and ws[-1].replace(".", "") in STREET_TYPES:
        t = STREET_TYPES[ws[-1].replace(".", "")]; ws = ws[:-1]
    unit = " ".join(w for w in re.sub(r"[^A-Z0-9 ]", " ", unit).split() if w not in UNIT_WORDS)
    return num, d, " ".join(ws), t, unit.replace(" ", "")


def norm_city(s):
    ws = re.sub(r"[^A-Z ]", " ", _undot(fold(s))).split()
    if ws and ws[0] in _CITY_PREFIX:
        ws[0] = _CITY_PREFIX[ws[0]]
    return " ".join(ws)


def norm_zip(s):
    d = _digits(s)
    if len(d) in (3, 4):
        d = d.zfill(5)                             # a leading zero lost in a spreadsheet
    d = d[:5]
    return d if len(d) == 5 and d != "00000" else ""


def address_keys(number, name, unit, zip5, city, state):
    """The five keys the address levels compare, best first. Each is empty when a part it
    needs is missing."""
    street = f"{number}|{name}" if number and name else ""
    full = f"{street}|{unit}|{zip5}" if street and zip5 else ""
    city_state = f"{city}|{state}" if city and state else ""
    return full, street, zip5, city_state, state


# ---- nicknames and phonetics ---------------------------------------------------------------
class Nicknames:
    """Nickname roots from a (name1, relationship, name2) table (carltonnorthern/nicknames).
    Two first names agree as nicknames when their root sets meet: BILL {BILL, WILLIAM,
    ROBERT, WILL} meets WILLIAM {WILLIAM}."""

    def __init__(self, table):
        roots = defaultdict(set)
        if table is not None and len(table):
            for a, b in zip(table["name1"].map(fold), table["name2"].map(fold)):
                roots[b].add(a)
                roots[a].add(a)
        self._roots = roots
        self.size = len(table) if table is not None else 0

    def roots(self, first):
        f = fold(first).split(" ")[0] if first else ""
        if not f:
            return frozenset()
        return frozenset(self._roots.get(f, set()) | {f})

    def roots_string(self, first):
        return "|".join(sorted(self.roots(first)))


def nysiis(s):
    s = re.sub(r"[^A-Z]", "", fold(s))
    return jellyfish.nysiis(s) if s else ""


def map_unique(values, func):
    """Apply func once per distinct value; values is a Series. Returns a Series."""
    s = pd.Series(values)
    uniq = pd.unique(s)
    table = {v: func(v) for v in uniq}
    return s.map(table)

# %%
# ---- Matching core v1.0: outside rarity -----------------------------------------------------
# Ported from goko-v2-poc/goko_v2_poc.ipynb cell "## 16" (surname_freq, first_freq,
# initial_share, org_idf). Change: org_idf takes the larger of NPPES's share and the reference
# population's own share of a word (PLAN.md open question 5), so AUTO or COLLISION, rare among
# NPPES health-care organizations, are not treated as rare in a list full of body shops.

class Rarity:
    """Value-specific chance agreement from outside tables. Tables arrive as dicts
    {value: count} plus the metadata totals; a missing table gives a flat rate that is stamped
    'FLAT' in the source so the run cannot be mistaken for a real one."""

    def __init__(self, surnames=None, first_names=None, org_df=None, meta=None, params=None,
                 own_org_counts=None, own_org_total=0):
        self.p = params or CoreParams()
        meta = meta or {}
        self.surnames, self.firsts, self.org_df = surnames or {}, first_names or {}, org_df or {}
        self.surname_total = meta.get("census", {}).get("people") or max(1, sum(self.surnames.values()))
        self.first_total = meta.get("ssa", {}).get("births") or max(1, sum(self.firsts.values()))
        self.org_n = meta.get("nppes", {}).get("organizations") or 1
        ini = defaultdict(int)
        for n, c in self.firsts.items():
            ini[n[0]] += c
        self.initial = {k: v / self.first_total for k, v in ini.items()}
        self.own_org = own_org_counts or {}
        self.own_org_total = own_org_total
        self.source = {"surnames": "census2010" if self.surnames else "FLAT",
                       "first_names": "ssa1930-2005" if self.firsts else "FLAT",
                       "org_tokens": ("nppes" if (self.org_df and self.org_n > 1) else "FLAT")
                                     + ("+reference_population" if self.own_org_total else "")}
        self._cache_org = {}

    def surname_freq(self, last):
        if not self.surnames:
            return self.p.flat_freq
        parts = [last] + [x for x in re.split(r"[ \-]", last) if x and x != last]
        return min(self.surnames.get(x, self.p.surname_floor) for x in parts) / self.surname_total

    def first_freq(self, first):
        if not self.firsts:
            return self.p.flat_freq
        f = first.split(" ")[0]
        return self.firsts.get(f, self.p.firstname_floor) / self.first_total

    def initial_share(self, letter):
        return self.initial.get(letter[:1], 1 / 26) if self.firsts else 1 / 26

    def org_idf(self, tok):
        """Bits of surprise in two organizations sharing this name word."""
        if tok in self._cache_org:
            return self._cache_org[tok]
        if not (self.org_df and self.org_n > 1):
            idf = 6.0
        else:
            idf = math.log2(self.org_n / self.org_df.get(tok, self.p.org_df_floor))
        if self.own_org_total:
            own = math.log2(self.own_org_total / max(1, self.own_org.get(tok, 0)))
            if self.own_org.get(tok, 0) >= self.p.own_org_min_count:
                idf = min(idf, own)
        self._cache_org[tok] = idf
        return idf


def own_org_word_counts(org_alias_strings):
    """How many parties of the reference population use each org word (for Rarity)."""
    counts = defaultdict(int)
    n = 0
    for s in org_alias_strings:
        if not s:
            continue
        n += 1
        for w in set(" ".join(s.split("|")).split()):
            counts[w] += 1
    return dict(counts), n

# %%
# ---- Matching core v1.0: value statistics for per-value u and vetoes -----------------------

VALUE_FIELDS = {  # field -> party-frame columns holding its values
    "ssn": ["id_ssn"], "npi": ["id_npi"], "dl": ["id_dl"], "tin": ["id_tin"],
    "license": ["id_license"], "email": ["id_email"], "vin": ["id_vin"], "plate": ["id_plate"],
    "cnpi": ["id_cnpi"], "phone": ["phone_own", "phone_row"],
}
KEY_FIELDS = ["dob", "addr_full", "addr_street", "zip", "city_state", "state", "specialty",
              "category"]


@dataclass
class ValueStats:
    """Per-value counts the comparisons read. `ref_counts[key][value]`: parties of the
    reference (right) population holding the value; `ref_n[key]`: those holding any value.
    `names[field][value]`: distinct names holding an identifier value across both sides.
    `single[field]`: values held under exactly one name."""
    ref_counts: dict
    ref_n: dict
    names: dict
    single: dict


def build_value_stats(left, right):
    """Counts from the two party frames. Identifier u uses how many distinct names hold the
    value across both sides (so a shared or placeholder SSN weighs little); dates, addresses,
    specialty and category use the reference side's own frequencies."""
    ref_counts, ref_n, names, single = {}, {}, {}, {}
    for k in KEY_FIELDS:
        v = right[k][right[k] != ""] if k in right else pd.Series([], dtype=object)
        if k == "category":
            v = v[v != "other"]
        ref_counts[k] = v.value_counts()
        ref_n[k] = int(len(v))
    both = pd.concat([left, right], ignore_index=True)
    for f, cols in VALUE_FIELDS.items():
        parts = [pd.DataFrame({"v": both[c], "n": both["holder_key"]}) for c in cols if c in both]
        long = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame({"v": [], "n": []})
        long = long[long["v"] != ""]
        nn = long.drop_duplicates().groupby("v")["n"].size()
        names[f] = nn
        single[f] = set(nn.index[nn == 1])
        rv = pd.concat([right[c] for c in cols if c in right], ignore_index=True) if cols else pd.Series([], dtype=object)
        rv = rv[rv != ""]
        ref_n[f] = int((pd.concat([right[c] != "" for c in cols], axis=1).any(axis=1)).sum()) if len(right) else 0
        ref_counts[f] = rv.value_counts()
    return ValueStats(ref_counts, ref_n, names, single)


def junk_values(stats, params):
    """Identifier values held under more names than params.junk_holders: {field: set}."""
    return {f: set(nn.index[nn > params.junk_holders]) for f, nn in stats.names.items()}

# %%
# ---- Matching core v1.0: comparisons (recordlinkage.Compare + custom features) -------------
# One level per field, the same code for candidates, random pairs, anchors and simulated
# pairs. Each feature returns its level codes and, where the level is value-specific, the
# value's own chance-agreement factor `uv` (NaN where the field-level u applies).


@dataclass
class CompareContext:
    params: CoreParams
    rarity: Rarity
    nick: Nicknames
    stats: ValueStats
    dba_pairs: list = field(default_factory=list)      # [(set, set)] declared as one org
    components: dict = field(default_factory=dict)    # random-pair rates for name sub-parts


def _unique_pairs(a, b):
    """Joint factorization of two aligned arrays: (inverse, unique a, unique b)."""
    ca, ua = pd.factorize(np.asarray(a, dtype=object))
    cb, ub = pd.factorize(np.asarray(b, dtype=object))
    nb = len(ub) + 1
    key = ca.astype(np.int64) * nb + cb.astype(np.int64)
    uk, inv = np.unique(key, return_inverse=True)
    return inv, np.asarray(ua, dtype=object)[uk // nb], np.asarray(ub, dtype=object)[uk % nb]


def _arr(s):
    return np.asarray(s.to_numpy() if hasattr(s, "to_numpy") else s, dtype=object)


def _lookup(counts, values):
    """counts: Series value->count. Returns float array (0 where absent)."""
    if counts is None or not len(counts):
        return np.zeros(len(values))
    return pd.Series(values).map(counts).fillna(0).to_numpy(dtype=float)


def _jw(a, b):
    return jellyfish.jaro_winkler_similarity(a, b)


def _last_cmp(a, b, p):
    """0 exact, 1 close (spelling, sound or one compound part), 2 differs, -1 empty."""
    if not a or not b:
        return -1
    if a == b:
        return 0
    ta, tb = set(re.split(r"[ \-]", a)), set(re.split(r"[ \-]", b))
    if (ta <= tb or tb <= ta) or _jw(a, b) >= p.jw_close or nysiis(a) == nysiis(b):
        return 1
    return 2


FIRST_CMP = ["exact", "nick_or_close", "initial", "empty", "differs"]


def _first_cmp(a, b, p, nick):
    """0 exact, 1 nickname or close spelling, 2 initial agrees, 3 empty, 4 differs."""
    if not a or not b:
        return 3
    if len(a) == 1 or len(b) == 1:
        return 2 if a[0] == b[0] else 4
    if a == b:
        return 0
    if (nick.roots(a) & nick.roots(b)) or _jw(a, b) >= p.jw_close:
        return 1
    return 4


def f_name(first_l, last_l, first_r, last_r, ctx):
    """Person name, one graded group (see FIELD_LEVELS['name'])."""
    p, R = ctx.params, ctx.rarity
    fl, ll, fr, lr = _arr(first_l), _arr(last_l), _arr(first_r), _arr(last_r)
    inv, ua, ub = _unique_pairs(ll, lr)
    lc = np.array([_last_cmp(a, b, p) for a, b in zip(ua, ub)], dtype=np.int8)[inv]
    inv, ua, ub = _unique_pairs(fl, fr)
    fc = np.array([_first_cmp(a, b, p, ctx.nick) for a, b in zip(ua, ub)], dtype=np.int8)[inv]
    swapped = (fl != "") & (ll != "") & (fl == lr) & (ll == fr) & (ll != lr)
    last_exact, last_close = lc == 0, lc == 1
    first_agree = (fc == 0) | (fc == 1)
    conds = [lc < 0, last_exact & (fc == 0), last_exact & (fc == 1),
             last_close & first_agree, last_exact & (fc == 2), swapped,
             last_exact & (fc == 3), last_exact & (fc == 4)]
    codes = [EMPTY, 0, 1, 2, 3, 4, 5, 6]
    level = np.select(conds, codes, default=7).astype(np.int8)
    # value-specific u: outside tables for the agreeing values, random-pair rates for the rest
    C = ctx.components or {}
    fL = map_unique(pd.Series(lr), R.surname_freq).to_numpy(dtype=float)
    fF = map_unique(pd.Series(fr), lambda v: R.first_freq(v) if v else 1.0).to_numpy(dtype=float)
    ini = map_unique(pd.Series(fr), lambda v: R.initial_share(v) if v else 1.0).to_numpy(dtype=float)
    fLsw = map_unique(pd.Series(fl), R.surname_freq).to_numpy(dtype=float)     # swapped: x.first is w.last
    uv = np.full(len(level), np.nan)
    uv = np.where(level == 0, fL * fF, uv)
    uv = np.where(level == 1, fL * C.get("first_nick_or_close", np.nan), uv)
    uv = np.where(level == 2, C.get("last_close", np.nan) *
                  np.where(fc == 0, fF, C.get("first_nick_or_close", np.nan)), uv)
    uv = np.where(level == 3, fL * ini, uv)
    uv = np.where(level == 4, fLsw * fF, uv)
    uv = np.where(level == 5, fL * C.get("first_empty", np.nan), uv)
    uv = np.where(level == 6, fL * C.get("first_differs", np.nan), uv)
    return level, uv, fc, lc


def f_middle(ml, mr, ctx):
    a, b = _arr(ml), _arr(mr)
    empty = (a == "") | (b == "")
    exact = (a == b) & ~empty & (np.char.str_len(a.astype(str)) > 1)
    ia = np.array([x[:1] for x in a], dtype=object)
    ib = np.array([x[:1] for x in b], dtype=object)
    initial = (ia == ib) & ~empty & ~exact
    level = np.select([empty, exact, initial], [EMPTY, 0, 1], default=2).astype(np.int8)
    return level, np.full(len(level), np.nan)


def _digit_arrays(v, width):
    return np.stack([(v // 10 ** k) % 10 for k in range(width)], axis=1)


def f_dob(dl, dr, ctx):
    a = np.asarray(dl, dtype=np.int64)
    b = np.asarray(dr, dtype=np.int64)
    empty = (a == 0) | (b == 0)
    ya, ma, da = a // 10000, (a // 100) % 100, a % 100
    yb, mb, db = b // 10000, (b // 100) % 100, b % 100
    exact = (a == b) & ~empty
    swap = (ya == yb) & (ma == db) & (da == mb) & ~exact
    hamming = (_digit_arrays(a, 8) != _digit_arrays(b, 8)).sum(axis=1)
    typo = (hamming == 1) & ~exact
    level = np.select([empty, exact, swap | typo, (ya == yb) & (ma == mb), ya == yb],
                      [EMPTY, 0, 1, 2, 3], default=4).astype(np.int8)
    st = ctx.stats
    uv = np.where(level == 0, _lookup(st.ref_counts.get("dob"),
                                      pd.Series(b).map(_dob_str).to_numpy()) / max(1, st.ref_n.get("dob", 0)),
                  np.nan)
    return level, uv


def _dob_str(v):
    v = int(v)
    return f"{v // 10000:04d}-{(v // 100) % 100:02d}-{v % 100:02d}" if v else ""


def f_address(full_l, street_l, zip_l, cs_l, st_l, full_r, street_r, zip_r, cs_r, st_r, ctx):
    fl, sl, zl, cl, tl = (_arr(x) for x in (full_l, street_l, zip_l, cs_l, st_l))
    fr, sr, zr, cr, tr = (_arr(x) for x in (full_r, street_r, zip_r, cs_r, st_r))
    eq = lambda x, y: (x == y) & (x != "")
    comparable = ((tl != "") & (tr != "")) | ((zl != "") & (zr != "")) | ((sl != "") & (sr != ""))
    conds = [eq(fl, fr), eq(sl, sr), eq(zl, zr), eq(cl, cr), eq(tl, tr), comparable]
    level = np.select(conds, [0, 1, 2, 3, 4, 5], default=EMPTY).astype(np.int8)
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    for code, key, vals in ((0, "addr_full", fr), (1, "addr_street", sr), (2, "zip", zr),
                            (3, "city_state", cr), (4, "state", tr)):
        m = level == code
        if m.any():
            uv[m] = _lookup(st.ref_counts.get(key), vals[m]) / max(1, st.ref_n.get(key, 0))
    return level, uv


def _near(a, b):
    """One substituted character or two adjacent ones exchanged (same length)."""
    if len(a) != len(b) or a == b:
        return False
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(diff) == 1:
        return True
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def _split_q(v):
    st, _, n = v.partition(":")
    return st, n


def f_identifier(vl, vr, ctx, field_):
    """Exact (value-specific u) / near (typo, for SSN, NPI, DL, TIN) / differs. Qualified
    values (DL, licence, plate: 'STATE:NUMBER') agree when the numbers match and the states
    match or one is unstated. Returns level, uv, veto (two different single-holder values of a
    one-per-party identifier; DL only within one state)."""
    a, b = _arr(vl), _arr(vr)
    n = len(a)
    empty = (a == "") | (b == "")
    qualified = field_ in ("dl", "license", "plate")
    level = np.full(n, EMPTY, dtype=np.int8)
    veto = np.zeros(n, dtype=bool)
    idx = np.flatnonzero(~empty)
    if len(idx):
        inv, ua, ub = _unique_pairs(a[idx], b[idx])
        near_ok = field_ in NEAR_FIELDS
        single = ctx.stats.single.get(field_, set())
        res = []
        for x, y in zip(ua, ub):
            if qualified:
                sx, nx = _split_q(x)
                sy, ny = _split_q(y)
                states_ok = (sx == sy) or not sx or not sy
                if nx == ny and states_ok:
                    res.append((0, False))
                elif near_ok and states_ok and _near(nx, ny):
                    res.append((1, False))
                else:
                    v = (field_ == "dl" and sx and sx == sy and x in single and y in single)
                    res.append((len(FIELD_LEVELS[field_]) - 1, bool(v)))
            else:
                if x == y:
                    res.append((0, False))
                elif near_ok and _near(x, y):
                    res.append((1, False))
                else:
                    v = field_ in VETO_FIELDS and x in single and y in single
                    res.append((len(FIELD_LEVELS[field_]) - 1, bool(v)))
        r = np.array(res, dtype=np.int64).reshape(-1, 2)[inv]
        level[idx] = r[:, 0]
        veto[idx] = r[:, 1].astype(bool)
    st = ctx.stats
    uv = np.full(n, np.nan)
    m = level == 0
    if m.any():
        names = _lookup(st.names.get(field_), b[m])
        refc = _lookup(st.ref_counts.get(field_), b[m])
        uv[m] = np.maximum(np.maximum(names, refc), 1.0) / max(1, st.ref_n.get(field_, 0))
    return level, uv, veto


def f_phone(own_l, row_l, own_r, row_r, ctx):
    """exact_owned_single: the agreeing number is owned on both sides and held under one name;
    exact_shared: agrees otherwise (row-level, or several holders); differs."""
    ol, rwl, orr, rwr = _arr(own_l), _arr(row_l), _arr(own_r), _arr(row_r)
    single = ctx.stats.single.get("phone", set())
    has_l = (ol != "") | (rwl != "")
    has_r = (orr != "") | (rwr != "")
    eq = lambda x, y: (x == y) & (x != "")
    own_own = eq(ol, orr)
    any_eq = own_own | eq(ol, rwr) | eq(rwl, orr) | eq(rwl, rwr)
    own_single = own_own & pd.Series(ol).isin(single).to_numpy()
    level = np.select([~(has_l & has_r), own_single, any_eq], [EMPTY, 0, 1], default=2).astype(np.int8)
    matched = np.where(own_own, ol, np.where(eq(ol, rwr), ol, np.where(eq(rwl, orr), rwl, rwl)))
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    m = (level == 0) | (level == 1)
    if m.any():
        names = _lookup(st.names.get("phone"), matched[m])
        refc = _lookup(st.ref_counts.get("phone"), matched[m])
        uv[m] = np.maximum(np.maximum(names, refc), 1.0) / max(1, st.ref_n.get("phone", 0))
    return level, uv


def f_spec_cat(spec_l, cat_l, str_l, spec_r, cat_r, str_r, ctx):
    """Specialty and category, one correlated group: same specialty / same category, both
    identifier- or mapping-backed / same category, one side given or keyword / different."""
    sl, cl, gl, sr, cr, gr = (_arr(x) for x in (spec_l, cat_l, str_l, spec_r, cat_r, str_r))
    cl = np.where(cl == "other", "", cl)
    cr = np.where(cr == "other", "", cr)
    same_spec = (sl == sr) & (sl != "")
    same_cat = (cl == cr) & (cl != "")
    strong = (gl == "strong") & (gr == "strong")
    comparable = ((cl != "") & (cr != "")) | ((sl != "") & (sr != ""))
    level = np.select([same_spec, same_cat & strong, same_cat, comparable], [0, 1, 2, 3],
                      default=EMPTY).astype(np.int8)
    st = ctx.stats
    uv = np.full(len(level), np.nan)
    m = level == 0
    if m.any():
        uv[m] = _lookup(st.ref_counts.get("specialty"), sr[m]) / max(1, st.ref_n.get("specialty", 0))
    m = (level == 1) | (level == 2)
    if m.any():
        uv[m] = _lookup(st.ref_counts.get("category"), cr[m]) / max(1, st.ref_n.get("category", 0))
    return level, uv


# ---- organization names (goko cell 18, adapted to levels) ----------------------------------
def _rejoin(x, y):
    """goko cell 18: undo OCR splits: 'CASUAL','TY' -> 'CASUALTY' when the other has it."""
    ys, out, i = set(y), [], 0
    while i < len(x):
        if i + 1 < len(x) and x[i] + x[i + 1] in ys and x[i] not in ys:
            out.append(x[i] + x[i + 1]); i += 2
        else:
            out.append(x[i]); i += 1
    return out


def _match_words(x, y, p):
    """goko _org_alias_bits' word pairing: exact first, then Jaro-Winkler >= jw_close.
    Returns (matched words of x, words only in x, words only in y)."""
    x, y = _rejoin(x, y), _rejoin(y, x)
    left, matched = list(y), []
    for t in x:
        hit = t if t in left else max(left, key=lambda u: _jw(t, u), default=None)
        if hit is not None and (hit == t or _jw(t, hit) >= p.jw_close):
            matched.append(t); left.remove(hit)
    only_x = [t for t in x if t not in matched]
    return matched, only_x, left


def _fuzzy_family(a, b, p):
    """goko: one name's words all appear (spelling-tolerant) in the other."""
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return bool(small) and all(any(t == u or _jw(t, u) >= p.jw_close for u in big) for t in small)


def declared_dba_pairs(org_alias_strings):
    """goko cell 18 declared_dbas: alias pairs that one party declares to be one organization
    ('X d/b/a Y'). A trade name shares no words with the legal name; without this the sibling
    level would split a party from its own d/b/a."""
    pairs, seen = [], set()
    for s in org_alias_strings:
        al = [a for a in s.split("|") if a] if s else []
        for i in range(len(al)):
            for j in range(i + 1, len(al)):
                k = (al[i], al[j])
                if k not in seen:
                    seen.add(k)
                    pairs.append((frozenset(al[i].split()), frozenset(al[j].split())))
    return pairs


def _dba_index(ctx):
    """word -> indexes of declared d/b/a pairs using it (built once per context)."""
    idx = getattr(ctx, "_dba_idx", None)
    if idx is None or idx[0] is not ctx.dba_pairs:
        d = defaultdict(set)
        for i, (q1, q2) in enumerate(ctx.dba_pairs):
            for w in q1 | q2:
                d[w].add(i)
        idx = (ctx.dba_pairs, d)
        ctx._dba_idx = idx
    return idx[1]


def _declared_same(xs, ys, ctx):
    """Some record declares the two names to be one organization (goko _declared_same).
    Only declarations sharing a word with each side are checked."""
    if not ctx.dba_pairs:
        return False
    d = _dba_index(ctx)
    cx = set().union(*(d.get(w, set()) for a in xs for w in a))
    cy = set().union(*(d.get(w, set()) for b in ys for w in b))
    p = ctx.params
    for i in sorted(cx & cy):
        q1, q2 = ctx.dba_pairs[i]
        for a in xs:
            for b in ys:
                if (_fuzzy_family(set(a), q1, p) and _fuzzy_family(set(b), q2, p)) or                         (_fuzzy_family(set(a), q2, p) and _fuzzy_family(set(b), q1, p)):
                    return True
    return False


def _org_words_u(words, R):
    """Chance two organizations share these words: the rarest counts in full, the others at
    half, because the words of one name travel together (goko _org_alias_bits)."""
    idfs = sorted((R.org_idf(t) for t in words), reverse=True)
    if not idfs:
        return 1.0
    return 2.0 ** -(idfs[0] + 0.5 * sum(idfs[1:]))


def org_level(al, ar, ctx):
    """(level code, uv, detail) for two '|'-joined alias strings."""
    p, R = ctx.params, ctx.rarity
    if not al or not ar:
        return EMPTY, np.nan, ""
    xs = [a.split() for a in al.split("|") if a]
    ys = [a.split() for a in ar.split("|") if a]
    for x in xs:
        for y in ys:
            if x == y:
                return 0, max(p.u_floor, _org_words_u(y, R)), " ".join(y)
    best = None
    for x in xs:
        for y in ys:
            matched, ox, oy = _match_words(x, y, p)
            score = sum(R.org_idf(t) for t in matched)
            if best is None or score > best[0]:
                best = (score, matched, ox, oy, x, y)
    _, matched, ox, oy, x, y = best
    declared = _declared_same(xs, ys, ctx)
    if declared and not matched:
        return 1, max(p.u_floor, _org_words_u(y, R)), "declared d/b/a"
    if matched and (not ox or not oy):
        return 2, max(p.u_floor, _org_words_u(matched, R)), " ".join(matched)
    dist = lambda ws: [t for t in ws if len(t) >= p.org_distinct_min_len and R.org_idf(t) >= p.org_rare_idf]
    if matched and dist(ox) and dist(oy) and not declared:
        return 5, np.nan, f"{'+'.join(dist(ox))} vs {'+'.join(dist(oy))}"
    if declared:
        return 1, max(p.u_floor, _org_words_u(y, R)), "declared d/b/a"
    if matched:
        top = max(matched, key=R.org_idf)
        if R.org_idf(top) >= p.org_rare_idf:
            return 3, max(p.u_floor, 2.0 ** -R.org_idf(top)), top
        return 4, np.nan, " ".join(matched)
    return 6, np.nan, ""


def f_org(al, ar, ctx):
    a, b = _arr(al), _arr(ar)
    inv, ua, ub = _unique_pairs(a, b)
    res = [org_level(x, y, ctx) for x, y in zip(ua, ub)]
    level = np.array([r[0] for r in res], dtype=np.int8)[inv]
    uv = np.array([r[1] for r in res], dtype=float)[inv]
    return level, uv


# Which party-frame columns each feature reads.
FEATURE_COLUMNS = {
    "name": (["first", "last"], ["first", "last"]),
    "middle": (["middle"], ["middle"]),
    "dob": (["dob_int"], ["dob_int"]),
    "address": (["addr_full", "addr_street", "zip", "city_state", "state"],
                ["addr_full", "addr_street", "zip", "city_state", "state"]),
    "phone": (["phone_own", "phone_row"], ["phone_own", "phone_row"]),
    "spec_cat": (["specialty", "category", "cat_strength"], ["specialty", "category", "cat_strength"]),
    "org": (["org_aliases"], ["org_aliases"]),
    **{f: ([f"id_{f}"], [f"id_{f}"]) for f in ["ssn", "npi", "dl", "tin", "license", "email",
                                                "vin", "plate", "cnpi"]},
}


def _feature(field_, ctx):
    if field_ == "name":
        return lambda a, b, c, d: f_name(a, b, c, d, ctx), [field_, f"uv_{field_}", "name_first_cmp", "name_last_cmp"]
    if field_ == "middle":
        return lambda a, b: f_middle(a, b, ctx), [field_, f"uv_{field_}"]
    if field_ == "dob":
        return lambda a, b: f_dob(a, b, ctx), [field_, f"uv_{field_}"]
    if field_ == "address":
        return lambda *s: f_address(*s, ctx), [field_, f"uv_{field_}"]
    if field_ == "phone":
        return lambda a, b, c, d: f_phone(a, b, c, d, ctx), [field_, f"uv_{field_}"]
    if field_ == "spec_cat":
        return lambda *s: f_spec_cat(*s, ctx), [field_, f"uv_{field_}"]
    if field_ == "org":
        return lambda a, b: f_org(a, b, ctx), [field_, f"uv_{field_}"]
    return (lambda a, b, f=field_: f_identifier(a, b, ctx, f),
            [field_, f"uv_{field_}", f"veto_{field_}"])


def compare_pairs(left, right, il, ir, part, ctx):
    """Level per field for positional pairs (il into left, ir into right), computed through
    recordlinkage.Compare with one custom vectorized feature per field. Returns a DataFrame
    with one row per pair: `<field>` level codes, `uv_<field>` value-specific u factors,
    `veto_<field>` flags and the name sub-comparisons."""
    il = np.asarray(il, dtype=np.int64)
    ir = np.asarray(ir, dtype=np.int64)
    cols = ["l", "r"]
    if len(il) == 0:
        out = pd.DataFrame({"l": il, "r": ir})
        for f in COMPARED_FIELDS[part]:
            _, labels = _feature(f, ctx)
            for lab in labels:
                out[lab] = pd.Series([], dtype=float if lab.startswith("uv_") else
                                     (bool if lab.startswith("veto_") else np.int8))
        return out
    pairs = pd.MultiIndex.from_arrays([il, ir], names=cols)
    cmp = rl.Compare(indexing_type="position")
    for f in COMPARED_FIELDS[part]:
        func, labels = _feature(f, ctx)
        lcols, rcols = FEATURE_COLUMNS[f]
        cmp.compare_vectorized(func, lcols, rcols, label=labels)
    feats = cmp.compute(pairs, left, right)
    feats = feats.reset_index(drop=True)
    feats.insert(0, "r", ir)
    feats.insert(0, "l", il)
    for c in feats.columns:
        if c in FIELD_LEVELS or c in ("name_first_cmp", "name_last_cmp"):
            feats[c] = feats[c].astype(np.int8)
        elif c.startswith("veto_"):
            feats[c] = feats[c].astype(bool)
    return feats


def coparty_proxy_levels(left, right, il, ir):
    """Co-party level for pairs used in estimation, where business links are not scored yet:
    'anchored' when the two tied businesses share a TIN or clinic NPI. Scoring uses the real
    anchors (business links on an identifier at p >= coparty_min_p, no veto)."""
    tl = left["tie_pos"].to_numpy()[il]
    tr = right["tie_pos"].to_numpy()[ir]
    has = (tl >= 0) & (tr >= 0)
    level = np.full(len(il), EMPTY, dtype=np.int8)
    if has.any():
        bl, br = tl[has], tr[has]
        agree = np.zeros(len(bl), dtype=bool)
        for c in ("id_tin", "id_cnpi"):
            a = left[c].to_numpy()[bl]
            b = right[c].to_numpy()[br]
            agree |= (a == b) & (a != "")
        level[has] = np.where(agree, 0, 1)
    return level

# %%
# ---- Matching core v1.0: parameter estimation ------------------------------------------------
# u from random pairs (Splink's method), with the name sub-part rates the value-specific u
# needs; m from level counts per source, EM with u fixed, a shrinkage chain across sources,
# and the prior over all pairs.


def level_counts(levels, fields, weights=None, exclude=None):
    """Counts of each level among informative pairs (level != EMPTY). `exclude[field]` is a
    boolean mask of pairs whose value of that field must not count (the anchor's own field).
    Returns {field: (counts array per level, informative total)}."""
    out = {}
    w = np.ones(len(levels)) if weights is None else np.asarray(weights, dtype=float)
    for f in fields:
        if f not in levels:
            continue
        lv = levels[f].to_numpy()
        ok = lv >= 0
        if exclude is not None and f in exclude:
            ok &= ~exclude[f]
        k = len(FIELD_LEVELS[f])
        counts = np.bincount(lv[ok].astype(np.int64), weights=w[ok], minlength=k)[:k]
        out[f] = (counts, float(w[ok].sum()))
    return out


def estimate_u(levels_random, fields, params):
    """Field-level u per level from random pairs, smoothed by a pseudo-count."""
    rows = []
    cnt = level_counts(levels_random, fields)
    for f in fields:
        counts, n = cnt.get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0))
        k = len(counts)
        u = (counts + params.u_pseudo) / (n + params.u_pseudo * k)
        for i, lev in enumerate(FIELD_LEVELS[f]):
            rows.append({"field": f, "level": lev, "level_code": i, "u": float(u[i]),
                         "u_count": float(counts[i]), "u_pairs": float(n),
                         "u_source": f"random pairs ({int(n):,} informative)"})
    return pd.DataFrame(rows)


def name_components(levels_random):
    """Random-pair rates of the name sub-parts: the first-name part given informative names,
    and 'last name close'. Used to build value-specific u for the partial name levels."""
    ok = levels_random["name"].to_numpy() >= 0 if "name" in levels_random else np.zeros(0, bool)
    n = max(1, int(ok.sum()))
    fc = levels_random["name_first_cmp"].to_numpy()[ok] if ok.any() else np.array([], dtype=int)
    lc = levels_random["name_last_cmp"].to_numpy()[ok] if ok.any() else np.array([], dtype=int)
    rate = lambda mask: (float(mask.sum()) + 0.5) / (n + 1.0)
    return {"first_nick_or_close": rate(fc == 1), "first_initial": rate(fc == 2),
            "first_empty": rate(fc == 3), "first_differs": rate(fc == 4),
            "last_close": rate(lc == 1), "pairs": n}


def em_fixed_u(levels, free_fields, fixed_fields, m_fixed, u_table, params, exclude=None):
    """Expectation-maximization over the pairs in `levels`, with u fixed for every field and m
    fixed for `fixed_fields`; learns m for `free_fields` and the match share lambda.
    `m_fixed[f]` and `u_table[f]` are arrays per level. Returns ({field: (m array, n_eff)},
    lambda, iterations)."""
    n = len(levels)
    if n == 0:
        return {}, float("nan"), 0
    fields = [f for f in list(free_fields) + list(fixed_fields) if f in levels]
    lv = {f: levels[f].to_numpy().astype(np.int64) for f in fields}
    ok = {f: (lv[f] >= 0) & (~exclude[f] if exclude is not None and f in exclude else True)
          for f in fields}
    m = {f: (np.asarray(m_fixed[f], dtype=float) if f in fixed_fields
             else np.linspace(0.9, 0.1, len(FIELD_LEVELS[f])) / np.linspace(0.9, 0.1, len(FIELD_LEVELS[f])).sum())
         for f in fields}
    u = {f: np.asarray(u_table[f], dtype=float) for f in fields}
    lam, it = 0.5, 0
    for it in range(1, params.em_max_iter + 1):
        log_m = np.zeros(n)
        log_u = np.zeros(n)
        for f in fields:
            idx = np.where(ok[f], lv[f], 0)
            log_m += np.where(ok[f], np.log(np.clip(m[f][idx], 1e-12, 1)), 0.0)
            log_u += np.where(ok[f], np.log(np.clip(u[f][idx], 1e-12, 1)), 0.0)
        a = np.log(lam) + log_m
        b = np.log(1 - lam) + log_u
        w = 1.0 / (1.0 + np.exp(np.clip(b - a, -700, 700)))
        new_lam = float(np.clip(w.mean(), 1e-6, 1 - 1e-6))
        delta = abs(new_lam - lam)
        for f in free_fields:
            if f not in lv:
                continue
            k = len(FIELD_LEVELS[f])
            c = np.bincount(lv[f][ok[f]], weights=w[ok[f]], minlength=k)[:k]
            tot = c.sum()
            if tot > 0:
                newm = (c + 1e-3) / (tot + 1e-3 * k)
                delta = max(delta, float(np.abs(newm - m[f]).max()))
                m[f] = newm
        lam = new_lam
        if delta < params.em_tol:
            break
    out = {}
    for f in free_fields:
        if f in lv:
            out[f] = (m[f], float(w[ok[f]].sum()), np.bincount(lv[f][ok[f]], weights=w[ok[f]],
                                                             minlength=len(FIELD_LEVELS[f]))[:len(FIELD_LEVELS[f])])
    return out, lam, it


def combine_m(field_, sources, published, params):
    """One field's m per level from sources in preference order.

    `sources`: list of (name, counts array, informative n) best first. Each estimate is shrunk
    toward the next one (alpha pseudo-pairs), bottom-up from the published value. Simulation
    (a source named 'simulation') joins the chain only when the sources before it hold fewer
    than n_min informative pairs. Returns rows with m, the chain, pairs and a 95% interval."""
    k = len(FIELD_LEVELS[field_])
    pub = np.asarray(published, dtype=float)
    pub = pub / pub.sum() if pub.sum() > 0 else np.full(k, 1.0 / k)
    before_sim = 0.0
    used = []
    for name, counts, n in sources:
        if name == "simulation" and before_sim >= params.n_min:
            continue
        if n > 0:
            used.append((name, np.asarray(counts, dtype=float), float(n)))
        if name != "simulation":
            before_sim += n
    m = pub.copy()
    for name, counts, n in reversed(used):
        m = (counts + params.alpha * m) / (n + params.alpha)
    n_total = sum(n for _, _, n in used)
    n_eff = n_total + params.alpha
    se = np.sqrt(np.clip(m * (1 - m), 0, None) / n_eff)
    chain = " > ".join(f"{name}({n:,.0f})" for name, _, n in used) or "published only"
    primary = used[0][0] if used else "published"
    rows = []
    for i, lev in enumerate(FIELD_LEVELS[field_]):
        rows.append({"field": field_, "level": lev, "level_code": i, "m": float(m[i]),
                     "m_lo": float(max(0.0, m[i] - params.ci_z * se[i])),
                     "m_hi": float(min(1.0, m[i] + params.ci_z * se[i])),
                     "m_source": primary, "m_chain": chain, "m_pairs": float(n_total),
                     "m_published": float(pub[i])})
    return rows


def weights_table(m_rows, u_df, components):
    """Join m and u per field and level; field-level bits; flag agreement levels where m < u
    (those count 0 bits). Value-specific levels say what their u rests on."""
    w = pd.DataFrame(m_rows).merge(u_df, on=["field", "level", "level_code"], how="left")
    w["u"] = w["u"].fillna(1.0)
    w["agreement"] = [lev in AGREEMENT_LEVELS.get(f, set()) for f, lev in zip(w["field"], w["level"])]
    w["zero_by_rule"] = [lev in ZERO_LEVELS.get(f, set()) for f, lev in zip(w["field"], w["level"])]
    w["bits_field_level"] = np.log2(np.clip(w["m"], 1e-12, 1) / np.clip(w["u"], 1e-12, 1))
    w["flag"] = np.where(w["agreement"] & (w["m"] < w["u"]), "m<u: agreement counts 0 bits", "")
    w["u_value_specific"] = [value_specific(f, lev) for f, lev in zip(w["field"], w["level"])]
    return w


VALUE_U_SOURCE = {
    ("name", "exact"): "census surname x SSA first name (per value)",
    ("name", "first_nick_or_close"): "census surname (per value) x random-pair rate of a nickname/close first name",
    ("name", "last_close_first_agrees"): "random-pair rate of a close surname x SSA first name (per value)",
    ("name", "initial_agrees"): "census surname x SSA share of the initial (per value)",
    ("name", "swapped"): "census x SSA for the swapped values",
    ("name", "first_empty"): "census surname (per value) x random-pair rate of an empty first name",
    ("name", "first_differs"): "census surname (per value) x random-pair rate of a differing first name",
    ("org", "exact"): "NPPES / reference-population word shares (per value)",
    ("org", "dba"): "NPPES / reference-population word shares (per value)",
    ("org", "short_form"): "NPPES / reference-population word shares of the shared words",
    ("org", "rare_shared"): "NPPES / reference-population share of the rarest shared word",
    ("dob", "exact"): "reference population: holders of the date",
    ("address", "exact"): "reference population: holders of the address",
    ("address", "street"): "reference population: holders of number + street",
    ("address", "zip"): "reference population: holders of the ZIP",
    ("address", "city_state"): "reference population: holders of city + state",
    ("address", "state"): "reference population: holders of the state",
    ("spec_cat", "specialty"): "reference population: holders of the specialty",
    ("spec_cat", "category_id"): "reference population: holders of the category",
    ("spec_cat", "category_weak"): "reference population: holders of the category",
}
for _f in IDENTIFIER_FIELDS:
    VALUE_U_SOURCE[(_f, "exact" if _f != "phone" else "exact_owned_single")] = "distinct names holding the value / reference holders of the field"
VALUE_U_SOURCE[("phone", "exact_shared")] = "distinct names holding the value / reference holders of the field"


def value_specific(f, lev):
    return VALUE_U_SOURCE.get((f, lev), "")


def strict_recall(fill, m_lookup):
    """How often a true match fires at least one strict rule, from field fill rates and the
    estimated m (rules treated as independent). `fill[key]`: share of pairs where both sides
    hold the field; `m_lookup(field, level)`: estimated m."""
    q = []
    ids = [f for f in ("ssn", "npi", "dl", "tin", "license", "email", "vin", "plate", "cnpi")]
    for f in ids:
        if fill.get(f, 0) > 0:
            q.append(fill[f] * m_lookup(f, "exact"))
    if fill.get("name", 0) > 0:
        q.append(fill["name"] * fill.get("dob", 0) * m_lookup("name", "exact") * m_lookup("dob", "exact"))
        q.append(fill["name"] * fill.get("street", 0) * m_lookup("name", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "street")))
    if fill.get("org", 0) > 0:
        q.append(fill["org"] * fill.get("zip", 0) * m_lookup("org", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "zip")))
        q.append(fill["org"] * fill.get("street", 0) * m_lookup("org", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "street")))
    return float(1 - np.prod([1 - min(1.0, x) for x in q])) if q else 0.0


def prior_estimate(n_strict, n_pairs, recall, params):
    """P(a random pair of the group matches) = strict pairs / recall / all pairs. A zero count
    uses a pseudo-count and is flagged."""
    flagged = n_strict == 0 or recall <= 0
    num = (n_strict if n_strict > 0 else params.prior_pseudo) / max(recall, 1e-3)
    prior = float(min(0.5, num / max(1.0, float(n_pairs))))
    return prior, flagged

# %%
# ---- Matching core v1.0: scoring, vetoes, basis, co-party, evidence -------------------------


def _lookup_table(w, f, col):
    sub = w[w["field"] == f].sort_values("level_code")
    return sub[col].to_numpy(dtype=float)


def score_pairs(levels, part, weights, prior_logit):
    """Fellegi-Sunter in bits. For each field: log2(m / u), where u is the value-specific u on
    levels that have one and the field-level u otherwise; an empty field is 0 bits; an
    agreement level never goes below 0; levels declared 'no evidence' are 0. Vetoes set p = 0
    and stay visible. Returns a DataFrame: bits_<field>, bits, logit, p, veto, basis."""
    n = len(levels)
    out = pd.DataFrame(index=levels.index)
    total = np.zeros(n)
    for f in PART_FIELDS[part]:
        if f not in levels:
            out[f"bits_{f}"] = 0.0
            continue
        lv = levels[f].to_numpy().astype(np.int64)
        mt = _lookup_table(weights, f, "m")
        ut = _lookup_table(weights, f, "u")
        agree = np.array([lev in AGREEMENT_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
        zero = np.array([lev in ZERO_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
        vspec = np.array([bool(value_specific(f, lev)) for lev in FIELD_LEVELS[f]])
        idx = np.where(lv >= 0, lv, 0)
        uv = levels[f"uv_{f}"].to_numpy(dtype=float) if f"uv_{f}" in levels else np.full(n, np.nan)
        use_v = vspec[idx] & ~np.isnan(uv)
        u = np.where(use_v, uv, ut[idx])
        u = np.clip(u, 1e-15, 1.0)
        bits = np.log2(np.clip(mt[idx], 1e-15, 1.0) / u)
        bits = np.where(agree[idx], np.maximum(bits, 0.0), bits)
        bits = np.where(zero[idx] | (lv < 0), 0.0, bits)
        out[f"bits_{f}"] = bits
        total += bits
    veto = np.full(n, "", dtype=object)
    for f in VETO_FIELDS:
        c = f"veto_{f}"
        if c in levels:
            v = levels[c].to_numpy(dtype=bool)
            veto = np.where(v, np.where(veto == "", f, veto + "+" + f), veto)
    out["bits"] = total
    out["logit"] = np.asarray(prior_logit, dtype=float) + total
    p = 1.0 / (1.0 + np.exp2(-np.clip(out["logit"].to_numpy(), -1000, 1000)))
    out["p"] = np.where(veto != "", 0.0, p)
    out["veto"] = veto
    out["basis"] = basis_of(levels, out, part)
    return out


def basis_of(levels, bits, part):
    """What the probability rests on, never upgraded by the score:
    identifier > address > dob > co_party > contextual (name + location/specialty/category)
    > name_only > none."""
    n = len(bits)
    pos = lambda f: (bits[f"bits_{f}"].to_numpy() > 0) if f"bits_{f}" in bits else np.zeros(n, bool)
    lv = lambda f: levels[f].to_numpy() if f in levels else np.full(n, EMPTY)
    ident = np.zeros(n, bool)
    for f in IDENTIFIER_FIELDS:
        if f in PART_FIELDS[part] and f in levels:
            exact = lv(f) == 0        # phone: only an owned, single-holder number
            ident |= exact & pos(f)
    addr = pos("address") & np.isin(lv("address"), [0, 1])
    location = pos("address") & np.isin(lv("address"), [2, 3, 4])
    dob = pos("dob") & np.isin(lv("dob"), [0, 1]) if part == "person" else np.zeros(n, bool)
    cop = pos("co_party")
    name = pos("name") | pos("org")
    context = name & (location | pos("spec_cat"))
    return np.select([ident, addr, dob & name, cop & name, context, name],
                     ["identifier", "address", "dob", "co_party", "contextual", "name_only"],
                     default="none").astype(object)


def apply_coparty(levels, scored, weights, prior_logit, anchored):
    """One-way co-party evidence for person pairs. `anchored`: boolean array, True where the
    two persons' tied businesses are linked on an identifier (p >= coparty_min_p, no veto),
    decided on business scores alone. Bits are added only where the names already agree, so
    a co-party can strengthen a name but never make one, and name-only links never vouch for
    each other. Returns re-scored pairs."""
    lev = levels.copy()
    has_tie = lev["co_party"].to_numpy() >= 0 if "co_party" in lev else np.zeros(len(lev), bool)
    name_agrees = scored["bits_name"].to_numpy() > 0
    code = np.where(has_tie, 1, EMPTY)
    code = np.where(has_tie & anchored & name_agrees, 0, code)
    lev["co_party"] = code.astype(np.int8)
    lev["uv_co_party"] = np.nan
    return lev, score_pairs(lev, "person", weights, prior_logit)


def evidence_rows(pair_ids, levels, scored, part, weights, values_l, values_r):
    """Long evidence: one row per pair and non-empty field (plus vetoing fields), with both
    values, the level, m and u with their sources and pair counts, and the bits. The rows of
    a pair sum to its total bits (the self-tests check it)."""
    rows = []
    w = weights.set_index(["field", "level_code"])
    for f in PART_FIELDS[part]:
        if f not in levels:
            continue
        lv = levels[f].to_numpy()
        keep = lv >= 0
        if not keep.any():
            continue
        idx = np.flatnonzero(keep)
        codes = lv[idx]
        sub = w.loc[[(f, int(c)) for c in codes]]
        uv = levels[f"uv_{f}"].to_numpy(dtype=float)[idx] if f"uv_{f}" in levels else np.full(len(idx), np.nan)
        vs = np.array([bool(x) for x in sub["u_value_specific"].to_numpy()])
        u_used = np.where(vs & ~np.isnan(uv), uv, sub["u"].to_numpy())
        rows.append(pd.DataFrame({
            "pair_id": np.asarray(pair_ids)[idx], "field": f,
            "value_extracted": values_l.get(f, np.full(len(lv), ""))[idx] if f in values_l else "",
            "value_watchlist": values_r.get(f, np.full(len(lv), ""))[idx] if f in values_r else "",
            "level": [FIELD_LEVELS[f][c] for c in codes],
            "m": sub["m"].to_numpy(), "m_source": sub["m_chain"].to_numpy(),
            "m_pairs": sub["m_pairs"].to_numpy(),
            "u": u_used,
            "u_source": np.where(vs & ~np.isnan(uv), sub["u_value_specific"].to_numpy(), sub["u_source"].to_numpy()),
            "u_pairs": sub["u_pairs"].to_numpy(),
            "bits": scored[f"bits_{f}"].to_numpy()[idx],
            "veto": levels[f"veto_{f}"].to_numpy()[idx] if f"veto_{f}" in levels else False,
        }))
    if not rows:
        return pd.DataFrame(columns=["pair_id", "field", "value_extracted", "value_watchlist", "level",
                                     "m", "m_source", "m_pairs", "u", "u_source", "u_pairs", "bits", "veto"])
    ev = pd.concat(rows, ignore_index=True)
    return ev.sort_values(["pair_id", "field"], kind="stable").reset_index(drop=True)

# %% [markdown]
# *End of the matching core.*
