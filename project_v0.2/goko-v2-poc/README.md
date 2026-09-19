# GOKO v2 — architecture POC

A runnable trace of the v2 pipeline: whole-note extraction, three detection lanes, claim
assembly, category assignment, cross-claim resolution. `architecture-trace.html` is the
design this implements; `goko_v2_poc.ipynb` is the implementation.

```
goko_v2_poc.ipynb            the pipeline, one cell per boundary
architecture-trace.html      the design it implements
notes/                       four fixture notes across three claims, two occurrences
fixtures/                    recorded LLM payloads for OFFLINE_MODE
run_offline_check.py         runs every cell headless; non-zero exit if anything breaks
poc_output/                  written by the notebook (gitignored)
```

## Running it

```bash
python3 run_offline_check.py          # no key, no network, ~2s
jupyter lab goko_v2_poc.ipynb         # same thing, interactively
```

`OFFLINE_MODE = True` (cell 1, the default) replays recorded extractions for the bundled
notes. It exists so the plumbing can be verified without a deployment, and it is never
selected silently — with no key and `OFFLINE_MODE = False`, cell 1 raises and names the
toggle. Every artifact from an offline run is stamped `model: "offline-replay"`.

For a real run: put your Azure values in `settings.env` (cell 1 prints which keys it found,
masked, and which variant names it accepts), set `OFFLINE_MODE = False`, and drop notes into
`notes/` named `{claim_id}_{note_id}.txt`.

**Cell 23 is the one to run before believing any other number.** It checks the invariants
this pipeline can otherwise violate while completing cleanly. Cell 24 lists the architecture
stages the POC does not implement, so a green summary cannot be read as a complete system.

## What was wrong with the first version

Every item below was reproduced against a run before it was fixed.

### It could not extract anything

`EXTRACTION_SCHEMA` used `"minItems": 1`. Strict structured outputs reject that keyword, so
every extraction call returned a 400 — and the loop's `except Exception` turned each one
into an empty note. The run completed, reported `0` round-trip failures, `0` unresolved
quotes and `0` validation problems, and produced a dossier of nothing. A clean summary over
an empty corpus is the worst available failure.

Fixed three ways: the keyword is gone; `lint_strict_schema` checks both schemas at
definition time; and a failed extraction is now recorded as `extraction_error`, counted in
the summary, and declared a **partial run** rather than an empty note.

### The round-trip check could not fail

The check that "validates the entire chain" sliced the raw text at a span and compared it to
the *clean* text at the same span. Both sides derive from the span being tested, so it
passed for any span — including one pointing at a different sentence. Demonstrated: a span
of `[0, 10]` claiming to be the quote `"Dr. Monroe"` passed.

It now compares the raw slice against **the quote the model emitted**, which is what the
architecture trace describes and what catches a hallucinated quote. Spans that fail are
dropped rather than carried into a citation. The offset map itself is checked separately and
exhaustively in cell 7 — every index, not a sample.

### Two of the three quote-resolution paths returned wrong coordinates

- The normalized retry returned `normalized_text.index(...)` — an offset into a *different
  string*. Any note where whitespace collapsed before the match got a silently wrong span.
- The fuzzy retry returned the scanning window's start and the quote's length. Demonstrated:
  a quote resolved to `'he claimant attended … morning y'` — off by one at both ends.

Both now map back to real coordinates; the fuzzy path aligns to the matching block.
Neither could be caught before, because the round-trip check passed them.

### `must_not_link` vetoed nothing

Union-find filtered `high` edges against the blocked set, but a pair is never both `high`
and `must_not_link`, so the filter could never reject anything. Demonstrated: A–B high, B–C
high, A–C blocked → all three in one component.

Two changes. The constraint is now checked against the *components* a union would join, and
refusals are recorded on the dossier. And `must_not_link` is raised by evidence of a
different kind — a type mismatch, or two different values of an identifier a party can only
have one of — rather than by a low similarity score, which is just a restatement of "no
edge" and cannot veto a transitive merge.

### Scoring bands that no input could reach

- **Cross-claim.** `rarity = 1/n` over entities sharing a detail. Any pair that exists at
  all has `n ≥ 2`, so rarity ≤ 0.5, so `identity ≤ 0.7275` — and the `same` band starts at
  0.85. No pair in any corpus could ever be scored `same`. Rarity is now `2/n` capped at 1
  (unique-to-a-pair is 1.0), distance is an additive prior rather than a multiplier that can
  only scale identity down, and detail type carries weight.
- **Within-claim.** `0.45·name + 0.55·shared_detail` caps a pair with no shared identifier
  at 0.45, below the `mid` band at 0.60: two mentions of the identical distinctive name in
  different notes could never merge, or even be flagged. The two signals are now scored
  independently and capped.

Cell 23 proves each band is reachable in both scorers. That is not calibration — the weights
remain placeholders — but an unreachable band is a bug regardless of calibration.

### Quieter defects

| | |
|---|---|
| **Re-running the remap cell doubled every detail** | It appended to the previous run's list. Three runs, three copies of one NPI, nothing in the output saying so. It now rebuilds from the envelopes and folds identical `(type, value)` pairs into one detail with two pieces of evidence. |
| **Entity ids were unstable** | Numbering followed the union-find root, which depends on the order edges arrived. `E1` could mean a different party on the next run, making the "frozen, scoreable artifact" incomparable with itself. Numbering now follows each component's lowest member key. |
| **`off_taxonomy_value` was caught by its own `except`** | The `raise` sat inside the `try`, so a version-skew bug was downgraded to `insufficient_evidence` — exactly what the architecture trace says must never happen, because it turns a pipeline bug into an apparent recall problem. It is now collected and raised out of the loop. |
| **The model could not say "I don't know"** | Generation was constrained to the six scored categories while `insufficient_evidence` was treated as a possible answer. Every ambiguous party was forced into one of the six. The refusal is now in the schema enum and out of `CATEGORIES`. |
| **Reconciliation matched on value only** | `overlaps()` was defined and never called. A note stating one phone number twice reconciled one mention and emitted the other pattern find as a phantom "recall gap". Matching now requires an overlapping span, and each pattern find is consumed once. |
| **Organizations blocked on their last token** | `Lakeshore PT` keyed on `pt`, `Lakeshore Physical Therapy` on `therapy`; the pair was never proposed. Blocking keys are now built per entity type — surname for people, leading token for organizations — with a stopword list split the same way. |
| **The GLiNER lane was dead code** | It computed spans nothing read. Its finds now reconcile against entity mentions, and unmatched ones surface as `entity_candidates`. |
| **Phones and NPIs fought over the same digits** | A bare ten-digit run matched both patterns. The phone pattern now requires a separator; a bare ten-digit NPI is flagged `cue: false`, because "ten digits after the word NPI" and "ten loose digits" are not the same claim. |
| **Captured values carried the cue's span** | `bar_number 6224417` came with a span covering `ARDC 6224417`, so every citation built from it was off by five characters. |
| **An empty `notes/` raised `IndexError` two cells later** | Both the empty and missing cases now fail where the problem is, with the expected filename format in the message. |
| **A loose filename pattern truncated note ids** | `(.+)_(\d{5,6})` against `…_1882130.txt` matches with the id silently truncated to `882130`. The pattern is anchored to the claim-id format. |
| **Dangling action participants vanished** | A participant whose mention resolved to nothing became `{"entity_id": null}` with no record. Counted and carried on the dossier now. |

## Design questions the trace leaves open

These are about the architecture, not the notebook. They need a decision before v1.

1. **`must_not_link` is described as a band of the identity score.** A band derived from the
   same similarity number cannot act as a constraint — it carries no information the score
   does not already carry. A veto needs independent evidence. Implemented here as type
   mismatch plus conflicting singular identifiers; the full list of disqualifying evidence
   is a decision, not an implementation detail.
2. **The trace's worked scores are not reproducible from the model it describes.** An
   `identity_score` of 0.96 for a single shared phone within an occurrence implies an
   evidence base near 1.0 before the distance weight, but the base is never defined. Either
   the weights are additive priors (as implemented here) or the worked numbers need
   restating.
3. **`insufficient_evidence` cannot be produced under constrained decoding** if generation
   is constrained to the six scored values. It has to be in the enum and out of the scored
   set, or it only ever exists as a verdict the validator imposes.
4. **Identity projects upward; `basis: "inferred"` details project with it.** A phone number
   attributed to a party by a pronoun becomes a join key in `union_details` with the same
   standing as a stated NPI. Whether inferred ownership should be allowed to chain people
   together across claims is a decision the trace does not record.
5. **A suspended projection may already have produced alerts.** The cluster-size alarm
   suspends a projection, but nothing says what happens to alerts derived from it before the
   suspension.
6. **Within-note duplicate mentions are never detected.** Assembly compares across notes
   only, on the principle that within-note coreference is the model's job. When the model
   emits two mentions for one party in one note, nothing notices.
