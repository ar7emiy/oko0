# Record linkage [B]: extracted entity records against a watchlist

Two spreadsheets in, one Excel workbook out: for each extracted party, how likely it is on the
watchlist, which watchlist rows it could be, the field-by-field evidence, and what every number
rests on. No text is read. Design: [DESIGN.md](DESIGN.md). Build plan: [PLAN.md](PLAN.md).
This is system [B]; it shares only the *code* of its matching core with goko-v2-poc [A].

## Install

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install --no-deps recordlinkage==0.16    # its metadata pins an old pandas
```

Python 3.13, pandas 3.x (not 4), recordlinkage 0.16.

## Run

Everything is in **`record_linkage.ipynb`**. Pick the data with `RL_DATASET` and run all cells:

| `RL_DATASET` | Watchlist | Extracted |
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

## Inputs

Two CSVs with the columns in DESIGN.md ("Input schema"). `record_id` is required and unique;
everything else may be empty; unknown columns are kept as `x_<name>` for display. Routing of
each column to the person part, the business part or both is `mappings/columns.csv`.

## Outputs (`out/<dataset>/`, gitignored)

`record_linkage_<dataset>.xlsx` with sheets **entities** (one row per extracted party: best
watchlist row, p, basis, `rests_on_name`, vetoes, other candidates), **candidates** (every
kept pair with per-field bits and the rules that proposed it), **evidence** (pair x field:
both values, level, m and u with sources and pair counts, bits; rows sum to the pair's bits),
**claims** (per-claim roll-up) and **manifest** (configuration, hashes, every parameter with
source, count and interval, priors and sensitivity, blocking counts, data quality, timing).
Past Excel's row limit a sheet continues as `name (2)`. The same tables are written as
Parquet, and the manifest as JSON. `acceptance.json` holds the acceptance table of the run.

## Files

| Path | What |
|---|---|
| `record_linkage.ipynb` | the whole system: matching core, pipeline, LEIE exporter, synthetic generator, self-tests |
| `run_notebook_check.py` | runs every cell; exit code 1 on any error or failed self-test |
| `mappings/` | reviewable tables: column routing, category map (LEIE's 88 GENERAL + 206 SPECIALTY values, drafted, `needs_review` flags), keyword rules, specialty synonyms, simulation noise, published starting m |
| `reference/` | copied Census / SSA / NPPES tables and the nickname table; `SOURCES.md` with SHA-256 (checked at start-up) |
| `data/`, `out/`, `review/` | gitignored |

## The matching core

The notebook section "Matching core v1.0" (normalizers, rarity lookups, comparison levels,
Fellegi-Sunter scorer, vetoes, basis, parameter estimation) takes plain tables and returns
plain tables. Its code cells are hashed; the self-tests compare the hash with the recorded
value. goko-v2-poc [A] is to receive an identical copy (not yet done).

## Status

See `../STATE.md` for what was run and measured. The review sample (plan milestone M6) is a
skeleton section only.
