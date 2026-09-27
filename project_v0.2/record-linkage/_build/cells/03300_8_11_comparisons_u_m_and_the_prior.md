## 8-11 · Comparisons, u, m and the prior

**Comparisons (8).** The core's `compare_pairs` gives one level per field for any set of
pairs; the same code runs on candidates, random pairs, anchors, watchlist duplicates and
simulated pairs. Each part (person, business) has its own weights.

**u (9).** `random_pairs` random extracted × watchlist pairs per run (split between parts by
their share of extracted parties) through the same comparisons give the field-level u of
every level (Splink's method), and the rates of the name sub-parts. Exact levels use
value-specific u instead: names from the Census/SSA tables, organization words from NPPES
(or the watchlist's own share), identifiers, dates and addresses from how many hold the value.

**m (10)**, per field and level, in order of preference:

| Source | Pairs | Used for |
|---|---|---|
| 1a strict anchors | extracted pairs sharing a valid one-per-party identifier (SSN, NPI, DL; TIN for businesses) held under exactly one name; at most `anchor_pairs_per_value` pairs per value; same-note pairs excluded | every field except the names (the anchor conditions on the name) and except the anchoring field itself |
| 1b loose anchors | the same identifier types held by 2-20 extracted parties, no name condition; EM with u fixed and the non-name m fixed from 1a | name, middle, org name |
| 2 watchlist duplicates | watchlist pairs sharing an SSN / NPI (TIN / clinic NPI) held by 2-20 parties; persons also by exact name + DOB (then not for name or DOB) | fields still short of data |
| 3 simulation | `sim_records` watchlist rows and their noisy copies (noise table) | any field with < `n_min` informative pairs from 1-2 |
| 4 published | `mappings/published_m.csv` | the base every estimate is shrunk toward |

Each estimate is shrunk toward the next source with alpha = 5 pseudo-pairs; the manifest
records the chain, the pairs behind it and a 95% interval. An agreement level whose m falls
below its u is flagged and counts 0 bits.

**Prior (11)**, per group of the extracted party, over *all* pairs: pairs firing a strict
rule (single-holder identifier agrees with no veto; exact name + DOB; exact name + street;
exact org name + ZIP or + street) / how often a true match fires one of them (from the
estimated m and the fill rates) / all extracted × watchlist pairs of the group. A group with
no strict pair uses a pseudo-count and is flagged.

**Where Splink would do better.** Splink estimates u from up to 10^8 random pairs in
DuckDB and trains m with EM in several passes, each blocked on a different rule and with u
fixed, then averages the passes; here EM runs once, on the loose-anchor set. Splink's prior
comes from a deterministic-rules count with a user-given recall; here recall is computed from
the m estimates. Splink does not use anchors or simulation.