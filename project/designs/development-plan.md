# Development plan

Written after the first-principles audit
(`first-principles-claim-note-audit.md`), a contextual review of it, and a
verification pass over the claims both made. This is the plan of record; where
it disagrees with the audit, the disagreement is stated and reasoned.

## The objective, stated as the thing to be proven

> The system finds **every** entity mention, in whatever shape it arrives, on
> data it has never seen; extracts **every** piece of metadata attached to them;
> links mentions **and** metadata probabilistically; and stores the result as an
> entity knowledge map other products can build on.

Explainability is not the goal. It is the mechanism that makes the goal
checkable — a fact you cannot trace to characters is a fact you cannot verify
either. Where the two trade off, accuracy wins.

Near-term audience: data-science and architecture leaders, on synthetic notes.
That sets two constraints. The fidelity claim must be *measured*, not asserted.
And enterprise controls (RBAC, retention, encryption) are not built yet — they
are designed and gated on real data.

## The architecture is one spine

```
span  ->  mention  ->  assertion  ->  entity  ->  graph
```

Everything else is either a **lane** feeding one of those arrows (three
extractors, ten blocking rules, two vector indices) or **measurement** (leakage
guard, coverage ledger, audit). Five nouns. Keeping it that way is a design
constraint, not an aesthetic preference: every capability below must attach to
an existing arrow or justify a new one.

**The spine is currently cut between `assertion` and `entity`/`graph`, with a
bypass wire soldered across the gap.** Verified: `build_graph.py` contains zero
references to `assertions`. It builds edges from `entity_class` plus claim
co-presence, using five hardcoded predicates, while `relations.py` — which
extracts open-vocabulary, span-grounded triples — is called only from notebook
20.

So Phase 1 is a **deletion**. It removes a fabricated pathway and reconnects the
spine. The result has fewer concepts, not more.

## Verified findings this plan is built on

Each was checked against source, not taken from the audit on trust.

| # | Finding | Evidence |
|---|---|---|
| F1 | Graph edges are fabricated from `entity_class`, not derived from evidence | `build_graph.py` references `assertions` **0 times**; `ROLE_PREDICATE` maps class → predicate |
| F2 | Relation extraction is not on the operational path | `extract_relations` / `bind_to_mentions` called only from `20_relation_extraction.py` |
| F3 | A precision gate sits in the recall path | `_is_plausible_name` **drops** single-token names; measured `variant:short` 100% miss, `variant:last_only` 88% miss |
| F4 | Metadata binding is not probabilistic | identifier → mention binding is a hard same-line-or-previous-line rule, decided once in the extractor |
| F5 | Organization names go through a person-name comparison | `ForenameSurnameComparison(first_name, last_name)` where fields are `tokens[0]`/`tokens[-1]`; commonest org "surnames" are `llp`, `care`, `chiropractic`, `group`. 7,468 identical-surface edges, **4.6%** clear threshold |
| F6 | Identifier vocabulary is closed | gazetteer knows a fixed kind list; anything else is invisible |
| F7 | Graph predicate vocabulary is closed while extraction is open | 5 hardcoded predicates vs. open-vocabulary assertions — lossy by construction |
| F8 | Generality is unproven | 0.857 entity recall measured only on `corpus_gen` output, whose shapes we control |
| F9 | `case_informative` is computed and read by nothing | grep: written in `profiling`, no production consumer |

---

# Phase 1 — Reconnect the spine

The single highest-leverage phase. Converts the weakest claim ("the graph edges
are manufactured") into the strongest ("every edge traces to a span").

### 1.1 Split `entity_type` from `role` *(F1, F5)*

Replace the closed five-value `ENTITY_CLASSES` with:

- **`entity_type`** — structural and closed: `person`, `organization`, `asset`,
  `unknown`. Drives comparison strategy and the `cannot_link` constraint.
- **`role`** — open, **claim-scoped**, expressed as assertions with evidence
  spans, polarity and confidence. A person is not "an attorney"; they *act as*
  attorney on claim X, per this sentence.

This is the fix for both the fabricated role edges and the org-name
resolution failure. Touches `contracts.py`, `pipeline_v2.py` (`LABEL_TO_CLASS`,
`_classify`), `entity_resolution.cannot_link_reason`, `build_graph.py`.

Deletes the `_classify` fallback defect: `LABEL_TO_CLASS.get(label, "claimant")`
currently writes a guess into a field readers treat as a fact.

### 1.2 Put relation extraction on the operational path *(F2)*

`pipeline_v2` and the ingest path call `extract_relations` →
`bind_to_mentions` → persist as assertions. Unbound candidates go to a **review
queue table**, never dropped — same principle as orphan identifiers.

### 1.3 Make argument resolution visible *(new — not in the audit)*

`relations.py` already instructs the model to resolve pronouns and role
descriptors using chunk text and a claim roster. The gap is that **successful
resolution is invisible**: when the LLM resolves "the claimant" to "Edward
Vance", the output records the name with no indication that inference occurred.
An inferred binding is indistinguishable from a directly-named one.

Two mechanisms, deliberately redundant:

1. **`resolution_method`** on each argument — `explicit` | `within_chunk_coref`
   | `claim_roster` | `unresolved`. Self-reported by the model.
2. **Independent verification** — deterministic check of whether the argument
   string actually appears in the chunk. When the two disagree (model says
   `explicit`, name is absent), *that disagreement is itself a flag.*

Self-report alone is the model describing its own behaviour, which models
misreport. Verification alone loses the distinction between coref types.

### 1.4 Roster carries ids, not just names *(refinement)*

The roster becomes claim-scoped candidates with entity ids, observed aliases,
supporting mention ids and confidence. The LLM's selection is a **proposal,
never authority**.

Upside the audit did not name: argument binding becomes *constrained selection*
rather than post-hoc surface matching, which retires the weakest link in
`bind_to_mentions` — `_partial_surface_match`, a substring test with a 12-char
length tolerance.

Two guards: keep an **open-world escape hatch** (a party not on the roster must
still be expressible as free text, or the closed-vocabulary failure returns),
and **snapshot the roster per call** so bindings are reproducible. Source the
roster from mentions plus resolved candidates *with confidence*, so a bad
upstream resolution cannot silently poison future extraction.

### 1.5 Assertion-led graph, open predicates *(F1, F7)*

`build_graph` promotes **only grounded assertions** to semantic edges.
Co-presence role edges become an explicitly typed
`inferred_from_co_presence` layer, off by default in factual views.

The predicate vocabulary opens with it. `BANNED_PREDICATES` (provenance-as-edge)
stays; the five-value whitelist goes. Otherwise the knowledge map can only
express five relationship types no matter what extraction finds.

### 1.6 Move the name-shape filter out of the recall path *(F3)*

`_is_plausible_name` becomes a **flag, not a drop**. Directly serves the
"any shape" requirement, and it is the cheapest item in this phase.

The system's own principle is to buy recall at candidate generation and decide
precision later with a model. A hard drop applied after the union contradicts
that, and it measurably costs single-token names — the exact shape a real note
uses on second reference.

### 1.7 Open the identifier vocabulary *(F6)*

Add a generic **structured-token detector**: capture identifier-shaped strings
the gazetteer cannot classify, store as `kind='unclassified'` observations with
their span.

Real claim data carries policy numbers, other carriers' claim numbers, adjuster
codes, license plates, DOT numbers, provider ids in formats nobody enumerated.
Whatever was not listed is currently invisible. This is the orphan-identifier
principle applied one level up: record the observation, defer the
classification.

### 1.8 Kill the coref silent fallback

`coref.py`'s `auto` backend falls back silently to a naive rule measured at 43%
accuracy. Raise instead, matching the GenAI and NER lanes.

### 1.9 Re-measure everything

The type split invalidates prior B³ numbers **by design**. Take fresh ones, and
add two that did not exist:

- **Argument-binding accuracy** on the subset of ground-truth relations whose
  arguments are pronominal or descriptor-form. Report alongside — *not as* —
  coref accuracy: implicit resolution only surfaces where a relation exists, so
  its denominator differs from a dedicated coref pass. Comparing it to
  FastCoref's 43% would be exactly the apples-to-oranges number this project's
  posture exists to avoid.
- **Recall on the handwritten notes** *(F8)*. They were written to contain what
  the generator cannot produce and have only ever been used for relations. This
  is the only read on generalization. Expect a worse number; that is the point.

---

# Phase 2 — Make linking probabilistic everywhere

### 2.1 Per-type comparison strategies *(F5)*

Organizations get whole-string comparison with term frequency over the **full
name**, not a forename/surname split. Re-run the B³ threshold sweep.

Finally measure the embedding lane's contribution against ground truth via
`same_as_edges.blocked_by` — currently marked "not yet measured" in
`ARCHITECTURE.md`.

### 2.2 Probabilistic identifier binding *(F4 — the schema change)*

**The one item that changes a table, and the one that most deserves scrutiny
before it is built.**

Today, whether an NPI belongs to a provider mention is decided once, in the
extractor, by a same-line-or-previous-line rule, and stored as a hard
`subject_mention_id` or NULL. There is no probability anywhere. That directly
contradicts the requirement that mentions *and metadata* be linked
probabilistically — and it makes the same mistake as F3: trading recall for
precision at the candidate stage, which the architecture's own principle
forbids.

Proposed: `identifier_bindings` as a scored candidate table — features being
line distance, same-segment, segment kind, signature-block proximity, and
`entity_type` compatibility. `identifier_observations.subject_mention_id` becomes
the *materialized winner above threshold*, exactly as `entity_snapshot` is the
materialized view over `same_as_edges`.

That symmetry is the argument for the design: identity is already a
threshold-derived view over scored edges, and metadata attachment should be the
same shape rather than a special case.

**Open question worth settling first:** whether to train this jointly with
Splink (identifier agreement already feeds the mention comparison, so a scored
binding creates a feedback path) or as a separate calibrated model. Leaning
separate, for the same reason the ER model is frozen at backfill — but this
should be reasoned through, not defaulted.

### 2.3 Three-band operating policy

`auto-link` / `review` / `no-link` instead of a single threshold. Cheap now, and
it is the answer to the inevitable "what about wrong merges?" question.

---

# Phase 3 — Masking boundary and provenance

### 3.1 Masking as a deactivatable stage

`src/masking.py`. Deterministic pseudonymization of names and identifiers at a
configurable boundary, behind `MASKING_ENABLED = False`.

**Hard requirement: surrogates must be length-preserving.** Every downstream
`char_start`/`char_end` has to survive the transform unchanged, or evidence
grounding breaks and the audit chain goes with it. The alternative — masking
only at the model boundary with spans re-mapped on return — is more complex and
more fragile. Length-preserving surrogates make masking transparent to the
entire chain, and `07_audit` can verify it mechanically: round-trip a masked
corpus, assert every span check still passes.

Deterministic mapping also preserves ER behaviour, so it can be toggled **live**
in the demo. That is a strong moment in front of an architecture audience: the
answer to "what about PII?" is a switch, not a slide.

Not built now: encryption, RBAC, retention, provider-path controls. Those are a
one-page design doc, gated on real data.

### 3.2 Intake hardening and run records

Validate a manifest on `deliver()`; quarantine rather than `UNKNOWN`. Write one
immutable **run record** per execution: config, model versions, prompt versions,
input hashes. Small work, and it is what makes the end-to-end trace credible.

It is also the prerequisite for any cached derived artifact (see Phase 4.2) —
without version tracking, derived text silently rots.

---

# Phase 4 — The demonstration

### 4.1 One note, end to end

Source → version → mentions → assertions → resolved entity → graph edge →
dossier, every fact clickable to its raw span. Most rendering already exists
(`export_dossier_html`, the QA viewer).

### 4.2 Entity-level retrieval, if chunk-only proves insufficient

GraphRAG-style **generated** entity summaries stay deferred. When they enter, it
is as a clearly-typed derived layer that cites the assertion ids it summarizes,
never as a fact source — the same treatment as inferred co-presence edges.

Try the cheaper, fully-auditable version first: **embed the deterministic
dossier text** as the entity-level retrieval document. It aggregates cross-chunk
signal the way a generated summary would, but every sentence is template-rendered
from stored assertions.

Sequencing note: this only works *after* Phase 1. Today's dossier inherits
class-derived roles and links, so embedding it now would propagate exactly the
fabrications Phase 1 removes.

### 4.3 Metrics pack

Stratified recall/precision, B³ curve, orphan-identifier recall, argument-binding
accuracy, generality delta (synthetic vs. handwritten) — each with its caveat
stated. For this audience the honesty is the differentiator.

---

# Phase 5 — Client-data readiness

### 5.1 Revise the archived ground-truth plan

`designs/archive/ground-truth-plan.html` is a complete, costed six-week plan
built around the client's actual data, and its central premise is right: **their
entity list is a precision oracle, not a recall oracle.** Keep the gold/silver
tiering, the locator certification, the κ ≥ 0.75 gate, the capture–recapture
coverage bounds, and manifest-schema-v2 output so `audit.py` and `qa_viewer.py`
run unchanged.

Revise rather than replace: merge the audit's stratification additions (OCR
quality, negation/retraction, quoted text, source system), and account for
tooling that now exists in a different form than the plan assumes.

**Draft this in parallel with Phases 1–2, not after.** It is a document, not
code, and the client conversation it feeds has lead time — the ask should
already be on the table when the demo lands.

### 5.2 Client entity list as the first reference-data adapter

The list is not only evaluation input; it is reference data, and its
category/duty field can seed the open role vocabulary. NPPES registry lookup for
NPIs is the natural second adapter — free public data, and checksum-valid is not
the same as registry-real.

---

# Sequencing

| Phase | Gates on | Delivers |
|---|---|---|
| 1 | nothing — build now | evidence-grounded graph, open vocabularies, visible inference |
| 2 | Phase 1 | probabilistic linking of metadata; ER that resolves organizations |
| 3 | independent of 1–2 | demonstrable privacy boundary; auditable run records |
| 4 | Phases 1–3 | the stakeholder trace and the metrics pack |
| 5 | client data contract | defensible numbers on real notes |

The audit proposed gating implementation on a data contract and a relation
evaluation set. **Rejected for Phases 1–4.** Those gates govern *claims about
real notes*, not *mechanism construction*. The handwritten notes with
`expected_relations.json` are sufficient to build and smoke-test the evidence
path now, and blocking on client deliverables you do not control would stall the
demo that exists to win the team.

## Explicitly not doing yet

- Generated entity/community summaries — until the assertion→graph path exists
- Free LLM graph traversal on the factual path — unauditable; the claim-scoped
  structural agent stays
- Bitemporal completion — `DECISIONS.md` already states the gap honestly
- Enterprise privacy controls — designed in Phase 3, built on real data
- Removing `case_informative` *(F9)* — dead weight, not a defect; delete when
  something else touches `profiling`
