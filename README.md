# oko0 — Entity Intelligence

Claim-note entity intelligence: extracting the people and organizations in insurance claim notes, resolving their identities, matching them against a watchlist — and measuring how well any of that actually works.

This file is the map. The repository accumulated three generations of work across parallel agent workflows, and without this you cannot tell which directory is current.

---

## Where things stand

| Directory | What it is | Status |
|---|---|---|
| **`project_v0.2/`** | Current. The Gold Annotator (the SME review application) plus the four proposal documents. | **Active** |
| **`project_v0.1/`** | A first-principles rebuild scaffold. Identity layer designed, no pipeline runs. | Superseded by v0.2's direction; retained for its design record |
| **`project/`** | The original full extraction system — NER ensemble, coreference, blocking, entity resolution, relations, embeddings, graph store — plus the audits that assessed it. | **Not current, but the most technically substantial code here.** See below |

**Start here:**

- Measuring quality → [`project_v0.2/ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md`](project_v0.2/ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md)
- Improving the extraction system → [`project_v0.2/GOKO-SYSTEM-DEVELOPMENT-PROPOSAL.md`](project_v0.2/GOKO-SYSTEM-DEVELOPMENT-PROPOSAL.md)
- Delivery work items → [`project_v0.2/ADO-BACKLOG.md`](project_v0.2/ADO-BACKLOG.md)
- The annotator itself → [`project_v0.2/gold-annotator/README.md`](project_v0.2/gold-annotator/README.md)

---

## How this repository got its shape

The sequence matters, because the current direction is a reaction to what came before.

**1. Build the system.** `project/` is a full extraction pipeline: chunking, an NER ensemble, coreference, blocking, entity resolution, relation extraction, an embedding index, a graph store, leakage guards, ablation tooling. It works and it is substantial.

**2. Audit it.** `project/designs/audits/` and `project/designs/full-system-architecture-audit.md` examined it against real data rather than fixtures. The finding was that the system had been **over-engineered relative to first principles** — capability had been added faster than the problem had been characterised.

**3. Rebuild from first principles.** [`project/designs/rebuild-from-first-principles.md`](project/designs/rebuild-from-first-principles.md) restates the problem from the ground up: what is irreducible, what the measurements force, what the design deliberately does *not* have, and — in its section 8 — what survives from the current system. `project_v0.1/` is the scaffold that came out of it.

**4. Discover the measurement gap.** The rebuild surfaced the harder problem: **nobody could say how well any version performed.** There was no answer key, so no version could be compared with any other. That reframed the priority.

**5. Build the means to measure.** `project_v0.2/` is the result — the Gold Annotator, which lets subject-matter experts build an independent answer key, plus the proposals that define the benchmark, the system roadmap and the delivery backlog.

The thread through all five steps: **capability outran measurement, so the correction was to build the measurement.**

---

## Branches

`main` is the current line of work. Two unrelated commit histories exist in this repository — an artifact of parallel agent workflows that were not coordinated, not a deliberate fork.

| Branch | History | Relationship to `main` |
|---|---|---|
| `main` | Root `914b63b` | Current |
| `codex/first_principles_rebuild` | Root `914b63b` | Identical to `main` |
| `claude/excel-workbench-completion` | Root `914b63b` | Ancestor of `main` — fully contained |
| `audit-full-system-architecture` | Root `914b63b` | Ancestor of `main` — fully contained |
| `claude/entity-intelligence-claims-poc-me1i6c` | Root `44688cd` | **Unrelated history.** Content fully contained in `main` |
| `audit-first-principles-claim-note-review` | Root `44688cd` | **Unrelated history.** Content fully contained in `main` |

**No work is stranded.** Comparing the tip of the unrelated history against `main` gives 386 files added and 29 modified, with **zero deletions** — every file on that line exists on `main`, and every one of the 29 shared files is larger and later on `main`. The two histories diverge only in commit lineage, not in content.

Safe to delete once confirmed: the two ancestor branches, and the two unrelated-history branches (tag them first if the commit history is worth keeping). `claude/entity-intelligence-claims-poc-me1i6c` was the repository default before `main` existed, so update the default branch setting before removing it.

---

## What to do with `project/`

This is the open question, and it deserves a decision rather than drift.

`project/src/` contains prototype implementations of most stages the current system roadmap proposes building:

| Roadmap stage (GOKO proposal §5) | Existing module |
|---|---|
| S1 Segmentation | `chunking.py` |
| S2 Candidate detection | `ner_ensemble.py` (498 lines) |
| S4 Within-note coreference | `coref.py` (252 lines) |
| S6/S7 Entity resolution | `blocking.py` (374), `entity_resolution.py` (1,275) |
| Relations and participants | `relations.py` (607) |
| Retrieval | `embed_index.py` |
| Held-out discipline | `leakage_guard.py` |
| Comparative evaluation | `ablation.py`, `profiles.py` |

**This overlap has not been reconciled.** The system development proposal describes the current production architecture as it was related in discovery, and proposes a staged pipeline from scratch. It was written without reference to this code. So there are two possibilities, and only engineering can say which:

1. These modules are a working head start on the proposed pipeline, and the roadmap should be re-scoped around what already exists.
2. These modules are exactly the over-engineering the audit identified, and the roadmap is right to start from the measurement instead.

The honest answer is likely "some of each, module by module." **The reconciliation task is to walk `project/src/` against the roadmap's nine stages and mark each module keep / rebuild / discard, with a reason.** Until that is done, the roadmap may be proposing work that is already sitting in this repository.

Section 8 of [`rebuild-from-first-principles.md`](project/designs/rebuild-from-first-principles.md) — "what survives from the current system" — is the right starting point, since it asked a version of this question already.
