# %% [markdown]
# # 07 - Audit vs Ground Truth  ·  the ONLY pipeline reader of ground truth
#
# Joins pipeline output to the sealed manifest and reports honestly, misses
# included: entity counts and mapping, mention recall/precision with itemised
# misses, B-cubed cluster quality with over/under-merge evidence trails, the
# scan-coverage proof, and hash re-verification.
#
# `leakage_guard` permits this file (and `01_generate_corpus`,
# `10_recall_ablation`) to touch ground truth. Every other notebook and every
# pipeline module is scanned and must not.

# %%
# --- bootstrap: make the src package importable from any working dir ---
import sys
from pathlib import Path

p = Path.cwd().resolve()
while not (p / "config" / "00_config.py").exists() and p != p.parent:
    p = p.parent
if str(p) not in sys.path:
    sys.path.insert(0, str(p))
print("project root:", p)

# %%
from src import audit
from src.repository import Repository

repo = Repository()
report = audit.run(repo)
print(report["summary"])

# %%
m = report["entity_mapping"]
print("GT entities        :", m["gt_entity_count"])
print("system clusters    :", m["system_entity_count"])
print("GT never recovered :", m["n_gt_never_recovered"])

# %%
r = report["mention_recall"]
pr = report["mention_precision"]
print("mention recall   :", r["recall"], "(", r["found"], "/", r["total_placements"], ")")
print("mention precision:", pr["precision"],
      "| planted non-entities wrongly extracted:", pr["fp_nonentity_planted"])

# %%
import json

print("recall by segment_kind:")
print(json.dumps(r["by_segment_kind"], indent=1))
print("recall by hard case:")
print(json.dumps(r["by_hard_case"], indent=1))

# %%
print("sample misses (doc_id, span, variant, segment_kind):")
for miss in r["missed_sample"][:8]:
    print("  ", miss["doc_id"], miss["span"],
          repr(miss["surface_variant"]), miss["segment_kind"])

# %% [markdown]
# ## Cluster quality
#
# B-cubed rather than pairwise F1: pairwise metrics are dominated by whichever
# entity happens to have the most mentions, so one large cluster resolving well
# can hide every small one failing.

# %%
c = report["cluster_quality"]
print("B-cubed precision/recall/F1:",
      c["bcubed_precision"], c["bcubed_recall"], c["bcubed_f1"])
print("over-merges :", c["n_over_merges"])
print("under-merges:", c["n_under_merges"])

# %%
print("over-merge evidence trail (sample):")
for om in report["over_merge_evidence"][:2]:
    print(json.dumps(om, indent=1)[:700])

# %% [markdown]
# ## Did the embedding lane help or hurt?
#
# The lane raises blocking recall, which can raise *both* true and false merges.
# Under-merges falling without over-merges rising is the lane working. The
# per-edge `blocked_by` column is what makes this answerable at all.

# %%
edges = repo.table("same_as_edges")
if "blocked_by" in edges.columns:
    print(edges["blocked_by"].value_counts(dropna=False))

# %% [markdown]
# ## Scan-coverage proof
#
# Every character of every note was seen by some extractor, or the shortfall is
# named. Recall you cannot attribute to a specific unscanned span is recall you
# cannot debug.

# %%
cov = report["coverage_proof"]
print("  overall coverage    :", cov["overall_coverage"])
print("  docs at 100%%        :", cov["n_docs_full_coverage"], "/", cov["n_docs"])
print("  coverage histogram  :", cov["coverage_histogram"])
print("  overlap depth (chars):", cov["overlap_depth_chars"],
      "(fraction", cov["overlap_fraction"], ")")
print("  docs under 100%%     :", cov["n_docs_under_100pct"])
print("hash re-verification  :", report["hash_verification"]["ok"])

# %%
repo.close()
