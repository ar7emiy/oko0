## Noise engine

Noisy copies of input rows, driven by `mappings/simulation_noise.csv` (a pessimistic table,
for review). The same engine makes the simulated true-match pairs for m (step 10), the
synthetic extracted rows and the LEIE test set. Each copy records which noises hit it.

**Where Splink would do better.** Splink has no simulator; its answer to missing labels is
EM plus the user's own labels. Simulation here is a last-resort source of m and is flagged
as such wherever it is used.