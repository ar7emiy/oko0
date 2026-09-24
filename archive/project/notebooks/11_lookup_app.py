# %% [markdown]
# # 11 - Lookup & Query App
#
# Name search plus natural-language questions. Gemini translates a question into
# a **structured query plan**; deterministic code executes that plan over the
# tables. The LLM plans, the tables answer — so the result is reproducible and
# every number in it came from a row, not from a model's recollection.
#
# Dossiers render with clickable evidence that highlights the exact span in the
# raw note.

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
import json

from src import app
from src.repository import Repository

repo = Repository()
index = app.EntityIndex(repo)
print("dossiers indexed:", len(index.dossiers))

# %%
# preloaded example questions: the generated plan + the table-executed answer
for q in app.EXAMPLE_QUESTIONS:
    out = app.answer_question(repo, index, q)
    names = [index.dossiers[e]["canonical_name"]
             for e in out["result"]["entity_ids"][:3]]
    print("Q:", q)
    print("   plan   :", json.dumps(out["plan"]))
    print("   answer : n =", out["result"]["n"], "| top:", names)
    print()

# %%
# export a self-contained clickable-evidence dossier snapshot
eid = max(index.dossiers, key=lambda e: index.dossiers[e]["n_mentions"])
path = app.export_dossier_html(repo, eid)
print("exported dossier snapshot ->", path)
print("open in a browser: click any evidence item to jump to the highlighted span.")

# %%
# launch the Gradio app (set LAUNCH_APP=0 for a headless run)
import os

if os.environ.get("LAUNCH_APP", "1") != "0":
    demo = app.build_app(repo)
    demo.launch(share=False)
else:
    print("LAUNCH_APP=0 -> skipping interactive launch (headless run).")
