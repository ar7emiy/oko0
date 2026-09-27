# Record linkage [B]: extracted entity records against a watchlist

Two tables in, tables and a summary workbook out: for each extracted party, how likely it is on
the watchlist, which watchlist rows it could be, the field-by-field evidence, and what every
number rests on. No text is read. Design: [DESIGN.md](DESIGN.md). Build plan:
[PLAN.md](PLAN.md). This is system [B]; it shares only the *code* of its matching core with
goko-v2-poc [A].

**B1** (current): no gold labels, quality-first, runs now, held-out-identifier and
noise-injection self-checks are first-class output. **B1.1**: the same on Delta Lake, plus
incremental scoring. Both ship in this one notebook.

## Install

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install --no-deps recordlinkage==0.16    # its metadata pins an old pandas
```

Python 3.13, pandas 3.x (not 4), recordlinkage 0.16, rapidfuzz, usaddress. For `IO_FORMAT =
"delta"` on a real Spark cluster (Databricks): pyspark and delta-spark, matched minor versions;
locally without them, Delta mode runs against an in-memory fake with the same interface (see
"B1.1: Delta Lake" below).

## Run

Everything is in **`record_linkage.ipynb`**. The Settings cell (top of "Run") holds every
switch; each also reads an environment variable, so `run_notebook_check.py` and Databricks jobs
can set them without editing the notebook:

| Setting | Values | Environment variable |
|---|---|---|
| dataset | `synthetic` (default) · `leie` · `scale` · `files` | `RL_DATASET` |
| `IO_FORMAT` | `csv` (default, for display) · `parquet` · `delta` | `RL_IO_FORMAT` |
| `EXHAUSTIVE` | `False` (default: recall-oriented blocking) · `True` (every same-type pair) | `RL_EXHAUSTIVE` |
| `ADDRESS_STANDARDIZER` | `usaddress` (default, offline) · `given` · `smarty` | `RL_ADDRESS_STANDARDIZER` |
| `BASELINE` | `False` (default) · `True`: run the user's current method beside B1 | `RL_BASELINE` |
| `SELF_CHECK` | `True` (default): held-out identifier + noise-injection tests | `RL_SELF_CHECK` |
| `INCREMENTAL` | `False` (default) · `True` (Delta only): score only new/changed rows | `RL_INCREMENTAL` |

| dataset | Watchlist | Extracted |
|---|---|---|
| `synthetic` (default) | ~5,000 fictional rows | ~3,000 fictional rows + 45 hand-written edge cases (truth in `data/`) |
| `leie` | OIG LEIE, exported from the raw download into `data/leie_watchlist.csv` | noisy copies of 3,000 LEIE rows + 3,000 fictional parties |
| `scale` | 1,000,000 fictional rows | ~300,000 fictional rows |
| `files` | `RL_WATCHLIST=path.csv` | `RL_EXTRACTED=path.csv` |

```
python run_notebook_check.py              # all cells on the synthetic set; non-zero exit on any error
python run_notebook_check.py leie         # the LEIE run
python run_notebook_check.py scale        # the benchmark
```

For `leie`, put the raw OIG file at `data/LEIE_UPDATED.csv` (or let the notebook download
<https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv>). The export keeps DOB and street
addresses, so it stays in gitignored `data/`.

Self-checks (`SELF_CHECK = True`, default) run the whole pipeline again several times (once per
held-out identifier, once for the noise test, and again for each with `BASELINE = True`), so
they are the slowest part of a run; this is deliberate (quality of measurement over run time).

## Inputs

Two tables with the columns in DESIGN.md ("Input schema"). `record_id` is required and unique;
everything else may be empty; unknown columns are kept as `x_<name>` for display. Routing of
each column to the person part, the business part or both is `mappings/columns.csv`. With
`IO_FORMAT = "delta"`, the inputs are Delta tables (`delta_extracted_table`,
`delta_watchlist_table`), read at a pinned version recorded in the manifest.

## Outputs (`out/<dataset>/`, gitignored)

**Every table** (`entities`, `rows`, `candidates`, `evidence`, `claims`, `dedup_pairs`,
`weights`, the self-check tables, `manifest`) is written in `IO_FORMAT`: CSV files under
`out/<dataset>/tables/` (default), Parquet, or Delta tables (MERGE on key, history kept).

- **entities**: one row per pooled extracted entity: records pooled, best watchlist match, p,
  basis, cluster status, conflicting candidates, other candidates.
- **rows**: one row per original extracted record, pointing back to its entity's result.
- **candidates**: every kept entity x watchlist pair, per-field bits, the rules that proposed
  it, cluster status, and (baseline on) `p_baseline`.
- **evidence**: pair x field — both values, level, m and u with sources and pair counts, how
  many distinct values the entity offered, bits; rows sum to the pair's bits.
- **claims**, **dedup_pairs** (extracted x extracted, and whether they pooled), **weights**
  (every m/u/bits, both models, with 95% bootstrap intervals and stability flags).
- **selfcheck_bands / _funnel / _basis / _bins**: precision/recall by threshold, the candidate
  stage's lost true pairs, precision by basis, true/false pairs by p band — B1 and (baseline
  on) the baseline, for both the held-out-identifier check and the noise test.

`record_linkage_<dataset>.xlsx` is a **bounded summary**: `summary`, `flagged_entities` (best
p >= `flag_p`, capped at `workbook_flagged_max`), `best_matches` (decision cards), `samples`
(stratified by basis x p band), `self_check`, `baseline_disagreements` (baseline on), `weights`,
`manifest`. Full candidates and evidence are only in the table files, so the workbook is never
overwhelmed. `acceptance.json` holds the acceptance table of the run.

## Files

| Path | What |
|---|---|
| `record_linkage.ipynb` | the whole system: matching core v1.1, pipeline, table I/O (CSV/Parquet/Delta), self-checks, LEIE exporter, synthetic generator, self-tests |
| `run_notebook_check.py` | runs every cell; exit code 1 on any error or failed self-test |
| `mappings/` | reviewable tables: column routing, category map (LEIE's 88 GENERAL + 206 SPECIALTY values, drafted, `needs_review` flags), keyword rules, specialty synonyms, simulation noise, published starting m |
| `reference/` | copied Census / SSA / NPPES tables and the nickname table; `SOURCES.md` with SHA-256 (checked at start-up); `.gitattributes` keeps them byte-exact across checkouts |
| `b2_sections.py` | B2, the gold-label layer, as notebook sections in percent format (to be inserted into the notebook at its marked insertion point); also runs on its own against `out/<dataset>/` |
| `review/stubs/` | fictional SME review packet generated from the synthetic run (committed; see its own README) |
| `data/`, `out/`, `review/` (except `review/stubs/`) | gitignored |

## The matching core

The notebook section "Matching core v1.1" (normalizers, rarity lookups, closed-form and sampled
u, comparison levels, Splink-style EM with bootstrap, the Fellegi-Sunter scorer, vetoes, basis,
pooled-entity aggregation, constrained clustering) takes plain tables and returns plain tables.
Its code cells are hashed; the self-tests compare the hash with the recorded value. goko-v2-poc
[A] is to receive an identical copy (not yet done).

## B1.1: Delta Lake

`IO_FORMAT = "delta"` reads the inputs as Delta tables and writes every output as a Delta
table, MERGE'd on its key, with full history. `INCREMENTAL = True` scores only entities whose
member rows changed since the last run (change data feed, or a version diff when the feed is
off), reusing the saved model and a cache of previously scored entity x watchlist pairs.

**Local testing status: the I/O layer is tested with a fake, not a real Spark cluster.** This
machine has no Java, so `pyspark` cannot run locally regardless of installation (PySpark needs
a JVM). `InMemoryDeltaBackend` reproduces Delta's semantics in pure pandas — versions (time
travel), a change data feed, and MERGE (upsert + delete-missing) — and every I/O and incremental
self-test (`TestTableIO`, `TestIncremental`) runs against it. `SparkDeltaBackend` is the same
interface over real `pyspark.sql` and `delta.tables.DeltaTable`, used automatically when
`IO_FORMAT = "delta"` runs where a `spark` session already exists (Databricks) or where
`pyspark` + `delta-spark` can be installed and a JVM is present.

**Databricks setup** (cluster libraries or a `%pip` cell): `pip install delta-spark==<matching
your Spark's Delta version>`; the cluster's Spark already has Delta built in, no extra library
needed there. Point `delta_catalog` / `delta_schema` at a Unity Catalog schema, or leave them
blank and set `delta_path_root` to a Volume path (`/Volumes/catalog/schema/volume/rl`). A
placeholder table, `delta_gold_labels_table` (`rl_gold_labels`), is reserved for gold-label
sections another workstream adds at the end of this notebook; nothing here reads or writes it.

## Gold labels (B2): `b2_sections.py`

The layer that uses SME labels: review samples, blind SME packets, label ingestion, evaluation on
a sealed test split, and four label-driven improvements that are adopted only if they beat the
pipeline there. It is written as notebook sections (`# %% [markdown]` / `# %% [code]`) to be
inserted after the pipeline's run and self-test sections; until then it runs on its own:

```
python b2_sections.py                          # B2 on out/synthetic (run the notebook first)
RL_DATASET=leie python b2_sections.py          # on another dataset's outputs
RL_B2_WRITE_STUBS=1 python b2_sections.py      # also regenerate review/stubs/
```

It reads only the pipeline's output tables (candidates, evidence, entities, manifest, and the
input rows for display), through the adapter table `B2_DEPENDENCIES` at its top; the exact
columns are listed in its first markdown cell. Inside the notebook it takes the variables
(`CAND_OUT`/`PAIRS`, `EVIDENCE`, `ENTITIES`, `MANIFEST`, `XDF`, `WDF`, `TF`) and the core's level
tables; outside, the Parquet files. `B2_IO` routes all file IO through the pipeline's
CSV/Parquet/Delta switch when set.

| Step | What |
|---|---|
| Sample | strata p band x basis (vetoed pairs a band of their own); allocation ~ sqrt(N_h), x4 for p 0.1-0.9, x2 for name-only and contextual; inclusion probabilities and weights recorded; split train 40 / calibration 20 / sealed_test 40 per extracted party by hash of party and seed; every sealed_test and calibration pair double-coded |
| Packet | per SME: blind workbook (values side by side, drop-downs, locked data cells), instructions, data dictionary, label template; coordinator key with the hidden strata; adjudication sheet |
| Labels | workbooks, CSV, Parquet, Delta; unknown / stale / unassigned ids, invalid labels, duplicates and contradictions rejected with reasons; Cohen's and Fleiss' kappa; disagreements and single "unsure" go to adjudication |
| Evaluation | sealed split only, post-stratified Horvitz-Thompson weights: precision / recall / F1 by threshold, band and basis; candidate-space recall and the recall ceiling; reliability table, Brier, log loss, average precision, confusion tables; paired stratified bootstrap against the pipeline |
| Improvements | (a) isotonic / Platt calibration on the calibration split; (b) semi-supervised EM (u fixed, train labels fix their pairs and anchor a prior shift); (c) gradient boosting on per-field bits with exact per-field contributions for the decision card; (d) cost-based threshold (false alarm 1 : miss 5). Adopted only if the sealed bootstrap interval (Bonferroni over the four) is above 0; applied only when a person also turns the switch on in `B2Config.apply` |
| Loop | next batch: highest entropy of the mean p across scorers plus their spread (m intervals, prior x/÷10, and the fitted models), train-split parties only, written as the next round's packet |

Outputs: `review/<dataset>/<run_id>/round_NN/` (packets, returned labels, adjudication; gitignored),
`out/<dataset>/b2/b2_report.xlsx` (adoption, metrics, reliability, denominators, agreement, label
issues, EM m, next batch, the B2 manifest section), `b2_candidates.parquet` (p under each model and
the p actually used), `b2_decision_card.parquet`, `b2_manifest.parquet`.

**gold-annotator compatibility.** The packets are **not importable** into
`../gold-annotator/` as it stands: that app annotates claim notes and records a watchlist decision
only per row of a firm export, after a claim's note review is frozen; it has no pair without
notes, no DOB / SSN / NPI / licence / vehicle fields on the watchlist side, and no blind pair
queue. It would need a pair-review queue: import of `coordinator/pair-queue-import_roundNN.csv`
into a pair table with per-reviewer assignments; an append-only pair-label table (label,
confidence, reason, time); a side-by-side page with no scores; an export in the columns of
`labels-template_*.csv` (review_id, annotator_id, label, confidence, reason, labelled_at), which B2
reads unchanged; optionally an adjudication view. B2 already accepts the app's vocabulary
(same / different / cant_tell). Until then the Excel packets are the delivery.

## Status

Measured runs are in `../STATE.md`: synthetic and LEIE meet their acceptance targets under
B1's quality-focused build. The 1M x 300k scale benchmark predates the "quality over
time/memory" priority and is no longer a target (see the note above cell 12's keep rule: a
display-size floor found during merge review was removed in favor of never dropping a scored
pair, regardless of table size). The review sample (plan milestone M6) is built as B2
(`b2_sections.py`), consuming the pipeline's output tables through adapters; it is not yet
inserted into the notebook.

## Choices made during the build (to confirm)

1. Two blocking rules added to the plan's list: surname-only parties meet every holder of the
   surname's NYSIIS code, and exact number + street (persons and businesses). The rarest-word
   rule also uses the rarest word of declared d/b/a partners. B1 adds several more (see
   PLAN.md section 9): compound-surname parts, sound-alike first name + surname initial, DOB
   alone, "first last" sorted-neighbourhood, a second rare organization word and its sound,
   one-digit/transposition keys for every identifier and phone.
2. Single-holder means one *holder* = surname + first initial (persons) or first alias
   (businesses), so "R. Smith" and "Robert Smith" holding one phone is one holder.
3. Identifier u per value = distinct holders of the value / watchlist parties holding the
   field (closed form in B1); DOB, address, specialty and category u from the watchlist's own
   frequencies (also closed form in B1).
4. Name levels combine outside tables with random-pair rates of the name sub-parts
   (e.g. "last exact, first differs" u = surname share x random rate of differing first names).
5. Agreement levels never count below 0 bits and disagreement levels never above 0; B1 adds a
   floor on m and bounds on every field's bits, so no single field can produce an absurd weight.
6. Invalid identifiers (Luhn, check digit, ranges, placeholders) and values held under more
   than 25 holders are not compared; placeholder DOBs are empty, not weak.
7. A near identifier (one digit / transposition) never vetoes and never makes the basis
   "identifier"; only an owned, single-holder phone makes the basis "identifier". B1 also
   blocks on near identifiers (a candidate rule), still never a match basis.
8. The watchlist's own share of an organization word replaces NPPES only when at least 5
   watchlist businesses use the word (open question 5).
9. Keyword categories are applied to both parts of the row; medical keywords were added
   beside the repair-shop and legal ones.
10. Nickname table read as undirected; a name's roots are itself and longer related names.
11. Evidence rows are written for non-empty fields only; the synthetic extracted set uses
    the noise table at half its rates, the LEIE copies at full rates.
12. `published_m.csv` has no published citations yet: values are GOKO's stated assumptions
    or placeholders, and say so. B1's new levels (name/org splits, `last_sound_first_agrees`,
    `last_fuzzy_first_weak`) are marked the same way.
13. **B1**: a pooled entity's exact-level u is multiplied by how many distinct values of that
    field its member rows offered (a multiplicity correction, so more chances to agree by
    chance is not free evidence).
14. **B1**: the baseline module's threshold (90), cleaning and missing-category behavior
    (block) are this build's assumptions, marked as such in the manifest, until the user
    supplies the real values.
