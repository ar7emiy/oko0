"""Deterministic text normalization + fuzzy matching primitives.

Pure-python (no external deps) so it runs identically offline and on Colab and
so scoring is fully reproducible. Covers: name normalization + order-insensitive
Jaro-Winkler, soundex, nickname table, phone/address/email/identifier
normalization and validation.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_TITLES = {"dr", "mr", "mrs", "ms", "miss", "atty", "esq", "prof"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def name_tokens(s: str, drop_titles: bool = True, drop_suffix: bool = True) -> list[str]:
    toks = normalize_name(s).split()
    if drop_titles:
        toks = [t for t in toks if t not in _TITLES]
    if drop_suffix:
        toks = [t for t in toks if t not in _SUFFIXES]
    return toks


def name_suffix(s: str) -> str | None:
    for t in normalize_name(s).split():
        if t in _SUFFIXES:
            return t
    return None


# ---- Jaro / Jaro-Winkler ---------------------------------------------------
def jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    match_dist = max(len(s1), len(s2)) // 2 - 1
    match_dist = max(match_dist, 0)
    s1_m = [False] * len(s1)
    s2_m = [False] * len(s2)
    matches = 0
    for i, c in enumerate(s1):
        lo = max(0, i - match_dist)
        hi = min(i + match_dist + 1, len(s2))
        for j in range(lo, hi):
            if not s2_m[j] and s2[j] == c:
                s1_m[i] = s2_m[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    t = 0
    k = 0
    for i in range(len(s1)):
        if s1_m[i]:
            while not s2_m[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    t /= 2
    return (matches / len(s1) + matches / len(s2) + (matches - t) / matches) / 3.0


def jaro_winkler(s1: str, s2: str, p: float = 0.1, max_prefix: int = 4) -> float:
    j = jaro(s1, s2)
    prefix = 0
    for a, b in zip(s1, s2):
        if a == b:
            prefix += 1
        else:
            break
        if prefix == max_prefix:
            break
    return j + prefix * p * (1 - j)


def token_set_jw(a: str, b: str) -> float:
    """Order-insensitive name similarity: greedy best token-to-token JW match."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    # Greedy match each token in the smaller set to best remaining in the larger.
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    remaining = list(large)
    scores = []
    for t in small:
        if not remaining:
            break
        best_i, best_s = -1, -1.0
        for i, u in enumerate(remaining):
            s = jaro_winkler(t, u)
            if s > best_s:
                best_s, best_i = s, i
        scores.append(best_s)
        remaining.pop(best_i)
    # Penalize unmatched tokens in the larger set slightly.
    denom = len(large)
    return sum(scores) / denom if denom else 0.0


# ---- Soundex ---------------------------------------------------------------
_SOUNDEX_MAP = {
    **dict.fromkeys("bfpv", "1"),
    **dict.fromkeys("cgjkqsxz", "2"),
    **dict.fromkeys("dt", "3"),
    "l": "4",
    **dict.fromkeys("mn", "5"),
    "r": "6",
}


def soundex(name: str) -> str:
    name = re.sub(r"[^a-z]", "", normalize_name(name))
    if not name:
        return "0000"
    first = name[0].upper()
    encoded = []
    prev = _SOUNDEX_MAP.get(name[0], "")
    for c in name[1:]:
        d = _SOUNDEX_MAP.get(c, "")
        if d and d != prev:
            encoded.append(d)
        if c not in "hw":
            prev = d
    return (first + "".join(encoded) + "000")[:4]


# ---------------------------------------------------------------------------
# Nicknames (small curated table; enough for the planted hard cases)
# ---------------------------------------------------------------------------
_NICKNAME_GROUPS = [
    {"robert", "rob", "bob", "bobby", "bert"},
    {"william", "will", "bill", "billy", "liam"},
    {"richard", "rich", "rick", "dick", "ricky"},
    {"james", "jim", "jimmy", "jamie"},
    {"john", "jack", "johnny", "jon"},
    {"michael", "mike", "mickey", "mick"},
    {"thomas", "tom", "tommy"},
    {"charles", "charlie", "chuck", "chas"},
    {"joseph", "joe", "joey"},
    {"edward", "ed", "eddie", "ted", "teddy"},
    {"anthony", "tony"},
    {"daniel", "dan", "danny"},
    {"christopher", "chris", "topher"},
    {"matthew", "matt"},
    {"nicholas", "nick", "nico"},
    {"elizabeth", "liz", "beth", "betty", "eliza", "lizzie"},
    {"katherine", "catherine", "kate", "katie", "kathy", "cathy", "kat"},
    {"margaret", "maggie", "meg", "peggy", "marge"},
    {"patricia", "pat", "patty", "trish"},
    {"jennifer", "jen", "jenny"},
    {"deborah", "deb", "debbie"},
    {"susan", "sue", "susie"},
    {"rebecca", "becca", "becky"},
    {"jonathan", "jon", "jonny"},
    {"alexander", "alex", "al", "xander"},
    {"benjamin", "ben", "benny"},
    {"samuel", "sam", "sammy"},
    {"stephen", "steven", "steve", "stevie"},
    {"andrew", "andy", "drew"},
]
_NICK_INDEX: dict[str, int] = {}
for _gi, _g in enumerate(_NICKNAME_GROUPS):
    for _n in _g:
        _NICK_INDEX[_n] = _gi


def are_nickname_variants(a: str, b: str) -> bool:
    """True if the first tokens are nickname variants of each other."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    x, y = ta[0], tb[0]
    if x == y:
        return False
    gi, gj = _NICK_INDEX.get(x), _NICK_INDEX.get(y)
    return gi is not None and gi == gj


# ---------------------------------------------------------------------------
# Phones / addresses / emails
# ---------------------------------------------------------------------------
def phone_digits(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


def phone_last7(s: str) -> str:
    d = phone_digits(s)
    return d[-7:] if len(d) >= 7 else ""


_STREET_ABBR = {
    "street": "st", "st": "st", "avenue": "ave", "ave": "ave", "av": "ave",
    "boulevard": "blvd", "blvd": "blvd", "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln", "court": "ct",
    "ct": "ct", "suite": "ste", "ste": "ste", "apartment": "apt", "apt": "apt",
    "floor": "fl", "fl": "fl", "north": "n", "south": "s", "east": "e",
    "west": "w", "place": "pl", "pl": "pl", "parkway": "pkwy", "pkwy": "pkwy",
}


def normalize_address(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[.,#]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    toks = [_STREET_ABBR.get(t, t) for t in s.split()]
    return " ".join(toks).strip()


def address_key(s: str) -> str:
    """A coarse key: leading number + first street token + zip if present."""
    norm = normalize_address(s)
    if not norm:
        return ""
    m_num = re.match(r"(\d+)", norm)
    zip_m = re.search(r"\b(\d{5})\b", norm)
    toks = norm.split()
    street = ""
    for t in toks[1:] if m_num else toks:
        if not t.isdigit():
            street = t
            break
    parts = []
    if m_num:
        parts.append(m_num.group(1))
    if street:
        parts.append(street)
    if zip_m:
        parts.append(zip_m.group(1))
    return "|".join(parts)


def normalize_email(s: str) -> str:
    return (s or "").strip().lower()


def email_domain(s: str) -> str:
    e = normalize_email(s)
    return e.split("@", 1)[1] if "@" in e else ""


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
NPI_RE = re.compile(r"\b\d{10}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
TIN_RE = re.compile(r"\b\d{2}-\d{7}\b")


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
# A closed set, because half of these are also ordinary words ("in", "or",
# "me", "la", "pa") and a bare two-letter-token rule mislabels them. US-only and
# therefore a LOCALE ASSUMPTION -- this is one of the lexicons T4.1 makes
# loadable per client rather than compiled in.
US_STATES = frozenset("""
al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt
ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc pr
""".split())
# Notes are written by people, so both forms turn up. Spelled-out names are
# folded to the abbreviation before parsing rather than treated as a city.
US_STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "wisconsin": "wi",
    "wyoming": "wy",
}


def address_parts(s: str) -> dict:
    """Split an address into independently comparable components.

    WHY THIS EXISTS
    ---------------
    `address_key` collapses an address to one opaque composite
    (number|street|zip) which was then compared by ExactMatch only. Measured,
    that means agreement is all-or-nothing:

        "1420 Maple Street, Springfield, IL 62704"  -> 1420|maple|62704
        "1420 Maple Street, Springfield, IL"        -> 1420|maple

    Drop the zip and the pair earns NOT weaker evidence but *none*. And a
    city-only address collapses to "springfield|62704", which exact-matches
    every other address in that zip -- so the same mechanism carries a
    false-negative and a false-positive risk at once.

    Components let a graded comparison give partial credit for partial
    agreement, which is what a client with imperfect address data actually has.
    Correlation between the parts (same street implies same city) is handled by
    keeping them ONE comparison with ordered levels rather than several
    independent ones -- see entity_resolution.address_comparison.

    Returns {"street": ..., "city": ..., "state": ..., "zip": ...}; any
    component that is not present is "" rather than guessed.
    """
    raw = (s or "").strip()
    if not raw:
        return {"street": "", "city": "", "state": "", "zip": ""}

    zip_m = _ZIP_RE.search(raw)
    zip_code = zip_m.group(1) if zip_m else ""

    # Work on a token stream so punctuated and unpunctuated addresses take the
    # same path -- "220 W Adams St Chicago IL 60606" is as common in these notes
    # as the comma-separated form, and an earlier version parsed only the latter,
    # leaving "chicago il" glued onto the street.
    toks = [US_STATE_NAMES.get(t, t) for t in normalize_address(raw).split()]
    while toks and toks[-1] == zip_code:
        toks.pop()
    state = ""
    if toks and toks[-1] in US_STATES:
        state = toks.pop()

    # City is what sits between the street and the state. With commas, take the
    # field before the state; without, take the trailing non-street tokens.
    city = ""
    fields = [" ".join(US_STATE_NAMES.get(t, t) for t in normalize_address(f).split())
              for f in raw.split(",")]
    fields = [f for f in fields if f]
    if len(fields) >= 2:
        for i, f in enumerate(fields):
            if f.split() and f.split()[0] == state and i > 0:
                city = fields[i - 1]
                break
        else:
            tail = fields[-1].split()
            # "…, Springfield IL 62704" -- city and state share the last field
            if state and tail and tail[-1] in (zip_code, state):
                city = " ".join(t for t in tail
                                if t not in (zip_code, state)) or fields[-2]
    elif state and len(toks) > 1:
        # Unpunctuated: everything after the last street-type token is the city.
        types = set(_STREET_ABBR.values())
        last_type = max((i for i, t in enumerate(toks) if t in types), default=-1)
        if last_type >= 0 and last_type + 1 < len(toks):
            city = " ".join(toks[last_type + 1:])
            toks = toks[: last_type + 1]

    street = " ".join(toks)
    if city and street.endswith(city):
        street = street[: -len(city)].strip()
    if street and not re.match(r"^\d", street):
        street = ""              # "Springfield IL 62704" carries no street
    return {"street": street, "city": city, "state": state, "zip": zip_code}


# A VIN is 17 characters, excluding I, O and Q so they cannot be confused with
# 1 and 0. Position 9 is a check digit over the other 16 -- a real check, which
# is why VIN sits alongside NPI as "checksum" rather than "format".
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_VIN_TRANSLIT = {**{str(d): d for d in range(10)},
                 **{c: v for c, v in zip("ABCDEFGH", range(1, 9))},
                 **{c: v for c, v in zip("JKLMN", range(1, 6))},
                 "P": 7, "R": 9,
                 **{c: v for c, v in zip("STUVWXYZ", range(2, 10))}}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def vin_is_valid(vin: str) -> bool:
    """ISO 3779 check digit at position 9.

    Real validation, not a shape test: a random 17-character string passes the
    pattern about 1 in 11 times by luck, so without the check digit the VIN
    detector would be a false-positive generator over part numbers and claim
    references.
    """
    v = (vin or "").strip().upper()
    if len(v) != 17 or not VIN_RE.fullmatch(v):
        return False
    total = 0
    for ch, w in zip(v, _VIN_WEIGHTS):
        if ch not in _VIN_TRANSLIT:
            return False
        total += _VIN_TRANSLIT[ch] * w
    r = total % 11
    return v[8] == ("X" if r == 10 else str(r))


def npi_is_valid(npi: str) -> bool:
    """NPI = 10 digits with Luhn check over '80840' + first 9 digits."""
    npi = re.sub(r"\D", "", npi or "")
    if len(npi) != 10:
        return False
    payload = "80840" + npi[:9]
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    return check == int(npi[9])


def npi_checkdigit(first9: str) -> int:
    payload = "80840" + first9
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def normalize_identifier(kind: str, value: str) -> str:
    v = (value or "").strip()
    if kind in ("npi", "ssn", "tin", "phone"):
        return re.sub(r"\D", "", v)
    if kind == "email":
        return normalize_email(v)
    return v.lower()
