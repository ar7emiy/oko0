# Gold Dataset Workbench — Python desktop app

This is a Windows desktop application written in Python with Tkinter. It does not use Node, a browser, localhost, a web server, or network calls at runtime. The reviewer reads and annotates note text; the application creates the Gold dataset and Excel workbook behind the scenes.

## Build on a preparation computer

Open this folder in VS Code. In its PowerShell terminal, run:

1. `Set-ExecutionPolicy -Scope Process Bypass`
2. `./build.ps1`

If Python is absent, the script installs it and asks you to reopen PowerShell. Run `./build.ps1` one more time after reopening. The completed desktop application is `dist\OfflineEntityAnnotator.exe`.

Only the preparation computer needs Python and the build dependencies. The resulting executable runs without Python, Node, or a server. Client security still needs to permit the executable itself.

## Run the source app and verify it

To launch the source application and use the synthetic test packet, first activate the Python virtual environment, then run:

1. `Set-ExecutionPolicy -Scope Process Bypass`
2. `./run-sample.ps1`

To run the non-visual regression check before opening the app, use:

`python gold_workbench.py --self-test`

In the application, click **Load notes**, then select both `.txt` files in `sample-data`. Click **Load client output** and choose `sample-data/client-export.csv` only if you want to test the post-seal proposal panel.

## Review workflow

1. Load the complete `.txt` note packet. Use names ending in the note ID, such as `C104_N02.txt`.
2. Read a note. Select exact source wording. The note itself is locked, so source text cannot accidentally be changed.
3. Use **New entity**, **Link reference**, **Record field**, **Record context**, **Record statement**, or **Mark uncertain**. The selected span remains active while you click a button.
4. Mark the note read only after you have reviewed the complete note. The progress line tells you how many notes, entities, mentions, and source-supported fields have been recorded.
5. Use **Undo last change** for a mistake. Each change is saved automatically as `.gold-workbench-session.json` beside the note packet. Use **Restore saved work** to resume it.
6. Seal a claim only when every note is marked read. Client proposals remain hidden until then, preserving blind Gold creation.
7. After sealing, a reviewed note with a client record where `Entity_Watchlist_flag = 1` and the note ID is cited receives an additional watchlist-review prompt. Compare the system entity and watchlist candidate against the note that remains visible, record a reasoned decision, and continue.
8. Export the review workbook at any checkpoint. Its sheet names and columns match the Excel Plan B template.

## Excel workbench and VBA wiring

The `excel-macro` folder contains a reviewer-facing Excel interface that matches the Python workbench layout without requiring a server or Node on the client machine.

- `Entity-Gold-Review-Macro-Free.xlsx` is the visual Excel workbench. It is safe to open and review without macros.
- `ReviewWorkflow.bas` is the VBA module that creates entity, mention, field, context, statement, uncertainty, and watchlist-review rows.
- `WIRE-UP-IN-EXCEL.md` gives the exact steps to convert a copy of the workbook to `.xlsm`, import the module, and attach each Excel button.
- `EXCEL-ANNOTATION-WORKBENCH-TUTORIAL.html` is the interactive, step-by-step reviewer tutorial for the Excel workbench.

The Excel design has no mandatory category or subcategory list. **Record context** stores the note’s exact characterization of an entity, for example `orthopedic surgeon`, with an optional open label. **Record statement** stores the exact action or relationship wording, a primary entity, and an optional second entity.

## Try the synthetic packet

The `sample-data` folder contains a client export and two complete fictional notes. It includes direct evidence for every Harbor Legal field and a deliberately conflicting Maya Chen watchlist TIN. It is a control test, not a representative corpus.

For a usability and scale test, load all 60 fictional notes in `sample-data\stress-packet\notes`. The packet spans six claims and includes names, shortened forms, pronouns, organization descriptions, contact fields, no-entity notes, and intentionally ambiguous references. Its `client-export.csv` follows the supplied client schema.
