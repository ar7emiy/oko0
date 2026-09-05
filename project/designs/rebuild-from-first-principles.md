# Entity intelligence, from first principles

Written 2026-09-05, after two days of measurement on the existing system found
that **46% of labeled mentions sit inside an entity that fuses two or more
distinct real parties** (D34), and that the field used to prevent exactly that
is wrong for **69% of entities** (`entity_class`).

This document assumes nothing exists. It asks what the simplest system that
could hit the goal looks like, then says what to keep and what to delete.

Everything asserted here as fact was measured on the 60-document slice. Claims
that are reasoned rather than measured are marked.

---

## 1. The goal

> Give an investigator — human or AI agent — a **dossier** for any entity in
> the corpus, and let them research that entity's activity across every
> document, where every statement in the dossier traces back to the exact text
> that produced it.

Unpacking that into properties the architecture must have:

| property | what it means operationally |
|---|---|
| **Traceable** | every fact carries a document id and character span; you can always ask "why does the system say this?" and get text back |
| **Accurate** | a dossier describes *one* real party. Merging two people is worse than missing a link — a wrong dossier is actively misleading, a missing link is merely incomplete |
| **Complete** | every mention of an entity is findable, in whatever form it appears |
| **Corpus-wide** | activity is assembled across documents and claims, not per-document |
| **Inspectable** | a non-expert can see what the system decided and why |

**One addition to the goal as stated.** The system must also be able to say
*"I don't know."* An entity intelligence layer that silently guesses is worse
than one that flags uncertainty, because the investigator cannot tell the two
apart. Declining is a first-class output.

**The asymmetry that should drive every design decision:** an over-merge
corrupts a dossier — an investigator reads facts about four different people as
though they were one. An under-merge leaves two dossiers that are each
internally correct. **Both are errors; only one produces confident falsehood.**

---

## 2. The irreducible problem

Strip away implementation and there are exactly four questions:

1. **Where in the text is something worth recording?** (span detection)
2. **Which of those refer to the same real-world thing?** (identity)
3. **What does the text say about it?** (facts)
4. **How does a user get at that?** (query)

Everything else is machinery in service of these.

---

## 3. What the measurements force us to accept

These are not opinions. Each was measured in the last two days and each kills a
design option.

### 3.1 Names find candidates. Names do not decide identity.

| pair | name similarity | reality |
|---|---|---|
| William Anderson ↔ Samuel Anderson | 0.8933 | different people |
| Omar Jones ↔ Margaret Jones | 0.9086 | different people |
| Thomas Collision Center ↔ Lopez Collision Center | 0.9202 | different organizations |

The old system scored name agreement at **+4.6 bits**, among its strongest
evidence, and let it drive automatic merges. Four different Andersons became one
entity. **Name similarity is necessary for candidate generation and nearly
worthless as decisive evidence.** Any architecture that lets a name score merge
two records will reproduce this failure.

### 3.2 A classifier's label cannot be a structural constraint.

`entity_class` disagreed with itself on **69% of real entities**, and on **30%
of distinct surface strings** — the identical text `"lucas martinez"` was
labeled attorney, claimant, medical_provider *and* repair_shop. It was used as
an absolute merge veto (removed — wrong 70% of the time), embedded into the
vector text, and used to filter blocking candidates, which meant the recall lane
was structurally prevented from linking most people to themselves.

**Anything that must be consistent across occurrences must be computed
deterministically from something stable.** Context is not stable — it encodes
*role*, which genuinely varies by sentence.

### 3.3 The LLM is excellent at reading and unreliable at bookkeeping.

Measured:

| task | result |
|---|---|
| quoting the exact surface text | **100%** of 873 surfaces present verbatim |
| reporting character offsets | wrong roughly **2 in 3** |
| deciding who an identifier belongs to | **0.989** precision |
| assigning a closed-vocabulary class | 30% self-contradiction |

**Ask it to read and to judge locally. Never ask it for offsets, identifiers,
or labels that must stay consistent.** Deterministic code locates, validates,
and assigns ids.

### 3.4 Transitive closure makes one bad edge unbounded.

Connected components merged four Andersons because each shared a surname with
the next. In a transitive-closure model, **the blast radius of a single wrong
edge is the entire connected component.** That is not a tuning problem.

### 3.5 Aggregate metrics hid all of this.

B-cubed F1 read 0.907 while 46% of mentions were in fused entities. Entity count
read "42 vs 42 gold" — a coincidence, over-merges cancelling fragmentation. Four
separate times a headline metric preferred a broken system. **The architecture
must expose composition, not just totals.**

---

## 4. Design principles

Derived directly from §3.

1. **Evidence decides identity; names only propose it.** Automatic merges
   require validated shared identifiers. Name agreement raises a candidate for
   review, never a merge.
2. **Determinism where consistency matters.** Normalization, span location,
   type-from-name, identifier validation, id assignment — all deterministic and
   inspectable. Same input, same output, always.
3. **The model reads; code records.** LLM output is accepted as *quoted text
   plus a local judgment*, then grounded, validated and stored by code. Any
   assertion whose quote is not found verbatim in the source is rejected.
4. **Contain the blast radius.** No global transitive merge. Identity beyond a
   claim is an explicit, inspectable, reversible link.
5. **Everything is an evidence row.** Dossiers are views, not stored artifacts.
   Corrections are new rows, never mutations.
6. **Declining is an output.** Unknown type, unbound identifier, unresolved
   candidate — all first-class states, never silently guessed.

---

## 5. The architecture

### 5.1 The core move: entities are claim-scoped; cross-claim identity is a link

This is the one structural decision everything else follows from.

```
        CLAIM A                      CLAIM B
   ┌──────────────────┐        ┌──────────────────┐
   │ local entity 1   │        │ local entity 4   │
   │  "Marcus Lopez"  │◄──────►│  "M. Lopez"      │
   │  (attorney role) │  link  │  (attorney role) │
   └──────────────────┘ basis: └──────────────────┘
                        shared validated email
```

**Within a claim**, a name is nearly unambiguous — one file, one set of parties,
context-rich. Resolution here is high-precision and mostly deterministic.

**Across claims**, two records are linked only on *evidence*, and the link is a
row with a basis and a confidence — not a merge. A dossier spanning claims is a
**traversal** of those links at a chosen confidence, recomputed on read.

Why this is the whole ballgame:

- A wrong cross-claim link is **one visible edge**, not a corrupted blob. It can
  be inspected, downweighted, or rejected without rebuilding anything.
- Local dossiers stay correct even when cross-claim linking is wrong.
- It matches how an investigator actually reasons: *"this is the Lopez on this
  file; is he the same Lopez on that one?"* — a question with an answer and a
  reason, not an assumption.
- Four different Andersons cannot fuse, because nothing merges them: each is
  local to their own claim, and no shared identifier links them.

### 5.2 Components

Seven, in order. Each has one job.

| # | component | job | determinism |
|---|---|---|---|
| 1 | **Ingest** | text in, `doc_id → claim_id` map, content hash | fully deterministic |
| 2 | **Span detection** | find name-like and identifier-like spans; union of a validating gazetteer, a token NER model, and an LLM reader | model-assisted, span **located** deterministically |
| 3 | **Normalize & type** | one normalizer per identifier kind; `name_type` (person/organization/unknown) from the **string** | fully deterministic |
| 4 | **Local resolution** | cluster mentions **within one claim** into local entities | deterministic rules + narrow fuzzy match |
| 5 | **Fact extraction** | LLM reads a chunk and returns quoted evidence + subject/predicate/object *by name*; code grounds the quote and binds names to local entities | model reads, code binds |
| 6 | **Cross-claim linking** | propose candidate links; auto-accept only on validated shared identifiers; everything else to a review queue | deterministic accept rule; scored ranking |
| 7 | **Dossier / query** | views over evidence rows; traversal at a confidence threshold | fully deterministic |

### 5.3 Data model

Every row carries its evidence. There are no derived tables that cannot be
regenerated.

```
document        (doc_id, claim_id, occurrence_id, text_sha, n_chars)

span            (span_id, doc_id, start, end, text)
                -- verbatim. text == document[start:end], always, asserted.

name_mention    (mention_id, span_id, surface, norm, name_type, found_by)
                -- name_type in {person, organization, unknown}, from the string

id_mention      (mention_id, span_id, kind, value_raw, value_norm,
                 validation)          -- checksum | format | none

local_entity    (local_id, claim_id, canonical_name, name_type)
local_member    (local_id, mention_id, basis, confidence)
                -- basis: exact_name | name_variant | shared_identifier | ...

identity_link   (local_id_a, local_id_b, basis, evidence_span_id,
                 confidence, status)
                -- status: auto | review | accepted | rejected
                -- NOT a merge. A dossier traverses these.

assertion       (assertion_id, subject_local_id, predicate,
                 object_local_id, object_value, polarity,
                 evidence_span_id, method, confidence)
                -- attributes, roles, activities and relationships are all
                -- assertions. One table, open predicate vocabulary.
```

**`role` is an assertion, not a column.** *"Marcus Lopez acts as attorney on
claim CLM0010, per this sentence"* — claim-scoped, evidence-backed, and free to
differ across claims, which is what actually happens in the data.

**`name_type` is a column, because it must be stable**, and it is derived from
the name string alone so that identical strings always type identically.

### 5.4 How identity is decided

**Within a claim** — accept a merge on any of:
- identical normalized name
- one name is a token-subset of another *and* no competing candidate in the
  claim (i.e. "Lopez" is unambiguous here because only one Lopez exists locally)
- shared validated identifier

**and on nothing else — in particular, not on fuzzy name similarity.** That
exclusion is measured, not stylistic. Across all **395 claims**, only **5**
contain two distinct real entities whose names collide under the local rule —
and **all five collide only on fuzzy similarity**, none on exact match or token
subset:

| claim | pair | Jaro-Winkler |
|---|---|---|
| CLM0009, CLM0030 | Andrew Anderson vs Samuel Anderson | 0.893 |
| CLM0051 | Amara Rossi vs Dr. Amara Smith | 0.892 |
| CLM0062 | Katherine Rodriguez vs Katherine Reyes | 0.886 |
| CLM0076 | Nicholas Larkin vs Nicholas Martin | 0.911 |

**Drop fuzzy matching from the local rule and within-claim collisions go to
zero across the entire corpus.** Fuzzy name similarity is exactly the signal
that produced the four fused Andersons; it has no place in an automatic merge
at any scope. Name variants that genuinely need it ("Bob" vs "Robert") are
caught by the token-subset and shared-identifier rules, or go to review.

**Across claims** — auto-link *only* on a shared identifier that passes its own
validation (NPI checksum, VIN check digit, email, SSN). Everything else — name
agreement, shared address, shared phone — produces a **review candidate**,
ranked by a probabilistic score, never auto-applied.

This is where the probability model earns its place: **ranking a review queue,
not deciding identity.** That is a demotion from its current role, and it is
deliberate — the calibrated score was excellent at ranking and catastrophic at
deciding.

**Measured coverage.** Of the **231** ground-truth entities that appear in more
than one claim:

| | | |
|---|---|---|
| a **strong** identifier (email/npi/ssn/tin/vin) written in ≥2 of their claims | **187** | **81%** — auto-linkable |
| any identifier, including phone and address, in ≥2 claims | 222 | 96% |
| neither | **44** | **19% — must go to review** |

So identifier-only auto-linking connects **four out of five** cross-claim
entities on conclusive evidence, and hands the rest to a queue rather than
guessing. Widening the auto-link basis to phone and address would reach 96%, but
those are reusable — people move, numbers get reassigned — so that trade buys
recall with precision and should be a per-client setting, not a default.

### 5.5 Grounding rule

One rule, applied everywhere, no exceptions:

> A fact may be stored only if its evidence quote is found verbatim in the
> source document. The span is computed by locating the quote, never taken from
> the model.

This is already proven: it took mention span grounding from 33% to 100%, at zero
recall cost, because the model's *surfaces* were always right even when its
*offsets* were always wrong.

---

## 6. What this deliberately does not have

| omitted | why |
|---|---|
| `entity_class` | measured 69% self-inconsistent; every use was harmful or already removed |
| global clustering | one bad edge, unbounded damage (§3.4) |
| name similarity as merge evidence | four Andersons (§3.1) |
| a classifier in the identity path | consistency requires determinism (§3.2) |
| model-supplied character offsets | wrong 2 in 3 (§3.3) |
| a stored, mutable dossier | dossiers are views; corrections are new rows |

---

## 7. Failure modes, and what contains each

An architecture is only as good as its behaviour when it is wrong.

| failure | containment |
|---|---|
| two people wrongly linked across claims | one `identity_link` row, visible, reversible; local dossiers unaffected |
| two people wrongly merged **within** a claim | bounded to one claim; requires a local name collision, which is rare and reviewable |
| entity missed entirely | union of three detectors; scan-coverage ledger reports unmapped text |
| identifier bound to the wrong party | binding method recorded per row; declining is allowed and measured |
| model hallucinates a fact | rejected at the grounding rule — no quote, no row |
| type wrong on an ambiguous name | `unknown` is a real state; unknown does not cross type boundaries |
| aggregate metric hides a defect | composition reported alongside totals: over-merge rate, entities-per-dossier, link basis mix |

---

## 8. Migration — what survives from the current system

Most of the extraction layer is sound. The identity layer is what needs
replacing.

**Keep, unchanged:**
- validating gazetteer (identifier recall **1.000**, checksums on NPI/VIN)
- three-detector union for names
- **locate-the-quote** span grounding (100%)
- LLM identifier binding (**0.989** precision, declines when unsure)
- relation extraction lane — qualitatively strong, currently unwired
- scan-coverage ledger
- stage narration

**Delete:**
- `entity_class` from the identity path — embedding text, blocking filter, veto
- global connected-components clustering
- the person-name comparison model applied to organizations

**Build:**
- `name_type` from the string (the org-suffix lexicon already exists)
- claim-scoped local resolution
- `identity_link` table + traversal
- review queue
- composition metrics

**Demote:**
- the probabilistic model — from deciding identity to ranking review candidates

---

## 9. What would falsify this design

Stated in advance, so this document can be proven wrong rather than argued
about.

1. ~~**If within-claim name collisions are common**~~ — **RUN, passed.** 5 of
   395 claims (1.3%) contain a colliding pair, and all five collide only on
   fuzzy similarity. Under the rule as stated (exact / subset / identifier,
   no fuzzy), **zero claims collide**. This is what promoted §5.1 to measured
   and sharpened the local rule.
2. ~~**If identifiers are too sparse to link across claims**~~ — **RUN,
   passed with a caveat.** 81% of cross-claim entities carry a strong
   identifier written in two or more of their claims and are auto-linkable;
   **19% (44 of 231) require review.** That is a real workload, not zero, and
   it makes falsifier #3 the live risk rather than this one.

   *Note on generality:* this corpus is synthetic and identifier-rich by
   construction. A client corpus may be far sparser, in which case the review
   queue grows and the phone/address auto-link setting becomes load-bearing.
   **Re-run this measurement on client data before promising the 81%.**
3. **If the review queue is larger than a human can process**, "escalate to
   review" is a euphemism for "drop." *Test:* candidate volume per 1,000
   documents at the proposed thresholds.
4. **If dossier traversal is too slow at corpus scale**, computing identity on
   read stops being viable and some materialization returns. *Test:* traversal
   latency at 10x, 100x the current corpus.

Each is measurable before the corresponding component is built. Per the standing
rule on this project: **for anything tagged reasoned or assumed, run the query
before writing the code.**

---

## 10. Confidence

| section | basis |
|---|---|
| §3 (what the measurements force) | **measured** — all figures from the 60-doc slice, last two days |
| §5.1 claim-scoped entities | **measured** — falsifier #1 run: 5 of 395 claims collide, all fuzzy-only; zero under the stated rule |
| §5.4 identifier-only auto-link | **measured** — falsifier #2 run: 81% auto-linkable, 19% to review |
| §5.5 grounding rule | **measured** — 33% → 100%, zero recall cost |
| §7 containment | **reasoned** — properties of the structure, not observed behaviour |
| §8 keep-list | **measured** — each figure cited |

The honest summary: the *diagnosis* is measured and solid. The *prescription* is
reasoned from it, and its two load-bearing assumptions (§5.1, §5.4) have named
tests that should be run before building either.
