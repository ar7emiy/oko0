# GOKO Entity Extraction: System Development Proposal

*A staged plan for improving entity and detail extraction, cross-claim identity resolution and watchlist matching — designed to run in parallel with the evaluation benchmark rather than waiting for it.*

**Companion document:** [Entity Intelligence: Evaluation Benchmark and SME Review Platform](ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md). That paper defines how quality is measured. This paper proposes what to build so the measurements improve. The two are deliberately separable: the benchmark stays honest only if the people building the system do not also define the scoring, and the build stays useful only if every stage has a metric that proves it worked.

**Status:** a proposal for architecture and sequencing review. The current-state description in Part 1 comes from discovery discussion rather than a code audit — **the engineering team should correct it before this plan is committed**, because the whole staging argument rests on it being accurate.

---

## Read this first

### What GOKO does today, in plain language

Claim notes are free text. GOKO reads them and reports the people and organizations involved, along with details like addresses, phone numbers and tax IDs, and it flags names that appear on a watchlist.

Mechanically, as described in discovery, it works like this:

- **One prompt does everything.** For a given note, a single retrieval-augmented generation (RAG) call asks a language model to find entities of certain categories — legal entities, for example — and return their metadata at the same time. Detection, typing, attribute extraction and categorization all happen in one shot.
- **It reads part of a note, not all of it.** Retrieval selects some chunks of text to put in front of the model. Text that is not retrieved is never read.
- **Its citations stop at the note.** Results point at a note ID. They do not point at the sentence or the character positions that support a particular value.
- **Its matching stays inside one note.** Associating a detail with an entity happens within a single note's content. There is no mechanism that recognizes the same clinic in note 4 and note 31 as one clinic, and nothing that links entities across claims.
- **Watchlist matching is name-only.** A separate exact-string search compares names against the watchlist, with fuzzy similarity scoring. It has no contextual layer: address, phone and tax ID are not used to confirm or reject a candidate.
- **There is no second detail-extraction path.** Everything GOKO knows about an entity comes from that one generative pass.

### What we are proposing

Replace the single one-shot pass with a **staged pipeline** where each stage does one job, hands its output to the next with evidence attached, and can be measured independently.

The reasoning is simple. A single prompt that detects, types, extracts and categorizes in one step produces a single blended result, and when that result is wrong there is no way to tell which of the four jobs failed. Separating them makes each one measurable, individually improvable, and individually replaceable.

The target is a **knowledge graph** in which every entity, every attribute and every identity link carries the evidence that supports it, a confidence, and the version of the system that produced it — assembled from the full text of every note in a claim, consolidated across notes and across claims.

### The relationship to the benchmark

These two programmes are designed to interlock:

- **The benchmark measures. This proposal builds.** Every stage below is tied in §7 to the specific benchmark metric that would show it working. A stage with no metric attached is a stage we cannot justify.
- **Neither one blocks the other.** The first experiment in §8 needs no gold data at all — it measures volume and cost, not correctness. Meanwhile the benchmark's own long-lead items (SME time, data access, environment approval) proceed independently.
- **They must not share an owner.** The team improving the system should not be the team defining what counts as correct. This is not a matter of trust; it is that a benchmark authored by the people it scores stops being evidence.

### The decision we are asking for

1. **Confirm or correct the current-state description** in Part 1. Everything downstream depends on it.
2. **Approve the coverage experiment in §8** — a bounded sizing test that answers whether full-note scanning is affordable before anything is rebuilt.
3. **Agree the architectural direction in Part 2** as the target, subject to what the experiment finds.
4. **Accept the versioning discipline in §11.** Without pinned model versions and versioned prompts, benchmark comparisons between releases mean nothing, and the entire measurement programme is wasted.

### What we are not proposing

Not a vendor change, not a rewrite, and not a graph database purchase. The stages below are incremental: each one can ship, be measured, and be kept or reverted on its own. The knowledge graph is a *view* assembled from an assertion store, not a platform decision made up front.

---

## Part 1 — Where the current system stands

### 1. What the architecture implies

Stated as a pipeline, the current system has two paths and three stages between them:

```text
Note  ──▶ retrieve top-k chunks ──▶ single LLM call ──▶ entities + details + categories
                                    (detect + type +
                                     extract + classify,
                                     all at once)

Name  ──▶ exact string search ──▶ fuzzy similarity score ──▶ alert if ≥ 90
          against watchlist
```

Everything the system reports about an entity comes out of one generative call per note, and everything it reports about watchlist risk comes out of one string comparison.

### 2. Six structural limits

These are not prompt-quality problems. They are consequences of the shape above, and no amount of prompt engineering removes them.

**2.1. A recall ceiling set by retrieval, not by extraction.**
If retrieval puts five chunks in front of the model and the clinic's phone number is in the sixth, the number cannot be extracted. The model never saw it. This matters most in exactly the claims that matter most — long ones with many notes, where information is scattered. **Any measured recall today is an upper bound on what the retrieval step supplied, not a measure of the model's ability to extract.** It is entirely possible for the extraction step to be performing well while overall recall looks poor.

**2.2. Four jobs blended into one score.**
Detection, typing, attribute extraction and categorization happen together. When an entity comes back with a wrong address, we cannot tell whether the model misread the text, attached a real address to the wrong party, or invented it. The benchmark separates these into attribute precision, conditional attribution accuracy and unsupported-value rate precisely because they have different causes and different fixes — but a one-shot system gives us no lever to pull differently for each.

**2.3. No provenance below the note.**
A note-level citation says "the answer is somewhere in this document." For a note of any length, that is not verifiable in practice. It means values cannot be audited cheaply, evidence-support cannot be scored at all, and silent drift in model behaviour has nothing to trip over.

**2.4. No cross-note consolidation.**
This is the largest gap, and the one that most directly blocks the knowledge graph objective. A claim is a story told across many notes over months or years. A clinic introduced in one note and given a phone number in another is, to the current system, two unrelated facts. The consolidated view of a party — the thing that makes entity intelligence useful — does not exist. Nor does anything link parties across claims, which is where repeat-participant patterns would show up.

**2.5. Watchlist matching with no context.**
Comparing names alone and thresholding a similarity score has two failure modes at once. Common names generate false alerts that consume investigator time, while genuine matches under a different spelling or a married name fall below the threshold and are never seen. The claim evidence that would settle most of these — a matching address, a matching tax ID, the party's role in the claim — is available and unused. **Moving the threshold trades one failure mode for the other; it cannot reduce both. Only adding context can.**

**2.6. No abstention and no confidence.**
Every output is asserted flatly. There is no "found an address but cannot tell whose it is," no "possible match, evidence insufficient." Forced choices become silent errors, and downstream consumers cannot triage by confidence because there is none.

### 3. Why this is a staging argument, not a criticism

The current design is a reasonable first system. One prompt per note is the fastest route to something that works, and it established that the extraction problem is tractable at all.

What it cannot do is *improve measurably*. Each of the six limits above sits between the system and a metric the business wants to move, and each needs a different structural change. That is the case for decomposition — not that the current approach is wrong, but that it has reached the end of what tuning can deliver.

---

## Part 2 — The target architecture

### 4. Design principles

Six rules that the staged design follows. They are stated first because every stage decision below follows from them, and because they are the part most worth arguing about now rather than later.

**4.1. Separate recall from precision, and buy them at different prices.**
Finding *candidates* should be cheap, exhaustive and deliberately over-inclusive. Deciding which candidates are *real* should be expensive, careful and selective. Running one moderately-priced model once over partial text gets the worst of both. A cheap high-recall sweep followed by a precise expensive pass gets both, usually for less money.

**4.2. Nothing is asserted without evidence.**
Every entity, attribute and link carries the note and the character positions that support it. This is what makes auditing possible, what makes the evidence-support metric computable, and what makes model drift detectable.

**4.3. Abstention is a valid, valuable output.**
"Address found, owner not established" is a better answer than a guessed owner, and it is worth more operationally because it routes to a human instead of silently corrupting a record. The benchmark is built to reward this: unresolved cases are reported separately rather than counted as errors.

**4.4. Identity is a link, never a merge.**
When the system decides two claim-level parties are the same person, it records a link with its evidence and confidence. It does not overwrite either party or pool their facts into one record. Merges are hard to reverse, and a wrong merge silently fabricates a combined history that no source supports. This mirrors the benchmark's requirement that a claim-local party survives any cross-claim decision.

**4.5. Normalization stores alongside; it never replaces.**
The original string is what a reviewer sees and what an audit checks. Normalized forms sit beside it with a named normalization version. Leading zeros, masking and partial values survive intact.

**4.6. The graph is derived, never hand-maintained.**
Everything lands first in an append-only assertion store. The graph is a rebuildable projection of that store. This means a scoring change or a corrected rule can be re-applied by rebuilding rather than by migrating, and it means the graph can never drift away from its evidence.

### 5. The pipeline

Nine stages. Each has a single job, a defined output, and a metric.

```text
    ┌─────────────────────────────────────────────────────────────┐
    │  S1  Segment          every note, deterministic chunks       │
    │  S2  Detect           cheap high-recall NER over ALL chunks  │
    │  S3  Type & filter    classify candidates, drop noise        │
    │  S4  Within-note      cluster mentions of the same party     │
    │      coreference                                             │
    │  S5  Attribute        extract details, bind owner + evidence │
    │      extraction       (abstention allowed)                   │
    │  S6  Claim-level      consolidate entities across the        │
    │      resolution       claim's notes                          │
    │  S7  Cross-claim      link identities across claims          │
    │      resolution                                              │
    │  S8  Watchlist        blocking + contextual scoring          │
    │      matching                                                │
    │  S9  Graph assembly   assertions → queryable graph           │
    └─────────────────────────────────────────────────────────────┘
```

**S1 — Segmentation.** Split every note into overlapping chunks by a deterministic rule, preserving character offsets back to the source. Overlap matters: an entity whose name spans a chunk boundary is otherwise lost. Deterministic matters: re-running must produce identical chunks, or nothing downstream is reproducible. **Every chunk goes forward. Retrieval is not used to decide what gets read.**

**S2 — Candidate detection.** A cheap, fast model sweeps all chunks for candidate mentions of people, organizations, locations, vehicles and identifiers, returning character offsets. This is the user-proposed NER pass, and the target here is **recall, not precision** — it should over-generate, because S3 can discard a false candidate but nothing downstream can recover a missed one. Either a small generative model (the GPT Nano tier, or equivalent) or a trained NER model is viable; §8 measures which.

**S3 — Typing and filtering.** Classify each candidate and discard obvious noise — a header, a form label, a boilerplate footer. First point at which precision is traded for recall, and the trade is explicit and tunable rather than buried in a prompt.

**S4 — Within-note coreference.** Group the mentions that refer to the same party inside one note, including pronouns and partial names ("Dr. Monroe", "she", "the doctor"). Output is one note-level entity per real party, carrying all its mentions. This is what stops the same party being counted three times.

**S5 — Attribute extraction with explicit attribution.** For each note-level entity, extract its details — address, phone, TIN, SSN, NPI, bar number, VIN — and for each one record three things separately: the **value** (original string preserved), the **evidence** (note plus character offsets), and the **ownership decision** (which party, or *owner not established*, with a reason).

This stage is where the benchmark's hardest distinction gets built in. A clinic's address is not a doctor's address because the doctor works there. The model is asked explicitly *whose is this*, and permitted to answer *cannot tell* — which is what makes conditional attribution accuracy measurable and improvable rather than silently wrong.

**S6 — Claim-level entity resolution.** Consolidate note-level entities into claim-level entities across all the claim's notes. Standard three-step: **blocking** (cheap candidate pairs by name key, shared identifier, shared address) → **scoring** (a model over name, identifiers, role, co-occurrence) → **decision** (same / different / insufficient evidence, with evidence retained).

This is the stage that fixes limit 2.4, and the first point at which a consolidated party view exists at all.

**S7 — Cross-claim resolution.** The same machinery over a wider population, at a higher evidentiary bar. Two rules that matter: a shared address or phone number alone never establishes identity, and every link stays reversible with its evidence intact. Over-merging here is worse than under-merging — a wrong link invents a repeat participant who does not exist, and that is a conclusion someone may act on.

**S8 — Watchlist matching with context.** Two changes to the current design. **Candidate generation** widens: blocking on name variants, phonetic keys and shared identifiers, so genuine matches under a different spelling can surface at all. **Scoring** deepens: instead of name similarity alone, a contextual scorer weighs the claim party's address, phone, tax ID and role against the watchlist entry's own attributes, and returns a **calibrated confidence** plus the reasons for it.

The practical effect is the one that matters to operations: a name-only 95 with a conflicting tax ID should rank *below* a name-only 82 with a matching address. Today those two are indistinguishable. And because the output carries reasons, a reviewer can act on it rather than re-deriving it.

**S9 — Graph assembly.** Project the assertion store into a queryable graph:

| Node | Represents |
|---|---|
| Claim | One claim |
| Note version | One note at a point in time |
| Note-level entity | A party as found in one note |
| Claim-level entity | A party consolidated across a claim |
| Global identity | A party linked across claims |
| Attribute | One detail value |
| Watchlist entry | One watchlist record at a version |

| Edge | Carries |
|---|---|
| mention-of | Character offsets, model version, confidence |
| attribute-of | Ownership decision, evidence, confidence, qualifications |
| consolidates | Which note-level entities, on what evidence |
| same-as | Both parties, evidence, confidence, reversible |
| matched-to-watchlist | Method, features, calibrated confidence, reasons |
| participates-in | Role, negation, time, attribution |

Every edge carries provenance, confidence, and the system version that produced it. The graph is rebuildable from the store at any time.

### 6. What this does not change

Worth stating so the scope stays honest. The pipeline does not make the system omniscient about text that is not in the notes; it does not verify that a phone number is real, only that the notes support it; and it does not remove the need for human review on consequential decisions. It makes the system's outputs *decomposable, evidenced and measurable*. That is the whole claim.

### 7. Each stage, and the metric that proves it worked

This table is the joint between this proposal and the benchmark. Every stage is accountable to a number defined in the companion paper.

| Stage | Primary benchmark metric | What improvement looks like |
|---|---|---|
| **S1–S2** Segmentation and detection | **Entity recall** (Part 2 §4) | More of the parties SMEs established are found, because more of the text was read. |
| **S3** Typing and filtering | **Entity precision**, **entity-type accuracy** | Fewer reported parties that are not real parties. |
| **S4** Within-note coreference | **Entity precision**; duplicate-extraction error count | One clinic reported once, not three times. The benchmark counts duplicates as errors and refuses them extra match credit. |
| **S5** Attribute extraction | **Attribute precision and recall**, **value precision**, **unsupported-value rate** | More details captured, fewer invented, originals preserved. |
| **S5** Ownership decisions | **Conditional attribution accuracy** | Valid values land on the right party. This is the metric no current lever moves. |
| **S5** Evidence binding | **Evidence-support precision** (Part 2 §7, future track) | Citations resolve to the sentence, making span-level scoring possible for the first time. |
| **S6** Claim-level resolution | **Claim-level exact-match accuracy**; attribute recall | A claim's parties consolidate, so details scattered across notes attach to one party. |
| **S7** Cross-claim resolution | **Pairwise identity precision and recall**; merge/split error counts | Repeat participants become visible, without inventing ones that are not there. |
| **S8** Watchlist matching | **Watchlist precision**, **candidate-conditional recall**, **false-positive rate**, threshold analysis | Fewer wasted investigations *and* fewer missed matches — both at once, which thresholding alone cannot deliver. |
| **S9** Graph assembly | **Category accuracy**; audit traceability | Every published figure traces to the assertions behind it. |

**Read the table in reverse to prioritize.** If the business cares most about investigator time, S8 is the highest-value stage. If it cares most about completeness of the entity record, S1–S2 and S6. If about data trustworthiness, S5.

---

## Part 3 — Getting there

### 8. Experiment 1: the coverage and volume test

> **This is the first thing to build, and it is deliberately not a rebuild.** It changes nothing in production. It answers one question that governs whether the whole architecture is affordable, and it can run today because it needs no gold data.

**The question.** If we stop retrieving a subset of chunks and instead sweep *every* chunk of *every* note with a cheap high-recall pass, what do we get, and what does it cost?

**The hypothesis being tested.** That current recall is limited primarily by retrieval coverage rather than by extraction ability. If true, full coverage is the single highest-leverage change available and everything else is secondary. If false, the cascade is still worth building but for different reasons, and we will have learned that cheaply.

**Method.**

1. Take a sample of claims spanning the range of note volumes — including the long, messy ones, because the cheap cases will mislead.
2. Segment every note (S1) and run the cheap detection pass (S2) over every chunk, using the GPT Nano tier or an equivalent small model.
3. In parallel, capture what the current one-shot RAG returns for the same notes.
4. Compare, and measure the cost of the comparison.

**What gets measured.** These are the numbers that determine feasibility:

| Measure | Why it decides something |
|---|---|
| Candidate mentions per note and per claim | The fan-out that every downstream stage must absorb. Sizes S3–S5. |
| Unique candidate entities per claim vs. what the current system returns | The recall headroom. This is the headline number. |
| Distribution across note length and note quality | Whether the gain concentrates in the long messy claims, as expected, or is flat. |
| Token cost and wall-clock time per note and per claim | Whether full-coverage scanning is affordable at portfolio scale. |
| Noise rate in candidates — rough manual read of a small sample | How much work S3 has to do, and whether a cheap model can feed it. |
| Chunk-boundary losses | Whether the overlap setting is right. |

**What it explicitly does not measure.** Correctness. Without the SME answer key, a new candidate is a *candidate* — we cannot say it is a real party that the current system missed. Stating this plainly matters, because the temptation to report "we found 40% more entities" as a quality improvement will be strong, and it would be wrong. **Until the benchmark exists, extra candidates are volume, not accuracy.**

**Decision it informs.**

- Large headroom, affordable cost → build the cascade, prioritizing S1–S5.
- Large headroom, unaffordable cost → the cascade is right but needs a cheaper detector or selective full-coverage on high-value claims only.
- Little headroom → retrieval is not the binding constraint. Re-prioritize toward S5 attribution and S6 consolidation, and revisit the current-state description, because it would mean something else is limiting recall.

**Cost of the experiment itself:** one engineer, a bounded sample, no production change, no SME time. This is the cheapest decision-grade evidence available on this programme.

### 9. Staged rollout

Each stage ships independently, is measured, and is kept or reverted on its own evidence. The ordering puts cheap high-leverage work first and the irreversible-if-wrong work last.

| Stage | Work | Depends on | Benchmark readiness |
|---|---|---|---|
| **A** | Experiment 1 (§8). No production change. | Nothing | None needed |
| **B** | S1–S3: full-coverage segmentation, detection, typing. Shadow-run alongside current system; do not switch. | A | Pilot gold data helps; not required to start |
| **C** | S4–S5: coreference and attribute extraction with evidence binding and abstention. | B | Gold data needed to tune the precision/recall trade |
| **D** | S6: claim-level consolidation. | C | Gold data needed — consolidation errors are invisible without it |
| **E** | S8: contextual watchlist matching. Can run in parallel with C/D; it depends on claim evidence from C but not on cross-claim work. | C | Gold watchlist judgments needed for calibration |
| **F** | S7: cross-claim identity resolution. | D | Gold identity decisions needed; highest risk of confident error |
| **G** | S9: graph assembly and query surface. Incremental throughout; formalized here. | C–F | Traceability, not a new metric |

**Shadow-running is the safety mechanism.** From stage B onward, the new pipeline runs alongside the existing one on the same inputs without changing what production consumes. Disagreements between old and new are the most informative signal available before gold data exists — they concentrate attention exactly where behaviour changed.

**Ordering notes.** S7 is last deliberately: it is the stage where a confident wrong answer does the most damage, and it benefits most from having consolidated, evidenced claim-level entities underneath it. S8 is pulled earlier than its dependency order strictly requires because it is likely the highest business value per unit of work — see §7.

### 10. Measuring progress before the gold benchmark exists

The benchmark takes time — SME hours, data access, environment approval. Development should not idle, but it also must not invent its own scoreboard. These are navigational instruments, not a substitute for the benchmark, and the distinction has to hold in how results are reported.

| Instrument | What it tells you | What it cannot tell you |
|---|---|---|
| **Volume and coverage deltas** | How much more text was read, how many more candidates surfaced | Whether the extra candidates are real |
| **Old-vs-new disagreement** | Where behaviour changed; a high-yield queue for manual inspection | Which of the two is right |
| **Self-consistency across runs** | Whether outputs are stable; catches nondeterminism early | Whether stable outputs are correct |
| **A small hand-labelled dev set** (10–20 claims, built by the engineering team) | Fast smoke-test signal; catches gross regressions within minutes | Anything publishable. It is not independent, it is not adjudicated, and it is too small |
| **Cost and latency per claim** | Whether a design is viable at scale | Quality, at all |

**Three rules for this period, which the benchmark's own reporting discipline requires:**

1. **Never publish a silver number as a benchmark result.** Label every pre-benchmark figure as provisional and name the instrument that produced it.
2. **Never let the engineering dev set become the answer key.** It is built by the people being measured, which is exactly the independence problem the benchmark exists to solve. When gold data arrives, the dev set becomes a smoke test and nothing more.
3. **Do not tune against the held-out benchmark collection.** When gold data does arrive, development uses the development collection only. This is the whole reason the benchmark separates them.

### 11. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Model version drift breaks comparability.** A provider updates a model and last quarter's scores stop meaning anything. | The entire measurement programme silently loses its baseline. This is the risk most likely to be discovered too late. | Pin exact model versions. Version and store every prompt. Set temperature to zero where determinism is available. Record the full system version on every assertion. Re-run the benchmark whenever any of these change, and treat it as a new system version. |
| 2 | **Cost and latency at full coverage.** Scanning every chunk of every note may not be affordable at portfolio scale. | The architecture is right but unaffordable. | This is what §8 measures, before anything is built. Fallbacks: a cheaper detector, selective coverage by claim value, or batch processing. |
| 3 | **Cascade error propagation.** A mention missed at S2 can never be recovered downstream. | Silent recall ceiling, in a new place. | Deliberately over-generate at S2. Monitor the candidate-to-confirmed ratio at S3 — if it approaches 1, the detector is being too selective. |
| 4 | **Over-merging at S6/S7.** Two parties wrongly linked create a combined history no source supports. | Fabricated conclusions that people may act on; harder to detect than a missed link. | Require corroborating evidence beyond name similarity. Keep every link reversible with its evidence. Report merge and split errors separately, as the benchmark does. Ship S7 last. |
| 5 | **Hallucinated attributes.** Generative extraction can produce plausible values absent from the text. | Corrupted records; erosion of trust in the whole system. | Evidence binding at S5 makes every value checkable against its span. The benchmark's unsupported-value rate is the detector. Consider requiring that an extracted value appear verbatim in its cited span. |
| 6 | **Sensitive data in model prompts.** Notes contain personal data and Social Security numbers. | Compliance exposure. | Settle data-handling terms before any external model call. Coordinate with the benchmark programme's governance decision rather than answering it twice. |
| 7 | **The current-state description is wrong.** Part 1 comes from discussion, not a code audit. | The staging argument is built on it. | Engineering confirms or corrects Part 1 as the first task, before §8 is scoped. |
| 8 | **Optimizing what is easy to measure.** Metrics become targets and the system games them. | Scores improve while usefulness does not. | The benchmark reports several metrics precisely so no single one can be gamed in isolation. Watch precision and recall together, and pooled against per-claim results. |

### 12. What we need decided

| # | Decision | Needed by | Decided by |
|---|---|---|---|
| 1 | Current-state description confirmed or corrected (Part 1) | Before §8 is scoped | Engineering |
| 2 | Approval and sample scope for Experiment 1 (§8) | Immediately | Product + engineering |
| 3 | Which model tier for S2 detection, and whether a trained NER is in scope | From §8 findings | Engineering + data science |
| 4 | Data-handling terms for model calls over real notes | Before any run on real data | Governance + sponsor |
| 5 | Model and prompt version pinning policy (§11 risk 1) | Before stage B | Engineering + data science |
| 6 | Priority order across S5, S6 and S8 — which business outcome leads | Before stage C | Product Owner |
| 7 | Where the assertion store lives, and its relationship to the benchmark's data model | Before stage C | Data architects |
| 8 | Whether the graph is materialized in a graph engine or projected from relational storage | Before stage G | Data architects + data science |

### 13. What success looks like

By the end of stage E, against the same frozen benchmark release used for the baseline, we should be able to show:

- **Entity recall** materially up, with the gain concentrated in the long, high-note-volume claims where the retrieval ceiling was binding.
- **Conditional attribution accuracy** up, and separable from value accuracy — so we can state whether remaining errors are transcription or attribution.
- **Watchlist precision and candidate-conditional recall both up**, rather than one traded against the other, demonstrating that context beat thresholding.
- **Every reported assertion traceable** to a note and character offsets.
- **A rebuildable graph** whose every edge carries evidence, confidence and system version.

And — the point of running the two programmes together — each of those claims backed by a benchmark number produced by people who did not build the system.

