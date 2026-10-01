"""Corpus immutability guard.

RESEARCH INVARIANT: once the corpus is generated, every file under
data/raw_notes/ is read-only for the rest of the pipeline. We record a sha256
per raw file in data/hashes.json (written once) and re-verify at the start AND
end of the full run. Any mismatch is a hard failure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .settings import Paths


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _raw_files() -> list[Path]:
    return sorted(p for p in Paths.raw_notes.glob("*.txt") if p.is_file())


def write_hashes(overwrite: bool = False) -> dict[str, str]:
    """Write data/hashes.json (once). Refuses to overwrite unless asked."""
    if Paths.hashes_json.exists() and not overwrite:
        raise FileExistsError(
            f"{Paths.hashes_json} already exists; refusing to overwrite "
            "(corpus hashes are written once). Pass overwrite=True to regenerate."
        )
    hashes = {p.name: sha256_file(p) for p in _raw_files()}
    Paths.hashes_json.parent.mkdir(parents=True, exist_ok=True)
    Paths.hashes_json.write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")
    return hashes


def load_hashes() -> dict[str, str]:
    return json.loads(Paths.hashes_json.read_text(encoding="utf-8"))


def verify_hashes(stage: str = "") -> dict:
    """Re-hash every raw file and compare to the sealed manifest.

    Returns a report dict; raises RuntimeError on any mismatch/missing/extra.
    """
    expected = load_hashes()
    actual = {p.name: sha256_file(p) for p in _raw_files()}

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(n for n in (set(expected) & set(actual)) if expected[n] != actual[n])

    report = {
        "stage": stage,
        "n_expected": len(expected),
        "n_actual": len(actual),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "ok": not (missing or extra or changed),
    }
    if not report["ok"]:
        raise RuntimeError(
            f"CORPUS INTEGRITY FAILURE ({stage or 'verify'}): "
            f"missing={missing} extra={extra} changed={changed}"
        )
    return report
