"""Frozen data contracts shared by every pipeline stage.

This module is the authority for: entity classes, segment kinds, polarity and
predicate vocabularies, the immutable relational schema (SQLite DDL), the
Gemini JSON-schema constrained-output specs (extraction / adjudication / query
plan), and the ground-truth manifest / dossier / scan-ledger shapes.

Every notebook (02-08) imports from here; none re-defines a table or a schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
ENTITY_CLASSES = (
    "claimant",
    "attorney",
    "medical_provider",
    "repair_shop",
    "adjuster",       # our-side adjuster / client rep
)

SEGMENT_KINDS = (
    "template_block",
    "narrative",
    "email_header",
    "email_body",
    "email_signature",
    "email_quoted",
    "boilerplate",
)

NOTE_CATEGORIES = (
    "medical_management",
    "legal_litigation",
    "siu_investigation",
    "repair_estimate",
    "payment",
    "subrogation",
    "plan_of_action",
    "general_correspondence",
)

POLARITIES = ("asserted", "negated", "alleged", "reported", "retracted")

# predicate vocabulary for assertions (subject mention -> predicate -> object)
PREDICATES = (
    "has_name",
    "has_role",            # object_value in ENTITY_CLASSES-ish role string, per claim
    "has_email",
    "has_phone",
    "has_address",
    "has_npi",
    "has_tin",
    "has_ssn",
    "has_dob",
    "has_firm",            # attorney firm / org affiliation
    "has_title",
    "works_on_claim",
    "represents",          # relation: subject represents object_mention
    "affiliated_with",     # relation: subject affiliated with object_mention (firm/shop)
    "allegation",          # free allegation text (object_value_raw)
)

IDENTIFIER_PREDICATES = ("has_email", "has_phone", "has_npi", "has_tin", "has_ssn")

# resolution candidate-generation pass identifiers (logged per pair as gen_passes)
GEN_PASSES = {
    "B0": "exact normalized name x class",
    "A1": "exact validated identifier (npi/tin/ssn/email)",
    "B1": "phone last-7 match",
    "B2": "normalized-address key match",
    "B3": "phonetic-name x state",
    "B4": "name-initials x DOB-year",
    "C1": "embedding top-k class-filtered",
    "D1": "claim co-occurrence",
}

# ---------------------------------------------------------------------------
# Relational schema (SQLite).  All tables are append/immutable-by-convention:
# mentions and assertions are NEVER updated or deleted after insert; entity
# membership changes are expressed as new rows in entity_versions/entity_members.
# ---------------------------------------------------------------------------
DDL = r"""
CREATE TABLE IF NOT EXISTS documents (
    doc_id            TEXT PRIMARY KEY,
    claim_id          TEXT NOT NULL,
    category          TEXT,            -- stored category field (may be NULL/implied)
    category_implied  TEXT,           -- category inferred from content (profiling)
    n_chars           INTEGER NOT NULL,
    seq_in_claim      INTEGER,
    created_ts        TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id           TEXT PRIMARY KEY,
    doc_id               TEXT NOT NULL,
    kind                 TEXT NOT NULL,   -- one of SEGMENT_KINDS
    char_start           INTEGER NOT NULL,
    char_end             INTEGER NOT NULL,
    template_fingerprint TEXT,            -- label-sequence hash for template_block
    dup_group_id         TEXT,            -- near-duplicate group
    is_canonical_dup     INTEGER DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS mentions (
    mention_id    TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    segment_id    TEXT,
    entity_class  TEXT NOT NULL,          -- one of ENTITY_CLASSES
    surface       TEXT NOT NULL,          -- raw surface string
    norm_surface  TEXT,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    extractor     TEXT NOT NULL,          -- 'template' | 'genai' | ...
    dup_group_id  TEXT,
    inside_quoted INTEGER DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS assertions (
    assertion_id       TEXT PRIMARY KEY,
    subject_mention_id TEXT NOT NULL,
    predicate          TEXT NOT NULL,      -- one of PREDICATES
    object_value_raw   TEXT,
    object_value_norm  TEXT,
    object_mention_id  TEXT,               -- set for relation predicates
    polarity           TEXT NOT NULL,      -- one of POLARITIES
    effective_from     TEXT,
    effective_to       TEXT,
    recorded_date      TEXT,
    temporal_conf      REAL,
    source_doc_id      TEXT NOT NULL,
    source_span_start  INTEGER NOT NULL,
    source_span_end    INTEGER NOT NULL,
    grounded           INTEGER NOT NULL DEFAULT 1,
    extractor          TEXT NOT NULL,
    pass_id            TEXT,
    confidence         REAL,
    FOREIGN KEY (subject_mention_id) REFERENCES mentions(mention_id)
);

-- SCAN-COVERAGE LEDGER: proves full-text scanning independent of what was found.
CREATE TABLE IF NOT EXISTS scan_ledger (
    ledger_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL,
    extractor   TEXT NOT NULL,
    pass_id     TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS candidate_pairs (
    pair_id       TEXT PRIMARY KEY,
    mention_id_a  TEXT NOT NULL,
    mention_id_b  TEXT NOT NULL,
    entity_class  TEXT,
    gen_passes    TEXT,                    -- JSON list of pass ids
    score         REAL,
    feature_json  TEXT,                    -- JSON of feature contributions + adjudicator verdict/rationale
    band          TEXT,                    -- 'link' | 'adjudicate' | 'no_link'
    adjudicated   INTEGER DEFAULT 0,
    verdict       TEXT                     -- 'link' | 'no_link' | NULL
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    entity_class    TEXT NOT NULL,
    canonical_name  TEXT,
    version_id      TEXT,                  -- current version
    n_mentions      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS entity_members (
    entity_id  TEXT NOT NULL,
    mention_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    PRIMARY KEY (entity_id, mention_id, version_id)
);

CREATE TABLE IF NOT EXISTS entity_versions (
    version_id      TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    cause           TEXT,                  -- 'initial' | 'merge' | 'split' | 'adjudicated_link'
    parent_entity_ids TEXT,               -- JSON list (lineage)
    created_ts      TEXT
);

-- Bitemporal attribute rows computed from assertions with survivorship tiers.
CREATE TABLE IF NOT EXISTS entity_attributes (
    attr_id           TEXT PRIMARY KEY,
    entity_id         TEXT NOT NULL,
    attribute         TEXT NOT NULL,       -- predicate-derived attribute name
    value_raw         TEXT,
    value_norm        TEXT,
    valid_from        TEXT,                -- real-world validity window
    valid_to          TEXT,
    known_from        TEXT,                -- system knowledge window
    known_to          TEXT,
    tier              TEXT,                -- survivorship tier name
    polarity          TEXT,
    conflict_flag     INTEGER DEFAULT 0,
    source_assertion_id TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

CREATE TABLE IF NOT EXISTS dossiers (
    entity_id    TEXT PRIMARY KEY,
    dossier_json TEXT NOT NULL
);

-- Identifiers are FIRST-CLASS observations, recorded whether or not a name
-- could be bound to them. An identifier mentioned with no name nearby (a
-- callback number, a bare billing address) is precisely the case that makes
-- identifier-mediated resolution valuable, so it must survive extraction.
CREATE TABLE IF NOT EXISTS identifier_observations (
    obs_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id            TEXT NOT NULL,
    char_start        INTEGER NOT NULL,
    char_end          INTEGER NOT NULL,
    kind              TEXT NOT NULL,      -- phone | email | address | npi | tin | ssn | vin
    value_raw         TEXT NOT NULL,
    value_norm        TEXT,
    subject_mention_id TEXT,              -- NULL => orphan, resolvable only via the id
    validated         INTEGER DEFAULT 0,
    extractor         TEXT
);

CREATE INDEX IF NOT EXISTS ix_idobs_doc ON identifier_observations(doc_id);
CREATE INDEX IF NOT EXISTS ix_idobs_norm ON identifier_observations(kind, value_norm);

-- Coreference output: an anaphor and the entity mention it was bound to.
-- Scored against the manifest's coref_chains (which carry the true referent
-- and hop count), so multi-hop resolution accuracy is measurable.
CREATE TABLE IF NOT EXISTS coref_links (
    link_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL,
    anaphor_start      INTEGER NOT NULL,
    anaphor_end        INTEGER NOT NULL,
    anaphor_text       TEXT,
    anaphor_kind       TEXT,              -- pronoun | descriptor
    antecedent_start   INTEGER,
    antecedent_end     INTEGER,
    antecedent_surface TEXT,
    antecedent_mention_id TEXT,
    backend            TEXT,
    confidence         REAL
);

CREATE INDEX IF NOT EXISTS ix_coref_doc ON coref_links(doc_id);
CREATE INDEX IF NOT EXISTS ix_seg_doc ON segments(doc_id);
CREATE INDEX IF NOT EXISTS ix_men_doc ON mentions(doc_id);
CREATE INDEX IF NOT EXISTS ix_men_class ON mentions(entity_class);
CREATE INDEX IF NOT EXISTS ix_ass_subj ON assertions(subject_mention_id);
CREATE INDEX IF NOT EXISTS ix_ass_pred ON assertions(predicate);
CREATE INDEX IF NOT EXISTS ix_ledger_doc ON scan_ledger(doc_id);
CREATE INDEX IF NOT EXISTS ix_attr_ent ON entity_attributes(entity_id);
CREATE INDEX IF NOT EXISTS ix_mem_ent ON entity_members(entity_id);
"""

TABLE_NAMES = (
    "documents", "segments", "mentions", "assertions", "scan_ledger", "coref_links", "identifier_observations",
    "candidate_pairs", "entities", "entity_members", "entity_versions",
    "entity_attributes", "dossiers",
)


# ---------------------------------------------------------------------------
# Gemini JSON-schema constrained output specs.
# These are response_schema dicts (OpenAPI-subset) for structured extraction.
# ---------------------------------------------------------------------------
def extraction_schema() -> dict:
    """Schema for narrative/email segment extraction.

    Returns a list of assertions, each carrying span offsets (relative to the
    segment text handed to the model), polarity, predicate, object value, and
    temporal info. The extractor maps segment-relative spans back to document
    offsets and runs the span-fidelity validator before persisting.
    """
    return {
        "type": "object",
        "properties": {
            "assertions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_surface": {"type": "string"},
                        "entity_class": {"type": "string", "enum": list(ENTITY_CLASSES)},
                        "subject_span_start": {"type": "integer"},
                        "subject_span_end": {"type": "integer"},
                        "predicate": {"type": "string", "enum": list(PREDICATES)},
                        "object_value": {"type": "string"},
                        "object_entity_surface": {"type": "string"},
                        "polarity": {"type": "string", "enum": list(POLARITIES)},
                        "effective_from": {"type": "string"},
                        "effective_to": {"type": "string"},
                        "temporal_conf": {"type": "number"},
                        "evidence_span_start": {"type": "integer"},
                        "evidence_span_end": {"type": "integer"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "entity_surface", "entity_class", "predicate",
                        "polarity", "evidence_span_start", "evidence_span_end",
                    ],
                },
            }
        },
        "required": ["assertions"],
    }


def adjudication_schema() -> dict:
    """Schema for the pairwise resolution adjudicator (ambiguous band)."""
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["link", "no_link"]},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
            "key_signals": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["verdict", "confidence", "rationale"],
    }


def query_plan_schema() -> dict:
    """Typed query-plan schema. Gemini fills this; deterministic code executes it.

    The plan is a filter/join spec over entities/attributes/identifiers/links.
    The model NEVER answers directly; it only emits a plan of this shape.
    """
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["find_entities", "describe_entity", "find_links"]},
            "target_class": {"type": "string", "enum": list(ENTITY_CLASSES) + ["any"]},
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [
                                "name", "email", "email_domain", "phone", "phone_last7",
                                "address", "address_key", "npi", "tin", "ssn", "dob",
                                "firm", "role", "claim_id", "allegation_text",
                            ],
                        },
                        "op": {
                            "type": "string",
                            "enum": ["eq", "contains", "endswith", "startswith", "fuzzy", "exists"],
                        },
                        "value": {"type": "string"},
                    },
                    "required": ["field", "op"],
                },
            },
            "link_via": {
                "type": "array",
                "items": {"type": "string", "enum": ["shared_identifier", "shared_address", "shared_claim", "same_firm"]},
            },
            "cross_reference": {"type": "string"},   # e.g. an address / email suffix / rep name to intersect against
            "want": {"type": "string", "enum": ["dossier", "list", "count"]},
        },
        "required": ["intent", "filters", "want"],
    }


# ---------------------------------------------------------------------------
# Dataclasses (typed builders used when inserting rows; keep field names aligned
# with the DDL above).
# ---------------------------------------------------------------------------
@dataclass
class Mention:
    mention_id: str
    doc_id: str
    segment_id: str | None
    entity_class: str
    surface: str
    norm_surface: str
    char_start: int
    char_end: int
    extractor: str
    dup_group_id: str | None = None
    inside_quoted: int = 0


@dataclass
class Assertion:
    assertion_id: str
    subject_mention_id: str
    predicate: str
    object_value_raw: str | None
    object_value_norm: str | None
    polarity: str
    source_doc_id: str
    source_span_start: int
    source_span_end: int
    extractor: str
    object_mention_id: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    recorded_date: str | None = None
    temporal_conf: float | None = None
    grounded: int = 1
    pass_id: str | None = None
    confidence: float | None = None


@dataclass
class ScanSpan:
    doc_id: str
    char_start: int
    char_end: int
    extractor: str
    pass_id: str


# ---- Ground-truth manifest shape (documentation; produced by corpus_gen) ----
GROUND_TRUTH_MANIFEST_SHAPE = {
    "seed": "int",
    "entities": [
        {
            "gt_entity_id": "str",
            "class": "one of ENTITY_CLASSES",
            "canonical": {"name": "str", "attributes": "..."},
            "attribute_windows": [
                {"attribute": "str", "value": "str", "valid_from": "date|null", "valid_to": "date|null"}
            ],
            "roles_per_claim": {"claim_id": "role"},
            "hard_case_tags": ["nickname", "name_flip", "typo", "jr_sr", "multi_role",
                                "phoenix_shop", "shared_address", "recycled_phone", "quoted_only"],
        }
    ],
    "placements": [
        {
            "gt_entity_id": "str",
            "doc_id": "str",
            "char_start": "int",
            "char_end": "int",
            "surface_variant": "str",
            "inside_quoted_dup": "bool",
            "segment_kind": "one of SEGMENT_KINDS",
        }
    ],
    "non_entities": [
        {"doc_id": "str", "char_start": "int", "char_end": "int", "text": "str", "kind": "placeholder|boilerplate"}
    ],
}
