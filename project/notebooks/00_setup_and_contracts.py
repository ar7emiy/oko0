# %% [markdown]
# # 00 - Setup & Contracts
#
# The frozen data contracts every later stage shares. Reads the single config
# source of truth and prints the schema the rest of the pipeline depends on.
# Does **not** read ground truth.
#
# Run cell-by-cell in VS Code / PyCharm, or `python notebooks/00_setup_and_contracts.py`
# start to finish. `jupytext --to ipynb` converts it if you want a .ipynb.

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
from src.settings import CFG, Paths, genai_mode, genai_mode_is_forced

Paths.ensure()
print("GENAI_MODEL =", CFG.GENAI_MODEL)
print("EMBED_MODEL =", CFG.EMBED_MODEL, "| dim", CFG.EMBED_DIM)
print("NER_BACKEND =", CFG.NER_BACKEND)
print("SEED        =", CFG.SEED)
print("GenAI mode  =", genai_mode(), "| explicitly forced:", genai_mode_is_forced())

# %% [markdown]
# `genai_mode()` returning `offline` without `forced=True` means no API key was
# found. That is a broken environment, not a mode: every LLM lane raises
# `LLMExtractorUnavailable` rather than quietly substituting a stub. Set
# `GEMINI_API_KEY` in `.env`, or set `GENAI_MODE=offline` deliberately.

# %%
from src import contracts

print("ENTITY_CLASSES     :", contracts.ENTITY_CLASSES)
print("SEGMENT_KINDS      :", contracts.SEGMENT_KINDS)
print("POLARITIES         :", contracts.POLARITIES)
print("CANONICAL_PREDICATES:", contracts.CANONICAL_PREDICATES)

# %% [markdown]
# Note the asymmetry, which is deliberate:
#
# * `POLARITIES` is a **closed enum**. Survivorship and graph assembly branch
#   structurally on `negated` / `retracted`, so an unrecognised value would be
#   silently treated as an assertion and reverse the meaning of a record.
# * `CANONICAL_PREDICATES` is an **open vocabulary**. It lists the spellings we
#   normalise toward; an unlisted predicate passes through unchanged. The
#   claims domain has a long tail of real relations (`landlord_of`,
#   `interpreter_for`, `supervises`) and a whitelist would silently discard them.

# %%
print("Relational schema (SQLite DDL):")
print(contracts.DDL)
print("tables:", contracts.TABLE_NAMES)

# %%
import json

print("query_plan_schema =")
print(json.dumps(contracts.query_plan_schema(), indent=1)[:900])

# %% [markdown]
# ## Blocking rules
#
# Load-bearing order: Splink stamps each predicted pair with the index of the
# rule that produced it, which is how the embedding lane's contribution is
# measured rather than asserted.

# %%
from src import entity_resolution as er

for i, name in enumerate(er.BLOCKING_RULE_NAMES):
    tag = "  <- embedding recall net" if i == er.EMB_RULE_INDEX else ""
    print(f"  {i}  {name}{tag}")
print()
print("embedding lane enabled:", CFG.EMB_BLOCK_ENABLED,
      "| sim >=", CFG.EMB_BLOCK_SIM,
      "| top-k", CFG.EMB_BLOCK_TOPK,
      "| max bucket", CFG.EMB_BLOCK_MAX_BUCKET)
