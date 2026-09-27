## 7 · Candidates

Only extracted × watchlist pairs of the same part type are ever proposed. The union of these
rules, each pair remembering which rules proposed it:

| Part | Rules |
|---|---|
| Person | exact SSN, provider NPI, DL (state:number), licence (state:number), email, VIN, plate; any phone; NYSIIS(last) + first initial; NYSIIS(last) + canonical first initial (Bill meets William); exact DOB + first initial (a surname change); swapped first/last; sorted neighbourhood on "last first" (window 5) |
| Business | exact TIN, clinic NPI, email, work phone; rarest word of each alias (d/b/a included); leading word + state; sorted neighbourhood on the sorted-word name |

**Before indexing**, every rule's pair count is computed from key counts on both sides and
printed. A key that would propose more than `block_pair_cap` pairs is refined with the state;
a refined key still over the cap is dropped and listed in the manifest with its pair count
(an unresolved outcome, never a silent loss). Keys shared by more than the cap in the sorted
neighbourhood are left to the refined blocks. Indexing runs in chunks of `chunk_size`
extracted parties through `recordlinkage.Index` (`Block`, `SortedNeighbourhood` with the
global sorting-key values, so a chunked run proposes exactly the pairs of an unchunked one).

**Where Splink would do better.** Splink's blocking runs as SQL joins in DuckDB, parallel
and out of core, and its `cumulative_comparisons_to_be_scored_from_blocking_rules_chart`
shows each rule's marginal pairs. recordlinkage's `Block` is a pandas merge per chunk.