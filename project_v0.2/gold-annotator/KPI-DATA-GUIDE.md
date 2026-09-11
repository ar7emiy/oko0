# Where the KPI numbers come from

The app evaluates **the firm's imported CSV or Excel workbook against this reviewer's saved answer
key**, using the reviewer's pairing and watchlist answers. It does not call an
extraction model, query an outside dataset, or run RapidFuzz.

With no `--notes` or `--firm` arguments, the inputs are the bundled fictional
practice notes and `annotator/practice/PRACTICE_firm.csv`. Practice scores describe
that exercise only. Real evaluation needs your UTF-8 note packet and the firm's
matching export, supplied at startup. Practice results establish no real-data accuracy.

## Input datasets

1. **Source notes:** supplied `.txt` files. Saved annotations retain exact quotes,
   positions and note IDs. Source files remain external; hashes detect changes.
2. **SME answer key:** entities, mentions, details, descriptions and actions in
   SQLite. Claim review freezes these revisions and independent category decisions.
   Later edits do not replace that evaluated version. Legacy exposed claims use
   current annotations and cannot contribute independent category labels.
3. **Firm output:** the CSV or XLSX passed with `--firm`, containing extracted names,
   categories, details, watchlist flags, method indicators and similarity scores.
   The app reads the firm's similarity score; it does not recalculate it.
4. **Review decisions:** firm-row-to-gold-entity pairing (or not in notes), and
   watchlist same/different/cannot-tell decisions, with note support and reasons.

## Main calculations

These use sealed claim answer keys for the selected reviewer. Practice is excluded
unless explicitly included. Pending firm rows are excluded from row metrics. Until
**Finish comparison** succeeds on every scored claim, scores are provisional:
incomplete pairing can look like missed entities. Zero denominators mean unavailable,
not 0% accuracy. Every score includes its actual numerator and denominator.

| Metric | Numerator / denominator |
|---|---|
| Found rate | Distinct paired gold entities / all gold entities in the selected answer keys |
| Right rate | Firm rows paired to gold / firm rows with pairing or not-in-notes decisions |
| Detail accuracy | Reported values present in gold under the same detail kind, anywhere in the claim / reported details on decided firm rows |
| Right-owner rate | Those matching values on the paired entity / all matching values above |
| Missed-detail rate | Distinct gold entity/kind/value combinations without the matching value on a paired firm row / all distinct gold entity/kind/value combinations |
| Unsupported-value rate (`made_up_rate`) | Reported values absent from gold for that detail kind throughout the claim / reported details on decided rows |
| Person/organization tag | Paired rows whose firm type matches gold / paired rows with comparable types |
| Category accuracy | Paired rows matching an assigned frozen category / paired rows with an assigned frozen category |
| Category coverage | Paired rows with assigned frozen categories / all paired rows; unresolved and legacy labels are excluded from accuracy |
| Watchlist accuracy by method | Same / (same + different), grouped by imported Exact/GenAI indicators; cannot-tell is reported separately |
| Cannot-tell rate | Cannot-tell watchlist decisions / all watchlist decisions |
| Similarity bins | Same / (same + different) within imported GenAI bins below 75, 75–84, 85–94 and 95–100 |

The compared detail kinds are address, city, state, ZIP, phone and TIN. Values are
trimmed and case-folded; whitespace is normalized. Phone/TIN/ZIP separators are
removed while leading zeros remain. Categories are compared after trimming and
case-folding; the study taxonomy must be aligned with the firm's category meanings.

Unsupported means **absent from the recorded gold**, not proven fabrication: an
SME could have missed the evidence. Repeated evidence does not multiply the unique
gold-detail denominator. Wrong-category counts do not establish blocked watchlist
comparisons or missed real matches; those require additional firm/watchlist inputs.

## Other diagnostics

These are not independent firm-vs-gold accuracy and can include unfinished notes:

- **Draft acceptance:** accepted / (accepted + dismissed), from pasted AI drafts.
  The API's historical key is `draft_precision`; edited drafts count as accepted.
- **Correction rate:** edited accepted drafts / accepted drafts.
- **Manual-addition share:** manual current records on notes with AI drafts / all
  current records on those notes. Historical key: `miss_rate`. This is not recall;
  manual annotations may predate the AI run.
- **Reviewer overlap:** shared exact (kind, start, end, detail-field) tuples /
  their union for two reviewers on one note. It does not measure agreement on
  entity identity, ownership or categories, and is not chance-corrected agreement.

## Three analysis tables

| File | Row meaning |
|---|---|
| `entity_comparison.csv` | One firm row, plus each gold entity with no paired firm row; includes gold category, detail list, firm fields, pairing and watchlist answers |
| `evidence.csv` | One annotation from the selected answer-key version, with exact source, positions, entity links and category evidence roles |
| `kpi_summary.csv` | One metric/group for a reviewer and scope, with numerator, denominator, provisional status and completion counts |

Join on `reviewer, claim, entity_id`; `entity2_id` identifies a second participant.
Multiple firm rows may link to one entity: count distinct entity IDs for entity
denominators, not repeated joined rows. A `gold_only` row is not a confirmed miss
while comparison is incomplete. Keep `is_practice` and `answer_key_basis` in your
filters. Import IDs/TIN/ZIP as text. JSON cells hold one-to-many detail/evidence
lists without duplicating the main row.

Exports contain only the current reviewer's work. The optional detailed format
retains audit tables, current annotations, frozen checkpoints and raw AI replies.
When pooling compatible results, sum numerators and denominators; do not average
percentages or mix fictional practice with real claims.

Note IDs are not globally unique annotation keys: use `(claim, note)` when joining
note evidence. A shared note can appear in several claims, with separate SME work.
Firm citation cells retain their comma-separated values and Excel `.0` artifacts;
split and normalize those IDs before joining. Missing citations must not fall back
to another claim. Keep shared source notes in the same train/test partition if
these exports are later used for modeling; this app does not create those splits.
