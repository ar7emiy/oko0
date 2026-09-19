# Proposed identifier capture and unassigned-detail support

Status: requirements only, 2026-09-14. **No application code changed.**

Client-facing context: [Entity Intelligence evaluation benchmark and SME review platform proposal](../ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md), especially Part 2 sections 2.1, 3 and 4. Section 3 now shows annotated captures of the running application with fictional practice data; these do not depict delivery of the requirements below. UX review with SMEs should establish a simpler interaction sequence before implementation.

## Current implementation findings

| Requirement | Verified current behavior | Gap |
|---|---|---|
| Typed unique identifiers | `static/app.js` defines TIN and Other identifier alongside address/phone fields. `annotator/store.py` validates against `DETAIL_FIELDS`; `annotator/ai_import.py` has its own detail aliases. | SSN, NPI, Attorney Bar number and VIN are not distinct structured choices. Other identifier can preserve an owned value but does not provide its scheme, issuer/jurisdiction or partial-value status as structured information. |
| Details without an owner | The form validator requires an entity for Detail; `Store.validate` rejects ownerless detail submissions. A nullable database field does not override those rules. | The app cannot save a structured, typed unassigned detail through the supported workflow. |
| Preserve uncertainty | Unclear accepts a passage and reason with no required owner. For non-detail kinds, validation clears structured detail type/value. | Unclear is not a substitute for a typed unassigned address or identifier, even though it preserves the words. |
| Scoring expanded types | `annotator/firm.py` maps six detail kinds; `annotator/scoring.py` uses these in the common comparison. | New identifier types and unassigned details must not enter existing totals merely because capture becomes possible. |

## Proposed capture requirements

Support SSN, TIN, NPI, Attorney Bar number, VIN, and Other with a required descriptive scheme name. Preserve the source quote, original string value, claim/note/version, reviewer and revision. Keep leading zeros; support masked or partial values explicitly. Store issuer/jurisdiction and time qualifications where relevant. Any normalized value needs a named normalization version and must not replace the original. Format validity is not proof of ownership or identity.

The current entity model is oriented toward people, organizations and locations. VIN ownership requires a reviewed subject model that can represent a vehicle, or an explicit relation to the relevant vehicle; it must not force a VIN onto an arbitrary person. Typed identifiers must be reflected consistently in manual capture, optional draft parsing, validation, dossier views and exports. No existing TIN or Other data should be silently reclassified during an eventual migration.

## Proposed unassigned-detail requirements

Capture the detail before ownership is known. Provide an explicit **Owner not established** choice and allow saving when no claim entity exists. Preserve the detail type and value, source evidence and a reason. Surface a claim-level unassigned-details collection and an entity/item review path. A later ownership assignment appends a decision; reversing it preserves the initial capture and earlier decisions.

Keep absence of ownership distinct from rejected or disputed ownership. An assigned detail must reference an entity in the appropriate claim. Cross-claim identity review must not silently transfer a source fact to another claim. If several owners are supported, preserve the separate attribution decisions and evidence rather than relying on a single overwritten owner field.

Retain unassigned details in exports but **exclude them from all initial benchmark calculations** in the proposal. Report the excluded population. GOKO details that cannot be judged because the reference ownership is unresolved are set aside with a reason rather than automatically scored unsupported. A future owner-independent capture or ownership-resolution evaluation needs a separately approved scope, reference labels and denominators. SSN/NPI/Bar/VIN comparison also requires equivalent GOKO information and agreed rules.

## Affected implementation areas for a future change

- `static/app.js`: field choices, selection actions that currently require an entity, form validation, optional-owner controls and unresolved-detail navigation.
- `annotator/store.py`: validation, ownership decision history and compatibility with existing records.
- `annotator/ai_import.py` and Copilot instructions: identifier aliases, typed output and acceptance of proposed details with unknown owners.
- `annotator/review.py` and completion rules: preserve typed unassigned details during claim review/freeze without requiring fabricated ownership.
- `annotator/undo.py`: restore ownership status and typed value as one consistent action.
- `annotator/export.py` and `analysis_tables.py`: typed identifier context, unassigned details, evidence associations, review status and explicit benchmark exclusion.
- `annotator/scoring.py`: approved scope and exclusions; no automatic expansion of existing denominators.

## Acceptance scenarios for implementation review

1. A note contains only an address. An SME saves a Street address with no owner, then finds the typed value and source in the claim review and export.
2. A later note establishes its owner. The SME assigns it without rewriting the source or losing the earlier unassigned decision; Undo restores the unassigned state.
3. Each identifier type survives manual entry, optional draft review and export with its exact original characters, including leading zeros and masking.
4. A bar number retains its jurisdiction; a VIN is not misrepresented as a person-level identifier. Same values do not automatically merge entities.
5. Repeated evidence passages remain available while one reviewed entity/detail/value statement receives one gold-fact count.
6. Unassigned details and unsupported benchmark identifier types are exportable but do not alter initial benchmark totals. Exclusions remain visible.

These scenarios are proposed checks, not tests claimed to have passed.
