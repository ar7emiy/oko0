# Spark v2 notebook

`goko_record_linkage_mvp_b1_spark_v2.ipynb` is standalone, using the matching definitions
from the current `goko_record_linkage_mvp_b1.ipynb` and the Spark/Delta adapters from the
original Spark notebook. The matching core is unchanged. The supplied pandas source's
SHA-256 is recorded in notebook metadata. The original notebooks are not modified.

Use Databricks Runtime 17.3 LTS with **Dedicated access mode**, fixed workers, and a
Unity Catalog volume accessible to driver and executors. `Standard_E8_v3` specifies
hardware, not the Databricks access mode. This notebook still uses RDDs and broadcasts.
Keep it beside `mappings/` and `reference/` in the Databricks Git folder.

Edit the two input tables, output schema and volume folder in Settings. Delta inputs
must use the expected matching schema; extra columns are not collected. Large output
tables remain Parquet parts until Spark loads them into Delta.

| Setting | Default | Effect |
|---|---|---|
| `OUTPUT_PREFIX` | `rl_v2_` | Separate Delta output table names |
| `WORK_FOLDER` | `/Volumes/main/record_linkage/work/v2` | Separate intermediate folders |
| `PAIRS_PER_TASK` | 100,000 | Comparison batch target |
| `EXECUTOR_PROCESSES` | 4 | Maximum fork children per Spark partition; memory can reduce it |
| `BOOTSTRAP_BATCH_REPS` | 8 | Concurrent draws; the total remains 200 |
| `STRICT_REQUIRE_COMPONENTS` | `True` | Require name and ZIP/street/DOB for compound strict-prior keys |
| `SELF_CHECK` | `False` | Optional held-out/noise reruns |
| `RUN_SELF_TESTS` | `False` | Optional embedded correctness tests |

## Implemented changes

- Prior estimation joins strict keys, applies identifier vetoes, deduplicates overlapping
  rules and aggregates counts in Spark. Only one count per extracted position returns to
  Python. No strict-prior pair is sampled or capped. The original `l < r` orientation
  and per-position bootstrap accounting are retained, including near identifiers and
  DL state qualification.
- EM comparisons return frequencies of level patterns rather than full comparison
  frames. Pattern ordering matches `numpy.unique`, preserving fits for the same sample.
  Capped-key training joins that exceed the configured global sample limit execute in
  Spark and persist to worker disks before sampling.
- Bootstrap draws retain the original RNG order, generated eight at a time. All
  configured replicates run.
- Each bounded wave uses one `collect()` action, allowing its partitions to run
  concurrently. With three counted executors and four processes per partition, a
  wave contains at most 12 comparison tasks. The next wave waits until those results
  are consumed. Packed results are released as they are decoded. Candidate/evidence
  tables remain on disk; collected values are summaries or bounded comparison samples.
  Broadcasts live for one call, including failure and early-stop cleanup. Each worker
  decodes a distinct broadcast once per partition. Even one-task calls run on a worker.
- Spark job descriptions identify the phase, part and task range. Longer calls report
  progress after the first wave, then roughly every 30 seconds at wave boundaries and
  at completion. `PAR.last_call` exposes task/wave/partition counts, elapsed seconds and
  the largest serialized wave result. Final candidate assembly logs each part's start
  and completion time. No log is emitted mid-wave.
- Oversized anchor groups use uniform pair-rank sampling before allocating pair indices,
  including exclusions for parties in the same note.
- Prior preflight logs raw join counts and largest block sizes, followed by Python RSS
  and available node/cgroup memory. Raw counts include self-pairs and overlaps before
  filtering. Worker memory controls respect Linux cgroup limits where available.
- Spark sorts and projects input columns before Arrow collection. Columnwise cleanup
  replaces multiple whole-frame string copies.

## Matching and sample differences

By default, an empty name combined with a ZIP no longer becomes a ZIP-only strict rule.
This changes estimated priors and can change posterior probabilities.
`STRICT_REQUIRE_COMPONENTS=False` restores the v1 key policy with distributed counting.
Rows and valid identifier rules remain available; missing information remains unresolved.

Small anchor groups and bounded training joins retain the legacy sample algorithm.
Oversized anchors use uniform pair-rank sampling; oversized Spark training joins use
an exact-size sample selected by stable hashes of pair positions and a run-seeded value.
Their sample membership, RNG consumption and subsequent fitted values can differ from
v1. Stable pair hashes avoid dependence on shuffle row order. These methods and the
missing-component policy are recorded in the manifest.

No new scoring/output cutoff is added. Existing candidate block refinement/drop rules
remain in effect and are reported in the original candidate diagnostics.

## Remaining resource requirements

Raw inputs, normalized party frames, value statistics, bounded training samples and
patterns, entity state, and accepted graph edges still reside in driver Python memory.
Anchor compatibility comparisons fill one final sample frame from batches rather than
concatenating all returned frames. The normalizer and cluster algorithm are not fully
distributed in this version.

Scoring batch size remains an estimate. A single pooled entity with many members or
candidates can exceed it. Spark joins, shuffles and disk-persisted samples need worker
disk space. Billions of legitimate pairs can remain expensive after driver allocation
is removed. This implementation does not promise constant memory at arbitrary volume.
The wave's collected results use more driver memory than one partition's results; the
wave remains bounded by the configured concurrency and comparison batch size. Spark
chooses partition placement and the fork cap is not a CPU reservation: multiple
partitions can land on one worker. Memory controls reduce local fork concurrency.

## Scheduling correction (2026-09-30)

The initial v2 used `RDD.toLocalIterator(prefetchPartitions=False)` for comparison
waves. It computes partitions as separate sequential jobs, which underused the cluster
and added job/worker startup overhead. The revision uses one bounded-wave `collect()`
instead, preserving task order, batch limits and broadcast lifetime. It does not change
matching weights, thresholds, candidate retention, evidence or sample algorithms.

The user reports that the initial v2 completed successfully on the real dataset.
Reported intermediate metrics included 9,605,906 scored entity/watchlist candidates,
33,483,994 member comparisons, 1,184 link chunks and 7,995.4 seconds elapsed at the
scoring/clustering marker. The reported 4.04 GB is sampled notebook Python memory,
not total driver/cluster memory. Exact run settings and final runtime were not captured
here. This successful run is the operational baseline; revised runtime is not measured.

## Checks and cluster validation

Run `python verify_spark_v2.py --full` in the project Python environment. The runner
checks every code cell's syntax and exact matching-core equality, loads definitions
without production settings, and exercises a small synthetic pipeline. Local prior
counts and oversized training joins use a disk-backed SQLite reference implementation.
Four transport tests exercise serialized task closures, one collect per bounded wave,
ordering, one-task execution, lazy next-wave dispatch, shared broadcast identity,
incomplete-result rejection and cleanup after failure or early iterator closure. The
harness rejects `toLocalIterator`; it does not simulate actual executor concurrency.

Local full suite: **95 embedded tests, 90 passed and 5 skipped**, plus **2 passing
transport tests**. The skips cover Linux fork/Spark execution and a file-location hash
check; exact core equality is checked separately by the runner. The scheduling revision's
targeted run executed **23 embedded tests, 18 passed and 5 skipped**, plus **4 passing
transport tests**. The added skip is a real Spark regression that checks a two-partition
wave submits one job, with ordered results and restored job properties.
The 100,000-member anchor regression represents roughly five billion possible pairs and
requests only 50 sampled pairs.

**The revised scheduling has not been verified on Databricks.** This Windows environment has
no Spark/Java runtime. On the target cluster, first set `RUN_NAME="synthetic"`,
`OUTPUT_PREFIX="rl_v2_smoke_"` and `RUN_SELF_TESTS=True`, then run all cells. The separate
prefix keeps validation outputs separate from the completed production results.
Embedded tests then exercise actual Spark
prior counts, oversized training sampling, pipeline parity and the one-job wave
regression. Restore production settings for the real inputs; use a new output prefix
and work folder for the first optimized production run to retain the successful baseline.
Compare phase timings, Spark job counts and worker/driver memory with that run. Leave
the existing batch size, fork cap and bootstrap count in place for this first comparison.
