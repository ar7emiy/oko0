"""Check a saved Copilot reply against its note, exactly as the app would read it.

    python check_answer.py NOTE.txt REPLY.txt [--known 1 2 ...] [--part-size 12000]

Use it to test the prompt on real Copilot replies before SMEs rely on it: every
line should parse, and every quote should be found in the note.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from annotator.ai_import import read_answer  # noqa: E402
from annotator.notes import parse_name, read  # noqa: E402


def check(note_path: Path, reply_path: Path, known: list[int], part_size: int, quiet: bool = False) -> dict:
    nt = read(note_path)
    claim, note = parse_name(note_path) or ("?", "?")
    report = read_answer(reply_path.read_text(encoding="utf-8"), nt.text, claim=claim, note=note,
                         existing_entities={k: f"E-{k}" for k in known}, part_size=part_size)
    c = report.counts()
    matches = {}
    for d in report.drafts:
        matches[d.match or "none"] = matches.get(d.match or "none", 0) + 1
    if not quiet:
        print(f"{reply_path.name} against {note_path.name}")
        for e in report.errors:
            print(f"  ERROR    {e}")
        for w in report.warnings:
            print(f"  warning  {w}")
        if report.repairs:
            print(f"  repaired {'; '.join(report.repairs)}")
        for r in report.rejected:
            print(f"  REJECTED line {r['line']}: {r['why']}  {r['raw'][:90]}")
        for d in report.drafts:
            if d.status != "ready":
                why = "; ".join(p["text"] for p in d.problems) or (f"duplicate of {d.duplicate_of}" if d.duplicate_of else "")
                print(f"  {d.status:15} #{d.seq} {d.type:11} {d.quote[:40]!r}  {why}")
        print(f"  => {c['ready']} ready, {c['needs_attention']} need attention, {c['duplicate']} duplicate, "
              f"{c['rejected']} rejected; matches {matches}; ignored lines {report.ignored_lines}")
    return {"counts": c, "errors": report.errors, "warnings": report.warnings, "repairs": report.repairs,
            "matches": matches, "report": report}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("note", type=Path)
    p.add_argument("reply", type=Path)
    p.add_argument("--known", type=int, nargs="*", default=[], help="entity numbers already recorded (E1 -> 1)")
    p.add_argument("--part-size", type=int, default=12000)
    a = p.parse_args()
    result = check(a.note, a.reply, a.known, a.part_size)
    sys.exit(1 if result["errors"] or result["counts"]["rejected"] else 0)


if __name__ == "__main__":
    main()
