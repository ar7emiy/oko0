"""Assemble cells/*.py|*.md (sorted by file name) into ../record_linkage.ipynb, outputs cleared.

    python assemble.py            # write the notebook
    python assemble.py --script   # also write notebook_as_script.py (every code cell, in order)
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cells():
    for p in sorted((HERE / "cells").iterdir()):
        if p.suffix in (".py", ".md"):
            yield p, p.read_text(encoding="utf-8")


def main():
    nb_cells, script = [], []
    for p, src in cells():
        src = src.rstrip("\n")
        lines = src.split("\n")
        source = [l + "\n" for l in lines[:-1]] + [lines[-1]]
        if p.suffix == ".md":
            nb_cells.append({"cell_type": "markdown", "metadata": {}, "source": source})
        else:
            nb_cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                             "source": source})
            script.append(f"# ==== {p.name} ====\n{src}\n")
    nb = {"cells": nb_cells,
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    (HERE.parent / "record_linkage.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                                                      encoding="utf-8", newline="\n")
    if "--script" in sys.argv:
        (HERE / "notebook_as_script.py").write_text("\n".join(script), encoding="utf-8", newline="\n")
    print(f"{len(nb_cells)} cells assembled")


if __name__ == "__main__":
    main()
