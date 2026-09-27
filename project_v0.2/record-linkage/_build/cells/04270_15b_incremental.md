## 15b · Incremental runs on Delta (B1.1)

With `INCREMENTAL = True` (Delta only), a run scores only what changed since the last run:

1. **State.** Every Delta run appends a row to `rl_run_state`: the run id, the extracted and
   watchlist tables and their exact versions, and the model id. The trained model (both
   models' weights, priors, name components) is saved in `rl_model`.
2. **What changed.** The extracted table's **change data feed** from the saved version + 1 to
   the current version lists the inserted, updated and deleted `record_id`s; if the feed is
   not enabled on the input table, the two versions are compared row by row (version diff).
   A changed watchlist version, a missing state or model, or `delta_full_refresh` makes the
   run a full one.
3. **What is re-scored.** Normalization, deduplication and clustering always run on the whole
   extracted table (they are cheap next to linking, and a new row may join an old entity).
   Linking against the watchlist, the expensive step, runs only for entities whose
   *signature* is new: a hash of the model id, every member row's content, how many holders
   each of the member's identifier values has, and (persons) the signatures of the tied
   businesses. Every other entity's scored pairs come from `rl_link_cache`.
4. **MERGE.** The output tables are merged on their keys: rows whose content changed are
   updated, new rows inserted, rows no longer produced deleted; everything else is untouched,
   and Delta's history keeps every earlier version.

With the same model, an incremental run produces the same tables as a full run on the new
snapshot (a self-test checks this). Statistics that span the whole extracted file (value
frequencies behind the deduplication model's u) move slowly as rows arrive; a periodic
`delta_full_refresh` re-estimates everything.

**Where Splink would do better.** Splink has no incremental mode of its own; its
`find_matches_to_new_records` scores new records against an existing linked set with a saved
model, which is the same idea as reusing `rl_model` here. Splink would do the re-scoring as
Spark SQL over only the new rows, without loading the whole extracted table on the driver.
