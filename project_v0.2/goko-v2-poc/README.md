# GOKO v2 — architecture POC

A runnable trace of the v2 pipeline: extraction in three lanes, identity as scored links
with a read-time merged view, a watchlist check against the federal health-care exclusion
list, category assignment, cross-claim reading, and a search app over the result.
`architecture-trace.html` is the design; `goko_v2_poc.ipynb` is the implementation.

```
goko_v2_poc.ipynb            the pipeline, one cell per boundary
architecture-trace.html      the design it implements
goko/projection.py           read-time merged view (lenses, weakest link); notebook and app share it
goko/watchlist.py            "Flagged for review" at a lens; notebook and app share it
goko/net.py                  IPv4-first resolution (see "Slow calls" below)
app/                         the search app: server.py, librarian.py, graph.py, static/ (app.js, card.js)
evaluate.py                  scores a court-corpus run against the clerk's party lists
notes/                       five fixture notes across four claims, three occurrences
fixtures/                    recorded LLM payloads for offline replay
corpus/courtlistener/        two real RICO dockets, seven filings, plus gold/ party lists
corpus/reference/            outside name-frequency tables (Census, SSA, NPPES) for rarity
corpus/registry/             OIG LEIE exclusion list as a compact table (the watchlist, cell 18c),
                             plus NPPES and LEIE lookups of the court defendants (evaluation only)
run_offline_check.py         runs every cell headless; non-zero exit if anything breaks
poc_output/                  written by the notebook (gitignored)
```

## Running it

```bash
pip install -r requirements.txt       # pandas 3, jellyfish, pypdf, ...
pip install --no-deps recordlinkage==0.16   # its pandas<3 pin is stale; see requirements.txt
python3 run_offline_check.py          # no key, no network, a few seconds
jupyter lab goko_v2_poc.ipynb         # same thing, interactively
python app/server.py --run poc_output # the search app over the last run, http://127.0.0.1:8765
python app/server.py --run poc_output --no-model   # never calls a model, whatever keys exist
```

Optional stages, each switchable in cell 1 without breaking anything downstream:
`CLEANER` (off by default: spans are positions in the source text as stored), `CHUNKING`
(on: long notes split on page and paragraph breaks, then sentences, with whole-sentence
overlap), `GLINER_ENABLED` (off: needs `pip install gliner`).

One toggle, `PROVIDER`, in cell 1:

| `PROVIDER` | Needs | Notes |
|---|---|---|
| `"offline"` *(default)* | nothing | Replays recorded extractions for the bundled notes. |
| `"gemini"` | an API key | Paste it into `GEMINI_API_KEY` in cell 1. No `settings.env`, no SDK — the adapter is raw HTTPS over `urllib`. Falls back to `$GEMINI_API_KEY` / `$GOOGLE_API_KEY`. |
| `"openai"` | an API key | api.openai.com directly (not Azure), raw HTTPS like the Gemini adapter. Key in `OPENAI_API_KEY` in cell 1 or the environment; model `OPENAI_MODEL`, default `gpt-5-nano`. Reasoning tokens get the same headroom as Gemini's thinking tokens; `reasoning_effort` is `low`. |
| `"azure"` | `settings.env` + `openai` | Cell 1 prints which keys it found, masked, and which variant names it accepts. |

Offline mode exists so the plumbing can be verified without a deployment, and it is never
selected silently — name a live provider with no key and cell 1 raises, naming the toggle.
Every artifact is stamped with the model that produced it.

For a real run, drop notes into `notes/` named `{claim_id}_{note_id}.txt`.

Gemini and Azure disagree on structured-output dialect. Rather than maintain two schemas,
`to_gemini_schema` (cell 2) translates: type unions become `nullable`,
`additionalProperties` is dropped (Gemini rejects it, OpenAI strict mode requires it), and
property order is pinned so responses stay diffable. `finishReason: "MAX_TOKENS"` is
normalised to `"length"` so the truncation check is provider-independent. Both translations
have self-tests in cell 23.

## Identity: links underneath, merged view on top

Nothing is ever physically merged. Every candidate pair of mentions, at any distance, gets
one **link** carrying a probability, a **basis** and possibly a **veto**. Entities are
computed when something reads them, at a **lens**:

| Lens | Admits |
|---|---|
| strict | identifier-backed links (see Identifiers below), p ≥ 0.90 |
| default | any basis, p ≥ 0.80 (what the dossier files use) |
| broad | any basis, p ≥ 0.10 |

Each merged entity lists the link that pulled in each member, and its confidence is its
**weakest link**. A union that would join a vetoed pair (two stated NPIs, M.D. against D.O.)
or grow a cluster past 40 mentions is refused and recorded.

The score is Fellegi-Sunter in form with fixed parameters. Each agreeing field adds
`log2(m/u)` bits. For names, `u` comes from outside tables, never from the corpus, so a
shared "Pierre" counts for far more than a shared "Smith". The prior odds depend on distance
(same note, same claim, same incident, same client, different client) and on role:
clinics and professionals recur across claims, private persons don't.

A rare exact name can score 0.99 and still be labelled `name_only`. The basis is never
upgraded by the score. Co-parties add weight only when they are linked on an identifier
(one-way, so name-only coincidences can't vouch for each other). Co-parties that match only
by name are displayed and never scored.

`recordlinkage` does the candidate generation and string comparisons. The markdown page
above cell 17 explains the configuration. Cell 18b holds EM weight learning, disabled, with
the criteria for turning it on.

Every link carries `fields`: for each compared field, the two values, the agreement level,
`m`, `u`, what `u` rests on (the surname's Census frequency, an organization word's NPPES
share, an identifier's assumed rate) and the bits it added. The rows sum to the link's bits.
The app's decision card is built from them, so nothing on screen is recomputed.

### Identifiers

| Type | Normalized | Counts as | Check |
|---|---|---|---|
| NPI | 10 digits | identifier, one per party (conflict vetoes) | Luhn (prefix 80840) |
| TIN, SSN, VIN, bar number | digits / uppercase | identifier, one per party | — |
| DEA number | `AB1234563` | identifier, one per party | DEA check digit |
| professional license (`state_license`) | `NY:212345`, or `212345` with no state | identifier | — |
| license plate | `NY:KLM4821`, or `KLM4821` | identifier | — |
| bank account | `021000021:4417229108` (routing:account), or the account alone | identifier | ABA routing checksum |
| email | lowercase | identifier | — |
| phone | `+1` and ten digits | identifier | — |
| address | lowercase words | weaker than an identifier | — |
| date of birth (`dob`) | ISO date | adds weight to a person's name (u = 1/(365×80)); a difference counts against, never vetoes; never an identifier on its own | real date, not in the future |

A plate, license or account number matches another when the numbers agree and the issuers
(state, routing number) agree or one is unstated. Policy and claim numbers are deliberately
not identifiers: they name a contract or a file, not a party. The pattern lane finds every
type above (cued where a bare number would be ambiguous: an uncued DEA-shaped string is kept
only if its check digit works). The app shows SSNs and bank accounts as their last four
digits: the page gets an opaque id and a masked label, and those digits are blanked in note
text, so the full value never reaches the browser.

## Flagged for review: the OIG exclusion list

`corpus/registry/leie_records.csv.gz` is the whole OIG List of Excluded Individuals/Entities
(84,001 records) reduced to what the linker compares: name parts or business name, NPI (blank
when all zeros; 11% have one), city, state, general category and specialty, exclusion type and
date, and a record id hashed from the record's own fields. `fetch_registry.py` builds it from
the gitignored raw download (`--leie-table` rebuilds without downloading). Street address,
ZIP and date of birth are left out.

Cell 18c links it with **the same machinery** as mention against mention. Each record is a
mention record (`source: "oig_leie"`, no claim); `recordlinkage` proposes pairs in two-frame
linking mode (surname NYSIIS, rarest and leading organization word, NPI), so two records are
never paired; the cell 18 scorer, rarity tables and vetoes decide. About 7,000 candidate pairs
are scored in ~4 s on the court corpus. What is new is declared:

- **Distance `watchlist`**, with a prior by the corpus party's role: 5e-7 for a professional
  or organization, 1e-7 for a private person. Semantics: the chance the party is on the list
  at all (~4% and ~1% for parties named in a fraud file), spread over its records.
- **A location field**, watchlist pairs only: the mention's own addresses against the record's
  city and state. Same state adds weight scaled by the state's population share, same city
  more; a different state counts against and never vetoes.
- **The record's NPI** is an identifier like any other: agreement makes a link
  identifier-backed; a different stated NPI vetoes.

An entity is **Flagged for review** at a lens when any of its mentions has a watchlist link
that lens admits. There is no second threshold, and the flag carries its basis: a name-only
flag says so. Links with p ≥ 0.001 go to `watchlist_links.json` with their field breakdown.

Decision card (AGENTS.md, change control):

| | |
|---|---|
| User need | See which parties may be excluded providers, and on what evidence. |
| New permitted decision | A read-time flag on an entity; nothing is merged, blocked or hidden. |
| Evidence kept | The watchlist link: p, basis, veto, per-field breakdown, the record's fields. |
| Unresolved outcome | Links below the lens stay visible ("possible match"), with their reason. |
| Dossier effect | `flagged_for_review` in the entity's flags, the admitted links in `watchlist`. |
| Disable / reverse | `WATCHLIST_ENABLED = False` in cell 18c, or delete the table: no link, no flag. |

**Court corpus, relinked.**

| Party | LEIE record | Link | Flagged at |
|---|---|---|---|
| Bradley Pierre (private person, NY filings) | BRADLEY PIERRE, employee, clinic; Lewisburg PA; 1128a3 (felony, health-care fraud), 2026-05-20; no NPI | p = 0.36, name only (surname ×7,300, first name ×780; no location on the mention) | broad only |
| Dr. Andrew J. Dowd (named in the American Transit complaint) | ANDREW J DOWD, physician, orthopedics; South Setauket NY; 1128a3, 2024-08-20; NPI on record | p = 0.96, name only (no NPI in the filing to compare) | default and broad |
| Nexray Medical Imaging | none on the list | — | never |

The complaint itself says Dr. Dowd "was convicted in December 2018 for mail fraud"; the flag
still rests on his name alone, and the card says so.

## The search app

`python app/server.py --run <run dir>` serves a read-only interface over one run. Every view
is computed by the server from the run's files, through the same projection and flag code
the notebook uses; nothing can be edited.

**Top bar.** The run (mentions, claims, notes, whether a librarian model is configured) and
the **lens**: Strict, Default or Broad. The lens is global. It decides what counts as one
party (which links merge) and who is flagged for review, in the list, the dossier and the
pinned dossier alike. Hover any lens for its rule.

**The list (left).** Every entity at the current lens. Parties **Flagged for review** come
first, strongest flag first, then everyone alphabetically. Each row shows the type (the
coloured dot), how many mentions and claims it spans, and a flag badge (`Flagged · weak`)
whose hover names the listed record and the link's basis. `possible match` marks a party with
an exclusion-list link that this lens does not admit. The filter box narrows the list by any
name the party goes by. It is a lookup only; no model is involved.

**Ask.** Opens the librarian's search bar over the list (Esc or × brings the list back).
Suggestions cover parties, identifiers, claims and notes; picking one opens it directly.
Enter lets the librarian decide: a query that clearly names something opens its dossier; a
question is answered from a retrieved subgraph, where every statement cites a party or a
source passage. Below the bar are suggested questions built from the open dossier ("Why is X
flagged for review?", "Who else shares <identifier>?", "Which claims mention X?") and your
recent searches (kept in this browser only).

**The trail (narrow column).** Every step you took, newest at the bottom, each with why it
was opened: "from the list", "co-party of Nexray", "mention of Bradley Pierre", "cited in …".
Click a step to go back; opening something new from there replaces the steps after it.

**The dossier (main pane).**
- *Header:* the name, type and claims, a **Flagged for review** badge if the lens flags it,
  and one sentence that says how the entity was formed: how many mentions across how many
  claims, what the merge rests on, and how strong its weakest link is. Click the weakest link
  to open its decision card. Below it, the **Role** line is the model's reading of what the
  party does in each claim ("medical · doctor"); it plays no part in identity, and
  `undetermined` is the model declining to guess.
- *Flagged for review:* each exclusion-list record a mention links to, with the link's
  strength and basis. Click a row for its decision card.
- *Identifiers, Mentions, Appears with, Actions:* each with its source passage. "joined via …"
  under a mention is the link that pulled it in; click it for the card. "Open in note" opens
  the passage in the note reader.
- *Candidates:* the closest mentions this lens kept apart, then the links that merged it.
  Each row shows the other party, name similarity, probability in words and number, basis,
  and any veto. Click any row for its decision card.
- **Pin** keeps the dossier in a pane beside the main one, to compare two parties. It follows
  the lens; links clicked in it open in the main pane.

**The decision card (drawer).** How one link was decided, in order: (1) the two mentions,
with their passages, or the exclusion-list record; (2) the starting odds in words ("1 in
10,000,000 — private person, different insurers"; hover for why); (3) one row per field: what
was compared, the agreement level, how common the value is ("about 1 in 7,800 people have
this surname"), and its effect as an odds multiplier (×7,300; bits on hover) with a bar;
identifier rows, conflicts, and the co-parties that match by name, shown and labelled as not
scored; (4) the result as odds and a probability (never a bare 1.00: "> 0.99") with a verbal
band; (5) what the link rests on, in words; (6) what each lens did with it, including a veto
or a refused union in plain words.

**The note reader.** A note in full, every extracted mention highlighted by type (person,
organization, vehicle; a red underline marks a flagged party). Click a mention for a drawer
with that party's dossier in brief and all its mentions; click one of those to jump to it in
this note, or to open the other note scrolled to it.

**Answers.** A short, collapsible log of the steps the server really took, streamed as they
happen: the routing decision, the parties matched, the one-hop expansion and its counts, the
facts assembled, the model call and how long it took (or that no model is configured), and
how many citations were checked and removed. "show what was sent" reveals the facts the
model received. Citations open their party or passage.

**Privacy.** SSNs and bank accounts appear as their last four digits everywhere, including
note text; the page never receives the full value. The model key is read from the
environment or `.env`, stays in the server process, and is never sent to the browser.
`--no-model` guarantees no model call at all.

**Cell 23 is the one to run before believing any other number.** It checks the invariants
this pipeline can otherwise violate while completing cleanly. Cell 24 lists the architecture
stages the POC does not implement, so a green summary cannot be read as a complete system.

## Court corpus results

Two RICO dockets from different insurers against one ring of providers: seven filings,
about 800k characters. Five of the docket parties appear on both dockets. Scored by
`evaluate.py` against the clerk's party lists (`corpus/courtlistener/gold/`), which the
pipeline never reads.

| | Gemini 3.1 Pro + GLiNER | Gemini 3.5 Flash |
|---|---|---|
| Extraction | 27 calls (5 of 7 notes split), 0 failures | 27 calls, 0 failures |
| Party recall, LLM | 16/17 | 16/17 |
| Party recall, GLiNER | 16/17 | not run |
| Cross-claim identities found (strict / default / broad) | 0 / 4 / 5 of 5 | 0 / 4 / 5 of 5 |
| Wrong cross-claim joins (default / broad) | 0 / 1 | 0 / 0 |
| Wall time | ~22 min (GLiNER ~9 on CPU) | ~8 min |

- **Recall.** Both lanes miss Leon Kucherovsky, who is on the second docket's list but not
  named in the selected filings. On these documents GLiNER added no party the LLM missed.
- **Strict finds nothing.** Court filings carry almost no shared identifiers, and every true
  cross-claim link is `name_only`.
- **Default misses Bradley Pierre (p = 0.36).** He is a private person matched on name
  alone. That is the private-person prior at work, as designed. He appears at broad, next to
  a display that 32 of his 65 co-parties also match by name (Pro run).
- **The Pro run's broad-lens error.** It joins Allstate Fire & Casualty with Allstate
  Property & Casualty through the bare "Allstate", at weakest link 0.55. FIRE is too common
  in NPPES to count as distinctive, so the sibling veto doesn't fire.
- **Cross-claim clusters outside the gold five are real too.** Medical Reimbursement
  Consultants, Allstate, and the attorney Cary Scott Goldinger all appear in both dockets'
  filings.

The first live run of this linker found every true identity but also joined Nexray with
Rutland and four Allstate siblings into one. Each wrong join traced to a concrete cause, now
fixed and covered by a self-test:

- **Sentence fragments used as names.** "Ninth Cause of Action against Nexray, Pierre, and
  Weiner" was treated as a name.
- **Sibling companies became aliases.** The model listed them as occurrences of one
  mention.
- **A generic short form chained siblings.** "Allstate" linked every sibling to every
  other.

### gpt-5-nano against the Gemini runs

Same corpus and pipeline. Extraction and category assignment both run on nano, with
`reasoning_effort` low and GLiNER off.

| | Gemini 3.1 Pro | Gemini 3.5 Flash | nano, effort low | nano, effort medium |
|---|---|---|---|---|
| Wall time (extraction / categories) | 22 min (6.3 / 6.8) | 7.8 min (3.4 / 4.3) | **3.2 min** (1.3 / 1.6) | 15.4 min (8.0 / 7.0) |
| Party recall | 16/17 | 16/17 | 16/17 | 15/17 |
| Cross-claim identities: default / broad | 4 / 5 | 4 / 5 | 4 / 5 | 4 / 5 |
| Wrong joins: default / broad | 0 / 1 | 0 / 0 | 0 / 0 | 0 / 0 |
| Entity mentions | 196 | 156 | 110 | 139 |
| **Actions** | 96 | 91 | **11** | 86 |
| Details found by the LLM | 14 | 18 | **2** (+6 pattern-only) | 8 (+5 pattern-only) |
| Quotes that could not be placed | 13 | 6 | 16 | 28 |

`OPENAI_REASONING_EFFORT` in cell 2 sets the effort.

Nano finds the parties about as well as Gemini, and on these filings party names alone drive
the identity results.

At low effort it extracts almost none of the relationships (who billed, referred, owned or
controlled whom) and almost none of the identifiers. Those actions and details are what
dossiers show and what graph-RAG answers are built from.

At medium effort nano recovers the actions (86 against Gemini's ~95). It is then slower than
Flash, misses one more party, and still finds fewer identifiers than either Gemini model.

Some of its quotes are paraphrases rather than copies (similarity 0.43–0.79 against the
source), and those are rejected rather than placed. That is the round-trip check doing its
job, but it costs spans.

The 3.1 Pro run's 28 category failures were HTTP 429s from the per-minute limit, before the
retry existed. They are not a model result.

## Slow calls: broken IPv6

On a machine whose IPv6 route is advertised but broken, Python's `urllib` tries every IPv6
address first, waiting out a full timeout on each, before it reaches IPv4. Browsers and
`curl` race the two address families and never notice.

This happened once during development, on a network with a misconfigured IPv6 route. It
added about 55 s to every connection: a one-word Gemini reply took 170 s. After the fix it
took 2.6 s, and the notebook's smoke test dropped from 172 s to 3 s.

`goko/net.py` orders IPv4 answers first and keeps IPv6 as the fallback. Cell 2 and the app
both call it.

Once calls were fast, the category step hit Gemini's per-minute quota. Both adapters now wait
out a 429 using the server's `retryDelay`. A per-day quota is different: Gemini 3.1 Pro
allows 250 requests a day on this key, and no retry can help once they're used, so the
adapters report it at once rather than waiting.

## First live run (Gemini 3.1 Pro)

The offline fixtures were written by hand, so they could only ever confirm the plumbing
behaves as its author expected. The first run against a real model found three bugs they
structurally could not:

| | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | 7 of 10 entities had no category | Gemini 3.x thinking tokens are charged against `maxOutputTokens`; the category call's 512-token budget was spent thinking before any answer was written | The adapter adds thinking headroom, so `max_tokens` means "room for the answer" on every provider. Thinking tokens are now reported in `usage`. |
| 2 | The summary reported those 7 as *"the model declining to guess"* | A failed call was recorded as `insufficient_evidence` | Failed calls are `CATEGORY_CALL_FAILED` and counted as a validity failure. A failed call is not an answer. |
| 3 | Surface forms like `by Dr. Monroe (NPI`, `Referred to Lakeshore PT for six` | `quote` did two jobs: a *locating* phrase padded for uniqueness, and the party's *name* for blocking and matching. The model padded it, as instructed. | Entity mentions now carry `name` alongside `quote`, mirroring `quote` / `raw_value` on details. The span narrows to the name inside the quote. |

Also: `gemini-2.5-pro` is still listed by the API but closed to new users, so the default is
now `gemini-3.1-pro-preview`. The smoke test caught it on cell 3.

After the fixes the live run is clean: 0 extraction failures, 0 category failures, 0
round-trip failures, 0 unresolved quotes, 28/28 self-tests. Four notes is a smoke test, not
a measurement.

**Where the model disagreed with the trace.** Not bugs, but concrete instances of open
design question 4 below:

- The trace says `Office at 4410 N Broadway` must stay `UNASSIGNED` — proximity is not
  ownership. Gemini assigned it to Dr. Monroe, labelled `basis: inferred`.
- The trace says the phone should be `inferred`, since ownership comes from the pronoun
  "He". Gemini called it `stated`.

The `basis` label is currently the only thing between an inference like the first one and a
cross-claim join key.

## What was wrong with the first version

Every item below was reproduced against a run before it was fixed.

### It could not extract anything

`EXTRACTION_SCHEMA` used `"minItems": 1`. Strict structured outputs reject that keyword, so
every extraction call returned a 400 — and the loop's `except Exception` turned each one
into an empty note. The run completed, reported `0` round-trip failures, `0` unresolved
quotes and `0` validation problems, and produced a dossier of nothing. A clean summary over
an empty corpus is the worst available failure.

Fixed three ways: the keyword is gone; `lint_strict_schema` checks both schemas at
definition time; and a failed extraction is now recorded as `extraction_error`, counted in
the summary, and declared a **partial run** rather than an empty note.

### The round-trip check could not fail

The check that "validates the entire chain" sliced the raw text at a span and compared it to
the *clean* text at the same span. Both sides derive from the span being tested, so it
passed for any span — including one pointing at a different sentence. Demonstrated: a span
of `[0, 10]` claiming to be the quote `"Dr. Monroe"` passed.

It now compares the raw slice against **the quote the model emitted**, which is what the
architecture trace describes and what catches a hallucinated quote. Spans that fail are
dropped rather than carried into a citation. The offset map itself is checked separately and
exhaustively in cell 7 — every index, not a sample.

### Two of the three quote-resolution paths returned wrong coordinates

- The normalized retry returned `normalized_text.index(...)` — an offset into a *different
  string*. Any note where whitespace collapsed before the match got a silently wrong span.
- The fuzzy retry returned the scanning window's start and the quote's length. Demonstrated:
  a quote resolved to `'he claimant attended … morning y'` — off by one at both ends.

Both now map back to real coordinates; the fuzzy path aligns to the matching block.
Neither could be caught before, because the round-trip check passed them.

### `must_not_link` vetoed nothing

Union-find filtered `high` edges against the blocked set, but a pair is never both `high`
and `must_not_link`, so the filter could never reject anything. Demonstrated: A–B high, B–C
high, A–C blocked → all three in one component.

Two changes. The constraint is now checked against the *components* a union would join, and
refusals are recorded on the dossier. And `must_not_link` is raised by evidence of a
different kind — a type mismatch, or two different values of an identifier a party can only
have one of — rather than by a low similarity score, which is just a restatement of "no
edge" and cannot veto a transitive merge.

### Scoring bands that no input could reach

- **Cross-claim.** `rarity = 1/n` over entities sharing a detail. Any pair that exists at
  all has `n ≥ 2`, so rarity ≤ 0.5, so `identity ≤ 0.7275` — and the `same` band starts at
  0.85. No pair in any corpus could ever be scored `same`. Rarity is now `2/n` capped at 1
  (unique-to-a-pair is 1.0), distance is an additive prior rather than a multiplier that can
  only scale identity down, and detail type carries weight.
- **Within-claim.** `0.45·name + 0.55·shared_detail` caps a pair with no shared identifier
  at 0.45, below the `mid` band at 0.60: two mentions of the identical distinctive name in
  different notes could never merge, or even be flagged. The two signals are now scored
  independently and capped.

Cell 23 proves each band is reachable in both scorers. That is not calibration — the weights
remain placeholders — but an unreachable band is a bug regardless of calibration.

### Quieter defects

| | |
|---|---|
| **Re-running the remap cell doubled every detail** | It appended to the previous run's list. Three runs, three copies of one NPI, nothing in the output saying so. It now rebuilds from the envelopes and folds identical `(type, value)` pairs into one detail with two pieces of evidence. |
| **Entity ids were unstable** | Numbering followed the union-find root, which depends on the order edges arrived. `E1` could mean a different party on the next run, making the "frozen, scoreable artifact" incomparable with itself. Numbering now follows each component's lowest member key. |
| **`off_taxonomy_value` was caught by its own `except`** | The `raise` sat inside the `try`, so a version-skew bug was downgraded to `insufficient_evidence` — exactly what the architecture trace says must never happen, because it turns a pipeline bug into an apparent recall problem. It is now collected and raised out of the loop. |
| **The model could not say "I don't know"** | Generation was constrained to the six scored categories while `insufficient_evidence` was treated as a possible answer. Every ambiguous party was forced into one of the six. The refusal is now in the schema enum and out of `CATEGORIES`. |
| **Reconciliation matched on value only** | `overlaps()` was defined and never called. A note stating one phone number twice reconciled one mention and emitted the other pattern find as a phantom "recall gap". Matching now requires an overlapping span, and each pattern find is consumed once. |
| **Organizations blocked on their last token** | `Lakeshore PT` keyed on `pt`, `Lakeshore Physical Therapy` on `therapy`; the pair was never proposed. Blocking keys are now built per entity type — surname for people, leading token for organizations — with a stopword list split the same way. |
| **The GLiNER lane was dead code** | It computed spans nothing read. Its finds now reconcile against entity mentions, and unmatched ones surface as `entity_candidates`. |
| **Phones and NPIs fought over the same digits** | A bare ten-digit run matched both patterns. The phone pattern now requires a separator; a bare ten-digit NPI is flagged `cue: false`, because "ten digits after the word NPI" and "ten loose digits" are not the same claim. |
| **Captured values carried the cue's span** | `bar_number 6224417` came with a span covering `ARDC 6224417`, so every citation built from it was off by five characters. |
| **An empty `notes/` raised `IndexError` two cells later** | Both the empty and missing cases now fail where the problem is, with the expected filename format in the message. |
| **A loose filename pattern truncated note ids** | `(.+)_(\d{5,6})` against `…_1882130.txt` matches with the id silently truncated to `882130`. The pattern is anchored to the claim-id format. |
| **Dangling action participants vanished** | A participant whose mention resolved to nothing became `{"entity_id": null}` with no record. Counted and carried on the dossier now. |

## Design questions the trace leaves open

These are about the architecture, not the notebook. They need a decision before v1.

1. **`must_not_link` is described as a band of the identity score.** A band derived from the
   same similarity number cannot act as a constraint — it carries no information the score
   does not already carry. A veto needs independent evidence. Implemented here as
   conflicting stated identifiers, conflicting primary licenses, and sibling organization
   names (entity type is a hard constraint on candidates); the full list of disqualifying
   evidence is a decision, not an implementation detail.
2. **The trace's worked scores are not reproducible from the model it describes.** An
   `identity_score` of 0.96 for a single shared phone within an occurrence implies an
   evidence base near 1.0 before the distance weight, but the base is never defined. Either
   the weights are additive priors (as implemented here) or the worked numbers need
   restating.
3. **`insufficient_evidence` cannot be produced under constrained decoding** if generation
   is constrained to the six scored values. It has to be in the enum and out of the scored
   set, or it only ever exists as a verdict the validator imposes.
4. **Identity projects upward; `basis: "inferred"` details project with it.** A phone number
   attributed to a party by a pronoun becomes a join key in `union_details` with the same
   standing as a stated NPI. Whether inferred ownership should be allowed to chain people
   together across claims is a decision the trace does not record.
5. **A suspended projection may already have produced alerts.** The cluster-size alarm
   suspends a projection, but nothing says what happens to alerts derived from it before the
   suspension.
6. **Within-chunk duplicate mentions are never detected.** Linking compares across chunks
   and notes, on the principle that coreference inside what the model read at once is the
   model's job. When the model emits two mentions for one party in one chunk, nothing
   notices.
7. **Name-only cross-claim identity is the common case, not the edge case.** On the court
   corpus every true cross-claim link is name-only, and only 11% of OIG LEIE exclusion rows
   carry an NPI. The POC's answer for the watchlist: a flag is shown only at a lens that
   admits the link, and it carries the link's basis, so a name-only flag reads as one (the
   court run's two flags are both name-only). Whether a name-only flag may reach the default
   view at all, and what an investigator's review of a flag records, are still undecided.
