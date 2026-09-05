"""Load config/config.py as the single source of truth and resolve paths.

Import config values as ``from src.settings import CFG``. Nothing else in the
repo may define a model name, threshold, seed or path.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path
from types import SimpleNamespace


def find_project_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).resolve()
    for cand in [here, *here.parents]:
        if (cand / "config" / "config.py").exists():
            return cand
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = find_project_root()
CONFIG_PATH = PROJECT_ROOT / "config" / "config.py"


def load_dotenv(path: Path | None = None) -> list[str]:
    """Read KEY=VALUE lines from a local .env into os.environ.

    An existing environment variable always wins, so an explicit
    `GEMINI_API_KEY=... python ...` or a CI secret is never overridden by a
    stale file on disk.
    """
    loaded: list[str] = []
    candidates = [path] if path else [PROJECT_ROOT.parent / ".env", PROJECT_ROOT / ".env"]
    for env_path in candidates:
        if not env_path or not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
                loaded.append(key)
    return loaded


DOTENV_KEYS_LOADED = load_dotenv()


def load_config() -> SimpleNamespace:
    ns = runpy.run_path(str(CONFIG_PATH))
    return SimpleNamespace(**{k: v for k, v in ns.items() if not k.startswith("_")})


CFG = load_config()

# Explicit, auditable override for the NER backend. There is NO automatic
# fallback: a run that cannot load the production model must either fail or be
# told, in so many words, to use something else.
_ner_override = os.environ.get("NER_BACKEND", "").strip().lower()
if _ner_override:
    CFG.NER_BACKEND = _ner_override


class Paths:
    root = PROJECT_ROOT
    config = PROJECT_ROOT / "config"
    corpus = (PROJECT_ROOT / CFG.CORPUS_DIR).resolve()
    raw_notes = (PROJECT_ROOT / CFG.CORPUS_DIR).resolve() / "raw_notes"
    ground_truth = (PROJECT_ROOT / CFG.CORPUS_DIR).resolve() / "ground_truth"
    manifest_json = ground_truth / "manifest.json"
    doc_index = (PROJECT_ROOT / CFG.CORPUS_DIR).resolve() / "doc_index.json"
    store = PROJECT_ROOT / CFG.STORE_DIRNAME
    db = PROJECT_ROOT / CFG.STORE_DIRNAME / CFG.DB_FILENAME
    genai_cache = PROJECT_ROOT / CFG.STORE_DIRNAME / CFG.GENAI_CACHE_DIRNAME

    @classmethod
    def ensure(cls) -> None:
        for p in (cls.store, cls.genai_cache):
            p.mkdir(parents=True, exist_ok=True)


def genai_mode() -> str:
    """'online' or 'offline'. Forced by GENAI_MODE; otherwise online iff a key exists."""
    forced = os.environ.get("GENAI_MODE", "").strip().lower()
    if forced in ("online", "offline"):
        return forced
    for var in CFG.GENAI_API_KEY_ENV_VARS:
        if os.environ.get(var):
            return "online"
    return "offline"


def genai_mode_is_forced() -> bool:
    """True when offline/online was CHOSEN, not fallen into.

    Without this, a run with no API key looks identical to a run with one.
    Callers that would otherwise substitute a stand-in use this to refuse
    unless the substitution was asked for explicitly.
    """
    return os.environ.get("GENAI_MODE", "").strip().lower() in ("online", "offline")


def api_key() -> str | None:
    for var in CFG.GENAI_API_KEY_ENV_VARS:
        if (v := os.environ.get(var)):
            return v
    return None
