## 1 · Mappings, reference tables and inputs

**Mappings** (`mappings/*.csv`) are the reviewable tables: column routing, category maps,
keyword rules, specialty synonyms, the simulation noise table and the published starting
values of m. **Reference tables** (`reference/`) are copied outside tables, checked against
the SHA-256 recorded in `reference/SOURCES.md`. **Inputs** are two CSVs with the schema in
DESIGN.md: `record_id` is required and unique per file, every other column may be empty,
missing schema columns are added empty, and unknown columns are kept as `x_<name>`
(displayed, never compared). All-empty columns are reported.

**Where Splink would do better.** Splink reads Parquet or a database table straight into
DuckDB without a pandas copy, so a 1M-row input costs little memory. Here pandas holds the
rows as text.