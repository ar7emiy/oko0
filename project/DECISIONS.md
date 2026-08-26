# DECISIONS.md

Design decisions and known limitations for the entity-intelligence POC over
synthetic insurance claim notes. Every material choice made without asking is
recorded here.

## Architecture

- **Logic in `src/`, notebooks are thin.** All real logic lives in importable
  modules under `src/`; each `notebooks/NN_*.ipynb` is a thin wrapper that calls
  one `src` engine and prints results. Rationale: the pipeline is unit-testable
  and runnable end-to-end from plain Python (verified), while the notebooks keep
  the call sites visible so the leakage guard (which scans notebook source) stays
  meaningful. `tests/build_notebooks.py` regenerates the notebooks from one place.
- **Single config source of truth.** `config/00_config.py` holds every model
  name, seed, path, threshold and scoring weight. It is a plain module (its name
  is not an importable identifier) loaded via `runpy` by `src/settings.py`. The
  model-isolation guard asserts no other file names a model.

## Offline determinism (important)

The system runs against the **real Gemini API when an API key is present**
(`GEMINI_API_KEY`/`GOOGLE_API_KEY`/Colab secret) and transparently falls back to
a **deterministic offline stub** when no key is present (or `GENAI_MODE=offline`).

- Why: the four research invariants (immutability, leakage guard, span grounding,
  scan coverage) and the whole pipeline must be executable and verifiable without
  network or credentials (CI, graders, this build). The offline path is honest:
  extraction/adjudication/query-planning use documented heuristics; embeddings use
  a deterministic hashing embedding. The **online path uses Gemini's JSON-schema
  constrained output** for all structured calls and the Gemini embedding endpoint.
- Consequence: reported extraction precision/recall and B-cubed reflect the
  **offline heuristic** extractor when run without a key. With Gemini online the
  extractor is stronger; the invariants and interfaces are identical either way.
- `genai.py` is transport + a `(model, prompt_hash)` disk cache. Each consumer
  supplies its own `offline_handler` thunk, so the offline logic sits next to the
  online prompt.

## Corpus generation

- **Deterministic assembly, not LLM-authored text.** The ground-truth manifest
  must record the exact `char_start/char_end` of every planted mention, written
  in the same pass that plants it. An LLM cannot guarantee it placed a surface at
  a known offset, so the generator assembles every note from fragments with a
  byte-accurate `NoteBuilder` and records each placement as it is emitted.
  (Offset fidelity is asserted in notebook 01 and the audit.) Gemini may enrich
  narrative flavor when online, but planted spans are always deterministic.
- **Hard cases planted by construction:** nickname/flip/typo/initials surface
  variants, Jr/Sr pair at one address, phoenix repair shop (new name+TIN, shared
  address/phone), shared building address across providers, recycled phone,
  address validity windows, multi-role (same person on two claims), and
  quoted-only entities (mentions appear ONLY inside quoted email history).
- **Provider/shop address+phone are surfaced in note text** (not only the
  manifest) so the shared-building / phoenix / recycled-phone hard cases are
  actually observable by the pipeline. Without this the manifest would contain
  relationships that never appear in any document.
- `claim_id` and category are derived by the pipeline **from note text**, never
  from the manifest, keeping the leakage guard clean. Category is stored on some
  notes and only implied on others (legacy inconsistency), as required.

## Invariants (the point of the research)

- **Immutability:** `data/hashes.json` seals sha256 of every raw note, written
  once; notebook 09 re-verifies at start AND end and hard-fails on mismatch.
- **Leakage guard:** `leakage_guard.scan_ground_truth_leakage()` scans notebooks
  02–06, 08 **and** the pipeline modules they import for the ground-truth token;
  only the generator (`corpus_gen`) and auditor (`audit`) may reference it. This
  is stronger than scanning notebooks alone.
- **Span grounding:** every extracted assertion's value must fuzzy-locate inside
  its claimed span (`SPAN_FIDELITY_MIN_RATIO`); failures are `grounded=0` and
  excluded downstream but retained for audit.
- **Scan-coverage ledger:** every extractor records every span it processes into
  `scan_ledger`, independent of whether an entity was found. The auditor proves
  per-doc character coverage from this ledger. Because profiling segments tile
  each document 100% and the two extractors partition template vs. non-template
  segments, union coverage is 100% by construction. **Overlap depth is 0** (the
  two passes are disjoint by design); the auditor still measures and reports it.

## Storage & vector search abstractions

- **VectorStore** is the only path to vector ops. `FaissVectorStore` uses
  `IndexFlatIP` (exact — no ANN recall confound at POC scale). Metadata filtering
  is emulated with a sidecar DataFrame + `faiss.IDSelectorBatch` applied *before*
  nearest-neighbor selection (so filtered recall is exact, not enlarge-k-and-post-
  filter). The class docstring specifies exactly what a managed
  `AzureAISearchVectorStore` must implement to swap in. The faiss-isolation guard
  asserts `faiss` is imported nowhere else.
- **Repository** wraps SQLite (+ parquet bulk dumps). Mentions and assertions are
  insert-only (immutable by convention); entity membership changes are new rows in
  `entity_versions`/`entity_members`. The storage-isolation guard asserts `sqlite3`
  is imported nowhere else.

## Resolution decisions

- **Candidate generation** is a union of independent blocking passes (A1 exact
  validated id, B1 phone-7, B2 address key, B3 phonetic-name×state, B4
  initials×DOB-year, C1 embedding top-k class-filtered, D1 claim co-occurrence);
  each pair logs its `gen_passes`. Large homogeneous blocks use a star topology
  instead of a clique to stay tractable while still merging.
- **Scoring** is a weighted feature model squashed to [0,1]. Embeddings are a
  *recall* signal and a weak scoring feature (weight 0.5, high band only) — they
  must not merge identities on their own. A `dup_group` feature links quoted
  copies of the same text. Hub identifiers (shared by >8 provisional entities)
  are down-weighted.
- **Calibration proxy (gt-free):** template+narrative naming the same entity in
  the same doc are treated as positives. We use this to *report* where positives
  land; we deliberately do **not** add the proxy offset to every pair's score —
  doing so shifts negatives up too and over-merges (observed: 180→77 clusters).
  The proxy is a diagnostic; the decision threshold stays in config.
- **Adjudicator** (ambiguous band, discriminating-signal gate) is **capped**
  (`ADJUDICATE_MAX`, most-uncertain first) so the online Gemini cost is bounded;
  offline it uses a deterministic rule. The verdict + rationale are stored in
  `feature_json` and surface as user-visible link evidence.
- **Clustering** is greedy correlation clustering over an igraph graph honoring
  cannot-link constraints — **not** naive connected components. Beyond pairwise
  cannot-link rules (conflicting validated ids, DOB conflict, person-vs-org,
  Jr/Sr at same address), a **cluster-scope identifier-consistency invariant**
  blocks any merge that would put two distinct validated-id values in one cluster.
  This is what stops transitive/embedding chains from over-merging.

## Dossiers

- `machine_annotation` is rendered from **stored data only** — a deterministic
  template over the assertion's predicate/polarity/dates and, for link edges, the
  stored `gen_passes` + feature weights + adjudicator rationale. No free-generated
  prose at display time, because the annotation exists to *verify* why an edge or
  fact is present. Bitemporal rows carry `valid_from/valid_to` (real world) and
  `known_from/known_to` (system); retractions close `known_to`; conflicting
  surviving values are flagged, not hidden.

## App / NL query

- The LLM only emits a typed query plan (`query_plan_schema`); deterministic code
  executes it over the tables. Answers are never generated straight from the
  model. The generated plan is shown for verification. Dossiers export as a
  **self-contained** HTML page (embedded raw-note text) with clickable evidence
  that highlights the exact span and shows the machine_annotation — works offline
  with no server.

## Known limitations (honest)

- **Offline extractor precision (~70% mention-level)** is limited by heuristics:
  capitalized-fragment name detection produces some spurious mentions; the
  online Gemini extractor is expected to do better. Recall ~89%.
- **Class inference** for names in free email/narrative text is heuristic
  (domain/keyword based); some attorney/adjuster mentions can be misclassed,
  which slightly inflates per-class entity counts.
- **Bitemporal `known_from`** is left null: the synthetic legacy notes rarely
  carry reliable recording timestamps, so we do not fabricate them. `valid_*`
  windows come from effective dates where present.
- **Overlap depth is 0** by design (disjoint extractor passes). The coverage
  proof still measures it, as required.
- **Resolution is tuned on offline hashing embeddings**; with real Gemini
  embeddings the C1 recall pass and the `embed_cosine` feature behave differently
  (more semantic), and thresholds may warrant light re-tuning.
- Full offline run ≈ 3–4 min (resolution dominates); well under the 40-min target.
  Online adds Gemini latency, bounded by batching, caching, and the adjudication
  cap.

## Representative offline results (SEED=20260826, no API key)

- Corpus: 180 GT entities, ~2.2k notes, ~6.4k planted placements (byte-accurate).
- Coverage: 100% of characters per doc; 0 docs under 100%.
- Mentions: recall ≈ 0.89, precision ≈ 0.70.
- Clusters: 180 GT vs ~198 system; B-cubed P/R ≈ 0.92/0.94 (F1 ≈ 0.93);
  ~8 GT entities never recovered (itemized in the audit).
