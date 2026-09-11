# Undo annotation changes

Need: recover from accidental saved annotations without erasing history.
Decision: Ctrl+Z or Undo reverses the latest undoable annotation operation for
the current reviewer, including AI accept/dismiss as a single operation.
Dependencies: durable before/after deltas for entities, record revisions,
draft states and run keys. Inverses append record revisions and retain entity IDs.
Unresolved: reject stale state, changed source or broken dependencies rather than
silently undoing different work. The prior frozen answer key never changes.
Reversal: create/edit/delete compensating records; reopen affected note completion
when needed. Undo itself is audited and is not placed back on the undo stack.
Text fields keep browser-native text undo. Claim freezing and firm exposure are
not reversible. Existing pre-upgrade history supports recovery of the last manual
record change or newly created entity when its prior state can be reconstructed.
