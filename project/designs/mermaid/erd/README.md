# Entity-intelligence schema — ERDs

Structural reference for where data lives and how tables relate. Companion to
[`../README.md`](../README.md), which shows the *process* (activity diagrams);
this shows the *shape* (data model). Four diagrams, because one 14-table ERD
is not readable, and because two of the stores here genuinely are different
storage models rather than more tables: the graph is in-memory igraph, and the
vector stores are FAISS indices with parquet sidecars.

Read alongside `src/contracts.py` (the DDL, single source of truth),
`src/graph_store.py` (`GraphNode` / `GraphEdge`) and `src/vectorstore.py`
(the `VectorStore` interface).

## Reading these

Standard crow's-foot cardinality (`||` one, `o{` zero-or-many, etc.), with one
deliberate repurposing:

| line | means |
|---|---|
| **solid** (`--`) | a `FOREIGN KEY` clause exists in the DDL — SQLite enforces it (`documents.doc_id`) |
| **dashed** (`..`) | a *logical* reference only — the column exists and is used that way in code, but no `FOREIGN KEY` clause declares it |

That split is the main finding of this pass: **most references in this schema
are logical, not enforced.** `src/contracts.py` declares exactly **5**
`FOREIGN KEY` clauses in the whole DDL. Across the 28 relationship lines drawn
in these four diagrams, 5 are solid and 23 are dashed. The vector stores in
ERD 4 can only ever be dashed — they are not SQL, so the ids joining them to
`mentions` and `documents` are a convention held up by code alone. This appears to be
unconsidered rather than deliberate — the module docstring's stated design
principle is an
append-only, immutable-by-convention log, which doesn't obviously require
skipping FK enforcement, and SQLite's bulk-insert path this pipeline uses
would not be meaningfully slower with `PRAGMA foreign_keys=ON`. Whether to
tighten this is an open question, not a decision made here.

## Diagrams

1. **[Evidence layer](01-evidence-layer.mermaid)** — `documents`, `segments`,
   `mentions`, `assertions`, `identifier_observations`, `coref_links`,
   `scan_ledger`. Everything Layer 0/1 writes.
2. **[Identity layer](02-identity-layer.mermaid)** — `same_as_edges`,
   `entity_snapshot`, `entities`, `entity_members`, `entity_versions`,
   `entity_attributes`, `dossiers`. Everything Layer 2/3 writes.
   `mentions` reappears as the bridge table, trimmed to its key column —
   see diagram 1 for its full attribute list.
3. **[Graph store](03-graph-store.mermaid)** — `GraphNode` / `GraphEdge`.
   **Not SQL.** An in-memory igraph structure, serialized separately
   (`store/claims_graph.pkl`), built by `build_graph.py` by reading FROM the
   tables above. Shown here because it answers the same "where does data
   live" question, not because it belongs in the SQLite ERD.
4. **[Vector stores](04-vector-stores.mermaid)** — `mentions.faiss` and
   `chunks.faiss`. **Not SQL either.** FAISS `IndexFlatIP` plus a parquet
   metadata sidecar, keyed by the SQL layer's own ids (`mention_id`,
   `chunk_id`), which is the only thing joining them to the tables. Both were
   missing from this reference until the vector layer was rewired — see
   [diagram 09](../09-vector-layer.mermaid) for the process view and for what
   was wrong with them.

## Notable shapes, while building this

- **The vector stores have no schema enforcement whatsoever.** Metadata is a
  JSON blob per row in a parquet sidecar (`FaissVectorStore._meta`), so a
  missing `claim_id` on a chunk vector would not fail at write time — it would
  fail as a silently unfilterable row at query time, which is how the Layer 4
  scope guarantee could be undermined without any error. The keys are
  documented in ERD 4 because nothing in the code declares them.
- **`entity_snapshot` has no declared primary key at all** — not even a
  composite one. Consistent with its own comment ("materialized view of
  identity at one operating threshold"): it's meant to be recomputed
  wholesale per threshold sweep, not addressed row-by-row. Still worth
  knowing before writing anything that assumes row identity here.
- **`identifier_observations.validated` is a bare 0/1**, collapsing the
  validation-*strength* distinction the gazetteer layer now computes
  (`checksum` / `format` / `none` — see diagram 04 in the parent folder).
  The richer signal exists in `gazetteers.GazetteerHit.validation` at
  extraction time and is not currently carried into this column.
- **Graph node kinds: 7 declared, 5 ever constructed.** `NODE_KINDS` in
  `graph_store.py` includes `event` and `allegation`; `build_graph.py` never
  emits either. Same pattern as the old `SEGMENT_KINDS` finding — a
  vocabulary wider than what the code actually produces.
- **`ORG_CLASSES = {"repair_shop"}` — only one of the five `entity_class`
  values is treated as an organization node.** `medical_provider` and
  `attorney` entities become `party` nodes (the same graph kind as a person),
  not `organization`. Whether that's intentional — a solo practitioner and a
  hospital both filed under `medical_provider` with no way to tell them apart
  as graph node kinds — is worth confirming; it isn't obviously right or
  obviously wrong, but it is easy to miss reading `build_graph.py` alone.
- **`entity_class` sits on three different tables** (`mentions`, `entities`,
  and implicitly `dossiers` via join) and means something slightly different
  on each: per-mention guess, per-entity rollup, and profile-rendering input.
  The proposed `entity_type` / `role` split (parent folder, diagram 06) would
  touch `mentions.entity_class` and `entities.entity_class` identically, so
  fixing it once fixes it everywhere this value is read.

## SQL → graph provenance

What `build_graph.py` actually reads to build each node/edge kind — the
mapping ERD 3 can't show on its own, since it only has the two dataclasses:

| graph object | kind | built from |
|---|---|---|
| node | `party` / `organization` | one per row in `entities`, split by `entity_class ∈ ORG_CLASSES` |
| node | `claim` | distinct `claim_id` values seen across resolved entities |
| node | `occurrence` | distinct `occurrence_id` values, joined from `documents` |
| node | `identifier` | one per distinct `(kind, value_norm)` in `identifier_observations` — **including orphans**, i.e. rows with `subject_mention_id IS NULL` |
| edge | `PART_OF` | claim node → occurrence node (containment) |
| edge | `PARTY_TO` | entity node → claim node, carrying `doc_id` + `span` provenance |
| edge | role edges (`REPRESENTED_BY`, `TREATED_BY`, `ADJUSTED_BY`, `REPAIRED_BY`, …) | entity → entity, anchored on the claim's `claimant`-class entity; predicate chosen from `entity_class` via `ROLE_PREDICATE` |
| edge | `HAS_IDENTIFIER` | identifier node → owning entity, only when `identifier_observations.subject_mention_id` resolves to an entity; confidence 0.95 if `validated` else 0.7 |
| edge | `OBSERVED_ON` | identifier node → claim node, **only for orphan identifiers** — the one path that lets a later query still attribute an unbound phone/email to a claim |

Note this table is downstream of the proposed `entity_type`/`role` split: role
edges are chosen from `entity_class` today, so once that field splits, the
role-edge predicate should read from `role`, not `entity_type`.

### ERD 1 — Evidence layer (documents, segments, mentions, assertions)

Source: [`01-evidence-layer.mermaid`](01-evidence-layer.mermaid)

```mermaid
---
title: "ERD 1 — Evidence layer (documents, segments, mentions, assertions)"
---
erDiagram
  DOCUMENTS {
    TEXT doc_id PK
    TEXT claim_id "from filename, never note text"
    TEXT occurrence_id "from client occurrence table"
    TEXT category "stored, may be NULL"
    TEXT category_implied "content-inferred; currently always NULL, see note"
    INTEGER n_chars
    INTEGER seq_in_claim
    TEXT created_ts
  }

  SEGMENTS {
    TEXT segment_id PK
    TEXT doc_id FK
    TEXT kind "body | quoted — see note"
    REAL boilerplate_score "0..1, advisory only"
    TEXT casing_regime "mixed | upper | lower | sparse"
    INTEGER case_informative "0 = casing carries no signal"
    INTEGER char_start
    INTEGER char_end
    TEXT template_fingerprint "label-sequence hash, form-like segments"
    TEXT dup_group_id "near-duplicate group"
    INTEGER is_canonical_dup
  }

  MENTIONS {
    TEXT mention_id PK
    TEXT doc_id FK
    TEXT segment_id "logical ref, no FK clause"
    TEXT entity_class "guessed when unmatched — see note"
    TEXT surface "raw extracted text"
    TEXT norm_surface
    INTEGER char_start
    INTEGER char_end
    TEXT extractor "token_ner+gazetteer+llm, any combo"
    TEXT dup_group_id
    INTEGER inside_quoted
    REAL boilerplate_score "carried from containing segment"
  }

  ASSERTIONS {
    TEXT assertion_id PK
    TEXT subject_mention_id FK
    TEXT predicate "open vocabulary, canonical forms preferred"
    TEXT object_value_raw
    TEXT object_value_norm
    TEXT object_mention_id "logical ref, relation predicates only"
    TEXT polarity "asserted|negated|alleged|reported|retracted"
    TEXT effective_from
    TEXT effective_to
    TEXT recorded_date
    REAL temporal_conf
    TEXT source_doc_id "logical ref, no FK clause"
    INTEGER source_span_start "the EVIDENCE location, not the subject's"
    INTEGER source_span_end
    INTEGER grounded
    TEXT extractor
    TEXT pass_id
    REAL confidence
  }

  IDENTIFIER_OBSERVATIONS {
    INTEGER obs_id PK
    TEXT doc_id "logical ref, no FK clause"
    INTEGER char_start
    INTEGER char_end
    TEXT kind "phone|email|address|npi|tin|ssn|vin"
    TEXT value_raw
    TEXT value_norm
    TEXT subject_mention_id "logical ref; NULL = orphan, kept anyway"
    INTEGER validated "bare bool; see validation-strength note"
    TEXT extractor
  }

  COREF_LINKS {
    INTEGER link_id PK
    TEXT doc_id "logical ref, no FK clause"
    INTEGER anaphor_start
    INTEGER anaphor_end
    TEXT anaphor_text
    TEXT anaphor_kind "pronoun | descriptor"
    INTEGER antecedent_start
    INTEGER antecedent_end
    TEXT antecedent_surface
    TEXT antecedent_mention_id "logical ref, no FK clause"
    TEXT backend
    REAL confidence
  }

  SCAN_LEDGER {
    INTEGER ledger_id PK
    TEXT doc_id FK
    INTEGER char_start
    INTEGER char_end
    TEXT extractor
    TEXT pass_id
  }

  DOCUMENTS ||--o{ SEGMENTS       : "FK doc_id"
  DOCUMENTS ||--o{ MENTIONS       : "FK doc_id"
  DOCUMENTS ||--o{ SCAN_LEDGER    : "FK doc_id"
  DOCUMENTS ||..o{ IDENTIFIER_OBSERVATIONS : "logical doc_id"
  DOCUMENTS ||..o{ COREF_LINKS    : "logical doc_id"
  SEGMENTS  ||..o{ MENTIONS       : "logical segment_id"
  MENTIONS  ||--o{ ASSERTIONS     : "FK subject_mention_id"
  MENTIONS  ||..o{ ASSERTIONS     : "logical object_mention_id (relation predicates)"
  DOCUMENTS ||..o{ ASSERTIONS     : "logical source_doc_id"
  MENTIONS  ||..o{ IDENTIFIER_OBSERVATIONS : "logical subject_mention_id (nullable)"
  MENTIONS  ||..o{ COREF_LINKS    : "logical antecedent_mention_id (nullable)"
```

### ERD 2 — Identity layer (resolution, entities, attributes, dossiers)

Source: [`02-identity-layer.mermaid`](02-identity-layer.mermaid)

```mermaid
---
title: "ERD 2 — Identity layer (resolution, entities, attributes, dossiers)"
---
erDiagram
  MENTIONS {
    TEXT mention_id PK
    TEXT entity_class "full attribute list — see ERD 1"
  }

  ASSERTIONS {
    TEXT assertion_id PK "full attribute list — see ERD 1"
  }

  SAME_AS_EDGES {
    INTEGER edge_id PK
    TEXT mention_id_a "logical ref, no FK clause"
    TEXT mention_id_b "logical ref, no FK clause"
    REAL probability "calibrated Splink score, NOT a decision"
    REAL match_weight
    TEXT backend
    TEXT suppressed_reason "non-NULL = excluded from clustering"
  }

  ENTITY_SNAPSHOT {
    TEXT entity_id "logical ref; no PK declared at all"
    TEXT mention_id "logical ref, no FK clause"
    REAL threshold "identity is a VIEW at this T, not a merge"
  }

  ENTITIES {
    TEXT entity_id PK
    TEXT entity_class "proposed split — see note"
    TEXT canonical_name
    TEXT version_id "logical ref, current-version pointer"
    INTEGER n_mentions
  }

  ENTITY_MEMBERS {
    TEXT entity_id PK "part of composite PK"
    TEXT mention_id PK "part of composite PK"
    TEXT version_id PK "part of composite PK"
  }

  ENTITY_VERSIONS {
    TEXT version_id PK
    TEXT entity_id "logical ref, no FK clause"
    TEXT cause "initial | merge | split | adjudicated_link"
    TEXT parent_entity_ids "JSON list — multi-valued, not a normal FK"
    TEXT created_ts
  }

  ENTITY_ATTRIBUTES {
    TEXT attr_id PK
    TEXT entity_id FK
    TEXT attribute "predicate-derived name"
    TEXT value_raw
    TEXT value_norm
    TEXT valid_from "real-world validity window"
    TEXT valid_to
    TEXT known_from "system-knowledge window"
    TEXT known_to
    TEXT tier "survivorship tier"
    TEXT polarity
    INTEGER conflict_flag
    TEXT source_assertion_id "logical ref, no FK clause"
  }

  DOSSIERS {
    TEXT entity_id PK "also the 1:1 ref target, no FK clause"
    TEXT dossier_json
  }

  MENTIONS       ||..o{ SAME_AS_EDGES    : "logical mention_id_a / mention_id_b"
  MENTIONS       ||..o{ ENTITY_SNAPSHOT  : "logical mention_id"
  MENTIONS       ||..o{ ENTITY_MEMBERS   : "logical mention_id"
  ENTITIES       ||..o{ ENTITY_SNAPSHOT  : "logical entity_id"
  ENTITIES       ||--o{ ENTITY_ATTRIBUTES : "FK entity_id"
  ENTITIES       ||..o{ ENTITY_MEMBERS   : "logical entity_id"
  ENTITIES       ||..o{ ENTITY_VERSIONS  : "logical entity_id"
  ENTITIES       ||..o| DOSSIERS         : "logical 1:1, entity_id"
  ENTITY_VERSIONS ||..o{ ENTITY_MEMBERS  : "logical version_id"
  ENTITIES       ||..o| ENTITY_VERSIONS  : "logical version_id = current version"
  ASSERTIONS     ||..o{ ENTITY_ATTRIBUTES : "logical source_assertion_id (from ERD 1)"
```

### ERD 3 — Graph store: a different storage model, fed BY the SQL layer

Source: [`03-graph-store.mermaid`](03-graph-store.mermaid)

```mermaid
---
title: "ERD 3 — Graph store: a different storage model, fed BY the SQL layer"
---
erDiagram
  GRAPH_NODE {
    TEXT node_id PK "entity_id | CLAIM::x | OCC::x | ID::kind::value"
    TEXT kind "party|organization|identifier|claim|occurrence — see note"
    TEXT label "entity_class, or identifier kind"
    TEXT name
    SET claim_ids "every claim this node touches"
    SET occurrence_ids
    DICT attrs "e.g. n_mentions"
  }

  GRAPH_EDGE {
    TEXT src "logical ref -> GRAPH_NODE.node_id"
    TEXT dst "logical ref -> GRAPH_NODE.node_id"
    TEXT predicate "open vocabulary; BANNED_PREDICATES rejected — see note"
    TEXT claim_id "a PROPERTY, not a partition key"
    TEXT occurrence_id
    TEXT doc_id "provenance"
    TUPLE span "provenance: (char_start, char_end)"
    REAL confidence
    TEXT polarity
  }

  GRAPH_NODE ||..o{ GRAPH_EDGE : "logical src"
  GRAPH_NODE ||..o{ GRAPH_EDGE : "logical dst"
```

### ERD 4 — Vector stores: a third storage model, keyed to the SQL layer

Source: [`04-vector-stores.mermaid`](04-vector-stores.mermaid)

```mermaid
---
title: "ERD 4 — Vector stores: a third storage model, keyed to the SQL layer"
---
erDiagram
  MENTIONS {
    TEXT mention_id PK "see ERD 1 for full attributes"
    TEXT entity_class
    TEXT doc_id
  }

  MENTION_VECTOR {
    TEXT str_id PK "= mentions.mention_id"
    INT int_id "FAISS internal id, from the sidecar parquet"
    VECTOR vector "768-dim, L2-normalized -> cosine = inner product"
    TEXT entity_class "filter key: a person never blocks with a repair shop"
    TEXT doc_id
    TEXT claim_id
    TEXT norm_surface
  }

  CHUNK_VECTOR {
    TEXT str_id PK "= chunk_id, from chunking.chunk_corpus"
    INT int_id
    VECTOR vector "768-dim, L2-normalized"
    TEXT claim_id "filter key: the Layer 4 scope boundary"
    TEXT occurrence_id
    TEXT doc_id
    INT char_start
    INT char_end
    TEXT text "the chunk itself, so retrieval needs no second read"
  }

  SAME_AS_EDGES {
    INT edge_id PK
    TEXT mention_id_a
    TEXT mention_id_b
    REAL probability
    TEXT blocked_by "which rule proposed it; 'emb_bucket' = the vector lane"
    TEXT suppressed_reason
  }

  DOCUMENTS {
    TEXT doc_id PK
    TEXT claim_id
  }

  MENTIONS ||..|| MENTION_VECTOR : "one vector per mention (logical, by id)"
  MENTION_VECTOR }o..o{ MENTION_VECTOR : "k-NN neighbours -> emb_bucket -> candidate pairs"
  MENTION_VECTOR ||..o{ SAME_AS_EDGES : "proposes pairs Splink then scores"
  DOCUMENTS ||..o{ CHUNK_VECTOR : "chunked into (logical, by doc_id)"
```
