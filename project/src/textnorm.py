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
