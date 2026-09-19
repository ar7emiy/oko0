# Manual validation guide

You build the answer key by hand, run the system, then look at the two side by
side yourself. Nothing here computes a score — that's deliberate, per your
request. This is for building your own trust in the numbers, not for
producing another number.

## 1. The 60 notes

`data/raw_notes/DOC00000.txt` through `DOC00059.txt`. Plain text, open them in
anything. This is not a sample — it's the exact, fixed slice every "60-doc"
figure in `designs/TODO.md` was measured against, so what you validate here is
what those numbers describe.

`data/doc_index.json` maps each `doc_id` to its `claim_id`/`occurrence_id`, if
you want to see which notes share a claim (several notes usually do — that's
what resolution is stitching back together).

**A ground-truth manifest already exists** at `data/ground_truth/manifest.json`
— it's what every automated measurement today (entity recall, B-cubed, etc.)
was scored against. It's produced by the same code that wrote the notes, so
it's correct by construction for the synthetic data, but it can't catch a bug
in *how* it was produced, and it can't catch judgment calls the way a human
reading the note fresh can. **Build your golden set from the raw text first,
without looking at it.** Compare against it afterward if you want a sanity
check on your own labeling — not before.

## 2. Building the golden set

Three CSVs in `validation/golden/`, one row per fact. Open in Excel, Sheets,
or a text editor — whatever's easiest. **`DOC00000` is filled in completely
across all three files**, marked `WORKED EXAMPLE` — not a partial sample, an
actual full answer key for that one note, so you have something to calibrate
against before doing the other 59 yourself. `DOC00001` onward are empty rows
for you to fill in.

Run `python validation/show_doc.py DOC00000` to see the raw note and that
worked example rendered side by side.

**Granularity note.** The golden CSVs are one row per *fact* — if a phone
number is stated twice in a note, that's one golden row, noted as "stated
twice." The system's per-document dump (`system_output/DOC00000.txt`) is one
row per *occurrence* — it will show that same phone number extracted at two
different spans. That's not a duplicate or an error on either side; it's the
two formats operating at different grain. When you compare, check that every
golden fact is covered by at least one system occurrence, not that the counts
match 1:1.

**One thing worth knowing before you compare `DOC00000`:** the system's
identifier dump shows four extra `dob`-kind rows beyond Robert Miller's real
date of birth — `2024-07-01`, `2026-06-15`, `2024-03-28`, `2026-08-18`. None of
those are birthdates; they're a payment date, a coverage-denial date, a
deposition date, and a reserve-adjustment date. The extractor's `dob` kind
currently catches *any* bare date, not literally only dates of birth (see the
caveat further down) — **don't add these to your golden set**, they aren't
identifiers in the sense a human means. One of them is worse than just
noise: the deposition date `2024-03-28` gets bound to **Robert Miller**, as if
it were his own date of birth, because the line-proximity fallback binds to
whichever name sits nearest on the page — and Robert Miller's name happens to
be the closest one, even though the deposition has nothing to do with him. Not
something to fix as part of this validation pass — logged as D33 on the board
so it doesn't get lost.

**`entities.csv`** — one row per distinct person/organization in a note.
`entity_type` must be one of the five the system uses: `claimant`, `attorney`,
`medical_provider`, `repair_shop`, `adjuster` — using the same vocabulary is
what makes your row and the system's answer directly comparable, not
apples-to-oranges. `all_surfaces_seen` is every way that entity is written in
*that one note* (nicknames, initials, "Miller, Robert" vs "Robert Miller",
typos) — this is what the system's entity-resolution step has to see through.

**`identifiers.csv`** — one row per phone/email/address/npi/tin/ssn/vin/dob,
and who it belongs to. **Leave `owner_entity_name` blank when the text
genuinely doesn't say** — don't guess to fill the cell. An identifier with no
stated owner is a real, intentional case in this corpus (the fixture calls it
an "orphan"), and guessing an owner defeats the point of checking whether the
system also correctly declines to guess.

**`relationships.csv`** — one row per relationship between two entities
("represents", "treated", "works at", whatever's natural — there's no fixed
vocabulary here, write it the way you'd say it). **Read the caveat below before
you invest time in this file.**

### The relationships caveat — read this first

The operational pipeline (the one that produced every number I've reported
today) does **not** currently extract general relationships at all. It finds
entities, identifiers, and who an identifier belongs to — but a sentence like
*"Harbor & Vance LLP regarding representation of Robert Miller"* produces no
`attorney → represents → claimant` fact anywhere in the graph. The capability
exists in code (`src/relations.py`) but has never been wired into the main
pipeline — that's tracked as defect D1 in `designs/TODO.md`, and it's still
open.

So validating relationships means testing that separate, unfinished lane on
its own, not the system as it operationally runs. It's real and worth doing —
just go in knowing you're evaluating research code, not a shipped capability,
and that a low score there doesn't move any of the numbers I've quoted you
elsewhere. See step 4.

**Practical note on effort:** 60 notes × 3 files by hand is real work. Nothing
stops you from doing a first pass on 10–15 notes to see how the comparison
feels before committing to all 60 — the run script has a `--limit` flag for
exactly that.

## 3. Running the system

```
python validation/run_narrated.py
```

This runs the exact pipeline behind every number today — profiling →
extraction → embedding → resolution → graph — over all 60 documents. You'll
see the same live narration that ran during today's work: chunk counts, which
lane found what, identifier-binding decisions, the resolver's calibration
report (match prior, bits of evidence per field, which comparisons couldn't be
trained). Nothing is dressed up for this run.

When it finishes, `validation/system_output/DOC00000.txt` (one file per note)
lists — in the order things appear in the text — every name mention, every
identifier and who it was bound to, every coreference link, and which
resolved entity each mention ended up in, with cross-references to any *other*
document sharing that entity so you can check clustering decisions directly.

```
python validation/run_narrated.py --limit 5      # quick look, 5 docs
```

**Cost/time:** every one of these 60 documents has been run through this exact
configuration many times today, so nearly every model call hits the on-disk
cache and costs nothing — a few minutes either way.

**Two things you'll see in the output that are real, not bugs** — worth
knowing before you flag them:
- **`entity_class` is per-mention**, not per-entity, and can be locally wrong
  even when the mention still lands in the correct resolved entity. In
  `DOC00000`, "Rob Miller" gets classified `medical_provider` by the local
  classifier but still resolves into the correct `Robert Miller` entity. Your
  golden `entity_type` is per-entity — that's what the resolved-entity column
  in the dump should be checked against, not the per-mention class next to
  each individual surface.
- **`identifier_kind=dob` is used for any bare date**, not literally only
  birthdates — a deposition date or a payment date extracted as a standalone
  date pattern also lands under `dob`. This is a real modeling simplification
  in the current schema, not something this validation pass needs to fix.

### Optional: the relations lane

```
python validation/run_narrated.py               # run this first
python validation/run_relations_lane.py --limit 5
```

Dumps raw subject/predicate/object triples to
`validation/system_output/DOC00000_relations.txt`. Unlike the main run, **this
calls the API fresh** — it's never been run before today, so nothing is
cached. Use `--limit` for a cheap look before running all 60.

You'll likely see near-duplicate triples from the same fact (chunks overlap by
design, so a sentence near a chunk boundary can be read twice) — that's a
known consequence of raw, undeduplicated output at this layer, not a labeling
bug on your end.

## 4. Comparing

```
python validation/show_doc.py DOC00000
```

Prints, for one document: the raw note, your three golden tables filtered to
that doc, the system's entity/identifier/coref dump, and the relations-lane
dump if you ran it. All in one scroll, no scoring, no diffing — you read it
and decide what matches.

Do this doc by doc. There's no aggregate view by design — you asked not to see
analytics at this stage, so there isn't one.
