## 16a · Baseline: the current method (switch `baseline`, default off)

A replica of the method in use today, so the self-checks can show it beside B1 on the same
truth:

1. **Name.** Each party's entity name is cleaned: lowercase, punctuation removed, legal
   suffixes (INC, LLC, PC, ...) and titles or credentials (DR, MD, JR, ...) dropped. A person's
   name is first + last as parsed (middle only with `baseline_include_middle`), a business's
   name as written.
2. **Candidates gated by category.** The extracted file's `category` column (the AI-assigned
   category) must equal the watchlist category, which is inferred from specialty and licence
   type (section 5). A pair with a missing category is blocked (`baseline_gate_missing =
   "block"`) or let through (`"pass"`).
3. **Match** when rapidfuzz `token_sort_ratio` of the two cleaned names is at least
   `baseline_threshold` (90). No identifiers, no other field, no probability.

**Assumed defaults.** Threshold 90, the cleaning above, first + last for persons and "block"
for missing categories are this build's assumptions, marked as such in the manifest, until the
user supplies the real settings.

When the switch is on, the held-out identifier check and the noise test report the baseline
beside B1, split the baseline's lost true pairs into *blocked by the category gate* and *name
too different*, and write a disagreement report: false alarms B1 avoids, matches B1 recovers
(and the reverse), and how many watchlist rows each extracted name hits (ambiguity), each row
with B1's decision card (field, level and bits).

**Where Splink would do better.** Nowhere specific: this is the user's method, reproduced
for comparison. Splink's closest counterpart would be a single-comparison model with a
deterministic rule; it would add nothing here.
