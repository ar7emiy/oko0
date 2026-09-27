## 4 · Value index

For every (type, value): how many parties hold it in each file, how many distinct names hold
it, whether one name holds it (single-holder: the only kind that can veto or anchor), and
whether it is junk (fails validation, or is held under more than `junk_holders` names). It
drives shared-identifier counts, anchors, per-value u and the row-level evidence. Junk values
are blanked from the party frames before any comparison and listed in the manifest.

**Where Splink would do better.** Splink computes term frequencies per column in SQL and
joins them onto pairs; the idea is the same, and Splink's version is lazier with memory.