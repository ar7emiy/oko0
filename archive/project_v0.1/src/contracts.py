"""The data contracts. Every table, and why it has the shape it has.

THE ONE STRUCTURAL DECISION
---------------------------
An entity is CLAIM-SCOPED. Identity beyond a claim is an explicit LINK, never a
merge.

That is not a preference. In v0, global transitive clustering fused four
different Andersons into one entity, and 46% of labeled mentions ended up inside
an entity that mixed two or more real parties. Under transitive closure the
blast radius of one wrong edge is the whole connected component -- so a single
0.89 name similarity between two strangers corrupts an unbounded number of
dossiers.

Making cross-claim identity a link changes the failure from "a corrupted blob
nobody can repair" to "one visible row a reviewer can reject."

EVERY ROW CARRIES ITS EVIDENCE
------------------------------
There is no table here that cannot be regenerated from spans, and no fact
without a span. Dossiers are VIEWS over these rows, never stored artifacts, so
a correction is a new row rather than a mutation.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Controlled vocabularies -- kept as small as possible
# ---------------------------------------------------------------------------

# STRUCTURAL type, derived from the NAME STRING alone -- never from context.
#
# v0 had `entity_class` (claimant/attorney/medical_provider/repair_shop/
# adjuster) assigned by a classifier reading surrounding context. Measured, it
# disagreed with itself on 69% of real entities, and on 30% of distinct surface
# strings -- the identical text "lucas martinez" was labeled attorney, claimant,
# medical_provider AND repair_shop. Context encodes ROLE, which genuinely varies
# sentence to sentence; it cannot answer a question that must stay constant.
#
# So type comes from the string, which makes it deterministic and identical for
# identical text by construction. `unknown` is a real answer, not a failure.
ENTITY_TYPES = ("person", "organization", "unknown")

# Identifier kinds. `dob` means DATE OF BIRTH and nothing else -- in v0 it
# absorbed every bare date, so payment dates and deposition dates were stored as
# people's birthdates and one was bound to a claimant as if it were his own.
IDENTIFIER_KINDS = ("phone", "email", "address", "npi", "tin", "ssn", "vin", "dob")

# How strongly an identifier was checked. Carried verbatim from v0, where the
# distinction proved load-bearing: only `checksum` kinds are safe to auto-link
# entities across claims.
VALIDATIONS = ("checksum", "format", "none")

# Why two mentions were put in the same local entity, or two local entities
# linked. Recorded per row so a reviewer can ask "on what basis?" and get an
# answer rather than a probability.
MERGE_BASES = ("exact_name", "token_subset_unambiguous", "shared_identifier")
LINK_BASES = ("shared_identifier", "name_and_attribute", "reviewer")

# Link lifecycle. `auto` and `review` are machine output; `accepted` and
# `rejected` are human decisions and a pipeline re-run MUST NOT overwrite them.
LINK_STATUS = ("auto", "review", "accepted", "rejected")

# Deliberately OPEN vocabulary. v0 closed this and then discarded any predicate
# not on the list -- including FILED, RECEIVED, CONTACTED, which in a claim file
# are the actual content. Normalization is a layer over the raw predicate, never
# a gate on extraction.
CANONICAL_PREDICATES = (
    "has_name", "has_email", "has_phone", "has_address", "has_npi", "has_tin",
    "has_ssn", "has_vin", "has_dob",
    "acts_as",            # role: claim-scoped, evidence-backed, NOT a column
    "represents", "affiliated_with", "treats", "employed_by",
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
DDL = r"""
CREATE TABLE IF NOT EXISTS document (
    doc_id        TEXT PRIMARY KEY,
    claim_id      TEXT NOT NULL,
    occurrence_id TEXT,
    text_sha      TEXT NOT NULL,
    n_chars       INTEGER NOT NULL
);

-- Every extracted span, verbatim. THE INVARIANT: text == the document's
-- characters at [start:end], always. In v0 only 33% of mentions satisfied this,
-- because the LLM was asked for character offsets and cannot count characters.
-- Spans are now LOCATED by searching for the model's quoted string, never taken
-- from the model. Measured: 33% -> 100%, at zero cost to recall.
CREATE TABLE IF NOT EXISTS span (
    span_id  TEXT PRIMARY KEY,
    doc_id   TEXT NOT NULL,
    start    INTEGER NOT NULL,
    end      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES document(doc_id)
);

CREATE TABLE IF NOT EXISTS name_mention (
    mention_id  TEXT PRIMARY KEY,
    span_id     TEXT NOT NULL,
    surface     TEXT NOT NULL,
    norm        TEXT NOT NULL,
    entity_type TEXT NOT NULL,        -- ENTITY_TYPES, from the string alone
    found_by    TEXT NOT NULL,        -- union provenance: gliner+llm+sweep
    FOREIGN KEY (span_id) REFERENCES span(span_id)
);

CREATE TABLE IF NOT EXISTS id_mention (
    mention_id TEXT PRIMARY KEY,
    span_id    TEXT NOT NULL,
    kind       TEXT NOT NULL,         -- IDENTIFIER_KINDS
    value_raw  TEXT NOT NULL,
    value_norm TEXT NOT NULL,
    validation TEXT NOT NULL,         -- VALIDATIONS
    FOREIGN KEY (span_id) REFERENCES span(span_id)
);

-- A CLAIM-SCOPED entity. This is the unit of identity the system is confident
-- about: within one claim file there are few parties and names are unambiguous.
CREATE TABLE IF NOT EXISTS local_entity (
    local_id       TEXT PRIMARY KEY,
    claim_id       TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_member (
    local_id   TEXT NOT NULL,
    mention_id TEXT NOT NULL,
    basis      TEXT NOT NULL,         -- MERGE_BASES -- why this mention is here
    confidence REAL,
    PRIMARY KEY (local_id, mention_id)
);

-- Cross-claim identity. NOT A MERGE. A dossier spanning claims is a traversal
-- of these rows at a chosen confidence, recomputed on read -- so a wrong link
-- is one edge to reject, not a cluster to rebuild.
--
-- decided_by / decided_at / reason are the reviewer's. A pipeline run may INSERT
-- rows with status 'auto' or 'review'; it must NEVER modify a row whose status
-- is 'accepted' or 'rejected'. If a reviewer's rejection reappears after the
-- next run, they stop reviewing -- and review is load-bearing here, since 19%
-- of real cross-claim entities cannot be auto-linked on identifiers alone.
CREATE TABLE IF NOT EXISTS identity_link (
    link_id         TEXT PRIMARY KEY,
    local_id_a      TEXT NOT NULL,
    local_id_b      TEXT NOT NULL,
    basis           TEXT NOT NULL,    -- LINK_BASES
    evidence_span_id TEXT,            -- the span that justifies it, when there is one
    confidence      REAL,
    status          TEXT NOT NULL,    -- LINK_STATUS
    decided_by      TEXT,
    decided_at      TEXT,
    reason          TEXT
);

-- Attributes, roles, activities and relationships are ALL assertions. One table,
-- open predicate vocabulary, every row span-grounded.
--
-- `role` lives here rather than as a column on local_entity: a person is not
-- "an attorney", they ACT AS attorney on claim X per this sentence. Role
-- genuinely varies by claim, which is exactly why v0's single entity_class
-- column could never be right.
CREATE TABLE IF NOT EXISTS assertion (
    assertion_id     TEXT PRIMARY KEY,
    subject_local_id TEXT NOT NULL,
    predicate        TEXT NOT NULL,   -- open vocabulary
    object_local_id  TEXT,            -- set for entity-to-entity relations
    object_value     TEXT,            -- set for attribute assertions
    polarity         TEXT NOT NULL DEFAULT 'asserted',
    evidence_span_id TEXT NOT NULL,   -- NOT NULL: no span, no assertion
    method           TEXT NOT NULL,   -- gazetteer | llm_binding | llm_relation
    confidence       REAL,
    source           TEXT NOT NULL DEFAULT 'corpus',
    FOREIGN KEY (evidence_span_id) REFERENCES span(span_id)
);

-- Proof that the text was READ, independent of what was found. Without it,
-- "we found nothing here" and "we never looked here" are indistinguishable.
CREATE TABLE IF NOT EXISTS scan_ledger (
    ledger_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT NOT NULL,
    start      INTEGER NOT NULL,
    end        INTEGER NOT NULL,
    stage      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_span_doc      ON span(doc_id);
CREATE INDEX IF NOT EXISTS ix_member_local  ON local_member(local_id);
CREATE INDEX IF NOT EXISTS ix_local_claim   ON local_entity(claim_id);
CREATE INDEX IF NOT EXISTS ix_link_a        ON identity_link(local_id_a);
CREATE INDEX IF NOT EXISTS ix_link_b        ON identity_link(local_id_b);
CREATE INDEX IF NOT EXISTS ix_assert_subj   ON assertion(subject_local_id);
"""

TABLE_NAMES = (
    "document", "span", "name_mention", "id_mention",
    "local_entity", "local_member", "identity_link", "assertion", "scan_ledger",
)

# Rows a pipeline re-run must never touch. See identity_link above.
HUMAN_OWNED = {"identity_link": ("accepted", "rejected")}
