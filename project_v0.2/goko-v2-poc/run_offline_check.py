#!/usr/bin/env python3
"""Execute every code cell of goko_v2_poc.ipynb in order, in OFFLINE_MODE.

This is the notebook's regression test: it proves the cells run top to bottom without a
deployment, and cell 23's self-tests raise if any pipeline invariant is broken. Exit code
is non-zero if any cell raises.

    python3 run_offline_check.py [notebook.ipynb]
"""
import io, json, sys, traceback
from contextlib import redirect_stdout
from pathlib import Path

args  = [a for a in sys.argv[1:] if not a.startswith("-")]
QUIET = "--quiet" in sys.argv
NB    = Path(args[0] if args else "goko_v2_poc.ipynb")

nb = json.loads(NB.read_text())
g = {"__name__": "__main__"}
failures = []

for i, cell in enumerate(nb["cells"]):
    if cell["cell_type"] != "code":
        continue
    src = "".join(cell["source"])
    buf = io.StringIO()
    err = None
    try:
        with redirect_stdout(buf):
            exec(compile(src, f"<cell {i}>", "exec"), g)
    except Exception:
        err = traceback.format_exc()
    out = buf.getvalue()
    if not QUIET:
        print(f"\n{'=' * 26} CELL {i} {'ok' if not err else 'ERROR'} {'=' * 26}")
        print(out.rstrip())
    if err:
        print(f"\n{'=' * 26} CELL {i} ERROR {'=' * 26}" if QUIET else "")
        print(out.rstrip() if QUIET else "")
        print(err)
        failures.append(i)
        break          # later cells read state this one did not build

print()
if failures:
    print(f"FAILED: cell(s) {failures}")
    sys.exit(1)
print(f"OK: all {sum(1 for c in nb['cells'] if c['cell_type'] == 'code')} code cells ran.")
