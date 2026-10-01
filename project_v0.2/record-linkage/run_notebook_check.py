"""Run every cell of record_linkage.ipynb on a dataset (default: synthetic); non-zero exit on any
error, including a failed self-test.

    python run_notebook_check.py                 # synthetic, the notebook check (< 2 min)
    python run_notebook_check.py leie            # the LEIE run
    python run_notebook_check.py scale           # the 1M x 300k benchmark
    python run_notebook_check.py synthetic --save   # also write the executed notebook back

Needs nbclient and ipykernel (requirements.txt).
"""
import os, sys, time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

HERE = Path(__file__).resolve().parent


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dataset = args[0] if args else "synthetic"
    os.environ["RL_DATASET"] = dataset
    nb_path = HERE / "record_linkage.ipynb"
    nb = nbformat.read(nb_path, as_version=4)
    client = NotebookClient(nb, timeout=None, kernel_name="python3", resources={"metadata": {"path": str(HERE)}})
    t0 = time.time()
    try:
        client.execute()
    except CellExecutionError as ex:
        print(f"FAILED on {dataset} after {time.time() - t0:.1f}s\n{str(ex)[-4000:]}")
        return 1
    dt = time.time() - t0
    for c in nb.cells:
        if c.cell_type == "code" and "ACCEPTANCE = acceptance_table" in c.source:
            for o in c.get("outputs", []):
                if o.get("name") == "stdout":
                    print(o["text"])
    print(f"OK: every cell ran on {dataset} in {dt:.1f}s")
    if "--save" in sys.argv:
        nbformat.write(nb, nb_path)
        print(f"executed notebook written to {nb_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
