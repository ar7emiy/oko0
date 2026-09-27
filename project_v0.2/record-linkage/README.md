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
| `b2_sections.py` | B2, the gold-label layer, as notebook sections in percent format (to be inserted into the notebook); also runs on its own against `out/<dataset>/` |
| `review/stubs/` | fictional SME review packet generated from the synthetic run (committed; see its README) |
| `data/`, `out/`, `review/` (except `review/stubs/`) | gitignored |

## The matching core

The notebook section "Matching core v1.0" (normalizers, rarity lookups, comparison levels,
Fellegi-Sunter scorer, vetoes, basis, parameter estimation) takes plain tables and returns
plain tables. Its code cells are hashed; the self-tests compare the hash with the recorded
value. goko-v2-poc [A] is to receive an identical copy (not yet done).

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

Measured runs are in `../STATE.md`: synthetic and LEIE meet their targets; the 1M x 300k
benchmark does **not** (54 min to the end of scoring, then out of memory building evidence
for 10.2M kept pairs). The review sample (plan milestone M6) is built as B2 (`b2_sections.py`,
next section); it is not yet inside the notebook.

## Choices made during the build (to confirm)

1. Two blocking rules added to the plan's list: surname-only parties meet every holder of the
   surname's NYSIIS code, and exact number + street (persons and businesses). The rarest-word
   rule also uses the rarest word of declared d/b/a partners.
2. Single-holder means one *holder* = surname + first initial (persons) or first alias
   (businesses), so "R. Smith" and "Robert Smith" holding one phone is one holder.
3. Identifier u per value = distinct holders of the value / watchlist parties holding the
   field; DOB, address, specialty and category u from the watchlist's own frequencies.
4. Name levels combine outside tables with random-pair rates of the name sub-parts
   (e.g. "last exact, first differs" u = surname share x random rate of differing first names).
5. Agreement levels never count below 0 bits and disagreement levels never above 0.
6. Invalid identifiers (Luhn, check digit, ranges, placeholders) and values held under more
   than 25 holders are not compared; placeholder DOBs are empty, not weak.
7. A near identifier (one digit / transposition) never vetoes and never makes the basis
   "identifier"; only an owned, single-holder phone makes the basis "identifier".
8. The watchlist's own share of an organization word replaces NPPES only when at least 5
   watchlist businesses use the word (open question 5).
9. Keyword categories are applied to both parts of the row; medical keywords were added
   beside the repair-shop and legal ones.
10. Nickname table read as undirected; a name's roots are itself and longer related names.
11. Evidence rows are written for non-empty fields only; the synthetic extracted set uses
    the noise table at half its rates, the LEIE copies at full rates.
12. `published_m.csv` has no published citations yet: values are GOKO's stated assumptions
    or placeholders, and say so.
