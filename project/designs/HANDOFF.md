# HANDOFF — session state and running work log

**For the agent picking this up.** Read this before touching code. It records
what is done, what is in flight, what is next, and — most importantly — the
standing constraints the user has set, several of which are easy to violate by
accident.

Updated progressively during the session. Newest work at the bottom of the log.

---

## 1. The goal, in the user's own terms

> The system finds **every** entity mention, in whatever shape it arrives, on
> data it has never seen; extracts **every** piece of metadata attached to them;
> links mentions **and** metadata probabilistically; and stores the result as an
> entity knowledge map other products can build on.

Two framings that govern almost every decision:

**Accuracy over explainability.** Explainability is the *mechanism* that makes
accuracy checkable, not the product. Where they conflict, data fidelity wins.
Do not optimise the audit story at the expense of the extraction story.

**Tunable object, not a bespoke pipeline.** The system must adapt to a client's
data through configuration and calibration, never through code changes. The
failure the user explicitly wants to avoid: *a client concludes a systematic
change is needed because we failed to identify a genuine gap in extraction,
linking, resolution, contextual grounding, or search.* Out-of-box thresholds are
fine; hardcoded domain knowledge with no override path is not.

**Near-term audience:** data-science and architecture leaders, on synthetic
notes, to secure a team. So claims must be *measured*, and enterprise controls
(RBAC, retention, encryption) are designed-not-built.

---

## 2. Standing instructions from the user

These were given explicitly and apply to all future work.

1. **Question every "settled routing decision."** Comments like *"handled
   elsewhere"*, *"belongs to the X lane"*, *"recorded separately"* read as
   settled and get treated as constraints. They are **claims**. Several are
   wrong — usually by conflating two different jobs that happen to sit near each
   other (*validate* vs *bind*; *find* vs *classify*). The recurring failure they
   produce: **the system discards evidence it already has, then builds a
   mechanism to approximate what it discarded.** Verdict table lives in
   `TODO.md` under *Routing decisions questioned* — add to it.
2. **Prefer the simpler, more holistic solution.** Several "fixes" turned out to
   be deletions. If a proposal adds a table or a stage, check first whether the
   capability already exists and is being thrown away.
3. **Docs must be impartial enough for a critiquing agent.** Separate *what is
   true now* (with `file:line` evidence) from *what is proposed* from *why we
   believe it*. Tag every claim `measured` / `reasoned` / `assumed`. State what
   would falsify it. The user runs external audits against these docs; a
   persuasive doc corrupts that.
4. **Record errors rather than quietly fixing them.** The plan has been wrong
   twice and both are documented as errors in place. This is deliberate — it is
   what makes the docs trustworthy to an auditor.
5. **Always verify claims against source before repeating them**, including
   claims from audits and from previous sessions.

---

## 3. Where things stand

**Branch:** `audit-full-system-architecture` — contains both my planning work
(`52cc8ef`) and another agent's full architecture audit (`855cbf6`).

**Document map:**

| file | what it is | author |
|---|---|---|
| `TODO.md` | status board — evidence, confidence, falsification per item | me |
| `development-plan.md` | reasoning behind the same items | me |
| `first-principles-claim-note-audit.md` | first external audit | agent A |
| `full-system-architecture-audit.md` | second external audit, broader | agent B |
| `mermaid/12,13,14-*.mermaid` | agent B's target architecture + breakpoints | agent B |
| `HANDOFF.md` | this file | me |

**These are not yet reconciled.** That is the task in flight. See §6.

---

## 4. What is actually broken (verified against source, not inherited)

Consolidated from both audits plus my own sweep. Everything here was checked by
grep or by execution.

**Fixed this session** — see the work log.

**Open, severe:**

| id | defect | evidence |
|---|---|---|
| D1 | Graph edges fabricated from `entity_class` + co-presence; extracted relations never reach the graph | `build_graph.py` references `assertions` **0×**; `extract_relations` called only from notebook 20 |
| D2 | Claim-handling activities discarded | `DEGENERATE_PREDICATES` contains `FILED`, `RECEIVED`, `SENT`, `CONTACTED`, `PROVIDED`, `PERFORMED` — in a claim file these *are* the content |
| D3 | Policy/claim numbers lost entirely | `IDENTIFIER_PREDICATE_RE` routes `POLICY_NUMBER`/`CLAIM_NUMBER` to the gazetteer lane; the gazetteer has **no detector for either** |
| D4 | LLM identifier bindings discarded | `relations.py:272` — the model correctly determines ownership with a span, output thrown away, binding falls to a line-distance rule |
| D5 | `POLARITIES` conflates three orthogonal axes | `(asserted, negated, alleged, reported, retracted)` = polarity + evidentiality + lifecycle. "states she was **not** driving" is unrepresentable |
| D6 | Vector-only retrieval | no BM25, no lexical lane, no reranking anywhere; `who_is_at()` exists and `answer()` never calls it |
| D7 | Locale model hardcoded, no override path | `_NICKNAME_GROUPS` (30 Anglo groups), `_TITLES`, `_STREET_ABBR`, US-only `PHONE_RE`, `soundex`. **Zero external resource loading in `src/`** |
| D8 | Entity IDs change when mentions arrive | content-derived uuid5 over sorted members — a held reference dangles after any ingest |
| D9 | Two coref mechanisms, disconnected | `coref_links` read only by audit/viewer; `relations.py` does its own via roster, unmeasured |
| D10 | Chunking ignores computed structure | fixed word windows; `segments`, casing, boilerplate all discarded at chunk time |
| D11 | No per-client config; no learning loop | config is one global module; corrections patch the *manifest*, never the system |
| D12 | Precision gate in the recall path | `_is_plausible_name` **drops** single-token names — measured 100% miss on `variant:short` |

**Open, scaling (not correctness):** `filter_fn` is an O(total-chunks) metadata
scan per query; `entities_in_chunks` iterates every mention per query.

---

## 5. Decisions already made — do not relitigate

- **Splink / Fellegi-Sunter for ER.** Calibrated probabilities, per-edge lane
  provenance. Right tool.
- **Identity is a threshold-derived view, never a destructive merge.** This is
  what makes re-clustering on ingest safe. Do not "materialize" identity.
- **Embeddings propose, never decide.** The blocking lane buys recall; Splink
  scores. Do not let vector similarity contribute to a match probability.
- **No silent fallbacks.** Missing backend → raise. Offline must be *chosen*
  (`GENAI_MODE=offline`), never fallen into.
- **Backfill trains, ingest scores against the frozen model.** Retraining per
  note would silently recalibrate every probability already stored.
- **Ground truth is invisible to the pipeline**, enforced by `leakage_guard`.
  Three files may touch it. Keep it that way — it is what makes every number
  credible.
- **Notebooks are `# %%` `.py`, never `.ipynb`.**

---

## 6. Next actions, in order

1. **Reconcile the four planning docs into one plan.** ← *in flight*
   Two audits + my plan + my TODO currently overlap and occasionally disagree.
   Target: `TODO.md` remains the single status board (its evidence/confidence/
   falsifiability format is the one to keep); agent B's reference architecture
   becomes the stated *target state*; `development-plan.md` becomes the path
   between them. Audits stay as-is — they are dated primary sources, do not edit.
2. **D6 hybrid retrieval + wire `who_is_at` into `answer()`.** Highest value per
   unit of work. There is currently a whole class of query (identifier lookup)
   the system cannot serve.
3. **D7 lexicons become loadable resources with coverage instrumentation.**
   Converts a silent recall failure into a visible, tunable one.
4. **D1/D2/D4 — the evidence path.** Relations reach the graph; activities stop
   being discarded; LLM identifier bindings stop being thrown away.
5. **T2.2 measurement** (`TODO.md`) — binding accuracy vs ground truth. Roughly
   an hour in `audit.py`, and it decides whether a schema change is needed at all.

---

## 7. Traps that have already bitten

- **Bash heredocs mangle backticks and backslashes.** Use the `Write`/`Edit`
  tools for content containing either, or build strings with `chr(92)`.
- **Windows console is cp1252.** `runlog.py` reconfigures stdout to UTF-8; keep
  new log output ASCII-safe regardless.
- **The full corpus is 2,000 notes and GLiNER on CPU is ~0.9s/chunk.** A full
  backfill is ~11 minutes. Use `CFG.TARGET_NOTES = 60` for iteration, and reuse
  an existing backfilled DB when testing the ingest path.
- **`genai` caches by `(model, prompt_hash)`**, so a second identical run is
  near-free. Do not mistake a cache hit for a performance fix.
- **Batch APIs exist and were unused in three places.** LLM lane batching was
  worth 15min → 115s; GLiNER batching only 1.1x (compute-bound, not
  overhead-bound). They look like the same optimisation and are not.

---

## 8. Work log

### 2026-09-02 — chunk index on ingest, and citation verification

**Two fixes, both verified by execution.**

**(a) `ingest()` never added arriving notes to the chunk index.**

Found by agent B's audit ("artifacts at different data versions"); I had swept
this code an hour earlier and missed it, in a path I wrote myself.

`backfill()` called `build_chunk_index`; `ingest()` did not. An arriving note was
profiled, extracted, embedded into `mentions.faiss`, resolved and added to the
graph — but its chunks never entered `chunks.faiss`. Layer 4 retrieval could only
ever see the backfill corpus, and it failed silently: the agent still returned
chunks, just never the new ones.

Proof, on the live DB before the fix:

```
docs in DB but NOT in chunks.faiss: 6 -> DOC00054..DOC00059   (exactly the ingested ones)
querying claim CLM0011 with text copied verbatim FROM DOC00054
  chunks returned: 0
after fix: 4
```

Changes:
- `build_graph.build_chunk_index` gains `doc_ids=` (same doc-scoping pattern as
  `profiling.run`, `pipeline_v2.run`, `embed_index.run`), loading the existing
  index and upserting rather than re-embedding the corpus.
- New `build_graph.ChunkIndexUnavailable` — raised if incremental indexing is
  asked to extend an index that does not exist. Defined in `build_graph` because
  that module owns the artifact; `agent.AgentStoreUnavailable` remains the
  query-time failure. (Deliberately *not* one shared class: two different
  failures. But do not create a *third* name for the same artifact — that bug
  was already fixed once for `MentionIndexUnavailable`.)
- `ingest()` now always calls it, **outside** the `rebuild_graph` flag, because
  retrieval correctness is not optional. When `rebuild_graph=False` the log now
  says the graph is stale rather than staying quiet about it.

**(b) Citations were requested but never verified.**

Found by agent B. `agent._synthesize` did
`cites = data.get("citations") or [...]` — the model's citation strings were
passed straight through and presented as provenance. For a system whose entire
claim is that facts trace to characters, the trace itself was unchecked.

Added `ClaimScopedAgent._verify_citations`, four checks cheapest-first: parses as
`doc_id:start-end` → document exists → span within document bounds → **span falls
inside evidence actually placed in the prompt** (a retrieved chunk or triple
span). The fourth is the one that matters: a syntactically perfect citation to a
real document the model was never shown is a fabricated provenance trail.

`answer()` now returns a `citation_check` block (`n_claimed`, `n_verified`,
`n_rejected`, `rejected` with reasons, `grounded`). Verified:

```
fabricated citations, 4 injected -> 4 rejected, distinct correct reasons
  NO_SUCH_DOC:0-10          unknown doc_id
  banana                    unparseable
  DOC00005:999999-1000000   span out of bounds
  DOC00005:0-5              span outside retrieved evidence   <- the important one
real citation                                                  -> verified
live answer on CLM0005: 11 claimed / 11 verified / 0 rejected  -> grounded
```

The live model *was* citing correctly. The point is that this is now known
rather than assumed.

**(c) Regression guard.** `tests/smoke_test.py` step 9 now asserts the invariant
**every document in the database is reachable by retrieval**
(`set(documents.doc_id) ⊆ set(doc_ids in chunk index)`), and that fabricated
citations are rejected. The chunk-index bug existed because nothing tested it.

**Not done, deliberately:** the `rebuild_graph=False` path in
`notebooks/30_live_pipeline.py` still leaves a stale graph for the single-note
demo. It now announces itself in the log. Decide whether the demo should just
always rebuild.
