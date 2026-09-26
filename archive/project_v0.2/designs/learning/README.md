# Excel annotation tutorial

Open `annotation-training.html` in a browser. It is a visual, read-only walkthrough. It highlights the complete fictional note text and traces each decision to the row and fields the SME fills in Excel. It never asks the SME to download, upload, create, or save data in the browser.

For an actual assignment, the coordinator gives the SME all supplied UTF-8 note files for the assigned claim and one workbook. The SME opens the files locally, follows the tutorial, completes the workbook, saves that workbook, and returns it through the agreed channel.

- `entity-evaluation-batch-template.xlsx`: one joined workbook for the claim batch. It contains the note inventory, blind gold tables, unaltered client entity output, silver review, unaltered watchlist pairs, field review, pair decisions, and a watchlist summary.

For blind gold work, the coordinator releases only the note inventory and gold sheets, then seals the completed gold work. The same claim's client-output and watchlist sheets are released only after that point. Silver can begin earlier on separate claims or with a different reviewer because it is assisted review, not blind gold.

The tutorial uses fictional notes and records. The pair dataset alone cannot verify source extraction because it has no note ID or source quotation. When notes and gold annotations exist for a pair, use them as source support; otherwise mark source verification `not_checked`.
