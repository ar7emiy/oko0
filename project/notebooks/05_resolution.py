# %% [markdown]
# # 05 - Layer 2: Entity Resolution
#
# Splink (Fellegi-Sunter record linkage with EM-trained m/u probabilities) over
# candidates from **two** blocking lanes, then connected components at a chosen
# threshold.
#
# Two properties worth stating before any numbers:
#
# 1. **Calibrated probabilities.** Every pair carries a real `match_probability`
#    with a per-comparison breakdown, not a hand-tuned weighted sum.
# 2. **No destructive merge.** The output is a `same_as_edges` table. Identity is
#    a *threshold-derived view* over it — change the threshold and the partition
#    recomputes. Nothing is written down as "these are the same forever", so a
#    questionable link is a low-probability edge you filter at read time rather
#    than a structural mistake baked into the store.

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
# ## The two blocking lanes
#
# Blocking recall is a **hard ceiling** on ER recall: a pair no rule proposes is
# never scored, so it can never be merged no matter how good the comparison
# model is. The nine deterministic rules only fire when two mentions share a key.
# The pairs that costs you are the realistic ones:
#
# ```
# "Bob Miller"        vs  "Robert Miller Jr"        -- no shared key
# "Valley Auto Body"  vs  "Valley Auto Body & Paint"
# an entity written differently in every note it appears in
# ```
#
# The embedding lane is a second candidate generator unioned with those rules.
# It only ever **proposes**; Splink scores its pairs with the same EM-trained
# model, so an embedding-found link is exactly as auditable as a deterministic
# one. Embeddings buy recall, which is what they are good at, and are kept out
# of the scoring decision, where "the vectors were close" is not an explanation
# anyone can audit.

# %%
from src import entity_resolution as er
from src.settings import CFG

for i, name in enumerate(er.BLOCKING_RULE_NAMES):
    tag = "  <- embedding recall net" if i == er.EMB_RULE_INDEX else ""
    print(f"  {i}  {name}{tag}")

# %% [markdown]
# ## Building the mention frame and attaching buckets

# %%
from src import blocking
from src.repository import Repository

repo = Repository()
frame = er.build_mention_frame(repo)
print("mentions:", len(frame), "| columns:", list(frame.columns))

# %%
frame, block_stats = blocking.attach_buckets(frame)
for k, v in block_stats.items():
    print(f"  {k:32s} {v}")

# %% [markdown]
# `n_oversize_components_dropped` is the guard doing its job. A loose similarity
# threshold lets components chain transitively — A~B, B~C, C~D with A nothing
# like D — and one runaway component of n mentions costs n²/2 pairs. Those
# components contribute **nothing** rather than contributing noise; the mentions
# in them keep all nine deterministic rules. A giant component means the
# embedding signal was not discriminative there, and the honest response is to
# stay out of the way.

# %%
# what the lane actually grouped
bucketed = frame[frame["emb_bucket"].notna()]
print("mentions with a bucket:", len(bucketed), "of", len(frame))
if len(bucketed):
    top = bucketed.groupby("emb_bucket")["full_name"].apply(list)
    top = sorted(top.items(), key=lambda kv: -len(kv[1]))[:8]
    for bucket, names in top:
        print(f"  {bucket}: {sorted(set(names))[:6]}")

# %% [markdown]
# Read those groups critically. Names that are obvious variants of each other
# are the lane working. Names that are merely *similar people* are candidate
# pairs Splink is about to reject — which is fine, that is the division of
# labour — but if the groups are mostly the latter, `EMB_BLOCK_SIM` is too low.

# %% [markdown]
# ## Full resolution run

# %%
res = er.run(repo)
for k, v in res.items():
    if k not in ("threshold_sweep", "embedding_blocking", "blocking_lanes",
                 "calibration"):
        print(f"  {k:24s} {v}")

# %% [markdown]
# ## Is this model actually calibrated?
#
# The layer's headline claim is *calibrated probabilities*, so the calibration
# itself has to be inspectable rather than assumed. Two things decide it.
#
# **The prior.** `probability_two_random_records_match` is the chance two
# randomly drawn mentions co-refer, and it multiplies every posterior. It is
# estimated from high-precision deterministic rules. Choosing those rules by
# *which fields you trust* rather than *which rules actually fire on the data*
# put it 16x too low — roughly 4 bits removed from every edge, which split ~80
# entities into 515 while precision still read 0.97. Nothing caught it for weeks
# because no run output named the prior. Now every run does.
#
# **The evidence ordering.** What one agreeing field is worth, in bits. This is
# the sanity check with no statistics in it: a globally unique identifier must
# outrank a name. If `npi` or `email` ever sits below `name_sorted`, the model is
# telling you something is wrong with its inputs, not with your intuition.

# %%
cal = res["calibration"]
lam = cal["probability_two_random_records_match"]
print(f"match prior: {lam:.6f}   (1 in {1/lam:,.0f} random mention pairs co-refer)")
print(f"estimated from {cal['n_lambda_rules']} deterministic rules")
print()
print("what one agreeing field is worth:")
for name, w in sorted(cal["agreement_weights_bits"].items(),
                      key=lambda kv: -kv[1]["match_weight_bits"]):
    print(f"  {w['match_weight_bits']:+7.2f} bits   {name}")

# %% [markdown]
# ## Parameters EM could not estimate
#
# Splink logs *"your model is not yet fully trained ... will use default values"*
# and carries on. The substituted value is not neutral: for a two-level
# comparison the invented `m` for agreement is 0.95 whatever the field is, so an
# exact NPI match — a nationally unique identifier — was scoring +2.73 bits,
# **less than an exact name match**.
#
# It cannot always be fixed by training harder. Only 7 of 922 mentions carry an
# NPI at all, so there is genuinely nothing to learn from. The honest response is
# to name it, flag the edges it touched, and let the operator decide — which is
# what `CFG.ER_REQUIRE_FULLY_TRAINED` is for.

# %%
print(f"fully trained: {cal['fully_trained']}"
      f"   ({cal['n_untrained_parameters']} substituted parameters)")
for r in cal["untrained"]:
    print(f"  {r['comparison']:14s} {r['parameter']}  "
          f"{str(r['level'])[:40]:42s} {r['reason']:24s} -> "
          f"{r['substituted_default']}")

# The per-edge flag is deliberately narrow: an edge is only affected if its
# gamma for that comparison IS one of the substituted levels. A pair where both
# npi values were null used no npi parameter and is perfectly calibrated.
print()
print(f"edges flagged uncalibrated: {res['n_edges_uncalibrated']} of "
      f"{res['n_edges_scored']}")

# %% [markdown]
# ## What each lane contributed
#
# Splink stamps every predicted pair with `match_key`, the index of the rule that
# generated it, and assigns the **first** rule that fires. So a pair credited to
# `emb_bucket` is one that no deterministic rule proposed at all. That count is
# the recall the embedding lane bought — measured, not asserted.

# %%
for rule, n in sorted(res["blocking_lanes"].items(), key=lambda kv: -kv[1]):
    tag = "   <- pairs NO deterministic rule proposed" if rule == "emb_bucket" else ""
    print(f"  {rule:24s} {n:>8}{tag}")

# %%
edges = repo.table("same_as_edges")
emb_only = edges[edges["blocked_by"] == "emb_bucket"]
print("edges from the embedding lane alone:", len(emb_only))
print("of those, above the operating threshold:",
      int((emb_only["probability"] >= CFG.ER_LINK_THRESHOLD).sum()))

# %% [markdown]
# The second number is the one that matters. Pairs the lane proposed that Splink
# then scored *above* threshold are merges that deterministic blocking could not
# have produced. Pairs it proposed that scored below are the cost of the net —
# work done to reject them, which is the correct outcome for a recall net.

# %%
# the actual merges the lane made possible, for eyeball review
if len(emb_only):
    names = repo.table("mentions").set_index("mention_id")["surface"].to_dict()
    hi = emb_only[emb_only["probability"] >= CFG.ER_LINK_THRESHOLD]
    for _, e in hi.sort_values("probability", ascending=False).head(15).iterrows():
        print(f"  {e['probability']:.3f}  {names.get(e['mention_id_a'], '?')!r:32s} "
              f"<-> {names.get(e['mention_id_b'], '?')!r}")

# %% [markdown]
# ## Identity is a view, not a merge

# %%
print(f"{'threshold':>10} {'n_entities':>11}")
for row in res["threshold_sweep"]:
    mark = "  <- operating point" if row["threshold"] == res["operating_threshold"] else ""
    print(f"{row['threshold']:>10} {row['n_entities']:>11}{mark}")

# %%
ent = repo.table("entities")
print("resolved entities by class:")
print(ent["entity_class"].value_counts())
print()
print("suppressed edges:", res["n_edges_suppressed"], res["suppression_reasons"])

# %%
repo.close()
