# Independent follow-up audit — evidence, artifacts, and incomplete facts

**Audit baseline:** committed `9e847c6` (`T0.9: collapse comparison levels EM
never observed`) on `audit-full-system-architecture`, read 2026-09-03. This is
a fresh source-first review after the fixes since the prior audit. It makes no
source, configuration, test, status-board, or handoff changes. No Gemini call
or full pipeline run was made.

## Verdict

The system is materially stronger than at the prior audit: it now rejects
unavailable embedding backends, records calibration gaps per edge, derives
identity as a re-computable view, and has repaired real span-grounding and
incremental-index defects. The remaining risk is now less about a missing model
and more about contracts between stages. A timestamp can still become a DOB;
the answer path can call an answer "grounded" without establishing that its
claims are supported; a tunable embedding setting can silently mix two vector
generations during incremental ingestion; and the planned relation path cannot
persist its own documented unbound-subject case. Each breaks a different part
of the product promise: retain every fact, link it probabilistically, expose
the evidence, and safely tune the object to client data.

| rank | finding | severity | status | primary evidence | falsification test |
|---|---|---|---|---|---|
| 1 | Written dates in email `Sent:` headers still route to a person's DOB. | Critical | **measured** | `src/pipeline_v2.py:47-50, 449-485`; 426/426 raw-corpus written-date matches are within 45 characters of `Sent:`. | Process a `Sent: Wed, Mar 10, 2026` fixture. The finding is false only if that span cannot create `kind='dob'`, `has_dob`, or an ER DOB feature. |
| 2 | Citation coordinates are verified, but the answer text is neither cited claim-by-claim nor checked for support; an uncited answer can be reported as grounded. | Critical | **reasoned** | `src/agent.py:267-280, 282-321`. | Stub the answer model to return an unsupported answer with `citations=[]` or one unrelated valid span. The finding is false if `answer()` rejects/withholds the answer and never reports `citation_check.grounded=True`. |
| 3 | Incremental ingest accepts a changed embedding model or vector-construction setting without versioning/rebuilding the old mention vectors and buckets. | High | **reasoned** | `src/embed_index.py:63-127`; `src/entity_resolution.py:189-232`; `src/incremental.py:108-130`; `config/00_config.py:64, 208-258`. | Backfill, alter only `EMB_BLOCK_CONTEXT_CHARS`, `EMB_BLOCK_SIM`, or a same-dimension `EMBED_MODEL`, then ingest one note. The finding is false if it raises a compatibility error before append, or atomically re-embeds/re-buckets every prior mention under a recorded new generation. |
| 4 | The relation contract promises to retain unbound subjects, but the only assertion table requires a non-null subject mention. | High | **reasoned** | `src/relations.py:386-418`; `src/contracts.py:128-147, 392-412`. | Bind a `RelationCandidate` whose subject is absent from `mentions`, then persist it through the intended assertion path. The finding is false if the evidence and null subject are retained without a guessed surrogate or an integrity error. |

## 1. A header timestamp is still identity evidence

This is a re-check of the prior audit's highest-severity observation, because
the current committed routing map is unchanged:

```python
# src/pipeline_v2.py:47-50
"date": "has_dob",
"date_written": "has_dob",
```

Every mapped span then reaches the identifier persistence loop
(`src/pipeline_v2.py:449-485`), where `has_dob` becomes `kind_i='dob'`. The
write-time shape check asks only whether a DOB has four digits
(`src/gazetteers.py:128-151`); it does not distinguish a birth date from an
email-header date. `build_mention_frame()` later consumes observations and
`has_dob` assertions as the resolution `dob` feature
(`src/entity_resolution.py:75-91`).

I re-ran a no-API scan over the raw corpus using the current written-date
pattern. It found 426 matches; **all 426** occur within 45 characters of a
`Sent:` header. Examples were `DOC00001: Sent: Wed, Mar 10, 2026`,
`DOC00003: Sent: Wed, Jun 17, 2026`, and
`DOC00005: Sent: Fri, Apr 11, 2026`.

This is not a recall-versus-precision trade. The character sequence was found
correctly but typed incorrectly. A record timestamp is a temporal fact; it is
not personal identity evidence and must never contribute to an entity-match
feature just because it shares a date shape with a DOB.

The concrete regression fixture is a note with a known email sender and the
single header date above. After processing, inspect:

```sql
SELECT kind, value_raw, char_start, char_end
FROM identifier_observations
WHERE doc_id = :fixture_doc;

SELECT predicate, source_span_start, source_span_end
FROM assertions
WHERE source_doc_id = :fixture_doc AND predicate = 'has_dob';
```

The current implementation fails the intended criterion if either returned span
covers `Mar 10, 2026`; a downstream frame inspection must additionally show
no `dob` feature originating from it.

## 2. A valid coordinate is not evidence for an answer

The D0b fix is real and valuable: `_verify_citations()` proves a submitted
coordinate parses, names an existing document, lies in bounds, and was inside
retrieved evidence (`src/agent.py:282-321`). That prevents a citation to a
document the model never saw.

It does not establish the next necessary claim: that *the answer says only what
those coordinates support*. `_synthesize()` returns `data["answer"]` unchanged
(`src/agent.py:267-280`). It validates only a separate citation list. Worse, an
empty citation list is replaced with citations for every retrieved chunk:

```python
raw_cites = data.get("citations") or [ ... every retrieved chunk ... ]
...
"grounded": bool(verified) and not rejected
```

Thus a model can return `"The claimant was paid $1,000,000"` with no citation,
receive fallback chunk citations, and the response can be marked `grounded`.
It can also attach one valid but irrelevant span to the same unsupported answer.
Neither case is an invalid-coordinate problem, so D0b's four checks correctly
allow it. Calling this condition `grounded` is the overclaim.

This is **reasoned**, not a model-output measurement: it follows directly from
the data flow and needs no API spend to falsify. Use a test double for
`src.agent.genai.generate_json` that returns either:

```python
{"answer": "Unsupported factual claim.", "citations": []}
# or
{"answer": "Unsupported factual claim.",
 "citations": ["<valid span from an unrelated retrieved chunk>"]}
```

Call `_synthesize()` with at least one retrieved chunk. The test should require
the answer to be withheld/flagged and `citation_check.grounded is False`.
Today, the first case is supplied fallback citations and the second has a valid
coordinate, so neither predicate about the answer itself is checked.

The architectural correction is to represent answer claims with their cited
evidence, rather than validate an answer and a separate list independently.
Even then, label the result accurately: deterministic checks can establish
**citation validity and coverage**; semantic entailment needs a separately
measured verifier or review lane. Do not collapse those properties into one
boolean named `grounded`.

## 3. The embedding artifact has no compatibility contract

The system deliberately makes the embedding lane tunable: `EMBED_MODEL`,
`EMB_BLOCK_SIM`, and `EMB_BLOCK_CONTEXT_CHARS` control the geometry and candidate
yield (`config/00_config.py:64, 208-258`). The configuration correctly says the
similarity floor is model-specific and context changes require recalibration.

On an incremental ingest, however, `embed_index.run(..., doc_ids=...)` loads the
existing FAISS index and upserts vectors only for the new note
(`src/embed_index.py:100-124`). The new vector text is built with the *current*
context setting (`src/embed_index.py:63-91`). The old vectors remain from the
previous setting/model. `incremental.resolve_incremental()` then searches that
mixed index and assigns new entries to old buckets (`src/incremental.py:108-130`)
before it calls the Splink model-compatibility guard.

That guard is narrow by design but incomplete for this artifact: its signature
contains only declared comparison names and blocking-rule column names
(`src/entity_resolution.py:189-214`), and `check_model_current()` compares only
those two fields (`src/entity_resolution.py:218-232`). It records neither the
embedding model nor context, similarity, top-k, class-filter setting, vector
generation, or the derived bucket algorithm. The FAISS metadata also stores
only entity class, document/claim id, and normalized surface
(`src/embed_index.py:121-124`).

This makes a client-tuning operation unsafe in a particularly quiet way. A
same-dimension model change can make old and new vectors non-comparable; a
context or threshold change makes old bucket membership reflect a different
candidate policy. The ingest completes with `blocked_by='emb_bucket'`, but that
label no longer identifies one stable recall mechanism. Splink still scores its
pairs correctly *given they were proposed*; the unmeasured failure is which
pairs are never proposed at all.

The falsification test requires no live model. Backfill a small fixture using a
deterministic test embedder, alter one vector-generation knob, then ingest a
note with a distinguishable test embedder. Correct behavior is either:

1. a typed refusal that demands a full re-embed/re-bucket/backfill, or
2. an atomic generation migration that records the new configuration and
   recalculates all historical vectors, buckets, and candidate provenance.

If the system instead appends the new vector and scores it against old vectors,
this finding holds. A tunable object needs this lifecycle contract; a runbook
instruction to remember a rebuild is not a control.

## 4. The planned relation path cannot store its own recall misses

`RelationCandidate` deliberately permits `subject_mention_id=None`, and
`bind_to_mentions()` explicitly retains such a result with a
`subject_not_in_mentions` flag (`src/relations.py:122-127, 386-418`). That is
the correct extraction posture: a relation whose subject was missed by NER is
evidence of an extraction gap, not evidence that the clause should disappear.

But the intended relational target, `assertions`, requires
`subject_mention_id TEXT NOT NULL` with a mention foreign key
(`src/contracts.py:128-147`); the Python `Assertion` type is non-null as well
(`src/contracts.py:392-412`). Therefore the currently planned T1.5 wiring
cannot both use the existing assertion contract and honor the relation module's
retention promise. It must choose to reject the row, invent a subject, or change
the evidence model. The first two reproduce the product failure the orphan
identifier table was introduced to avoid.

This is not yet a runtime error because relation extraction remains outside the
operational pipeline (known D1). It is a **reasoned pre-integration contract
failure**, not a claim that current production writes are failing. The focused
test is:

1. create a span-grounded `RelationCandidate` whose named subject is absent from
   `mentions`;
2. run `bind_to_mentions()` and assert its subject id remains `None` with the
   documented flag;
3. persist the candidate through the exact assertion mapping proposed for T1.5.

The current schema must either reject it with `NOT NULL constraint failed` or
lose the null state. This finding is falsified only when the operational schema
has a first-class, span-grounded relation observation that preserves raw
arguments and nullable resolved links, and the above fixture round-trips without
substitution.

## What I checked and found sound

- **The event evaluator does not get a free score from the sealed fixture's
  other placements.** I compared all 4,594 `kind='event'` spans in the manifest
  to every non-event placement in the same document: **0 overlap**. This does
  not make event extraction implemented—it remains 0 by construction—but it
  rules out that specific metric artifact.
- **Citation coordinates are now genuinely checked against retrieved input.**
  The D0b verifier's document, bounds, and retrieved-evidence tests are sound;
  finding 2 is a distinct claim-to-evidence coverage gap, not a reversal of
  that fix.
- **The frozen Splink model does guard its declared comparison and blocking-rule
  schema.** `ModelOutOfDate` prevents scoring new notes with a model trained on
  a different comparison set (`src/entity_resolution.py:189-247`). Finding 3
  is confined to the vector artifact and candidate-policy configuration omitted
  from that signature.
- **There is no automatic acceptance of the offline embedding stub for ER.**
  `blocking.attach_buckets()` raises when embedding blocking is enabled in
  offline mode (`src/blocking.py:246-271`), preventing lexical-shingle output
  from being presented as semantic candidate generation.

## What I could not check, and why

- I did not run Gemini, GLiNER, the fast tier, or the full pipeline. The audit
  instruction forbids the multi-hour/costly run; additionally, the Windows
  `.venv` cannot launch because its base interpreter is unavailable and WSL
  execution is denied in this environment. The measured checks above use only
  local Node/JSON/raw-text processing.
- I did not quantify the rate of answer hallucination, vector-generation drift,
  or unbound relation arguments. Those require the narrow test doubles
  specified in each falsification test (and, later, real labelled client data),
  so they are explicitly marked **reasoned**.
- I did not re-audit known open architectural work—assertion-led graph
  construction, activity extraction, locale packs, hybrid lexical retrieval,
  or coreference unification—as newly discovered defects. They remain correctly
  tracked on the board; this audit focuses on the additional cross-stage
  contracts that would otherwise survive those implementations.
