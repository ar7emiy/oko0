# Full-system architecture audit

**System:** claim-note entity intelligence and evidence-grounded retrieval

**Audit branch:** `audit-full-system-architecture`

**Disposition:** findings and target architecture only; no implementation code was changed

**Companion diagrams:** [client-tunable reference architecture](mermaid/12-client-tunable-reference-architecture.mermaid), [search and context routing](mermaid/13-search-and-context-routing.mermaid), and [current executable breakpoints](mermaid/14-current-system-breakpoints.mermaid)

## Executive verdict

The repository contains several strong POC mechanisms, but the assembled system is **not ready for real client data or a production-quality architectural demonstration**. The main problem is not that a few thresholds need tuning. The problem is that important transitions between stages either discard evidence, manufacture semantics, expose stale derived state, or use one global configuration and artifact set for every possible client.

The current implementation is best described as a **single-client research pipeline with product-shaped entry points**. It is not yet a client-tunable product object. A second client with a different line of business, note style, source schema, role vocabulary, identifier family, privacy boundary, or search workload would require edits to Python constants and logic, then would overwrite the first client's database, model, graph, caches, and vector indexes.

The right correction is not a rewrite into microservices. It is a **modular monolith with explicit contracts**:

1. a versioned `ClientProfile` containing client-controlled policies and adapters;
2. an immutable `RunSpec` recording the exact profile, model, prompt, and artifact versions used;
3. one evidence ledger that preserves candidates before interpretation;
4. separately versioned projections for identity, graph, dossiers, and indexes;
5. a query router that chooses exact, lexical, semantic, temporal, and graph mechanisms by query need;
6. evaluation gates that calibrate each client profile without modifying core code.

The biggest risk today is **false certainty**: an output can look fully formed even when the relationship was inferred from co-presence, an identifier was only format-matched, a model-training step silently failed, the search index omitted new notes, or a citation string was never checked against the evidence supplied to the model.

## What was reviewed

The sweep covered the complete tracked architecture surface: 37 Python modules under `src/`, 15 `# %%` notebook-source files, the SQLite contracts and repository, ingestion and incremental processing, both vector indexes, entity resolution, graph construction, the query application and agent, the one smoke-test file, 15 pre-existing Mermaid diagrams, ERDs, current Markdown documentation, and archived design documents.

This is a static architecture and source review. I did not use synthetic-pipeline output as proof that the design generalizes, because that is one of the issues under review.

## First principles for actual claim handling

Insurance claim notes are not merely a bag of party names. They are an evolving record of who communicated what, when an action occurred, what source reported it, whether it was denied or corrected, which claim or occurrence it concerns, and what the handler did next. The NAIC property/casualty model regulation describes claim-file documentation broadly and calls for enough detail to reconstruct claim activity, including dates associated with relevant documents. That makes chronology, provenance, and correction history part of the domain model rather than optional reporting features. See [NAIC Model Regulation 902](https://content.naic.org/sites/default/files/model-law-902.pdf).

The architecture should therefore obey these invariants:

- **Evidence is immutable; interpretations are versioned.** Preserve the exact source bytes and spans. A model output is never the source record.
- **Observation, assertion, and identity are different things.** Seeing a name, interpreting a relationship, and deciding two mentions refer to one entity are separate probabilistic operations.
- **Identity is global within an authorized client boundary; role is contextual.** A party may be claimant on one claim, witness on another, employee in one sentence, and unrelated elsewhere.
- **Uncertainty has multiple axes.** Negation, evidential source, lifecycle/retraction, and confidence cannot be collapsed into one mutually exclusive label.
- **The world is open.** New roles, relationships, identifier types, note formats, and event types must survive as evidence even when the system cannot yet normalize them.
- **Retrieval is not one algorithm.** Names, claim numbers, policy codes, dates, and quoted phrases require exact or lexical retrieval; concepts benefit from vectors; relationships require graph traversal; chronology requires structured filtering.
- **Client tuning changes policy or learned artifacts, not source code.** An unsupported data concept may require a new adapter, but ordinary client variation must not create a code fork.
- **Abstention is a valid output.** Unknown, unresolved, conflicting, and unsupported are safer and more informative than a confident default.

Microsoft's current GraphRAG architecture similarly separates documents, text units, entities, relationships, extracted claims/statements, communities, reports, and embeddings, and exposes provider/factory boundaries for models, readers, storage, vector stores, and workflows. That does not mean this product should copy GraphRAG wholesale; it supports the architectural principle that these are separate artifacts and replaceable capabilities, not one implicit script. See the official [GraphRAG architecture](https://microsoft.github.io/graphrag/index/architecture/) and [dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/).

The NIST AI RMF Playbook likewise treats data provenance, documented limits, monitoring, and traceability as lifecycle concerns. Here that translates into persisted run/artifact lineage and measurable release gates, not merely console logs or prose claims. See the [NIST AI RMF Playbook](https://airc.nist.gov/docs/AI_RMF_Playbook.pdf).

## What is worth preserving

The audit is not a rejection of everything built so far. These choices are sound foundations:

- Source claim and occurrence identity is supplied by the client metadata contract rather than inferred from prose.
- Evidence spans and a scan ledger exist as first-class concepts.
- Structured identifiers are retained even when no nearby subject can be bound.
- The NER, structured-token, and LLM lanes retain extractor provenance.
- The embedding ER lane proposes candidates but does not itself decide identity.
- Pair scores are stored before threshold-based clustering.
- Predicate normalization is intended as a mapping, not a whitelist.
- Production NER and LLM lanes now fail loudly when unavailable.
- `# %%` Python files are the notebook source; there are currently no tracked `.ipynb` copies, so there is no notebook duplication strategy to reconcile.
- Mermaid source files are an appropriate architecture source layer, provided current and proposed behavior remain visibly distinct.

Those principles should survive the redesign. Several implementations beneath them need correction.

## Critical findings

### C1 — There is no client boundary or tunable runtime object

**Evidence.** `settings.py` creates one process-global [`CFG`](../src/settings.py#L69) and one static [`Paths`](../src/settings.py#L94) namespace. Every run uses one database, one Splink model, one graph pickle, one cache, and one pair of FAISS indexes. The schema has no `client_id`, `source_system`, `run_id`, or artifact-version dimension.

**Why it is bad.** Changing a threshold, model, role cue, source mapping, or search policy mutates the runtime for everybody. Two clients cannot be processed safely in the same deployment. Reproduction depends on whatever globals happened to be imported. “Single source of truth” is being used to mean “single mutable global,” which is the opposite of a multi-client product boundary.

**Required correction.** Introduce an immutable, versioned `ClientProfile` and `RunSpec`, and pass a `PipelineContext` explicitly into orchestration and stage services. Namespaces for stores and artifacts must include client and run/profile versions. Defaults are copied into a profile at onboarding; they are never silently inherited from a process singleton.

### C2 — The semantic evidence spine is disconnected

**Evidence.** [`relations.py`](../src/relations.py) extracts open-vocabulary subject–predicate–object candidates, but only notebook 20 calls it. Neither [`pipeline_v2.py`](../src/pipeline_v2.py) nor [`ingest.py`](../src/ingest.py) invokes it. [`build_graph.py`](../src/build_graph.py) never reads `assertions`; instead [`ROLE_PREDICATE`](../src/build_graph.py#L26) manufactures treatment, representation, repair, and adjustment edges from `entity_class` plus claim co-presence, choosing the first claimant as an arbitrary anchor at [line 132](../src/build_graph.py#L132).

**Why it is bad.** The graph can assert “A was treated by B” even when no note says so, while relationships the LLM did extract never reach the graph. This is a categorical provenance failure, not an accuracy-tuning issue.

**Required correction.** Persist relation and event candidates to the evidence ledger; resolve their arguments visibly; promote only grounded, policy-eligible assertions to factual graph edges. Co-presence can remain a navigation signal, but it must be typed `derived_co_presence`, never rendered as a note-supported fact.

### C3 — Incremental processing does not produce a consistent searchable snapshot

**Evidence.** Backfill builds both the graph and chunk index at [`ingest.py:116-119`](../src/ingest.py#L116). Incremental ingest refreshes only the graph at [`ingest.py:186-190`](../src/ingest.py#L186); the new note is never added to `chunks.faiss`. Identity materialization deletes only `entity_snapshot`, `entity_members`, and `entities` at [`incremental.py:281-284`](../src/incremental.py#L281), while [`profiles.run`](../src/profiles.py#L94) appends random-ID `entity_attributes` and upserts only current dossier IDs. Old attributes and dossiers belonging to content-derived entity IDs remain behind.

**Why it is bad.** After a successful ingest, SQL mentions may include the note, the graph may reflect it, vector retrieval may not see it, and old profile rows may still describe entity IDs that no longer exist. There is no single “dataset after ingest.” Stakeholders can receive different answers depending on which projection a feature reads.

**Required correction.** Every ingest creates one `processing_run` and an atomic published snapshot. Derived projections carry `source_run_id` and are built or incrementally updated to the same watermark. Publish an index/graph/profile manifest only after every required artifact succeeds; readers consume the last complete manifest, never a mixture.

### C4 — Entity identifiers are structurally unstable

**Evidence.** [`cluster_at`](../src/entity_resolution.py#L368) derives `entity_id` by hashing the sorted member mention IDs at [line 388](../src/entity_resolution.py#L388). The code explicitly acknowledges that gaining one mention creates a new entity ID at [`incremental.py:308`](../src/incremental.py#L308). `entity_versions` is cleared during full resolution and is never materialized as a lineage record.

**Why it is bad.** A normal new note changes the primary key of a known party. Bookmarks, annotations, graph references, human review decisions, downstream integrations, and audit trails all break or appear to refer to deleted entities. A content-derived cluster signature is useful as a snapshot fingerprint, not as the durable identity key.

**Required correction.** Mint a stable opaque `entity_id` once. Store membership in versioned `entity_snapshots`, with explicit merge/split lineage and predecessor IDs. Use a deterministic `cluster_fingerprint` only to detect unchanged membership. Define survivor-ID and alias/redirect policy for merges.

### C5 — The search architecture uses the wrong mechanism for many claim questions

**Evidence.** The agent sends every question through one claim-filtered vector lookup in [`retrieve_chunks`](../src/agent.py#L90), then expands entities whose mentions happen to fall fully inside those chunks. The separate [`app.py`](../src/app.py) implements an unrelated in-memory dossier filter/query-plan product. Neither path provides lexical/BM25 retrieval, exact structured routing, temporal search, result fusion, or one shared query trace.

**Why it is bad.** Claim numbers, policy identifiers, telephone numbers, names, exact wording, dates, and specialized codes often perform better under exact or keyword search. Azure's official hybrid-search guidance explicitly notes this distinction and runs vector and full-text retrieval in parallel, merging them with reciprocal-rank fusion. See [Azure AI Search hybrid search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview).

**Required correction.** One query service must parse scope and authorization, classify retrieval needs, run exact SQL/identifier, lexical, vector, temporal, and graph lanes as applicable, fuse/rerank results, assemble an evidence pack, and expose the full retrieval trace. The detailed target is in [diagram 13](mermaid/13-search-and-context-routing.mermaid).

### C6 — Grounded-answer claims are not enforced

**Evidence.** The agent prompt asks for citations, but [`_synthesize`](../src/agent.py#L185) accepts arbitrary model-provided citation strings at [lines 205-207](../src/agent.py#L205). It does not parse each answer claim, verify that citations refer to retrieved spans, or test entailment. The module docstring says output “is checked against” evidence, but no such checker exists.

**Why it is bad.** Prompt instructions are not controls. A syntactically cited answer can cite a non-existent span, cite a real span that does not support the claim, or omit support for one sentence.

**Required correction.** Generate structured answer claims, each with evidence IDs selected from the supplied evidence pack. Reject unknown IDs mechanically. Verify source-span integrity and run an entailment/support check; downgrade or abstain on unsupported claims. Persist the query plan, retrieval candidates, selected evidence, model version, and verification result.

### C7 — Core semantic dimensions are conflated

**Evidence.** `ENTITY_CLASSES` combines structural type and claim role. Separately, [`POLARITIES`](../src/contracts.py#L51) makes `asserted`, `negated`, `alleged`, `reported`, and `retracted` mutually exclusive.

**Why it is bad.** Type and role are different dimensions; this was already identified. The same defect also exists in polarity. “Reported” identifies an evidence source, “negated” changes propositional truth, and “retracted” changes lifecycle. A note can report a negation, allege a fact later retracted, or express uncertainty conditionally. One enum cannot represent those combinations. The earlier design position that “polarity should stay closed” was incomplete: **structural axes may be closed, but they must first be the correct axes.**

**Required correction.** Split:

- `entity_type`: small closed structural set (`person`, `organization`, `asset`, `location`, `event`, `unknown`);
- `role_assertion`: open, claim-scoped, evidence-bearing;
- `proposition_status`: `affirmed | negated | uncertain | conditional`;
- `evidentiality`: `direct | reported | alleged | inferred` plus source entity when known;
- `lifecycle_status`: `active | corrected | retracted | superseded` with a pointer to the affected assertion;
- calibrated confidence as a separate numeric field.

### C8 — The production extraction path still deletes valid candidate evidence

**Evidence.** [`_is_plausible_name`](../src/pipeline_v2.py#L62) requires capitalization and usually two tokens; failures are dropped at [`pipeline_v2.py:253-256`](../src/pipeline_v2.py#L253). LLM spans are clamped into bounds and model-returned text is accepted without requiring equality to the raw slice at [`ner_ensemble.py:233-235`](../src/ner_ensemble.py#L233). [`union_spans`](../src/ner_ensemble.py#L312) collapses every overlap to one longest span.

**Why it is bad.** Lowercase names, one-token follow-up references, nested organizations/persons, adjacent model boundary disagreements, and legitimate overlapping entities are lost before a scored precision stage can review them. A model can return the wrong text with an in-bounds offset and still create a mention that appears grounded.

**Required correction.** Store all lane candidates first. Require exact `raw[start:end]` agreement or explicitly relocate/reject the candidate; never clamp silently. Reconcile candidates with interval and label compatibility rules that preserve nested/multi-label alternatives. Convert name shape, casing, boilerplate, and header cues into features and flags, not destructive gates.

## High-severity findings

### H1 — Claim activity and chronology are discarded as “degenerate”

[`relations.DEGENERATE_PREDICATES`](../src/relations.py#L97) rejects `FILED`, `ARRANGED`, `PERFORMED`, `PROVIDED`, `RECEIVED`, `SENT`, and `CONTACTED`. In claim handling, these are often exactly the actions needed to reconstruct handling: contact attempts, document receipt, referrals, inspections, payments, reserve changes, denials, requests, commitments, and next actions.

Do not force every activity into a direct entity-to-entity edge. Introduce an event/claim-activity record with actor, action type, participants/objects, event time, record time, status, source, and evidence. Unknown action types remain open. The graph may project selected events into nodes or edges; the evidence ledger retains all of them.

### H2 — Entity resolution can silently train a partial model

The Splink backend catches and ignores failure when estimating the match prior, skips failed EM blocks, and ignores model-save errors at [`entity_resolution.py:272-310`](../src/entity_resolution.py#L272). Incremental within-batch scoring also logs and continues after failure.

That violates the repository's stated no-silent-degradation rule. A run needs an explicit `model_status` and training report: required comparisons trained, prior provenance, excluded blocks and reasons, calibration set, model checksum, and validity window. Failing a required component must block publication; optional components must be recorded as absent and prevent comparisons with fully enabled runs.

### H3 — Connected-components clustering can amplify one bad edge

Splink documents threshold clustering as connected components: any path of above-threshold links joins a cluster. See the official [Splink clustering documentation](https://moj-analytical-services.github.io/splink/api_docs/linker_clustering.html). That is exactly what [`cluster_at`](../src/entity_resolution.py#L368) implements. Pairwise plausibility is not cluster consistency: A≈B and B≈C can merge A and C despite a hard conflict.

Keep pair scoring, but add cluster-level validation, cannot-link constraints, bridge-edge diagnostics, and three decision bands: auto-link, review, no-link. Large or internally inconsistent merges should remain proposed until reviewed. Thresholds and constraints are per entity type and client profile.

### H4 — Identifier detection, validation, ownership, and graph meaning are conflated

The gazetteer correctly applies a checksum only where one exists, but storage reduces validity to a boolean; profiles then label almost any normalized narrative identifier `validated_id`. `subject_for` assigns ownership with a same/previous-line rule, while relation extraction discards identifier relations because the gazetteer supposedly “owns” them.

Use separate fields for `detection_method`, `format_validity`, `checksum_validity`, `registry_validity`, and `validation_source`. Ownership is a separate scored assertion with evidence and competing candidates. A shared identifier is a network signal, not automatically identity evidence. Which identifier kinds may contribute to ER, and at what weight, belongs in the client profile.

### H5 — Context is accidental rather than assembled

The LLM sees a fixed overlapping chunk and sometimes a name roster. It does not receive a typed, versioned context package containing source metadata, note author/time, note chronology, current claim/occurrence state, authoritative parties, neighboring notes, prior explicit aliases, or reference-data hits. Fifty-percent chunk overlap mitigates boundary truncation but does not solve cross-note context.

Introduce a `ContextAssembler` that produces a manifest of exactly what was supplied to each model call. Context sources are selected by task and scope; every supplied item has an ID, provenance, confidence, and as-of timestamp. This makes argument resolution reproducible and prevents an increasingly large prompt from becoming the architecture.

### H6 — Intake has no document identity, version, or quarantine contract

[`deliver`](../src/ingest.py#L53) overwrites files with the same name, accepts optional claim metadata, and mutates one `doc_index.json`. `documents` stores no content hash, source system, source-native ID, ingestion ID, version, MIME type, author, note timestamp, or line of business. Missing mappings become `UNKNOWN` elsewhere.

Create a source-adapter contract and immutable `source_document_version`. Validate the manifest before processing, quarantine malformed or unmapped input, hash bytes, retain source-native identifiers, and make retries idempotent by `(client_id, source_system, source_document_id, source_version/hash)`.

### H7 — Privacy and authorization are outside the architecture

Raw note text is sent to external generation and embedding APIs, stored in vector metadata, and cached on disk. SSN/TIN values can appear directly in graph node IDs at [`build_graph.py:153-160`](../src/build_graph.py#L153). The graph explicitly removes a cross-claim authorization gate, while [`agent.cross_claim_network`](../src/agent.py#L234) still calls a now-incompatible `authorized=` API.

Before real client data, define the data-processing boundary: approved providers and regions, fields allowed to leave the client boundary, masking/tokenization with offset mapping, encryption, retention, audit logs, and claim/cross-claim authorization policies. Cross-claim identity may be a core capability **within a client**, but access is still policy-controlled and recorded. Raw sensitive values must never be identifiers in logs, URLs, graph keys, or cache filenames; use opaque IDs and protected value stores.

### H8 — Model, prompt, cache, and index lineage is absent

Generation cache keys include model/task/prompt but not response schema, client profile, safety settings, SDK/provider revision, or reference-context manifest. Vector artifacts do not store embedding model/version or dimensional schema. FAISS index and Parquet metadata are persisted as two non-atomic files.

Every derived artifact needs an `ArtifactManifest`: client, run, source watermark, code commit, profile version, model and provider version, prompt/schema hash, reference-data versions, row/vector counts, checksum, and predecessor. Write artifacts to a temporary versioned location, validate them, then atomically promote one manifest pointer.

### H9 — The vector-store abstraction promises portability it cannot provide

The interface accepts an arbitrary Python `filter_fn`, then documentation claims a managed store can translate it to native server filtering. It cannot generally translate a lambda. The same abstraction also requires vector reconstruction and all-pairs `knn_within`, which suits ER candidate generation but not many managed retrieval services.

Split the ports by job:

- `EntityCandidateIndex`: batch upsert, typed compatibility filters, k-NN candidate generation, model/version introspection;
- `EvidenceSearchIndex`: lexical/vector/hybrid search, typed filter AST, ranking profile, pagination, deletion/watermark;
- optional `EmbeddingProvider`: task-specific embedding with declared dimensions and version.

FAISS remains a valid exact-search POC adapter. It is not a production contract by itself.

### H10 — Two independent query systems will drift

`app.py` plans a closed set of dossier-table filters; `agent.py` performs vector entry plus graph expansion. They expose different semantics, scopes, and error behavior. A stakeholder asking the same question through the two paths can receive different datasets with no shared query trace.

Retain one `QueryService` and expose multiple interfaces over it. Structured lookup and natural-language questions compile into the same typed query plan. The UI can show or constrain that plan, but there is one executor, one authorization check, and one evidence packet.

### H11 — Evaluation proves fixture compatibility, not client generality

The only automated test file generates the same synthetic corpus the source code was designed around. Notebook 30 also generates synthetic history while describing the operational path. Handwritten relation notes are valuable challenge fixtures, but relation extraction is disconnected and they are not a representative, independently labeled claim-note dataset. There are no retrieval relevance judgments, citation-support tests, per-source/LOB slices, or drift monitors.

Keep synthetic tests for invariants and exact planted spans. Add independently authored challenge sets and client data with leakage-safe splits. Evaluate stage contracts separately: candidate recall, span fidelity, type accuracy, argument binding, polarity dimensions, identifier ownership, pair and cluster ER, event extraction, retrieval Recall@K/nDCG, citation support, abstention, latency, and cost. Defaults graduate only when their confidence intervals and failure slices are recorded.

## Medium-severity and design-debt findings

### M1 — The repository is not an append-only evidence store

Comments describe immutable mentions/assertions and versioned entity membership, but full runs delete evidence-derived tables, incremental extraction deletes and rewrites note rows, and foreign keys are disabled around destructive materialization. Either implement immutable versions and projections, or describe the database honestly as a disposable POC materialization. The target should be append-only source/evidence plus replaceable versioned projections.

### M2 — SQLite portability is overstated

The repository uses SQLite connection semantics, PRAGMAs, raw SQL, pandas table loads, and frequent commits. Replacing it with SQL Server is not mechanical. Define a storage port around domain operations and transactions, then implement adapters; do not promise portability from a thin wrapper over engine-specific behavior.

### M3 — The current graph store is a projection, not the system of record

An in-memory igraph pickle is fine for a POC traversal adapter, but edges have no stable edge IDs, repeated upserts are not idempotent on a loaded graph, there is no schema/version manifest, and deserializing pickle assumes a trusted artifact. Treat it as a rebuildable projection from the evidence/identity tables.

### M4 — Dossier “links” overstate correlation

`profiles.py` links entities by shared identifiers and even shared email domains. A common corporate domain or office address is useful retrieval context but is not affiliation or identity. Store the primitive observation and derive scored network features with degree/hub context. Render them as “shared signal,” not “linked entity,” unless an assertion supports the relationship.

### M5 — Language, locale, and line-of-business assumptions live in core code

The carrier domain, English role cues, English pronouns/descriptors, US address abbreviations, US identifier patterns, nickname list, and note-category vocabulary are embedded in modules. Some are useful general linguistic or structural patterns, but they are not universal.

They should become named, versioned packs selected by client profile: `en-US`, jurisdiction, LOB, source system, and carrier reference data. Each feature records which pack produced it. Unknown text still reaches model-based/open-world lanes.

### M6 — Documentation has multiple competing truths

The Mermaid README is generated from source diagrams, while current Markdown plans, an older audit, live HTML, and archived documents overlap. Several statements already contradict code: open graph predicates versus the limited builder, grounded answer checking that is not implemented, and cross-claim authorization language that disagrees between modules.

Adopt a documentation index with four statuses: `CURRENT`, `TARGET`, `DECISION`, `ARCHIVE`. Every diagram states its code commit and status. The new audit does not silently rewrite earlier records; it supersedes specific conclusions explicitly.

### M7 — Operational logging is visible but not durable

`runlog.py` is helpful console narration. It is not an audit log, metrics system, or run ledger. Persist stage start/end, counts, warnings, model calls, costs, lane health, errors, retries, watermarks, and publication outcome under a run ID. Console output becomes one rendering of those events.

## Hard-coded logic: retain, parameterize, or remove

| Current mechanism | First-principles verdict | Target treatment |
|---|---|---|
| Email/phone shape patterns | Broad structural detectors are valuable, though locale coverage varies | Keep as versioned detector packs; never treat shape as ownership or registry validation |
| NPI checksum | Genuine domain validation | Keep; add registry adapter and explicit validation type/source |
| Quote marker `>` | Valid but incomplete general convention | Keep as one feature; add source-format adapters and confidence |
| SHA-256 source fingerprinting | Correct evidence-integrity mechanism | Keep; put hash on immutable document versions and run manifests |
| GLiNER labels and threshold | Reasonable default, not a universal ontology | Client/model profile with open `unknown` route and measured calibration |
| Chunk size 300 / overlap 50% | POC default, not an industry truth | Task-specific profile; benchmark sentence/layout-aware and hierarchical alternatives |
| `ourinsco.com` adjuster rule | Synthetic/client-specific leakage into core | Remove from core; carrier roster/domain is client reference data |
| Five `ENTITY_CLASSES` | Semantically wrong abstraction | Replace with closed structural type plus open evidence-based roles |
| Capitalized two-token name gate | Recall-destroying assumption | Feature only; never delete a model candidate |
| English nickname table | Potentially useful weak evidence, culturally narrow | Optional locale pack; never a deterministic merge |
| US address abbreviations/key | Useful US default but collision-prone | Locale adapter; preserve full normalized address and component confidence |
| Same/previous-line identifier binding | Useful high-precision proposal | Candidate feature alongside semantic binding; persist ambiguity |
| One ER threshold | Insufficient policy | Per-type/client auto-link, review, no-link bands with calibration artifact |
| `DEGENERATE_PREDICATES` dropping contacts/actions | Domain-destructive | Route claim actions into event extraction; only reject semantically empty output after typing |
| Open predicate strings | Correct open-world direction | Keep raw predicate plus normalized taxonomy version and mapping confidence |
| One five-value `polarity` enum | Conflates proposition, source, and lifecycle | Split into orthogonal closed structural axes |
| One embedding model for ER and retrieval | Unjustified coupling | Separate task-specific providers/models and evaluations |

## Recommended target: a client-tunable modular monolith

### Architecture decision

Three options were considered:

| Option | Result |
|---|---|
| Patch globals and add more constants | Rejected. Fastest short-term, but every client difference becomes another condition and artifacts remain mutually unsafe. |
| **Versioned client profile + explicit ports in one modular runtime** | **Recommended.** Preserves POC speed and notebook traceability while making variation, lineage, and testing first-class. |
| Build a plugin marketplace and independent microservices now | Rejected for this stage. It creates deployment and contract overhead before the evidence semantics are correct. |

### Control plane

`ClientProfile` should contain references—not arbitrary Python callbacks—to versioned configuration documents:

- identity: `client_id`, profile version, effective window;
- source contracts: adapters, field mappings, filename rules, source-native IDs, required metadata;
- domain packs: jurisdiction, locale, LOB, note-system format;
- extraction policy: enabled lanes, model refs, label descriptions, chunk/context policy, candidate thresholds;
- vocabulary policy: predicate normalization, role normalization, event taxonomy mappings, unknown handling;
- reference providers: carrier staff roster, client entity list, NPPES or other registries, address standardization;
- resolution policy: strategies per entity type, candidate lanes, feature sets, constraints, thresholds, review bands;
- search policy: intent routing, filters, lane weights, fusion, reranking, graph depth, context budget;
- governance policy: authorization scopes, masking/provider boundary, retention, logging, human-review permissions;
- evaluation policy: required datasets, metrics, slice gates, drift thresholds, abstention requirements.

`RunSpec` snapshots the resolved profile plus code commit, exact models/prompts/schemas, source watermark, and reference-data versions. Stages receive this object; they do not read process globals.

### Data plane and immutable artifact flow

1. **Ingest:** adapter emits immutable document version plus authoritative metadata. Invalid records are quarantined.
2. **Context preparation:** segment/layout/quote signals and task-specific chunks are versioned, not treated as truth.
3. **Candidate generation:** NER, structured detectors, relation/event extraction, and optional client reference matching write candidates with raw spans and lane provenance.
4. **Evidence reconciliation:** exact span validation, compatible overlap handling, normalization proposals, and uncertainty fields produce observations/assertions without deleting unresolved evidence.
5. **Argument/identifier binding:** multiple candidates and methods are scored; explicit, coreferential, roster, and proximity bindings remain distinguishable.
6. **Entity resolution:** deterministic and embedding lanes propose pairs; per-type models score; constraints and cluster validation decide auto/review/no-link.
7. **Stable identity:** durable entity IDs point to versioned membership snapshots and merge/split lineage.
8. **Projections:** graph, dossiers, exact/lexical indexes, vector indexes, and analytics views are built from one published run watermark.
9. **Query:** a shared router produces an evidence pack; synthesis cannot create facts and every answer claim is verified against selected evidence.
10. **Evaluation and review:** labels and corrections create new training/calibration data and profile versions. They do not retroactively mutate prior runs.

### Extension rule

A client should **not** need core-code changes to:

- map a different note/claim schema;
- supply another role vocabulary or carrier roster;
- enable a new identifier/reference-data adapter already supported by the interface;
- choose a model/provider approved for its data boundary;
- calibrate extraction, ER, review, or search thresholds;
- change query routing weights and context budgets;
- add a normalized predicate/event mapping while preserving raw values;
- define evaluation slices and release gates.

A code change is legitimate when the client reveals a genuinely new capability class: a new document modality, a new binding algorithm, a new external registry protocol, or a new storage/search backend. Even then it enters through an existing port and should not alter the evidence contract.

## Search and context target

The query plan must separate **authorization scope** from **relevance scope**. A user may be authorized for cross-claim analysis but ask a claim-specific question; conversely, an entity may exist globally while the user is authorized for only one claim.

Recommended query sequence:

1. parse authorization, tenant, claim/occurrence, time, and source constraints;
2. extract exact anchors such as claim IDs, names, identifiers, dates, quoted strings, and codes;
3. classify required lanes:
   - exact/SQL for IDs, metadata, counts, and deterministic filters;
   - lexical/BM25 for names, codes, specialized terms, and exact wording;
   - vector for semantic questions and paraphrases;
   - temporal for as-of, before/after, and sequence questions;
   - graph for relationships, paths, shared signals, and cross-claim networks;
4. run lanes in parallel under the same policy filter;
5. fuse rank lists, preserve lane attribution, then rerank against the full question;
6. assemble raw spans, assertions, entities, and graph paths into one bounded evidence packet;
7. synthesize structured answer claims using only evidence IDs;
8. verify citations/support and abstain where support is insufficient;
9. persist the complete search trace for relevance evaluation and stakeholder explanation.

Vector search remains important, but it is one retrieval lane. Embeddings in ER remain valuable as a production-level candidate recall net, but they must be independently calibrated and must never be confused with answer retrieval.

## Minimum data-model corrections

The next schema design should add or revise these first-class records:

- `clients`, `client_profiles`, `profile_versions`;
- `source_documents`, `source_document_versions`, `source_metadata`, `quarantine_records`;
- `processing_runs`, `stage_runs`, `model_calls`, `artifact_manifests`;
- `extraction_candidates` preserving every lane result before reconciliation;
- `mentions` with structural `entity_type`, raw span equality status, and extraction-run lineage;
- `assertions` with argument records, proposition status, evidentiality, lifecycle, confidence, and assertion-to-assertion correction links;
- `events` / `claim_activities` for chronological handling actions;
- `identifier_observations`, `identifier_validations`, and scored `identifier_bindings` as separate concerns;
- `same_as_edges` with model/calibration version and comparison explanations;
- stable `entities`, versioned `entity_snapshots`, membership, and merge/split lineage;
- `review_items` and immutable `review_decisions`;
- `search_runs`, lane candidates, fused ranking, selected evidence, answer claims, and verification outcomes.

Every derived table/index must carry `client_id`, `source_run_id`, and its own artifact version or be physically namespaced by those values.

## Delivery sequence

### Gate 0 — Stop producing misleading outputs

- Remove fabricated role edges from factual views.
- Make relation extraction and claim-activity extraction part of the evidence path.
- Fail publication when any required projection is stale or incomplete.
- Verify LLM mention spans and answer citations mechanically.
- Make model-training degradation explicit.

### Gate 1 — Establish the product boundary

- Add `ClientProfile`, `RunSpec`, source adapter, run ledger, and artifact manifest.
- Namespace all data and artifacts by client/profile/run.
- Define privacy/provider and authorization policies before loading real client notes.

### Gate 2 — Correct semantic and identity models

- Split type, role, proposition status, evidentiality, and lifecycle.
- Preserve all candidates; replace destructive shape/overlap gates.
- Separate identifier validation from binding.
- Introduce stable entity IDs, versioned snapshots, review bands, and cluster validation.

### Gate 3 — Build the correct retrieval product

- Unify `app.py` and `agent.py` behind one query service.
- Add exact, lexical, temporal, vector, and graph lanes with fusion/reranking.
- Make incremental index publication consistent.
- Add answer-claim citation verification and search trace persistence.

### Gate 4 — Calibrate on independent and client data

- Preserve synthetic tests for invariants only.
- Add independent challenge and representative client sets.
- Calibrate per client, LOB, source, entity type, and query class.
- Publish quality, abstention, latency, and cost gates with confidence intervals.

This order is intentional. Tuning the present thresholds before fixing evidence routing, snapshot consistency, and semantics would optimize a system whose outputs do not yet mean what their labels claim.

## Acceptance criteria for “ready to test on real data”

The system is ready for a controlled real-data pilot only when all of the following are true:

- one client profile and data-processing boundary has been reviewed and versioned;
- source documents are immutable/versioned and malformed metadata is quarantined;
- every factual assertion/edge opens an exact source span and states whether argument resolution was explicit or inferred;
- claim activities and chronology are retained rather than discarded;
- type, role, negation, evidentiality, and retraction are not conflated;
- entity IDs remain stable as notes arrive, with visible merge/split lineage;
- an ingest publishes one consistent SQL/graph/search snapshot or publishes nothing;
- exact, lexical, vector, temporal, and graph retrieval are evaluated on their intended query classes;
- generated answer citations are mechanically valid and semantically supported;
- cross-claim and external-model access is authorized, logged, and client-scoped;
- no required model, training block, index, or stage can fail while a run is reported successful;
- independent evaluation—not generator-derived fixtures—supports the stated quality claims.

## Final assessment

The project is conceptually recoverable without discarding all work. Its best idea is the evidence-first separation of raw spans, candidates, pair scores, and derived views. Its worst architectural pattern is repeatedly crossing those boundaries implicitly: a role guess becomes identity type, co-presence becomes a factual relationship, format validity becomes a trusted identifier, one pair edge becomes a whole cluster, a vector hit becomes the universal search mechanism, and a prompt request becomes a citation control.

The next build should make those transitions explicit, versioned, scored, and client-configurable. Once that is done, thresholds become what they should be: calibrated operating policies over a correct mechanism, not patches holding together a mechanism that changes meaning between stages.
