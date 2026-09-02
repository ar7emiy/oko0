# TODO — status board

Companion to `development-plan.md`. The plan carries the reasoning; this carries
the state, the evidence, and what would prove each item wrong.

## For a reviewer reading this cold

**Known bias in this document.** The same author wrote the system, the critique
of it, and this list. An external audit
(`first-principles-claim-note-audit.md`) was commissioned precisely because of
that, and several items below originate there. Where this document disagrees
with that audit, the disagreement is marked. Treat unmarked agreement between
the two with more suspicion than disagreement.

**Numbering.** `T1.4` here is §1.4 in the plan. Items with a letter suffix
(`T1.2a`, `T1.3a`) are finer-grained than the plan — they were split out because
each is a distinct action with its own falsification test, and because `T1.2a`
records a correction to the plan itself. Phase 4–5 items are listed but not
expanded; they are gated on Phase 1–2 and their design will change with those
outcomes.

**Every item separates three things**, because conflating them is how a plan
becomes unfalsifiable:

| field | means |
|---|---|
| **Current** | what the code does today, with `file:line` evidence you can check |
| **Problem** | what is wrong with that, tagged **measured** or **unmeasured** |
| **Proposed** | the change |
| **Confidence** | `measured` (a number exists) · `reasoned` (argument only) · `assumed` (belief, no evidence) |
| **Falsified if** | the observation that would kill this item |

**An item at `assumed` confidence has no business being built before its
falsification test runs.** Two items below are in that state and are marked as
blocked on measurement rather than scheduled.

---

## Current state, factually

Verified by grep against source on 2026-09-02, not taken from prose.

**What works and is measured**

| | value | conditions |
|---|---|---|
| identifier recall (finding them) | 1.000 | synthetic corpus, 2000 notes |
| entity recall | 0.857 | same |
| scan coverage | 100% chars/doc, 0 docs short | same |
| B³ F1 | 0.83 (P 0.82 / R 0.83) | **stale** — predates the embedding lane; measured with LLM lane stubbed |
| single-note ingest, end to end | 18.5s | 60-note corpus, live models |
| LLM lane batching | 15min+ → 115s | 160 chunks, 8 workers |
| GLiNER batching | 1.1x (10.5s vs 11.2s) | 12 chunks, CPU, identical spans |

**What is broken and measured**

- 7,468 edges join mentions with byte-identical surface text; **4.6%** clear the
  0.45 threshold. `Rios Car Care` — 28 mentions / 12 notes → **28 entities**.
- `variant:short` 100% miss, `variant:last_only` 88% miss.

**What is broken and unmeasured**

- Identifier *binding* accuracy. We measure whether identifiers are **found**
  (1.000), never whether they are attached to the **right** entity. 1,211
  orphans exist in the 2000-note corpus; the split between genuine orphans and
  artifacts of the binding rule is unknown.
- Generality. Every number above is against `corpus_gen` output, whose shapes we
  control.

**Structural facts a reviewer should verify independently**

- `build_graph.py` references `assertions` **0 times**. Semantic edges come from
  `entity_class` + claim co-presence, 5 hardcoded predicates.
- `extract_relations` / `bind_to_mentions` are called only from
  `notebooks/20_relation_extraction.py`.
- `coref_links` is written by `pipeline_v2` and read only by `audit.py` and
  `qa_viewer.py` — no production consumer.
- `case_informative` is computed in `profiling.py` and read by nothing.

---

## Phase 1 — Reconnect the evidence path

### T1.1 — Split `entity_type` from `role`
**Status:** not started · **Confidence:** measured

**Current.** `ENTITY_CLASSES` is a closed 5-value set doing two unrelated jobs:
structural kind (drives `cannot_link_reason` and the name comparison) and
claim-scoped role. `_classify` falls back to `LABEL_TO_CLASS.get(label,
"claimant")`, writing a guess into a field readers treat as fact.

**Problem (measured).** Organizations pass through
`ForenameSurnameComparison(first_name, last_name)` where those fields are
`tokens[0]`/`tokens[-1]`. `'delgado legal partners'` → first=`delgado`,
last=`partners`. The commonest org "surnames" are `llp` (31), `care` (28),
`chiropractic` (28), `group` (26), so term-frequency adjustment *penalises* the
matches it should reward. This is the 4.6% figure above.

**Proposed.** `entity_type` closed and structural (`person` / `organization` /
`asset` / `unknown`); `role` open, claim-scoped, expressed as assertions with
evidence spans, polarity and confidence.

**Falsified if.** Per-type comparison strategies (T2.1) fail to move the
identical-surface merge rate materially above 4.6%. That would mean the name
comparison was not the binding constraint and something else is.

**Touches.** `contracts.py`, `pipeline_v2.py`, `entity_resolution.py`,
`build_graph.py`. Invalidates all prior B³ numbers by design.

---

### T1.2 — Put relation extraction on the operational path
**Status:** not started · **Confidence:** measured (the disconnect is a fact)

**Current.** `relations.py` produces span-grounded, open-vocabulary triples with
polarity and evidence. Nothing in the operational path calls it.

**Proposed.** `pipeline_v2` and the ingest path call `extract_relations` →
`bind_to_mentions` → persist as assertions. Unbound candidates go to a review
queue table, never dropped.

**Falsified if.** Relation precision on the handwritten set is low enough that
persisting the output degrades the graph rather than grounding it. This is
genuinely possible and unmeasured — `expected_relations.json` is one person's
reading, not an adjudicated gold set.

---

### T1.2a — Stop discarding LLM identifier bindings ⚠ **corrects an error in this plan**
**Status:** not started · **Confidence:** reasoned

**Current.** `relations.py:202` instructs the model to skip identifiers
(*"handled elsewhere"*), and `relations.py:272` drops any that arrive:

```python
if IDENTIFIER_PREDICATE_RE.match(pred):
    # Belongs to the gazetteer/identifier lane, which validates it.
    rejected["identifier_binding"] += 1
    continue
```

The LLM reads the note, correctly determines who a phone number belongs to, with
an evidence span — and the output is thrown away. Binding then falls to
`pipeline_v2.subject_for`: same line, or previous line within 120 chars.

**Problem.** The comment conflates two different jobs. *Validating* an NPI is a
checksum — decidable, and correctly the gazetteer's. *Binding* it to a person is
local semantic reading — the LLM's strength, and what the line rule crudely
approximates.

**Proposed.** Gazetteer finds and validates; LLM binds with an evidence span;
line proximity demotes to a feature. Confidence comes from **lane agreement**,
the pattern extraction already uses (`found_by: gliner+llm`) — agree → high;
disagree → review queue.

**Why this is flagged.** The first version of this plan (commit `2b5c2c4`) did
not contain this item. It wired relations in at T1.2 while leaving the discard
filter intact, then proposed at T2.2 building a feature model to approximate the
evidence being discarded upstream. A reviewer should read that as evidence that
the codebase's routing comments are load-bearing in the wrong way — they read as
settled decisions and were treated as boundaries rather than claims.

**Falsified if.** T2.2's measurement shows the line rule already matches ground
truth closely and LLM bindings add nothing.

---

### T1.3 — Make argument resolution visible
**Status:** not started · **Confidence:** reasoned

**Current.** `relations.py` already instructs the model to resolve pronouns and
role descriptors using chunk text plus a claim roster. Successful resolution
leaves **no trace** — when "the claimant" becomes "Edward Vance", the output
records the name and nothing marks it as inferred. Flags fire only on failure.

**Problem.** An inferred binding is indistinguishable from a directly-named one
in the evidence ledger.

**Proposed.** Two redundant mechanisms: `resolution_method` (`explicit` /
`within_chunk_coref` / `claim_roster` / `unresolved`) reported by the model, plus
an independent deterministic check of whether the argument string appears in the
chunk. Disagreement between them is itself a flag.

**Why both.** Self-report is the model describing its own behaviour, which models
misreport. Verification alone cannot distinguish coref types.

---

### T1.3a — Collapse two coreference mechanisms into one
**Status:** not started · **Confidence:** reasoned

**Current.** Two mechanisms exist and do not talk.
`coref.py` (FastCoref, or a naive fallback measured at **43%** accuracy) writes
`coref_links` — consumed only by `audit.py` and `qa_viewer.py`, never by a
production path. Separately, `relations.py` performs implicit coref via the
roster; its own docstring calls the roster *"the cheap form of the coreference
context that `coref.py` and the `coref_links` table exist to provide."*

**Problem.** The better mechanism is unmeasured and unrecorded; the worse one is
measured, recorded, and unused.

**Proposed.** One mechanism. LLM resolution becomes the coref record — written to
`coref_links` with `resolution_method` from T1.3 — and `coref.py` either feeds
the roster or is deleted. This **removes** a stage rather than adding one.

**Falsified if.** Argument-binding accuracy (T1.9) comes in below FastCoref's
measured accuracy on comparable cases.

---

### T1.4 — Roster carries ids, not just names
**Status:** not started · **Confidence:** reasoned

**Current.** Roster is a list of name strings; binding happens afterward by
surface match, including `_partial_surface_match` — substring containment with a
12-character length tolerance.

**Proposed.** Claim-scoped candidates with entity ids, aliases, supporting
mention ids and confidence. LLM selection is a proposal, never authority. Turns
binding into constrained selection and retires the substring heuristic.

**Guards.** Keep an open-world escape hatch (a party not on the roster must
still be expressible as free text, or the closed-vocabulary failure returns).
Snapshot the roster per call for reproducibility. Source it with confidence
values so a bad upstream resolution cannot silently poison extraction.

---

### T1.5 — Assertion-led graph, open predicates
**Status:** not started · **Confidence:** measured (the fabrication is a fact)

**Current.** `build_graph.py` reads `assertions` zero times. Role edges come from
`ROLE_PREDICATE[entity_class]` plus co-presence on a claim — so opposing counsel
and the claimant's attorney are indistinguishable.

**Proposed.** Only grounded assertions become semantic edges. Co-presence edges
become an explicitly typed `inferred_from_co_presence` layer, off by default in
factual views. The 5-predicate whitelist goes; `BANNED_PREDICATES`
(provenance-as-edge) stays.

---

### T1.6 — Move the name-shape filter out of the recall path
**Status:** not started · **Confidence:** measured

**Current.** `_is_plausible_name` requires two capitalized tokens and **drops**
the rest, after the union.

**Problem (measured).** `variant:short` 100% miss, `variant:last_only` 88% miss.
A bare "Jones" on second reference is discarded before anything can score it.

**Proposed.** Flag, not drop. Cheapest item in Phase 1.

**Falsified if.** Precision collapses far enough that downstream resolution
degrades. Measurable directly.

---

### T1.7 — Open the identifier vocabulary
**Status:** not started · **Confidence:** assumed ⚠

**Current.** The gazetteer knows a fixed kind list. Anything else is invisible.

**Problem (assumed, not measured).** Real claim data is believed to carry policy
numbers, other carriers' claim numbers, adjuster codes, DOT numbers, provider ids
in unlisted formats. **We have not seen real claim data.** The synthetic corpus
only contains kinds we chose to generate, so this gap cannot be observed in any
measurement we currently have.

**Proposed.** Generic structured-token detector; unclassified identifier-shaped
strings stored with their spans. Classification deferred, observation preserved.
Binding follows T1.2a — the LLM can bind an identifier whose *kind* is unknown.

**Falsified if.** A sample of real notes shows the existing kind list already
covers what appears. **This item should not be built before real notes or a
client schema are seen.**

---

### T1.8 — Kill the coref silent fallback
**Status:** not started · **Confidence:** measured

`coref.py`'s `auto` backend falls back silently to a rule measured at 43%.
Raise, matching the GenAI and NER lanes. Subsumed by T1.3a if that lands first.

---

### T1.9 — Re-measure
**Status:** not started · **Confidence:** n/a

The type split invalidates prior B³ numbers by design. Two new measurements:

- **Argument-binding accuracy** on ground-truth relations whose arguments are
  pronominal or descriptor-form. Report alongside — *not as* — coref accuracy:
  implicit resolution only surfaces where a relation exists, so the denominator
  differs from a dedicated coref pass. Comparing it directly to FastCoref's 43%
  would be an apples-to-oranges number.
- **Recall on the handwritten notes.** The only read on generality. Expect worse
  than 0.857.

---

## Phase 2 — Probabilistic linking everywhere

### T2.1 — Per-type comparison strategies
**Status:** blocked on T1.1 · **Confidence:** measured

Organizations get whole-string comparison with term frequency over the full name.
Re-run the B³ sweep. Also finally measure the embedding lane's ground-truth
contribution via `same_as_edges.blocked_by` — currently marked "not yet
measured" in `ARCHITECTURE.md`.

---

### T2.2 — Measure identifier binding, then decide
**Status:** **measurement first, build gated** · **Confidence:** assumed ⚠

**Current.** Binding is `subject_for`: same line, or previous line within 120
chars, taking the last qualifying mention. Binary, decided in the extractor, no
probability. Its docstring defends the strictness — a looser rule mis-binds
across email headers, and wrong identifiers then look like conflicting validated
ids and split one person into many entities. That reasoning is sound.

**Problem.** The rule pays a global recall cost to avoid one identifiable failure
mode. A signature block with a title line between name and contact
(`Karen Wu` / `Senior Adjuster` / `kwu@...`) yields an orphan. Two names on one
line bind to the last silently, with no record it was ambiguous.

**But the size of the problem is unknown.** 1,211 orphans exist; how many
*should* have bound is unmeasured.

**The measurement, which comes first.** `corpus_gen` writes `GTIdentifier`
records with owner associations and validity windows. So for every identifier
found, ground truth says who owns it. Compare three ways: line rule vs. LLM
binding (T1.2a) vs. ground truth. Yields binding precision, binding recall, and
the genuine-vs-artifact orphan split. Roughly an hour in `audit.py`.

**Then, and only then, one of three outcomes:**

1. LLM binding matches ground truth closely → T1.2a is the whole fix; no schema
   change; this item closes.
2. Both lanes are individually weak but disagree informatively → keep both,
   confidence from agreement.
3. Both are weak and agree on the wrong answer → the scored
   `identifier_bindings` table becomes justified.

**Note on the earlier plan.** Outcome 3 was originally proposed as the *plan*,
before the measurement and before noticing the LLM bindings were being
discarded. That was an over-engineering error, and it is recorded here rather
than quietly corrected.

**If outcome 3.** `identifier_bindings` as scored candidates;
`identifier_observations.subject_mention_id` becomes the materialized winner
above threshold — the same shape as `entity_snapshot` over `same_as_edges`.
Open question then: joint vs. separate calibration, since identifier agreement
already feeds the Splink mention comparison and would create a feedback path.
Likely resolution is to use entity state **as of backfill** (frozen), matching
what the operational path already does for the model and for `emb_bucket`.

---

### T2.3 — Three-band operating policy
**Status:** not started · **Confidence:** reasoned

`auto-link` / `review` / `no-link` instead of one threshold.

---

## Phase 3 — Masking and provenance

### T3.1 — Masking as a deactivatable stage
**Status:** not started · **Confidence:** reasoned

`src/masking.py`, deterministic pseudonymization behind `MASKING_ENABLED=False`.

**Hard requirement:** surrogates must be **length-preserving**, so every
`char_start`/`char_end` survives unchanged. Verifiable mechanically — round-trip
a masked corpus and assert every span check still passes. Deterministic mapping
also preserves ER behaviour, so it can be toggled live.

Not built: encryption, RBAC, retention. Designed only, gated on real data.

### T3.2 — Intake validation and run records
**Status:** not started · **Confidence:** reasoned

Validate a manifest on `deliver()`; quarantine rather than `UNKNOWN`. One
immutable run record per execution: config, model and prompt versions, input
hashes. Prerequisite for any cached derived artifact.

---

## Phase 4 — Demonstration

- **T4.1** one note traced source → span → mention → assertion → entity → edge →
  dossier. Most rendering exists.
- **T4.2** entity-level retrieval **only if** chunk-only proves insufficient, and
  the deterministic dossier gets embedded before any generated summary is
  considered. Blocked on Phase 1 — today's dossier inherits class-derived roles
  and would propagate the fabrications Phase 1 removes.
- **T4.3** metrics pack, each figure with its measurement conditions attached.

---

## Phase 5 — Client data

- **T5.1** revise `archive/ground-truth-plan.html` rather than replace it. Its
  central premise holds: the client entity list is a **precision oracle, not a
  recall oracle**. Draft in parallel with Phases 1–2, since the client
  conversation has lead time.
- **T5.2** the entity list is also the first reference-data adapter; NPPES
  lookup for NPIs is the natural second (checksum-valid ≠ registry-real).

---

## Routing decisions questioned

Standing practice, prompted by T1.2a. Comments asserting a boundary
(*"handled elsewhere"*, *"belongs to the X lane"*) read as settled and get
treated as constraints. Each is a claim.

| location | claim | verdict |
|---|---|---|
| `relations.py:202,272` | identifiers "handled elsewhere" | **Wrong.** Conflates validate (gazetteer) with bind (LLM). → T1.2a |
| `coref.py` / `relations.py` roster | coref is a separate stage | **Wrong.** Two mechanisms; the unused one is measured, the used one is not. → T1.3a |
| `pipeline_v2.subject_for` | "no name → no assertion, rather than a wrong one" | **Under-examined.** Correct instinct, wrong stage — precision decided at candidate generation. → T2.2 |
| `build_graph` `ROLE_PREDICATE` | class implies relationship | **Wrong.** → T1.5 |
| `embed_index` two indices | mention vs. chunk vectors serve opposed objectives | **Holds.** Different keys, different consumers. |
| `vectorstore` faiss isolation | one module may import faiss | **Holds.** Guard-enforced, swappable. |

---

## Not planned, deliberately

- Generated entity/community summaries — until the assertion→graph path exists.
- Free LLM graph traversal on the factual path — unauditable.
- Bitemporal completion — gap stated honestly in `DECISIONS.md`.
- Enterprise privacy controls — designed Phase 3, built on real data.
- Removing `case_informative` — dead weight, not a defect. Delete when something
  else touches `profiling.py`.
