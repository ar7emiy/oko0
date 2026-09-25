# %% [markdown]
# ## Noise engine
#
# Noisy copies of input rows, driven by `mappings/simulation_noise.csv` (a pessimistic table,
# for review). The same engine makes the simulated true-match pairs for m (step 10), the
# synthetic extracted rows and the LEIE test set. Each copy records which noises hit it.
#
# **Where Splink would do better.** Splink has no simulator; its answer to missing labels is
# EM plus the user's own labels. Simulation here is a last-resort source of m and is flagged
# as such wherever it is used.

# %%
from wlink.core import *
from wlink.config import *

_TYPO_ALPHA = "ABCDEFGHIJKLMNOPRSTUVWY"
SUFFIX_WORDS = {"INC", "LLC", "PC", "PLLC", "CORP", "CO", "LTD", "LLP", "PA", "INCORPORATED",
                "CORPORATION", "COMPANY", "P.C.", "L.L.C.", "INC."}
ABBREV_OF = {v: k for k, v in ORG_ABBREV.items() if len(k) >= 3}

# A small fictional-use geography: real city / state / ZIP-prefix triples, fictional streets.
GEOGRAPHY = [
    ("BROOKLYN", "NY", "112"), ("QUEENS", "NY", "113"), ("BRONX", "NY", "104"), ("ALBANY", "NY", "122"),
    ("NEWARK", "NJ", "071"), ("PATERSON", "NJ", "075"), ("PHILADELPHIA", "PA", "191"), ("PITTSBURGH", "PA", "152"),
    ("BOSTON", "MA", "021"), ("WORCESTER", "MA", "016"), ("HARTFORD", "CT", "061"), ("PROVIDENCE", "RI", "029"),
    ("BALTIMORE", "MD", "212"), ("RICHMOND", "VA", "232"), ("CHARLOTTE", "NC", "282"), ("ATLANTA", "GA", "303"),
    ("MIAMI", "FL", "331"), ("ORLANDO", "FL", "328"), ("TAMPA", "FL", "336"), ("HIALEAH", "FL", "330"),
    ("DETROIT", "MI", "482"), ("CLEVELAND", "OH", "441"), ("COLUMBUS", "OH", "432"), ("CHICAGO", "IL", "606"),
    ("MILWAUKEE", "WI", "532"), ("MINNEAPOLIS", "MN", "554"), ("SAINT LOUIS", "MO", "631"), ("MEMPHIS", "TN", "381"),
    ("NEW ORLEANS", "LA", "701"), ("HOUSTON", "TX", "770"), ("DALLAS", "TX", "752"), ("SAN ANTONIO", "TX", "782"),
    ("PHOENIX", "AZ", "850"), ("DENVER", "CO", "802"), ("LAS VEGAS", "NV", "891"), ("LOS ANGELES", "CA", "900"),
    ("SAN DIEGO", "CA", "921"), ("FRESNO", "CA", "937"), ("SEATTLE", "WA", "981"), ("PORTLAND", "OR", "972"),
]
STREET_NAMES = ["MAPLE", "OAK", "CEDAR", "PINE", "ELM", "WILLOW", "BIRCH", "SPRUCE", "CHESTNUT", "WALNUT",
                "HICKORY", "MAGNOLIA", "DOGWOOD", "SYCAMORE", "LAUREL", "JUNIPER", "HAWTHORN", "ASPEN",
                "LINDEN", "POPLAR", "CYPRESS", "HOLLY", "IVY", "ORCHARD", "MEADOW", "PRAIRIE", "RIDGE",
                "SUMMIT", "VALLEY", "HILLSIDE", "LAKEVIEW", "RIVERSIDE", "BAYVIEW", "HARBOR", "SUNSET",
                "SUNRISE", "PARK", "GARDEN", "CHURCH", "SCHOOL", "MILL", "BRIDGE", "MARKET", "UNION",
                "LIBERTY", "FRANKLIN", "WASHINGTON", "JEFFERSON", "MADISON", "MONROE", "JACKSON", "LINCOLN",
                "GRANT", "HAMILTON", "ADAMS", "CLINTON", "KENNEDY", "HIGHLAND", "FOREST", "GREEN", "SPRING",
                "CENTER", "MAIN", "BROAD", "HIGH", "WATER", "FRONT", "CANAL", "STATION", "RAILROAD", "COLONIAL",
                "EUCLID", "KINGS", "QUEENS", "WINDSOR", "OXFORD", "CAMBRIDGE", "STRATFORD", "ASHFORD",
                "BRADFORD", "CLIFTON", "FAIRVIEW", "GLENWOOD", "KENWOOD", "LAKEWOOD", "MAPLEWOOD", "OAKWOOD",
                "ROSEWOOD", "WOODLAND", "WESTGATE", "EASTGATE", "NORTHGATE", "SOUTHGATE", "CROSSWIND",
                "WINDMILL", "BLUEBIRD", "CARDINAL", "ORIOLE", "HERON", "FALCON", "EAGLE", "HAWK", "SPARROW",
                "1ST", "2ND", "3RD", "4TH", "5TH", "6TH", "7TH", "8TH", "9TH", "10TH", "12TH", "14TH", "21ST",
                "34TH", "45TH", "79TH", "110TH"]
STREET_SUFFIXES = ["ST", "AVE", "RD", "DR", "LN", "CT", "BLVD", "PL", "WAY", "TER"]
SPECIALTIES = ["CHIROPRACTIC", "PHYSICAL THERAPY", "ACUPUNCTURE", "ORTHOPEDICS", "GENERAL PRACTICE",
               "PAIN MANAGEMENT", "RADIOLOGY", "NEUROLOGY", "PSYCHOLOGY", "PODIATRY", "INTERNAL MEDICINE",
               "OSTEOPATHY", "DENTISTRY", "PHARMACY", "NURSING"]


def luhn_npi(prefix9):
    """A valid NPI from nine digits."""
    total = 0
    for i, ch in enumerate(reversed("80840" + prefix9)):
        v = int(ch)
        if i % 2 == 0:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    return prefix9 + str((10 - total % 10) % 10)


def vin_with_check(body16, rng):
    """A VIN with a correct check digit from 16 characters (position 9 is replaced)."""
    v = list(body16[:8] + "0" + body16[8:16])
    r = sum(_VIN_MAP[c] * w for c, w in zip(v, _VIN_W)) % 11
    v[8] = "X" if r == 10 else str(r)
    return "".join(v)


class Fake:
    """Fictional values with realistic frequencies (names drawn from the Census and SSA
    tables), deterministic under one numpy Generator."""

    def __init__(self, ref, rng, n_surnames=30000, n_firsts=3000):
        self.rng = rng
        sn = sorted((ref.get("surnames") or {"SMITH": 1}).items(), key=lambda kv: -kv[1])[:n_surnames]
        fn = sorted((ref.get("first_names") or {"JOHN": 1}).items(), key=lambda kv: -kv[1])[:n_firsts]
        self.surnames = np.array([k for k, _ in sn], dtype=object)
        self.sw = np.array([v for _, v in sn], dtype=float); self.sw /= self.sw.sum()
        self.firsts = np.array([k for k, _ in fn], dtype=object)
        self.fw = np.array([v for _, v in fn], dtype=float); self.fw /= self.fw.sum()
        nick = ref.get("nicknames")
        self.nick_of = defaultdict(list)
        if nick is not None:
            for a, b in zip(nick["name1"].map(fold), nick["name2"].map(fold)):
                self.nick_of[a].append(b)

    def surname(self, n=None):
        return self.rng.choice(self.surnames, size=n, p=self.sw)

    def first(self, n=None):
        return self.rng.choice(self.firsts, size=n, p=self.fw)

    def digits(self, k):
        return "".join(str(x) for x in self.rng.integers(0, 10, k))

    def ssn(self):
        while True:
            s = f"{self.rng.integers(1, 899):03d}{self.rng.integers(1, 100):02d}{self.rng.integers(1, 10000):04d}"
            if norm_ssn(s)[1]:
                return s

    def tin(self):
        while True:
            s = f"{self.rng.integers(10, 99):02d}{self.rng.integers(0, 10 ** 7):07d}"
            if norm_tin(s)[1]:
                return s

    def npi(self):
        return luhn_npi(str(self.rng.integers(1, 3)) + self.digits(8))

    def phone(self):
        while True:
            s = f"{self.rng.integers(201, 990)}{self.rng.integers(200, 999)}{self.rng.integers(0, 10000):04d}"
            if norm_phone(s)[1]:
                return s

    def dob(self, lo=1940, hi=2002):
        y = int(self.rng.integers(lo, hi + 1)); m = int(self.rng.integers(1, 13)); d = int(self.rng.integers(1, 29))
        return f"{y:04d}-{m:02d}-{d:02d}"

    def address(self, state=None):
        g = [x for x in GEOGRAPHY if x[1] == state] if state else GEOGRAPHY
        if not g:
            g = GEOGRAPHY
        city, st, z3 = g[int(self.rng.integers(0, len(g)))]
        return {"street_number": str(int(self.rng.integers(1, 9999))), "street_direction": "",
                "street_name": str(self.rng.choice(STREET_NAMES)), "street_type": str(self.rng.choice(STREET_SUFFIXES)),
                "unit": (str(int(self.rng.integers(1, 40))) if self.rng.random() < 0.3 else ""),
                "city": city, "state": st, "zip": z3 + f"{int(self.rng.integers(0, 100)):02d}"}

    def email(self, first, last):
        dom = str(self.rng.choice(["mailbox.test", "post.test", "inbox.test", "webmail.test"]))
        return f"{first.lower()}.{last.lower()}{int(self.rng.integers(1, 999))}@{dom}".replace(" ", "")

    def dl(self):
        return str(self.rng.choice(list("ABCDEFGHJKLMNPRSTWY"))) + self.digits(7)

    def vin(self):
        chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
        body = "".join(self.rng.choice(list(chars), 16))
        return vin_with_check(body, self.rng)

    def plate(self):
        return "".join(self.rng.choice(list("ABCDEFGHJKLMNPRSTUVWXYZ"), 3)) + self.digits(4)


def _typo(s, rng):
    s = str(s)
    if len(s) < 3:
        return s
    i = int(rng.integers(1, len(s) - 1))
    op = int(rng.integers(0, 4))
    c = _TYPO_ALPHA[int(rng.integers(0, len(_TYPO_ALPHA)))]
    if op == 0:
        return s[:i] + c + s[i + 1:]
    if op == 1:
        return s[:i] + s[i + 1:]
    if op == 2:
        return s[:i] + c + s[i:]
    return s[:i - 1] + s[i] + s[i - 1] + s[i + 1:]


def _digit_typo(s, rng):
    d = [i for i, ch in enumerate(s) if ch.isdigit()]
    if not d:
        return s
    i = d[int(rng.integers(0, len(d)))]
    new = str((int(s[i]) + int(rng.integers(1, 10))) % 10)
    return s[:i] + new + s[i + 1:]


def _transpose(s, rng):
    d = [i for i in range(len(s) - 1) if s[i].isdigit() and s[i + 1].isdigit() and s[i] != s[i + 1]]
    if not d:
        return s
    i = d[int(rng.integers(0, len(d)))]
    return s[:i] + s[i + 1] + s[i] + s[i + 2:]


def apply_noise(rows, noise, fake, rng, scale=1.0, id_prefix="sim"):
    """Noisy copies of input-schema rows. `noise`: the simulation_noise table; `scale`
    multiplies every rate. Returns (copies, log) where log lists the noises per copy."""
    rate = {n: float(r) * scale for n, r in zip(noise["noise"], noise["rate"])}
    hit = lambda n: rng.random() < rate.get(n, 0.0)
    cats = ["medical", "legal", "repair shop", "witness", "claimant", "other"]
    out, log = [], []
    for i, r in enumerate(rows.to_dict("records")):
        r = dict(r)
        applied = []

        def did(n):
            applied.append(n)
        has_person = bool(r.get("first_name") or r.get("last_name"))
        if has_person:
            last, first = r.get("last_name", ""), r.get("first_name", "")
            if last and hit("surname_typo"):
                last = _typo(last, rng); did("surname_typo")
            if last and re.search(r"[ \-]", last) and hit("surname_compound_dropped"):
                last = re.split(r"[ \-]", last)[0]; did("surname_compound_dropped")
            if last and hit("surname_change"):
                last = str(fake.surname()).title(); did("surname_change")
            f = fold(first)
            if f and hit("first_nickname") and fake.nick_of.get(f):
                opts = fake.nick_of[f]
                first = opts[int(rng.integers(0, len(opts)))].title(); did("first_nickname")
            elif f and hit("first_initial_only"):
                first = f[0]; did("first_initial_only")
            elif f and hit("first_typo"):
                first = _typo(first, rng); did("first_typo")
            elif f and hit("first_missing"):
                first = ""; did("first_missing")
            if first and last and hit("names_swapped"):
                first, last = last, first; did("names_swapped")
            r["first_name"], r["last_name"] = first, last
            mid = r.get("middle_name", "")
            if mid:
                if hit("middle_dropped"):
                    mid = ""; did("middle_dropped")
                elif hit("middle_initial"):
                    mid = mid[0]; did("middle_initial")
            r["middle_name"] = mid
            dob = r.get("dob", "")
            if dob:
                y, m, d = dob[:4], dob[5:7], dob[8:10]
                if hit("dob_missing"):
                    dob = ""; did("dob_missing")
                elif hit("dob_placeholder"):
                    dob = "1900-01-01"; did("dob_placeholder")
                elif int(d) <= 12 and d != m and hit("dob_day_month_swap"):
                    dob = f"{y}-{d}-{m}"; did("dob_day_month_swap")
                elif hit("dob_digit_typo"):
                    for _ in range(10):
                        cand = _digit_typo(dob.replace("-", ""), rng)
                        iso, ok, _r = norm_dob(cand)
                        if ok:
                            dob = iso; break
                    did("dob_digit_typo")
                elif hit("dob_year_off"):
                    dob = f"{int(y) + (1 if rng.random() < 0.5 else -1):04d}-{m}-{d}"; did("dob_year_off")
                r["dob"] = dob
            if r.get("provider_specialty") and hit("specialty_coarser"):
                r["provider_specialty"] = "PHYSICIAN"; did("specialty_coarser")
        for col in ("ssn", "provider_npi", "driver_license_number", "tin"):
            v = r.get(col, "")
            if v:
                if hit("id_digit_typo"):
                    r[col] = _digit_typo(v, rng); did(f"id_digit_typo:{col}")
                elif hit("id_transposition"):
                    r[col] = _transpose(v, rng); did(f"id_transposition:{col}")
        if r.get("street_name") or r.get("zip") or r.get("state"):
            if hit("moved_within_state"):
                r.update(fake.address(r.get("state") or None)); did("moved_within_state")
            elif hit("moved_other_state"):
                others = [g[1] for g in GEOGRAPHY if g[1] != r.get("state")]
                r.update(fake.address(others[int(rng.integers(0, len(others)))])); did("moved_other_state")
            if r.get("unit") and hit("unit_dropped"):
                r["unit"] = ""; did("unit_dropped")
            if r.get("zip") and hit("zip_typo"):
                r["zip"] = _digit_typo(r["zip"], rng); did("zip_typo")
        for col in ("home_phone", "work_phone"):
            if r.get(col) and hit("phone_changed"):
                r[col] = fake.phone(); did(f"phone_changed:{col}")
        if r.get("email") and hit("email_changed"):
            r["email"] = fake.email(fold(r.get("first_name") or "info") or "info",
                                    fold(r.get("last_name") or "office") or "office"); did("email_changed")
        b = r.get("business_name", "")
        if b:
            if _DBA_RE.search(b) and hit("business_dba_used"):
                b = _DBA_RE.split(b)[-1].strip(" ,"); did("business_dba_used")
            words = b.split()
            if len(words) > 1 and words[-1].upper().strip(",.") in SUFFIX_WORDS and hit("business_suffix_dropped"):
                b = " ".join(words[:-1]).strip(" ,"); did("business_suffix_dropped")
            words = b.split()
            ab = [j for j, w in enumerate(words) if w.upper() in ABBREV_OF]
            if ab and hit("business_abbreviated"):
                j = ab[int(rng.integers(0, len(ab)))]
                words[j] = ABBREV_OF[words[j].upper()].title(); b = " ".join(words); did("business_abbreviated")
            if hit("business_typo"):
                words = b.split()
                j = int(rng.integers(0, len(words)))
                if len(words[j]) >= 5:
                    words[j] = _typo(words[j], rng); b = " ".join(words); did("business_typo")
            r["business_name"] = b
        if r.get("category") and hit("category_disagrees"):
            r["category"] = str(rng.choice([c for c in cats if c != r["category"]])); did("category_disagrees")
        r["record_id"] = f"{id_prefix}:{r['record_id']}"
        out.append(r)
        log.append(";".join(applied))
    return pd.DataFrame(out, columns=list(rows.columns)), log
