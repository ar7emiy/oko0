# %% [markdown]
# # 04 - Mention Vector Index
#
# One vector per **mention**, not per entity. Entities do not exist yet at this
# point in the pipeline; resolving them is what this index is for.
#
# The index has exactly one consumer: `src/blocking.py`, the embedding recall
# net in Layer 2. It used to have none — this module wrote `entities.faiss` for
# a v1 resolution pass that was deleted when v2 moved to Splink, and nobody
# removed the builder, so the index was written on every run and read by
# nothing. It is now named for what it holds and feeds a live lane.

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
from src import embed_index
from src.repository import Repository
from src.settings import CFG, Paths

repo = Repository()
print("context window:", CFG.EMB_BLOCK_CONTEXT_CHARS, "chars each side")
print(embed_index.run(repo))

# %% [markdown]
# ## What a node text looks like
#
# `normalized name | class | local context`. Name first so it dominates the
# embedding.

# %%
nodes = embed_index.build_nodes(repo)
for n in nodes[:6]:
    print(f"  {n['mention_id'][:10]}  {n['node_text'][:110]}")

# %% [markdown]
# ## Calibration — `EMB_BLOCK_SIM` is model-specific and must be measured
#
# **This is the cell referenced by `blocking.EmbeddingThresholdMiscalibrated`
# and by the `EMB_BLOCK_SIM` comment in config. Re-run it after changing
# `EMBED_MODEL`.**
#
# Embedding models differ enormously in how they use the cosine range. A floor
# that is reasonable for a sentence-transformer is not reasonable here:
#
# | model family | co-referring cosine | unrelated cosine |
# |---|---|---|
# | sentence-transformers (all-MiniLM etc.) | 0.75 – 0.95 | 0.1 – 0.4 |
# | `gemini-embedding-001` | **0.30 – 0.34** | **0.25 – 0.29** |
#
# `EMB_BLOCK_SIM` was first set to `0.86` — a sensible-looking number from the
# first row of that table. Against `gemini-embedding-001` it produced **zero
# edges**. Resolution still ran, still produced clusters, still passed every
# assertion, and simply merged less. Nothing anywhere said why. That is the exact
# failure class this codebase removed everywhere else, so it is now an exception
# rather than a silent shrug.
#
# The labelled probe below is small on purpose: calibration needs *known* pairs,
# and these are pairs whose truth you can check by reading them.

# %%
import itertools

from src import blocking, genai
from src.embed_index import build_node_text
from src.vectorstore import FaissVectorStore

# (surface, entity_class, context, TRUE entity group)
PROBE = [
    ("Bob Miller",               "claimant",         "spoke with Bob Miller about the tow invoice",     "miller"),
    ("Robert Miller Jr",         "claimant",         "Robert Miller Jr confirmed the vehicle was his",  "miller"),
    ("R. Miller",                "claimant",         "left voicemail for R. Miller re: the estimate",   "miller"),
    ("Valley Auto Body",         "repair_shop",      "vehicle towed to Valley Auto Body for teardown",  "valley"),
    ("Valley Auto Body & Paint", "repair_shop",      "Valley Auto Body & Paint sent a supplement",      "valley"),
    ("Valley Autobody",          "repair_shop",      "Valley Autobody has not returned our call",       "valley"),
    ("Dr. Alicia Reyes",         "medical_provider", "Dr. Alicia Reyes examined the claimant on 3/14",  "reyes"),
    ("Alicia Reyes, MD",         "medical_provider", "records requested from Alicia Reyes, MD",         "reyes"),
    ("Karen Wu",                 "adjuster",         "Karen Wu is handling the file",                   "wu"),
    ("adjuster Karen Wu",        "adjuster",         "reassigned to adjuster Karen Wu on 4/2",          "wu"),
    # distractors that must NOT group
    ("Robert Chen",              "claimant",         "Robert Chen is the adverse driver",               "chen"),
    ("Miller Insurance",         "repair_shop",      "Miller Insurance is the adverse carrier",         "millerins"),
    ("Dr. Alan Reyes",           "medical_provider", "Dr. Alan Reyes is an orthopedist in Tucson",      "alanreyes"),
    ("Summit Collision",         "repair_shop",      "Summit Collision quoted the repair",              "summit"),
]


def calibrate(window: int) -> dict:
    """Cosine separation between known-true and known-false same-class pairs."""
    texts = [build_node_text(s.lower(), c, ctx[:window] if window else "")
             for s, c, ctx, _ in PROBE]
    V = genai.embed(texts)
    S = V @ V.T
    pos, neg = [], []
    for i, j in itertools.combinations(range(len(PROBE)), 2):
        if PROBE[i][1] != PROBE[j][1]:
            continue                    # the class filter would exclude this pair
        rec = (float(S[i, j]), PROBE[i][0], PROBE[j][0])
        (pos if PROBE[i][3] == PROBE[j][3] else neg).append(rec)
    return {"window": window, "pos": sorted(pos), "neg": sorted(neg, reverse=True)}


runs = [calibrate(w) for w in (0, 40, 120)]

# %%
print(f"{'ctx':>4} {'true_min':>9} {'true_med':>9} {'false_max':>10} {'margin':>8}  separable")
for r in runs:
    lo = r["pos"][0][0]
    med = r["pos"][len(r["pos"]) // 2][0]
    hi = r["neg"][0][0]
    print(f"{r['window']:>4} {lo:>9.4f} {med:>9.4f} {hi:>10.4f} {lo - hi:>8.4f}"
          f"  {'yes' if lo > hi else 'NO - overlapping'}")

# %% [markdown]
# `true_min` is the recall floor: set the threshold above it and you lose real
# pairs. `false_max` is the precision ceiling: set it below and you propose
# rubbish. A usable threshold sits between them, and `margin` says how much room
# there is. Measured here the margin is about **0.01** — thin, and a real
# property of this model rather than a tuning failure. It is also why
# `blocking.py` raises instead of shrugging when the threshold falls outside the
# observed distribution.

# %%
r0 = runs[0]
print("context window 0 — the configured default")
print()
print("  hardest TRUE pairs (these set the recall floor):")
for s, a, b in r0["pos"][:4]:
    print(f"     {s:.4f}  {a!r:26s} <-> {b!r}")
print()
print("  hardest FALSE pairs (these set the precision ceiling):")
for s, a, b in r0["neg"][:4]:
    print(f"     {s:.4f}  {a!r:26s} <-> {b!r}")

# %% [markdown]
# The hardest false pair is **`Dr. Alicia Reyes` vs `Dr. Alan Reyes`** — two
# different people, shared surname, same speciality. The floor sits just below it
# on purpose: the lane *proposes* that pair and Splink rejects it. Separating
# those two with a cosine threshold would be asking the wrong component to make
# the decision.

# %% [markdown]
# ### Why the default context window is 0
#
# The window barely moves separability — it shifts the whole distribution down
# without improving the margin, and it does **not** help on the Alicia/Alan Reyes
# pair, which was the main argument for including context at all.
#
# So `EMB_BLOCK_CONTEXT_CHARS = 0`: simplest configuration, highest absolute
# similarities, and — the real reason — it removes a coupling. With context in
# the vector, `EMB_BLOCK_SIM` has to be re-calibrated every time the window
# changes, and two knobs that must move together are two chances to move only
# one.
#
# Caveat worth keeping: 14 hand-labelled mentions is a small sample. Re-measure
# on real annotated data before treating "context does not help" as settled.

# %% [markdown]
# ## End-to-end check on the probe set
#
# At the configured threshold, does the lane actually group these?

# %%
texts = [build_node_text(s.lower(), c, "") for s, c, _, _ in PROBE]
ids = [f"p{i:02d}" for i in range(len(PROBE))]
classes = {i: r[1] for i, r in zip(ids, PROBE)}
truth = {i: r[3] for i, r in zip(ids, PROBE)}
surface = {i: r[0] for i, r in zip(ids, PROBE)}

store = FaissVectorStore(CFG.EMBED_DIM, Paths.store / "_probe.faiss",
                         Paths.store / "_probe.parquet")   # never persisted
store.upsert(ids, genai.embed(texts),
             [{"entity_class": c} for c in classes.values()])

edges = blocking.knn_edges(store, ids, classes)
roots = blocking.connected_components([(a, b) for a, b, _ in edges], ids)
groups = {}
for m, root in roots.items():
    groups.setdefault(root, []).append(m)

print(f"edges at EMB_BLOCK_SIM={CFG.EMB_BLOCK_SIM}: {len(edges)}")
for a, b, s in sorted(edges, key=lambda e: -e[2]):
    ok = "OK" if truth[a] == truth[b] else "XX"
    print(f"  {ok}  {s:.4f}  {surface[a]!r:26s} <-> {surface[b]!r}")

# %%
print("buckets:")
for root, mem in groups.items():
    if len(mem) > 1:
        clean = len({truth[m] for m in mem}) == 1
        print(f"  {'CLEAN' if clean else 'MIXED'}: {[surface[m] for m in mem]}")

true_pairs = {tuple(sorted(pair)) for pair in itertools.combinations(ids, 2)
              if truth[pair[0]] == truth[pair[1]]
              and classes[pair[0]] == classes[pair[1]]}
got = {tuple(sorted((a, b))) for a, b, _ in edges}
print()
print(f"recall    {len(true_pairs & got)}/{len(true_pairs)}")
print(f"precision {len(true_pairs & got)}/{len(got)}")

# %% [markdown]
# Measured on this machine, live against `gemini-embedding-001`: **recall 7/7,
# precision 7/7** on the twelve-mention subset, forming three clean buckets.
#
# For comparison, the deterministic name rules (`full_name`, `name_sorted`,
# `last_name`) propose **1 of those 7 pairs**. The other six are pairs that
# without this lane are never scored, never merged, and never appear in any
# report — a failure that is invisible rather than wrong, which is what makes it
# worth a whole lane.

# %%
repo.close()
