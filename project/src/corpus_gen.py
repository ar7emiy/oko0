"""Deterministic synthetic corpus generator + sealed ground-truth manifest.

WHY DETERMINISTIC (not LLM-authored text): the ground-truth manifest must record
the EXACT char_start/char_end of every planted mention, written in the same pass
that plants it. An LLM cannot guarantee it placed a surface at a known offset, so
the generator assembles every note from fragments with a byte-accurate text
builder and records each placement as it is emitted. (Gemini may enrich narrative
flavor when online, but planted spans are always deterministically placed --
see DECISIONS.md "Corpus generation".)

This module is one of only two allowed to touch data/ground_truth (it is the
writer). It produces:
  - data/raw_notes/<doc_id>.txt         (immutable after generation)
  - data/ground_truth/manifest.json     (entities, placements, non_entities)
"""
from __future__ import annotations

import json
import random
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
    "Priya", "Wei", "Omar", "Fatima", "Sofia", "Hassan",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Rios", "Nguyen", "Patel", "Kim", "Okafor", "Rossi", "Petrov",
]
LAW_FIRMS = [
    ("XYZ Law Group", "xyzlawgroup.com"),
    ("Harbor & Vance LLP", "harborvance.com"),
    ("Sterling Injury Attorneys", "sterlinginjury.com"),
    ("Delgado Legal Partners", "delgadolegal.com"),
    ("Whitfield Trial Group", "whitfieldtrial.com"),
]
CITIES = [
    ("Springfield", "IL", "627"), ("Riverton", "NJ", "080"),
    ("Fairview", "TX", "750"), ("Lakewood", "CO", "802"),
    ("Ashford", "GA", "301"), ("Bristol", "PA", "190"),
]
STREETS = ["Maple", "Oak", "Cedar", "Elm", "Washington", "Lincoln", "Park",
           "Market", "Highland", "Franklin", "Sunset", "Willow"]
STREET_TYPES = ["St", "Ave", "Blvd", "Rd", "Dr", "Ln", "Ct"]
PROVIDER_SUFFIX = ["Orthopedics", "Physical Therapy", "Imaging Center",
                   "Medical Group", "Chiropractic", "Neurology Associates"]
SHOP_SUFFIX = ["Auto Body", "Collision Center", "Automotive", "Car Care",
               "Body Works", "Repair"]

DISCLAIMER = (
    "CONFIDENTIALITY NOTICE: This email and any attachments are for the sole use "
    "of the intended recipient and may contain privileged information. If you are "
    "not the intended recipient, please notify the sender and delete this message."
)
PLACEHOLDERS = ["xx", "N/A", "TBD", "same as above", "___", "____", "pending", "-"]


@dataclass
class GTEntity:
    gt_entity_id: str
    klass: str
    first: str = ""
    last: str = ""
    suffix: str = ""
    org_name: str = ""
    firm: str = ""
    email: str = ""
    npi: str = ""
    tin: str = ""
    ssn: str = ""
    phone_windows: list = field(default_factory=list)   # [{value, valid_from, valid_to}]
    address_windows: list = field(default_factory=list)  # [{value, valid_from, valid_to}]
    dob: str = ""
    roles_per_claim: dict = field(default_factory=dict)
    hard_case_tags: list = field(default_factory=list)

    def display_name(self) -> str:
        if self.org_name:
            return self.org_name
        n = f"{self.first} {self.last}".strip()
        return f"{n} {self.suffix}".strip() if self.suffix else n

    def current_phone(self) -> str:
        return self.phone_windows[-1]["value"] if self.phone_windows else ""

    def current_address(self) -> str:
        return self.address_windows[-1]["value"] if self.address_windows else ""


class _Rng:
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def pick(self, seq):
        return self.r.choice(seq)

    def chance(self, p):
        return self.r.random() < p

    def intr(self, a, b):
        return self.r.randint(a, b)

    def sample(self, seq, k):
        k = min(k, len(seq))
        return self.r.sample(list(seq), k)


# ---------------------------------------------------------------------------
# Surface-variant machinery
# ---------------------------------------------------------------------------
def _typo(s: str, rng: _Rng) -> str:
    if len(s) < 4:
        return s
    i = rng.intr(1, len(s) - 2)
    if rng.chance(0.5):  # transpose
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    # duplicate a char
    return s[:i] + s[i] + s[i:]


def name_variants(ent: GTEntity, rng: _Rng) -> dict:
    """Return {variant_kind: surface_string} for a person entity."""
    first, last = ent.first, ent.last
    full = ent.display_name()
    out = {"canonical": full}
    if ent.org_name:
        out["flip"] = ent.org_name
        return out
    out["flip"] = f"{last}, {first}" + (f" {ent.suffix}" if ent.suffix else "")
    out["initials"] = f"{first[0]}. {last}"
    # nickname
    grp = textnorm._NICK_INDEX.get(first.lower())
    if grp is not None:
        variants = [v for v in textnorm._NICKNAME_GROUPS[grp] if v != first.lower()]
        if variants:
            nick = rng.pick(sorted(variants)).capitalize()
            out["nickname"] = f"{nick} {last}"
    out["typo"] = _typo(full, rng)
    return out


# ---------------------------------------------------------------------------
# NoteBuilder: byte-accurate assembly + placement recording
# ---------------------------------------------------------------------------
class NoteBuilder:
    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.buf: list[str] = []
        self.n = 0
        self.placements: list[dict] = []
        self.non_entities: list[dict] = []
        self._seg_kind = "narrative"
        self._in_quoted = False

    def segment(self, kind: str, quoted: bool = False):
        self._seg_kind = kind
        self._in_quoted = quoted
        return self

    def add(self, s: str) -> tuple[int, int]:
        start = self.n
        self.buf.append(s)
        self.n += len(s)
        return start, self.n

    def add_entity(self, surface: str, ent: GTEntity, variant: str) -> tuple[int, int]:
        start, end = self.add(surface)
        self.placements.append({
            "gt_entity_id": ent.gt_entity_id,
            "doc_id": self.doc_id,
            "char_start": start,
            "char_end": end,
            "surface_variant": surface,   # the actual surface string emitted
            "variant_kind": variant,      # canonical|flip|nickname|initials|typo
            "inside_quoted_dup": self._in_quoted,
            "segment_kind": self._seg_kind,
        })
        return start, end

    def add_placeholder(self, surface: str, kind: str = "placeholder") -> tuple[int, int]:
        start, end = self.add(surface)
        self.non_entities.append({
            "doc_id": self.doc_id, "char_start": start, "char_end": end,
            "text": surface, "kind": kind,
        })
        return start, end

    def text(self) -> str:
        return "".join(self.buf)


# ---------------------------------------------------------------------------
# Entity population
# ---------------------------------------------------------------------------
def _gen_phone(rng: _Rng) -> str:
    return f"({rng.intr(200,989)}) {rng.intr(200,999)}-{rng.intr(1000,9999)}"


def _gen_address(rng: _Rng) -> str:
    city, state, z3 = rng.pick(CITIES)
    return (f"{rng.intr(10,9999)} {rng.pick(STREETS)} {rng.pick(STREET_TYPES)}, "
            f"{city}, {state} {z3}{rng.intr(10,99)}")


def _gen_npi(rng: _Rng) -> str:
    first9 = "".join(str(rng.intr(0, 9)) for _ in range(9))
    if first9[0] == "0":
        first9 = "1" + first9[1:]
    return first9 + str(textnorm.npi_checkdigit(first9))


def _gen_tin(rng: _Rng) -> str:
    return f"{rng.intr(10,99)}-{rng.intr(1000000,9999999)}"


def _gen_ssn(rng: _Rng) -> str:
    return f"{rng.intr(100,899)}-{rng.intr(10,99)}-{rng.intr(1000,9999)}"


def _gen_dob(rng: _Rng) -> str:
    return f"{rng.intr(1,12):02d}/{rng.intr(1,28):02d}/{rng.intr(1948,2005)}"


def build_entities(rng: _Rng) -> list[GTEntity]:
    ents: list[GTEntity] = []
    used_names = set()

    def fresh_person():
        for _ in range(50):
            f = rng.pick(FIRST_NAMES)
            l = rng.pick(LAST_NAMES)
            if (f, l) not in used_names:
                used_names.add((f, l))
                return f, l
        return rng.pick(FIRST_NAMES), rng.pick(LAST_NAMES)

    n_target = rng.intr(CFG.N_GROUND_TRUTH_ENTITIES_MIN, CFG.N_GROUND_TRUTH_ENTITIES_MAX)

    # --- claimants ---
    n_claim = int(n_target * 0.42)
    for i in range(n_claim):
        f, l = fresh_person()
        e = GTEntity(gt_entity_id=f"gt_clm_{i:03d}", klass="claimant", first=f, last=l)
        e.dob = _gen_dob(rng)
        e.phone_windows = [{"value": _gen_phone(rng), "valid_from": "2024-01-01", "valid_to": None}]
        e.address_windows = [{"value": _gen_address(rng), "valid_from": "2024-01-01", "valid_to": None}]
        if rng.chance(0.4):
            e.ssn = _gen_ssn(rng)
        ents.append(e)

    # --- attorneys (several sharing a firm/domain) ---
    n_att = int(n_target * 0.18)
    for i in range(n_att):
        f, l = fresh_person()
        firm, domain = rng.pick(LAW_FIRMS) if i % 2 else LAW_FIRMS[0]  # bias toward XYZ
        e = GTEntity(gt_entity_id=f"gt_att_{i:03d}", klass="attorney", first=f, last=l, firm=firm)
        e.email = f"{f.lower()}.{l.lower()}@{domain}"
        e.phone_windows = [{"value": _gen_phone(rng), "valid_from": "2023-01-01", "valid_to": None}]
        e.address_windows = [{"value": _gen_address(rng), "valid_from": "2023-01-01", "valid_to": None}]
        ents.append(e)

    # --- medical providers (with NPIs) ---
    n_prov = int(n_target * 0.18)
    for i in range(n_prov):
        if rng.chance(0.5):
            f, l = fresh_person()
            name = f"Dr. {f} {l}"
            e = GTEntity(gt_entity_id=f"gt_prv_{i:03d}", klass="medical_provider",
                         first=f, last=l, org_name=name)
        else:
            l = rng.pick(LAST_NAMES)
            e = GTEntity(gt_entity_id=f"gt_prv_{i:03d}", klass="medical_provider",
                         org_name=f"{l} {rng.pick(PROVIDER_SUFFIX)}")
        e.npi = _gen_npi(rng)
        e.phone_windows = [{"value": _gen_phone(rng), "valid_from": "2022-01-01", "valid_to": None}]
        e.address_windows = [{"value": _gen_address(rng), "valid_from": "2022-01-01", "valid_to": None}]
        ents.append(e)

    # --- repair shops (with TINs) ---
    n_shop = int(n_target * 0.12)
    for i in range(n_shop):
        l = rng.pick(LAST_NAMES)
        e = GTEntity(gt_entity_id=f"gt_shp_{i:03d}", klass="repair_shop",
                     org_name=f"{l} {rng.pick(SHOP_SUFFIX)}")
        e.tin = _gen_tin(rng)
        e.phone_windows = [{"value": _gen_phone(rng), "valid_from": "2023-06-01", "valid_to": None}]
        e.address_windows = [{"value": _gen_address(rng), "valid_from": "2023-06-01", "valid_to": None}]
        ents.append(e)

    # --- adjusters / client reps ---
    n_adj = n_target - len(ents)
    for i in range(max(n_adj, 3)):
        f, l = fresh_person()
        e = GTEntity(gt_entity_id=f"gt_adj_{i:03d}", klass="adjuster", first=f, last=l)
        e.email = f"{f[0].lower()}{l.lower()}@ourinsco.com"
        e.phone_windows = [{"value": _gen_phone(rng), "valid_from": "2020-01-01", "valid_to": None}]
        ents.append(e)

    _plant_hard_cases(ents, rng)
    return ents


def _plant_hard_cases(ents: list[GTEntity], rng: _Rng) -> None:
    by_class: dict[str, list[GTEntity]] = {}
    for e in ents:
        by_class.setdefault(e.klass, []).append(e)

    # Jr/Sr pair at one address
    claimants = by_class.get("claimant", [])
    if len(claimants) >= 2:
        sr, jr = claimants[0], claimants[1]
        jr.first, jr.last = sr.first, sr.last
        sr.suffix, jr.suffix = "Sr", "Jr"
        shared_addr = sr.address_windows[-1]["value"]
        jr.address_windows = [{"value": shared_addr, "valid_from": "2024-01-01", "valid_to": None}]
        sr.hard_case_tags.append("jr_sr")
        jr.hard_case_tags.append("jr_sr")

    # phoenix repair shop: new name+TIN, same address/phone as an existing shop
    shops = by_class.get("repair_shop", [])
    if len(shops) >= 2:
        old, new = shops[0], shops[-1]
        new.address_windows = [dict(old.address_windows[-1])]
        new.phone_windows = [dict(old.phone_windows[-1])]
        old.hard_case_tags.append("phoenix_shop")
        new.hard_case_tags.append("phoenix_shop")

    # shared building address across unrelated providers
    provs = by_class.get("medical_provider", [])
    if len(provs) >= 2:
        bldg = provs[0].address_windows[-1]["value"]
        provs[1].address_windows = [{"value": bldg, "valid_from": "2022-01-01", "valid_to": None}]
        provs[0].hard_case_tags.append("shared_address")
        provs[1].hard_case_tags.append("shared_address")

    # recycled phone number (claimant reuses a provider's old phone)
    if claimants and provs:
        recycled = provs[-1].phone_windows[-1]["value"]
        claimants[-1].phone_windows.append({"value": recycled, "valid_from": "2026-01-01", "valid_to": None})
        claimants[-1].hard_case_tags.append("recycled_phone")
        provs[-1].hard_case_tags.append("recycled_phone")

    # address change over time (validity windows) for a couple of attorneys
    for e in by_class.get("attorney", [])[:2]:
        old = e.address_windows[-1]
        old["valid_to"] = "2025-06-30"
        e.address_windows.append({"value": _gen_address(rng), "valid_from": "2025-07-01", "valid_to": None})
        e.hard_case_tags.append("address_change")

    # multi_role: mark one claimant to also appear as an adjuster elsewhere
    if claimants:
        claimants[2 % len(claimants)].hard_case_tags.append("multi_role")

    # quoted_only: mark a few entities to appear ONLY in quoted email history
    pool = by_class.get("attorney", []) + by_class.get("medical_provider", [])
    for e in rng.sample(pool, min(4, len(pool))):
        e.hard_case_tags.append("quoted_only")


# ---------------------------------------------------------------------------
# Claim / role assignment
# ---------------------------------------------------------------------------
def assign_claims(ents: list[GTEntity], rng: _Rng) -> dict:
    # quoted_only entities are excluded from normal role pools so their ONLY
    # placements are inside quoted email history (planted separately).
    quoted_only_ids = {e.gt_entity_id for e in ents if "quoted_only" in e.hard_case_tags}
    by_class: dict[str, list[GTEntity]] = {}
    for e in ents:
        if e.gt_entity_id in quoted_only_ids:
            continue
        by_class.setdefault(e.klass, []).append(e)

    claims = {}

    for c in range(CFG.N_CLAIMS):
        claim_id = f"CLM{c:04d}"
        roster = {}
        clm = rng.pick(by_class["claimant"])
        roster["claimant"] = [clm]
        clm.roles_per_claim[claim_id] = "claimant"
        if rng.chance(0.75):
            att = rng.pick(by_class["attorney"])
            roster["attorney"] = [att]
            att.roles_per_claim[claim_id] = "claimant_attorney"
        provs = rng.sample(by_class["medical_provider"], rng.intr(0, 2))
        if provs:
            roster["medical_provider"] = provs
            for p in provs:
                p.roles_per_claim[claim_id] = "treating_provider"
        if rng.chance(0.4):
            shop = rng.pick(by_class["repair_shop"])
            roster["repair_shop"] = [shop]
            shop.roles_per_claim[claim_id] = "repair_shop"
        adj = rng.pick(by_class["adjuster"])
        roster["adjuster"] = [adj]
        adj.roles_per_claim[claim_id] = "adjuster"
        claims[claim_id] = roster

    # multi_role: force the tagged claimant onto a SECOND distinct claim so the
    # same person is genuinely mentioned across two claims (cross-claim linkage).
    for e in ents:
        if "multi_role" in e.hard_case_tags and e.klass == "claimant":
            existing = set(e.roles_per_claim)
            for c in range(CFG.N_CLAIMS):
                cid = f"CLM{c:04d}"
                if cid not in existing:
                    claims[cid]["claimant"] = [e]
                    e.roles_per_claim[cid] = "claimant"
                    break
            break
    return claims


# entities that should appear ONLY inside quoted history are tracked here
def _pick_variant(ent: GTEntity, rng: _Rng, variants: dict) -> tuple[str, str]:
    kinds = list(variants.keys())
    weights = {"canonical": 0.5, "flip": 0.15, "nickname": 0.15, "initials": 0.1, "typo": 0.1}
    pool = []
    for k in kinds:
        pool += [k] * max(1, int(weights.get(k, 0.1) * 20))
    k = rng.pick(pool)
    return k, variants[k]


__all__ = ["generate_corpus", "GTEntity"]


# ---------------------------------------------------------------------------
# Note generation
# ---------------------------------------------------------------------------
def _label_variants(rng: _Rng):
    """Inconsistent label styles for template blocks."""
    return {
        "claimant": rng.pick(["Claimant Name:", "Clmt name -", "CLAIMANT_NM=", "Claimant:"]),
        "attorney": rng.pick(["Attorney:", "Clmt Atty -", "ATTY_NAME=", "Counsel:"]),
        "provider": rng.pick(["Provider:", "Treating Physician -", "PROVIDER=", "Dr:"]),
        "phone": rng.pick(["Phone:", "Ph -", "TEL=", "Contact #:"]),
        "email": rng.pick(["Email:", "E-mail -", "EMAIL=", "Mail:"]),
        "dob": rng.pick(["DOB:", "D.O.B -", "BIRTHDATE=", "Date of Birth:"]),
        "address": rng.pick(["Address:", "Addr -", "ADDR=", "Mailing Address:"]),
        "npi": rng.pick(["NPI:", "NPI #-", "NPI_NUM="]),
        "tin": rng.pick(["TIN:", "Tax ID -", "TIN_NUM="]),
        "claim": rng.pick(["Claim No:", "Claim# -", "CLAIM_ID="]),
    }


def _emit_template_block(nb: NoteBuilder, claim_id: str, roster: dict, rng: _Rng):
    nb.segment("template_block")
    lab = _label_variants(rng)
    nb.add(f"{lab['claim']} {claim_id}\n")
    # claimant
    clm = roster["claimant"][0]
    nb.add(f"{lab['claimant']} ")
    if rng.chance(0.85):
        kind, surf = _pick_variant(clm, rng, name_variants(clm, rng))
        nb.add_entity(surf, clm, kind)
    else:
        nb.add_placeholder(rng.pick(PLACEHOLDERS))
    nb.add("\n")
    # dob (sometimes placeholder)
    nb.add(f"{lab['dob']} ")
    if clm.dob and rng.chance(0.7):
        nb.add(clm.dob)
    else:
        nb.add_placeholder(rng.pick(["N/A", "TBD", "xx/xx/xxxx"]))
    nb.add("\n")
    # phone
    nb.add(f"{lab['phone']} ")
    if rng.chance(0.7):
        nb.add(clm.current_phone())
    else:
        nb.add_placeholder("same as above", kind="placeholder")
    nb.add("\n")
    # attorney
    if "attorney" in roster:
        att = roster["attorney"][0]
        nb.add(f"{lab['attorney']} ")
        kind, surf = _pick_variant(att, rng, name_variants(att, rng))
        nb.add_entity(surf, att, kind)
        nb.add(f"  ({att.firm})\n")
        nb.add(f"{lab['email']} ")
        nb.add(att.email if rng.chance(0.8) else "___")
        if not rng.chance(0.8):
            pass
        nb.add("\n")
    # provider + NPI + (address/phone surfaced so shared-building / recycled-phone
    # hard cases are observable in the text, not just the manifest)
    if "medical_provider" in roster:
        p = roster["medical_provider"][0]
        nb.add(f"{lab['provider']} ")
        nb.add_entity(p.display_name(), p, "canonical")
        nb.add("\n")
        nb.add(f"{lab['npi']} {p.npi}\n")
        if p.address_windows and rng.chance(0.7):
            nb.add(f"{lab['address']} {p.current_address()}\n")
        if p.phone_windows and rng.chance(0.7):
            nb.add(f"{lab['phone']} {p.current_phone()}\n")
    # repair shop + TIN + address/phone (phoenix-shop detection needs these)
    if "repair_shop" in roster:
        s = roster["repair_shop"][0]
        nb.add(f"{lab['provider']} ")
        nb.add_entity(s.display_name(), s, "canonical")
        nb.add("\n")
        nb.add(f"{lab['tin']} {s.tin}\n")
        if s.address_windows and rng.chance(0.8):
            nb.add(f"{lab['address']} {s.current_address()}\n")
        if s.phone_windows and rng.chance(0.8):
            nb.add(f"{lab['phone']} {s.current_phone()}\n")
    # occasionally truncate mid-template with narrative jammed on
    if rng.chance(0.25):
        nb.add(f"{lab['address']} ")
        nb.segment("narrative")
        nb.add("clmt states mail returned undeliverable will confirm new addr next call")


def _emit_email(nb: NoteBuilder, claim_id: str, roster: dict, rng: _Rng, ents_by_id: dict):
    """Email with From/Sent/To/Subject headers, body, signature, and quoted chain."""
    sender = roster.get("attorney", roster.get("adjuster"))[0]
    recipient = roster["adjuster"][0] if sender.klass != "adjuster" else roster.get("attorney", [sender])[0]

    def header(frm: GTEntity, to: GTEntity, subj: str):
        nb.segment("email_header")
        nb.add("From: ")
        nb.add_entity(frm.display_name(), frm, "canonical")
        nb.add(f" <{frm.email or 'noreply@example.com'}>\n")
        nb.add(f"Sent: {rng.pick(['Mon','Tue','Wed','Thu','Fri'])}, "
               f"{rng.pick(['Jan','Feb','Mar','Apr','May','Jun'])} {rng.intr(1,28)}, 2026 "
               f"{rng.intr(1,12)}:{rng.intr(10,59)} {rng.pick(['AM','PM'])}\n")
        nb.add("To: ")
        nb.add_entity(to.display_name(), to, "canonical")
        nb.add(f" <{to.email or 'adj@ourinsco.com'}>\n")
        nb.add(f"Subject: RE: Claim {claim_id} - status\n\n")

    def signature(who: GTEntity):
        nb.segment("email_signature")
        nb.add("\n--\n")
        _, _ = nb.add_entity(who.display_name(), who, "canonical")
        nb.add(f"\n{who.firm or 'Claims Department'}\n")
        nb.add(f"Direct: {who.current_phone() or '(555) 000-0000'}\n")
        if who.email:
            nb.add(f"{who.email}\n")
        if who.address_windows:
            nb.add(f"{who.current_address()}\n")

    # most-recent message
    header(sender, recipient, "status")
    nb.segment("email_body")
    body = rng.pick([
        f"Following up on {claim_id}. Please advise on the current plan of action.",
        f"Per our call, attaching the updated demand for {claim_id}. Client is available next week.",
        f"We have not received the records yet for {claim_id}. Kindly expedite.",
    ])
    nb.add(body + " &nbsp; <br>\n")
    signature(sender)
    nb.segment("boilerplate")
    nb.add_placeholder("\n" + DISCLAIMER, kind="boilerplate")

    # quoted reply chain duplicating earlier messages 2-5x (re-plants mentions inside quotes)
    n_quote = rng.intr(2, 5)
    prev_sender, prev_recip = recipient, sender
    for q in range(n_quote):
        nb.segment("email_quoted", quoted=True)
        prefix = ">" * (q + 1)
        nb.add(f"\n{prefix} From: ")
        nb.add_entity(prev_sender.display_name(), prev_sender, "canonical")
        nb.add(f" <{prev_sender.email or 'x@example.com'}>\n")
        nb.add(f"{prefix} Sent: earlier\n")
        nb.add(f"{prefix} To: {prev_recip.display_name()}\n")
        nb.add(f"{prefix} Subject: RE: Claim {claim_id}\n")
        nb.add(f"{prefix} {body}\n")
        prev_sender, prev_recip = prev_recip, prev_sender


def _emit_plan_of_action(nb: NoteBuilder, claim_id: str, roster: dict, rng: _Rng, quoted_only_ent: GTEntity | None):
    nb.segment("narrative")
    clm = roster["claimant"][0]
    kind, surf = _pick_variant(clm, rng, name_variants(clm, rng))
    templates = [
        "spoke w clmt {name} last Tues re tx status; ",
        "POA: {name} denies prior tx with ",
        "suspect shop inflating parts on {name} file; ",
        "prior note listed wrong DOB for {name}, correct is {dob}; ",
    ]
    t = rng.pick(templates)
    # emit with name planted
    before, _, after = t.partition("{name}")
    before = before.replace("{dob}", clm.dob or "unknown")
    after = after.replace("{dob}", clm.dob or "unknown")
    nb.add(before)
    nb.add_entity(surf, clm, kind)
    nb.add(after)

    # negation / allegation / provider mention
    if "medical_provider" in roster and rng.chance(0.6):
        p = roster["medical_provider"][0]
        nb.add("Dr. ")
        nb.add_entity(p.last or p.display_name(), p, "initials" if p.last else "canonical")
        nb.add(" per records. ")
    if rng.chance(0.5):
        nb.add("clmt alleges ongoing pain; ")
    # a mention that appears ONLY inside quoted history for a quoted_only entity
    if quoted_only_ent is not None:
        nb.segment("email_quoted", quoted=True)
        nb.add("\n> earlier corr from ")
        nb.add_entity(quoted_only_ent.display_name(), quoted_only_ent, "canonical")
        nb.add(f" <{quoted_only_ent.email or 'x@example.com'}> re coverage\n")


def generate_corpus(seed: int | None = None) -> dict:
    """Generate the corpus + sealed manifest. Returns a summary dict.

    Idempotent-by-seed: clears data/raw_notes and rewrites deterministically.
    """
    seed = CFG.SEED if seed is None else seed
    rng = _Rng(seed)
    Paths.ensure()

    # clear prior raw notes (regeneration only; hashes are re-sealed afterwards)
    for f in Paths.raw_notes.glob("*.txt"):
        f.unlink()

    ents = build_entities(rng)
    ents_by_id = {e.gt_entity_id: e for e in ents}
    claims = assign_claims(ents, rng)

    quoted_only = [e for e in ents if "quoted_only" in e.hard_case_tags]
    quoted_only_iter = iter(quoted_only * 100) if quoted_only else iter(())

    all_placements: list[dict] = []
    all_non_entities: list[dict] = []
    doc_rows = []
    placed_gt_ids: set[str] = set()

    doc_counter = 0
    for claim_id, roster in claims.items():
        n_notes = rng.intr(CFG.NOTES_PER_CLAIM_MIN, CFG.NOTES_PER_CLAIM_MAX)
        for s in range(n_notes):
            doc_id = f"DOC{doc_counter:05d}"
            doc_counter += 1
            nb = NoteBuilder(doc_id)
            category = rng.pick(list(_CATS))
            form = rng.pick(["template", "email", "plan", "template", "plan", "mixed"])

            # header line (legacy inconsistency: category stored vs implied)
            store_cat = category if rng.chance(0.6) else ""
            if store_cat:
                nb.segment("template_block")
                nb.add(f"[{store_cat.upper()}] claim {claim_id} note {s+1}\n")

            if form == "template":
                _emit_template_block(nb, claim_id, roster, rng)
            elif form == "email" and ("attorney" in roster or "adjuster" in roster):
                _emit_email(nb, claim_id, roster, rng, ents_by_id)
            elif form == "plan":
                qo = None
                if quoted_only and rng.chance(0.4):
                    qo = next(quoted_only_iter, None)
                _emit_plan_of_action(nb, claim_id, roster, rng, qo)
            else:  # mixed
                _emit_template_block(nb, claim_id, roster, rng)
                nb.add("\n\n")
                _emit_plan_of_action(nb, claim_id, roster, rng, None)

            text = nb.text()
            # write immutable raw note
            (Paths.raw_notes / f"{doc_id}.txt").write_text(text)
            doc_rows.append({
                "doc_id": doc_id, "claim_id": claim_id,
                "category_stored": store_cat, "n_chars": len(text), "seq_in_claim": s,
            })
            all_placements.extend(nb.placements)
            all_non_entities.extend(nb.non_entities)
            for pl in nb.placements:
                placed_gt_ids.add(pl["gt_entity_id"])

    # Guarantee every quoted_only entity has >=1 placement, ALL inside quotes:
    # emit a dedicated correspondence note per unplaced quoted_only entity.
    for e in quoted_only:
        if e.gt_entity_id in placed_gt_ids:
            continue
        doc_id = f"DOC{doc_counter:05d}"
        doc_counter += 1
        nb = NoteBuilder(doc_id)
        claim_id = f"CLM{rng.intr(0, CFG.N_CLAIMS-1):04d}"
        nb.segment("email_header")
        nb.add(f"[GENERAL_CORRESPONDENCE] claim {claim_id}\nFrom: Records Desk\n\n")
        nb.segment("email_body")
        nb.add("See prior thread below for background.\n")
        nb.segment("email_quoted", quoted=True)
        nb.add("\n> From: ")
        nb.add_entity(e.display_name(), e, "canonical")
        nb.add(f" <{e.email or 'records@example.com'}>\n> Re: prior correspondence on this file.\n")
        text = nb.text()
        (Paths.raw_notes / f"{doc_id}.txt").write_text(text)
        doc_rows.append({"doc_id": doc_id, "claim_id": claim_id,
                         "category_stored": "general_correspondence",
                         "n_chars": len(text), "seq_in_claim": 0})
        all_placements.extend(nb.placements)
        all_non_entities.extend(nb.non_entities)
        placed_gt_ids.add(e.gt_entity_id)

    # keep the quoted_only tag only for entities whose placements are ALL quoted
    placements_by_ent: dict[str, list[dict]] = {}
    for pl in all_placements:
        placements_by_ent.setdefault(pl["gt_entity_id"], []).append(pl)
    for e in quoted_only:
        pls = placements_by_ent.get(e.gt_entity_id, [])
        if not pls or any(not p["inside_quoted_dup"] for p in pls):
            e.hard_case_tags = [t for t in e.hard_case_tags if t != "quoted_only"]

    manifest = {
        "seed": seed,
        "n_docs": len(doc_rows),
        "entities": [_entity_manifest(e) for e in ents],
        "placements": all_placements,
        "non_entities": all_non_entities,
        "claims": {cid: {k: [e.gt_entity_id for e in v] for k, v in roster.items()}
                   for cid, roster in claims.items()},
        "documents": doc_rows,
    }
    Paths.manifest_json.parent.mkdir(parents=True, exist_ok=True)
    Paths.manifest_json.write_text(json.dumps(manifest, indent=1))

    return {
        "seed": seed,
        "n_entities": len(ents),
        "n_docs": len(doc_rows),
        "n_placements": len(all_placements),
        "n_non_entities": len(all_non_entities),
        "n_quoted_only": len([e for e in ents if "quoted_only" in e.hard_case_tags]),
    }


_CATS = (
    "medical_management", "legal_litigation", "siu_investigation",
    "repair_estimate", "payment", "subrogation", "plan_of_action",
    "general_correspondence",
)


def _entity_manifest(e: GTEntity) -> dict:
    attrs = []
    for a in e.address_windows:
        attrs.append({"attribute": "has_address", "value": a["value"],
                      "valid_from": a["valid_from"], "valid_to": a["valid_to"]})
    for p in e.phone_windows:
        attrs.append({"attribute": "has_phone", "value": p["value"],
                      "valid_from": p["valid_from"], "valid_to": p["valid_to"]})
    canonical = {
        "name": e.display_name(),
        "email": e.email, "npi": e.npi, "tin": e.tin, "ssn": e.ssn,
        "dob": e.dob, "firm": e.firm,
    }
    return {
        "gt_entity_id": e.gt_entity_id,
        "class": e.klass,
        "canonical": {k: v for k, v in canonical.items() if v},
        "attribute_windows": attrs,
        "roles_per_claim": e.roles_per_claim,
        "hard_case_tags": sorted(set(e.hard_case_tags)),
    }
