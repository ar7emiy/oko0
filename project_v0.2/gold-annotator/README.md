# Claim Note Annotator

A small web app that SMEs use to build the answer key (gold data) for the firm's entity extraction. It then grades the firm's output against that key, as described in [../EVALUATION.md](../EVALUATION.md).

It uses only the Python standard library: no installs, no internet, and no build step. The page is plain HTML, CSS and JavaScript served by the app itself.

## Run it

Python 3.10 or newer.

```powershell
python run.py --notes "C:\path\to\notes" --firm "C:\path\to\firm-export.csv"
```

Your browser opens at `http://localhost:8765/`. On first use the app asks for your name; every record is saved under it. A practice claim is always included, and it never counts toward the real answer key.

| Option | Meaning |
|---|---|
| `--notes` | Folder of claim notes. Subfolders are searched too. |
| `--firm` | The firm's export CSV. Repeat it for several files. |
| `--db` | Where annotations are saved. Default: `annotations.sqlite3` next to `run.py`. |
| `--port` | Default 8765. |
| `--part-size` | Characters per part when a long note is sent to Copilot. Default 12000. |
| `--host` | Default `127.0.0.1`, which means this computer only. See [Sharing](#sharing). |
| `--no-browser` | Don't open a browser. |

## Notes stay where they are

- Name each note `CLAIM_NOTE.txt`, for example `C201_N04.txt`. The claim is everything before the last underscore.
- Notes are read from disk each time they are opened. They are never copied into the database. The app stores only each note's path, a fingerprint (SHA-256), and the character positions of what the SME marked.
- If a note file changes after work on it has started, the app stops saving to it and says why. Positions in a changed note can't be trusted.
- Positions are Unicode characters, counted from 0, with the end excluded. The file is read as UTF-8 and line breaks are kept as they are.

## The firm's export

One row per person or company the firm's tool reported. The app needs at least `claim_number` and `entity_name`. Every other column it uses is listed in `annotator/firm.py` (`COLUMNS`), and missing columns are treated as empty. The firm's rows stay hidden until the SME finishes a claim, so the answer key is built blind.

## The SME workflow

1. **Record.** Select words in the note and pick what they are: a person or company, another mention of one, a detail, a description, an action or link, or something unclear. Number keys 1 to 6 also work.
2. **AI drafts (optional).** Click **Get AI drafts**, copy the message, paste it into Copilot, then paste Copilot's reply back into the app. Each draft is highlighted in the note, and the SME accepts, fixes or dismisses it. Nothing from the AI is saved until the SME accepts it. The app works fully without AI.
3. **Complete.** Mark each note complete once it has been read in full.
4. **Compare.** When every note on a claim is complete, finish the claim. The firm's rows then appear. For each row the SME says who it is, whether the firm's category is right, and, for watchlist flags, whether the watchlist entry is the same person or company and why.
5. **Scores and export.** **Scores** shows every EVALUATION.md fraction worked out ("7 ÷ 10 = 70%"). **Export** downloads a zip of CSV files for data scientists. Its `README.txt` explains every file and column.

Press **?** at any time for the guide or the 2-minute tour.

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
python -m unittest discover -s tests     # 55 tests: parsing, quote finding, workflow, HTTP, sample replies
node tests/e2e/ui_flow.mjs               # 27 steps in headless Edge or Chrome, with screenshots
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
| `annotator/practice/` | The practice note and its firm rows. |
| `static/` | The page. |
