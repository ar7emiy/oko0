# %% [markdown]
# # 30 - The system running: notes arrive, the dataset updates
#
# This is the **operational** path, not the research one. The difference matters:
#
# | | research path (01-11) | operational path (this) |
# |---|---|---|
# | input | a corpus generated with a sealed ground-truth manifest | notes arriving from a feed |
# | processing | every stage over the whole corpus, every run | only the arriving notes |
# | output | accuracy measured against the manifest | a resolved entity dataset |
# | question answered | *how accurate is this system?* | *what does this system do with a note?* |
#
# Both run the **same engines over the same tables**. The leakage guard is what
# makes that claim checkable rather than a promise: no pipeline module may read
# ground truth, so the manifest is genuinely invisible to everything used here.
#
# The run has two phases, which is how a real linkage system works:
#
# 1. **Backfill** — onboarding. A full pass over the client's history. This is
#    where the Splink model is trained by EM. Expensive, once.
# 2. **Ingest** — steady state. A note arrives, gets processed, and folds into
#    the resolved dataset. Cost is proportional to the note, not the corpus.
#
# Every stage logs what it *decided*, not just that it finished.

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
import shutil

from src.settings import CFG, Paths, genai_mode

# A demo-sized history. The default is 2000 notes, which is the right scale for
# measuring accuracy and the wrong scale for watching something run.
CFG.TARGET_NOTES = 60
CFG.N_OCCURRENCES = 10

print("GenAI mode :", genai_mode())
print("NER backend:", CFG.NER_BACKEND)
print("history    :", CFG.TARGET_NOTES, "notes")
assert genai_mode() == "online", (
    "This demo needs real models. The offline stubs cannot support the "
    "embedding blocking lane (their similarity distributions overlap), so the "
    "resolution step would not be the real one."
)

# %% [markdown]
# ## The note feed
#
# `corpus_gen` writes realistic legacy adjuster notes. It *also* writes a sealed
# ground-truth manifest, but nothing on this path reads it — that manifest exists
# so the research notebooks can measure accuracy, and the leakage guard enforces
# that the pipeline never sees it.
#
# Some notes are held back entirely, outside the watched folder, so the backfill
# genuinely cannot see them. They arrive later.

# %%
from src import corpus_gen

summary = corpus_gen.generate_corpus()
print("generated:", {k: summary[k] for k in ("n_docs", "n_claims", "n_entities")
                     if k in summary})

all_docs = sorted(f.stem for f in Paths.raw_notes.glob("*.txt"))
history, incoming = all_docs[:-6], all_docs[-6:]

HELD = Paths.data / "_incoming"
HELD.mkdir(exist_ok=True)
for d in incoming:
    shutil.move(str(Paths.raw_notes / f"{d}.txt"), str(HELD / f"{d}.txt"))

print(f"history in the watched folder : {len(history)} notes")
print(f"held back to arrive later     : {incoming}")

# %% [markdown]
# ## Phase 1 — Backfill
#
# The full historical load. Watch each stage report what it found. The extraction
# stage is the slow one (a model call per chunk) and prints a heartbeat, because
# minutes of silence is indistinguishable from a hang.

# %%
from src import ingest
from src.repository import Repository

repo = Repository()
back = ingest.backfill(repo)

# %% [markdown]
# ### What the backfill produced

# %%
import pandas as pd

ents = repo.table("entities")
print(f"{len(ents)} resolved entities from {len(repo.table('mentions'))} mentions")
print()
print(ents["entity_class"].value_counts().to_string())

# %%
# The entities that appear across the most notes -- the ones resolution had to
# actually work for.
members = repo.table("entity_members")
docs_of = repo.table("mentions").set_index("mention_id")["doc_id"].to_dict()
spread = (members.assign(doc=members["mention_id"].map(docs_of))
          .groupby("entity_id")["doc"].nunique().sort_values(ascending=False))
top = spread.head(10)
named = ents.set_index("entity_id")
print(f"{'entity':<34}{'class':<20}{'notes':>6}")
for eid, n in top.items():
    if eid in named.index:
        r = named.loc[eid]
        print(f"{str(r['canonical_name'])[:32]:<34}{r['entity_class']:<20}{n:>6}")

# %% [markdown]
# ## Phase 2 — A note arrives
#
# Read the note first, so you can see what the pipeline is about to be asked to
# do with it. Then watch it go through.

# %%
NOTE = incoming[0]
text = (HELD / f"{NOTE}.txt").read_text(encoding="utf-8")
print(f"--- {NOTE} ---")
print(text[:1200])

# %%
ingest.deliver([HELD / f"{NOTE}.txt"])
res = ingest.ingest(repo, [NOTE], rebuild_graph=False)

# %% [markdown]
# The line that matters is `MATCHED an existing entity`. That is a mention in
# this note being recognised as somebody already in the dataset — resolved
# against the corpus, not against this note. If instead everything was
# `new entities`, resolution found no link, which is a real outcome too and
# worth being able to see.

# %%
r = res["resolution"]
print(f"pairs scored for this note : {r.get('n_pairs_scored')}")
print(f"above threshold            : {r.get('n_pairs_above_threshold')}")
print(f"matched existing entities  : {len(r.get('entities_matched_existing', []))}")
print(f"created new entities       : {len(r.get('entities_created', []))}")
print(f"entities in dataset now    : {r.get('n_entities_total')}")
print(f"wall clock                 : {res['elapsed_s']}s")

# %% [markdown]
# ### Which blocking lane proposed the pairs?
#
# `emb_bucket` means the embedding recall net found a candidate that shared no
# deterministic key with anything — a name variant no exact rule would have
# caught. Everything else is a shared email, NPI, sorted name, soundex surname.

# %%
for lane, n in sorted((r.get("blocking_lanes") or {}).items(), key=lambda kv: -kv[1]):
    tag = "   <- no deterministic rule proposed these" if lane == "emb_bucket" else ""
    print(f"  {str(lane):<26}{n:>6}{tag}")

# %% [markdown]
# ## Phase 3 — A batch arrives
#
# Same path, several notes at once. This is what a nightly feed looks like.

# %%
batch = incoming[1:]
for d in batch:
    ingest.deliver([HELD / f"{d}.txt"])
res2 = ingest.ingest(repo, batch, rebuild_graph=True)

# %% [markdown]
# ## Phase 4 — The dataset
#
# What a consumer of this system actually gets.

# %%
ents = repo.table("entities")
members = repo.table("entity_members")
mentions = repo.table("mentions").set_index("mention_id")
docs = repo.table("documents").set_index("doc_id")

by_id = ents.set_index("entity_id")     # index once, not once per entity
claim_of = docs["claim_id"].to_dict()

rows = []
for eid, g in members.groupby("entity_id"):
    mids = [m for m in g["mention_id"] if m in mentions.index]
    if not mids or eid not in by_id.index:
        continue
    sub = mentions.loc[mids]
    claims = {claim_of[d] for d in sub["doc_id"] if d in claim_of}
    rows.append({
        "entity": by_id.loc[eid, "canonical_name"],
        "class": by_id.loc[eid, "entity_class"],
        "mentions": len(mids),
        "notes": sub["doc_id"].nunique(),
        "claims": len(claims),
        "surfaces": " | ".join(sorted(set(sub["surface"]))[:3]),
    })
dataset = pd.DataFrame(rows).sort_values(["claims", "mentions"], ascending=False)
print(dataset.head(20).to_string(index=False))

# %% [markdown]
# The `surfaces` column is the point of the whole system: one entity, several
# ways it was written across different notes, resolved into a single row. An
# entity spanning more than one **claim** is the cross-claim signal — the same
# party appearing on multiple files.

# %%
multi = dataset[dataset["claims"] > 1]
print(f"{len(multi)} entities appear on more than one claim")
print(multi.head(10).to_string(index=False))

# %% [markdown]
# ### Identifiers attached to entities

# %%
obs = repo.table("identifier_observations")
bound = obs[obs["subject_mention_id"].notna()]
ent_of = dict(zip(members["mention_id"], members["entity_id"]))
name_of = ents.set_index("entity_id")["canonical_name"].to_dict()
seen = {}
for _, o in bound.iterrows():
    eid = ent_of.get(o["subject_mention_id"])
    if eid:
        seen.setdefault(name_of.get(eid, eid), set()).add(f"{o['kind']}={o['value_norm']}")
for name, ids in list(seen.items())[:12]:
    print(f"  {str(name)[:30]:<32}{', '.join(sorted(ids)[:3])}")
print()
print(f"orphan identifiers (no name to bind to, kept anyway): "
      f"{int(obs['subject_mention_id'].isna().sum())}")

# %% [markdown]
# ### One entity, end to end
#
# A dossier: every claim it touches, every attribute, and every piece of evidence
# traced to a span in a specific note.

# %%
dossiers = repo.all_dossiers()
d = max(dossiers, key=lambda x: x["n_mentions"])
print(f"{d['canonical_name']}  [{d['class']}]  {d['n_mentions']} mentions")
print("identity  :", d["identity"])
print("attributes:", list(d["attribute_timelines"].keys()))
print()
for ev in d["evidence"][:6]:
    print(f"  {ev['doc_id']}:{ev['span'][0]}-{ev['span'][1]}")
    print(f"    {ev['snippet'][:100]}")
    print(f"    -> {ev['machine_annotation']}")

# %% [markdown]
# Every line of that dossier is reproducible from the tables — the annotation is
# rendered from stored data, not generated prose at display time. That is what
# makes it something you can put in front of an adjuster.

# %% [markdown]
# ## Known limitation, shown rather than hidden
#
# Look at the `surfaces` column above and you will find the same organization
# listed under several rows. That is real, it is measurable, and it is worth
# showing on the way past.

# %%
same_surface = (dataset.groupby("entity")
                .agg(entities=("entity", "size"), mentions=("mentions", "sum"))
                .query("entities > 1")
                .sort_values("entities", ascending=False))
print(f"{len(same_surface)} names resolve to more than one entity")
print(same_surface.head(8).to_string())

# %%
edges = repo.table("same_as_edges")
surf = repo.table("mentions").set_index("mention_id")["surface"].to_dict()
live = edges[edges["suppressed_reason"].isna()].copy()
live["sa"] = live["mention_id_a"].map(surf)
live["sb"] = live["mention_id_b"].map(surf)
identical = live[(live["sa"] == live["sb"]) & live["sa"].notna()]
if len(identical):
    over = (identical["probability"] >= CFG.ER_LINK_THRESHOLD).mean()
    print(f"edges joining BYTE-IDENTICAL surface text : {len(identical)}")
    print(f"median probability                        : {identical['probability'].median():.3f}")
    print(f"clearing the {CFG.ER_LINK_THRESHOLD} threshold"
          f"                    : {over:.1%}")

# %% [markdown]
# **What this is.** Not a blocking failure — those pairs were proposed, scored
# and stored. They are scored by the wrong model.
#
# `ForenameSurnameComparison(first_name, last_name)` is a *person*-name
# comparison, and `first_name`/`last_name` are just `tokens[0]` and `tokens[-1]`.
# Organizations parse absurdly under it:
#
# ```
# 'delgado legal partners'  ->  first='delgado'  last='partners'
# 'kim spine institute'     ->  first='kim'      last='institute'
# ```
#
# The commonest "surnames" among organization mentions are `llp`, `care`,
# `chiropractic`, `group` — structural suffixes shared by many distinct firms.
# Term-frequency adjustment, which correctly down-weights a match on a common
# surname like *Smith*, therefore penalises exactly the matches it should
# reward: for an organization the distinguishing token is the **first** one.
#
# Entities *with* a corroborating identifier resolve fine — that is why
# `Yusuf Nguyen` merged above. Entities known only by name mostly do not.
#
# **Lowering the threshold is the wrong fix**: `ER_LINK_THRESHOLD` was chosen
# from a measured B-cubed curve, and dropping it would raise false merges
# everywhere else. The real fix is the `entity_type` / `role` split (diagram 06),
# after which organization names can use a whole-string comparison with term
# frequency over the full name. That changes the comparison model and would
# invalidate every accuracy number measured against the current one, so it
# belongs in its own measured pass — not as a demo tweak.

# %% [markdown]
# ## Phase 5 — Ask it a question
#
# Layer 4: retrieval hard-scoped to one claim.

# %%
from src.agent import ClaimScopedAgent

agent = ClaimScopedAgent(repo)
claim = docs["claim_id"].value_counts().index[0]
ans = agent.answer(claim, "who are the parties on this claim and how are they connected?")
print("scope   :", ans["scope"])
print("parties :", [(e["name"], e["class"]) for e in ans["entities"]][:8])
print()
print(ans["answer"][:900])
print()
print("citations:", ans["citations"][:4])

# %%
repo.close()

# %% [markdown]
# ## What this demonstrated
#
# - A note arrived, was segmented, extracted, embedded, blocked, scored, and
#   folded into the resolved dataset — at a cost proportional to the note.
# - Mentions in it were matched to entities that were already there, using a
#   model trained during backfill and never silently retrained.
# - Every stage said what it decided while it ran.
# - The output is an entity dataset where every fact traces to a span in a note.
#
# **What it did not demonstrate.** The notes are synthetic. They are realistic —
# email chains, boilerplate, ALL-CAPS blocks, negation, orphan identifiers — but
# `corpus_gen` wrote them, and it also wrote a ground-truth manifest that the
# research notebooks use to measure accuracy. Running this on real claim notes
# needs no code change on this path (nothing here reads the manifest), but the
# accuracy numbers in `ARCHITECTURE.md` are measured against synthetic data and
# should not be quoted as if they were measured on yours.
