# Workbench delivery status

Verified 2026-09-10 (America/Chicago).

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
