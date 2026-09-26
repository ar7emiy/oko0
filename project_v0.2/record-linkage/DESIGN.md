# Record linkage: two initiatives

This folder holds the **standalone record-linkage package**: two spreadsheets in, a
watchlist-probability per extracted entity out, no text. It shares its scoring principles
with the identity linker inside goko-v2-poc but is a separate build with separate inputs.
This file tracks both, how they differ, and the design decisions taken so far.

## The two initiatives

| | A. GOKO linker (`goko-v2-poc/`, notebook cells 16–19) | B. Standalone package (this folder) |
|---|---|---|
| Question | Which mentions across notes and claims are the same party? Is any on the OIG list? | For each extracted entity record in a claim, how likely is it on the watchlist? |
| Input | Claim notes (full text) → LLM extraction → mentions with spans | Two spreadsheets: extracted entity records, and the watchlist. No text |
| Unit compared | A mention: a name as written, its occurrences, the details the note says it owns, its roles in actions | A party within a row: structured fields only |
| Evidence available | Name, identifiers, details, co-parties, roles and actions, quotes and spans a reader can check | Name, identifiers, details, co-occurrence within a row, shared details across rows |
| Ownership of a detail | Stated or inferred by the model from the text | Only from which columns sit in which row (row-level unless the column says whose it is) |
| Relationships | Extracted from text: actions, (planned) group membership | Inferred only from rows and shared details: same row, same phone/address/TIN |
| Scale | Hundreds to thousands of mentions per batch | ~1 million watchlist rows × claim entities: candidate search must be indexed |
| Output | Scored links → read-time merged view → dossiers, app, graph RAG | Per-entity probability + candidates + field-by-field evidence (one Excel workbook) |
| Explanation | Decision card, backed by quotes in the note | Same field-by-field breakdown, backed by the input values only |
| Shared core | Fellegi-Sunter scoring, value-specific rarity from outside tables, identifier vetoes, basis separate from probability, one-way anchored co-party evidence, no silent name-only upgrades | same |

## Decisions so far (B)

- Inputs: two CSVs with the columns below; any may be null. The package does the watchlist
  breakdown, driven by a column-mapping file.
- Watchlist ~1M rows after breakdown.
- Rows may carry a person and a business together; each row splits into a person part and a
  business part tied to the row. Row-level details (address, phones) are held by both,
  marked row-level. Ownership rules per column are in one reviewable table.
- Probabilities should be data- and formula-driven, not preset (see "Parameters").
- No unstructured text; relationships only from rows and shared details.

- There are no labelled pairs. "Linked" in the extracted data means each row's details were
  attached to that entity (by a person on a form, or by GenAI RAG over claim notes; treated as
  reliable for now). It says who owns a detail, not which entities match.
- Extracted file: hundreds of thousands of rows, null-heavy, many unmerged duplicates (same
  name at different addresses, businesses sharing an address, and so on).

### Input schema (both files, same columns; everything but `record_id` may be empty)

| Column | Meaning | Goes to |
|---|---|---|
| `record_id` | unique row id (required) | row |
| `claim_id`, `note_id` | extracted file only; the watchlist has neither | row |
| `category` | medical, legal, repair shop, witness, claimant, other | row |
| `first_name`, `middle_name`, `last_name` | | person part |
| `dob`, `ssn` | | person part |
| `driver_license_number`, `driver_license_state` | | person part |
| `provider_npi` | | person part |
| `professional_license_number`, `_state`, `_type` | | person part |
| `provider_specialty` | | person part |
| `business_name` | | business part |
| `tin` | EIN is a business TIN | business part |
| `clinic_npi` | | business part |
| `street_number`, `street_direction`, `street_name`, `street_type`, `unit`, `city`, `state`, `zip` | address | row: held by both parts |
| `home_phone` | | person part |
| `work_phone` | | row: held by both parts |
| `email` | | person part, or the business when there is no person |
| `vin`, `plate_number`, `plate_state` | vehicle | person part, moderate weight |

Routing confirmed 2026-09-25.

### Breakdown ("explode"), done by the package, by rule

Each row yields up to two parties, a person part (when there is a first or last name) and a
business part (when there is a business name, or a TIN or clinic NPI with no name), tied to
each other by the row. Each detail is normalized and attached to its owner per the table, or
to both parts with ownership "row". Output of the step: a parties table, a details table
(party, type, normalized value, ownership own/row), and ties (same row). One derived index maps
every detail value to every party holding it across both files: it drives shared-identifier
counts, anchored pairs and row-level evidence.

### Category

- Given category is kept; an inferred category is added beside it with the rule that set it:
  provider/clinic NPI or a medical license type → medical (identifier-backed); bar number or a
  legal license type → legal (identifier-backed); business-name words such as "Auto Body",
  "Collision", "Towing" → repair shop, and "Law Office", "Esq.", "LLP" → legal (keyword, weaker).
  Witness and claimant are never inferred.
- "other" counts as no information.
- Given vs inferred disagreement is a data-quality finding; matching uses the
  identifier-backed value; the given value stays visible.
- In matching, category is supporting evidence, never a veto. Its weight is learned from how
  often anchored true matches agree on it, so frequent conflicts on identical entities make
  it count for little automatically.
- Category sets the group for starting rates: professional (medical, legal), business
  (repair shop, or no person part), private (witness, claimant), unknown. Each group's rate is
  estimated from the data, not preset.

### Answered 2026-09-25

- **Watchlist category** is not given directly; it is inferred from `provider_specialty` and
  `professional_license_type`, which are more granular than the extracted categories
  (acupuncture, chiropractic, osteopathy, ...). The package carries a reviewable mapping table
  from each specialty and license type to the six extracted categories (e.g. acupuncture,
  chiropractic, osteopathy → medical; attorney → legal); unmapped values → unknown, listed in
  the run manifest. The granular specialty is also compared on its own, as a supporting field,
  whenever the extracted row has one.
- **Output**: one Excel workbook, one sheet per table: entities (one row per extracted row:
  probability, basis, best watchlist row), candidates (every scored entity × watchlist pair
  above a floor), evidence (pair × field breakdown), claims (per-claim roll-up), manifest
  (parameters, their sources and counts, mappings, versions).
- **Several candidates**: the entity's probability is its single best match; every other
  candidate is listed. **Name-only matches are never hidden**: early runs will be dominated by
  them, so they appear in every sheet with basis `name_only`, count toward the entity sheet,
  and are filterable rather than thresholded away.
- **Relationship columns**: none beyond the flat schema.

### Settled in the build plan (PLAN.md section 7, accepted 2026-09-25)

- Name m is not estimated from the "one name per identifier" anchor (circular): a strict
  anchor gives m for non-name fields, a loose anchor plus EM with u fixed gives name m.
- The entities sheet has one row per party (record_id + part), not per extracted row.
- Output is one Excel workbook (see "Answered 2026-09-25").
- No bar-number column: legal licences are recognised through the licence type.
- Vetoes: SSN, provider NPI, driver licence (same state), TIN. Never clinic NPI. Sibling
  businesses are a strong negative level, not a veto.
- The prior group comes from the extracted party; business parts are "business" unless
  identifier-backed medical or legal.
- Category and specialty are compared as one correlated group.
- Basis gains "contextual" (name + location/specialty/category); `rests_on_name` covers
  contextual and name_only.
- Without an identifier, a given category ranks before a keyword one.

The build is `record_linkage.ipynb` (PLAN.md section 8); its README lists the further choices
made during the build.

## Parameters: sources, in order of preference

| Parameter | Source |
|---|---|
| u, chance agreement | Random record pairs from the data (as Splink does); outside tables for names (Census, SSA) and organization words (NPPES + a state business registry); for identifiers, how many distinct parties hold each value |
| m, agreement among true matches | 1) anchored pairs inside the extracted file (two rows sharing a TIN/NPI that only one name ever uses: real extracted messiness); 2) watchlist duplicates anchored on single-holder SSN/NPI; 3) pessimistic simulation of extraction noise; 4) published starting values, only where nothing else informs a field |
| Prior | Probability that two random records match (independent of candidate rules), estimated per category group by count; output includes a sensitivity table |
| Correlated fields | Compared as one graded group: address (exact / same street and number / same ZIP / same city / same state), name |
| Vetoes | Rules, not odds: two different single-holder identifiers of a one-per-party type |

Every parameter in a run's manifest records its source and the number of pairs behind it.

What each learning source depends on (2026-09-24): anchored pairs need enough single-holder
identifiers present on both rows and are biased toward better-kept records; EM needs enough
true matches among candidates (fragile when matches are rare, as against a watchlist) and
assumes fields are independent; any prior estimated among candidate pairs changes with the
candidate rules, hence defining it over all pairs.

## Where Splink would do better (to be restated as comments at each notebook step)

recordlinkage is the required base. Splink runs on DuckDB/Spark (1M rows routine), estimates u
from random pairs, adjusts per value by term frequency, uses multi-level comparisons with an
explicit null level, trains EM with u fixed and in blocking-aware passes, defines the prior
independently of blocking, and draws a waterfall per pair. recordlinkage's ECMClassifier is
textbook EM on binary vectors: u learned with m, prior among candidate pairs, no term
frequency, no correction for blocking. The package implements Splink's fixes in its own
scorer on top of recordlinkage's indexing and comparisons.
