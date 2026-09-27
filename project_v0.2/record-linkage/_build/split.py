"""One-time: split record_linkage.ipynb into ordered cell files (cells/NNNNN_*.py|.md)."""
import json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
nb = json.loads((HERE.parent / "record_linkage.ipynb").read_text(encoding="utf-8"))
out = HERE / "cells"
out.mkdir(exist_ok=True)
for i, c in enumerate(nb["cells"]):
    src = "".join(c["source"])
    first = src.strip().splitlines()[0] if src.strip() else "empty"
    slug = re.sub(r"[^a-z0-9]+", "_", first.lower()).strip("_")[:40]
    ext = "md" if c["cell_type"] == "markdown" else "py"
    (out / f"{(i + 1) * 100:05d}_{slug}.{ext}").write_text(src, encoding="utf-8", newline="\n")
print(len(nb["cells"]))
