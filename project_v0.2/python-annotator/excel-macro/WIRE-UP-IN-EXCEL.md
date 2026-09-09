# Wire the Excel workbench to VBA

Use a licensed desktop copy of Microsoft Excel. The workbook and VBA module are separate so the macro-free interface can be reviewed safely before macros are added.

## Files to use

- `Entity-Gold-Review-Macro-Free.xlsx` is the reviewer-facing workbook shell.
- `ReviewWorkflow.bas` is the complete VBA workflow.
- `EXCEL-ANNOTATION-WORKBENCH-TUTORIAL.html` teaches the reviewer-facing flow.

## Create the macro-enabled workbook

1. Make a copy of `Entity-Gold-Review-Macro-Free.xlsx` and open that copy in desktop Excel.
2. Save it as `Entity-Gold-Review.xlsm` using **Excel Macro-Enabled Workbook**.
3. Press `Alt+F11` to open the Visual Basic Editor.
4. In the Project pane, right-click the workbook, choose **Import File**, and select `ReviewWorkflow.bas`.
5. Return to Excel with `Alt+Q` and save.

The module expects the visible sheet to be named `Review Desk` and the supporting sheets to retain their supplied names. Do not rename them.

## Turn the action cells into buttons

The colored cells in column H are intentionally visual placeholders in the macro-free file. In the `.xlsm` copy, put a rounded rectangle over each corresponding cell group, type the action label, right-click it, choose **Assign Macro**, and select the listed procedure.

| Review Desk label | VBA procedure |
|---|---|
| New entity | `NewEntity` |
| Link reference | `LinkReference` |
| Record field | `RecordField` |
| Record context | `RecordContext` |
| Record statement | `RecordStatement` |
| Mark uncertain | `MarkUncertain` |
| Refresh entity list | `RefreshDesk` |
| Seal claim | `SealClaim` |
| Import client output | `ImportClientOutput` |
| Load note matches | `LoadWatchlistMatches` |
| Save decision | `SaveWatchlistDecision` |

Keep the macro-free colors when formatting each button: yellow for a new entity, mint for reference, blue for a field, purple for context, peach for a statement, and orange for uncertainty.

## Hide the backend only after testing

The macro writes its records to these sheets: `Entities`, `Mentions`, `Fields`, `Context`, `Statements`, `Uncertain`, `Watchlist Review`, `Watchlist Candidates`, `Sealed Claims`, and `Raw Client Output`.

Run one complete example from the tutorial first. Confirm that each button adds one row to the expected sheet. Then hide the backend sheets with **Right-click sheet tab → Hide**. Keep `Review Desk` visible for the SME.

## What the reviewer does

The reviewer keeps the note open in Notepad next to Excel. They paste exact source wording into the source box, specify only the entity reference or the small amount of context needed by the action, and press the corresponding button. The VBA module creates the IDs and output rows.

`Record context` does not require a category or subcategory. It stores the note’s exact wording, for example `orthopedic surgeon`, linked to the selected entity. `Record statement` stores the exact action or relationship wording, a primary entity, and an optional second entity.

## Client-data and watchlist review

Use **Import client output** only after Gold annotation is complete for a claim. After sealing the claim, enter the current claim and note, choose **Load note matches**, and review only the client watchlist matches whose exact-search or GenAI note ID cites that note. The decision is based on the note and Gold evidence, not the similarity score alone.
