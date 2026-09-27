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
| `mappings/` | reviewable tables: column routing, category map, keyword rules, specialty synonyms, simulation noise, published starting m |
| `reference/` | copied Census / SSA / NPPES tables and the nickname table; `SOURCES.md` with SHA-256 (checked at start-up); `.gitattributes` keeps them byte-exact across checkouts |
| `data/`, `out/`, `review/` | gitignored |

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

## Status

Measured runs are in `../STATE.md`.

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
