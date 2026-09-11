"""Start the claim note annotator.

    python run.py --notes "C:\\path\\to\\notes" --firm "C:\\path\\to\\firm-export.csv"

Then open the address it prints. Standard library only; Python 3.10 or newer.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from annotator.server import App, Config, serve  # noqa: E402
from annotator.store import Store  # noqa: E402
from annotator.review import load_taxonomy  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Claim note annotator")
    p.add_argument("--notes", type=Path, help="folder of CLAIM_NOTE.txt files (searched recursively)")
    p.add_argument("--firm", type=Path, action="append", default=[], help="the firm's export CSV (repeatable)")
    p.add_argument("--db", type=Path, default=HERE / "annotations.sqlite3", help="where annotations are saved")
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 keeps it on this computer only")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--part-size", type=int, default=12000,
                   help="characters per part when a long note is sent to Copilot")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--taxonomy", type=Path, help="versioned study category definitions (JSON)")
    a = p.parse_args(argv)

    if a.notes and not a.notes.exists():
        p.error(f"notes folder not found: {a.notes}")
    store = Store(a.db)
    app = App(store, Config(notes_dir=a.notes, firm_files=a.firm, part_size=a.part_size,
                            taxonomy=load_taxonomy(a.taxonomy)))
    httpd = serve(app, a.host, a.port)
    url = f"http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}/"
    print(f"Claim note annotator running at {url}")
    print(f"  notes: {a.notes or '(practice note only)'}")
    print(f"  firm export: {', '.join(map(str, a.firm)) or '(none)'}")
    print(f"  saving to: {a.db}")
    for s in app.config.skipped:
        print(f"  skipped: {s}")
    for w in app.config.firm_warnings:
        print(f"  firm export: {w}")
    print("Press Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
