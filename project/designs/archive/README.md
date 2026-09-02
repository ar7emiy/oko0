# Archived design mockups

Six of the eight original `designs/*.html` mockups, moved here because each is
superseded by something that actually exists now. Kept via `git mv` rather than
deleted, so history and content are still reachable.

| file | superseded by | why |
|---|---|---|
| `architecture.html` | `../../ARCHITECTURE.md` | Early v0 mockup. The markdown doc carries the real, measured architecture — this described a version of the system before Layers 1-4, Splink, or the embedding lane existed. |
| `dossier.html` | `src/profiles.py` + `app.export_dossier_html()` | The mockup's design was implemented for real. `export_dossier_html()` produces the actual clickable-evidence dossier from live data; the mockup is now a picture of something that exists. |
| `annotation-guidelines.html` | `src/corpus_gen.py` | Described a human-SME-annotates-real-notes-via-spreadsheet workflow. That approach was replaced by a deterministic synthetic generator that plants its own sealed ground truth with exact character offsets — no human annotation step exists in the pipeline any more. |
| `data-scientist-manual.html` | `README.md`, `ARCHITECTURE.md`, `DECISIONS.md` | Onboarding doc for the same human-annotation-era workflow above. |
| `ground-truth-plan.html` | `src/corpus_gen.py` | Sprint plan for building the human-annotation ground truth. Ground truth is now generated, not annotated. |
| `ground-truth-timeline.html` | `src/corpus_gen.py` | Same era, a timeline for the same superseded plan. |

**Still live in `designs/`:**
- `qa-viewer-mockup.html` — the design `src/qa_viewer.py` implements; referenced directly from the root `README.md`.
- `pipeline-activity-diagrams.html` — actively maintained, most recently updated alongside the embedding-blocking-lane work.
