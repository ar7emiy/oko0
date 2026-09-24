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
| Output | Scored links → read-time merged view → dossiers, app, graph RAG | Per-entity probability + candidates + field-by-field evidence (CSV set) |
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

Columns known so far: first name, last name, DOB, SSN, provider specialty, provider NPI,
professional license number / state / type, driver license number / state, business name,
TIN (EIN is a business TIN), clinic NPI, street number / direction / name / type, unit,
city, state, ZIP, home phone, work phone, VIN, license plate number / state, email.

## Open questions (B)

1. Output: a set of CSVs (entities, candidates, evidence, claims, run manifest) or one
   Excel workbook with those as sheets.
2. Combining several weak candidates for one entity: best single match (proposed) or
   combined.
3. Whether any relationship columns (employer, owner) exist beyond the flat list.

## Parameters: what can be learned from data, and what each needs

See the conversation of 2026-09-24; summary in the package README when it is written.
