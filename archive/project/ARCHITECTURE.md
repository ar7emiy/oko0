# Entity Intelligence: architecture and measured results

Implementation and honest evaluation of a four-layer entity-intelligence system
over synthetic insurance claim notes. Everything below is measured against a
sealed ground-truth manifest.

```
occurrence -> claim -> note          (2,000 notes, 390 words mean, 395 claims,
        |                             240 occurrences)
        v
LAYER 1  HIGH-RECALL EXTRACTION      chunking, coreference chains,
        |                            token-NER u gazetteers u LLM, sweep
        v
LAYER 2  ENTITY RESOLUTION           Splink (Fellegi-Sunter, EM-calibrated)
        |                            -> probabilistic SAME_AS edges
        v
LAYER 3  DUAL STORAGE                chunk vector index + GLOBAL entity graph
        |                            (parties, orgs, identifiers, events)
        v
LAYER 4  RETRIEVAL                   claim-filtered chunks + cross-claim
                                     entity enrichment
```

---

## 1. The fixture (corpus v2)

The first fixture flattered every measurement: ~65-word notes, 34% rigid
template, claim-scoped entities, two planted cross-claim cases. It was rebuilt to
match production shape before any further tuning, because numbers taken against
the old one could not be trusted.

| property | v1 | v2 |
|---|---|---|
| notes | 2,224 | 2,000 |
| words / note | ~65 | **390** (251–527) |
| structured template share | 34% | **~8%** |
| hierarchy | claim → note | **occurrence → claim → note** |
| entities on >1 claim | ~2 planted | **51% of entities** |
| identifier ground truth | none | **1,622 with validity windows** |
| coreference ground truth | none | **3,944 chains with hop counts** |
| event / relationship truth | none | **1,182 events, 2,674 relations** |

All 45,629 planted spans are byte-accurate against the written files; generation
is deterministic per seed. Two generator bugs were found and fixed in the
process: Zipf sampling let one claimant take 183 of 395 claims (replaced with a
capped explicit allocation), and anaphor sentences were emitted without
capitalization or terminal punctuation.

**Caveat:** the recurrence distribution is my judgment call, not measured from
production. It is config-tunable (`FANOUT_ALPHA`, `FANOUT_MAX_SHARE`).

---

## 2. What the new fixture immediately exposed

**Orphan identifier recall was 0%** — 0 of 1,211 name-less identifier mentions.

The gazetteers extracted every one of them correctly. `pipeline_v2` then
discarded any identifier it could not bind to a nearby name, because assertions
require a subject mention. That silently destroyed the exact capability the
system exists to provide: attributing "callback left at (312) 555-0148, no name
given" to a person.

The old fixture could not have revealed this — it had no orphan identifiers.

**Fix:** identifiers are now first-class observations
(`identifier_observations`), recorded whether or not a subject binds. Binding a
name is a separate, optional step.

| | before | after |
|---|---|---|
| orphan identifier recall | 0.000 | **1.000** |
| overall identifier recall | 0.857 | **1.000** |

---

## 3. Layer 2: Splink replaces the hand-rolled scorer

The previous resolver was a hand-tuned weighted sum that wrote merges
permanently and enforced constraints as hard vetoes. That produced a failure
mode where a single mis-bound identifier permanently vetoed thousands of valid
edges and split one person into ten entities.

Two structural changes:

**Calibrated probabilities.** Splink's EM training produces a real
`match_probability` per pair. The match prior is estimated from deterministic
rules rather than accepting Splink's 1e-4 default, which is badly wrong for a
corpus where entities recur heavily.

*Calibration is now reported, not assumed.* Every run prints the prior and what
each agreeing field is worth in bits, and the run output carries a `calibration`
block naming any m/u parameter EM could not estimate. This exists because the
first version of that prior was estimated from rules requiring `email` or `npi`
— fields present on 6% of mentions. It came out **16× too low**, subtracting ~4
bits from every edge and splitting 42 entities into 515, while the system went
on reporting 0.97 precision. Nothing in any run output named the prior, so
nothing caught it. See `entity_resolution.lambda_rules()`; the rule-selection
principle is *which high-precision rules actually fire on the data in hand*, not
which fields are most trustworthy in the abstract.

Edges that used a substituted parameter are flagged individually in
`same_as_edges.uncalibrated`, so an uncalibrated merge is distinguishable from a
calibrated one at read time rather than only in aggregate.

**Identity is a threshold-derived view.** Output is a `same_as_edges` table;
resolved identity is connected components at a chosen threshold, materialized
into `entity_snapshot`. Nothing is written as "same forever", so a questionable
link is a low-probability edge you filter at read time. Constraints suppress
edges *before* clustering rather than vetoing permanently.

### The operating point came from the curve, not intuition

| threshold | entities | B³ P | B³ R | B³ F1 |
|---|---|---|---|---|
| 0.30 | 915 | 0.778 | 0.851 | 0.813 |
| **0.45** (operating) | **1,010** | **0.818** | **0.833** | **0.825** |
| 0.60 (F1 max) | 1,113 | 0.853 | 0.822 | **0.837** |
| 0.70 | 9,855 | 0.934 | 0.569 | 0.707 |
| 0.90 | 16,766 | 0.997 | 0.106 | 0.192 |

> **Stale — kept for the shape, not the numbers.** This table was measured on a
> 16,766-mention corpus state that no longer exists and predates three fixes made
> on 2026-09-02. It has not been re-measured at that scale. The current
> 60-document store measures as follows, and *is* current:
>
> | threshold | entities | B³ P | B³ R | B³ F1 |
> |---|---|---|---|---|
> | 0.20 | 52 | 0.793 | 0.945 | 0.862 |
> | **0.45** (operating) | **54** | **0.796** | **0.937** | **0.861** |
> | 0.60 | 55 | 0.796 | 0.931 | 0.858 |
> | 0.80 (F1 max) | 66 | 0.932 | 0.908 | **0.920** |
> | 0.95 | 86 | 0.997 | 0.841 | 0.912 |
>
> Ground truth is 42 entities in that scope. The curve moved three times in one
> day and each move is traceable to a named defect: the match prior 16x too low
> (T0.4/D17), a third of mention spans not containing their own surface (D25),
> and a class-based veto that was suppressing correct merges 70% of the time
> (D29). At 0.45 that is F1 0.604 → 0.773 → 0.843 → **0.861**.
>
> **Re-measuring the full corpus is outstanding** (T0.6).

Ground truth is 570 entities. F1 is flat across 0.30–0.60; we operate at **0.45**
rather than the marginal F1 max at 0.60, favouring recall since the product goal
is not missing connections. At the intuitive 0.90, precision is 0.997 but recall
collapses to 0.106 — the true-match probability mass sits in 0.5–0.9.

**This is the argument for the threshold-as-a-view design.** Under the old
destructive-merge model, picking 0.9 would have silently produced a 17,000-entity
graph with no way to see the mistake or undo it.

### Bugs found while integrating

- **Empty-string blocking explosion.** Missing identifiers were filled with `""`,
  so all ~20k mentions lacking an address blocked together (~200M pairs) and
  exhausted disk. Splink excludes NULLs from blocking; an empty string is a value.
- **NaN read as a conflict.** `float('nan')` is truthy and `NaN != NaN`, so
  `if va and vb and va != vb` marked every pair of mentions *without* an
  identifier as conflicting — suppressing all 2.49M edges and leaving every
  mention as its own entity.
- **Name inversion.** String similarity scored `"miller robert"` vs
  `"robert miller"` poorly. Fixed with `ForenameSurnameComparison` plus a
  token-sorted name column. True-match median probability rose 0.51 → 0.64.
- **Blocking recall** improved 0.56 → **0.73** by adding sorted-name and
  last-name blocking. This remains the measured cap on achievable B³ recall.

---

## 4. Layer 3: three corrections to the graph model

All three were agreed in review and are now implemented.

**Identity is global.** The first version partitioned adjacency by `claim_id` so
traversal physically could not leave a claim. Wrong boundary: a person is the
same person across the corpus. `claim_id` / `occurrence_id` are now node and edge
*properties* plus containment edges, and claim scoping is a **query-time filter**
— which is exactly what the RAG path needs and what lets the entity layer enrich
across claims.

**Cross-claim edges are ordinary edges.** The authorization gate is removed.
Cross-claim linkage is the system's purpose, not a privileged operation.

**Predicates are an open vocabulary.** The whitelist of four role verbs silently
dropped or force-fit everything else. Now any predicate is accepted, normalized
toward canonical forms; only bulk provenance-as-edge (`MENTIONED_IN`,
`HAS_NOTE`) is rejected — that is already carried as `doc_id` + span on every
edge. Density is controlled by confidence and hub down-weighting instead.

**Identifiers and events are first-class node kinds**, which is what makes an
unnamed identifier mention a two-hop path rather than a dead end.

Also fixed: ~70% of notes never state a claim number in prose, so text-derived
attribution left them `UNKNOWN` (the largest hub in the graph). Claim/occurrence
membership is now read from a structural document index — legitimately available
system metadata, not ground truth. Only entity identity must be inferred.

---

## 5. The operational path: the same engines, run as a system

The four layers above describe a *batch* pass over a corpus. That is the shape
that answers "how accurate is this system" and the wrong shape for running one:
every stage globbed the whole corpus, so adding one note meant reprocessing
every note.

`src/ingest.py` runs the same engines over the same tables in two phases:

```
BACKFILL (onboarding, once)          profile -> extract -> embed
        |                            -> resolve (TRAIN by EM) -> dossiers, graph
        v
        splink_model.json + mention_blocks
        |
INGEST (steady state, per note)      profile THIS note -> extract THIS note
                                     -> upsert vectors -> attach to existing blocks
                                     -> score ONLY the new pairs against the
                                        already-trained model
                                     -> append edges -> re-cluster -> dataset
```

Measured live on a 60-note corpus: backfill 670s, then **a single arriving note
through every stage in 18.5s**, and a four-note batch in 87s. One arriving note
matched an existing entity and merged two that had been separate.

The design decisions behind it — why the model is frozen at backfill, why
re-clustering the whole corpus every time is nonetheless correct, and what
incremental bucketing deliberately gives up — are in `DECISIONS.md` under
*Operational path*. The process view is `designs/mermaid/10-operational-ingest.mermaid`.

Three lanes were found calling batch-capable APIs one item at a time while the
batching primitive sat unused. The LLM lane was the expensive one: 160 chunks
went from **unfinished after 15 minutes** to **115s** across 8 workers. GLiNER
batching was measured at only **1.1x** on CPU (10.5s vs 11.2s, identical spans) —
transformer inference is compute-bound, so there is little per-call overhead to
amortise. Worth recording because the two look like the same optimisation and
are not.

## 6. Where it stands, honestly

**Working and measured:**
- Identifier recall 100%, including 100% of name-less mentions
- Cross-claim entity presence (a high-volume attorney correctly spans 76 claims
  across 71 occurrences)
- 441 identifier nodes bridge more than one entity — the network signal
- Claim scoping holds as a retrieval filter while identity stays global

### Extraction precision drives resolution quality

One extraction fix moved B³ F1 from **0.70 to 0.83**. Sentence-opening verbs are
capitalized, so a greedy capitalized-sequence match produced spans like
`"Contacted James Moore"`; each corrupted surface became its own spurious
cluster. Trimming the leading token was a small change with a large downstream
effect — worth remembering when triaging ER quality: check the surfaces first.

**Not good enough yet:**
- **Entity resolution: B³ F1 0.83 (P 0.82 / R 0.83), 1,010 entities vs 570
  ground truth.** Still ~1.8x over-fragmented. The measured bottleneck was
  blocking recall (0.73): 27% of true co-referring pairs were never scored,
  which caps B³ recall no matter how good the comparison model is.

  That measurement is what motivated the **embedding recall net** — a second
  candidate-generation lane that proposes pairs sharing no deterministic key
  (`src/blocking.py`, diagram 07). It is built and on the tested path. Its
  effect on this number is **not yet measured against ground truth**; the audit
  now carries `same_as_edges.blocked_by` so the question is answerable, and the
  thing to look for is under-merges falling without over-merges rising.
- **Single-token name variants are missed outright**: `variant:short` 100% miss,
  `variant:last_only` 88% miss. The name-shape filter requires two capitalized
  tokens, so a bare "Jones" or "XYZ" is rejected. That is a deliberate
  precision/recall trade that is now measurable and is the clearest next lever.
- **Coreference is the weakest component: 43% overall accuracy** at 79%
  attempt coverage. Counter-intuitively, accuracy is *worse* on direct
  references (hop 1: 0.38) than on chained ones (hop 2: 0.58) — because in dense
  prose the nearest preceding person is frequently not the referent, and the
  naive nearest-compatible-mention rule takes it anyway. A real coref model
  (`fastcoref`, blocked in this environment) is the fix; the hop-level ground
  truth to evaluate one now exists.
- **Event extraction is not implemented** — event recall is 0% by construction,
  and the ground truth for it now exists and is waiting.
- **Identifier over-binding**: one email currently binds to dozens of entity
  fragments. Largely downstream of ER under-merging rather than a separate bug,
  but it needs confirming.

### Why over-fragmentation happens: organization names go through a person-name comparison

Found while building the operational ingest path (notebook 30), and it is a
sharper diagnosis than the earlier "blocking recall 0.73" note. Measured on a
60-note corpus:

- **7,468 stored edges join mentions whose surface text is byte-identical.**
- **Only 4.6% of them clear the 0.45 operating threshold.** Median probability
  **0.384** — and the value is *identical* across most of them, the signature of
  "the name agrees and every identifier is NULL".
- Concretely: `Rios Car Care` appears 28 times across 12 notes and resolves to
  **28 separate entities**. `Whitfield Trial Group`, 26 mentions across 8 notes,
  resolves to 26. Meanwhile `Edward Vance` (62 mentions, 16 notes) resolves to
  **1** — because that one has corroborating identifiers.

The mechanism is not blocking and not the threshold. It is the name comparison:

```
ForenameSurnameComparison("first_name", "last_name")
    .configure(term_frequency_adjustments=True)
```

`first_name`/`last_name` are derived as `tokens[0]` and `tokens[-1]`, which is a
*person* name model. Organizations parse absurdly under it:

```
'delgado legal partners'  ->  first='delgado'  last='partners'
'kim spine institute'     ->  first='kim'      last='institute'
```

The most common "surnames" among organization mentions are `llp` (31), `care`
(28), `chiropractic` (28), `group` (26) — structural suffixes shared by many
distinct firms. Term-frequency adjustment, which correctly *down-weights* a
match on a common surname like Smith, therefore penalises exactly the matches it
should reward: for an organization the distinguishing token is the **first** one,
and the suffix carries almost no information.

**Why this is not fixed by moving the threshold.** `ER_LINK_THRESHOLD = 0.45`
was chosen from a measured B-cubed curve, and lowering it to catch these would
raise false merges everywhere else. The pairs are not mis-ranked relative to a
cutoff; they are scored by the wrong model.

**The principled fix** is the `entity_type` / `role` split already proposed
(diagram 06): once person and organization are distinguishable, organization
names can use a whole-string comparison with term-frequency on the full name
rather than a forename/surname split. That is a change to the comparison model
and would invalidate every B-cubed number measured against the current one, so
it belongs in its own measured pass rather than as a side effect.

Note also visible above: `entity_class` is itself unreliable here —
`anthony okonjo` and `deborah lopez` are people carrying organization classes,
which is the known `_classify` fallback defect (`LABEL_TO_CLASS.get(label,
"claimant")`) writing a guess into a field readers treat as a fact.

**Environment caveats that affect the numbers:**
- The figures above were measured in an environment with **no Gemini key and no
  HuggingFace access**, so the LLM extractor and relation extraction ran on
  deterministic stubs and NER ran on the regex-shape backend. They are lower
  bounds, and they are the last numbers taken before those fallbacks were
  removed. A missing key or an unreachable GLiNER now raises
  (`LLMExtractorUnavailable` / `NERBackendUnavailable`) instead of substituting a
  stub, precisely because figures like these are indistinguishable from real
  ones once they are written down.
- **These numbers therefore predate the embedding blocking lane** and every
  change made alongside it. Re-measure before quoting them.

**Scan coverage is reported as a hygiene check, not a quality metric.** It proves
every character was read, not that anything was found — necessary, not
sufficient. It was previously overstated as a headline result.
