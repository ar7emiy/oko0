# Explicit comparison completion and analysis exports

User need: reviewers need a visible end to firm/watchlist comparison and usable
practice exports; data scientists need a small set of joinable tables.

Permitted decision: a reviewer confirms comparison after every firm row has a
pairing or not-in-notes answer and each flagged row has a watchlist decision,
note-support answer and reason. Cannot-tell remains a valid unresolved outcome.

Dependencies: completion retains a fingerprint of firm rows and saved answers.
Changing these invalidates completion. The frozen independent answer key remains
unchanged. Incomplete comparisons are labeled provisional, not silently final.

Dossier effect: none. Analysis tables project the frozen version when available,
label legacy/current versions and preserve exact evidence and source hashes.
Practice inclusion is explicit and marked; it never establishes real accuracy.

Reversal: edit a comparison answer to reopen completion. Select detailed export
to retain the prior audit-table layout. Uncheck practice to return to real scope.
