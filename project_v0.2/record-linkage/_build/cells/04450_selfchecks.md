## 16b · Self-checks without gold labels

Two measurements of the whole system that need no labels. Both run the complete B1 pipeline
(deduplication, estimation, blocking, scoring, clusters) again on altered inputs, so what they
measure is what a run produces. Their results are read by nothing in the pipeline (AGENTS rule
13): they measure it, they do not tune it.

**Held-out identifier check** (`holdout_ids`: SSN, provider NPI, TIN, driver licence). Where
both an extracted and a watchlist party carry one of these identifiers, the identifier is the
truth: equal values are a match, different values are not (values one digit or one
transposition apart are left out as ambiguous; values held under more than
`holdout_max_holders` holders are left out as unreliable). The identifier's input column is
then blanked in both files and B1 runs on everything else. `holdout_mode = "each"` hides one
identifier per run (each is judged with the others still present); `"all"` hides all of them in
one run.

**Noise-injection test.** `noise_sources` watchlist records are copied 1 to `noise_max_copies`
times with the pessimistic noise table (the simulation engine of the noise section), and
`noise_decoys` fictional parties that are not on the list are added. Truth: each copy matches
its source and the source's own watchlist duplicates (records sharing an SSN, NPI, DL, TIN or
clinic NPI with it); every other pair of a copy or a decoy is a non-match.

**Metrics** (both tests, B1 and the baseline): for each p threshold, true positives, false
positives, false negatives, precision and recall; true and false pairs per p band; precision
per basis at p >= 0.5; the funnel of the true pairs (proposed by the candidate stage, kept,
above 0.5), with the number the **candidate stage lost** also written to the manifest. An
extracted row is judged through the entity it was pooled into, so deduplication errors count.
Denominators are explicit in every table (AGENTS rule 12).

**Where Splink would do better.** Splink has no built-in held-out identifier check, but its
labelling tools (`truth_space_table_from_labels_column`, ROC and precision-recall charts) do the
same arithmetic from a column that marks the truth, and it can use a withheld identifier as that
column. Noise injection has no Splink counterpart; Splink's own benchmarks use labelled public
data. The measurement here is ours.
