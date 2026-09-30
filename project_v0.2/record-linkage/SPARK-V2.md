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
| `EXECUTOR_PROCESSES` | 4 | Maximum fork children per executor task; memory can reduce it |
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
- Results stream through `toLocalIterator` in bounded waves. Broadcasts live for one
  call, including failure cleanup. Each executor decodes a distinct broadcast once per
  partition and clears references afterward. Even one-task calls run on a worker.
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

## Checks and cluster validation

Run `python verify_spark_v2.py --full` in the project Python environment. The runner
checks every code cell's syntax and exact matching-core equality, loads definitions
without production settings, and exercises a small synthetic pipeline. Local prior
counts and oversized training joins use a disk-backed SQLite reference implementation.
Two transport tests exercise serialized task closures, bounded wave ordering, one-task
execution, shared broadcast identity and cleanup after failure.

Local full suite: **95 embedded tests, 90 passed and 5 skipped**, plus **2 passing
transport tests**. The skips cover Linux fork/Spark execution and a file-location hash
check; exact core equality is checked separately by the runner. A final targeted rerun
executed **22 embedded tests, 18 passed and 4 skipped**, plus the same transport checks.
The 100,000-member anchor regression represents roughly five billion possible pairs and
requests only 50 sampled pairs.

**Databricks execution has not been verified locally.** This Windows environment has
no Spark/Java runtime. On the target cluster, first set `RUN_NAME="synthetic"` and
`RUN_SELF_TESTS=True`, then run all cells. Embedded tests then exercise actual Spark
prior counts, oversized training sampling and pipeline parity. Restore production
settings for the real inputs. No real 300k/400k dataset has been run for v2.
