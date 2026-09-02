# %% [markdown]
# # 06 - Profiles & Dossiers
#
# Bitemporal attribute rows with survivorship tiers (validated-ID > template >
# narrative); retractions close `known_to`; conflicts are flagged rather than
# silently resolved. Builds a dossier per entity where every evidence item
# carries a table-derived `machine_annotation`.

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
from src import profiles
from src.repository import Repository

repo = Repository()
print("profiles:", profiles.run(repo))

# %%
d = repo.all_dossiers()[0]
print("sample dossier:", d["canonical_name"], "[", d["class"], "]")
print("  identity   :", d["identity"])
print("  attributes :", list(d["attribute_timelines"].keys()))
print("  #evidence  :", len(d["evidence"]))
if d["evidence"]:
    print("  ex machine_annotation:", d["evidence"][0]["machine_annotation"])

# %% [markdown]
# ## Survivorship
#
# When two sources disagree about an attribute the tier decides, and the losing
# value is kept rather than overwritten. A dossier that shows only the winning
# value hides the fact that a conflict existed at all, which is the thing a
# reviewer most needs to see.

# %%
from src.settings import CFG

print("tiers (higher wins):", CFG.SURVIVORSHIP_TIERS)
attrs = repo.table("entity_attributes")
if "tier" in attrs.columns:
    print()
    print(attrs["tier"].value_counts())

# %%
# dump bulk tables to parquet (SQLite is the single file; parquet for bulk)
paths = repo.dump_parquet()
print("parquet bulk tables written:", [p.name for p in paths])
repo.close()
