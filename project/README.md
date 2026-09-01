# Entity Intelligence over Synthetic Insurance Claim Notes — Research POC

A runnable research POC that builds an entity-intelligence system over a
synthetic corpus of legacy-style insurance claim notes: it generates the corpus
with a **sealed ground-truth manifest**, profiles and extracts entities/assertions
with full **scan-coverage proof** and **span grounding**, resolves mentions into
versioned entities, builds **verifiable dossiers**, audits itself honestly against
ground truth, and serves a **lookup + NL-query app** where every answer traces back
to a highlighted span in a raw note.

The four invariants are the point of the research: **corpus immutability**,
**leakage guard**, **span grounding**, **100% scan coverage**. They are enforced
mechanically and checked in notebook 09.

## Runtime

- Target: **Google Colab**, top-to-bottom on a fresh VM. `notebooks/09_run_all.ipynb`
  installs deps, seals/verifies hashes, runs the guards, executes notebooks 01–08
  (papermill-style via nbclient), prints the audit summary, and checks the
  acceptance checklist. Full offline run ≈ 3–4 min (well under the 40-min target).
- **GenAI:** all structured calls use **Gemini** (`GENAI_MODEL`) with JSON-schema
  constrained output; embeddings use `EMBED_MODEL`. Model names live **only** in
  `config/00_config.py`. Provide an API key via `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` / Colab secret. **With no key the system runs in a
  deterministic offline mode** so every invariant is verifiable without network —
  see `DECISIONS.md` ("Offline determinism").
- **Vectors:** FAISS `IndexFlatIP` behind a single `VectorStore` abstraction.
- **Storage:** SQLite (+ parquet) behind a thin repository layer.

## Run it

In Colab (or locally):

```bash
pip install -r requirements.txt
# optional, for the real Gemini path:
export GEMINI_API_KEY=...          # otherwise runs deterministic offline
jupyter nbconvert --to notebook --execute notebooks/09_run_all.ipynb
```

Or open `notebooks/09_run_all.ipynb` and Run All. To launch just the app after a
run:

```python
from src.repository import Repository
from src import app
app.build_app(Repository()).launch(share=True)
```

To launch the extraction QA viewer (ground truth vs. extraction overlay,
resolution match-lineage drill-down, ground-truth correction queue -- see
`designs/qa-viewer-mockup.html` for the design this implements) after a full
run including `entity_resolution.run()`:

```python
from src.repository import Repository
from src import qa_viewer
qa_viewer.build_app(Repository()).launch(share=True)
```

Run the notebooks individually in order (00 → 08) to step through each phase.

## Layout

```
config/00_config.py     single source of truth (models, seed, thresholds, weights)
src/                    all logic (importable, unit-testable, runs offline)
  settings, hashing, textnorm, contracts, genai, vectorstore, repository,
  leakage_guard, corpus_gen, profiling, extraction, embed_index, resolution,
  profiles, audit, app
notebooks/00..09        thin wrappers over src; 09 orchestrates end-to-end
data/raw_notes/         generated corpus — IMMUTABLE after generation
data/ground_truth/      sealed manifest (only nb 01 writes, nb 07 reads)
data/hashes.json        sha256 per raw file, written once
store/                  sqlite + parquet + faiss artifacts
tests/                  build_notebooks.py (regenerates notebooks), smoke_test.py
```

## What each notebook does

| nb | phase | notes |
|----|-------|-------|
| 00 | setup & contracts | prints the frozen schema every stage shares |
| 01 | generate corpus | deterministic; writes manifest + seals hashes (GT **writer**) |
| 02 | profiling | segmentation, template fingerprinting, MinHash near-dup |
| 03 | extraction | template parser + Gemini/heuristic; span grounding + coverage ledger |
| 04 | embed & index | per-mention embeddings through VectorStore (FAISS) |
| 05 | resolution | blocking passes → scoring → adjudicator → greedy correlation clustering |
| 06 | profiles & dossiers | bitemporal attributes; table-derived machine_annotation |
| 07 | audit | recall/precision, B-cubed, coverage proof (GT **reader**) |
| 08 | lookup app | name search + NL→plan→table answer; clickable-evidence dossier HTML |
| 09 | run all | fresh-VM orchestration + acceptance checklist |
| 10 | Layer 1 | hybrid high-recall extraction (chunk→coref→union→sweep) |
| — | `entity_resolution.py` | Splink ER → probabilistic SAME_AS edges (Layer 2) |
| 11 | ablation | recall lift per extraction layer vs ground truth |
| 12 | Layer 3 | claim-scoped graph + dual storage |
| 13 | Layer 4 | per-claim agent + scope-isolation proof |

## Invariants & acceptance

Checked and printed by notebook 09:

- Corpus hashes identical before/after the full run.
- Leakage guard: notebooks 02–06, 08 and their modules never touch ground truth.
- Scan-coverage ledger shows 100% character coverage per doc (shortfalls listed).
- Every dossier fact click-navigates to a highlighted span with a table-derived
  annotation (export a dossier from nb 08 and open it in a browser).
- Audit reports GT vs extracted counts, mention recall with itemized misses,
  B-cubed, and over/under-merge listings with evidence trails.
- NL question → visible structured query plan → table-executed answer → traced UI.
- Model names only in config; FAISS only behind VectorStore; storage only behind
  the repository layer (all guard-enforced).

## Current state (corpus v2)

The fixture was rebuilt to match production data shape — occurrence → claim →
note, 390-word predominantly free-text notes, and pervasive cross-claim entity
overlap — because the previous fixture flattered every measurement.

Measured end to end, offline:

| metric | value |
|---|---|
| entity mention recall / precision | 85.7% / 81.0% |
| identifier recall | **100%** (incl. 100% of name-less mentions) |
| entity resolution (B³ P/R) | 0.82 / 0.83 — 1,010 entities vs 570 GT |
| coreference accuracy | 43% — the weakest component |
| event extraction | not implemented (GT now exists) |
| scan coverage (hygiene check) | 100% |

Resolution is Splink (Fellegi-Sunter, EM-calibrated); identity is a
**threshold-derived view** over probabilistic `SAME_AS` edges rather than a
stored merge, so the operating point is chosen from a measured B³ curve and a
questionable link is filterable rather than structural.

Run `python tests/smoke_test.py` to verify every invariant end to end
(`--fast` skips resolution).

See **`ARCHITECTURE.md`** for the full evaluation, the bugs the new fixture
exposed, and what is still not good enough.

See `DECISIONS.md` for design rationale and honest known limitations.

## Ground truth on real client data

Everything above is measured against the synthetic corpus. Building a real
ground-truth set on a client's actual notes is a separate track, planned in
full in `designs/`:

- **`ground-truth-plan.html`** — the build plan: tiers, sizing, sprints, tickets.
- **`ground-truth-timeline.html`** — the same tickets scheduled on a calendar, by owner.
- **`annotation-guidelines.html`** — the manual for whoever does the marking.
- **`data-scientist-manual.html`** — the engineering process, stage by stage, with file citations.

The short version of what those four documents work out in detail:

**Silver.** The client's own records already say a name belongs to a given
claim, but never say *where* in the note text — and our extraction system
scores on exact position, not just on a name matching. So a script locates
each client-known entity in the actual note text (trivial where the client
already ran an exact-text search; real name-matching where their AI-derived
match may have normalized the text away from its literal form), our
extraction pipeline runs against those same real notes for the first time,
and the two are compared. Anywhere they disagree — a name the locator
couldn't find, a phone number our system found that the client's record left
blank — a human gives a quick yes or no. That produces two cheap, concrete
things: specific, provable evidence of what the client's process is missing
today (the actual deliverable), and a sanity check that our system isn't
somehow worse than what they already have. It cannot tell you how much
*nobody's* process is finding, because every question in it starts from a
name someone already had.

**Gold.** A separate, smaller set of notes gets read by a human with nothing
shown — no client list, no located spans — who marks every entity they see,
then only afterward reconciles against what the locator found. That's the
only step that can surface entities nobody's process — not the client's, not
ours — ever flagged, and it's what makes the eventual recall and precision
numbers defensible with a real confidence interval rather than "we agree
with what was already tracked."

Both write into the same manifest shape the synthetic corpus already
produces, so `audit.py` and `qa_viewer.py` run against real ground truth
unmodified once it exists.
