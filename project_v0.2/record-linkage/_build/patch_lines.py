"""Replace lines [start, end] (1-based, inclusive) of a file with the content of another file.
    python patch_lines.py TARGET START END SOURCE"""
import sys
from pathlib import Path

target, start, end, source = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
lines = target.read_text(encoding="utf-8").split("\n")
new = source.read_text(encoding="utf-8").rstrip("\n").split("\n")
print("replacing:", repr(lines[start - 1][:60]), "...", repr(lines[end - 1][:60]))
lines[start - 1:end] = new
target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
