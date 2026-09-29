"""Run every cell of goko_record_linkage_mvp_b1.ipynb against the built-in synthetic set (no
real data needed); non-zero exit on any error, including a failed self-test.

    python run_mvp_check.py                 # the notebook check (a few minutes)
    python run_mvp_check.py --save          # also write the executed notebook back

This does not touch EXTRACTED_CSV_PATH / WATCHLIST_CSV_PATH: it patches an in-memory copy of
the Settings cell so RUN_NAME becomes "synthetic" (the notebook's own built-in test set,
generated once into data/), then executes that copy. The notebook file on disk is never
changed unless --save is given, and even then only the executed copy's outputs are updated,
not the settings.

Needs nbclient and ipykernel (requirements.txt).
"""
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

HERE = Path(__file__).resolve().parent
NB_NAME = "goko_record_linkage_mvp_b1.ipynb"


def main():
    nb_path = HERE / NB_NAME
    nb = nbformat.read(nb_path, as_version=4)
    patched = False
    for cell in nb.cells:
        if cell.cell_type == "code" and 'RUN_NAME = "production"' in cell.source:
            cell.source = cell.source.replace('RUN_NAME = "production"', 'RUN_NAME = "synthetic"', 1)
            patched = True
    if not patched:
        print(f"could not find the Settings cell's RUN_NAME in {NB_NAME}; nothing patched")
        return 1
    client = NotebookClient(nb, timeout=None, kernel_name="python3", resources={"metadata": {"path": str(HERE)}})
    t0 = time.time()
    try:
        client.execute()
    except CellExecutionError as ex:
        print(f"FAILED after {time.time() - t0:.1f}s\n{str(ex)[-4000:]}")
        return 1
    dt = time.time() - t0
    for c in nb.cells:
        if c.cell_type == "code" and "ACCEPTANCE = acceptance_table" in c.source:
            for o in c.get("outputs", []):
                if o.get("name") == "stdout":
                    print(o["text"])
    print(f"OK: every cell ran on the built-in synthetic set in {dt:.1f}s")
    if "--save" in sys.argv:
        nbformat.write(nb, nb_path)
        print(f"executed notebook written to {nb_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
