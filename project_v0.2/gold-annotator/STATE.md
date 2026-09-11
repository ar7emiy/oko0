# Workbench delivery status

Verified 2026-09-11 (America/Chicago).

## Client workbook import increment

- Added standard-library XLSX loading and the client's case-insensitive header
  aliases, while retaining canonical CSV support and original citation values.
- Split comma-separated Exact/GenAI citations, stripping only numeric all-zero
  decimal suffixes for lookup. Claim filenames remain the membership source.
- Shared note IDs retain separate claim annotations; missing cited files are
  labeled in comparison and never opened under another claim.
- Added sparse/shared/inline Excel cell decoding, simple zero-padding formats,
  cached-formula handling and explicit errors for unavailable formula values.
- Fixed row ID collisions when several imported files contain the same claim.

Validation: **91 Python tests passed** and **35 headless Edge checks passed**.
New synthetic workbook tests cover client aliases, leading zeros, citation lists,
shared note IDs, sparse cells, formula errors, duplicate aliases and multi-file
claims. The actual client workbook has not been supplied or validated.

## Undo, practice and analysis export increment

- Persisted Undo for annotation/entity mutations and draft accept/dismiss, with
  compensating revisions, source guards and reviewer isolation. Ctrl+Z preserves
  native text editing. Frozen answer keys remain unchanged; no redo is provided.
- Added an independent second fictional practice claim and five sample firm rows.
- Added explicit comparison completion tied to saved answers; changes reopen it.
- Browser exports default to three joinable analysis CSVs, with detailed audit
  export available and practice included only when explicitly selected.
- Corrected missed-detail counting to require a matching value and use unique
  gold entity/kind/value denominators. Unsupported reported details on rows marked
  not-in-notes now contribute to the reported-detail denominator.
- Documented KPI datasets, formulas, limits and joins in `KPI-DATA-GUIDE.md`.

Validation: **83 Python tests passed**, **35 headless Edge checks passed**, and
JavaScript syntax passed. Browser checks cover saved and native text Undo,
comparison completion, practice export opt-in and the second practice note.
Completion and new-practice screenshots inspected. All test data was synthetic;
the user's saved annotations and real claim files were not modified.

Earlier delivery checks below are retained as history.

## Claim-level evidence review increment

Implemented after the initial Claude handoff: **Review claim evidence** now
precedes **Freeze and compare**. The dossier shows every entity-linked record
across notes, including actions, details, and exact source navigation. Existing
annotation editing can correct ownership without moving the original evidence.

Category decisions have assigned/insufficient/conflicting outcomes, optional
explicit subcategory, rationale and support/conflict/repeated record references.
They retain revision history. A versioned, configurable role taxonomy is supplied
independently of firm exports. Changed evidence or policy requires renewed review.
An attested checkpoint freezes the complete annotation basis, category decisions,
taxonomy and source fingerprints. Comparison and core gold metrics use that
snapshot despite later annotation edits. Category coverage accompanies accuracy.
Legacy exposed claims are never retrospectively labeled independent.

Browser exports now contain only the current reviewer's answers and withhold
firm rows for claims that reviewer has not unlocked. CSV exports distinguish
current annotations from the frozen JSON checkpoint and decision history.
Full note files remain external; no automatic classifier or independent-source
corroboration inference was introduced. The starter taxonomy needs study-owner
alignment before real-data evaluation.

See [the decision card](decisions/001-claim-review.md) for the new gate and its
unresolved and reversal behavior. The historical checks below describe the
initial handoff.

Final increment verification:

- **69 Python tests passed**, including exact cross-note provenance, ownership
  correction, stale evidence/policy rejection, revision history, idempotent
  saves, concurrent-view conflicts, source changes, unresolved outcomes, legacy
  claims, export blinding and immutable scoring after later edits.
- **30 real headless Edge checks passed**, including the source-highlight modal,
  retained category inputs, both entity reviews, unsaved-change freeze blocking,
  attestation, automatic frozen category comparison and the original annotation
  and AI-draft flow.
- Dossier, category-form and comparison screenshots inspected; entity navigation
  stays visible during scrolling and the form has a jump control.
- JavaScript syntax and Git whitespace checks passed. No real claim data,
  real Copilot tenant or external classification service was used.

## Handoff trace

The latest UI is this Python server and browser app. It supersedes the Excel
interface for the requested SME workflow; it is not the extraction runtime
proposed in the parent architecture.

Claude's last committed branch head was `68b0672`. Its app implementation,
README and final browser assertion fix were present locally but uncommitted
when Claude reached its usage limit. Codex fast-forwarded
`codex/first_principles_rebuild` from `4c4e481` to that head, preserved the
local implementation, completed QA, and added delivery ignore rules and this
status record. The edited parent `EVALUATION.md` is excluded from this delivery.

## Delivered behavior

- Standard-library Python server, SQLite annotations, and local HTML/CSS/JS.
- File-backed complete notes, fingerprint checks, Unicode evidence positions,
  claim-wide entities, revision history, and manual annotation without AI.
- Optional Copilot message generation, tolerant reply parsing, explicit draft
  review, source highlighting, and guided help available from the page.
- Note completion and claim sealing, followed by firm-row pairing, category
  judgments, watchlist decisions, scores, and a CSV ZIP export.
- A fictional practice claim, excluded from the real-data export.

## Checks actually run

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 55 tests passed |
| `node tests/e2e/ui_flow.mjs` | 27 browser checks passed in headless Edge |
| Screenshot review | Tour/menu, note legend, draft card/keyboard controls, comparison form inspected |
| Simulated Copilot reply cases | All 13 fixtures meet expected ready/attention counts and exact source-slice checks |
| Faithful rich-note reply | 51 drafts ready |
| Deliberately sloppy rich-note reply | 34 ready; one paraphrase correctly needs attention |
| Truncation, repeated references, arrays, tables/refusals | Regression checks passed |

The browser suite uses temporary fictional data and checks persisted comparison
answers, JavaScript errors, covered controls and visible control names. It is a
desktop acceptance run, not a complete accessibility or production-load audit.

## Remaining deployment checks

The supplied replies are simulated, not generated in the firm's M365 tenant.
Use `check_answer.py` with real tenant replies and the longest representative
notes before relying on Copilot; adjust `--part-size` if necessary. These tests
establish parser/workflow behavior, not extraction accuracy on client data.

The default deployment is one local computer. Reviewer names are self-reported;
shared hosting needs the firm's authentication. Formal study assignment,
adjudication and the separate extraction runtime are not delivered by this app.
Wrong-category counts do not establish which watchlist comparisons were blocked
or how many real matches were missed; that requires additional firm inputs.

Run instructions and deployment limits are in [README.md](README.md).
