"""Mechanical guards for the research invariants that concern source code.

1. LEAKAGE GUARD (non-negotiable): notebooks 02-06 and 08 (and the pipeline
   modules they import) must NEVER reference ground truth. Only the generator
   (notebook 01 / corpus_gen.py) and the auditor (notebook 07 / audit.py) may.
2. MODEL ISOLATION: model-name strings appear only in config/00_config.py.
3. FAISS ISOLATION: `import faiss` appears only in src/vectorstore.py.
4. STORAGE ISOLATION: `import sqlite3` appears only in src/repository.py.

Notebook 09 runs these and hard-fails the run on any violation.
"""
from __future__ import annotations

import re
from pathlib import Path

from .settings import PROJECT_ROOT, Paths

GT_TOKEN = "ground" + "_truth"  # avoid this file itself tripping a naive grep

# Files permitted to reference ground truth.
GT_ALLOWED_FILES = {
    "src/corpus_gen.py",
    "src/audit.py",
    "src/ablation.py",       # audit-side: measures recall against the manifest
    "src/qa_viewer.py",      # audit-side: overlays extraction against ground truth
    "src/settings.py",       # defines the path constants (infra, never reads content)
    "src/leakage_guard.py",  # this guard
}

# Pipeline modules that must be ground-truth-free (imported by notebooks 02-06,08).
PIPELINE_MODULES = [
    "src/profiling.py", "src/embed_index.py", "src/blocking.py",
    "src/relations.py",
    "src/profiles.py", "src/app.py",
    # Layer 1-4 architecture: none of these may see ground truth either
    "src/chunking.py", "src/gazetteers.py", "src/coref.py",
    "src/ner_ensemble.py", "src/sweep.py", "src/pipeline_v2.py",
    "src/graph_store.py", "src/build_graph.py", "src/agent.py",
    "src/entity_resolution.py",
    # The operational path. These matter MORE than the rest, not less: they are
    # what runs when there is no ground truth to leak from, so if one of them
    # ever reads the manifest the demo would be quietly cheating.
    "src/ingest.py", "src/incremental.py", "src/runlog.py",
]

# NOTE ON data/doc_index.json: it maps note -> claim/occurrence. That is
# STRUCTURAL SYSTEM METADATA, not ground truth -- every real claim system knows
# which file a note was written on. Only ENTITY IDENTITY must be inferred from
# text, and that lives solely in the manifest. The guard below deliberately
# polices the manifest, not the doc index.

# Notebook 11 (ablation) is audit-side and legitimately reads ground truth.
LEAKAGE_NOTEBOOKS = ["02_profiling", "03_extraction", "04_embed_index",
                     "05_resolution", "06_profiles_dossiers",
                     "08_graph_and_chunk_index", "09_agent",
                     "20_relation_extraction"]


def _notebook_source(nb_path: Path) -> str:
    """Notebooks are ``# %%`` cell-format .py files, so the source IS the file.

    They used to be generated .ipynb, and this had to walk the JSON to pull the
    code cells out. Reading the file is now the whole job. The function is kept
    so callers read a notebook the same way they always did.
    """
    return nb_path.read_text(encoding="utf-8")


def scan_ground_truth_leakage() -> dict:
    """Scan notebooks 02-06,08 + pipeline modules for the ground-truth token."""
    violations = []

    for stem in LEAKAGE_NOTEBOOKS:
        nb = Paths.notebooks / f"{stem}.py"
        if not nb.exists():
            violations.append(f"notebook {stem}.py is missing; the guard cannot "
                              "vouch for a file it never read")
            continue
        if GT_TOKEN in _notebook_source(nb):
            violations.append(f"notebook {stem}.py references {GT_TOKEN}")

    for rel in PIPELINE_MODULES:
        f = PROJECT_ROOT / rel
        if f.exists() and GT_TOKEN in f.read_text(encoding="utf-8"):
            violations.append(f"module {rel} references {GT_TOKEN}")

    ok = not violations
    if not ok:
        raise RuntimeError("LEAKAGE GUARD FAILED:\n  " + "\n  ".join(violations))
    return {"ok": True, "checked_notebooks": LEAKAGE_NOTEBOOKS,
            "checked_modules": PIPELINE_MODULES}


def _iter_source_files():
    for f in (PROJECT_ROOT / "src").glob("*.py"):
        yield f.relative_to(PROJECT_ROOT).as_posix(), f.read_text(encoding="utf-8")
    for f in Paths.notebooks.glob("*.py"):
        yield f"notebooks/{f.name}", _notebook_source(f)


def check_model_isolation() -> dict:
    """No model string outside config/00_config.py. We flag any 'gemini-...' or
    'GENAI_MODEL ='/'EMBED_MODEL =' assignment appearing outside config."""
    violations = []
    model_lit = re.compile(r"[\"']gemini-[a-z0-9.\-]+[\"']")
    assign = re.compile(r"^\s*(GENAI_MODEL|EMBED_MODEL)\s*=", re.M)
    for rel, text in _iter_source_files():
        if rel == "src/leakage_guard.py":
            continue
        if model_lit.search(text) or assign.search(text):
            violations.append(rel)
    if violations:
        raise RuntimeError(f"MODEL ISOLATION FAILED: model strings outside config in {violations}")
    return {"ok": True}


def check_faiss_isolation() -> dict:
    violations = []
    pat = re.compile(r"^\s*import\s+faiss|^\s*from\s+faiss\s+import", re.M)
    for rel, text in _iter_source_files():
        if rel == "src/vectorstore.py":
            continue
        if pat.search(text):
            violations.append(rel)
    if violations:
        raise RuntimeError(f"FAISS ISOLATION FAILED: faiss imported outside vectorstore in {violations}")
    return {"ok": True}


def check_storage_isolation() -> dict:
    violations = []
    pat = re.compile(r"^\s*import\s+sqlite3|^\s*from\s+sqlite3\s+import", re.M)
    for rel, text in _iter_source_files():
        if rel == "src/repository.py":
            continue
        if pat.search(text):
            violations.append(rel)
    if violations:
        raise RuntimeError(f"STORAGE ISOLATION FAILED: sqlite3 imported outside repository in {violations}")
    return {"ok": True}


def run_all_guards() -> dict:
    return {
        "ground_truth_leakage": scan_ground_truth_leakage(),
        "model_isolation": check_model_isolation(),
        "faiss_isolation": check_faiss_isolation(),
        "storage_isolation": check_storage_isolation(),
    }
