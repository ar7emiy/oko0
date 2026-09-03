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
- **Auditing this system?** Read `AUDITOR-BRIEF.md`, not this file. This board
  is the builder's account; read it *last*, after the source, or you will only
  find the gaps already inside the builder's frame. Write findings to
  `audits/YYYY-MM-DD-<slug>.md` and never edit this file or `HANDOFF.md`.

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
| D4 | Identifier binding was a line-proximity rule: precision 0.747 → **0.940** with the LLM lane (llm sub-lane 0.969) | me | ✅ **fixed** — binding lane shipped |
| D5 | `POLARITIES` conflates polarity + evidentiality + lifecycle | B | open |
| D6 | Vector-only retrieval; no lexical/exact lane; `who_is_at()` never called | B, me | **partly fixed** — exact lane wired (T3.2); lexical/rerank still open |
| D7 | Locale model hardcoded, zero external resource loading | me | open |
| D8 | Entity IDs change when mentions arrive | B | open, **contested** |
| D9 | Two disconnected coref mechanisms | me | open |
| D10 | Chunking discards the structure profiling computed | me | open |
| D11 | No per-client config; corrections never feed the system | B, me | open |
| D12 | `_is_plausible_name` drops single-token names | A, me | open |
| D13 | Cluster-level consistency guard lost in v1→v2 | B | **measured — reframed.** The one violation is caused by D4, not by clustering. Guard would split a correct cluster |
| D14 | Splink training completeness never checked | B | ✅ **fixed** — reported per-run and per-edge; 7 untrained parameters named |
| D15 | `who_is_at` normalized differently than the indexer, so phone and address lookup returned `[]` **always** | me, via T3.2 | ✅ **fixed** |
| D16 | An `identifier_observations` row has `kind=phone, value_raw="voicemail"` — identifier extraction has a precision leak | me, via T3.2 | open |
| D17 | **The match prior was 16× too low**, so every edge lost ~4 bits and 42 entities were split into 515 | me, via T0.4 | ✅ **fixed** — B-cubed F1 at the operating threshold 0.604 → 0.800 |
| D18 | `u` is inflated 3–37× by match contamination in the random-pair sample | me, via T0.4 | open — ceiling measured (+0.026 F1), no label-free estimator yet (T0.5) |
| D19 | **TIN was blocked but never compared** — it proposed candidates and then contributed zero evidence to their score | user, via T0.4's evidence report | ✅ **fixed** — now +2.21 bits |
| D20 | **`address_key` compared by ExactMatch only** — one opaque `number|street|zip` composite, so a missing zip earned *no* evidence rather than less, while a city-only address exact-matched every address in its zip | user, via T0.4 | ✅ **fixed** — graded four-level comparison over decomposed components |
| D21 | **SSN and VIN were declared in the ground-truth manifest but never written into any note** — zero occurrences across all 2,000 notes; `corpus_gen` minted them as entity attributes and never placed them, and its VIN values failed their own ISO check digit so a validating detector would have scored 0% on a fixture that looked correct | me, via D19 | ✅ **fixed** — 526 notes now carry an SSN, 359 a check-digit-valid VIN |
| D22 | **`policy_number` matched ordinary prose** — under `re.I` the pattern accepted any 5+ letter word after "policy", so "policy vehicle" and "policy holder" scanned as policy numbers and were sent to the LLM binding lane to have owners assigned | me, via D21 verification | ✅ **fixed** — the captured part must now contain a digit |
| D23 | **No identifier VALUE is ever written two ways.** Formats do vary across the corpus (phones appear as `(312) 555-0142` 967× and bare 10-digit 395×; dates in both numeric and written form) — but each individual value keeps one spelling everywhere it occurs: 0 of 1,341, against **92% of entities appearing under multiple name surfaces**. So `normalize_identifier`'s actual job, reconciling two spellings of one value, is never exercised | me, via T0.7 | open — **explains T0.7's flat result**; the largest fixture gap on the board |

**Scaling, not correctness:** `filter_fn` is an O(total-chunks) metadata scan per
query; `entities_in_chunks` iterates every mention per query.

---

## Current state, factually

Verified by grep/execution, 2026-09-02.

| | value | conditions |
|---|---|---|
| identifier recall (finding) | 1.000 | synthetic, 2000 notes |
| identifier **binding** precision | **0.940** (LLM lane **0.969**) | in-pipeline vs GT, 8 docs; was 0.747 under the line rule. **Not yet checked on the handwritten notes** — the only read on generality |
| entity recall | 0.857 | synthetic only — generality unproven (D-gen) |
| scan coverage | 100% chars/doc | — |
| **B³ F1 at the operating threshold (0.45)** | **0.800** (P 0.888 / R 0.728) | 60-doc subset, post-T0.4. Was **0.604** (P 0.973 / R 0.438) |
| **entities vs ground truth @ 0.45** | **81 vs 42 = 1.9×** | same subset. Was **515 = 12.3×**. Residual over-split is D18 |
| **B³ F1 floor across 0.20–0.95** | **0.783** | the curve is flat post-T0.4; was **0.185** |
| **match prior λ** | **0.026** | estimated 0.0264 against a measured 0.0121; was 0.000764 |
| identical-surface pairs above threshold | **4.6%** of 7,468 | the D1/D5 org-name failure |
| single-note ingest | 18.5s | 60-note corpus, live models |
| full-corpus (2,000-note) figures | **not re-measured** | the full run is hours (T0.6); every row above the ingest line is the 60-doc subset |

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

### T0.4 Splink calibration *(D14 — and D17, which the investigation found)*
**Status:** ✅ **shipped** · **Confidence:** measured end-to-end

Started as the small item the heading says: read the *"your model is not yet
fully trained"* warning instead of letting it scroll past. Measuring first — the
standing rule — turned up **a much larger defect sitting behind it**, and the
original item turned out to be the minor half.

#### What was measured

Persisted model inspected parameter by parameter, then every candidate fix run
end-to-end and scored with B-cubed against ground truth. In evidence terms:

| agreeing field | was worth | should be worth |
|---|---|---|
| exact name | +4.96 bits | +8.22 |
| exact phone | +3.07 bits | +8.26 |
| exact address | +2.95 bits | +7.54 |
| **exact NPI** | **+2.73 bits** | — (m never estimated) |
| exact email | +2.57 bits | +4.11 |

An exact match on a **nationally unique provider identifier** counted for
*little more than half* an exact match on a name. The ordering was inverted
against every intuition about what identifies a person.

#### Root cause — **D17, the match prior**

`probability_two_random_records_match` (λ) is estimated from deterministic rules
and then applied to every posterior. The shipped rules were
`[email, npi, full_name AND dob]` — the textbook choice, and on this corpus
**the fields that are nearly always absent**: email is non-null on 55 of 922
mentions, npi on 7. The rules barely fired.

    λ estimated  0.000764        λ in truth  0.012097          16x low

Nothing compensates for a wrong prior. EM re-fits `m` against whatever `u` it is
handed, so `u` errors partly wash out; λ is applied at the end and simply shifts
the entire distribution down ~4 bits.

#### Result, through the shipped code path

| | at threshold 0.45 | entities | flatness (min F1, 0.20–0.95) |
|---|---|---|---|
| before | F1 **0.604**, P 0.973, R 0.438 | **515** | **0.185** |
| after | F1 **0.800**, P 0.888, R 0.728 | **81** | **0.783** |

42 is the truth for this 60-document subset, so the system was splitting one
entity into **twelve** while reporting 0.97 precision for it — because B-cubed
precision *rises* under over-splitting, which is exactly why a precision number
alone cannot be trusted as a health check. It is still ~1.9× over-split after
the fix; that residue is T0.5.

The curve also stops being a cliff, which is what lets a shipped threshold
survive contact with a client's data.

**`ER_LINK_THRESHOLD = 0.45` needed no change** — it was never the bug, it was
downstream of it. Its config comment had drifted into describing a curve the
system no longer produced; that comment now carries the correction.

#### Rejected, with reasons

- **Let EM train `u` too** (`fix_u_probabilities=False`). Measured F1 0.80 →
  **0.64**; produces `name_sorted` m=0.0 and −44-bit weights. EM sees only the
  *blocked* population, which is not remotely representative. `u` stays fixed.
- **Splink's `populate_probability_two_random_records_match_from_trained_values`.**
  Returns λ = **0.619** — it claims 62% of random mention pairs co-refer. Scores
  acceptably at 0.45 by accident and peaks at 0.99, destroying the threshold's
  meaning. A prior nobody can defend out loud is not a calibration.
- **Estimate `u` on a deduplicated frame** (the textbook remedy for
  match-contaminated `u`). Not viable here: the deduplicated frame is 42 rows and
  contains no identifier pairs at all, so Splink cannot observe the
  email/phone/npi/address levels. **The remedy fails precisely on the columns
  that need it.**

#### Shipped

`entity_resolution.lambda_rules()` (name-led rules that actually fire, with the
measurement in the docstring) · `training_completeness()` · `calibration_report()`
· λ and the evidence ordering logged **every run** · `calibration` block in the
run output · `same_as_edges.uncalibrated` naming the untrained comparisons an
edge actually used · `CFG.ER_REQUIRE_FULLY_TRAINED` to make it fatal · a failed
λ estimate now **raises** instead of falling through to Splink's 1e-4.

The per-edge flag is selective by design: **2 of 14,895 edges**, both `npi`. A
blanket flag would have been alarmist and useless for triage.

**Falsification test that now exists:** the run output states λ and the bits each
agreeing field is worth. If an identifier is ever worth less than a name, that is
visible without reading the code.

### T0.5 Correct `u` for match contamination — the remaining calibration gap
**Status:** open · **Confidence:** measured (ceiling quantified, no label-free
implementation yet)

**Current.** `estimate_u_using_random_sampling` estimates *P(agree | non-match)*
by sampling random pairs and treating them all as non-matches. Valid when λ ≈
1e-4; here λ ≈ 1.2e-2, so the sample is ~1.2% true matches and those inflate `u`.
Measured against ground truth: **phone 36.9× too high, address 18.3×, name
13.8×, dob 4.2×, email 2.6×.**

**Why it is second-order, not first.** EM re-fits `m` under whatever `u` it is
given, so the *ratio* partly survives. With λ fixed and `u` oracle-corrected
(override verified to survive training):

    λ corrected only        best F1 0.8109   @0.45 0.8002
    λ + u corrected         best F1 0.8387   @0.45 0.8064

**+0.026 F1** — and, more usefully, the 0.99 cliff disappears (F1 0.80 instead of
0.29), because the mass of true pairs stops being crushed below the top of the
scale.

**Blocked on:** no label-free estimator yet. Dedup-frame sampling is out (see
above). The open candidate is a two-pass scheme — cluster once, then compute `u`
analytically over cross-cluster pairs (424k pairs on this corpus, exact, no
sampling) — but the pass-1 threshold has to be chosen without labels, and a naive
fixed-point iteration is bistable: started from the shipped λ it converges to the
broken value.

**Falsification test.** Compare the two-pass `u` against the GT-derived `u` on
this corpus; require within 3× on every column, and require F1 ≥ 0.83.

---

### T0.6 The regression gate takes hours, so it does not get run
**Status:** open · **Confidence:** measured

**Current.** `tests/smoke_test.py` regenerates the full 2,000-note corpus and
re-extracts all of it through the LLM lanes. Measured during T0.4: **~46 model
calls per minute**, and the run was still inside Layer 1 after 50 minutes with
zero mentions committed. It was abandoned, and T0.4 shipped behind a **scoped**
regression over 60 documents instead.

**Problem.** A gate nobody can afford to run is not a gate. This gets *worse*
with every LLM lane added — the identifier binding lane (T1.2) added one call
per chunk containing identifiers, and the relation lane will add more. The
failure mode is not that the test breaks, it is that it stops being run and
changes ship on scoped checks whose coverage nobody has audited.

**Also measured, and worse:** the assertions themselves were insensitive to the
defect T0.4 found. `assert best["bcubed_f1"] > 0.6` passed at **0.79** while the
operating threshold was splitting 42 entities into 515, because B-cubed
precision *rises* under over-splitting and the sweep's best point sat far from
where the system actually runs. Fixed as part of T0.4 — the gate now checks the
entity count at the operating point and the calibration block — but the lesson
generalises: **assert at the operating point, not at the best point on a curve.**

**Proposed.** Split into tiers. A `--tier=fast` covering the invariants over a
fixed 60-document subset (minutes, run on every change), and the full-corpus run
as a deliberate, separately-invoked job whose numbers refresh `ARCHITECTURE.md`.
The subset must be fixed and named, not "the first N", so its numbers are
comparable across runs.

**Falsification test.** The fast tier must catch every defect the full run would
on the scoped corpus — verify by re-introducing the T0.4 prior bug and
confirming the fast tier fails.

### T0.7 Identifier comparisons: TIN, SSN, VIN and a graded address *(D19–D21)*
**Status:** ✅ **shipped**, benefit **not demonstrated** · **Confidence:** measured

**Found by the user**, reading T0.4's new evidence report and asking *"why NPI
only? where is SSN, TIN, address, city, state, zip?"* — which is exactly the
question that report exists to provoke.

**Current, before.** `comparison_specs` scored name, email, phone, npi,
address_key and dob. Checked against the schema and the corpus:

| kind | detected | blocks | **scores** | can veto |
|---|---|---|---|---|
| phone | ✓ | ✓ | ✓ | – |
| address | ✓ | ✓ | ✓ *(exact only)* | – |
| email | ✓ | ✓ | ✓ | – |
| VIN | **✗ no detector** | ✗ | **✗** | ✗ |
| SSN | ✓ | ✗ | **✗** | ✓ |
| NPI | ✓ | ✓ | ✓ | ✓ |
| TIN | ✓ | ✓ | **✗** | ✓ |

SSN could only ever *veto* a merge, never support one. TIN proposed candidates
and then contributed nothing to their score. NPI — scored — is the rarest kind
in the corpus. None of this was a decision: `comparison_specs` documents why
`entity_class` is excluded and is silent on TIN and SSN.

**Shipped.** `tin`, `ssn`, `vin` comparisons; a VIN detector with a real ISO 3779
check digit; `textnorm.address_parts` decomposing street/city/state/zip; and a
graded four-level address comparison replacing the all-or-nothing ExactMatch.
One comparison with ordered levels, **not four independent ones** — the
components are heavily correlated and Fellegi-Sunter assumes conditional
independence, so four would price one piece of evidence four times.

**Measured, and the honest answer is: barely anything.**

| | before | after |
|---|---|---|
| B³ F1 @ 0.45 | 0.810 | **0.812** |
| best B³ F1 | 0.861 @ 0.8 | **0.863 @ 0.8** |
| entities vs 43 gold | 1.35× | 1.37× |

**+0.002 is noise.** TIN was the only genuinely new trained signal (+2.21 bits,
25 mentions) and the address regrade moved its top level from ~+3.1 to +4.56
bits. Report it as shipped, not as an improvement.

**The interesting failure.** The first attempt put `ssn` and `vin` at the TOP of
the evidence ordering at **+10.00 bits each** — and both were entirely fabricated.
Neither column has a single value in this corpus, so EM could train nothing and
Splink substituted its two-level default (m=0.95, u=0.0009 → +10 bits). A change
meant to add evidence instead added *the strongest signal in the model, invented*.
**T0.4's own instrumentation caught it within one run**, which is the clearest
argument yet for reporting bits-per-field.

Fixed by `_prune_absent`: a comparison whose columns are entirely NULL in this
corpus is dropped rather than trained on nothing. Substituted parameters went
18 → 10. This is also the tunable-object behaviour — a client whose notes carry
SSNs gets that comparison trained on their data; one whose notes do not is never
shown a fabricated weight for it.

**Blocked on D21.** SSN and VIN cannot be measured at all: the manifest declares
125 and 140, and **zero appear in any of the 2,000 notes**. `corpus_gen` mints
them as entity attributes and never places them, and its VIN values fail their
own check digit. Until that is fixed, both lanes are correct-by-construction and
untested — say so rather than counting them as coverage.

**Falsification test.** Fix D21, re-extract, and require the SSN lane to
measurably raise recall on the entities that carry one. If it does not, the lane
is decoration and should be removed rather than kept for completeness.

**Also shipped alongside:** `model_signature` / `check_model_current`. Changing
`comparison_specs` invalidates the frozen model the ingest path scores arriving
notes with, and nothing detected that — the store would have accumulated edges
calibrated two different ways with no way to tell them apart. Ingest now refuses
a stale model instead.

### T0.8 The fixture never varies an identifier's surface *(D23)*
**Status:** open · **Confidence:** measured

**Measured, and stated precisely.** Formats *do* vary across the corpus — phones
appear as `(312) 555-0142` 967 times and as a bare 10-digit run 395 times; dates
appear both numerically and written out. What never happens is the case that
matters: **0 of 1,341 identifier values is written two different ways**. Each
phone, address, email, SSN, VIN, NPI and TIN keeps one spelling everywhere it
occurs. For contrast, **472 of 512 entities (92%) appear under more than one name
surface** — order flips, nicknames, initials, titles.

So the corpus has format *diversity* without per-value *variation*, and it is
per-value variation that identifier matching exists to survive.

**Why it matters more than it sounds.** The fixture was built to stress *name*
matching and it does that well — which is why the name comparison model is the
elaborate part and why its numbers move. The identifier half of the system is
validated only against its best case:

- `textnorm.normalize_identifier` cannot be tested at all. There is nothing to
  normalize, so every regression in it is invisible. (D15 — `who_is_at`
  normalizing differently from the indexer, so *every* phone and address lookup
  returned `[]` — lived undetected in exactly this blind spot.)
- The graded address comparison (T0.7) has nothing to grade: ExactMatch already
  catches 100% of these addresses. **This is the explanation for T0.7's +0.002.**
- On real claim notes, `(312) 555-0142` / `312-555-0142` / `312.555.0142` /
  `3125550142` are the *same* phone, and addresses vary at least as much. That
  variation is where identifier matching either works or does not, and this
  corpus contains none of it.

**Proposed.** Plant surface variants for identifiers the way the fixture already
plants them for names, from a per-kind variant generator: phone punctuation and
groupings, `ext.` suffixes, address abbreviation and suite/zip presence, email
casing, SSN with and without hyphens, VIN with a lowercase run.

**Falsification test.** With variants planted, identifier recall must stay at
1.000 and the graded address comparison must show a measurable B-cubed gain over
ExactMatch. If recall drops, `normalize_identifier` has a real defect the current
fixture cannot see — which is the point of the item.

**Not a bug in the generator so much as an unstated assumption**: whoever built
the variant machinery applied it to names and stopped. Worth checking whether
the same is true of dates and monetary amounts.

# Phase 1 — Reconnect the evidence path

The spine is `span → mention → assertion → entity → graph`, currently cut between
`assertion` and `graph` with a bypass wire across the gap. This phase is a
**deletion**: it removes the fabricated pathway. Full reasoning in
`development-plan.md` §1.

| item | what | confidence |
|---|---|---|
| T1.1 | Split `entity_type` (closed, structural) from `role` (open, claim-scoped, evidence-backed) *(D1, org-name failure)* | measured |
| T1.2 | Relations onto the operational path; **identifier binding lane ✅ DONE** *(D4)* | measured |
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

### T2.2 — ✅ **RESOLVED by measurement: Outcome 1. No schema change.**

The board defined three outcomes and gated the build on measuring which held.
Measured, against ground truth, on the same eight documents:

| | precision | bindings offered | when unsure |
|---|---|---|---|
| line rule (`subject_for`) | 0.830 | 53 — and 24 left unbound | binds the nearest name, silently |
| **LLM (gazetteer finds, LLM binds)** | **0.973** | **111** | **declines** — 4 empty-owner cases |

Corpus-wide the line rule is worse than that sample suggests: **precision 0.747,
recall 0.371**. Of 176 orphans, **144 had their owner named within 300
characters** — 82% of "orphans" are misses, not true orphans.

**The error *kinds* differ more than the rates.** The LLM's 3 errors are all
person-vs-their-own-firm (`3764 Oak Ave` → "Delgado Legal Partners" where GT says
"Anthony Okonjo"; the firm's office address — arguably both are right). The line
rule's errors are category errors: an attorney's email bound to the **claimant**,
a provider's address to the **claimant**, the claimant's phone to a **repair
shop**. The `fatima.martin@harborvance.com` → "Grace Martin" case is the shape of
it — an email whose local-part names its owner, bound to a different person who
happened to sit closer on the page.

**So: Outcome 1. T1.2 is the entire fix.** Gazetteer finds and validates (a Luhn
check is decidable and not a model's job); the LLM binds with an evidence span;
line proximity demotes to a feature. **No `identifier_bindings` table, no scored
candidate model, and the joint-vs-separate calibration question does not arise.**

The plan proposed the schema change *as the plan* before this measurement
existed. Recorded as an over-engineering error, twice avoided now — once by
noticing the discard, once by measuring before building.

**One correction to how this was previously described.** I wrote that the LLM
"already produces these bindings and we throw them away." Not quite: bypassing
the code filter yielded **zero** identifier relations, because `relations.PROMPT`
also instructs *"Do NOT extract identifiers as relations… Skip those."* The
discard is belt-and-braces — forbidden at the source **and** filtered downstream.
The capability is **latent**, not actively produced and discarded. The
recommendation is unchanged; the characterisation was overstated.

**Falsified if.** The 0.973 does not hold on the handwritten notes, whose shapes
`corpus_gen` does not produce. Worth checking before this number is quoted.

### T1.2 identifier binding — ✅ **DONE**

Shipped as `relations.bind_identifiers` / `bind_identifiers_many`, wired into
`pipeline_v2` ahead of the line rule. Gazetteer finds and validates; the LLM
binds with an evidence span; line proximity is the fallback.
`identifier_observations.binding_method` records which lane decided each row.

Measured in-pipeline over 8 documents against ground truth:

| lane | correct | wrong | precision |
|---|---|---|---|
| **llm** | 63 | 2 | **0.969** |
| line_rule (fallback only) | 0 | 2 | 0.000 |
| — | | | **overall 0.940**, up from 0.747 |

96 bound by the LLM, 36 by the fallback, 34 left unbound. The lane offered 154
bindings and **declined 42** — declining is the behaviour that makes it safe.

Both LLM "errors" are the same case: bound to `'Tony Okonjo'` where ground truth
says `'Anthony Okonjo'` — a nickname variant of the *correct* person. So 0.969
is a floor, not a ceiling.

**Open question, deliberately not settled: should the line rule be a fallback at
all?** It runs only where the LLM declined — i.e. on the cases the model judged
unclear — and scored **0/2** there. An LLM decline is information ("the text does
not say"), and overriding it with a rule measured at 0.747 corpus-wide may be
worse than leaving the identifier unbound, which is a supported state. n=2 is far
too small to act on. Measure over the full corpus before changing it.

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
- **A `dob` conflict veto.** A person has exactly one date of birth, so a differing
  DOB looks like it belongs in `cannot_link_reason` alongside npi/tin/ssn. Held
  back on purpose: DOB binding accuracy has never been measured, real DOBs carry
  transcription errors, and **T0.3 measured what a consistency rule does when it
  meets a mis-bound identifier — it splits a correct cluster.** Revisit after
  measuring dob binding, not before. The full veto policy, including why `vin`
  scores but must never veto (a claimant owns two cars; a shop touches hundreds),
  is documented on `cannot_link_reason` and in diagram 07.
