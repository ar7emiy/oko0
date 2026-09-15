# Excel annotation workbench

Assisted-review annotation workbench for Excel: a macro-free `.xlsx` template,
the VBA that drives it, an offline HTML tutorial, and portable verification
that runs without Excel.

This directory continues the work in `../excel-macro/`, which was left
mid-verification when the session building it stopped. The difference is that
everything here can be rebuilt and re-checked on any machine with Python and
Node — no Codex runtime, no Excel license, no network.

## Rebuild and verify

```sh
python build_macro_free_interface.py   # regenerate Entity-Gold-Review-Macro-Free.xlsx
python verify_delivery.py              # 302 portable structure/contract checks
node   test_tutorial.mjs               # tutorial behavior in a simulated DOM
python preview_workbook.py             # workbook-preview.html, layout review without Excel
```

`workbench-schema.json` is the single source of truth for backend sheets, table
names and column names. The builder reads it, the VBA reads the same names at
runtime, and `verify_delivery.py` checks that the delivered workbook and every
`.bas` module still agree with it. Change a column there and rebuild; never edit
the header row in the workbook by hand.

openpyxl is imported from the copy vendored at
`../../offline-python-annotator/vendor/` when it is not installed system-wide,
so no `pip install` step is required.

## What each file is

| File | Role |
|---|---|
| `workbench-schema.json` | Backend sheet/table/column contract. Source of truth. |
| `build_macro_free_interface.py` | Builds the delivered `.xlsx` from the schema. |
| `*.bas`, `ThisWorkbook.txt` | VBA modules. Import into an `.xlsm`; see `WIRE-UP-IN-EXCEL.md`. |
| `verify_delivery.py` | Portable checks over workbook XML and VBA source. |
| `test_tutorial.mjs` | Runs the tutorial's own JS against a stub DOM. |
| `preview_workbook.py` | Approximate HTML render of the built workbook. |
| `COPILOT-PROMPT.md` | Prompt text embedded into the AI Instructions sheet. |
| `QA-ACCEPTANCE.md` | The Windows Excel acceptance run. Still outstanding. |
| `build_macro_free_interface.mjs`, `verify_macro_free_interface.mjs` | Superseded originals, kept for provenance. They need the Codex-only `@oai/artifact-tool` and will not run here. |

## What is verified, and what is not

Verified here, mechanically:

- The workbook exports every backend page, with table names and columns exactly
  matching the schema, no merged cells anywhere, no formula error cells, and no
  `vbaProject` part.
- Every VBA module declares `Option Explicit`, has balanced procedures, assigns
  only to declared names, wires only procedures that exist, performs no merge
  mutations, and references only column names the schema defines.
- The tutorial's own event handlers, evidence highlighting, ten guided saves,
  revision, rejection of unlocatable evidence, manual entry and completeness
  guidance behave correctly in a simulated DOM.
- Reference implementations of the UTF-16 note splitting and evidence-offset
  rules round-trip at the 32,766 / 32,767 / 32,768 / 100,000 unit boundaries,
  across an emoji at a split point, CRLF and combining accents.

**Not verified, and not claimable from this machine:** no VBA has been executed,
no workbook has been opened in Excel, and no Copilot tenant has been exercised.
`preview_workbook.py` approximates layout; it is not an Excel render. The
checks confirm that the delivered artifacts are internally consistent, not that
the workbench behaves correctly at runtime. `QA-ACCEPTANCE.md` on licensed
Windows desktop Excel remains the gate before this goes to an SME.
