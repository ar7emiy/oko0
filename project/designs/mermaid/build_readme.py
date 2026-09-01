#!/usr/bin/env python3
"""Regenerate README.md from the .mermaid sources.

The .mermaid files are the source of truth. GitHub renders mermaid only inside
fenced code blocks in Markdown, not standalone .mermaid files, so README.md
embeds a generated copy of each one. Run this after editing any diagram:

    python3 designs/mermaid/build_readme.py
"""
import pathlib

HERE = pathlib.Path(__file__).parent

PREAMBLE = """# Pipeline activity diagrams — mermaid sources

Mermaid versions of the UML activity diagrams in
[`../pipeline-activity-diagrams.html`](../pipeline-activity-diagrams.html), which
remains the fuller companion: it carries the per-stage goal statements, the
worked-example tables in full, and the `entity_class` design discussion that has
no diagram.

These show the *process* — what happens to a document as it moves through the
pipeline. For the *data model* — what tables exist and how they relate — see
[`erd/`](erd/README.md).

Each `.mermaid` file here is standalone and is the source of truth. The blocks
below are generated copies so they render on GitHub — regenerate with
`python3 build_readme.py` after editing any diagram.

## Reading these

| shape | meaning |
|---|---|
| stadium, dark fill | initial / final node |
| rectangle, grey fill | activity — something happens |
| rectangle, blue fill | object node — data at rest |
| diamond | decision |
| dark bar | fork / join |
| rectangle, red fill | data discarded here |
| rectangle, amber fill | a path worth noticing |
| dashed box, dotted edge | worked data example, or a design caveat |
| **green, thick dashed** | **PROPOSED — designed, not built.** Shown at the point in the flow where it would land, so it can be reviewed in place. |
| purple, dashed | `src/research/` — corpus-fitted, unimported by the pipeline, entered only by naming it |

## Proposed changes currently on the board

Both are drawn into the diagram at their insertion point rather than described
separately, so the review question is "does this belong here?" and not "where
would this go?".

| # | change | where | status |
|---|---|---|---|
| 1 | Split `entity_class` into a closed `entity_type` (person / organization) and an **open** `role` defaulting to `NULL` | [diagram 06](06-filter-classify-persist.mermaid), replacing the *Classify entity_class* node | designed, not built |
| 2 | Normalize the mention surface (strip leading role/title tokens) before deriving ER blocking keys | [diagram 07](07-entity-resolution.mermaid), inserted between *build_mention_frame* and *derive blocking keys* | designed, not built |

Proposal 1 fixes a live defect: `_classify` falls back to
`LABEL_TO_CLASS.get(label, "claimant")`, so an unmatched person is silently
stored as a claimant and an unmatched organization as a medical provider — a
guess written into a field readers treat as a fact.

Proposal 2 is backed by measurement rather than intuition: on this machine
GLiNER's recall was identical across casing regimes (9/9 mixed, ALL CAPS and
lowercase), but exact span-boundary agreement was only 24/31 = 77%, and the
disagreements were leading role words (`adjuster Karen Wu` vs `Karen Wu`).
Role-word absorption happens in mixed case too, so it is not a casing bug.

Two notational compromises, since Mermaid's flowchart grammar is not UML:

- **Fork and join bars** are drawn as labelled dark nodes rather than the thin
  UML synchronisation bar, which the grammar has no shape for. `stateDiagram-v2`
  does provide a real `<<fork>>`, but gives up the decision diamond, the object
  node, and multi-line labels — a bad trade for diagrams whose whole point is the
  per-node data examples.
- **Data examples** hang off their activity as dashed notes on a dotted edge,
  rather than sitting in a table beside the figure as they do in the HTML.

Every diagram in this folder is checked to parse and render with mermaid 11.

## Diagrams

"""

ORDER = sorted(p for p in HERE.glob("*.mermaid"))

TITLES = {}
for p in ORDER:
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("title:"):
            TITLES[p.name] = line.split(":", 1)[1].strip().strip('"')
            break

out = [PREAMBLE]
for p in ORDER:
    out.append(f"### {TITLES.get(p.name, p.stem)}\n")
    out.append(f"Source: [`{p.name}`]({p.name})\n")
    out.append("```mermaid\n" + p.read_text(encoding="utf-8").rstrip() + "\n```\n")

(HERE / "README.md").write_text("\n".join(out), encoding="utf-8")
print(f"README.md written from {len(ORDER)} sources")
