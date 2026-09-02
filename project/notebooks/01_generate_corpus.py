# %% [markdown]
# # 01 - Generate Synthetic Corpus  ·  ground-truth WRITER
#
# Deterministically generates legacy claim notes across ~300 claims and, in the
# same pass, writes the sealed ground-truth manifest with the exact char offset
# of every planted mention. Then seals sha256 of every raw note.
#
# **This is one of only three files permitted to touch ground truth** (with
# `07_audit` and `10_recall_ablation`). `leakage_guard` enforces that.
# After this notebook the raw corpus is read-only for the rest of the pipeline.

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
from src import corpus_gen

summary = corpus_gen.generate_corpus()
print("corpus summary:", summary)

# %%
# seal hashes (written once) and immediately verify
from src.hashing import verify_hashes, write_hashes

hashes = write_hashes(overwrite=True)
report = verify_hashes("post-generation")
print("sealed", len(hashes), "raw files; integrity ok =", report["ok"])

# %%
# peek at one raw note and validate that planted offsets are byte-accurate
import json

from src.settings import Paths

man = json.loads(Paths.manifest_json.read_text(encoding="utf-8"))
doc = man["documents"][0]["doc_id"]
print("--- sample note", doc, "---")
print((Paths.raw_notes / f"{doc}.txt").read_text(encoding="utf-8")[:700])

# %%
ok = 0
sample = man["placements"][:2000]
for pl in sample:
    t = (Paths.raw_notes / f"{pl['doc_id']}.txt").read_text(encoding="utf-8")
    ok += (t[pl["char_start"]:pl["char_end"]] == pl["surface_variant"])
print(f"planted-offset fidelity: {ok} / {len(sample)}")
print("entities:", len(man["entities"]),
      "| placements:", len(man["placements"]),
      "| non_entities:", len(man["non_entities"]))

# %% [markdown]
# Offset fidelity has to be exactly 1.0. Every recall number the audit reports
# is a comparison against these offsets, so a manifest that disagrees with the
# note text by even one character makes the whole measurement meaningless.
