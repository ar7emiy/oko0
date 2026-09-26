# %% [markdown]
# # 03 - Layer 1: Hybrid High-Recall Extraction
#
# Overlapping chunking -> coreference -> **union** of (token-NER ∪ gazetteer ∪
# LLM) -> pass-2 differential sweep.
#
# The premise: a single LLM pass misses low-salience entities. A name that
# appears once, in a signature block, in the middle of a template, is not
# *interesting* to a summarising model — but it is exactly the name an
# investigator needs. So every extractor runs and the results are unioned;
# recall is bought at the candidate stage and precision is decided later.
#
# This notebook shows each component separately, then runs the whole stage into
# the `mentions` / `assertions` tables that Layers 2-4 consume.

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
from src import chunking, coref, gazetteers, ner_ensemble, sweep
from src.settings import CFG, Paths

print("chunk target:", CFG.CHUNK_TOKENS, "tokens, overlap", CFG.CHUNK_OVERLAP_RATIO)
doc = sorted(Paths.raw_notes.glob("*.txt"))[1]
text = doc.read_text(encoding="utf-8")
chunks = chunking.chunk_document(doc.stem, "CLM0000", text)
print("chunks:", len(chunks), "| coverage:", chunking.coverage_report(text, chunks))

# %% [markdown]
# ## Gazetteers - structured codes are never left to a language model
#
# An NPI has a checksum. An email has a grammar. Handing those to an LLM trades
# a decidable check for a probabilistic one. `validation` records which kind of
# check actually passed, so a checksum-verified NPI and a merely well-shaped
# string are never treated as equally trustworthy downstream.

# %%
for h in gazetteers.scan_valid(text):
    print(f"  {h.label:16s} {h.text!r:28s} validation={h.validation}"
          f"  checksum_verified={h.checksum_verified}")

# %% [markdown]
# ## Token-level NER
#
# GLiNER is the production backend and is **required**: if the weights are
# unreachable it raises `NERBackendUnavailable`. There is no automatic fallback
# to the deterministic research backend, because a run that silently degrades to
# regex name-shape matching produces numbers that look like NER numbers.

# %%
backend = ner_ensemble.get_token_ner()
print("backend:", backend.name)
for c in backend.extract(text, 0)[:10]:
    print(f"  {c.label:18s} {c.text!r}")

# %% [markdown]
# ## The union, with provenance

# %%
spans = ner_ensemble.extract_chunk(chunks[0], backend)
extra = sweep.sweep_chunk(chunks[0], spans)
allspans = ner_ensemble.union_spans([spans, extra])
for c in allspans[:14]:
    print(f"  {c.label:16s} {c.text!r:34s} found_by={sorted(c.extractors)}")
print()
print("residual unmapped after sweep:", sweep.residual_report(text, allspans))

# %% [markdown]
# `found_by` is the ablation's raw material: it says which extractor would have
# had to be present for each span to survive. Spans found by exactly one
# extractor are the ones that justify running all of them.

# %% [markdown]
# ## Coreference - pronouns and descriptors are LINKS, never nodes
#
# "The claimant" is not an entity. Creating a node for it produces a graph where
# every claim has a party called "the claimant" and none of them are anybody.

# %%
demo = ("Dr. Ruiz treated the claimant. Ace Collision billed us. "
        "The shop inflated parts and the physician disagreed.")
ms = [{"start": demo.index("Dr. Ruiz"), "end": demo.index("Dr. Ruiz") + 8,
       "text": "Dr. Ruiz", "label": "medical_provider"},
      {"start": demo.index("Ace Collision"), "end": demo.index("Ace Collision") + 13,
       "text": "Ace Collision", "label": "repair_shop"}]
for link in coref.get_resolver().resolve(demo, ms):
    print(f"  {link.kind:10s} {link.surface!r:16s} -> "
          f"{link.antecedent_surface!r} ({link.antecedent_class})")

# %% [markdown]
# ## Run Layer 1 over the whole corpus

# %%
from src import pipeline_v2
from src.repository import Repository

repo = Repository()
print(pipeline_v2.run(repo))

# %%
mentions = repo.table("mentions")
assertions = repo.table("assertions")
print("mentions by class:")
print(mentions["entity_class"].value_counts())
print()
print("mention provenance (which extractor found it):")
print(mentions["extractor"].value_counts())

# %%
print("predicates:")
print(assertions["predicate"].value_counts())
print()
print("polarities:")
print(assertions["polarity"].value_counts())
print()
print("grounded fraction:", round((assertions["grounded"] == 1).mean(), 4))

# %% [markdown]
# `grounded == 0` means the stored value does not match the text at the stored
# span. Those rows are kept and flagged rather than dropped, so the span-fidelity
# failure rate is visible instead of being hidden by deletion.

# %%
print("mentions inside high-boilerplate regions:",
      int((mentions["boilerplate_score"] > 0.5).sum()),
      "- kept and flagged, not dropped")
print("mentions inside quoted blocks:", int(mentions["inside_quoted"].sum()))

# %%
repo.close()
