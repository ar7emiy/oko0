"""Load config/00_config.py as the single source of truth and resolve paths.

`config/00_config.py` is a plain module (its name is not a valid identifier),
so we exec it via runpy and expose the resulting namespace here. Import config
values as ``from src.settings import CFG`` (a SimpleNamespace) or use the path
helpers. Nothing else in the repo re-defines a model name, seed or threshold.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path
from types import SimpleNamespace


def find_project_root(start: Path | None = None) -> Path:
    """Walk up until we find the directory that contains config/00_config.py."""
    here = (start or Path(__file__).resolve()).resolve()
    for cand in [here, *here.parents]:
        if (cand / "config" / "00_config.py").exists():
            return cand
    # Fallback: parent of src/
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = find_project_root()
CONFIG_PATH = PROJECT_ROOT / "config" / "00_config.py"


def load_config() -> SimpleNamespace:
    ns = runpy.run_path(str(CONFIG_PATH))
    public = {k: v for k, v in ns.items() if not k.startswith("_")}
    return SimpleNamespace(**public)


CFG = load_config()

# Explicit, auditable override for the NER backend. There is no automatic
# fallback any more: a run that cannot load the production model must either
# fail or be told, in so many words, to use the research scanner instead. This
# env var is how the offline test harness says so -- and because it is
# recorded in the run output (`token_ner_backend`), a research run can never be
# mistaken for a model run after the fact.
_ner_override = os.environ.get("NER_BACKEND", "").strip().lower()
if _ner_override:
    CFG.NER_BACKEND = _ner_override


# ---- Canonical paths (everything relative to PROJECT_ROOT) -------------------
class Paths:
    root = PROJECT_ROOT
    config = PROJECT_ROOT / "config"
    data = PROJECT_ROOT / "data"
    raw_notes = PROJECT_ROOT / "data" / "raw_notes"
    ground_truth = PROJECT_ROOT / "data" / "ground_truth"
    hashes_json = PROJECT_ROOT / "data" / "hashes.json"
    manifest_json = PROJECT_ROOT / "data" / "ground_truth" / "manifest.json"
    notebooks = PROJECT_ROOT / "notebooks"
    store = PROJECT_ROOT / "store"
    db = PROJECT_ROOT / "store" / CFG.DB_FILENAME
    faiss_index = PROJECT_ROOT / "store" / CFG.FAISS_INDEX_FILENAME
    faiss_meta = PROJECT_ROOT / "store" / CFG.FAISS_META_FILENAME
    genai_cache = PROJECT_ROOT / "store" / CFG.GENAI_CACHE_DIRNAME

    @classmethod
    def ensure(cls) -> None:
        for p in (cls.data, cls.raw_notes, cls.ground_truth, cls.store, cls.genai_cache):
            p.mkdir(parents=True, exist_ok=True)


def genai_mode() -> str:
    """Return 'online' or 'offline'.

    Forced by GENAI_MODE env var; otherwise online iff an API key is present.
    """
    forced = os.environ.get("GENAI_MODE", "").strip().lower()
    if forced in ("online", "offline"):
        return forced
    for var in CFG.GENAI_API_KEY_ENV_VARS:
        if os.environ.get(var):
            return "online"
    return "offline"


def genai_mode_is_forced() -> bool:
    """True when offline/online was chosen DELIBERATELY, not fallen into.

    Without this distinction a run with no API key looks identical to a run
    with one. Callers that would otherwise substitute a stand-in for the model
    use this to refuse unless the substitution was asked for explicitly.
    """
    return os.environ.get("GENAI_MODE", "").strip().lower() in ("online", "offline")


def api_key() -> str | None:
    for var in CFG.GENAI_API_KEY_ENV_VARS:
        v = os.environ.get(var)
        if v:
            return v
    return None
