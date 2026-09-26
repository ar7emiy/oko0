# Notebooks

Every notebook here is a **`# %%` cell-format `.py` file**, not `.ipynb`.

## Why this format

`# %%` marks a cell boundary. VS Code, PyCharm, Spyder and `jupytext` all
recognise it, so these files:

- run **cell-by-cell** in an editor, with the same interactive feel as a notebook;
- run **start-to-finish** as an ordinary script (`python notebooks/03_extraction.py`),
  which is how `99_run_all.py` executes them — a fresh interpreter each, no
  nbconvert, no kernel nesting, and a traceback that names a line you can open;
- **diff and review as source**, so a change to a cell is a one-line diff rather
  than a churn of JSON with embedded outputs and execution counts;
- convert on demand: `jupytext --to ipynb notebooks/03_extraction.py`.

Nothing is written in both formats. There is one file per notebook and it is the
source of truth.

## What was here before

Fourteen `.ipynb` files **generated** by `tests/build_notebooks.py` — a 30KB
script that emitted notebook JSON with each cell's source as a Python string
literal. That was a v0 decision, and the reasoning was not silly: keeping the
pipeline call sites inside notebooks gave `leakage_guard.py` (which scans
notebook source for ground-truth reads) something meaningful to scan, while the
logic stayed in `src/` where it is testable.

What went wrong is what goes wrong with generated artifacts nobody reads:

- Editing a cell meant editing a string literal in a generator, so in practice
  nobody edited them.
- They drifted. `00_setup_and_contracts.ipynb` called
  `contracts.PREDICATES`, `GEN_PASSES`, `extraction_schema()` and
  `adjudication_schema()` — all four deleted in the v0/v1 pruning pass — and
  `05_resolution.ipynb` printed the deleted `candidate_pairs` table. Both threw
  on execution.
- Five of them described a pipeline (`extraction.py`, `resolution.py`,
  `09_run_all` orchestrating via nbconvert) that no longer existed.

The generator and its output are both deleted. `leakage_guard._notebook_source`
now just reads the file, because for a `.py` notebook the source *is* the file.

## Order

| file | stage | ground truth |
|---|---|---|
| `00_setup_and_contracts.py` | frozen schema, blocking rules, config echo | — |
| `01_generate_corpus.py` | corpus + sealed manifest + hashes | **writer** |
| `02_profiling.py` | segmentation, boilerplate score, casing regime | — |
| `03_extraction.py` | Layer 1: chunk → coref → union → sweep | — |
| `04_embed_index.py` | mention vectors (`mentions.faiss`) | — |
| `05_resolution.py` | Layer 2: Splink + the embedding recall net | — |
| `06_profiles_dossiers.py` | bitemporal attributes, dossiers | — |
| `07_audit_vs_ground_truth.py` | recall, B-cubed, coverage proof | **reader** |
| `08_graph_and_chunk_index.py` | Layer 3: graph + `chunks.faiss` | — |
| `09_agent.py` | Layer 4: scoped retrieval + isolation proof | — |
| `10_recall_ablation.py` | recall lift per extractor | **reader** |
| `11_lookup_app.py` | search + NL→plan→table answer | — |
| `20_relation_extraction.py` | open-vocabulary S-P-O against hand-written notes | reader (own GT) |
| `99_run_all.py` | orchestration + acceptance checklist | — |

`04` must run before `05`: the embedding blocking lane reads `mentions.faiss`
and raises `MentionIndexUnavailable` rather than resolving with less recall than
the configuration promises. `08` must run before `09` for the same reason.

Only the three files marked above may reference ground truth.
`leakage_guard.scan_ground_truth_leakage()` scans the rest and fails the run on
any violation — including if one of the files it expects is **missing**, since a
guard that silently vouches for a file it never read is worse than no guard.
