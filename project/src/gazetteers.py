"""Layer 1b: deterministic gazetteers + regex for structured patterns.

Named cause of missed entities: "expecting GenAI to catch structured codes".
These patterns are hardcoded and exact -- an LLM is never asked to find a claim
id, NPI, TIN, SSN, CPT or ICD-10 code. Deterministic extractors run on every
character of every chunk and their output is UNIONed with the model extractors.

Every matcher returns absolute-offset spans (given the chunk's char_start) plus
an explicit VALIDATION STRENGTH, so downstream code can tell what a hit is
actually worth:

  * 'checksum'  -- a real check digit was verified. Only `npi` qualifies (Luhn
                   over '80840' + the first 9 digits, the NPPES standard). A
                   random 10-digit string passes with p~0.1, so this genuinely
                   discriminates.
  * 'format'    -- a shape or context constraint beyond the matching pattern
                   itself (email has an '@' and a dotted host; phone reduces to
                   10 digits; icd10/cpt require a cue word nearby).
  * 'none'      -- the pattern matched and nothing further was checked.

This distinction used to be a single `valid: bool` that conflated all three.
`ssn` and `tin` in particular were "validated" by re-running the identical
regex that had already matched, which added no information while reading -- in
code and in the architecture diagrams -- as though a real check had occurred.
Identifiers ARE structurally stronger than names, but that strength is
per-label and must not be claimed uniformly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import textnorm


@dataclass
class GazetteerHit:
    start: int          # absolute char offset in the document
    end: int
    text: str
    label: str          # semantic label, e.g. 'npi', 'phone'
    valid: bool         # passed whatever check applies to this label
    validation: str = "none"   # 'checksum' | 'format' | 'none'
    extractor: str = "regex_gazetteer"

    @property
    def checksum_verified(self) -> bool:
        """True only for a genuinely check-digit-verified identifier."""
        return self.validation == "checksum" and self.valid


# ---------------------------------------------------------------------------
# Patterns. Ordered most-specific first; overlapping hits are resolved by the
# ensemble (longest span wins, provenance unioned).
# ---------------------------------------------------------------------------
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn",             re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("tin",             re.compile(r"\b\d{2}-\d{7}\b")),
    ("npi",             re.compile(r"\b\d{10}\b")),
    # 140 VINs are planted in this corpus and, until now, none was ever
    # extracted: `vin` was declared a valid identifier kind in the schema and
    # had no detector anywhere. In a claim file the VIN is the natural join key
    # between a claimant, a vehicle and a repair shop.
    ("vin",             textnorm.VIN_RE),
    ("icd10",           re.compile(r"\b[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?\b")),
    ("cpt",             re.compile(r"\b\d{5}(?:-[A-Z]{2})?\b")),
    ("policy_number",   re.compile(r"\b(?:POL|PLC|POLICY)[#\s:-]*([A-Z0-9-]{5,})\b", re.I)),
    ("email",           textnorm.EMAIL_RE),
    ("phone",           textnorm.PHONE_RE),
    ("monetary_amount", re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b")),
    ("date",            re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
    ("date_written",    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b")),
    ("zip",             re.compile(r"\b\d{5}(?:-\d{4})?\b")),
    ("address",         re.compile(
        r"\b\d{1,5}\s+[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\s+"
        r"(?:St|Ave|Blvd|Rd|Dr|Ln|Ct|Pl|Pkwy)\b\.?"
        r"(?:,\s*[A-Z][A-Za-z]+,\s*[A-Z]{2}\s*\d{5})?")),
]

# ICD-10 and CPT are shape-ambiguous against ordinary tokens/zips in this corpus;
# they are collected but flagged low-confidence unless a cue word precedes them.
_ICD_CUE = re.compile(r"(?:icd|dx|diagnos)", re.I)
_CPT_CUE = re.compile(r"(?:cpt|procedure code|proc code)", re.I)


# What kind of check, if any, backs each label. See the module docstring.
VALIDATION_STRENGTH = {
    "npi": "checksum",
    "vin": "checksum",     # ISO 3779 check digit at position 9
    "email": "format",
    "phone": "format",
    "icd10": "format",     # cue-word context, not a code-set membership test
    "cpt": "format",       # same
    # Everything else has no check beyond the pattern that matched:
    "ssn": "none", "tin": "none", "policy_number": "none",
    "monetary_amount": "none", "date": "none", "date_written": "none",
    "zip": "none", "address": "none",
}


def _validate(label: str, text: str, left_context: str) -> tuple[bool, str]:
    """Return (passed, validation_strength).

    NOTE: a label with strength 'none' returns True -- the pattern matched and
    nothing more was asserted. That is not the same as being verified, which is
    why the strength is returned alongside and must be carried downstream.
    """
    strength = VALIDATION_STRENGTH.get(label, "none")
    if label == "npi":
        return textnorm.npi_is_valid(text), strength
    if label == "vin":
        # Shape alone is not enough: a random 17-char alphanumeric token passes
        # the pattern about 1 in 11 times, so without the check digit this would
        # be a false-positive generator over part numbers and claim references.
        return textnorm.vin_is_valid(text), strength
    if label == "email":
        return ("@" in text and "." in text.split("@")[-1]), strength
    if label == "phone":
        return (len(textnorm.phone_digits(text)) == 10), strength
    if label == "icd10":
        return bool(_ICD_CUE.search(left_context)), strength
    if label == "cpt":
        return bool(_CPT_CUE.search(left_context)), strength
    # ssn / tin previously re-ran their own matching regex here and called the
    # result validation. Removed: it was tautological.
    return True, strength


# When two patterns claim the SAME span (e.g. a valid 10-digit NPI also matches
# the bare-digit phone shape), the higher-priority label wins.
LABEL_PRIORITY = {
    "ssn": 95, "tin": 94, "npi": 93, "vin": 93, "email": 92,
    "policy_number": 90, "address": 80, "date_written": 72, "date": 70,
    "monetary_amount": 65, "phone": 60, "icd10": 55, "cpt": 54, "zip": 20,
}


def scan(text: str, base_offset: int = 0, resolve_conflicts: bool = True) -> list[GazetteerHit]:
    """Run every deterministic pattern over `text`.

    `base_offset` is the chunk's absolute char_start so returned spans are
    absolute document offsets. When `resolve_conflicts`, hits sharing an exact
    span are collapsed to the highest-priority label (see LABEL_PRIORITY), and a
    hit fully contained inside a higher-priority hit is dropped (e.g. the zip
    inside a full address).
    """
    hits: list[GazetteerHit] = []
    for label, pat in PATTERNS:
        for m in pat.finditer(text):
            s, e = m.start(), m.end()
            left = text[max(0, s - 30):s]
            ok, strength = _validate(label, m.group(0), left)
            hits.append(GazetteerHit(
                start=base_offset + s, end=base_offset + e, text=m.group(0),
                label=label, valid=ok, validation=strength,
            ))
    if not resolve_conflicts:
        return hits

    # 1) exact-span conflicts -> highest priority label wins
    by_span: dict[tuple[int, int], GazetteerHit] = {}
    for h in hits:
        key = (h.start, h.end)
        cur = by_span.get(key)
        if cur is None or LABEL_PRIORITY.get(h.label, 0) > LABEL_PRIORITY.get(cur.label, 0):
            by_span[key] = h
    kept = sorted(by_span.values(), key=lambda h: (h.start, -(h.end - h.start)))

    # 2) drop a hit strictly contained in a higher-priority hit
    out: list[GazetteerHit] = []
    for h in kept:
        contained = any(
            o is not h and o.start <= h.start and h.end <= o.end
            and (o.end - o.start) > (h.end - h.start)
            and LABEL_PRIORITY.get(o.label, 0) >= LABEL_PRIORITY.get(h.label, 0)
            for o in kept
        )
        if not contained:
            out.append(h)
    return out


def scan_valid(text: str, base_offset: int = 0) -> list[GazetteerHit]:
    """Hits that passed whatever check applies to their label.

    For most labels that check is vacuous -- see VALIDATION_STRENGTH. Use
    `scan_checksum_verified` when you need identifiers that are actually
    verified rather than merely well-shaped.
    """
    return [h for h in scan(text, base_offset) if h.valid]


def scan_checksum_verified(text: str, base_offset: int = 0) -> list[GazetteerHit]:
    """Only hits backed by a real check digit (today: npi)."""
    return [h for h in scan(text, base_offset) if h.checksum_verified]


# ---------------------------------------------------------------------------
# Static gazetteer lists (known-value lookups). In production these come from
# reference data (provider registries, firm directories, carrier rep rosters).
# ---------------------------------------------------------------------------
ROLE_CUES = {
    "attorney": ("atty", "attorney", "counsel", "esq", "law group", "law offices",
                 "llp", "legal", "trial group"),
    "medical_provider": ("dr.", "dr ", "physician", "provider", "clinic", "hospital",
                         "orthopedic", "physical therapy", "imaging", "chiropractic",
                         "neurology", "medical group", "npi"),
    "repair_shop": ("auto body", "collision", "automotive", "car care", "body works",
                    "repair", "shop", "tin"),
    "adjuster": ("adjuster", "claims department", "claim rep", "examiner"),
}

ORG_SUFFIXES = (
    "LLP", "LLC", "Inc", "PLLC", "PC", "Group", "Associates", "Partners",
    "Center", "Clinic", "Hospital", "Body", "Collision", "Automotive",
    "Orthopedics", "Neurology", "Therapy", "Imaging", "Chiropractic",
)


def role_from_context(context: str) -> str | None:
    low = context.lower()
    for role, cues in ROLE_CUES.items():
        if any(c in low for c in cues):
            return role
    return None
