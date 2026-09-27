# ---- Matching core v1.1: normalizers ------------------------------------------------------
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
    The table lists relations both ways ('bill has_nickname robert'), so it is read as
    undirected, and a name's roots are itself plus every related name longer than it: BILL
    {BILL, ROBERT, WILLIAM} meets WILLIAM {WILLIAM}, and BILLY meets WILL through WILLIAM, but
    ROBERT {ROBERT} does not meet WILLIAM through BILL."""

    def __init__(self, table):
        nb = defaultdict(set)
        if table is not None and len(table):
            for a, b in zip(table["name1"].map(fold), table["name2"].map(fold)):
                nb[a].add(b)
                nb[b].add(a)
        self._roots = {n: {x for x in rel if len(x) > len(n)} for n, rel in nb.items()}
        self.size = len(table) if table is not None else 0

    def roots(self, first):
        cache = self.__dict__.setdefault("_cache", {})
        r = cache.get(first)
        if r is None:
            f = fold(first).split(" ")[0] if first else ""
            r = cache[first] = frozenset(self._roots.get(f, set()) | {f}) if f else frozenset()
        return r

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