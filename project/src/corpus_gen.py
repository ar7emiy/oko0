"""Deterministic synthetic corpus generator (v2) + sealed ground-truth manifest.

WHY DETERMINISTIC (not LLM-authored): the manifest must record the EXACT
char_start/char_end of every planted mention, written in the same pass that
plants it. An LLM cannot guarantee it placed a surface at a known offset, so
every note is assembled from fragments through a byte-accurate NoteBuilder and
each placement is recorded as it is emitted.

WHAT CHANGED FROM v1
--------------------
v1 produced ~65-word, 34%-template, claim-scoped notes with two planted
cross-claim cases. Every downstream measurement taken against it was therefore
suspect. v2 rebuilds the fixture to match the real data shape:

  * occurrence -> claim -> note hierarchy (1-4 claims per occurrence)
  * 250-500 word notes, predominantly free-text narrative
  * power-law entity recurrence, so cross-claim overlap is the norm
  * IDENTIFIERS as first-class ground truth, with association windows and
    deliberate name-less ("orphan") mentions
  * COREFERENCE CHAINS with the true referent AND hop count, so the multi-hop
    "hopping" failure mode is measurable for the first time
  * EVENTS (dated actions with no external id) and OPEN-VOCABULARY
    RELATIONSHIPS beyond the four role types

This module and src/audit.py + src/ablation.py are the only code permitted to
touch data/ground_truth. This one is the writer.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field

from . import textnorm
from .settings import CFG, Paths

# ---------------------------------------------------------------------------
# Static pools
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Robert", "William", "Richard", "James", "John", "Michael", "Thomas",
    "Charles", "Joseph", "Edward", "Anthony", "Daniel", "Christopher",
    "Matthew", "Nicholas", "Elizabeth", "Katherine", "Margaret", "Patricia",
    "Jennifer", "Deborah", "Susan", "Rebecca", "Jonathan", "Alexander",
    "Benjamin", "Samuel", "Stephen", "Andrew", "Maria", "Elena", "Diego",
    "Priya", "Wei", "Omar", "Fatima", "Sofia", "Hassan", "Alicia", "Marcus",
    "Yusuf", "Ingrid", "Tomas", "Nadia", "Peter", "Grace", "Lucas", "Amara",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Rios", "Nguyen", "Patel", "Kim", "Okafor", "Rossi", "Petrov", "Reyes",
    "Okonjo", "Vance", "Delgado", "Whitfield", "Sterling", "Larkin", "Ibarra",
]
LAW_FIRMS = [
    ("XYZ Law Group", "xyzlawgroup.com"),
    ("Harbor & Vance LLP", "harborvance.com"),
    ("Sterling Injury Attorneys", "sterlinginjury.com"),
    ("Delgado Legal Partners", "delgadolegal.com"),
    ("Whitfield Trial Group", "whitfieldtrial.com"),
    ("Ibarra & Cole", "ibarracole.com"),
]
CITIES = [
    ("Springfield", "IL", "627"), ("Riverton", "NJ", "080"),
    ("Fairview", "TX", "750"), ("Lakewood", "CO", "802"),
    ("Ashford", "GA", "301"), ("Bristol", "PA", "190"),
    ("Northline", "OH", "441"), ("Kelso", "WA", "986"),
]
STREETS = ["Maple", "Oak", "Cedar", "Elm", "Washington", "Lincoln", "Park",
           "Market", "Highland", "Franklin", "Sunset", "Willow", "Larkin", "Grand"]
STREET_TYPES = ["St", "Ave", "Blvd", "Rd", "Dr", "Ln", "Ct"]
PROVIDER_SUFFIX = ["Orthopedics", "Physical Therapy", "Imaging Center",
                   "Medical Group", "Chiropractic", "Neurology Associates",
                   "Spine Institute", "Rehabilitation Services"]
SHOP_SUFFIX = ["Auto Body", "Collision Center", "Automotive", "Car Care",
               "Body Works", "Repair", "Frame & Paint"]
OCCURRENCE_TYPES = ["rear-end collision", "multi-vehicle collision",
                    "slip and fall", "intersection collision", "sideswipe",
                    "parking lot impact", "premises liability incident"]

DISCLAIMER = (
    "CONFIDENTIALITY NOTICE: This email and any attachments are for the sole use "
    "of the intended recipient and may contain privileged information. If you are "
    "not the intended recipient, please notify the sender and delete this message."
)
PLACEHOLDERS = ["xx", "N/A", "TBD", "same as above", "___", "____", "pending", "-"]


# ---------------------------------------------------------------------------
# Ground-truth records
# ---------------------------------------------------------------------------
@dataclass
class GTEntity:
    gt_entity_id: str
    klass: str
    first: str = ""
    last: str = ""
    suffix: str = ""
    org_name: str = ""
    firm: str = ""
    dob: str = ""
    identifiers: list = field(default_factory=list)   # gt_identifier_ids
    claims: set = field(default_factory=set)
    occurrences: set = field(default_factory=set)
    roles_per_claim: dict = field(default_factory=dict)
    hard_case_tags: list = field(default_factory=list)

    def display_name(self) -> str:
        if self.org_name:
            return self.org_name
        n = f"{self.first} {self.last}".strip()
        return f"{n} {self.suffix}".strip() if self.suffix else n

    def short_name(self) -> str:
        if self.org_name:
            return self.org_name
        return f"{self.last}" if self.last else self.org_name

    def is_person(self) -> bool:
        return bool(self.first) and not self.org_name


@dataclass
class GTIdentifier:
    gt_identifier_id: str
    kind: str
    value: str
    # [{gt_entity_id, valid_from, valid_to}] -- an identifier may change hands
    associations: list = field(default_factory=list)

    def owner_at(self, date: str | None = None) -> str | None:
        for a in self.associations:
            if a["valid_to"] is None:
                return a["gt_entity_id"]
        return self.associations[0]["gt_entity_id"] if self.associations else None


@dataclass
class GTEvent:
    gt_event_id: str
    etype: str
    date: str
    claim_id: str
    participants: list = field(default_factory=list)   # [{gt_entity_id, role}]


@dataclass
class GTRelationship:
    subject: str
    predicate: str
    obj: str
    claim_id: str


# ---------------------------------------------------------------------------
# RNG helpers
# ---------------------------------------------------------------------------
class _Rng:
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def pick(self, seq):
        return self.r.choice(list(seq))

    def chance(self, p):
        return self.r.random() < p

    def intr(self, a, b):
        return self.r.randint(a, b)

    def sample(self, seq, k):
        seq = list(seq)
        return self.r.sample(seq, min(k, len(seq)))

    def weighted(self, mapping: dict):
        ks = list(mapping)
        return self.r.choices(ks, weights=[mapping[k] for k in ks], k=1)[0]

    def shuffle(self, seq):
        self.r.shuffle(seq)
        return seq


def _powerlaw_weights(n: int, alpha: float) -> list[float]:
    """Zipf-like weights: rank i gets 1/(i+1)^alpha. Lower alpha -> heavier skew."""
    return [1.0 / ((i + 1) ** alpha) for i in range(n)]


# ---------------------------------------------------------------------------
# Value generators
# ---------------------------------------------------------------------------
def _gen_phone(rng):
    return f"({rng.intr(200,989)}) {rng.intr(200,999)}-{rng.intr(1000,9999)}"


def _gen_address(rng):
    city, state, z3 = rng.pick(CITIES)
    return (f"{rng.intr(10,9999)} {rng.pick(STREETS)} {rng.pick(STREET_TYPES)}, "
            f"{city}, {state} {z3}{rng.intr(10,99)}")


def _gen_npi(rng):
    first9 = "".join(str(rng.intr(0, 9)) for _ in range(9))
    if first9[0] == "0":
        first9 = "1" + first9[1:]
    return first9 + str(textnorm.npi_checkdigit(first9))


def _gen_tin(rng):
    return f"{rng.intr(10,99)}-{rng.intr(1000000,9999999)}"


def _gen_ssn(rng):
    return f"{rng.intr(100,899)}-{rng.intr(10,99)}-{rng.intr(1000,9999)}"


def _gen_vin(rng):
    """A VIN that passes its own ISO 3779 check digit.

    The previous version returned 17 random characters. That is not a VIN: the
    ninth character is a weighted check digit over the other sixteen, so a
    random string fails validation about ten times in eleven. Any detector that
    validates -- as gazetteers now does, deliberately, because the bare
    17-character shape matches part numbers and claim references -- would have
    rejected every planted VIN and scored 0% recall on a fixture that looked
    correct.

    Same principle as _gen_npi: a synthetic identifier that does not satisfy its
    own checksum tests the wrong thing.
    """
    chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    body = [rng.pick(chars) for _ in range(17)]
    body[8] = "0"                                  # placeholder; replaced below
    weights = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
    xl = {**{str(d): d for d in range(10)},
          **{c: v for c, v in zip("ABCDEFGH", range(1, 9))},
          **{c: v for c, v in zip("JKLMN", range(1, 6))},
          "P": 7, "R": 9,
          **{c: v for c, v in zip("STUVWXYZ", range(2, 10))}}
    total = sum(xl[c] * w for c, w in zip(body, weights))
    r = total % 11
    body[8] = "X" if r == 10 else str(r)
    return "".join(body)


def _gen_dob(rng):
    return f"{rng.intr(1,12):02d}/{rng.intr(1,28):02d}/{rng.intr(1948,2005)}"


def _gen_date(rng, y0=2024, y1=2026):
    return f"{rng.intr(y0,y1)}-{rng.intr(1,12):02d}-{rng.intr(1,28):02d}"


def _typo(s: str, rng) -> str:
    if len(s) < 4:
        return s
    i = rng.intr(1, len(s) - 2)
    if rng.chance(0.5):
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return s[:i] + s[i] + s[i:]


def name_variants(ent: GTEntity, rng) -> dict:
    """Surface variants for an entity: {variant_kind: surface}."""
    out = {"canonical": ent.display_name()}
    if ent.org_name and not ent.first:
        out["short"] = ent.org_name.split()[0]
        return out
    first, last = ent.first, ent.last
    out["flip"] = f"{last}, {first}" + (f" {ent.suffix}" if ent.suffix else "")
    out["initials"] = f"{first[0]}. {last}"
    out["last_only"] = f"{'Dr. ' if ent.klass == 'medical_provider' else ''}{last}"
    grp = textnorm._NICK_INDEX.get(first.lower())
    if grp is not None:
        variants = [v for v in textnorm._NICKNAME_GROUPS[grp] if v != first.lower()]
        if variants:
            out["nickname"] = f"{rng.pick(sorted(variants)).capitalize()} {last}"
    out["typo"] = _typo(ent.display_name(), rng)
    return out


def identifier_variants(ident, rng) -> dict:
    """Surface variants for one identifier VALUE: {variant_kind: surface}.

    The fixture planted name variants from the start -- order flips, nicknames,
    initials, typos -- and 92% of entities appear under more than one surface.
    It planted NO identifier variants: measured, 0 of 1,341 identifier values
    was ever written two different ways (D23). Formats differed *between*
    values, never *within* one.

    That left the identifier half of the system validated only against its best
    case. `textnorm.normalize_identifier` could not be tested at all -- there
    was nothing to normalize -- and D15 (`who_is_at` normalising differently
    from the indexer, so every phone and address lookup returned [], always)
    survived in exactly that blind spot.

    These are the forms a claim note actually contains. Some of them the system
    handles by construction (digits-only normalisation folds phone punctuation);
    at least one it does not (an extension survives \\D stripping and changes
    the normalised value). Both outcomes are the point: this exists to make the
    identifier lanes falsifiable, not to be passed.
    """
    v = ident.value
    out = {"canonical": v}
    k = ident.kind
    if k == "phone":
        d = re.sub(r"\D", "", v)
        if len(d) == 10:
            out["punct_paren"] = f"({d[:3]}) {d[3:6]}-{d[6:]}"
            out["punct_dot"] = f"{d[:3]}.{d[3:6]}.{d[6:]}"
            out["bare"] = d
            out["extension"] = f"{d[:3]}-{d[3:6]}-{d[6:]} ext. {rng.intr(10, 899)}"
    elif k == "email":
        out["mixed_case"] = ".".join(p.capitalize() for p in v.split("@")[0].split(".")) \
            + "@" + v.split("@")[1]
        out["upper_domain"] = v.split("@")[0] + "@" + v.split("@")[1].upper()
    elif k in ("ssn", "tin"):
        out["bare"] = re.sub(r"\D", "", v)
    elif k == "vin":
        out["lowercase"] = v.lower()
    elif k == "address":
        long_form = {"St": "Street", "Ave": "Avenue", "Rd": "Road", "Dr": "Drive",
                     "Blvd": "Boulevard", "Ct": "Court", "Ln": "Lane",
                     "Pl": "Place", "Pkwy": "Parkway"}
        spelled = v
        for short, full in long_form.items():
            spelled = re.sub(rf"\b{short}\b", full, spelled)
        if spelled != v:
            out["spelled_street"] = spelled
        out["no_zip"] = re.sub(r"\s*\b\d{5}(?:-\d{4})?\b", "", v).rstrip(", ")
        m = re.match(r"(\d+\s+\S+(?:\s+\S+)?)(,.*)$", v)
        if m:
            out["with_suite"] = f"{m.group(1)} Suite {rng.intr(100, 899)}{m.group(2)}"
    return out


# ---------------------------------------------------------------------------
# NoteBuilder -- byte-accurate assembly + placement recording
# ---------------------------------------------------------------------------
class NoteBuilder:
    """Assembles a note and records the exact offsets of everything planted."""

    def __init__(self, doc_id: str, claim_id: str, occurrence_id: str, rng=None):
        # rng is optional so the builder stays usable without one, but with it
        # add_identifier plants surface VARIANTS -- see identifier_variants.
        self.rng = rng
        self.doc_id = doc_id
        self.claim_id = claim_id
        self.occurrence_id = occurrence_id
        self.buf: list[str] = []
        self.n = 0
        self.placements: list[dict] = []
        self.non_entities: list[dict] = []
        self.coref_chains: list[dict] = []
        self._seg = "narrative"
        self._quoted = False
        # per-entity anaphora state for hop counting
        self._last_name_span: dict[str, tuple] = {}
        self._last_anaphor: dict[str, dict] = {}

    # -- primitives --------------------------------------------------------
    def segment(self, kind: str, quoted: bool = False):
        self._seg, self._quoted = kind, quoted
        return self

    def add(self, s: str) -> tuple[int, int]:
        start = self.n
        self.buf.append(s)
        self.n += len(s)
        return start, self.n

    def words(self) -> int:
        return len("".join(self.buf).split())

    def text(self) -> str:
        return "".join(self.buf)

    # -- planted things ----------------------------------------------------
    def add_entity(self, surface: str, ent: GTEntity, variant: str) -> tuple[int, int]:
        s, e = self.add(surface)
        self.placements.append({
            "kind": "entity", "gt_id": ent.gt_entity_id,
            "doc_id": self.doc_id, "char_start": s, "char_end": e,
            "surface": surface, "variant_kind": variant,
            "inside_quoted_dup": self._quoted, "segment_kind": self._seg,
        })
        self._last_name_span[ent.gt_entity_id] = (s, e)
        self._last_anaphor.pop(ent.gt_entity_id, None)   # chain restarts at a name
        return s, e

    def add_identifier(self, ident: GTIdentifier, orphan: bool = False) -> tuple[int, int]:
        # Canonical most of the time, a variant sometimes. Keeping canonical
        # dominant matters: with ~3 placements per identifier it leaves nearly
        # every value at least one canonical sighting, so a variant that fails
        # to normalise shows up as a SPLIT rather than as a value the corpus
        # never wrote down plainly.
        surface, vkind = ident.value, "canonical"
        if self.rng is not None and self.rng.chance(0.40):
            vs = {k: s for k, s in identifier_variants(ident, self.rng).items()
                  if k != "canonical" and s and s != ident.value}
            if vs:
                vkind = self.rng.pick(sorted(vs))
                surface = vs[vkind]
        s, e = self.add(surface)
        self.placements.append({
            "kind": "identifier", "gt_id": ident.gt_identifier_id,
            "doc_id": self.doc_id, "char_start": s, "char_end": e,
            "surface": surface, "variant_kind": vkind,
            "identifier_kind": ident.kind,
            "orphan": orphan,   # True => no name co-located; must resolve via the id
            "inside_quoted_dup": self._quoted, "segment_kind": self._seg,
        })
        return s, e

    def add_event(self, surface: str, ev: GTEvent) -> tuple[int, int]:
        s, e = self.add(surface)
        self.placements.append({
            "kind": "event", "gt_id": ev.gt_event_id,
            "doc_id": self.doc_id, "char_start": s, "char_end": e,
            "surface": surface, "event_type": ev.etype,
            "inside_quoted_dup": self._quoted, "segment_kind": self._seg,
        })
        return s, e

    def add_anaphor(self, surface: str, ent: GTEntity, kind: str) -> tuple[int, int] | None:
        """Emit a pronoun/descriptor pointing back at `ent`, recording hop depth.

        hops=1 points straight at a named mention; hops>=2 points at a previous
        anaphor which itself points back -- the multi-hop case that breaks
        naive nearest-mention resolvers.
        """
        gid = ent.gt_entity_id
        if gid not in self._last_name_span:
            return None
        prev = self._last_anaphor.get(gid)
        if prev is not None and prev["hops"] < CFG.COREF_MAX_HOPS:
            hops = prev["hops"] + 1
            chain = prev["chain"] + [[prev["start"], prev["end"]]]
        else:
            hops = 1
            chain = [list(self._last_name_span[gid])]
        s, e = self.add(surface)
        rec = {
            "doc_id": self.doc_id, "anaphor_start": s, "anaphor_end": e,
            "anaphor_text": surface, "anaphor_kind": kind,
            "referent_gt_entity_id": gid, "hops": hops,
            "chain": chain + [[s, e]],
            "segment_kind": self._seg,
        }
        self.coref_chains.append(rec)
        self._last_anaphor[gid] = {"start": s, "end": e, "hops": hops, "chain": chain}
        return s, e

    def add_placeholder(self, surface: str, kind: str = "placeholder") -> tuple[int, int]:
        s, e = self.add(surface)
        self.non_entities.append({
            "doc_id": self.doc_id, "char_start": s, "char_end": e,
            "text": surface, "kind": kind,
        })
        return s, e


# ---------------------------------------------------------------------------
# Population building
# ---------------------------------------------------------------------------
def expected_claims() -> int:
    """Expected claim count from the occurrence fanout distribution."""
    ev = sum(int(k) * v for k, v in CFG.CLAIMS_PER_OCCURRENCE_WEIGHTS.items())
    return max(1, int(round(CFG.N_OCCURRENCES * ev)))


def build_population(rng: _Rng, n_claims_est: int | None = None):
    """Create entities and the identifier pool bound to them.

    Claimants scale with the claim count (most appear once); professional pools
    are fixed and much smaller, which is what produces recurrence.
    """
    n_claims_est = n_claims_est or expected_claims()
    ents: list[GTEntity] = []
    idents: list[GTIdentifier] = []
    used = set()
    counters = {"i": 0}

    def new_ident(kind, value, owner, valid_from="2019-01-01", valid_to=None):
        counters["i"] += 1
        gid = f"gt_id_{counters['i']:04d}"
        gi = GTIdentifier(gt_identifier_id=gid, kind=kind, value=value,
                          associations=[{"gt_entity_id": owner, "valid_from": valid_from,
                                         "valid_to": valid_to}])
        idents.append(gi)
        return gi

    def fresh_person():
        for _ in range(80):
            f, l = rng.pick(FIRST_NAMES), rng.pick(LAST_NAMES)
            if (f, l) not in used:
                used.add((f, l))
                return f, l
        return rng.pick(FIRST_NAMES), rng.pick(LAST_NAMES)

    def attach(ent, kinds):
        for kind in kinds:
            if kind == "phone":
                gi = new_ident("phone", _gen_phone(rng), ent.gt_entity_id)
            elif kind == "address":
                gi = new_ident("address", _gen_address(rng), ent.gt_entity_id)
            elif kind == "email":
                dom = ent.firm and dict(LAW_FIRMS).get(ent.firm) or "example.com"
                if ent.klass == "adjuster":
                    val = f"{ent.first[0].lower()}{ent.last.lower()}@ourinsco.com"
                elif ent.klass == "attorney":
                    dom = next((d for f, d in LAW_FIRMS if f == ent.firm), "example.com")
                    val = f"{ent.first.lower()}.{ent.last.lower()}@{dom}"
                else:
                    val = f"{ent.short_name().lower().replace(' ','')}@{rng.pick(['northlineortho.com','medgroup.net','clinicmail.com'])}"
                gi = new_ident("email", val, ent.gt_entity_id)
            elif kind == "npi":
                gi = new_ident("npi", _gen_npi(rng), ent.gt_entity_id)
            elif kind == "tin":
                gi = new_ident("tin", _gen_tin(rng), ent.gt_entity_id)
            elif kind == "ssn":
                gi = new_ident("ssn", _gen_ssn(rng), ent.gt_entity_id)
            elif kind == "vin":
                gi = new_ident("vin", _gen_vin(rng), ent.gt_entity_id)
            else:
                continue
            ent.identifiers.append(gi.gt_identifier_id)

    # ---- claimants ----
    n_clm = max(1, int(n_claims_est * CFG.CLAIMANT_POOL_RATIO))
    for i in range(n_clm):
        f, l = fresh_person()
        e = GTEntity(f"gt_clm_{i:04d}", "claimant", first=f, last=l, dob=_gen_dob(rng))
        ents.append(e)
        attach(e, ["phone", "address"] + (["ssn"] if rng.chance(0.35) else [])
               + (["vin"] if rng.chance(0.45) else []))

    # ---- attorneys ----
    n_att = CFG.N_ATTORNEYS
    for i in range(n_att):
        f, l = fresh_person()
        firm, _dom = LAW_FIRMS[i % len(LAW_FIRMS)] if rng.chance(0.7) else rng.pick(LAW_FIRMS)
        e = GTEntity(f"gt_att_{i:04d}", "attorney", first=f, last=l, firm=firm)
        ents.append(e)
        attach(e, ["email", "phone", "address"])

    # ---- medical providers ----
    n_prv = CFG.N_PROVIDERS
    for i in range(n_prv):
        if rng.chance(0.55):
            f, l = fresh_person()
            e = GTEntity(f"gt_prv_{i:04d}", "medical_provider", first=f, last=l,
                         org_name=f"Dr. {f} {l}")
        else:
            l = rng.pick(LAST_NAMES)
            e = GTEntity(f"gt_prv_{i:04d}", "medical_provider",
                         org_name=f"{l} {rng.pick(PROVIDER_SUFFIX)}")
        ents.append(e)
        attach(e, ["npi", "phone", "address"] + (["email"] if rng.chance(0.5) else []))

    # ---- repair shops ----
    n_shp = CFG.N_REPAIR_SHOPS
    for i in range(n_shp):
        l = rng.pick(LAST_NAMES)
        e = GTEntity(f"gt_shp_{i:04d}", "repair_shop",
                     org_name=f"{l} {rng.pick(SHOP_SUFFIX)}")
        ents.append(e)
        attach(e, ["tin", "phone", "address"])

    # ---- adjusters ----
    n_adj = CFG.N_ADJUSTERS
    for i in range(n_adj):
        f, l = fresh_person()
        e = GTEntity(f"gt_adj_{i:04d}", "adjuster", first=f, last=l)
        ents.append(e)
        attach(e, ["email", "phone"])

    _plant_hard_cases(ents, idents, rng, new_ident)
    _reassign_identifiers(ents, idents, rng)
    return ents, idents


def _reassign_identifiers(ents, idents, rng):
    """Hand a share of identifiers from one entity to another over time.

    Without this the temporal dimension of identifier association is untestable:
    every identifier would have exactly one owner forever, and a resolver could
    ignore validity windows with no penalty.
    """
    by_class = {}
    for e in ents:
        by_class.setdefault(e.klass, []).append(e)
    reassignable = [i for i in idents
                    if i.kind in ("phone", "address", "email")
                    and len(i.associations) == 1]
    n = int(len(reassignable) * CFG.IDENTIFIER_REASSIGN_RATIO)
    for gi in rng.sample(reassignable, n):
        prev_owner = gi.associations[0]["gt_entity_id"]
        prev = next((e for e in ents if e.gt_entity_id == prev_owner), None)
        if prev is None:
            continue
        pool = by_class.get(prev.klass, [])
        cand = [e for e in pool if e.gt_entity_id != prev_owner]
        if not cand:
            continue
        new_owner = rng.pick(cand)
        cutoff = _gen_date(rng, 2024, 2025)
        gi.associations[0]["valid_to"] = cutoff
        gi.associations.append({"gt_entity_id": new_owner.gt_entity_id,
                                "valid_from": cutoff, "valid_to": None})
        new_owner.identifiers.append(gi.gt_identifier_id)
        prev.hard_case_tags.append("identifier_reassigned")
        new_owner.hard_case_tags.append("identifier_reassigned")


def _plant_hard_cases(ents, idents, rng, new_ident):
    """Deliberate resolution traps, each tagged so the audit can break out recall."""
    by_class: dict[str, list[GTEntity]] = {}
    for e in ents:
        by_class.setdefault(e.klass, []).append(e)
    ident_by_id = {i.gt_identifier_id: i for i in idents}

    def ids_of(ent, kind):
        return [ident_by_id[i] for i in ent.identifiers if ident_by_id[i].kind == kind]

    clms = by_class.get("claimant", [])
    prvs = by_class.get("medical_provider", [])
    shps = by_class.get("repair_shop", [])
    atts = by_class.get("attorney", [])

    # Jr/Sr pair sharing an address
    if len(clms) >= 2:
        sr, jr = clms[0], clms[1]
        jr.first, jr.last = sr.first, sr.last
        sr.suffix, jr.suffix = "Sr", "Jr"
        sr_addr = ids_of(sr, "address")
        if sr_addr:
            jr.identifiers = [i for i in jr.identifiers
                              if ident_by_id[i].kind != "address"] + [sr_addr[0].gt_identifier_id]
            sr_addr[0].associations.append(
                {"gt_entity_id": jr.gt_entity_id, "valid_from": "2021-01-01", "valid_to": None})
        sr.hard_case_tags.append("jr_sr")
        jr.hard_case_tags.append("jr_sr")

    # phoenix shop: new name + new TIN, inherits address and phone
    if len(shps) >= 2:
        old, new = shps[0], shps[-1]
        for kind in ("address", "phone"):
            src = ids_of(old, kind)
            if src:
                new.identifiers = [i for i in new.identifiers
                                   if ident_by_id[i].kind != kind] + [src[0].gt_identifier_id]
                src[0].associations.append(
                    {"gt_entity_id": new.gt_entity_id, "valid_from": "2024-06-01", "valid_to": None})
        old.hard_case_tags.append("phoenix_shop")
        new.hard_case_tags.append("phoenix_shop")

    # shared building address across unrelated providers
    if len(prvs) >= 3:
        a, b = prvs[0], prvs[1]
        src = ids_of(a, "address")
        if src:
            b.identifiers = [i for i in b.identifiers
                             if ident_by_id[i].kind != "address"] + [src[0].gt_identifier_id]
            src[0].associations.append(
                {"gt_entity_id": b.gt_entity_id, "valid_from": "2022-03-01", "valid_to": None})
        a.hard_case_tags.append("shared_address")
        b.hard_case_tags.append("shared_address")

    # recycled phone: number closes for a provider and reopens for a claimant
    if prvs and clms:
        prov, clm = prvs[-1], clms[-1]
        src = ids_of(prov, "phone")
        if src:
            src[0].associations[0]["valid_to"] = "2024-12-31"
            src[0].associations.append(
                {"gt_entity_id": clm.gt_entity_id, "valid_from": "2025-02-01", "valid_to": None})
            clm.identifiers.append(src[0].gt_identifier_id)
            prov.hard_case_tags.append("recycled_phone")
            clm.hard_case_tags.append("recycled_phone")

    # attorney relocation: address window closes, a new one opens
    for e in atts[:3]:
        src = ids_of(e, "address")
        if src:
            src[0].associations[0]["valid_to"] = "2025-06-30"
            gi = new_ident("address", _gen_address(rng), e.gt_entity_id, "2025-07-01", None)
            e.identifiers.append(gi.gt_identifier_id)
            e.hard_case_tags.append("address_change")


# ---------------------------------------------------------------------------
# Hierarchy + roster assignment
# ---------------------------------------------------------------------------
def _allocate_slots(pool: list, total_slots: int, alpha: float,
                    max_share: float, rng: _Rng) -> list:
    """Deal `total_slots` appearances across `pool` on a capped Zipf shape.

    Sampling directly from Zipf weights lets the top rank run away (rank 0 took
    23% of all claims in an earlier build). Allocating explicit per-entity counts
    and capping each at `max_share` keeps the head plausible while preserving the
    long tail that makes hub handling worth testing. Returns a shuffled bag of
    entity references to deal out.
    """
    n = len(pool)
    if n == 0 or total_slots <= 0:
        return []
    w = _powerlaw_weights(n, alpha)
    s = sum(w)
    cap = max(1, int(total_slots * max_share))
    counts = [min(cap, max(1, round(total_slots * wi / s))) for wi in w]
    bag = []
    for ent, c in zip(pool, counts):
        bag.extend([ent] * c)
    # top up / trim to the requested number of slots
    while len(bag) < total_slots:
        bag.append(pool[rng.intr(0, n - 1)])
    rng.shuffle(bag)
    return bag[:total_slots]


def _allocate_claimants(pool: list, n_claims: int, rng: _Rng) -> list:
    """Most claimants appear exactly once; a minority recur on 2-4 claims."""
    bag = list(pool)
    rng.shuffle(bag)
    bag = bag[:n_claims]
    n_repeat = int(len(bag) * CFG.CLAIMANT_REPEAT_SHARE)
    for ent in rng.sample(bag, n_repeat):
        extra = rng.intr(1, CFG.CLAIMANT_MAX_CLAIMS - 1)
        bag.extend([ent] * extra)
    while len(bag) < n_claims:
        bag.append(pool[rng.intr(0, len(pool) - 1)])
    rng.shuffle(bag)
    return bag[:n_claims]


def build_hierarchy(ents, rng: _Rng):
    """occurrence -> claims -> roster, with capped power-law entity recurrence."""
    by_class: dict[str, list[GTEntity]] = {}
    for e in ents:
        by_class.setdefault(e.klass, []).append(e)
    for k in by_class:
        rng.shuffle(by_class[k])

    # Provision the whole corpus up-front so recurrence has a controlled shape.
    n_claims_est = expected_claims()
    ms = CFG.FANOUT_MAX_SHARE
    bags = {
        "attorney": _allocate_slots(by_class.get("attorney", []),
                                    int(n_claims_est * 1.4), CFG.FANOUT_ALPHA["attorney"], ms, rng),
        "medical_provider": _allocate_slots(by_class.get("medical_provider", []),
                                            int(n_claims_est * 2.2),
                                            CFG.FANOUT_ALPHA["medical_provider"], ms, rng),
        "repair_shop": _allocate_slots(by_class.get("repair_shop", []),
                                       int(n_claims_est * 1.1),
                                       CFG.FANOUT_ALPHA["repair_shop"], ms, rng),
        "adjuster": _allocate_slots(by_class.get("adjuster", []),
                                    int(n_claims_est * 1.2),
                                    CFG.FANOUT_ALPHA["adjuster"], ms, rng),
    }
    cursors = {k: 0 for k in bags}

    def draw(klass, n=1):
        """Deal the next n distinct entities from the pre-allocated bag.

        Wraps around rather than falling back to a uniform random pick: a random
        fallback silently breaks the FANOUT_MAX_SHARE cap once a bag drains.
        """
        bag = bags.get(klass, [])
        if not bag:
            return []
        out, seen = [], set()
        for _ in range(min(len(bag), n * 4)):
            cand = bag[cursors[klass] % len(bag)]
            cursors[klass] += 1
            if cand.gt_entity_id not in seen:
                seen.add(cand.gt_entity_id)
                out.append(cand)
            if len(out) >= n:
                break
        return out

    occurrences, claims = [], {}
    claim_n = 0
    claimant_pool = by_class.get("claimant", [])
    claimant_bag = _allocate_claimants(claimant_pool, n_claims_est, rng)
    claimant_cursor = 0

    for o in range(CFG.N_OCCURRENCES):
        occ_id = f"OCC{o:04d}"
        n_cl = int(rng.weighted(CFG.CLAIMS_PER_OCCURRENCE_WEIGHTS))
        occ_claims = []
        occ_type = rng.pick(OCCURRENCE_TYPES)
        occ_date = _gen_date(rng)
        # parties to the same occurrence often share the shop and adjuster
        shared_shop = draw("repair_shop", 1)
        shared_adj = draw("adjuster", 1)
        for _c in range(n_cl):
            claim_id = f"CLM{claim_n:04d}"
            claim_n += 1
            if claimant_cursor < len(claimant_bag):
                clm = claimant_bag[claimant_cursor]
                claimant_cursor += 1
            else:
                clm = rng.pick(claimant_pool)

            roster = {"claimant": [clm]}
            # multi-role: a person who is a claimant elsewhere appears here as a
            # witness, which is a genuine cross-claim identity case
            if rng.chance(0.13):
                w = rng.pick(claimant_pool)
                if w.gt_entity_id != clm.gt_entity_id:
                    roster["witness"] = [w]
            if rng.chance(0.78):
                roster["attorney"] = draw("attorney", 1)
            if rng.chance(0.22):
                roster.setdefault("attorney", [])
                roster["attorney"] = (roster["attorney"] + draw("attorney", 1))[:2]
            provs = draw("medical_provider", rng.intr(0, 3))
            if provs:
                roster["medical_provider"] = provs
            if shared_shop and rng.chance(0.55):
                roster["repair_shop"] = shared_shop
            elif rng.chance(0.2):
                roster["repair_shop"] = draw("repair_shop", 1)
            roster["adjuster"] = shared_adj or draw("adjuster", 1)

            for cls, members in roster.items():
                for m in members:
                    m.claims.add(claim_id)
                    m.occurrences.add(occ_id)
                    m.roles_per_claim.setdefault(claim_id, cls)

            claims[claim_id] = {"occurrence_id": occ_id, "roster": roster,
                                "occ_type": occ_type, "occ_date": occ_date}
            occ_claims.append(claim_id)

        occurrences.append({"occurrence_id": occ_id, "claim_ids": occ_claims,
                            "type": occ_type, "date": occ_date})

    for e in ents:
        if len(e.claims) > 3:
            e.hard_case_tags.append("high_fanout")
        if len(e.occurrences) > 1:
            e.hard_case_tags.append("cross_occurrence")
    return occurrences, claims


def build_events_and_relations(claims, rng: _Rng):
    events, relations = [], []
    n_ev = 0
    for claim_id, meta in claims.items():
        roster = meta["roster"]
        clm = roster["claimant"][0]
        atts = roster.get("attorney", [])
        provs = roster.get("medical_provider", [])
        shops = roster.get("repair_shop", [])
        adjs = roster.get("adjuster", [])

        # ---- open-vocabulary relationships ----
        for a in atts:
            relations.append(GTRelationship(a.gt_entity_id, "represents", clm.gt_entity_id, claim_id))
            if a.firm:
                relations.append(GTRelationship(a.gt_entity_id, "employed_by", a.firm, claim_id))
        for p in provs:
            relations.append(GTRelationship(p.gt_entity_id, "treats", clm.gt_entity_id, claim_id))
        for s in shops:
            relations.append(GTRelationship(s.gt_entity_id, "repairs", clm.gt_entity_id, claim_id))
        for d in adjs:
            relations.append(GTRelationship(d.gt_entity_id, "adjusts", clm.gt_entity_id, claim_id))
        if len(atts) >= 2:
            relations.append(GTRelationship(atts[0].gt_entity_id, "co_counsel",
                                            atts[1].gt_entity_id, claim_id))
        if provs and atts and rng.chance(0.3):
            relations.append(GTRelationship(atts[0].gt_entity_id, "referred",
                                            provs[0].gt_entity_id, claim_id))
        if len(provs) >= 2 and rng.chance(0.25):
            relations.append(GTRelationship(provs[0].gt_entity_id, "referred",
                                            provs[1].gt_entity_id, claim_id))
        if shops and rng.chance(0.15):
            relations.append(GTRelationship(shops[0].gt_entity_id, "subcontracts_to",
                                            "unnamed sublet shop", claim_id))
        # relations a closed four-verb schema would drop or force-fit
        for w in roster.get("witness", []):
            relations.append(GTRelationship(w.gt_entity_id, "witnessed",
                                            meta["occ_type"], claim_id))
        if len(adjs) >= 1 and rng.chance(0.18):
            relations.append(GTRelationship(adjs[0].gt_entity_id, "supervises",
                                            clm.gt_entity_id, claim_id))
        if len(atts) >= 1 and rng.chance(0.22):
            relations.append(GTRelationship(atts[0].gt_entity_id, "opposing_counsel",
                                            "carrier counsel", claim_id))
        if provs and rng.chance(0.35):
            relations.append(GTRelationship(provs[0].gt_entity_id, "billed",
                                            clm.gt_entity_id, claim_id))
        if provs and rng.chance(0.3):
            relations.append(GTRelationship(provs[-1].gt_entity_id, "examined",
                                            clm.gt_entity_id, claim_id))
        if roster.get("witness") and rng.chance(0.25):
            relations.append(GTRelationship(roster["witness"][0].gt_entity_id,
                                            "related_to", clm.gt_entity_id, claim_id))

        # ---- events ----
        for _ in range(rng.intr(*CFG.EVENTS_PER_CLAIM)):
            etype = rng.pick(CFG.EVENT_TYPES)
            actor = None
            if etype in ("motion_filed", "demand_sent", "suit_filed", "deposition_taken"):
                actor = atts[0] if atts else adjs[0] if adjs else clm
            elif etype in ("ime_performed", "procedure_performed", "records_produced", "examined"):
                actor = provs[0] if provs else clm
            elif etype in ("estimate_written", "inspection_completed"):
                actor = shops[0] if shops else adjs[0] if adjs else clm
            else:
                actor = adjs[0] if adjs else clm
            ev = GTEvent(f"gt_ev_{n_ev:05d}", etype, _gen_date(rng), claim_id,
                         [{"gt_entity_id": actor.gt_entity_id, "role": "actor"},
                          {"gt_entity_id": clm.gt_entity_id, "role": "subject"}])
            events.append(ev)
            n_ev += 1
    return events, relations


# ---------------------------------------------------------------------------
# Prose generation
# ---------------------------------------------------------------------------
PRONOUN_BY_CLASS = {
    "claimant": ["he", "she", "they"], "attorney": ["he", "she", "they"],
    "adjuster": ["he", "she", "they"], "medical_provider": ["he", "she", "they"],
    "repair_shop": ["they", "it"],
}
POSSESSIVE = {"he": "his", "she": "her", "they": "their", "it": "its"}
DESCRIPTOR_BY_CLASS = {
    "claimant": ["the claimant", "the insured", "the clmt"],
    "attorney": ["the attorney", "counsel", "the atty"],
    "medical_provider": ["the physician", "the provider", "the treating facility"],
    "repair_shop": ["the shop", "the facility"],
    "adjuster": ["the adjuster", "the examiner"],
}

FILLER = [
    "Diary set for 14 days pending further documentation.",
    "No change to exposure at this time.",
    "Reserves reviewed and remain adequate based on current information.",
    "Will continue to monitor and update the file as records arrive.",
    "Awaiting return call; left voicemail on the listed contact number.",
    "File reviewed with supervisor; plan of action approved as written.",
    "Nothing further pending on this segment of the claim.",
    "Documentation requested has not yet been received.",
    "Follow-up scheduled consistent with the current plan of action.",
    "Coverage position remains unchanged pending completion of the review.",
    "Note entered to memorialize the discussion for the file record.",
]

EVENT_PHRASING = {
    "motion_filed": ["filed a motion", "filed motion to compel", "submitted a motion"],
    "deposition_taken": ["took the deposition", "conducted deposition"],
    "demand_sent": ["sent a demand package", "forwarded the demand"],
    "suit_filed": ["filed suit", "commenced litigation"],
    "ime_performed": ["performed the IME", "completed the independent exam"],
    "procedure_performed": ["performed the procedure", "completed the surgical procedure"],
    "records_produced": ["produced treatment records", "released the records"],
    "payment_issued": ["issued payment", "released indemnity payment"],
    "reserve_set": ["set the reserve", "adjusted the reserve"],
    "estimate_written": ["wrote the estimate", "prepared a repair estimate"],
    "siu_referral": ["referred the file to SIU", "submitted an SIU referral"],
    "coverage_denied": ["denied coverage", "issued a coverage denial"],
    "settlement_reached": ["reached settlement", "finalized settlement terms"],
    "inspection_completed": ["completed the inspection", "finished the vehicle inspection"],
}


class _Composer:
    """Emits realistic adjuster prose into a NoteBuilder, planting ground truth."""

    def __init__(self, nb: NoteBuilder, rng: _Rng, roster: dict, ident_by_id: dict,
                 claim_events: list, meta: dict):
        self.nb, self.rng, self.roster = nb, rng, roster
        self.ident_by_id = ident_by_id
        self.events = list(claim_events)
        self.meta = meta
        self.chains_left = rng.intr(*CFG.COREF_CHAINS_PER_NOTE)

    # -- helpers -----------------------------------------------------------
    def _ent(self, cls, idx=0):
        got = self.roster.get(cls, [])
        return got[idx] if len(got) > idx else None

    def _name(self, ent, prefer_canonical=False):
        variants = name_variants(ent, self.rng)
        if prefer_canonical or self.rng.chance(0.55):
            kind = "canonical"
        else:
            kind = self.rng.pick([k for k in variants if k != "canonical"])
        self.nb.add_entity(variants[kind], ent, kind)

    def _ident_of(self, ent, kind):
        for i in ent.identifiers:
            gi = self.ident_by_id[i]
            if gi.kind == kind:
                return gi
        return None

    def _anaphor(self, ent, capitalize=False):
        """Emit a pronoun or descriptor for `ent`; returns True if emitted.

        `capitalize` is applied to the surface BEFORE planting so the recorded
        ground-truth surface matches the characters actually written.
        """
        if self.chains_left <= 0:
            return False
        if self.rng.chance(CFG.COREF_DESCRIPTOR_RATIO):
            surface = self.rng.pick(DESCRIPTOR_BY_CLASS.get(ent.klass, ["the party"]))
            kind = "descriptor"
        else:
            surface = self.rng.pick(PRONOUN_BY_CLASS.get(ent.klass, ["they"]))
            kind = "pronoun"
        if capitalize:
            surface = surface[0].upper() + surface[1:]
        res = self.nb.add_anaphor(surface, ent, kind)
        if res:
            self.chains_left -= 1
            return True
        return False

    def _sentence_with_anaphor(self, ent, tail_options):
        """'<Anaphor> <tail>.' — only if an antecedent name exists in the note."""
        start_len = self.nb.n
        if not self._anaphor(ent, capitalize=True):
            return False
        self.nb.add(" " + self.rng.pick(tail_options) + ". ")
        return self.nb.n > start_len

    # -- paragraph kinds ---------------------------------------------------
    def para_contact(self):
        nb, rng = self.nb, self.rng
        clm = self._ent("claimant")
        nb.segment("narrative")
        nb.add("Contacted ")
        self._name(clm)
        nb.add(" to discuss the reported ")
        nb.add(self.meta["occ_type"])
        nb.add(" and confirm the details on file. ")
        ph = self._ident_of(clm, "phone")
        if ph:
            nb.add("Reached at ")
            nb.add_identifier(ph)
            nb.add(". ")
        self._sentence_with_anaphor(clm, [
            "confirmed the account given at first notice",
            "reiterated that the vehicle was stopped at the time of impact",
            "described ongoing discomfort in the lower back",
            "advised that treatment is continuing on a weekly basis",
        ])
        addr = self._ident_of(clm, "address")
        if addr and rng.chance(0.55):
            nb.add("Mailing address confirmed as ")
            nb.add_identifier(addr)
            nb.add(". ")
        self._sentence_with_anaphor(clm, [
            "also asked about the status of the property damage portion",
            "requested a copy of the estimate for review",
            "will follow up with the treating office directly",
        ])
        nb.add(rng.pick(FILLER) + " ")

    def para_medical(self):
        nb, rng = self.nb, self.rng
        prov = self._ent("medical_provider")
        clm = self._ent("claimant")
        if not prov:
            return self.para_status()
        nb.segment("narrative")
        nb.add("Treatment update: ")
        self._name(prov)
        nb.add(" continues to manage care for ")
        self._name(clm)
        nb.add(". ")
        npi = self._ident_of(prov, "npi")
        if npi and rng.chance(0.6):
            nb.add("Provider NPI on file is ")
            nb.add_identifier(npi)
            nb.add(". ")
        self._sentence_with_anaphor(prov, [
            "reports steady improvement over the last four weeks",
            "recommends continued conservative treatment",
            "has not yet released the full records requested",
            "indicated that imaging was unremarkable",
        ])
        ev = self._pop_event(("ime_performed", "procedure_performed", "records_produced", "examined"))
        if ev:
            nb.add("On ")
            nb.add(ev.date)
            nb.add(" the office ")
            nb.add_event(rng.pick(EVENT_PHRASING.get(ev.etype, ["completed the action"])), ev)
            nb.add(". ")
        addr = self._ident_of(prov, "address")
        if addr and rng.chance(0.5):
            nb.add("Billing submitted from ")
            nb.add_identifier(addr)
            nb.add(". ")
        self._sentence_with_anaphor(prov, [
            "will forward the narrative report once finalized",
            "confirmed the next appointment is already scheduled",
        ])
        nb.add(rng.pick(FILLER) + " ")

    def para_legal(self):
        nb, rng = self.nb, self.rng
        att = self._ent("attorney")
        clm = self._ent("claimant")
        if not att:
            return self.para_status()
        nb.segment("narrative")
        nb.add("Spoke with ")
        self._name(att)
        nb.add(" of ")
        nb.add(att.firm or "counsel's office")
        nb.add(" regarding representation of ")
        self._name(clm)
        nb.add(". ")
        em = self._ident_of(att, "email")
        if em and rng.chance(0.6):
            nb.add("Correspondence to be directed to ")
            nb.add_identifier(em)
            nb.add(". ")
        ev = self._pop_event(("motion_filed", "demand_sent", "suit_filed", "deposition_taken"))
        if ev:
            nb.add("Counsel ")
            nb.add_event(rng.pick(EVENT_PHRASING.get(ev.etype, ["took action"])), ev)
            nb.add(" on ")
            nb.add(ev.date)
            nb.add(". ")
        self._sentence_with_anaphor(att, [
            "requested a copy of the policy declarations page",
            "advised that the client is not yet at maximum medical improvement",
            "will circulate a settlement demand once treatment concludes",
            "disputed the characterization of liability in the report",
        ])
        att2 = self._ent("attorney", 1)
        if att2:
            nb.add("Co-counsel ")
            self._name(att2)
            nb.add(" is also appearing on this matter. ")
        nb.add(rng.pick(FILLER) + " ")

    def para_repair(self):
        nb, rng = self.nb, self.rng
        shop = self._ent("repair_shop")
        if not shop:
            return self.para_status()
        nb.segment("narrative")
        nb.add("Property damage: vehicle currently at ")
        self._name(shop)
        nb.add(". ")
        tin = self._ident_of(shop, "tin")
        if tin and rng.chance(0.55):
            nb.add("Shop TIN ")
            nb.add_identifier(tin)
            nb.add(" verified against the vendor file. ")
        # VIN: same defect as SSN -- 140 were generated onto claimants and never
        # written down. The repair paragraph is where a VIN belongs, and it is
        # the identifier that legitimately joins a claimant, a vehicle and a
        # shop, so its absence removed a whole class of cross-entity link from
        # the fixture.
        clm_v = self._ent("claimant")
        vin = self._ident_of(clm_v, "vin") if clm_v else None
        if vin and rng.chance(0.6):
            nb.add(rng.pick([
                "Vehicle VIN ", "Unit VIN ", "VIN on the estimate reads ",
            ]))
            nb.add_identifier(vin)
            nb.add(rng.pick([". ", " per the estimate of record. ",
                             ", matches the policy vehicle schedule. "]))
        ev = self._pop_event(("estimate_written", "inspection_completed"))
        if ev:
            nb.add("The shop ")
            nb.add_event(rng.pick(EVENT_PHRASING.get(ev.etype, ["completed work"])), ev)
            nb.add(" on ")
            nb.add(ev.date)
            nb.add(". ")
        self._sentence_with_anaphor(shop, [
            "is waiting on a back-ordered part before completing the repair",
            "submitted a supplement for additional labor hours",
            "has not returned the signed authorization",
        ])
        if rng.chance(0.28):
            nb.add("Adjuster notes the parts pricing appears inflated relative to comparable shops in the area; ")
            nb.add("flagging for review rather than treating as established. ")
        nb.add(rng.pick(FILLER) + " ")

    def para_siu(self):
        nb, rng = self.nb, self.rng
        clm = self._ent("claimant")
        nb.segment("narrative")
        nb.add("Investigation notes: reviewed the reported sequence of the ")
        nb.add(self.meta["occ_type"])
        nb.add(" against the recorded statement. ")
        # SSN: previously generated onto the entity and never written into any
        # note, so 125 declared SSNs appeared in zero of 2,000 documents and the
        # SSN lane could not be exercised at all. An SIU/identity-verification
        # paragraph is where it plausibly appears in a real claim file.
        ssn = self._ident_of(clm, "ssn") if clm else None
        if ssn and rng.chance(0.6):
            nb.add(rng.pick([
                "Identity verified against the file of record, SSN ",
                "Claimant identity confirmed; SSN on file ",
                "Ran the identity check under SSN ",
            ]))
            nb.add_identifier(ssn)
            nb.add(". ")
        if rng.chance(0.5):
            nb.add("There is a suspected inconsistency between the described point of impact and the documented damage pattern. ")
        ev = self._pop_event(("siu_referral", "coverage_denied"))
        if ev:
            nb.add("File ")
            nb.add_event(rng.pick(EVENT_PHRASING.get(ev.etype, ["was escalated"])), ev)
            nb.add(" on ")
            nb.add(ev.date)
            nb.add(". ")
        self._sentence_with_anaphor(clm, [
            "denies any prior injury to the same body part",
            "was unable to recall the name of the responding officer",
            "provided a second account that differs on the sequence of events",
        ])
        nb.add(rng.pick(FILLER) + " ")

    def para_payment(self):
        nb, rng = self.nb, self.rng
        nb.segment("narrative")
        ev = self._pop_event(("payment_issued", "reserve_set", "settlement_reached"))
        nb.add("Financial: ")
        if ev:
            nb.add("carrier ")
            nb.add_event(rng.pick(EVENT_PHRASING.get(ev.etype, ["processed the transaction"])), ev)
            nb.add(" on ")
            nb.add(ev.date)
            nb.add(f" in the amount of ${rng.intr(1,48)},{rng.intr(100,999)}.00. ")
        else:
            nb.add(f"indemnity reserve currently set at ${rng.intr(5,60)},000.00. ")
        nb.add("Expense reserve reviewed in the same pass. ")
        nb.add(rng.pick(FILLER) + " ")

    def para_status(self):
        nb, rng = self.nb, self.rng
        nb.segment("narrative")
        nb.add("Status: ")
        nb.add(rng.pick([
            "file remains in active handling pending receipt of outstanding documentation. ",
            "no material change since the prior entry; plan of action unchanged. ",
            "awaiting confirmation from the opposing carrier on liability position. ",
            "coverage confirmed under the applicable policy period. ",
        ]))
        nb.add(rng.pick(FILLER) + " ")
        nb.add(rng.pick(FILLER) + " ")

    def para_orphan_identifier(self):
        """An identifier mention with NO name attached — resolvable only via the id."""
        nb, rng = self.nb, self.rng
        candidates = []
        for cls in ("medical_provider", "repair_shop", "attorney", "claimant"):
            for ent in self.roster.get(cls, []):
                for kind in ("phone", "address", "email"):
                    gi = self._ident_of(ent, kind)
                    if gi:
                        candidates.append(gi)
        if not candidates:
            return self.para_status()
        gi = rng.pick(candidates)
        nb.segment("narrative")
        nb.add(rng.pick([
            "Callback left at ",
            "Return call placed to ",
            "Correspondence returned undeliverable from ",
            "Message received from ",
        ]))
        nb.add_identifier(gi, orphan=True)
        nb.add(rng.pick([
            "; caller did not identify themselves on the message. ",
            "; no name given on the outgoing greeting. ",
            "; unable to determine which party this belongs to from the note alone. ",
        ]))
        nb.add(rng.pick(FILLER) + " ")

    def _pop_event(self, types):
        for i, ev in enumerate(self.events):
            if ev.etype in types:
                return self.events.pop(i)
        return None

    # -- email block -------------------------------------------------------
    def email_block(self):
        nb, rng = self.nb, self.rng
        att = self._ent("attorney")
        adj = self._ent("adjuster")
        if not (att and adj):
            return self.para_status()
        sender, recip = (att, adj) if rng.chance(0.6) else (adj, att)

        def header(frm, to):
            nb.segment("email_header")
            nb.add("\n\nFrom: ")
            self._name(frm, prefer_canonical=True)
            em = self._ident_of(frm, "email")
            if em:
                nb.add(" <")
                nb.add_identifier(em)
                nb.add(">")
            nb.add("\nSent: ")
            nb.add(f"{rng.pick(['Mon','Tue','Wed','Thu','Fri'])}, "
                   f"{rng.pick(['Jan','Feb','Mar','Apr','May','Jun'])} {rng.intr(1,28)}, 2026 "
                   f"{rng.intr(1,12)}:{rng.intr(10,59)} {rng.pick(['AM','PM'])}")
            nb.add("\nTo: ")
            self._name(to, prefer_canonical=True)
            nb.add(f"\nSubject: RE: Claim {nb.claim_id} - status\n\n")

        header(sender, recip)
        nb.segment("email_body")
        body = rng.pick([
            "Following up on the outstanding records request. Please advise on the current plan of action.",
            "Per our call, attaching the updated demand package. Client is available for a call next week.",
            "We have not received the itemized billing yet. Kindly expedite so we can complete the review.",
        ])
        nb.add(body + " ")
        self._sentence_with_anaphor(sender, [
            "also asked whether the file has been assigned to counsel",
            "noted that the prior correspondence went unanswered",
        ])
        nb.add("&nbsp; <br>\n")

        nb.segment("email_signature")
        nb.add("\n--\n")
        self._name(sender, prefer_canonical=True)
        nb.add("\n" + (sender.firm or "Claims Department") + "\n")
        ph = self._ident_of(sender, "phone")
        if ph:
            nb.add("Direct: ")
            nb.add_identifier(ph)
            nb.add("\n")
        ad = self._ident_of(sender, "address")
        if ad:
            nb.add_identifier(ad)
            nb.add("\n")

        nb.segment("boilerplate")
        nb.add_placeholder("\n" + DISCLAIMER, kind="boilerplate")

        # quoted reply chain re-plants the mentions inside quotes
        for q in range(rng.intr(1, 3)):
            nb.segment("email_quoted", quoted=True)
            pre = ">" * (q + 1)
            nb.add(f"\n{pre} From: ")
            self._name(recip, prefer_canonical=True)
            nb.add(f"\n{pre} Sent: earlier\n{pre} To: ")
            self._name(sender, prefer_canonical=True)
            nb.add(f"\n{pre} {body}\n")

    # -- structured header -------------------------------------------------
    def template_block(self, full: bool):
        nb, rng = self.nb, self.rng
        nb.segment("template_block")
        labels = {
            "claimant": rng.pick(["Claimant Name:", "Clmt name -", "CLAIMANT_NM=", "Claimant:"]),
            "atty": rng.pick(["Attorney:", "Clmt Atty -", "ATTY_NAME=", "Counsel:"]),
            "prov": rng.pick(["Provider:", "Treating Physician -", "PROVIDER=", "Dr:"]),
            "phone": rng.pick(["Phone:", "Ph -", "TEL=", "Contact #:"]),
            "dob": rng.pick(["DOB:", "D.O.B -", "BIRTHDATE="]),
            "addr": rng.pick(["Address:", "Addr -", "ADDR=", "Mailing Address:"]),
        }
        clm = self._ent("claimant")
        nb.add(f"Claim: {nb.claim_id}   Occurrence: {nb.occurrence_id}\n")
        nb.add(f"{labels['claimant']} ")
        self._name(clm)
        nb.add("\n")
        nb.add(f"{labels['dob']} ")
        nb.add(clm.dob if rng.chance(0.7) else "")
        if not clm.dob or rng.chance(0.3):
            nb.add_placeholder(rng.pick(PLACEHOLDERS))
        nb.add("\n")
        ph = self._ident_of(clm, "phone")
        nb.add(f"{labels['phone']} ")
        if ph and rng.chance(0.8):
            nb.add_identifier(ph)
        else:
            nb.add_placeholder("same as above")
        nb.add("\n")
        if full:
            att = self._ent("attorney")
            if att:
                nb.add(f"{labels['atty']} ")
                self._name(att)
                nb.add(f"  ({att.firm})\n")
            prov = self._ent("medical_provider")
            if prov:
                nb.add(f"{labels['prov']} ")
                self._name(prov)
                nb.add("\n")
                npi = self._ident_of(prov, "npi")
                if npi:
                    nb.add("NPI: ")
                    nb.add_identifier(npi)
                    nb.add("\n")
            ad = self._ident_of(clm, "address")
            if ad:
                nb.add(f"{labels['addr']} ")
                nb.add_identifier(ad)
                nb.add("\n")
        nb.add("\n")


# ---------------------------------------------------------------------------
# Note assembly
# ---------------------------------------------------------------------------
def _compose_note(nb: NoteBuilder, rng: _Rng, roster, ident_by_id, claim_events, meta):
    """Build one note to the configured word length."""
    comp = _Composer(nb, rng, roster, ident_by_id, claim_events, meta)
    form = rng.weighted(CFG.NOTE_FORM_WEIGHTS)
    target = rng.intr(CFG.NOTE_WORDS_MIN, CFG.NOTE_WORDS_MAX)

    if form in ("mixed", "template_heavy"):
        comp.template_block(full=(form == "template_heavy"))

    paras = [comp.para_contact, comp.para_medical, comp.para_legal,
             comp.para_repair, comp.para_siu, comp.para_payment]
    rng.shuffle(paras)
    if rng.chance(CFG.ORPHAN_PARAGRAPH_CHANCE):
        paras.insert(rng.intr(0, len(paras) - 1), comp.para_orphan_identifier)

    email_emitted = False
    i = 0
    guard = 0
    while nb.words() < target and guard < 40:
        guard += 1
        if form == "narrative_email" and not email_emitted and nb.words() > target * 0.45:
            comp.email_block()
            email_emitted = True
            continue
        fn = paras[i % len(paras)]
        i += 1
        nb.segment("narrative")
        nb.add("\n\n")
        fn()
    if form == "narrative_email" and not email_emitted:
        comp.email_block()
    return form


def generate_corpus(seed: int | None = None) -> dict:
    """Generate corpus v2 + the sealed manifest. Deterministic for a given seed."""
    seed = CFG.SEED if seed is None else seed
    rng = _Rng(seed)
    Paths.ensure()

    for f in Paths.raw_notes.glob("*.txt"):
        f.unlink()

    ents, idents = build_population(rng)
    ident_by_id = {i.gt_identifier_id: i for i in idents}
    occurrences, claims = build_hierarchy(ents, rng)
    events, relations = build_events_and_relations(claims, rng)

    events_by_claim: dict[str, list] = {}
    for ev in events:
        events_by_claim.setdefault(ev.claim_id, []).append(ev)

    # distribute the note budget across claims
    claim_ids = list(claims)
    per_claim = {}
    remaining = CFG.TARGET_NOTES
    for cid in claim_ids:
        n = rng.intr(CFG.NOTES_PER_CLAIM_MIN, CFG.NOTES_PER_CLAIM_MAX)
        per_claim[cid] = n
        remaining -= n
    while remaining > 0:
        per_claim[rng.pick(claim_ids)] += 1
        remaining -= 1
    while remaining < 0:
        cid = rng.pick(claim_ids)
        if per_claim[cid] > 1:
            per_claim[cid] -= 1
            remaining += 1

    all_placements, all_non_entities, all_chains, doc_rows = [], [], [], []
    doc_n = 0
    for cid in claim_ids:
        meta = claims[cid]
        roster = meta["roster"]
        for s in range(per_claim[cid]):
            doc_id = f"DOC{doc_n:05d}"
            doc_n += 1
            nb = NoteBuilder(doc_id, cid, meta["occurrence_id"], rng=rng)
            form = _compose_note(nb, rng, roster, ident_by_id,
                                 events_by_claim.get(cid, []), meta)
            text = nb.text()
            (Paths.raw_notes / f"{doc_id}.txt").write_text(text, encoding="utf-8")
            doc_rows.append({
                "doc_id": doc_id, "claim_id": cid,
                "occurrence_id": meta["occurrence_id"], "form": form,
                "n_chars": len(text), "n_words": len(text.split()), "seq_in_claim": s,
            })
            all_placements.extend(nb.placements)
            all_non_entities.extend(nb.non_entities)
            all_chains.extend(nb.coref_chains)

    manifest = {
        "schema_version": CFG.MANIFEST_SCHEMA_VERSION,
        "seed": seed,
        "occurrences": occurrences,
        "claims": {cid: {"occurrence_id": m["occurrence_id"],
                         "roster": {k: [e.gt_entity_id for e in v] for k, v in m["roster"].items()}}
                   for cid, m in claims.items()},
        "documents": doc_rows,
        "entities": [_entity_manifest(e) for e in ents],
        "identifiers": [{"gt_identifier_id": i.gt_identifier_id, "kind": i.kind,
                         "value": i.value, "associations": i.associations} for i in idents],
        "events": [{"gt_event_id": e.gt_event_id, "type": e.etype, "date": e.date,
                    "claim_id": e.claim_id, "participants": e.participants} for e in events],
        "relationships": [{"subject": r.subject, "predicate": r.predicate,
                           "object": r.obj, "claim_id": r.claim_id} for r in relations],
        "placements": all_placements,
        "coref_chains": all_chains,
        "non_entities": all_non_entities,
    }
    Paths.manifest_json.parent.mkdir(parents=True, exist_ok=True)
    Paths.manifest_json.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    # Structural document metadata: which claim/occurrence each note belongs to.
    # This is NOT ground truth and NOT subject to the leakage guard -- every real
    # claim system knows which file a note was written on. Only ENTITY identity
    # must be inferred. Without it, ~70% of narrative notes (which never state a
    # claim number in prose) would be unattributable to a claim at all.
    doc_index = {d["doc_id"]: {"claim_id": d["claim_id"],
                               "occurrence_id": d["occurrence_id"]}
                 for d in doc_rows}
    (Paths.data / "doc_index.json").write_text(json.dumps(doc_index, indent=1), encoding="utf-8")

    words = [d["n_words"] for d in doc_rows]
    kinds = {}
    for p in all_placements:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    return {
        "schema_version": CFG.MANIFEST_SCHEMA_VERSION, "seed": seed,
        "n_occurrences": len(occurrences), "n_claims": len(claims),
        "n_docs": len(doc_rows),
        "words_mean": round(sum(words) / max(1, len(words)), 1),
        "words_min": min(words), "words_max": max(words),
        "n_entities": len(ents), "n_identifiers": len(idents),
        "n_events": len(events), "n_relationships": len(relations),
        "placements_by_kind": kinds,
        "n_coref_chains": len(all_chains),
        "n_non_entities": len(all_non_entities),
    }


def _entity_manifest(e: GTEntity) -> dict:
    canonical = {"name": e.display_name(), "dob": e.dob, "firm": e.firm}
    return {
        "gt_entity_id": e.gt_entity_id,
        "class": e.klass,
        "canonical": {k: v for k, v in canonical.items() if v},
        "identifiers": e.identifiers,
        "claims": sorted(e.claims),
        "occurrences": sorted(e.occurrences),
        "roles_per_claim": e.roles_per_claim,
        "hard_case_tags": sorted(set(e.hard_case_tags)),
    }


__all__ = ["generate_corpus", "GTEntity", "GTIdentifier", "GTEvent", "NoteBuilder"]
