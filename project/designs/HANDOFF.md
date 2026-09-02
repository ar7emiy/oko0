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

**Reconciled 2026-09-02.** `TODO.md` is the single authoritative board;
`development-plan.md` is the reasoning; both audits are untouched primary
sources; agent B's `mermaid/12`+`13` are the adopted target state. Phase
numbering is aligned across both docs (0–7).

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
| D13 | **Cluster-level consistency guard was lost in the v1→v2 move** | `cluster_at` is pure connected components. `cannot_link_reason` is *pairwise* — it suppresses A–B, but if A–C and C–B survive, A and B still merge unchecked. v1 had a documented cluster-scope identifier-consistency invariant, described as "what stops transitive/embedding chains from over-merging"; v2 dropped it. Matters **more** now, because the embedding blocking lane is exactly that transitive-chaining risk |
| D14 | **Splink training completeness is never checked** | zero guards. Splink prints *"Your model is not yet fully trained… will use default values"* on every run; nothing reads it. An untrained comparison silently falls back to defaults, so probabilities it touches are uncalibrated while still being reported as calibrated — which undercuts the system's headline claim |

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

~~1. Reconcile the planning docs.~~ ✅ **done** — see §3.

1. **T3.2 — wire `who_is_at()` into `answer()`.** The cheapest item on the board.
   A working identifier→entity lookup exists and the agent never calls it, so
   identifier questions go through an embedding path that cannot serve them.
2. **T0.3 / T0.4 — the two open correctness bugs.** Cluster-consistency guard
   (a regression the embedding lane makes worse) and Splink training
   completeness. Start T0.3 with a *query*, not a build: count how many current
   clusters actually violate the invariant. That may falsify the item outright.
3. **T3.1 — hybrid retrieval.** Exact + lexical + vector + temporal + graph,
   fused by RRF. Decide the routing question explicitly (§ agent B leaves it
   open); run-all-and-fuse is the robust default at this scale.
4. **T4.1 — lexicons as loadable resources + coverage instrumentation.** The
   single change that most serves "tunable object". Instrumentation matters as
   much as the resources: it converts a silent gap into a visible one.
5. **T1.2 / T1.2b / T1.2c / T1.5 — the evidence path.** Relations reach the
   graph; activities and policy numbers stop being discarded.
6. **T2.2 measurement** — binding accuracy vs ground truth. ~1h in `audit.py`,
   and it decides whether a schema change is needed at all.

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

### 2026-09-02 (cont.) — verifying agent B's audit before merging it

Checked its claims against source rather than accepting them. **Six were real
and I had missed all six**, three of them in code I wrote or reviewed the same
day:

| claim | verdict |
|---|---|
| artifacts at different data versions | ✅ chunk index — fixed above |
| citations not enforced | ✅ fixed above |
| activities discarded as degenerate | ✅ `DEGENERATE_PREDICATES` |
| semantic dimensions conflated | ✅ `POLARITIES` mixes 3 axes |
| ER can train a partial model | ✅ **D14** — no completeness check |
| connected components amplify one bad edge | ✅ **D13** — v1 invariant lost |

Two I would **rate differently** than the audit does:

- **Entity ID instability (its C4, my D8)** is real, but the fix conflicts with a
  property we deliberately built: content-derived ids give idempotent re-ingest
  and reproducibility. A stable-id registry makes ids depend on processing
  *history*, so the same corpus in a different order yields different ids.
  Registry + lineage is probably right, but reproducibility then has to come from
  the RunSpec and snapshot instead of from id determinism. That trade needs
  deciding explicitly, not assuming.
- **H9, "the vector-store abstraction promises portability it cannot provide"** —
  partially fair. `knn_within` and `get_vector` do assume vector read-back. But
  the abstraction has held through two real changes (a rename plus a second
  index) and the faiss-isolation guard is enforced. Treat as design debt, not a
  critical finding.

Its **reference architecture (mermaid 12/13/14) is the right target** and is
adopted as such. Its weaknesses as a *plan*: no sequencing or cost, no cold-start
story (where do out-of-box defaults come from for a client with no labels and no
reference data — which is the question the user actually asked), query routing
left unspecified when it is the crux, and no unit-economics for multi-lane LLM
extraction at carrier volume.

**Reconciliation decision.** Both audits stay untouched as dated primary sources
— editing them destroys the record. `TODO.md` stays the single status board and
absorbs their findings in its own evidence/confidence/falsification format, with
attribution. `development-plan.md` becomes the path from here to agent B's target.

### 2026-09-02 (cont.) — reconciliation complete

Four planning docs → one board. Structure now:

- **`TODO.md`** — the single authoritative status board. Defect register (D0a–D14,
  each with attribution and verification status), current-state table with
  measurement conditions, phases 0–7, the routing-decisions verdict table, and
  an explicit not-doing list.
- **`development-plan.md`** — reasoning and rejected alternatives only. No
  parallel item list to drift.
- **Audits** — untouched. Dated primary sources; superseded by the board, never
  edited.
- **`mermaid/12`, `13`** — adopted target state.

**Two phases added**, both from findings neither my plan nor agent A had:
**Phase 3 (Search)** and **Phase 4 (Tunability)**. Phase 4 is the one that
directly answers the user's "tunable object" requirement, and its core finding is
that *every lexicon in the system is a Python constant with no override path* —
plus no instrumentation, so the gap is silent.

Phase numbering is aligned across both docs. Sequencing table updated: **Phases 0
and 3 gate on nothing and pay off immediately.**

**Deliberately rejected from agent B's proposal:** microservices. Its
modular-monolith recommendation is right for this scale; splitting services now
adds operational surface without solving a single defect in the register.

### 2026-09-02 (cont.) — T3.2 exact lane, and the bug it exposed

**Done.** `answer()` now runs an exact-match lane before the vector lane and
unions the entities it resolves into graph expansion.

The design choice worth keeping: the detector is `gazetteers.scan`, **the same
one used on note text**. A query is text. Reusing the extractor means a query
identifier is recognised, normalised and validated exactly as the note version
was — rather than a second query parser free to drift from the first. No new
component.

**Wiring it in exposed D15 within minutes.** `who_is_at` applied its own
normalization (`phone_last7` for phones, `address_key` for addresses) while
`build_graph` keys identifier nodes on `normalize_identifier`. Lookup asked for
`ID::phone::7979442`; the index held `ID::phone::3237979442`. **Every phone and
every address lookup had always returned `[]`** — and it was invisible because
`answer()` never called the function. The docstring calls this "precisely the
case identifier-mediated resolution exists to solve."

Fix: one shared normalization function, no overrides. Last-7 matching is a
*blocking* concern (deliberately fuzzy — see the `phone7` rule) and has no place
in an exact lookup. Guarded in `smoke_test` so the two sides cannot drift again.

Also fixed a reporting flaw in my own first draft: `exact_lookup` only reported
identifiers it *resolved*, so a detected-but-unresolved identifier looked
identical to a query with no identifier in it — which is exactly what hid D15
during the first test run. It now reports `resolved: bool` separately.

**New finding, not yet fixed (D16):** an `identifier_observations` row carries
`kind=phone, value_raw="voicemail"`. Identifier extraction has a precision leak
somewhere — the gazetteer's `PHONE_RE` does not match that string, so it came
from another path. Worth tracing.

**Note for whoever continues:** this is the third time a defect has been found by
*using* a capability rather than by reading it. The chunk index, the citations,
and now this. Reading the code finds design problems; running it finds the ones
that matter.

### 2026-09-02 (cont.) — T0.3 measured first, and the measurement reversed it

**Do not build the cluster-consistency guard.** The board said to start T0.3 with
a query rather than a build. That was correct, and it prevented an active
regression.

Corpus-wide there is exactly **one** violation: `Edward Vance`, 77 mentions, two
distinct validated NPIs. Traced to ground truth:

- `1141482996` is owned by `gt_prv_0001` **Dr. Anthony Reyes**. Bound correctly
  once, then bound **again** to "Edward Vance" later in the same document.
- `7459966595` is owned by `gt_prv_0007` **Dr. Jonathan Vance**. Bound to
  "Ted Vance" and "Edward Vance" — both of which ground truth says are
  `gt_clm_0012`, *the claimant*.

**The cluster is fine. The identifiers are mis-bound.** Two providers' NPIs were
attached to claimant mentions by the line-proximity rule in `subject_for`. A
consistency guard would have reacted by *splitting a correct cluster* on the
strength of a wrong identifier.

`subject_for`'s docstring predicted this precisely: *"Those wrong identifiers
then look like conflicting validated ids and the cluster-consistency rule splits
one real person into many entities."* The author foresaw the failure mode and
chose strictness to avoid it. The strictness was not enough — and the guard that
would have "caught" it would have done the damage the docstring warned about.

**Consequences for the plan:**

1. **T0.3 is blocked on T2.2**, not ready to build. If it is ever built it needs
   *temporal* awareness — identifiers legitimately change hands, so two values
   conflict only when their validity windows overlap. v1's blanket rule was too
   strong; restoring it verbatim would be a second mistake.
2. **D4 / T2.2 is promoted.** Identifier binding now has a *demonstrated*
   failure with ground-truth attribution, not a hypothesis. It is the highest
   priority open item.
3. A caution for the docs: `ARCHITECTURE.md` cites `Edward Vance` as the success
   case — "62 mentions, 16 notes, resolves to 1 entity" — as evidence that
   identifier-corroborated entities resolve well. The *clustering* claim survives
   this finding, but the entity carries two identifiers that are not its own, so
   the example should not be used as evidence about identifier quality.

**Fourth time measurement has changed the answer this session.** The pattern is
now unambiguous enough to state as a rule: for anything tagged `assumed` or
`reasoned`, run the query before writing the code.
