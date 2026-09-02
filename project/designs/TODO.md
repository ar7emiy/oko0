# TODO — status board

The single status board. Reconciles two external audits and my own sweep into
one ordered plan.

- **Target state:** `mermaid/12-client-tunable-reference-architecture.mermaid`
  and `13-search-and-context-routing.mermaid` (agent B). Adopted.
- **Reasoning and rejected alternatives:** `development-plan.md`.
- **Primary sources, unedited:** `first-principles-claim-note-audit.md` (agent
  A), `full-system-architecture-audit.md` (agent B). Dated evidence — do not
  revise them; supersede them here.
- **Session state and standing instructions:** `HANDOFF.md`.

## For a reviewer reading this cold

**Known bias.** The same author wrote the system, much of its critique, and this
board. Two external audits were commissioned because of that. Where this board
disagrees with them, the disagreement is marked with reasoning — treat *unmarked
agreement* with more suspicion than disagreement.

**Every item carries:** what the code does now (with `file:line`), the problem
tagged **measured** / **unmeasured**, the proposal, a confidence level
(`measured` · `reasoned` · `assumed`), and what would falsify it. An item at
`assumed` has no business being built before its falsification test runs.

**Numbering.** `T1.4` here is §1.4 in `development-plan.md`. Letter suffixes are
finer-grained splits. `D*` ids are defects in the register below.

---

## Defect register

Every row verified against source by grep or execution. "Found by" is attribution,
not authority — each was independently checked.

| id | defect | found by | status |
|---|---|---|---|
| D0a | `ingest()` never added arriving notes to the chunk index — retrieval could only see the backfill corpus, silently | B | ✅ **fixed** `1a1bbe5` |
| D0b | Citations demanded by prompt, never verified | B | ✅ **fixed** `1a1bbe5` |
| D1 | Graph edges fabricated from `entity_class` + co-presence; relations never reach the graph | A, me | open |
| D2 | Claim-handling activities discarded as degenerate | B | open |
| D3 | Policy/claim numbers routed to a lane with no detector — lost entirely | me | open |
| D4 | Identifier binding is a line-proximity rule and **demonstrably mis-binds**; LLM bindings that would fix it are discarded | me | open — **promoted**, now has a proven failure |
| D5 | `POLARITIES` conflates polarity + evidentiality + lifecycle | B | open |
| D6 | Vector-only retrieval; no lexical/exact lane; `who_is_at()` never called | B, me | **partly fixed** — exact lane wired (T3.2); lexical/rerank still open |
| D7 | Locale model hardcoded, zero external resource loading | me | open |
| D8 | Entity IDs change when mentions arrive | B | open, **contested** |
| D9 | Two disconnected coref mechanisms | me | open |
| D10 | Chunking discards the structure profiling computed | me | open |
| D11 | No per-client config; corrections never feed the system | B, me | open |
| D12 | `_is_plausible_name` drops single-token names | A, me | open |
| D13 | Cluster-level consistency guard lost in v1→v2 | B | **measured — reframed.** The one violation is caused by D4, not by clustering. Guard would split a correct cluster |
| D14 | Splink training completeness never checked | B | open |
| D15 | `who_is_at` normalized differently than the indexer, so phone and address lookup returned `[]` **always** | me, via T3.2 | ✅ **fixed** |
| D16 | An `identifier_observations` row has `kind=phone, value_raw="voicemail"` — identifier extraction has a precision leak | me, via T3.2 | open |

**Scaling, not correctness:** `filter_fn` is an O(total-chunks) metadata scan per
query; `entities_in_chunks` iterates every mention per query.

---

## Current state, factually

Verified by grep/execution, 2026-09-02.

| | value | conditions |
|---|---|---|
| identifier recall (finding) | 1.000 | synthetic, 2000 notes |
| identifier recall (**binding**) | **unmeasured** | 1,211 orphans; genuine-vs-artifact split unknown |
| entity recall | 0.857 | synthetic only — generality unproven (D-gen) |
| scan coverage | 100% chars/doc | — |
| B³ F1 | 0.83 | **stale** — predates embedding lane; LLM lane was stubbed |
| identical-surface pairs above threshold | **4.6%** of 7,468 | the D1/D5 org-name failure |
| single-note ingest | 18.5s | 60-note corpus, live models |

---

# Phase 0 — Correctness. Do first.

Things that are wrong *right now* and cheap to fix.

### T0.1 Chunk index on ingest — ✅ **DONE** (`1a1bbe5`)
Proof before fix: querying a claim with text copied verbatim from an ingested
note returned **0 chunks**. `build_chunk_index` gained `doc_ids=`; `ingest()`
calls it unconditionally, outside `rebuild_graph`. Smoke test now asserts the
invariant *every document is reachable by retrieval*.

### T0.2 Citation verification — ✅ **DONE** (`1a1bbe5`)
Four checks: parses → doc exists → span in bounds → **span inside evidence
actually placed in the prompt**. The fourth catches a fabricated provenance trail
(a perfect citation to a real document the model was never shown). Verified: 4/4
fabrications rejected with distinct reasons.

### T0.3 Cluster-level consistency guard *(D13)* — ⛔ **DO NOT BUILD YET**
**Status:** measured, and the measurement inverted the item · **Confidence:** measured

**The measurement ran first, and it was right to.** Building this guard would
have made the system worse.

Corpus-wide, exactly **one** cluster violates the invariant: `Edward Vance`,
77 mentions, holding two distinct validated NPIs. Tracing both to ground truth:

| NPI | GT owner | bound to |
|---|---|---|
| 1141482996 | `gt_prv_0001` Dr. Anthony Reyes | ✅ "Dr. Anthony Reyes" … **and ❌ "Edward Vance"** later in the same doc |
| 7459966595 | `gt_prv_0007` Dr. Jonathan Vance | ❌ "Ted Vance" and ❌ "Edward Vance" — both GT `gt_clm_0012`, *the claimant* |

**The cluster is not over-merged. The identifiers are mis-bound.** Two providers'
NPIs were attached to claimant mentions by the line-proximity rule in
`subject_for`. A consistency guard would have responded by **splitting a correct
cluster** because of a wrong identifier — fixing a symptom by damaging the thing
that was right.

And `subject_for`'s own docstring predicted exactly this: *"Those wrong
identifiers then look like conflicting validated ids and the cluster-consistency
rule splits one real person into many entities."* The author foresaw the failure
and chose strictness to avoid it. **The strictness was not enough.**

**Revised proposal.** Blocked on T2.2. When binding is trustworthy, revisit —
and if it is built, the rule needs **temporal awareness**, because identifiers
legitimately change hands (`IDENTIFIER_REASSIGN_RATIO = 0.10`, and real providers
hold both Type 1 and Type 2 NPIs). Two values conflict only when their validity
windows *overlap*. v1's blanket rule was too strong; restoring it verbatim would
be a second mistake.

**Falsified as originally written.** Kept as a record of an item that
measurement reversed.

### T0.4 Splink training completeness check *(D14)*
**Status:** not started · **Confidence:** measured

**Current.** Splink prints *"Your model is not yet fully trained. Missing
estimates for: email (some u values are not trained, some m values are not
trained)"* and *"will use default values"* on essentially every run. Nothing
reads it. I watched these scroll past repeatedly and treated them as noise.

**Problem.** An untrained comparison silently falls back to Splink defaults, so
every probability that comparison touches is uncalibrated — while still being
reported as a calibrated probability. That undercuts the system's headline claim
directly.

**Proposed.** After training, inspect the settings for untrained m/u values.
Either raise, or record the untrained set in the run output and on affected
edges. Consistent with the no-silent-fallback policy already in force everywhere
else.

---

# Phase 1 — Reconnect the evidence path

The spine is `span → mention → assertion → entity → graph`, currently cut between
`assertion` and `graph` with a bypass wire across the gap. This phase is a
**deletion**: it removes the fabricated pathway. Full reasoning in
`development-plan.md` §1.

| item | what | confidence |
|---|---|---|
| T1.1 | Split `entity_type` (closed, structural) from `role` (open, claim-scoped, evidence-backed) *(D1, org-name failure)* | measured |
| T1.2 | Relations onto the operational path **and remove the identifier discard** *(D4)* | measured |
| T1.2b | **Stop discarding claim activities** *(D2)* | measured |
| T1.2c | **Detectors for policy/claim numbers** *(D3)* | measured |
| T1.3 | Make argument resolution visible (`resolution_method` + independent verification) | reasoned |
| T1.3a | Collapse the two coref mechanisms into one *(D9)* — removes a stage | reasoned |
| T1.4 | Roster carries entity ids, not just names — retires `_partial_surface_match` | reasoned |
| T1.5 | Assertion-led graph, open predicate vocabulary *(D1)* | measured |
| T1.6 | Name-shape filter becomes a flag, not a drop *(D12)* | measured |
| T1.7 | Generic structured-token detector *(D7 partial)* | **assumed** ⚠ gated on seeing real data |
| T1.8 | Kill the coref silent fallback | measured |
| T1.10 | **Split `POLARITIES` into three axes** *(D5)* | measured |

### T1.2b — Stop discarding claim activities *(D2)*
**Confidence:** measured

**Current.** `DEGENERATE_PREDICATES` contains `FILED`, `RECEIVED`, `SENT`,
`CONTACTED`, `PROVIDED`, `ARRANGED`, `PERFORMED`, `MADE`.

**Problem.** This is a **domain-modeling error, not a code bug**. The stated
reasoning — these "carry no relational semantics on their own" — is correct for a
static entity-relationship graph and wrong for a claim file, where the temporal
activity log *is* the primary artifact. `CONTACTED(adjuster, claimant, 05/02)` is
not a vague edge; it is the diary.

**Proposed.** Activities become a first-class kind alongside relations, with
`activity_type_raw` preserved, `activity_type_normalized` optional, and
`activity_family` **nullable**. Normalization is a layer, never an extraction
gate. Agent B's rule holds: *close only structural mechanics; keep domain meaning
open.*

### T1.2c — Policy and claim numbers *(D3)*
**Confidence:** measured

`IDENTIFIER_PREDICATE_RE` routes LLM-extracted `POLICY_NUMBER` and `CLAIM_NUMBER`
away to "the gazetteer lane, which owns them." The gazetteer has **no detector
for either**. They are extracted, routed, and lost — arguably the most important
identifiers in an insurance file. Concrete instance of the closed-vocabulary gap
producing *total* loss rather than degraded quality.

### T1.10 — Split the polarity enum *(D5)*
**Confidence:** measured

`POLARITIES = (asserted, negated, alleged, reported, retracted)` collapses three
orthogonal axes:

| axis | values | question |
|---|---|---|
| polarity | asserted / negated | is it claimed true or false? |
| evidentiality | direct / reported / alleged / inferred | who says so, how strongly? |
| lifecycle | active / corrected / retracted / superseded | does it still stand? |

*"The claimant states she was **not** driving"* is **reported AND negated** —
currently unrepresentable. A fact asserted then retracted needs two axes too.

### T1.9 — Re-measure
The type split invalidates prior B³ by design. Two measurements that do not yet
exist: **argument-binding accuracy** (on ground-truth relations with pronominal
or descriptor arguments — report alongside, *not as*, coref accuracy; the
denominators differ), and **recall on the handwritten notes** (the only read on
generality; expect worse than 0.857).

---

# Phase 2 — Probabilistic linking everywhere

| item | what | confidence |
|---|---|---|
| T2.1 | Per-type comparison strategies; re-run B³ sweep; finally measure the embedding lane's GT contribution | measured |
| T2.2 | **Measure identifier binding, then decide** *(D4)* | **assumed** ⚠ measurement gates the build |
| T2.3 | Three-band policy: auto-link / review / no-link | reasoned |

### T2.2 remains measurement-first
`corpus_gen` writes `GTIdentifier` records with owner associations, so ground
truth knows who owns every identifier. Compare **line rule vs LLM binding vs
ground truth** — about an hour in `audit.py`. Three outcomes; only one is a
schema change. The original plan proposed the schema change *as the plan*, before
noticing the LLM bindings were being discarded upstream — recorded as an
over-engineering error rather than quietly corrected.

---

# Phase 3 — Search: the right mechanism per question

**New phase.** Neither my original plan nor agent A covered this; agent B is
right that it is critical. Target: `mermaid/13-search-and-context-routing.mermaid`.

### T3.1 Hybrid retrieval *(D6)*
**Confidence:** measured (the absence is a fact — no BM25/lexical/rerank anywhere)

**Problem.** `retrieve_chunks` is one embed call and one dense top-k. The
highest-value claim queries are exact-match — *"who is NPI 1568291037"*, *"find
the note citing policy ABC-123"*. A dense vector of `1568291037` is close to
meaningless; dense retrieval is structurally weak on rare literal tokens.

**Proposed.** Lanes fused by RRF: **exact** (identifiers, claim numbers),
**lexical** (names, codes, jargon, quoted wording), **vector** (concepts,
paraphrase), **temporal** (chronology, as-of), **graph** (relationships,
networks).

**Open design question, flagged not answered:** how a query is routed. LLM
classifier, query-shape rules, or always-run-all-and-fuse. Agent B's proposal
leaves this unspecified and it is the crux — the three differ sharply in cost,
latency and failure mode. Run-all-plus-RRF is the robust default and probably
right for a POC.

### T3.2 Wire `who_is_at()` into `answer()` *(D6)* — ✅ **DONE**

The detector is `gazetteers.scan` — **the same one used on note text**. A query
is text; reusing the extractor means a query identifier is recognised, normalised
and validated exactly as the note version was, rather than by a second parser
free to drift.

`answer()` now runs the exact lane first and unions its entities into graph
expansion, so an identifier query reaches the graph even when the vector lane
retrieves nothing relevant.

**Wiring it in immediately exposed D15**, a bug that had been latent since the
function was written: `who_is_at` applied its own normalization (`phone_last7`,
`address_key`) while `build_graph` keys identifier nodes on
`normalize_identifier`. The lookup asked for `ID::phone::7979442` while the index
held `ID::phone::3237979442`. **Every phone and address lookup returned `[]`,
always** — invisible because nothing called the function. One shared
normalization function is the fix; last-7 matching is a *blocking* concern
(deliberately fuzzy) and never belonged in an exact lookup.

Measured after the fix, on a planted recycled-phone case:

```
query "who is associated with (323) 797-9442?"
  VECTOR lane : 5 chunks -> 22 entities   (none of them from the phone)
  EXACT  lane : 21 graph rows -> A. Martin, Rios Car Care, Yusuf Nguyen
```

Guarded in `smoke_test`: bound identifier observations must be resolvable
through `who_is_at`, so index and lookup normalization cannot drift apart again.

### T3.3 Reranking
Dense top-k feeds the LLM directly. A cross-encoder rerank over the fused
candidate set is the standard next lift.

### T3.4 Structural chunking *(D10)*
`profiling` computes segments, casing regime and boilerplate score; chunking
discards all of it and slices by word count. A chunk can straddle a quoted email
chain and the adjuster's own narrative — two voices, two time contexts, one
embedding. 50% overlap doubles the index to mitigate a boundary problem that
structural chunking solves properly.

---

# Phase 4 — Tunability: the client-configurable object

**New phase, and the one that most directly serves the stated goal.** The system
must adapt to client data through configuration, never code changes.

### T4.1 Lexicons become loadable resources *(D7)*
**Confidence:** measured

**Current.** `_NICKNAME_GROUPS` (30 groups, all Anglo), `_TITLES` (8 English),
`_SUFFIXES`, `_STREET_ABBR` (20 US types), US-only `PHONE_RE`, `soundex` (1918
US census, English surnames — and it is one of ten blocking rules). **Zero
external resource loading anywhere in `src/`.** Every lexicon is a Python
constant.

**Problem.** A Miami/LA/NYC book gets *zero* nickname matching on Hispanic names
— no José/Pepe, Francisco/Paco. Medical notes are full of `RN`, `DO`, `PA-C`,
`LCSW`, none of which are titles, so they contaminate name tokens and therefore
`first_name`/`last_name` and therefore blocking *and* the comparison model. Any
international exposure loses every non-US phone.

**And it fails silently.** No counter for "names that matched no nickname group",
no report of "phone-shaped strings that did not match `PHONE_RE`". The client
experiences it as *"your recall is mediocre on our data"* with no diagnostic
pointing at the cause — **exactly the systematic-change request the user wants to
avoid.**

**Proposed.** Versioned resource files per deployment; **coverage
instrumentation** as a first-class metric (what fraction of tokens hit each
lexicon); a bootstrap that mines candidate alias pairs from the client's own
resolved clusters. Auto-detect language/script/locale, apply compatible packs,
**record which pack interpreted a value and with what confidence**, leave
ambiguous values unclassified rather than guessing.

### T4.2 ClientProfile *(D11)*
**Confidence:** reasoned

A versioned per-client object: source-data mappings, approved models, locale
packs, reference data, ER thresholds, search and retention policy. Every run
records the exact profile, code, model, prompt and reference-data versions used.

**Cold start is the unanswered question** — and it is the one the user actually
asked. Where do out-of-box defaults come from for a client with no labels and no
reference data? Agent B's proposal does not address it. Provisional answer:
defaults ship from the synthetic corpus, and the first weeks of a deployment are
a calibration period with the coverage instrumentation from T4.1 as the signal.

### T4.3 Correction feedback loop *(D11)*
**Confidence:** reasoned

`qa_viewer` collects corrections; `audit._apply_corrections` uses them to patch
the **ground-truth manifest** for scoring. Nothing updates a lexicon, threshold,
gazetteer or model. The only path from human judgment to system behaviour is a
developer editing Python.

Corrections should become versioned labels feeding calibration and lexicon
enrichment — **not** truth injected directly into production.

### T4.4 Stable entity IDs *(D8)* — **contested**
**Confidence:** reasoned, with an explicit trade to settle

Agent B rates this critical. It is real: a consumer holding an `entity_id` has a
dangling reference after any ingest, because ids are content-derived uuid5 over
sorted members.

**But the fix conflicts with a property we deliberately built.** Content-derived
ids give *same input → same output* and idempotent re-ingest. A stable-id
registry makes ids depend on processing **history**, so the same corpus in a
different order yields different ids.

**Proposed resolution:** registry + explicit merge/split lineage, with
reproducibility provided by the RunSpec and snapshot rather than by id
determinism. That is a trade to decide deliberately, not a bullet to adopt.

### T4.5 Reference data as optional evidence
Client-supplied entity lists (employees, vendors, counsel, providers) enter as
`ReferenceEntity` records that **participate in resolution rather than bypassing
it**. Two distinctions that must hold: a client employee or vendor is a
persistent client-wide entity; *claimant* or *attorney-for-claimant* is a
**claim-specific role** and must never become a global property. An authoritative
client domain list helps identify the organization; it does **not** prove someone
is an employee — a claimant may use a corporate address, and quoted messages
carry foreign domains. Exact roster match is far stronger evidence.

---

# Phase 5 — Masking and provenance

| item | what |
|---|---|
| T5.1 | `src/masking.py`, deterministic, behind `MASKING_ENABLED=False`. **Surrogates must be length-preserving** so every char offset survives — verifiable by round-tripping a masked corpus and asserting span checks still pass. Toggleable live in the demo. |
| T5.2 | Intake validation and immutable run records (config, model, prompt, input hashes). Quarantine, never `UNKNOWN`. Prerequisite for any cached derived artifact. |

Not built: encryption, RBAC, retention. Designed only, gated on real data.

---

# Phase 6 — Demonstration

- **T6.1** one note traced source → span → mention → assertion → entity → edge →
  dossier, every fact clickable.
- **T6.2** entity-level retrieval only if chunk-only proves insufficient, and the
  **deterministic dossier** gets embedded before any generated summary is
  considered. Blocked on Phase 1 — today's dossier inherits class-derived roles
  and would propagate the fabrications Phase 1 removes.
- **T6.3** metrics pack, each figure with its measurement conditions attached.

---

# Phase 7 — Client data

- **T7.1** revise `archive/ground-truth-plan.html` rather than replace it. Its
  premise holds: the client entity list is a **precision oracle, not a recall
  oracle**. Draft in parallel with Phases 1–2; the client conversation has lead
  time.
- **T7.2** the entity list is the first reference-data adapter; NPPES lookup for
  NPIs the natural second (checksum-valid ≠ registry-real).

---

## Routing decisions questioned

Standing practice. Comments asserting a boundary (*"handled elsewhere"*,
*"belongs to the X lane"*) read as settled and get treated as constraints. Each
is a claim, and the failure they produce is specific: **the system discards
evidence it already has, then builds a mechanism to approximate what it
discarded.**

| location | claim | verdict |
|---|---|---|
| `relations.py:202,272` | identifiers "handled elsewhere" | **Wrong.** Conflates *validate* (gazetteer, checksums) with *bind* (LLM). → T1.2 |
| `relations.py` `DEGENERATE_PREDICATES` | activity verbs "carry no relational semantics" | **Wrong for this domain.** The diary is the artifact. → T1.2b |
| `IDENTIFIER_PREDICATE_RE` | policy/claim numbers belong to the gazetteer | **Wrong.** It has no detector for them. → T1.2c |
| `coref.py` / roster | coref is a separate stage | **Wrong.** Two mechanisms; the unused one is measured, the used one is not. → T1.3a |
| `subject_for` | "no name → no assertion, rather than a wrong one" | **Under-examined.** Right instinct, wrong stage. → T2.2 |
| `build_graph` `ROLE_PREDICATE` | class implies relationship | **Wrong.** → T1.5 |
| `embed_index` two indices | mention vs chunk vectors serve opposed objectives | **Holds.** |
| `vectorstore` faiss isolation | one module may import faiss | **Holds.** Guard-enforced; survived two real changes. |

---

## Not planned, deliberately

- Generated entity/community summaries — until the assertion→graph path exists.
- Free LLM graph traversal on the factual path — unauditable.
- Bitemporal completion — stated honestly in `DECISIONS.md`.
- Enterprise privacy controls — designed Phase 5, built on real data.
- Microservices. Agent B's modular-monolith recommendation is right for this
  scale; splitting services now would add operational surface without solving a
  single defect above.
