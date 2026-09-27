## 15a · Table I/O: CSV, Parquet, Delta Lake (B1.1)

One setting, `io_format`, applies to the two inputs and every output table:

| `io_format` | Inputs | Outputs |
|---|---|---|
| `csv` (default) | the two CSV files | `out/<dataset>/tables/<name>.csv` |
| `parquet` | the two Parquet files (`.parquet` beside the CSVs, or `RL_EXTRACTED` / `RL_WATCHLIST`) | `out/<dataset>/tables/<name>.parquet` |
| `delta` | `spark.read.table` of `delta_extracted_table` and `delta_watchlist_table`, read **at a pinned version** | a Delta table per output, `delta_output_prefix` + name, in `delta_catalog`.`delta_schema` (or under `delta_path_root`), change data feed on |

The pandas core runs unchanged on the Databricks driver: a Delta table becomes a pandas frame
with `toPandas()`, and every output goes back with `spark.createDataFrame(...)`. The manifest
records each input table's name and **exact version** (Delta time travel reproduces the run),
and each output table's version after the write.

**Writes keep history.** A Delta output is written by `MERGE` on its key: new rows inserted,
changed rows updated (a row hash decides), rows no longer produced deleted, unchanged rows left
alone. Every earlier state stays readable through Delta's version history (`DESCRIBE HISTORY`,
`VERSION AS OF`). The manifest and the self-check tables are appended with the run id.

**Gold labels (for B2).** `delta_gold_labels_table` (`rl_gold_labels`) is reserved for the
gold-label sections that B2 adds at the end of this notebook. Nothing here reads or writes it.

The Delta code talks to Spark only through `SparkDeltaBackend`; `InMemoryDeltaBackend` has the
same interface (versions, change data feed, merge) in pure pandas and is what the self-tests
use when Spark is absent.

**Where Splink would do better.** On Databricks Splink runs on Spark itself: it reads Delta
tables, blocks, compares and predicts as distributed Spark SQL, and writes the predictions as a
Spark table with no driver round trip, so input size is bounded by the cluster, not by driver
memory. Here the driver holds both inputs as pandas frames, which suits a strong driver and
keeps one code path for files and Delta, but is the ceiling on input size.
