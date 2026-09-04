"""Print the raw note, your golden rows, and the system's raw output for one
document, back to back. No scoring, no diffing, no computed anything -- this
exists so you can eyeball the three side by side yourself.

USAGE
-----
    python validation/show_doc.py DOC00000
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.settings import Paths  # noqa: E402

VAL_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = VAL_DIR / "golden"
OUT_DIR = VAL_DIR / "system_output"


def _print_csv_rows(path: Path, doc_id: str, columns: list[str]) -> None:
    if not path.exists():
        print(f"  (no file at {path.relative_to(ROOT)})")
        return
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r["doc_id"] == doc_id]
    if not rows:
        print(f"  (no rows for {doc_id} in {path.name})")
        return
    widths = {c: max(len(c), *(len(r.get(c, "")) for r in rows)) for c in columns}
    print("  " + "  ".join(c.ljust(widths[c]) for c in columns))
    for r in rows:
        print("  " + "  ".join(r.get(c, "").ljust(widths[c]) for c in columns))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python validation/show_doc.py DOC00000")
    doc_id = sys.argv[1]

    print("#" * 88)
    print(f"# {doc_id}")
    print("#" * 88)

    note_path = Paths.raw_notes / f"{doc_id}.txt"
    print("\n" + "=" * 88)
    print("RAW NOTE")
    print("=" * 88)
    print(note_path.read_text(encoding="utf-8") if note_path.exists()
          else f"(not found: {note_path})")

    print("\n" + "=" * 88)
    print("YOUR GOLDEN ENTITIES")
    print("=" * 88)
    _print_csv_rows(GOLDEN_DIR / "entities_template.csv", doc_id,
                    ["entity_name", "entity_type", "all_surfaces_seen", "notes"])

    print("\n" + "=" * 88)
    print("YOUR GOLDEN IDENTIFIERS")
    print("=" * 88)
    _print_csv_rows(GOLDEN_DIR / "identifiers_template.csv", doc_id,
                    ["identifier_kind", "value", "owner_entity_name", "notes"])

    print("\n" + "=" * 88)
    print("YOUR GOLDEN RELATIONSHIPS")
    print("=" * 88)
    _print_csv_rows(GOLDEN_DIR / "relationships_template.csv", doc_id,
                    ["subject_entity", "predicate", "object_entity_or_value",
                     "evidence_quote", "notes"])

    print("\n" + "=" * 88)
    print("SYSTEM OUTPUT -- entities / identifiers / coref (run_narrated.py)")
    print("=" * 88)
    p = OUT_DIR / f"{doc_id}.txt"
    print(p.read_text(encoding="utf-8") if p.exists()
          else f"(not generated yet -- run: python validation/run_narrated.py)")

    print("=" * 88)
    print("SYSTEM OUTPUT -- relations lane, unwired research code "
          "(run_relations_lane.py)")
    print("=" * 88)
    p = OUT_DIR / f"{doc_id}_relations.txt"
    print(p.read_text(encoding="utf-8") if p.exists()
          else "(not generated -- run: python validation/run_relations_lane.py)")


if __name__ == "__main__":
    main()
