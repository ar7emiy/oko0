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
    for line in p.read_text().splitlines():
        if line.startswith("title:"):
            TITLES[p.name] = line.split(":", 1)[1].strip().strip('"')
            break

out = [PREAMBLE]
for p in ORDER:
    out.append(f"### {TITLES.get(p.name, p.stem)}\n")
    out.append(f"Source: [`{p.name}`]({p.name})\n")
    out.append("```mermaid\n" + p.read_text().rstrip() + "\n```\n")

(HERE / "README.md").write_text("\n".join(out))
print(f"README.md written from {len(ORDER)} sources")
