# Claim Note Annotator

A small web app that SMEs use to build the answer key (gold data) for the firm's entity extraction. It then grades the firm's output against that key, as described in [../EVALUATION.md](../EVALUATION.md).

It uses only the Python standard library: no installs, no internet, and no build step. The page is plain HTML, CSS and JavaScript served by the app itself.

## Run it

Python 3.10 or newer.

```powershell
python run.py --notes "C:\path\to\notes" --firm "C:\path\to\firm-export.csv"
```

Your browser opens at `http://localhost:8765/`. On first use the app asks for your name; every record is saved under it. Two fictional practice claims are always included. Practice is excluded from scores and exports unless explicitly included. The second practice claim is independent so completing the first does not prevent another exercise.

| Option | Meaning |
|---|---|
| `--notes` | Folder of claim notes. Subfolders are searched too. |
| `--firm` | The firm's CSV or XLSX export. Repeat it for several files. |
| `--db` | Where annotations are saved. Default: `annotations.sqlite3` next to `run.py`. |
| `--port` | Default 8765. |
| `--part-size` | Characters per part when a long note is sent to Copilot. Default 12000. |
| `--taxonomy` | Optional study taxonomy JSON. Default: the versioned starter definitions in `taxonomy.json`. |
| `--host` | Default `127.0.0.1`, which means this computer only. See [Sharing](#sharing). |
| `--no-browser` | Don't open a browser. |

## Notes stay where they are

- Name each note `CLAIM_NOTE.txt`, for example `C201_N04.txt`. The claim is everything before the last underscore.
- Client filenames such as `123456-123456-12-12_1234567890.txt` work directly. The same note ID may occur under several claim prefixes; annotations and entities remain separate for each claim. All supplied note files enter the packet, even if the firm never cites them.
- Notes are read from disk each time they are opened. They are never copied into the database. The app stores only each note's path, a fingerprint (SHA-256), and the character positions of what the SME marked.
- If a note file changes after work on it has started, the app stops saving to it and says why. Positions in a changed note can't be trusted.
- Positions are Unicode characters, counted from 0, with the end excluded. The file is read as UTF-8 and line breaks are kept as they are.

## The firm's export

One row per person or company the firm's tool reported. The app needs at least `claim_number` and `entity_name`. Every other column it uses is listed in `annotator/firm.py` (`COLUMNS`), and missing columns are treated as empty. The firm's rows stay hidden until the SME finishes a claim, so the answer key is built blind.

CSV and XLSX are supported without additional packages. XLSX sheets with matching
headers are imported in workbook order; each sheet's first nonblank row must be
its header. Unsupported sheets and ambiguous headers are reported. Formula cells
need saved calculated values; the app does not run Excel calculations. Store
identifiers as text where possible; simple all-zero Excel formats are also read
with their leading zeros. The importer cannot reconstruct digits already lost in Excel.

The client headers are accepted without renaming: matching is case-insensitive,
with aliases for `entity_category`, `entity_subcategory`, `entity_zip`, `entity_NER`,
`GenAI_Note_ID`, and `GenAI_entityNameCleaned`. `RecordType` (or the supplied header
with its parenthesized values) is retained; rows are not merged by cleaned name.
Missing `Watchlist_City` is treated as unknown and reported as an optional column.

Both Exact and GenAI note-ID cells may contain comma-separated IDs. Citation
lookup trims tokens, removes only an all-zero decimal suffix (`1234567890.0`
becomes `1234567890`) and preserves leading zeros. Original citation values remain
in the imported data and exports. Each link resolves only inside its row's claim;
missing files appear as "not supplied for this claim" during comparison.

For the client packet, from this app folder (adjust the two paths as needed):

```powershell
.\.venv\Scripts\python.exe run.py --notes "C:\path\to\oko_gt_notes_data" --firm "C:\path\to\client_entity_data.xlsx"
```

An XLSX workbook is recognized by its contents, so an accidental `.xslx` filename
also works. Existing installations must update the app code before using Excel.

## The SME workflow

1. **Record.** Select words in the note and pick what they are: a person or company, another mention of one, a detail, a description, an action or link, or something unclear. Number keys 1 to 6 also work.
2. **AI drafts (optional).** Click **Get AI drafts**, copy the message, paste it into Copilot, then paste Copilot's reply back into the app. Each draft is highlighted in the note, and the SME accepts, fixes or dismisses it. Nothing from the AI is saved until the SME accepts it. The app works fully without AI.
3. **Complete.** Mark each note complete once it has been read in full.
4. **Review claim evidence.** When all notes are complete, open the claim review. Select an entity to see its mentions, descriptions, actions and details grouped by original note. Click any quote to inspect the full source with that exact passage highlighted. Use **Open note to correct annotation** to correct ownership, then **Return to claim review**. Unresolved references have their own list.
5. **Record categories.** For each entity, assign a broad claim role or choose insufficient/conflicting evidence. Mark the records that support, conflict with, or repeat evidence for that conclusion. Give a brief rationale; subcategory is optional and must appear in selected evidence. Save each entity review. The entity list stays beside the evidence; Previous/Next and Jump to category decision reduce scrolling. Unsaved inputs survive navigation within the page, but must be saved before closing it.
6. **Freeze and compare.** Confirm the claim review before the firm's rows appear. This freezes the entities, exact record revisions, category decisions, source fingerprints and taxonomy. Pair each firm row to an entity and review watchlist flags. Category agreement is calculated from the frozen category; it is no longer a judgment made while looking at the firm's output.
7. **Finish comparison.** Answer every firm row, including watchlist decisions, note support and reasons, then click **Finish comparison**. The page confirms completion. Changing an answer reopens this stage; scores remain provisional until all scored claims have completed comparisons.
8. **Scores and export.** **Scores** shows fractions such as "7 ÷ 10 = 70%". **Export results** or **Export** offers three consolidated CSVs: `entity_comparison.csv`, `evidence.csv`, and `kpi_summary.csv`. Choose the detailed format for individual audit tables and frozen checkpoints. Tick **Include practice data (fictional)** to export your practice work; otherwise practice-only work produces empty answer-key tables. Exports include the current reviewer's work, and firm rows remain hidden until that reviewer unlocks the claim. See [KPI-DATA-GUIDE.md](KPI-DATA-GUIDE.md) for input datasets, formulas, denominators and table joins.

Use **Undo** or **Ctrl+Z** (**Cmd+Z** on Mac) to reverse saved annotation/entity changes and AI draft acceptance or dismissal, one action at a time. Inside a text field, the shortcut retains normal text undo. Saved undo history survives a restart; upgrading an older database can recover only its last reconstructible action. Undo does not reverse category/comparison decisions or replace a frozen answer key. Correcting annotation work reopens its note. There is no redo yet.

After updating the app, stop the server with **Ctrl+C**, run the same startup command again, and refresh the browser. Keep the same database and reviewer name to continue saved work.

Press **?** at any time for the guide or the 2-minute tour.

## Category definitions and review versions

The included taxonomy is an explicit starter policy, not a claim that these are the firm's approved definitions. It describes **roles in the supplied claim**, not general occupations. A coordinator can supply a JSON file with `version`, `scope`, and `categories` (each with `name` and `definition`) using `--taxonomy`. Definitions are independent of imported firm rows. Confirm the category meanings and the handling of multiple roles before the study; retain an unresolved outcome when the evidence does not settle a single category.

Changing the taxonomy or an entity's evidence makes its saved review stale. Review and save again before freezing; earlier decisions remain in history. Supporting and conflicting links refer to exact record revisions. Mark copied material as repeated: several notes repeating one statement do not establish independent corroboration. No automated category inference or external-source lookup is performed.

After freezing, later annotation corrections remain available but do not change the evaluated answer key. Restore the original source files if their fingerprints change; the app cannot reconstruct a changed full note from annotation quotes. The immutable checkpoint contains annotations and source hashes, not copies of the complete notes.

Existing databases gain the review tables automatically. Claims already sealed in the older workflow stay usable for comparison, but cannot acquire independent category labels retrospectively. Their prior category judgments remain historical and are excluded from the new category accuracy measure. A reviewer who has seen the firm's output cannot become blind again by reopening a note or changing their display name; names are self-reported, not authentication.

## Setting up Copilot

The instructions are in [prompts/copilot-agent-instructions.md](prompts/copilot-agent-instructions.md). They are 6,030 characters, which fits Copilot Studio's 8,000-character limit for agent instructions.

- **With a Copilot agent (recommended).** Create an agent in Copilot Studio or the M365 agent builder, paste the file's contents as its instructions, and turn off web search and other knowledge sources. SMEs then paste only the message the app builds.
- **With plain Copilot chat.** Tick **Include the full instructions** in the app. The copied message then carries the instructions with it.

Copilot replies in JSON Lines inside one code block. The app's reader is tolerant. It ignores chat text around the block and fixes common slips such as curly quotes, trailing commas and a missing `before`. It points out any line it can't place, and says what to do about it. If Copilot runs out of room, the reader says so, and the SME types "continue".

**Check the limits in your tenant.** How much text Copilot accepts and returns varies by licence and surface. Before SMEs rely on it:

1. Paste the app's message for your longest note into Copilot and save the reply to a file.
2. Run:

   ```powershell
   python check_answer.py "C:\path\to\C201_N04.txt" reply.txt --known 1 2
   ```

   `--known` lists the E numbers already recorded on the claim. The check prints every draft as ready, needing attention or duplicate, with the reason.
3. If replies get cut off, lower `--part-size`. The app then offers the note in parts.

The sample replies in `tests/ai_samples/` were written to test the reader, including deliberately sloppy ones. They were not produced by a real M365 Copilot run, so repeat the check above with real replies.

## Sharing

The app has no logins. The name an SME enters is trusted as given. Keep the default `--host 127.0.0.1` so it runs for one person on one computer. To share it on a network, put it behind the firm's own sign-in first. Notes never leave the computer or share they are read from, except for what an SME chooses to paste into the firm's Copilot.

## Tests

The completed handoff and QA evidence are recorded in [STATE.md](STATE.md).

```powershell
python -m unittest discover -s tests     # parsing, evidence, workflow, frozen review, HTTP, sample replies
node tests/e2e/ui_flow.mjs               # 35 steps in headless Edge or Chrome, with screenshots
```

The browser run needs Node 22 or newer and Microsoft Edge or Google Chrome. It uses the stress packet in `../python-annotator/sample-data/`, fails on any JavaScript error, stray text such as "undefined", or a control covered by something else, and writes screenshots to `tests/e2e/screens/`.

## Layout

| Path | What it does |
|---|---|
| `run.py` | Starts the server. |
| `check_answer.py` | Checks a saved Copilot reply against its note. |
| `annotator/server.py` | HTTP routes and the workflow rules. |
| `annotator/store.py` | SQLite storage. Records are append-only: an edit adds a revision, and a delete adds a retired revision. |
| `annotator/ai_import.py`, `spans.py` | Reading Copilot replies and finding each quote in the note. |
| `annotator/copilot.py` | Builds the message SMEs paste into Copilot. |
| `annotator/scoring.py`, `export.py` | The EVALUATION.md scores and the data-scientist export. |
| `annotator/review.py`, `taxonomy.json` | Claim dossiers, evidence-linked category decisions and immutable review checkpoints. |
| `annotator/practice/` | Two fictional practice notes and their firm rows. |
| `static/` | The page. |
