## 18 · Review sample (later phase: not built)

This section is a skeleton. The plan's milestone M6 adds:

1. **Blind stratified sample.** From the candidates sheet, strata by basis x p band x prior group,
   a fixed number per stratum, drawn with the run seed; the reviewer's sheet shows both records
   side by side without p, basis or bits.
2. **Labels read back** from `review/` (gitignored) with openpyxl: match / not a match / cannot
   tell, with a reason.
3. **Metrics**: precision per stratum and overall with the stratum weights, recall against the
   labelled matches that the candidates reached, and a calibration table (predicted p vs
   observed share) with explicit denominators (AGENTS rule 12).

Labels are never read by the pipeline (AGENTS rule 13): they measure it, they do not tune it.

**Where Splink would do better.** Splink can take labels as a table and plot ROC and
precision-recall curves and threshold selection charts from them directly.
