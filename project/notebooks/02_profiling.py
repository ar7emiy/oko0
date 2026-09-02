# %% [markdown]
# # 02 - Profiling
#
# Ingest raw notes, segment each into fully-tiling spans, fingerprint template
# blocks, and detect near-duplicates (MinHash over 5-word shingles).
#
# ## What segmentation does and does not claim
#
# There are exactly **two** segment kinds now: `body` and `quoted`. The previous
# seven (`template_block`, `narrative`, `email_header`, `email_body`,
# `email_signature`, `boilerplate`) were produced by the most fragile rules in
# the codebase and five of them were read by nothing downstream.
#
# Boilerplate is no longer a gate. `profiling.boilerplate_score()` returns a
# 0..1 advisory score over a cue bundle, and mentions inside high-scoring
# regions are **kept** and flagged, because a signature block is exactly where
# an adjuster's name and phone number live.

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
from src import profiling
from src.repository import Repository

repo = Repository()
repo.reset()   # fresh DB for a full pipeline run
print("profiling:", profiling.run(repo))

# %%
segs = repo.table("segments")
print("segment kinds:")
print(segs["kind"].value_counts())
print()
print("template fingerprints  :", segs["template_fingerprint"].nunique())
print("non-canonical near-dups:", int((segs["is_canonical_dup"] == 0).sum()))

# %% [markdown]
# ## Boilerplate as a score, not a verdict

# %%
print("boilerplate_score distribution:")
print(segs["boilerplate_score"].describe())
print()
print("segments scoring > 0.5:", int((segs["boilerplate_score"] > 0.5).sum()),
      "of", len(segs), "- kept, not dropped")

# %% [markdown]
# ## Casing regime
#
# The pipeline does not assume notes are correctly capitalised. `src/casing.py`
# detects the regime per segment so downstream stages can route rather than
# guess; it is a detector, never a truecaser, and it never invents case.

# %%
print(segs["casing_regime"].value_counts())
print()
print("case-informative segments:", int(segs["case_informative"].sum()),
      "of", len(segs))

# %% [markdown]
# `case_informative = False` means capitalisation carries no signal in that
# segment, so any name detector keying on initial capitals is blind there. That
# is the routing decision this pass exists to enable.

# %%
repo.close()
