"""Development harness: execute the notebook's definition cells (everything before the Run
section, plus any cell named in --also) in one namespace, then run a snippet.
    python dev_run.py "code to run"      (cwd must be the record-linkage folder)"""
import os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STOP = "04900"          # first cell of the Run section


def load(ns, upto=STOP, also=()):
    for p in sorted((HERE / "cells").iterdir()):
        if p.suffix != ".py":
            continue
        if p.name >= upto and not any(p.name.startswith(a) for a in also):
            continue
        src = p.read_text(encoding="utf-8")
        try:
            exec(compile(src, str(p), "exec"), ns)
        except Exception:
            print("while executing", p.name)
            raise
    return ns


if __name__ == "__main__":
    os.chdir(HERE.parent)
    also = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--also=")]
    code = [a for a in sys.argv[1:] if not a.startswith("--")]
    ns = {"__name__": "nb"}
    t0 = time.time()
    load(ns, also=also)
    print(f"definitions loaded in {time.time() - t0:.1f}s")
    for c in code:
        exec(compile(Path(c).read_text(encoding="utf-8") if c.endswith(".py") else c, "snippet", "exec"), ns)
