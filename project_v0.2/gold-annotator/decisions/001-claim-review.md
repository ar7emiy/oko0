# Claim evidence review before firm comparison

User need: judge each entity using the complete claim, without showing the firm's category first.

Permitted decision: after note annotation, an SME records a broad claim-role category, insufficient evidence, or conflicting evidence. Each decision records a rationale and supporting, conflicting, or repeated evidence references. Repetition is not independent corroboration.

Dependencies: entity identity, exact record revisions, source fingerprints and a versioned taxonomy independent of firm exports. A changed entity/evidence basis requires renewed review. A final checkpoint captures all entities, records, decisions and source fingerprints atomically before firm comparison opens.

Unresolved outcome: insufficient/conflicting evidence is explicitly reviewable and excluded from category accuracy, with coverage reported. Unassigned references remain visible at claim review.

Dossier effect: show each sourced record under its original note, including actions and the second participant. Source navigation never copies or moves a record. Existing annotation editing corrects ownership with revision history.

Reverse: revise decisions before freezing; prior decision revisions remain. After freezing, later annotation corrections do not rewrite the evaluated snapshot. Previously exposed legacy claims cannot acquire an independent checkpoint retrospectively. No automatic taxonomy classifier, external lookup or entity merge is enabled.
