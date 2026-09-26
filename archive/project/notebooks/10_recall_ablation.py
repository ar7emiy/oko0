# %% [markdown]
# # 10 - Recall Ablation  ·  ground-truth READER
#
# The architecture's central claim, measured: does the union of extractors
# actually approach zero misses, or is one extractor carrying the others?
#
# Cumulative stages: LLM only -> +token-NER -> +gazetteer -> +sweep. Each stage's
# `recall_lift` is what that extractor was worth. An extractor with near-zero
# lift is one you are paying for and not using.

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
from src import ablation

report = ablation.run()          # full corpus; pass limit_docs=250 for a fast pass
print(report["summary"])

# %%
print(f"{'stage':16s} {'name_recall':>11s} {'lift':>8s} "
      f"{'name_prec':>10s} {'id_recall':>10s}")
for stage, sc in report["stages"].items():
    lift = sc.get("recall_lift")
    lift = f"{lift:+.3f}" if lift is not None else "     -"
    print(f"{stage:16s} {sc['recall']:>11.4f} {lift:>8s} "
          f"{sc['name_span_precision']:>10.3f} "
          f"{sc['identifiers']['identifier_recall']:>10.4f}")

# %%
final = report["stages"]["plus_sweep"]
print("identifier recall by kind:")
for k, v in final["identifiers"]["by_kind"].items():
    print(f"   {k:10s} {v['recall']:.3f}  ({v['found']}/{v['total']})")

# %%
print("which extractor covered each found placement:")
for combo, n in list(final["provenance_of_found"].items())[:8]:
    print(f"   {combo:28s} {n}")

# %% [markdown]
# Combos of size one are the load-bearing cases: a placement found by exactly one
# extractor would have been missed entirely without it. That column, not the
# headline recall, is the argument for running the whole ensemble.

# %%
print("remaining misses after the full stack:", final["n_missed"])
for m in final["missed_sample"][:10]:
    print("  ", m["doc_id"], m["span"], repr(m["surface"]), m["segment_kind"])
print()
print("chunking:", report["chunking"])
