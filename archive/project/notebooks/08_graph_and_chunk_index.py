# %% [markdown]
# # 08 - Layer 3: Dual Storage (chunk vectors + claim-scoped graph)
#
# Two stores, built together because Layer 4 needs both:
#
# * **chunks.faiss** — one vector per chunk, with `claim_id` and `occurrence_id`
#   in the metadata so retrieval can filter to a claim without partitioning the
#   index.
# * **the graph** — every node and edge carries a `claim_id`; generic predicates
#   are rejected at insert time.
#
# Cross-claim network links exist but live in a reserved scope reachable only
# through a separately-authorised call.

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

# %% [markdown]
# ## Chunk vector index
#
# Build this even for a graph-only experiment. `ClaimScopedAgent` raises if it
# is missing — an agent with an empty chunk index answers every question from
# graph expansion alone, returns zero citations, and used to report no error at
# all, which is one of four retrieval layers silently absent behind output still
# shaped like a real answer.

# %%
from src import build_graph
from src.repository import Repository

repo = Repository()
print("chunk index:", build_graph.build_chunk_index(repo))

# %% [markdown]
# ## Graph assembly

# %%
stats = build_graph.build_graph(repo)
print({k: v for k, v in stats.items() if k != "predicates"})
print()
print("predicates:", stats["predicates"])

# %% [markdown]
# ## Graph density control
#
# Generic predicates are rejected outright. `MENTIONED_IN` and `RELATED_TO` edges
# make a graph where everything connects to everything, which retrieves nothing
# useful and hides the edges that carry meaning.

# %%
from src.graph_store import PredicateRejected, get_graph_store, validate_predicate

for pred in ("TREATED_BY", "MENTIONED_IN", "RELATED_TO"):
    try:
        print(f"  {pred:14s} -> accepted as {validate_predicate(pred)}")
    except PredicateRejected as e:
        print(f"  {pred:14s} -> REJECTED: {str(e)[:70]}")

# %% [markdown]
# **Known gap.** This whitelist is also why the open-vocabulary predicates that
# `src/relations.py` extracts (notebook 20) do not reach the graph: the
# assertion layer speaks an open vocabulary and the graph speaks a closed one,
# and nothing currently translates between them. `build_graph` never reads the
# `assertions` table at all — only five hardcoded predicates exist here. Closing
# that is the next piece of work, not a solved problem.

# %%
g = get_graph_store()
g.load()
sub = g.subgraph("CLM0005")
print("CLM0005 subgraph:", len(sub["nodes"]), "nodes,", len(sub["edges"]), "edges")
for e in sub["edges"][:8]:
    print(f"   {e['subject'][:26]:28s} --{e['predicate']:22s}--> "
          f"{e['object'][:24]:26s} [{e['doc_id']}:{e['span'][0]}-{e['span'][1]}]")

# %% [markdown]
# Every edge carries a span. An edge you cannot trace back to the characters
# that produced it is not evidence, it is an assertion by the pipeline.

# %% [markdown]
# ## Scope isolation

# %%
from src.graph_store import CROSS_CLAIM_SCOPE, ScopeViolation

try:
    g.neighbors([], 1, CROSS_CLAIM_SCOPE)
except ScopeViolation as e:
    print("blocked as designed:", str(e)[:90])
try:
    g.cross_claim_links(["x"], authorized=False)
except ScopeViolation as e:
    print("blocked as designed:", str(e)[:90])

# %%
repo.close()
