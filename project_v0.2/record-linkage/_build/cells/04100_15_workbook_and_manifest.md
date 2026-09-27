## 15 · Tables, workbook and manifest

**Tables.** Every output is a plain table written in the format `io_format` selects (the same
setting reads the inputs): `csv` (default, for display) or `parquet` into
`out/<dataset>/tables/`, or `delta` tables (section 15a). The full tables are: **entities** (one
row per extracted entity), **rows** (one row per extracted party, pointing back to its entity's
result), **candidates** (every kept entity x watchlist pair with its bits per field and cluster
status), **evidence** (pair x field: both values, level, m and u with their sources, bits;
the rows of a pair sum to its bits), **claims**, **dedup_pairs** (extracted x extracted pairs,
and whether they pooled), **weights** (every m and u, both models, with intervals and flags),
the self-check tables, and the **manifest**.

**Workbook: a summary, never overwhelmed.** `record_linkage_<dataset>.xlsx` holds: *summary*
(counts and the self-check headline), *flagged_entities* (best p >= `flag_p`, strongest first,
at most `workbook_flagged_max` rows; all of them are in the entities table), *best_matches*
(each flagged entity's best match with its decision card), *samples* (candidate pairs sampled
per basis x p band, with decision cards), *self_check* (held-out identifier and noise-test
metrics, B1 and baseline), *baseline_disagreements* (when the baseline is on), *weights* and
*manifest*. Full candidates and evidence are only in the table files.

The manifest holds: the run configuration, input hashes (files) or table versions (Delta),
input reports, the address standardizer's counts, unmapped category values, blocking counts,
deduplication counts, every m, u and bits value of both models with source, pair count, 95%
bootstrap interval and flags (unstable weights are listed apart), every training pass, the
priors with their intervals, the sensitivity table, cluster counts, data-quality findings,
vetoes, the self-check funnel (how many true pairs the candidate stage lost) and metrics, and the
timing of each step.

**Where Splink would do better.** Splink writes predictions straight to a database table or
Parquet from DuckDB or Spark and its model JSON records the trained parameters; on Databricks
it writes Spark tables without a pandas round trip. It has no workbook: the workbook is this
package's requirement, now a summary so its row limit never binds.
