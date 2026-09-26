# Build plan: standalone record-linkage package [B]

Status: **approved 2026-09-25**, with the delivery and shared-code decisions in section 8.
Implements [DESIGN.md](DESIGN.md).

## 1. Layout (`project_v0.2/record-linkage/`)

| Path | Purpose |
|---|---|
| `DESIGN.md` | Agreed design; gets the decisions settled in section 7 |
| `README.md` | Install (recordlinkage `--no-deps`), run, inputs/outputs, status |
| `requirements.txt` | pandas>=3,<4 (recordlinkage breaks on pandas 4), numpy, pyarrow, jellyfish, xlsxwriter (fast Excel writing), openpyxl (reading labels back) |
| `record_linkage.ipynb` | Orchestration only: one section per step, markdown explanations, a "Where Splink would do better" note at each step |
| `run_notebook_check.py` | Runs every cell on the synthetic set; non-zero exit on any error |
| `src/wlink/config.py` | One `RunConfig`: paths, seeds, sample sizes, chunk sizes, caps, floors, K, N_MIN, smoothing. The manifest dumps it; no thresholds anywhere else |
| `src/wlink/io.py` | Read CSVs; schema check; `record_id` required and unique; unknown columns kept as `x_*` |
| `src/wlink/mapping.py` | Load and validate the reviewable tables in `mappings/` |
| `src/wlink/normalize.py` | Name parsing, nicknames, NYSIIS, org aliases/d-b-a/suffixes/abbreviations (ported from goko), SSN, TIN, NPI (Luhn), DL, license, phone, email, VIN (check digit), plate, DOB (placeholder detection), address parts, ZIP5, state |
| `src/wlink/explode.py` | Rows → parties, details, ties, value index |
| `src/wlink/category.py` | Given vs inferred category, keyword rules, watchlist mapping, prior group, data-quality findings |
| `src/wlink/reference.py` | Outside tables and per-value u lookups (flat fallback stamped) |
| `src/wlink/candidates.py` | Blocking rules, pair counts per rule before indexing, chunked recordlinkage indexing, identifier joins |
| `src/wlink/compare.py` | recordlinkage comparisons plus custom features (org word rarity, graded address, DOB) → one level per field. Same code for candidates, random pairs, anchors, simulated pairs |
| `src/wlink/params.py` | u, m, prior, sensitivity → manifest records |
| `src/wlink/simulate.py` | Noise engine driven by `mappings/simulation_noise.csv` |
| `src/wlink/score.py` | Vectorized Fellegi-Sunter, vetoes, basis classes, one-way co-party, posterior, roll-ups |
| `src/wlink/explain.py` | Evidence rows per pair; rows sum to the pair's total |
| `src/wlink/output.py` | Workbook writer; continuation sheets past Excel's row limit; JSON copy of the manifest |
| `src/wlink/review.py` | *Later phase*: blind stratified review sample; labels read back into precision, recall, calibration |
| `mappings/*.csv` | columns (routing), category_map, category_keywords, specialty_canon, simulation_noise, published_m (with citations) |
| `reference/` | Copied Census/SSA/NPPES tables + new nickname table; `SOURCES.md` with hashes; `refresh_reference.py` |
| `tools/export_leie.py` | Raw OIG LEIE → input schema |
| `tools/make_synthetic.py` | Fictional test set + truth file (seeded) |
| `tools/make_scale_set.py` | 1M watchlist + 300k extracted rows for the benchmark (not committed) |
| `tests/` | `unittest` modules + small synthetic inputs |
| `data/`, `out/`, `review/` | Gitignored. Labels are never read by the pipeline (AGENTS rule 13) |

Reference tables are **copied, not linked**, so the folder stands alone and a refresh in goko-v2-poc can't silently change [B]'s scores. Ported goko helpers carry a header naming their source cell.

## 2. Pipeline (one notebook section each)

| # | Step | What it does | Scale approach |
|---|---|---|---|
| 0 | Setup | Seeds, versions, input hashes | – |
| 1 | Load and validate | Schema check, unique `record_id`, report all-null columns | pyarrow reader, text dtype |
| 2 | Normalize | Per the column table; validity flags (Luhn, VIN check, SSN ranges, junk values like 000000000 or 1900-01-01) | Vectorized; name/org parsing cached per distinct value |
| 3 | Breakdown | Person part if a first/last name; business part if a business name, or a TIN/clinic NPI with no name; email to the person (or the business if no person); address and work phone held by both as "row"; empty rows reported | Long details table |
| 4 | Value index | For each (type, value): holders per file, distinct names among holders, single-holder flag, junk flag | One groupby |
| 5 | Category | Extracted: identifier-backed → given → keyword. Watchlist: specialty map → licence-type map → unknown. "other" = empty. Disagreements recorded; unmapped values listed | Mapping joins |
| 6 | Outside rarity | Census, SSA, NPPES, nicknames | Lookups |
| 7 | Candidates | Rules below; pair count per rule printed before indexing; oversized keys refined (e.g. + state); only extracted×watchlist, same part type | Chunks of ~20k extracted parties |
| 8 | Compare | One level per field (table below), including an explicit empty level | Parallel, ~100 bytes/pair |
| 9 | u | Random pairs + outside tables + value index | 5M random pairs in chunks |
| 10 | m | Anchors → watchlist duplicates → simulation → published values | Capped per value |
| 11 | Prior | Count-based per group, sensitivity table | From built candidates |
| 12 | Score | Sum of log2(m/u), per-value u on exact levels, 0 bits when empty; vetoes; co-party pass; basis | numpy; keep a pair if p ≥ floor, top-K for its entity, or identifier/veto. Never filtered by basis |
| 13 | Roll-up | Entity = best single match, others listed, `rests_on_name` flag | groupby |
| 14 | Evidence | Per field: both values, level, m, u, their sources and pair counts, bits | Kept pairs only |
| 15 | Workbook | Sheets: entities, candidates, evidence, claims, manifest; filters on basis and `rests_on_name` | Streaming writer; continuation sheets |
| 16 | Diagnostics | Blocking recall on identifier anchors; weight table; p histogram by basis; top 20 name-only matches | – |
| 17 | Self-tests | Invariant checks | – |
| 18 | Review sample *(later)* | Blind stratified sample; labels → metrics | – |

**Blocking rules** (union; each marks which rule proposed the pair):
- **Persons:** exact SSN, provider NPI, DL (state:number), licence (state:number), email, VIN, plate; any phone; NYSIIS(last) + first initial; NYSIIS(last) + canonical first initial (Bill meets William); exact DOB + first initial (surname change); swapped first/last; sorted neighbourhood on "last first" (window 5).
- **Businesses:** exact TIN, clinic NPI, email, work phone; rarest NPPES word of each alias (incl. d/b/a); leading word + state; sorted neighbourhood on the sorted-word name.
- Every rule the prior relies on is a subset of these, checked by a test.

**Comparison levels** (each field also has an empty level worth 0 bits):

| Field | Levels, best first |
|---|---|
| Person name (one group) | exact first+last · last exact + first nickname or close spelling · last close/same sound + first agrees · last exact + initial agrees · swapped · last exact, first empty · last exact, first differs · else |
| Middle | exact · initial agrees · differs |
| Org name | exact · declared d/b/a alias · short form (word subset) · rare shared word · common shared word · sibling pattern (strong negative) · none |
| DOB | exact (placeholder dates get little weight) · day/month swap or one-digit typo · same year+month · same year · differs |
| Address (one group) | exact incl. unit and ZIP · same number+street · same ZIP · same city+state · same state · differs |
| Each identifier | exact (weighted by how many hold the value) · near (one digit/transposition; SSN, DL, NPI) · differs (veto where one-per-party applies) |
| Phone | exact, owned, single holder · exact, row-level or shared · differs |
| Specialty + category (one group, correlated) | same specialty · same category (identifier-backed) · same category (keyword) · different |
| Co-party | anchored tie · n/a |

## 3. Data structures

- **parties**: party id, source, record_id, part, claim/note ids, name parts, nickname root, phonetic codes, org name/aliases/rare word, DOB, address parts, category fields, specialty, passthrough columns.
- **details** (long): party, type, normalized value, raw value, source column, ownership (own/row), valid.
- **ties**: record_id, person party, business party.
- **value_index**: type, value, holders per file, distinct names among holders, single-holder flags, junk flag and reason.
- **pairs**: party ids, proposing rules, level per field, per-value u, bits per field, total, prior group, prior, p, veto, basis, co-party bits.
- **evidence** (long): pair, field, both values, level, m (+source, pairs), u (+source, pairs), bits.
- **entities**: identity, category (given/inferred/rule/mismatch/group), candidates count, best watchlist row and name, p, basis, `rests_on_name`, vetoes, best non-name-only p, top-K others.
- **claims**: claim, rows, parties, max p and its entity, counts by basis × p band, name-only count at p ≥ 0.5.
- **manifest**: section, key, value, source, pairs, confidence interval, note. Covers run config, reference hashes, unmapped values, blocking counts, m, u, prior, sensitivity, data quality, vetoes.

## 4. Parameter estimation

**u.** Random extracted×watchlist pairs (5M) run through the same comparison code; per-value u on exact levels: names from outside tables, identifiers/DOB/address from the watchlist's own value frequencies (so shared or placeholder values weigh little automatically). The manifest records u, its source and counts.

**m, per field and level, in order:**

| Order | Source | Used for |
|---|---|---|
| 1a | Extracted pairs sharing a valid, one-per-party identifier held under exactly one name (≤ 50 pairs per value; same-note pairs excluded) | Non-name fields only (DOB, address, phone, email, vehicle, specialty/category): this anchor conditions on the name, so name m would be ≈ 1 |
| 1b | Same identifiers held by 2–20 parties, no name condition; EM with u fixed, run only on this set | Name, middle, org-name m |
| 2 | Watchlist duplicates on single-holder SSN/NPI (LEIE: 177 NPI groups; 1,003 name+DOB groups for other fields) | Fields still short of data |
| 3 | Simulation: 50k watchlist records + noisy copies per the noise table | Any field with < 50 informative pairs after 1–2 |
| 4 | Published values (cited) | Only where nothing else applies |

A field that defines an anchor is never estimated from that anchor. Estimates are shrunk toward the next source (α = 5); the manifest gives 95% intervals; an m below u is flagged and set to 0 bits.

**Simulation noise table** (pessimistic, for review): surname typo 4%, compound part dropped 3%, surname change 4%; first nickname 10%, initial only 6%, typo 4%, missing 5%; swapped names 1.5%; middle dropped 40% / initial 30%; DOB day-month swap 2%, digit typo 3%, year ±1 1%, missing 20%, placeholder 1%; SSN/NPI/DL digit typo 1.5%, transposition 1%; moved within state 35%, to another state 12%, unit dropped 25%, ZIP typo 2%; phone changed 35%; email changed 25%; business suffix dropped 35%, abbreviated 15%, d/b/a used 15%, typo 4%; category disagrees 20%; specialty coarser 25%.

**Prior, per group, over all pairs.** Group from the extracted party (professional / business / private / unknown). Count pairs firing strict rules (identifier agrees with no veto; exact name + DOB; exact org name + ZIP; exact name + street), divide by all possible pairs in the group, and correct for how often a true match fires those rules (computed from the estimated m's and how often fields are filled, instead of a hand-set recall). Zero counts use a small pseudo-count, flagged. Sensitivity table: each group × several recall and prior settings → how many entities cross 0.5 / 0.8 / 0.9.

**Vetoes (rules):** two different valid, single-holder values of SSN, provider NPI, DL (same state), TIN. Not clinic NPI (organizations hold several), phone, email, licence, VIN, plate. A vetoed pair stays visible with p = 0 and its reason.

**Basis classes:** identifier · address · dob · co_party · contextual (name + location/specialty/category) · name_only · none. `rests_on_name` = contextual or name_only; a filter, never a threshold.

**Co-party (one way):** a person pair gains bits only when their tied businesses are themselves linked on an identifier (p ≥ 0.9, no veto) and the names already agree. Name-only links never vouch for each other. Its m and u are estimated like any field.

## 5. Tests and acceptance

- **Unit tests:** normalizers, breakdown, category, candidates (each rule proposes its target; cross-file and same-type only; chunked = unchunked), comparison levels, score invariants (empty = 0 bits; evidence sums to total; an extra agreeing identifier never lowers p; veto → p = 0 visible; name-only never becomes identifier; co-party needs an anchor; deterministic), parameters (closed-form u; anchor excludes its field; EM recovers known m on simulated data; prior formula), output (sheets, continuation, manifest completeness), LEIE export.
- **Synthetic set:** ~2,000 persons and 500 businesses; ~5,000 watchlist and ~3,000 extracted rows; ~45 hand-written edge cases with truth (person+business rows, shared TINs, sibling businesses, shared and junk SSNs, conflicting SSN veto, Bill/William, typos, swapped names, initials, TIN-only claim rows, rare exact name with nothing else (must show as name_only), John Smith, day/month swap, moved state, category conflicts, keyword businesses, VIN/plate, shared clinic phone, co-party anchoring, watchlist duplicates, invalid NPI, empty rows...).
- **Real data:** OIG LEIE as the watchlist (84,001 rows) against noisy copies of 3,000 LEIE rows + 3,000 fictional parties; LEIE against itself for duplicates; a 1M × 300k scale benchmark.
- **Acceptance:** all tests pass; notebook check < 2 min; every hand-written case proposed with the expected basis, veto and top rank; blocking recall ≥ 99% on synthetic pairs; every true name-only pair visible; every parameter in the manifest with source and count; LEIE run < 5 min with ≥ 98% of true pairs proposed; scale run < 60 min and < 10 GB RAM; identical results on rerun.

## 6. Phasing

| Milestone | Content | Effort |
|---|---|---|
| M0 | Scaffold, config, reference copy, mapping drafts, notebook skeleton with Splink notes | 0.5 d |
| M1 | Normalize, breakdown, value index, category; LEIE exporter; synthetic generator; tests | 2 d |
| M2 | Candidates and comparisons; blocking diagnostics; tests | 1.5 d |
| M3 | u, anchors, EM, simulation, fallbacks, prior + sensitivity, manifest; tests | 2 d |
| M4 | Scoring, vetoes, basis, co-party, roll-ups, evidence, workbook; end-to-end test | 1.5 d |
| M5 | LEIE runs, scale benchmark, tuning, README/STATE | 1 d |
| M6 (later) | Review sample + label metrics | 1 d |

About 9.5 working days in total.

**Initial category mapping** is drafted from the 88 LEIE GENERAL and 206 SPECIALTY values: clinical professions and facilities → medical; LAW PRACTICE / LAWYER → legal; employees, owners, billing and management companies, insurers, government → other; a "needs review" flag on ambiguous ones (adult homes, transportation companies, technicians, counsellors, social workers). Nothing in LEIE maps to repair shop, witness or claimant.

## 7. Issues raised against DESIGN.md (proposed resolutions)

1. **Name m would be circular** with the "one name per identifier" anchor → strict anchor for non-name fields, loose anchor + fixed-u EM for names.
2. **Entities sheet grain** → one row per party (record_id + part), not per extracted row.
3. The comparison table still says "CSV set" → one Excel workbook.
4. **No bar-number column** → legal licences detected through licence type.
5. **Veto set** → SSN, provider NPI, DL (same state), TIN; not clinic NPI. Sibling businesses as a strong negative level, not a veto.
6. **Prior group** from the extracted party; business parts go to "business" unless identifier-backed medical/legal.
7. **Category and specialty are correlated** → compared as one group.
8. **Basis:** add "contextual" (name + location/specialty/category); `rests_on_name` covers contextual and name_only.
9. **Category precedence** without an identifier: given before keyword.

## Open questions for the user

1. The real ~1M watchlist: which list, which columns does it fill, what specialty vocabulary?
2. The LEIE export needs DOB, street and ZIP (kept out of the committed goko table): rebuild it locally into gitignored `data/`?
3. LEIE GENERAL goes into `professional_license_type`; exclusion type/date carried as display columns?
4. Add a nickname table (carltonnorthern/nicknames, Apache-2.0)?
5. No state business registry yet; NPPES makes AUTO/BODY/COLLISION look rare → use the larger of NPPES and the watchlist's own word share until one is chosen. Which state?
6. Cross-type matching (a sole proprietor "John Smith DC PC" vs a person; an SSN used as a TIN): out of scope for v1, or display only?
7. Deduplicating the extracted file itself: out of scope (the claims sheet absorbs repeats)?
8. Exclude anchor pairs within one note?

## Risks

Excel's row limit (continuation sheets, floor + top-K); candidate volume on common surnames (initial blocks, counts before indexing, state refinement); sparse anchors in null-heavy data (fallback chain, shown in the manifest); pandas 3 with recordlinkage `--no-deps` (pin < 4); best-single-match understates several independent weak candidates (DESIGN's choice; others listed).

## 8. Decided 2026-09-25

**Approved.** All issue resolutions in section 7 are accepted; build to this plan.

**Delivery form: one notebook.** The whole system ships as a single `record_linkage.ipynb`:
every function, the LEIE exporter, the synthetic-data generator and the tests live in it
(tests as a self-test section, like goko's cell 23). Development happens in plain `.py`
modules with unit tests first; once everything passes, the code is assembled into the
notebook, the notebook is run end to end, and the development modules are removed. Data
files stay files: `mappings/*.csv`, `reference/`, and the gitignored `data/`, `out/`,
`review/`. Where section 1 lists `src/wlink/*.py`, `tools/*.py` and `tests/`, read them as
development-time files that end up as notebook sections.

**Same core code, separate systems.** [A] (goko-v2-poc) and [B] are entirely separate: no
shared library, no shared runtime, no data passing between them. The matching core (name and
org normalization, rarity lookups, comparison levels, the Fellegi-Sunter scorer, vetoes,
basis classes, parameter estimation) is identical *code* in both. [B] writes it first as one
contiguous notebook section headed with a core version; [A] later receives a copy of that
section, with its text-derived layers kept in separate cells. Each notebook's self-tests
include a check that its core section matches the recorded version hash, so drift is caught.
The core must therefore take plain tables in and return plain tables out, with nothing
spreadsheet-specific ([B]) or text-specific ([A]) inside it.
