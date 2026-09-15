# Independent adversarial audit — evidence routing and hard recall gates

**Audit baseline:** committed `ae80178` (`Serve the query fields the planner is
told it can use`), read on 2026-09-02. The working tree also contained
uncommitted builder work under `src/`; this audit does not rely on or alter that
work. No Gemini call or full pipeline run was made.

## Verdict

The system has several sound foundations: raw evidence spans are retained for
the paths it actually persists; identifier detection is separated from check
digit validation; exact identifier lookup now uses the same extractor and
normalizer as ingestion; and embeddings only propose ER candidates. However,
the current evidence-routing boundary still violates the core product claim.
It deterministically converts email `Sent:` timestamps into a person's DOB,
and it discards several other structured observations after detecting them.
Those are not model-quality limitations: they are deterministic type-routing
errors. Two additional hard gates turn a noisy derived class and a text-only
LLM owner name into irrevocable candidate/binding choices. Until these are
fixed or measured away, the system should not claim to extract every piece of
metadata or link metadata probabilistically.

| rank | finding | severity | status | primary evidence | falsification test |
|---|---|---|---|---|---|
| 1 | Email-header timestamps are routed and scored as DOBs. | Critical | **measured** | `pipeline_v2.py:47-50, 192-199, 369-413`; 426/426 `date_written` hits in raw notes occur after `Sent:`. | Run one note containing `Sent: Wed, Mar 10, 2026` through extraction. The finding is false if no `identifier_observations.kind='dob'`, `has_dob` assertion, or ER `dob` feature can be produced from that span. |
| 2 | The pipeline detects structured metadata then drops it because only names and a short identifier map have persistence routes. | High | **measured** | `gazetteers.py:55-70`; `pipeline_v2.py:369-372`; 3,499 raw-note monetary hits; crafted policy/CPT hits map to no predicate. | Add a valid policy number, money amount, CPT and ICD-10 to one note; after extraction, query a candidate/observation ledger. The finding is false if each survives with raw span, type, normalization/validation state, and provenance—even when it has no entity owner. |
| 3 | The LLM binding lane computes an ownership evidence span, then throws it away and re-selects an owner by surface-name proximity. | High | **reasoned** | `relations.py:462-557`; `pipeline_v2.py:251-255, 326-359`. | Create a note with two distinct mentions sharing the same normalized surface and an identifier whose LLM evidence points to the non-nearest one. The finding is false if the persisted `subject_mention_id` is selected from the returned evidence span rather than closest matching name text. |
| 4 | The embedding recall lane hard-partitions on `entity_class`, although that field is a role-like, corpus-fitted classifier with a fallback guess—not a structural person/organization type. | High | **reasoned** | `config/00_config.py:182-184`; `blocking.py:121-127, 267-270`; `pipeline_v2.py:36-50, 510-549`. | Measure ground-truth same-entity mention pairs whose predicted `entity_class` differs. The finding is false if the rate is zero on representative unseen/client data, or if an ablation allowing cross-class candidate proposal produces no recovered true pairs. |

## 1. `Sent:` dates can become DOB evidence

`gazetteers.PATTERNS` deliberately recognizes both numeric dates and written
dates. That is reasonable. The error is the next boundary:

```python
# pipeline_v2.py:47-50
"date": "has_dob",
"date_written": "has_dob",
```

All `gazetteers.scan()` hits whose `valid` flag is true are also sent to the LLM
identifier-binding lane (`pipeline_v2.py:192-199`). `date` and `date_written`
have validation strength `none`, but `gazetteers._validate()` returns `True` for
that class (`gazetteers.py:109-132`). When an owner is selected, the later loop
turns both labels into `kind_i='dob'`, persists an identifier observation, and
creates a `has_dob` assertion (`pipeline_v2.py:369-413`).

I ran the pure gazetteer over all 2,000 current raw notes, without an API call:

```text
all hits: 19,877
date hits: 250
date_written hits: 426
date/date_written hits with 'dob' or 'birth' in nearby context: 166
```

Then I inspected the 426 written-date hits specifically: **426/426** appeared
within 45 characters of `Sent:` in an email header. Examples:

```text
DOC00001  Sent: Wed, Mar 10, 2026
DOC00005  Sent: Fri, Apr 11, 2026
DOC00022  Sent: Mon, Feb 15, 2026
```

Those are record timestamps, not dates of birth. This is worse than simply
adding a wrong attribute: `entity_resolution.build_mention_frame()` consumes
both identifier observations and `has_dob` assertions as its `dob` comparison
feature (`entity_resolution.py:75-91`). A header timestamp can therefore
become false linkage evidence. `audit.identifier_recall()` scores only span
overlap against planted identifiers (`audit.py:200-247`), not label correctness,
owner correctness, or whether a value was semantically a DOB, so the present
1.000 identifier-recall gate cannot catch this.

**Required distinction:** date-of-birth is a typed attribute whose extraction
needs local semantic evidence (a DOB/birth-date cue, a structured source field,
or a dedicated model decision). Event and record timestamps are temporal facts.
They must remain separate even when their character shape is identical.

The minimal persistence check after the one-note fixture is:

```sql
SELECT kind, raw_value, source_span_start, source_span_end
FROM identifier_observations
WHERE doc_id = :fixture_doc_id;

SELECT predicate, source_span_start, source_span_end
FROM assertions
WHERE doc_id = :fixture_doc_id AND predicate = 'has_dob';
```

Any returned DOB row or assertion whose span covers the `Sent:` date confirms
the failure. A follow-on ER-frame inspection must also show no DOB feature from
that span.

## 2. Detection is not persistence: the structured-token dead end

The candidate union contains more structured values than the pipeline is
willing to persist. The only post-union routes are:

1. a candidate label in `NAME_LABELS`, or
2. a label present in `IDENTIFIER_LABEL_TO_PREDICATE`.

Everything else hits `if not pred: continue` at `pipeline_v2.py:369-372`.
There is no generic candidate ledger or observation table for structured values
that lack an owner. This drops evidence after it was found and span-grounded.

The raw-note scan counted **3,499 `monetary_amount` hits**. Those values are
not in the map, so that deterministic extractor has no persistence path. The
same applies to `policy_number`, `cpt`, `icd10`, and `zip`. A crafted no-API
probe demonstrated the live routing map:

```text
input: Sent: Mar 10, 2026. Policy POL-AB12345. Procedure CPT 99213.

date_written  Mar 10, 2026         -> has_dob
policy_number Policy POL-AB12345   -> None
cpt           99213                -> None
```

This refines an already-known board item rather than duplicating it. D3 says
policy/claim numbers have no detector. That diagnosis is stale after the recent
`policy_number` detector was added in `gazetteers.py:64-70`: the detector now
finds a valid policy value, but the output evaporates at the persistence map.
The system has moved the broken boundary one step downstream; it has not gained
a policy-number capability.

The right architectural question is not whether every structured token should
be bound to a person. It is whether every detected observation is retained as
an observation with: raw span, type, raw/normalized value, validation strength,
source document, and nullable owner/argument links. The answer must be yes for
a system whose stated purpose includes metadata and later event/relationship
reasoning. Ownership binding is an enrichment step, not permission to keep the
value.

For the falsification fixture, the corresponding evidence-retention query is:

```sql
SELECT observation_type, raw_value, normalized_value, validation,
       source_span_start, source_span_end, owner_mention_id
FROM structured_observations
WHERE doc_id = :fixture_doc_id
ORDER BY source_span_start;
```

The exact table name is deliberately an architectural expectation rather than a
claim about the current schema: the current schema has no generic observation
ledger. The finding is disproved only if an equivalent query returns all four
fixture values with the stated provenance fields; a row is allowed to have a
null owner.

## 3. Binding provenance is reduced to a name string

`relations.IdentifierBinding` carries `evidence_start`, `evidence_end`, and
`evidence_text` (`relations.py:462-473`). `_binding_rows()` fills these fields
from the model response (`relations.py:522-557`). That is exactly the evidence
needed to bind an identifier to a particular mention.

But `pipeline_v2.py:251-255` reduces each result to this pair before use:

```python
(identifier_value_lower, owner_text)
```

`llm_binding_for()` subsequently searches the document's extracted mentions by
normalized surface and chooses the closest matching surface to the identifier
(`pipeline_v2.py:326-359`). It neither carries the LLM evidence offsets forward
nor proves that the selected mention occurs in the LLM-cited ownership clause.

For a unique name this proxy happens to work. For repeated names, title/full-name
variants, or two different people with the same name in a note, it can attach a
correct model decision to the wrong mention. The reported binding precision is
therefore not yet a proof that binding provenance is preserved at mention level.
This is a **reasoned** finding because I did not spend Gemini budget on an
adversarial duplicate-name run.

## 4. A derived role label is a hard ER recall boundary

The embedding lane calls itself “class-filtered k-NN.” With
`EMB_BLOCK_SAME_CLASS=True` (`config/00_config.py:182-184`), `knn_edges()`
partitions mentions by `entity_class` *before* it calls the vector index
(`blocking.py:121-127`). A pair in different groups is never proposed, so
Splink never gets the chance to decide that it is the same entity.

That would be defensible only if the field were a reliable structural type such
as `person` versus `organization`. It is not. `pipeline_v2._classify()` writes
a closed role-like value—claimant, attorney, medical provider, repair shop, or
adjuster—from hard-coded English/domain cues and an `@ourinsco.com` constant;
an unmatched GLiNER `person` falls back to `claimant` and `organization` to
`medical_provider` (`pipeline_v2.py:36-50, 510-549`). The same derived value is
also inserted into the embedding text (`embed_index.py:56-60`).

This makes an extraction/classification error a zero-recall ER decision, not a
feature whose reliability Splink can learn. It is particularly at odds with the
client-tunable requirement: unseen job titles, source domains, firms, and
locales are precisely where the classifier may change its mind about one real
party. The current synthetic fixture may not expose this because it is built
around the same role taxonomy; that is why this finding is **reasoned**, not
measured.

## What I checked and found sound

- **No silent vector fallback for the ER lane.** `blocking.attach_buckets()`
  raises when real embeddings are unavailable rather than pretending the
  offline shingle stub is semantic (`blocking.py:244-271`).
- **Embedding does not make an identity decision.** It creates candidate pairs;
  Splink scores them and records the source blocking lane (`blocking.py:18-30`,
  `entity_resolution.py:406-415`). This is the correct division of labour.
- **NPI and VIN validation are genuine check-digit checks.** The gazetteer
  distinguishes `checksum`, `format`, and `none` validation rather than claiming
  all regex matches are equally validated (`gazetteers.py:1-29, 109-132`).
- **Exact query lookup reuses note-time parsing and normalization.**
  `agent.exact_lookup()` calls `gazetteers.scan()` and then the shared
  `textnorm.normalize_identifier()` path, avoiding a second drifting query
  parser (`agent.py:158-213`).
- **The builder correctly preserved unbound identifiers.** The observation is
  stored even when no owner is available (`pipeline_v2.py:365-405`), which is
  materially better than discarding name-less evidence.

## What I could not check, and why

- I did not run the end-to-end pipeline or any Gemini call. The task explicitly
  prohibits the multi-hour, budget-consuming full run; the date-routing finding
  is established without it from current routing code plus the 2,000-note raw
  scan.
- The Windows `.venv` points to a missing Python 3.13 base install. WSL Python
  could run the pure `gazetteers`/`textnorm` checks but lacks numpy and the
  project dependencies, so it could not construct the full repository/pipeline.
- I did not quantify duplicate-name binding errors or cross-`entity_class` true
  pairs. Those require a focused fixture or a real/labelled run; the exact
  falsification tests above are intentionally narrow enough to add without a
  full corpus rerun.
- I did not treat synthetic accuracy figures as evidence of real-data
  generalization. The raw corpus itself has already been shown to lack
  identifier-value format variation (board D23), so it cannot settle the
  normalization question.
