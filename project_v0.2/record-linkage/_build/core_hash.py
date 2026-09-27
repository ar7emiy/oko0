"""Print the matching-core hash of ../record_linkage.ipynb (same algorithm as the self-test)."""
import hashlib, json, sys
from pathlib import Path

NL, CR = chr(10), chr(13)
nb_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "record_linkage.ipynb"
nb = json.loads(nb_path.read_text(encoding="utf-8"))
inside, parts = False, []
for c in nb["cells"]:
    src = "".join(c["source"])
    if c["cell_type"] == "markdown" and src.startswith("## Matching core v"):
        inside = True
        continue
    if c["cell_type"] == "markdown" and src.strip().startswith("*End of the matching core.*"):
        break
    if inside and c["cell_type"] == "code":
        parts.append(NL.join(l.rstrip() for l in src.replace(CR + NL, NL).split(NL)))
print(hashlib.sha256((NL + "# ---- cell ----" + NL).join(parts).encode("utf-8")).hexdigest())
