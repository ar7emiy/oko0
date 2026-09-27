# STATE

Last updated: 2026-09-26.

Archive (2026-09-23): this folder now holds only goko-v2-poc, gold-annotator and their
governing documents. Moved to `../archive/`: the Excel and desktop annotators
(python-annotator, offline-annotator, offline-python-annotator, ANNOTATION-DELIVERY-README),
the design studies (`designs/`, including the Excel tutorial; references below to
`designs/` now resolve under `../archive/project_v0.2/designs/`), and the EVALUATION.md
redirect stub. The gold-annotator's test packets moved from `python-annotator/sample-data/`
to `gold-annotator/sample-data/`; its 91 unit tests pass from the new location. goko-v2-poc
status is in its own README.

Proposal visual follow-up: real annotated app screenshots replace concept artwork;
the redundant metric illustration was removed. Browser workflow passed 35 checks
on temporary fictional data. No application source changes.

Client proposal renamed to ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md with proposed
output model and concept illustrations. Identifier and unassigned-detail gaps are
tracked in gold-annotator/REVIEW-AND-IDENTIFIER-REQUIREMENTS.md. Documentation only;
SVGs rendered and inspected, and application code was not changed.

Evaluation calculation reference added: explicit formulas and conceptual input
requirements for gold evidence, GOKO results and SME comparison decisions, without
fixing an export schema. Documentation only; application behavior is unchanged.

Evaluation editorial follow-up: client-facing lightpaper now explains the proposed
method through GOKO's supplied fields, standard metrics and the SME review design.
Current support and proposed extensions are distinguished. Documentation only.

Evaluation plan revised against current gold-annotator code: claim-first and
cross-claim review, explicit comparison requirements/denominators, below-90
watchlist review proposal, frozen benchmark cohorts and future span measures.
Documentation only; no new runtime features or tests are claimed. See EVALUATION.md.

Client import increment: the gold annotator now reads XLSX and client header
aliases, splits comma-separated note citations and normalizes numeric `.0`
suffixes for claim-local lookup. Shared note IDs retain separate SME work per
claim. Validation: 91 Python tests and 35 headless Edge checks, all synthetic;
the real client workbook has not been supplied.

Latest annotation increment: persisted annotation Undo, a second independent
fictional practice claim, explicit comparison completion, opt-in practice export,
and three consolidated analysis CSVs. KPI provenance and denominators are in
`gold-annotator/KPI-DATA-GUIDE.md`. Checks: 83 Python tests and 35 headless Edge
checks passed with synthetic data; no real-data accuracy evaluation was run.

## Record linkage [B] (`record-linkage/`), 2026-09-26

**Built** (executable): `record_linkage.ipynb`, one notebook holding the matching core v1.0
(normalizers, rarity lookups, comparison levels, Fellegi-Sunter scorer, vetoes, basis,
parameter estimation; code-cell SHA-256 `f51d969c9f7efe34c4b2abbd416542003d79308ab12694a09ce24852591a2c48`
checked by a self-test), breakdown, value index, category, blocking, u / m / prior estimation,
scoring, roll-ups, evidence, workbook, diagnostics, the LEIE exporter, the synthetic generator,
51 self-tests and an acceptance table. `run_notebook_check.py` runs every cell. Mappings and
reference tables are files; data, outputs and review labels are gitignored.
The development modules (`src/wlink`, `tests/`) were assembled into the notebook and removed
(they remain in git history, commit 9e33221).

**Checked** (actual runs on this machine, Windows, Python 3.13, pandas 3.0.6, recordlinkage 0.16):
- Synthetic (2,962 extracted x 5,047 watchlist rows): notebook check 84 s for every cell
  including self-tests; pipeline 37 s; 51/51 self-tests; 53/53 hand-written edge-case
  expectations; 99.21% of true pairs proposed (2,135/2,152), every proposed true pair kept.
- OIG LEIE (84,001 rows) against 3,000 noisy LEIE copies + 3,000 fictional parties:
  125 s excluding the 18 s export; 98.90% of true pairs proposed (2,967/3,000); one proposed
  true pair fell below the keep rule (2,966/2,967 visible); peak 1.3 GB.
- 1/10 benchmark (100,000 x 28,090 rows): pipeline 93 s, 473k pairs scored, recall 99.0%
  persons / 99.9% businesses.
- **Full benchmark (1,000,000 watchlist x ~300,000 extracted rows): target not met.**
  Generation 470 s (not counted); normalize to rarity 226 s; u and m 385 s; scoring 49.1M
  pairs (21.1M business, 28.0M person) in 2,582 s, i.e. 54 min to the end of scoring, peak
  8.5 GB; then the evidence step failed with an out-of-memory error building evidence for
  10.2M kept pairs. Causes: single-core per-unique-pair Python comparisons (about 50 us per
  pair), the keep rule (top 3 with ties) keeping 10M pairs, and a synthetic business
  universe whose blocks are dense (rarest-word blocks: 30M pairs before refinement).

**B2, gold labels (built 2026-09-26, branch `claude/record-linkage-b2`)**: `record-linkage/b2_sections.py`,
notebook sections in percent format, **not yet inserted** into `record_linkage.ipynb` (B1 is
changing the notebook in parallel; insert at its marked point). Label schema; stratified review
sampler (p band x basis, weights, sealed split per extracted party by hash); blind SME Excel
packets, instructions, data dictionary, label templates, adjudication sheet; label ingestion
(XLSX / CSV / Parquet, Delta via `deltalake` or the pipeline's IO), validation, Cohen / Fleiss
kappa, adjudication; sealed-split evaluation with post-stratified HT weights, recall ceiling,
reliability, Brier, bootstrap; four switchable improvements (calibration, semi-supervised EM,
gradient boosting with exact per-field contributions, cost threshold) with a pre-stated adoption
rule; active-learning next batch; 17 self-tests. Fictional stub packets in
`record-linkage/review/stubs/` (committed, regenerate byte-identically).

Checked (actual runs, synthetic SMEs from the truth files with 2-6% flips and frequent "unsure"
on name-only pairs; every sealed and calibration pair double-coded and adjudicated):
- 17/17 B2 self-tests pass standalone on the synthetic and LEIE outputs, and inside a copy of the
  notebook with the sections appended (all cells ran, 118 s; the notebook itself not changed).
  Includes: sealed views refused by every fitting function, and flipping every sealed label
  leaves every fitted parameter unchanged; a deliberately miscalibrated B1 gets calibration adopted.
- Synthetic (11,545 candidates; 1,500 sampled, 612 sealed): B1 at p >= 0.5, HT-weighted on the
  sealed gold labels: precision 0.990, recall in the candidate space 0.972, F1 0.981, Brier 0.0061;
  recall ceiling 0.992 (truth), so overall recall ~0.964. Name-only pairs: precision 0.82, recall
  0.64. No improvement adopted (calibration, EM and the supervised model are worse on Brier; the
  cost threshold's interval spans 0).
- LEIE (30,415 candidates; 595 sealed): B1 precision 0.943, candidate-space recall 0.924, F1 0.933,
  Brier 0.0126; ceiling 0.989, overall recall ~0.914; name-only recall 0.46. Supervised model
  better on the point estimate (Brier 0.0116, F1 0.943) but its interval spans 0; nothing adopted.
- Label noise: with only 25% of sealed pairs double-coded, B1's sealed Brier on synthetic read
  0.030 instead of 0.006, i.e. SME noise dominated the measurement; hence the double-coding default.
- Real SME labels: none yet. The gold-annotator cannot import the packets (it needs a pair-review
  queue; see record-linkage/README.md).

Environment note: with `core.autocrlf=true`, a fresh checkout converts
`reference/nicknames_LICENSE.txt` to CRLF and B1's reference-hash self-test fails (recorded
hashes mix LF and CRLF files); worked around locally, not committed.

**Not built**: the copy of the core into
goko-v2-poc [A]; cited published m values (`mappings/published_m.csv` holds stated
assumptions and placeholders, marked as such). No client data has been run.

## Record linkage B1 / B1.1 (`record-linkage/`), 2026-09-26

B1 ("no gold labels, high-quality output, runs now") and B1.1 ("the same on Delta Lake") built
on branch `claude/record-linkage-b1` from the tip of `claude/determined-albattani-wonyak`
(commit 599f23b). Matching core bumped to **v1.1**; hash re-recorded (below). Gold-label
sections are being built in parallel by another workstream ("B2") in a separate file; this
notebook leaves a marked insertion point at the end (section 18) for them and does not touch
gold/label/calibration features itself.

**Built** (executable), added to the notebook: exact-agreement u in closed form over all pairs
(`closed_form_u`); richer name/organization comparisons (Jaro-Winkler, normalized Levenshtein,
rapidfuzz token-sort/token-set, NYSIIS, Metaphone; a rarity-weighted org `close` level; middle
name compared only once the surname already agrees); a modular US address standardizer
(`given` / `usaddress` default / `smarty`, the last never called without credentials and never
in tests); Splink-style EM in several training passes with a Dirichlet prior toward the
existing source chain, bootstrapped 95% intervals, an m floor and bounded bits, and an
`unstable` flag; a recall-maximizing blocking-rule union (widened further, see below) plus an
`EXHAUSTIVE` switch; extracted-side deduplication into pooled entities (a second comparison
context against the extracted file itself, `constrained_clusters` union-find respecting
identifier vetoes) that are matched against the watchlist with a multiplicity correction;
consistent post-scoring clusters (same constrained union-find) with name-only links visible but
never clustered; a held-out-identifier self-check (SSN/NPI/TIN/DL) and a noise-injection test,
both first-class outputs with precision/recall by threshold and by basis and the candidate
stage's lost true pairs; an optional baseline module (rapidfuzz `token_sort_ratio` + category
gate, off by default, `p_baseline` in the candidates table) with a disagreement report against
B1; an `IO_FORMAT` switch (`csv` / `parquet` / `delta`) covering inputs and every output table;
a bounded summary workbook (full tables moved to CSV/Parquet/Delta); a Delta incremental mode
(change-data-feed-driven re-scoring, a link cache, MERGE with kept history) with a placeholder
gold-labels table for B2. **82 self-tests** (51 carried over, updated for the entity grain and
new level names where semantics changed, plus 31 new: closed-form u, EM/bootstrap bounds,
richer comparisons, the address standardizer (including an injected fake for the `smarty` path),
extracted-side deduplication, veto-respecting clustering, the baseline module, the table-I/O
layer and an incremental-vs-full-run equivalence check). Matching core v1.1 code-cell SHA-256:
`24d2b8a678f103c62332f71114a5c10979d31416cabf2acef3a934ffd125549a`.

**Checked** (actual runs on this machine, Windows, Python 3.13, pandas 3.0.6, recordlinkage
0.16, rapidfuzz 3.14.6, usaddress 0.5.16, scipy 1.18.1):
- Self-tests: 82/82 pass (`python run_notebook_check.py` also runs them as part of the
  synthetic check).
- **Synthetic run** (`RL_DATASET=synthetic`, default settings, `SELF_CHECK=True`,
  `BASELINE=False`): every cell ran in 609 s (includes 82 self-tests and 6 full pipeline
  reruns for the self-checks: 4 held-out identifiers + the noise test; B1 is not
  time-optimized, see PLAN.md/DESIGN.md). Main pipeline 475 s. 2,527 extracted person parties
  -> 1,942 entities (507 pooled, 1 dedup link refused for a conflicting identifier); 646
  business parties -> 505 entities (123 pooled). Blocking recall on true synthetic pairs
  99.72% (2,146/2,152); candidate stage lost 6/2,259 true pairs (0.27%) across the
  self-checks. 53/53 hand-written edge-case expectations met. 2,145/2,146 kept true pairs
  visible (the same "one pair falls below the keep rule" pattern as v1.0's LEIE run).
  79 m/u level rows, all with a source. 45,848 pairs scored.
  - Held-out-identifier check, B1 precision/recall at p >= 0.5 (`out/synthetic/tables/selfcheck_bands.csv`
    has every threshold): SSN 0.972/0.913 (115 true pairs), NPI 1.000/0.943 (297), TIN
    0.973/0.982 (112), DL 0.984/0.984 (63).
  - Noise-injection test, B1 precision/recall at p >= 0.5: person 0.953/0.986 (1,404 true
    pairs, up to 3 noisy copies per source plus 800 decoys), business 0.957/0.989 (268).
  - Precision by basis at p >= 0.5 (`selfcheck_basis.csv`): identifier and address bases are
    at or near 1.00 precision throughout; the weaker spots are exactly where little evidence
    exists — noise-test `name_only` (0.625-0.765, 4-13 true pairs) and `contextual` under
    heavy noise (0.60-0.81) — both small-count strata, reported rather than hidden.
  - `BASELINE` was not run on synthetic (LEIE below has the B1-vs-baseline comparison the
    task asked for).
- **OIG LEIE** (84,001 watchlist rows, exported from the raw download) against noisy copies
  of 3,000 LEIE rows + 3,000 fictional parties, `RL_BASELINE=true`, default `SELF_CHECK=True`:
  every cell ran in 1,349 s (82 self-tests + 2 full pipeline reruns for the self-checks: the
  held-out-identifier check ran only for NPI — LEIE has no SSN/TIN/DL fields, so those were
  correctly skipped as "fewer than 5 true pairs" — and the noise test). Main pipeline 1,202 s:
  17 s LEIE export, 26 s normalize/standardize/breakdown/category, **331 s u/m/prior**
  (dominant cost: closed-form u plus a 5,000,000-pair sample and Splink-style EM with 200
  bootstrap replicates per level, both dedup and link models), 21 s candidates/dedup/link/
  cluster, 18 s roll-ups/evidence/diagnostics; held-out check 388 s, noise test 409 s; peak
  3.35 GB (well inside memory; the v1.0 1M-row benchmark had failed here). 5,885 extracted
  person parties -> 5,207 entities (605 pooled, 1 refused); 115 business parties -> 115
  entities (no business duplicates in this extracted set). 99.30% of true pairs proposed
  (2,979/3,000); candidate stage lost 19/4,401 true pairs across the self-checks (0.43%);
  2,978/2,979 kept true pairs visible (one below the keep rule, the same pattern v1.0's LEIE
  run showed). 79 m/u level rows, all sourced. 577,142 pairs scored.
  - **Held-out-identifier check (NPI, 339 true pairs), B1 vs baseline, precision/recall
    at p >= 0.5** (`out/leie/tables/selfcheck_bands.csv`): B1 0.994/0.976, baseline (token-sort
    >= 90 + category gate) 0.927/0.820. B1 leads on both; the baseline's 61 missed true pairs
    split 5 blocked by the category gate, 56 name-too-different (`selfcheck_funnel.csv`).
  - **Noise-injection test, person (3,874 true pairs)**: B1 0.961/0.960, baseline 0.761/0.559.
    B1 leads by a wide margin; baseline misses split 972 blocked by the gate, 735
    name-too-different.
  - **Noise-injection test, business (188 true pairs)**: B1 0.685/0.936 at p >= 0.5, rising to
    0.845/0.931 at p >= 0.8 and 0.869-0.893/0.89-0.91 at p >= 0.9-0.99; baseline 0.898/0.702.
    **This is the one place the baseline's precision beats B1's at the loosest threshold** —
    traced in `selfcheck_basis.csv` to the `name_only` basis alone (15 true positives, 54 false
    positives, precision 0.217): LEIE's business universe is thin and its extracted-noise test
    has no business duplicates to anchor on, so purely-name business matches at p >= 0.5 are
    genuinely weak evidence here and B1 shows them as such (AGENTS rule 5: name-only is visible,
    never hidden or upgraded) rather than suppressing them the way a fixed threshold would.
    Every other basis (address, identifier, contextual) is at 0.91-1.00 precision. Reported
    plainly rather than tuned away.
  - Decision-card evidence for every disagreement is in `baseline_disagreements.csv`, e.g. the
    baseline's false alarms B1 avoids: "Amber Wright" / "AMBER L BRIGHT" (token-sort 92, no B1
    candidate at all — DOB/address disagree); "Robert Johnson" / "ROBERT MAX JR JOHNSON"
    (token-sort 100, B1 p=0.013, basis name_only, address differs -2.5 bits). Ambiguity
    (`baseline_ambiguity.csv`): most extracted names hit exactly one watchlist row under the
    baseline; up to 50 for the noisiest common names.
- Candidate generation, true pairs lost: reported per run in `selfcheck_funnel` and in the
  manifest's `selfcheck.funnel` section (`lost_at_candidates`); 6/2,259 (0.27%) on synthetic,
  19/4,401 (0.43%) on LEIE.

**B1.1 (Delta Lake) testing status: faked, not real.** This machine has no Java, so `pyspark`
cannot run locally regardless of installation (it needs a JVM `delta-spark` also depends on).
The Delta I/O layer (`TableIO`, table versions, change data feed, MERGE, incremental scoring)
is tested against `InMemoryDeltaBackend`, a pure-pandas stand-in with the same interface, in
`TestTableIO` and `TestIncremental` (including a check that an incremental run reproduces a
full run's entity probabilities on an unchanged snapshot). `SparkDeltaBackend` implements the
same interface over real `pyspark.sql` / `delta.tables.DeltaTable` calls and is used
automatically once a Spark session exists (Databricks) or `pyspark` + `delta-spark` are
installed with a JVM present; it has not been exercised against a real cluster from this
machine.

**Not built**: the copy of the core into goko-v2-poc [A]; a standalone reloadable model
artifact outside the Delta incremental path (`rl_model` reload works only inside
`run_incremental`); cross-type matching (still out of scope, PLAN.md open question 6); a real
Spark/Delta run (see above). No client data has been run.

## Python annotation workbench delivery

The subsequent SME workflow increment adds a claim-level evidence dossier and
independent category review before firm comparison. Evidence-linked category
decisions and a frozen answer-key checkpoint retain exact record revisions,
taxonomy and source fingerprints. Current annotations remain editable without
silently changing frozen evaluation inputs. See `gold-annotator/STATE.md`.
Increment checks: 69 Python tests and 30 headless Edge workflow checks passed.

The SME annotation UI now exists in `gold-annotator/`: a standard-library Python
server with a browser interface, file-backed notes and SQLite annotation storage.
It supports manual annotation, optional Copilot draft review, claim-wide entities,
completion, post-seal comparison, category/watchlist judgments and CSV export.
Codex completed the Claude handoff on `codex/first_principles_rebuild`.
Checks: 55 Python tests and 27 headless Edge workflow checks passed; screenshots
of the tutorial, draft controls and comparison form were reviewed. Copilot reply
fixtures are simulated; no tenant or client-data evaluation was performed.
See `gold-annotator/STATE.md` for the trace, limits and repeatable QA commands.
This delivery is the annotation workbench, not the proposed v0.2 extraction runtime.

## Current status

**Extraction-runtime documentation scaffold complete. No v0.2 extraction runtime or client evaluation has been executed.** The approved redesign now follows v0.1's root Markdown layout: README, ARCHITECTURE, AGENTS, CLAUDE, and STATE.

## Delivered

- General-first architecture and explicit evidence/reference/identity/presentation gates.
- Offline HTML tutorial, complete fictional note files, and editable Excel workbooks for independent annotation, client-record review, and watchlist pair review.

Evaluation materials distinguish assisted silver review from independent, adjudicated gold annotation over complete claim files, independent of model chunks. The tutorial highlights the original note text and directly maps every demonstrated mention to a workbook row. Workbooks have completed fictional examples and blank templates for gold, silver, and watchlist review.

Validation: all watchlist workbook sheets were inspected and rendered; gold/silver workbooks and original-note example addresses were previously checked. The tutorial is static and contains no input, download, persistence, or submission controls. These checks validate the training materials, not either system's accuracy.

The four-field client export shape and exact-search versus GenAI behavior follow the user's clarification. Worked examples are fictional. Existing entity records are leads, not labels. No client notes, watchlist, exports, or ground-truth data were opened or modified.

## Implementation next

1. Implement source-version/evidence persistence and repeat-safe ingestion.
2. Implement one model adapter and inspectable mention/statement proposal storage; choose the provider/model as an implementation decision.
3. Deliver the first source viewer and provisional dossier, then local reference decisions and correction history.
4. Add corpus candidate comparison and explicit consolidation/split decisions.
5. Enable later adapters/retrieval features individually after documenting their new decision permissions.

## Evaluation next

Client owner supplies frozen UTF-8 note versions, structural metadata, entity exports, and watchlist/pipeline decision records. Confirm evaluation scope and permitted reference sources. Two SMEs pilot the guide independently; a lead adjudicates. The analyst fixes the sampling/split plan before selecting the main study and keeps tuning separate from the test release.

## Open implementation and study choices

Model provider; first UI; how client categories are defined; alert unit and actual threshold/tie behavior; availability of rejected/no-candidate logs; eligible time window; annotation staffing and study size after pilot effort is known. These are explicit future choices, not invented completed decisions.

Earlier audits remain in `designs/` as history. The general-first design and root ARCHITECTURE take precedence over them. New ground-truth measures are permitted for the requested evaluations; old reported metrics are not used as design inputs.

## Offline annotator tutorial

The primary delivery is `designs/learning/annotation-training.html` and `designs/annotator-learning-package.zip`. PDFs, executive-plan documents, the PDF generator, and the earlier browser data-entry workflow were deleted at the user's request. Do not generate them.

The HTML is a visual, read-only e-learning walkthrough. It starts from the full notes, highlights names, pronouns, descriptions, and repeated mentions in place, and lights up the corresponding Excel rows. Annotators work only in supplied `.txt` files and their Excel workbook. The watchlist workbook separates the unaltered pair input, field comparisons, pair decision, and optional source evidence. It is a training tool, not the extraction runtime or an adjudication backend.
