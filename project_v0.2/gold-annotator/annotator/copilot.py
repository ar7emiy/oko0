"""The message an SME copies into Copilot for one note (or one part of a long note)."""
from __future__ import annotations

from pathlib import Path

from .ai_import import split_parts

INSTRUCTIONS_PATH = Path(__file__).resolve().parent.parent / "prompts" / "copilot-agent-instructions.md"


def instructions() -> str:
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


def build_message(*, claim: str, note: str, text: str, entities: list[dict], part: int, part_size: int,
                  include_instructions: bool) -> dict:
    parts = split_parts(text, part_size)
    part = max(1, min(part, len(parts)))
    start, end = parts[part - 1]
    known = "\n".join(f"E{e['number']} | {e['label']} | {e['type']}" for e in entities) or "none"
    body = (f"CLAIM: {claim}\nNOTE: {note}\nPART: {part} of {len(parts)}\n"
            f"KNOWN:\n{known}\n\n<<<NOTE\n{text[start:end]}\nNOTE>>>")
    if include_instructions:
        body = instructions() + "\n\n----------\n\n" + body
    return {"message": body, "part": part, "parts": [list(p) for p in parts], "chars": len(body)}
