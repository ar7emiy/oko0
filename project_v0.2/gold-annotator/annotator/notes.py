"""Finding and reading claim notes.

Notes are UTF-8 .txt files named CLAIM_NOTE.txt, split on the LAST underscore.
The same note ID can occur in multiple claims; the pair is the lookup key.
Text is read as bytes and decoded
without newline translation: CRLF stays two characters, because every stored
position is a character offset into exactly this text.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PRACTICE_CLAIM = "PRACTICE"
PRACTICE_CLAIMS = {"PRACTICE", "PRACTICE2"}


def is_practice(claim):
    return claim in PRACTICE_CLAIMS

PRACTICE_DIR = Path(__file__).resolve().parent / "practice"


@dataclass(frozen=True)
class NoteFile:
    claim: str
    note: str
    path: Path

    @property
    def practice(self) -> bool:
        return is_practice(self.claim)


def parse_name(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    cut = stem.rfind("_")
    if cut < 1 or cut == len(stem) - 1:
        return None
    return stem[:cut].strip(), stem[cut + 1:].strip()


def discover(notes_dir: Path | None) -> tuple[list[NoteFile], list[str]]:
    """All notes under notes_dir plus the practice note. Returns (notes, skipped)."""
    found: list[NoteFile] = []
    skipped: list[str] = []
    roots = [PRACTICE_DIR]
    if notes_dir is not None:
        roots.append(notes_dir)
    seen: set[tuple[str, str]] = set()
    for root in roots:
        if not root.exists():
            skipped.append(f"{root}: folder not found")
            continue
        for path in sorted(root.rglob("*.txt")):
            parsed = parse_name(path)
            if parsed is None:
                skipped.append(f"{path.name}: name must be CLAIM_NOTE.txt")
                continue
            claim, note = parsed
            if root != PRACTICE_DIR and is_practice(claim):
                skipped.append(f"{path.name}: claim {PRACTICE_CLAIM} is reserved for the practice note")
                continue
            if (claim, note) in seen:
                skipped.append(f"{path.name}: duplicate of claim {claim} note {note}")
                continue
            seen.add((claim, note))
            found.append(NoteFile(claim, note, path))
    found.sort(key=lambda n: (n.practice is False, n.claim, _natural(n.note)))
    return found, skipped


def _natural(text: str) -> tuple:
    """Sort N2 before N10."""
    parts, number = [], ""
    for ch in text:
        if ch.isdigit():
            number += ch
        else:
            if number:
                parts.append((0, int(number)))
                number = ""
            parts.append((1, ch))
    if number:
        parts.append((0, int(number)))
    return tuple(parts)


@dataclass(frozen=True)
class NoteText:
    text: str
    sha256: str
    had_bom: bool


def read(path: Path) -> NoteText:
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if had_bom else raw
    text = body.decode("utf-8")  # strict: a decoding failure must surface, not be papered over
    return NoteText(text=text, sha256=hashlib.sha256(raw).hexdigest(), had_bom=had_bom)
