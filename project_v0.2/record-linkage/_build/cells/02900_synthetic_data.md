## Synthetic data

A fictional test set with a truth file, deterministic under the run seed.

* **Universe**: persons and businesses with canonical details; names drawn with Census and
  SSA frequencies (so "Smith" is as common as it is), every identifier fictional and valid
  (NPIs pass Luhn, VINs their check digit).
* **Watchlist rows**: 60% of the universe, lightly noised, ~10% listed twice (watchlist
  duplicates), plus watchlist-only parties up to the requested size.
* **Extracted rows**: 70% of the universe (so 40% of them are not listed), null-heavy, noised
  with the simulation table at half its rates, many parties in several claims (unmerged
  duplicates), grouped into claims and notes.
* **Edge cases**: ~45 hand-written cases with the expected best watchlist row, basis, veto
  and levels, listed in the table `EDGE_CASES`.

Truth is written beside the inputs and read only by diagnostics and self-tests, never by the
pipeline (AGENTS rule 13).

**Where Splink would do better.** Splink ships labelled demo datasets (febrl, historical
persons) with known truth; they are real benchmarks. This set is ours and shaped by our own
noise table, so results on it show that the code does what it says, not how well it would do
on client data.