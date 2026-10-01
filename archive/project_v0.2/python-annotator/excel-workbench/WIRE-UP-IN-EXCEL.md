# Set up the annotation workbench

Use Windows desktop Excel with macros permitted by your organisation. No Node, Python, server, add-in, API key or Copilot is required for manual review. Copilot drafting is optional and uses the SME's existing Microsoft 365 environment.

## Install into the new template

1. Keep your existing annotation workbook unchanged. Open **Entity-Gold-Review-Macro-Free.xlsx**, then Save As **Entity-Gold-Review.xlsm** (Excel Macro-Enabled Workbook).
2. Press **Alt+F11**. In this new workbook's VBA project, choose **File > Import File** for all eight `.bas` files: `WorkbenchStore`, `WorkbenchNotes`, `ReviewWorkflow`, `WorkbenchQueue`, `WorkbenchSetup`, `WorkbenchWatchlist`, `WorkbenchTests`, and `WorkbenchLegacy` (if supplied). Do not import older copies of ReviewWorkflow alongside these modules. There are no additional VBA references to enable.
3. Double-click **ThisWorkbook** under Microsoft Excel Objects. Paste the contents of **ThisWorkbook.txt** into that code window. This code belongs in the workbook object, not a standard module.
4. Choose **Debug > Compile VBAProject**. Return to Excel with **Alt+Q**, press **Alt+F8**, select **SetupWorkbench**, and click **Run**. Setup creates and assigns every button automatically. Save.
5. On a disposable test copy, run **RunCoreSelfTests**, then follow **QA-ACCEPTANCE.md**. Compilation and tests need the client's licensed Excel; they were not executed by the file generator.

The supplied `.xlsx` is macro-free and has no clickable workflow until wired. The new table layout is incompatible with replacing only the module in an old workbook. Use the new template. Setup is repeat-safe and can recreate buttons after a file rename.

## Load notes

On **Notes**, enter the claim number, note ID and positive reading-order number. Copy the **whole note** from Notepad with Ctrl+A, Ctrl+C, then click **Paste whole note** in Excel. This button reads Unicode text directly from the clipboard and stores it in parts of at most 8,000 UTF-16 units. It does not pass the note through one Excel cell. Read the capture confirmation, including its first and last text.

Alternatively, click **Import TXT files** and select multiple UTF-8 files named `CLAIM_NOTE.txt`. The last underscore separates claim from note ID. Selection order becomes provisional reading order; confirm or edit `note_order` in **Note Register** before reviewing. The existing 60-note fictional packet is at `../sample-data/stress-packet/notes` relative to this folder.

**Select note** opens Note Register. Select a stored row and click **Open selected note**. Review Desk displays a page of the source text. Previous/Next text page reaches the entire note; **Locate evidence** moves to the selected quote and colors/bolds its matching occurrence. **Notes** also shows the current text page.

Do not manually edit Note Parts. Re-pasting changed text creates a new source version, preserving the old one. Historical annotations remain traceable through Entries.source_id; the old version is marked superseded. Review the new version explicitly.

## Manual entry — no AI needed

1. Enter your reviewer name on Review Desk. Click **New manual entry**.
2. Choose **Entry kind**. Paste exact source wording into **Exact source quote**. Select occurrence 1, 2, etc. when those exact words repeat; **Locate evidence** checks the choice.
3. For a new entity, fill display name and optional open entity type. For a reference, field, context or statement, choose an accepted entity using **Choose entity**. This fills the primary reference; copy a second accepted reference into **Second entity** when a statement needs it.
4. Fill only the applicable details: reference form; field kind and stated value; optional context/statement label; or a reason for uncertainty. Entity type and context labels remain open, not limited to the client's category buckets.
5. Click **Attest & Save**, read the declaration and confirm. A successful durable save reports the entry revision. Click New manual entry or Load next AI draft to continue. Saving does not automatically skip past the accepted record.

**Save draft** preserves unfinished work without attestation. **Resume saved draft** lists drafts for the current note. **Previous entry / Next reviewed entry** navigate the latest accepted revisions in source order within the current note. Edits to an accepted entry require a fresh attestation. **Delete entry** dismisses an AI proposal or retires an accepted record; it blocks deleting an entity with accepted dependents. Reassign dependents through their forms first.

Dirty navigation asks Yes = save draft, No = discard edits, Cancel = remain. The saved draft is separate from the last accepted version. The workbench must save successfully before reporting acceptance; keep the working file writable.

## Optional Copilot drafts

1. Open the current note in Review Desk. On **AI Instructions**, read/copy the invocation at the end of the prompt into the Copilot pane. It identifies Note Register and Note Parts as the source.
2. Ask Copilot to fill **AI Queue** and **AI Analysis Input** only. If direct table insertion is unavailable in the tenant, paste its literal tabular result into the existing AI Queue columns. Do not paste JSON or formulas. Confirm claim/note/version and processed parts yourself.
3. When Copilot is finished, click **Save queue snapshot** on AI Analysis Input. Stop Copilot editing during this operation. The snapshot preserves draft values and brief source-based explanations.
4. **Load next AI draft** populates the same manual form in source order. Check, correct and attest, or Delete entry to dismiss it. Missing evidence/unknown entity keys require correction before acceptance. AI entity keys are resolved to accepted references only after the entity is saved.
5. Read passages without AI proposals and add missing entries manually. When all drafts are resolved, **Complete note** records a separate whole-note completeness declaration.

Analysis is kept only for the five most recently pasted distinct claim/note identities. Re-pasting an unchanged note refreshes recency. Older analysis expires, but source notes, pending candidates, accepted entries and their provenance remain. Do not request private chain-of-thought; the log contains the AI's draft outputs and short evidence explanations.

AI-assisted annotations are labelled as such through their queue provenance. For independent manual Gold, use a separate working copy without AI/client outputs. Hidden sheets alone do not make a workbook blind to Copilot.

## Watchlist review

After completing a note, use **Watchlist review**. Import the supplied `.csv` or `.xlsx` client export with its original 26 headers. IDs/TINs/ZIPs should already be text in an Excel export; numeric values that Excel rounded before export cannot be recovered. CSV import preserves literal text and multiline quoted fields.

Imports append with unique batch/row IDs. Do not import the same export repeatedly. **Load next pair** shows flagged records citing the exact current note ID, including all provided system and watchlist metadata. Base the same/different/insufficient-evidence decision on the note and metadata together. Provide a source-based reason, then Save decision. The >90 supplied subset does not establish whole-system recall or performance below the threshold.

Review Desk remains available for source context. A later source annotation change reopens note completeness and marks its watchlist reviews for recheck. Claim-only or compound note-ID fields require explicit mapping and are not silently assigned.

## Recovery and limits

Each write creates a pre-write recovery copy under the Windows TEMP folder named after the working workbook with `.recovery.xlsm` appended. This file contains the same sensitive data as the workbook. A failed write restores in-memory tables/form where possible and does not advance. If Excel itself crashes or a cloud save fails ambiguously, preserve both files and reopen the recovery copy if necessary. Changes since the last successful save are not guaranteed after a process crash.

Use one SME writer per workbook. Copilot should finish staging before VBA begins accepting records. AutoSave/cloud behavior and clipboard permissions must be exercised in the actual tenant. Optional AI availability must never prevent manual annotation.

This release keeps the familiar output tabs; **Entries** additionally records source version, revision, reviewer and AI/manual origin. Output tables are projections: do not edit them directly.

## Preserve work from the older workbook

Run **ImportLegacyWorkbook** from Alt+F8. Select the previous workbook. Its annotation cells are copied as literal values into **Legacy Archive**, with original sheet/row/field and `unverified_legacy` status. The original file is opened read-only with macros disabled and remains untouched. This is a preservation import, not an automatic conversion to accepted Gold: old offsets and attestations may not exist. Load the relevant source notes, use the archived values as reference and review each entry through the form. Keep the original file as the authoritative historical copy.
