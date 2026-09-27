## Matching core v1.1

**This section is the matching core.** It is identical code in [B] (this notebook) and,
later, in [A] (goko-v2-poc). The self-test section hashes every code cell between this
heading and the "End of the matching core" marker and compares the hash with the recorded
value, so any drift between the two systems is caught. Change it only deliberately: bump
`CORE_VERSION`, re-record the hash, and copy the section to [A].

**Contract.** Plain tables in, plain tables out. Nothing here reads a file, writes a
spreadsheet or knows about note text. The caller builds a *party frame* per side, one row per
party, with these columns (empty string when unknown):

| Column | Meaning |
|---|---|
| `party_id`, `part` | stable id; `person` or `business` |
| `first`, `middle`, `last` | cleaned name parts (`clean_person`) |
| `first_roots`, `last_nysiis`, `name_key` | nickname roots (`|`-joined), NYSIIS of the surname, `FIRST LAST` |
| `holder_key` | who holds a value, for single-holder counts: `LAST|F` (surname and first initial) for a person, the first alias for a business |
| `org_aliases`, `name_key` (business) | `|`-joined aliases from `org_aliases`; first alias is the name key |
| `dob`, `dob_int` | ISO date; `YYYYMMDD` as int (0 = none) |
| `addr_full`, `addr_street`, `zip`, `city_state`, `state` | address keys (`address_keys`) |
| `id_ssn` `id_npi` `id_dl` `id_tin` `id_license` `id_email` `id_vin` `id_plate` `id_cnpi` | valid, non-junk identifier values |
| `phone_own`, `phone_row` | a phone the party owns; a phone its row holds |
| `specialty`, `category`, `cat_strength` | canonical specialty; category; `strong` or `weak` |
| `tie` | `party_id` of the other part of the same row, or empty |

Pairs are positional: `il[i]` indexes the left frame, `ir[i]` the right one. The right frame
is the reference population whose value frequencies give per-value `u` (the watchlist in [B]).

**Where Splink would do better (whole core).** Splink compiles comparisons to SQL and runs
them in DuckDB or Spark, so 1M x 300k is routine and multi-core by default; here numpy and
per-unique-value Python loops do the work on one core. Splink's comparison library has
tested levels for names, dates and addresses; the levels below are hand-written. Splink
draws a waterfall chart per pair; the evidence table below is its tabular equivalent.