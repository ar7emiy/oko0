# Application screenshot provenance

The three PNGs were captured on 2026-09-14 from the running Gold Annotator through
its headless Edge/CDP browser test workflow, using a fresh temporary database and
the bundled fictional practice data. No user annotations or client data were used.

- `01-live-detail.png`: after choosing Northstar as the TIN owner, before Save.
- `02-live-claim-review.png`: the claim dossier before required entity reviews.
- `03-live-comparison.png`: comparison completed, with export available.

Lettered outlines and explanatory cards were injected as a temporary SVG layer
over the live page immediately before capture. Underlying controls, text and
application state were retained; notifications were allowed to expire. No image
generation, reconstructed interface or image retouching was used.

Capture used a temporary copy of `gold-annotator/tests/e2e/ui_flow.mjs` with capture
hooks at the states above. All 35 browser checks passed. The temporary script was
removed, and the application and permanent test sources were not changed. Captures
were visually inspected at 1440 × 900. Application source was the version present
at repository commit `9475657` (the intervening proposal changes were documentation).

These screens show the current development interface, including its existing
terminology. They do not show delivery of proposed unassigned-detail or expanded
identifier support. The former conceptual SVGs were removed, including the
redundant evidence-to-metrics illustration in section 4.
