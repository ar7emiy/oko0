# First-principles audit: claims-note intelligence POC

**Status:** Proposed — findings only; no production code was changed by this audit.  
**Date:** 2026-09-01  
**Decision required:** agree the target architecture and the evidence plan before further implementation.

## Executive finding

The current repository has a promising *evidence spine*: raw-character spans,
explicit identifier observations, non-destructive resolution, an embedding
candidate lane, and a claim-scoped retrieval design. Those are sound starting
principles.

It is **not yet a production-shaped claims intelligence system**. It is a
synthetic-data POC with several production-shaped components. The largest gap
is not model quality: the only code that extracts open subject-predicate-object
relations is a research notebook and is not invoked by operational ingestion or
graph construction. Meanwhile the graph manufactures role edges from a closed,
synthetic-oriented five-class classifier. That reverses the desired evidence
flow: inferred labels create relationships instead of grounded relationships
creating knowledge.

The right next move is not to tune thresholds or add more heuristics. It is to
make the intake contract, evidence/relationship path, and evaluation contract
real before using real notes to judge model performance.

The companion process map is
[`mermaid/11-evidence-first-target.mermaid`](mermaid/11-evidence-first-target.mermaid).

## What a real claim file requires from the architecture

This audit treats a claim note as one time-stamped item in a regulated claim
file, not as a free-standing paragraph. NAIC guidance defines the file broadly:
it can include adjuster logs, investigation material, correspondence, medical
records, police reports, bills, estimates, payment records and other documents
used to support claim handling. It requires enough detail to reconstruct the
inception, handling and disposition of the claim.

That leads to five non-negotiable design implications:

1. **Source metadata is evidence, not decoration.** Claim, occurrence, note
   identity, source-system identifier, document/note type, author/actor,
   authored/entered/received timestamps, line of business, and document
   version must arrive from the claims system. None should be guessed from
   prose.
2. **The system must preserve who said what, when, and with what certainty.**
   A claim note can report a claimant allegation, a provider record, an adjuster
   conclusion, or a retraction. These are different evidentiary states, even
   when they use the same words.
3. **A relationship must have direct evidence.** “Dr. A appears on the same
   claim as B” does not prove Dr. A treated B. Relationships may be proposed,
   but their source span, extraction method, confidence, modality and review
   state must remain visible.
4. **Identity is probabilistic and longitudinal.** People, firms, providers,
   vehicles and phone numbers recur and change. A merge is a reviewable
   hypothesis, not a destructive rewrite.
5. **The input carries sensitive information.** Names, SSNs, health details,
   addresses and claim narratives must be managed as sensitive data across the
   database, cache, vector indexes, logs and model-provider boundary.

Sources: [NAIC Market Regulation Handbook, Claims chapter](https://content.naic.org/sites/default/files/publication-market-reg-hb.pdf),
[NAIC Model 910, claim-file definition](https://content.naic.org/sites/default/files/inline-files/MDL-910.pdf),
[NAIC Model 903, file documentation](https://content.naic.org/sites/default/files/model-law-903.pdf).

## Scope and method

This is a static, first-principles audit of the active code and its design
documents. It did not use client notes, make API calls, or alter pipeline code.

I traced the operational path:

`ingest.deliver -> profiling.run -> pipeline_v2.run -> embed_index.run ->
incremental/entity_resolution -> profiles -> build_graph/build_chunk_index`

and independently traced the relation path:

`relations.extract_relations -> bind_to_mentions`

The latter has callers only in `notebooks/20_relation_extraction.py`; it is not
called by the operational path. Findings below distinguish code facts from
proposals.

## Inventory: what is genuinely general vs. what is fitting the fixture

| Component | Assessment | Why |
|---|---|---|
| External claim/occurrence identity | **Correct principle, incomplete interface** | The code correctly stopped extracting claim IDs from prose. But it accepts missing metadata as `UNKNOWN`, and `deliver()` stores ad-hoc JSON instead of validating an authoritative client manifest. |
| Absolute source spans and evidence-grounded assertions | **Keep** | General, auditable, and essential for reconstructing a claim-handling fact. |
| Content hashing / idempotent mention IDs | **Keep, extend** | Content-derived IDs prevent accidental duplicate inserts. The raw document itself still lacks an immutable version/fingerprint/run record. |
| MinHash near-duplicate detection | **Keep as advisory** | Language- and carrier-agnostic enough to flag repeated quoted/template content. It must not decide whether a mention is true. |
| Overlapping chunks | **Keep as a measured mitigation** | Overlap is a standard answer to boundary loss. The current 300-word/50% values are unvalidated operating values, not universal constants; real note lengths and the actual model context window should determine them. |
| GLiNER candidate NER | **Keep as a baseline, evaluate locally** | A zero-shot NER model with descriptive labels is a credible high-recall candidate generator, not a proof of claims-domain accuracy. GLiNER was designed for arbitrary entity labels, but its paper does not establish accuracy on this client's notes. [GLiNER paper](https://arxiv.org/abs/2311.08526) |
| Regex extraction of e-mail, phone and check-digit NPI | **Keep, but narrow its claim** | These are structural patterns, not corpus phrase matching. An NPI check digit is meaningful validation. Email/phone syntax is only format evidence; address, TIN, SSN, policy, CPT and ICD patterns are jurisdiction/line-of-business dependent and currently much weaker. |
| Boilerplate score | **Safe only because advisory** | The English cue list is not general. It does not destroy evidence today, so it is acceptable as an observed feature until actual carrier formats are sampled. |
| `quoted` detection with a `>` prefix | **Narrow heuristic** | It catches conventional e-mail forwarding but not native claim-system quote/reply formats, pasted correspondence, or imported documents. Its value must be measured per source system. |
| Five `entity_class` values | **Must be replaced** | It conflates entity type with claim role and forces unrecognized people into `claimant` and organizations into `medical_provider`. |
| Role/context word lists and `@ourinsco.com` | **Synthetic/carrier-specific; remove from fact creation** | They encode one imagined carrier and a handful of generated vocabulary patterns. They are currently used to persist entity classes and manufacture graph relationships. |
| Open predicate normalization | **Keep with governance** | Unknown predicates survive rather than being dropped. Normalization must be versioned and measured, not silently reinterpreted. |
| Relation extractor | **Promising but disconnected** | It is the correct direction—open predicates plus verbatim evidence—but it is a research-only function at present. |
| Embeddings as an ER candidate lane | **Correct shape, unvalidated operating point** | Candidate generation increases recall without making a merge. The current `0.29` floor came from 14 hand-labelled mentions; it cannot be treated as production calibration. |
| Splink/EM linkage and threshold-derived identity | **Keep as a mechanism, recalibrate** | Blocking is the main determinant of what can be linked, and model training/thresholds need a representative labelled set. [Splink blocking guidance](https://moj-analytical-services.github.io/splink/topic_guides/blocking/blocking_rules.html) |
| Vector retrieval constrained to a claim | **Keep** | It is a useful evidence-retrieval layer. It is not a substitute for an evidence graph or a permission model. |

## Findings, prioritized

### P0 — evidence correctness: open relations do not reach the dataset or graph

**Evidence in code**

- `src/relations.py` can extract a grounded, open-vocabulary relation and bind
  it to mentions.
- `rg` finds its only callers in `notebooks/20_relation_extraction.py`.
- `src/pipeline_v2.py` persists only name, identifier and keyword-allegation
  assertions.
- `src/build_graph.py` never reads `assertions`. It emits `REPRESENTED_BY`,
  `TREATED_BY`, `REPAIRED_BY`, and `ADJUSTED_BY` solely from a party's inferred
  `entity_class` and co-presence on the claim.

**Why this fails the product goal**

The stated goal is an evidence-grounded knowledge map. Current graph role edges
are not facts extracted from text. For example, an attorney mentioned in a
status note becomes `claimant -> REPRESENTED_BY -> attorney` even if the note
says the attorney represents a different party, withdrew, or is opposing
counsel. Conversely, a real `witnessed`, `referred_to`, `employed_by`, or
`supervises` relation can be extracted in notebook 20 but is never persisted.

**Proposal**

Make the assertion table the evidence ledger for all semantic relations:

`raw span -> relation candidate -> mention/entity binding -> assertion -> graph edge`

The graph builder should promote only accepted, grounded assertions. Any
derived relationship needed for navigation must be explicitly typed as
`inferred_from_co_presence` (or similar), carry the rule/version/confidence,
and be off by default in factual views. Do not build this until the input
contract and relation evaluation set below exist.

### P0 — entity type and claim role are incorrectly fused

**Evidence in code**

- `contracts.ENTITY_CLASSES` is a closed five-value tuple.
- `pipeline_v2.LABEL_TO_CLASS` maps generic `person` to `claimant` and generic
  `organization` to `medical_provider`.
- `_classify()` adds carrier-specific domain and cue-word rules, then falls back
  to that mapping.
- `entity_resolution.cannot_link_reason()` and `build_graph.ROLE_PREDICATE`
  consume those classes as structural truth.

**Why this fails on real claims**

Claim files can name insureds, claimants, drivers, passengers, witnesses,
employers, landlords, adjusters, carrier personnel, defense and plaintiff
counsel, public adjusters, investigators, vendors, facilities, physicians,
subrogation counterparts, and organizations with several roles. “Person” and
“claimant” are not alternatives; one is an entity type and the other is a
claim-scoped role. Forcing unknown people into claimant artificially makes
synthetic evaluation look coherent and makes real graph edges wrong.

**Proposal**

Replace the single field in a future build with:

- a small structural `entity_type` (`person`, `organization`, `asset`,
  `claim`, `event`, `identifier`, `unknown`), used only for carefully justified
  incompatibility checks; and
- an open, claim-scoped `role assertion` with its own evidence, polarity,
  temporal scope and confidence (`witness`, `claimant`, `opposing_counsel`,
  etc.).

This is not adding an ever-larger closed taxonomy. It separates the genuinely
closed question (what sort of thing is this?) from the open question (what role
does it play in this claim at this time?).

### P0 — real-note intake, provenance, and versioning are absent

**Evidence in code**

- `profiling.ingest_documents()` reads only a `doc_index.json` convenience map;
  a missing entry becomes `claim_id="UNKNOWN"`.
- `ingest.deliver()` copies a file by name and can overwrite a prior file.
- `documents.created_ts`, `seq_in_claim`, and all document source metadata are
  written as `None`.
- There is no raw-document fingerprint, source-system ID, document version,
  ingestion batch/run ID, model/prompt version, or immutable processing log.

**Why this matters**

The system cannot reconstruct the actual chronology of handling, distinguish an
updated note from a new note, reliably order events, or prove which version of
a note/model produced a claim. This is incompatible with the auditability
expected of a claim file even before considering regulations.

**Proposal**

Define and validate a source manifest before ingesting any client file. At
minimum, require `source_note_id`, `note_id`, `claim_number`, `occurrence_id`,
`document_type`, `source_system`, `created_at`, `entered_at` when distinct,
`author/actor` when available, `line_of_business`, `file_name`, and a content
hash/version. Reject or quarantine an input with missing required structural
metadata; never convert it to a working `UNKNOWN` claim. Persist one immutable
processing-run record containing configuration/model/prompt versions and input
hashes.

### P0 — sensitive-data boundary is not designed

The POC stores raw notes, raw identifiers, local SQLite, JSON cache, FAISS
metadata and an `igraph` pickle. There is no encryption, role-based access,
redaction/tokenization policy, retention policy, source-to-model data boundary,
or audit trail of read access. This is a design gap, not a criticism of using a
local POC. It must be designed before real notes enter the system.

NIST advises a context-based assessment of PII, appropriate safeguards, and
minimization of collection/retention. [NIST SP 800-122](https://csrc.nist.gov/pubs/sp/800/122/final)
is a useful baseline; client counsel/security must determine the applicable
insurance, privacy and health-information obligations.

### P1 — casing detection is contradicted by the persistence filter

`casing.py` correctly detects that capitalization may be uninformative, but
`pipeline_v2._is_plausible_name()` then rejects a normal name unless it has two
capitalized tokens (or begins with `dr`). This means a GLiNER/LLM mention such
as `john smith`, `JOHN SMITH`, OCR-distorted text, many non-English forms, or a
single-token legal entity can be filtered after detection. The filter also
contains English header terms.

This is not a general linguistic safeguard. It is a high-precision shape rule
that may be useful as a *review score* or a candidate-ranking feature after it
is measured, but must not be an unmeasured hard persistence gate. The casing
detector is therefore currently cosmetic for the main loss mode it was meant to
address.

### P1 — regex value is uneven and must be described honestly

The deterministic structured extractors are not all alike.

- **Strong/general enough to retain:** exact e-mail syntax, normalized phone
  syntax, and U.S. NPI check-digit validation. They find material that a
  semantic model can miss and can be independently verified.
- **Conditional:** dates, monetary amounts, ICD/CPT patterns and policy numbers
  are useful candidates only with line-of-business, country and source-system
  context. The current formats are largely U.S.-centric.
- **Weak / not a validator:** SSN and TIN format matching, generic address
  matching, ZIP matching and the current contextual code cues. They may be
  retained as extracted strings with a low-confidence source label, but should
  not drive merges or facts absent authoritative reference data.
- **Synthetic/carrier-specific and unsuitable as fact logic:** role cue lists,
  organization suffix lists, `@ourinsco.com`, phrase lists such as “trial group”
  and “car care,” and the keyword allegation detector.

The right production pattern is a small, jurisdiction-aware identifier parser
plus pluggable client reference-data adapters (provider registry, party roster,
carrier directory, policy/claim system). Reference data can strengthen an
already extracted candidate; it should never be silently mistaken for proof in
the note.

### P1 — NER label coverage is narrower than the product scope

The current NER schema permits 14 labels, but `pipeline_v2` persists only
name-like labels and a subset of identifiers. It discards model candidates for
`medical_condition`, `procedure`, and `monetary_amount`; it does not operationally
handle vehicles/VINs despite the synthetic configuration mentioning VIN; and it
has no first-class claimant/insured policy, coverage, loss location, payment,
reserve, task/deadline, document, event, or organization-directory concepts.

That does not mean every one of these needs to become a graph node. It means the
system needs an explicit product-specific evidence model before deciding what
to retain, relate, summarize, or deliberately ignore. A candidate that is
discarded is not a negative finding; it is an unmeasured blind spot.

### P1 — ER is a sound mechanism with synthetic calibration and unsafe cluster semantics

Splink-style blocking and probabilistic scoring are appropriate mechanisms.
Splink itself emphasizes that blocking controls which candidate pairs can be
considered; missed blocking candidates are a hard recall ceiling. The current
embedding lane correctly *proposes* pairs rather than merging them directly.

However, the operating assumptions are not production-ready:

- `ER_LINK_THRESHOLD=0.45`, deterministic-recall `0.7`, embedding floor `0.29`,
  top-k `25`, and max bucket `60` were calibrated on synthetic or tiny
  hand-written probes.
- the comparison model treats organization surfaces as person first/last names;
  the latest run already shows organization fragmentation;
- `last_name` blocking is too permissive for many real surnames and dangerous
  when organization labels are misclassified;
- union-find components allow transitive chains, so several plausible edges can
  create an implausible cluster;
- no three-way operating policy exists: auto-link, review candidate, and
  leave-unlinked; and
- no representative holdout measures pair precision/recall, blocking recall,
  cluster quality, and error by source, line, entity type and time.

Use per-entity-type comparison strategies after the type/role split, calibrate
on held-out client annotations, and introduce a review band. A production score
is not a fact merely because it clears a global number. This aligns with the
need to measure performance under deployment-like conditions and document
human oversight. [NIST AI RMF](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)

### P1 — coreference is both unmeasured and currently non-operative for facts

`coref.py` retains a good non-destructive shape (links plus raw offsets), but
its default `auto` backend silently falls back to a nearest compatible mention
when FastCoref is unavailable. That conflicts with the repository's stated
no-silent-fallback principle. Its descriptor map is a closed English insurance
list, and the operational relation path does not use `resolved_view()` or
`coref_links` to bind relation arguments. Coreference may be valuable, but it
should remain an explicit, measured enrichment until it is integrated with
relation persistence and evaluated on real note chronology.

### P1 — the current graph is an index, not yet a trustworthy knowledge graph

The graph data structure can carry open predicates, span provenance, polarity
and confidence. That is good. The builder does not yet use that capability for
semantic assertions. It also treats only `repair_shop` as an organization,
which makes firms and medical facilities parties; this is a direct consequence
of the type/role conflation.

The desired graph should be an **evidence graph**:

- stable nodes for claims, source documents, evidence spans, mentions,
  identifiers and resolved entities;
- edges from assertions whose provenance and modality are preserved;
- optional inferred/navigation edges in a visibly separate layer; and
- query-time claim scope plus access/purpose controls.

The vector store is complementary: it retrieves semantically relevant source
text. It should not invent facts or replace relationship storage.

### P2 — temporal and lifecycle claims in the schema are not implemented

The contracts/repository comments describe immutable append-only entities,
versions and bitemporal attributes. The active code deletes and recreates
resolution/profile tables on full runs; no caller writes `entity_versions`,
and document timestamps/effective dates are mostly unset. This is a mismatch
between the design narrative and actual behavior, inherited from an earlier
architecture.

For the POC, the honest state is “current derived snapshot plus source evidence.”
Do not claim bitemporal entity history until source timestamps, change events,
model/run versions, and supersession semantics are implemented and tested.

## Proposed target architecture (no implementation in this branch)

### 1. Intake and immutable evidence ledger

Receive a validated manifest and content-addressed source documents. Store
structural metadata separately from textual claims. Preserve source order and
versions. Quarantine invalid records with reasons.

### 2. Candidate extraction, not early interpretation

Run general NER/structured parsers over all text; preserve candidates with raw
spans and extractor/version/confidence. Use regexes only where their semantic
scope is explicit. Do not let role assumptions discard an extracted mention.

### 3. Mention typing and role assertions

Classify structural entity type separately from open, claim-scoped role
assertions. Reference data may enrich or corroborate these assertions, but raw
text evidence remains accessible.

### 4. Grounded relation/event extraction

Extract factual triples with verbatim evidence and modality. Bind directly when
possible; retain unbound candidates in a reviewable queue rather than converting
them into graph facts or dropping them.

### 5. Type-specific identity resolution

Use structured identifiers, normalized surface comparisons, reference data and
embeddings only to generate or score candidates. Apply calibrated auto/review/
no-link bands and cluster-level safeguards. Re-run calibration when input
source, model, data distribution or matching policy changes.

### 6. Evidence graph and retrieval

Promote grounded assertions to graph edges. Keep derivations separate. Build
vector retrieval over source chunks and retrieve it under claim/purpose scope.
Every answer or visualization should link back to the raw document span.

### 7. Measurement and human correction loop

Create a stratified client-note evaluation set before tuning: source system,
line of business, note type, chronology, capitalization/OCR quality, quoted
text, entity type, identifier type, uncommon roles, negation/retraction and
hard identity variants. Measure each stage independently and end-to-end. Store
review outcomes as labelled evidence, with a governed process for future model
or policy updates.

## Decision gates before implementation

| Gate | Required evidence | What it unlocks |
|---|---|---|
| G0: data contract | Client metadata manifest, source-system sample, retention/access decision, documented permissible model-provider path | Safe intake design |
| G1: representative sample | De-identified/approved notes across source/line/note types and a frozen annotation guide | Real baseline measurement |
| G2: evidence path | Demonstrated span-grounded relation persistence and graph promotion, with no class-derived factual edges | Knowledge-graph POC |
| G3: identity evaluation | Held-out blocking, pair, cluster and review-band metrics by entity type | ER operating policy |
| G4: stakeholder trace | One arriving note shown from source/version through final dataset, with every final fact traceable | High-fidelity product demo |

## Recommended implementation order after agreement

1. Design G0/G1 intake and data-governance contracts; do **not** tune models yet.
2. Replace type/role conflation and make the actual relation/assertion path
   operational.
3. Build the evidence graph from assertions and visibly demote derived edges.
4. Establish the real-note benchmark, then calibrate NER, extraction, ER and
   coreference stage by stage.
5. Add the review workflow and monitoring/change controls.

## Research basis and limits

- NAIC materials support the claim-file reconstruction and heterogeneous-source
  requirements; implementation must be tailored to the carrier, jurisdiction,
  line of business and contractual obligations.
- GLiNER supports the choice of a flexible candidate NER model, not a claim of
  accuracy on these notes. [GLiNER](https://arxiv.org/abs/2311.08526)
- Splink supports candidate blocking and matching against existing records, not
  the current synthetic thresholds. [Splink blocking](https://moj-analytical-services.github.io/splink/topic_guides/blocking/blocking_rules.html)
  and [new-record matching API](https://moj-analytical-services.github.io/splink/api_docs/inference.html)
  describe the mechanism.
- NIST guidance supports the need for documented data suitability, human
  oversight, evaluation under deployment-like conditions, and monitoring; it
  does not prescribe this exact architecture. [NIST AI RMF](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)
  and [NIST SP 800-122](https://csrc.nist.gov/pubs/sp/800/122/final).

No inference in this document should be read as a claim of measured performance
on client notes. That measurement begins only after G0 and G1.
