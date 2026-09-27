# Record linkage [B]: extracted entity records against a watchlist

Two spreadsheets in (extracted entity records, and a watchlist), one Excel workbook out: for
each extracted party, how likely it is on the watchlist, which watchlist rows it could be,
field-by-field evidence, and what every number rests on. No text is read; relationships come
only from rows and shared details. Design: [DESIGN.md](DESIGN.md); build plan:
[PLAN.md](PLAN.md). Everything is in this notebook; data files stay files (`mappings/`,
`reference/`, and the gitignored `data/`, `out/`, `review/`).

**Run.** `RL_DATASET=synthetic|leie|scale|files` (default `synthetic`), then run all cells.
`python run_notebook_check.py` runs every cell on the synthetic set and exits non-zero on any
error or failed self-test.

**Sections.** Matching core v1.0 (shared with goko-v2-poc) · 0 Setup · 1 Mappings,
reference tables, inputs · 2 Normalize · 3 Breakdown · 4 Value index · 5 Category · 6 Outside
rarity and party frames · 7 Candidates · Noise engine · Synthetic data · LEIE exporter ·
8-11 Comparisons, u, m, prior · 12 Score · 13 Roll-up · 14 Evidence · 15 Workbook and manifest ·
16 Diagnostics · Edge-case check · Pipeline function · Run · 17 Self-tests · Acceptance ·
18 Review sample (later phase: skeleton only).

**Rules this notebook keeps** (project_v0.2/AGENTS.md): every link carries a score and a basis,
name-only links are visible and never upgraded, conflicting identifiers veto (rule 5); every
gate has an unresolved outcome: an extracted party with no candidate is shown as such, empty
rows and dropped oversized blocking keys are listed (rule 11); truth files are read only by
diagnostics and self-tests, never by the pipeline (rule 13).
