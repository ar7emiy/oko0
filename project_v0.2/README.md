# General entity intelligence over unstructured text

The general-first redesign: preserve source text, propose interpretations, make resolution
decisions visible and reversible, and produce evidence-backed dossiers. Claim notes are the
initial evaluation domain, not the core ontology.

This folder holds two working systems and the documents that govern them.

## Layout

```text
goko-v2-poc/        the extraction and identity pipeline (goko_v2_poc.ipynb), its search
                    app (app/), test corpora, outside reference data, and evaluation
gold-annotator/     the SME review platform that produces independently annotated gold data
AGENTS.md           implementation rules and controls
CLAUDE.md           points to AGENTS.md
ARCHITECTURE.md     authoritative working design
STATE.md            status log
ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md   how quality is measured (the benchmark)
GOKO-SYSTEM-DEVELOPMENT-PROPOSAL.md          what to build so the measurements improve
ADO-BACKLOG.md      work items traced to the proposal's requirements
assets/             images used by the proposals
```

Read in this order: [ARCHITECTURE.md](ARCHITECTURE.md), [AGENTS.md](AGENTS.md), then the
README of whichever system you are working on: [goko-v2-poc](goko-v2-poc/README.md) or
[gold-annotator](gold-annotator/README.md).

## History

Earlier attempts are kept in [`../archive/`](../archive/): `project/` and `project_v0.1/`,
the Excel and desktop annotators that preceded the gold-annotator web app
(`project_v0.2/python-annotator`, `offline-annotator`, `offline-python-annotator`), and the
design studies, including the Excel tutorial (`project_v0.2/designs/`). The gold-annotator's
test packets moved from the archived Excel annotator to `gold-annotator/sample-data/`.

## Initial input

UTF-8 text with a stable source-document ID and optional metadata. Changed content creates a
source version. Claim, conversation, or collection membership is optional context. Existing
entity records and watchlists are evaluation aids or application inputs; neither is
automatically authoritative truth.

## Design and evaluation are separate

The architecture does not inherit earlier accuracy metrics or thresholds. The evaluation
plans define a new, independently reviewed reference dataset and explicit measures for later
testing. A claim-note benchmark will establish behavior on that domain only; it cannot
establish generality across all unstructured text.
