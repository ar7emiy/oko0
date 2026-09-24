# STATE

Last updated: 2026-09-23.

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
