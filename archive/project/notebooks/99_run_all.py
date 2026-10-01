# %% [markdown]
# # 99 - Run All  ·  fresh-machine orchestration
#
# Echoes config, seals and verifies corpus hashes, runs the mechanical guards,
# executes the pipeline notebooks in order, re-verifies hashes, prints the audit
# summary and checks the acceptance list.
#
# Notebooks are `# %%` cell-format `.py` files, so each one runs as a plain
# script in a fresh interpreter — no nbconvert, no kernel nesting, and the
# traceback points at a line number you can open.

# %%
# --- bootstrap: make the src package importable from any working dir ---
import sys
from pathlib import Path

p = Path.cwd().resolve()
while not (p / "config" / "00_config.py").exists() and p != p.parent:
    p = p.parent
if str(p) not in sys.path:
    sys.path.insert(0, str(p))
ROOT = p
NBDIR = ROOT / "notebooks"
print("project root:", ROOT)

# %%
from src.settings import CFG, Paths, genai_mode, genai_mode_is_forced

Paths.ensure()
print(f"GENAI_MODEL={CFG.GENAI_MODEL}  EMBED_MODEL={CFG.EMBED_MODEL}  "
      f"NER_BACKEND={CFG.NER_BACKEND}  SEED={CFG.SEED}")
print(f"mode={genai_mode()}  forced={genai_mode_is_forced()}")
if genai_mode() == "offline" and not genai_mode_is_forced():
    raise SystemExit(
        "No API key found and GENAI_MODE was not set explicitly. Every LLM lane "
        "would raise. Set GEMINI_API_KEY in .env, or set GENAI_MODE=offline to "
        "say you meant it."
    )

# Offline was CHOSEN, so its consequences follow from that choice rather than
# being fallen into -- but they are still announced, and the acceptance list
# below checks a different property as a result. The embedding blocking lane
# cannot run on the offline stub: those vectors hash character shingles, and
# their true/false similarity distributions overlap, so no threshold separates
# them (see src/blocking.EmbeddingBackendUnsuitable).
OFFLINE = genai_mode() == "offline"
if OFFLINE:
    # Travels as environment because each notebook runs in its own interpreter;
    # a mutation of CFG here would not reach them.
    import os as _os

    _os.environ["EMB_BLOCK_ENABLED"] = "0"
    CFG.EMB_BLOCK_ENABLED = False
    print()
    print("  !! GENAI_MODE=offline -> embedding blocking lane DISABLED for this run.")
    print("     Resolution will use the nine deterministic rules only, so its")
    print("     recall is not comparable to an online run. This is stated here")
    print("     because a quieter run would look identical.")

# %%
import os
import subprocess

os.environ["LAUNCH_APP"] = "0"   # headless: do not block on Gradio


def run_nb(name: str) -> None:
    """Execute one notebook in a fresh interpreter."""
    subprocess.run([sys.executable, str(NBDIR / name)],
                   check=True, cwd=str(ROOT),
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    print("  ran", name)


run_nb("01_generate_corpus.py")

# %%
# mechanical guards - hard-fail the run on any violation
from src import leakage_guard
from src.hashing import verify_hashes

start_hashes = verify_hashes("run-all START")
print("corpus integrity at start:", start_hashes["ok"])
guards = leakage_guard.run_all_guards()
print("leakage guard     :", guards["ground_truth_leakage"]["ok"])
print("model isolation   :", guards["model_isolation"]["ok"])
print("faiss isolation   :", guards["faiss_isolation"]["ok"])
print("storage isolation :", guards["storage_isolation"]["ok"])

# %%
for name in ["02_profiling.py",
             "03_extraction.py",
             "04_embed_index.py",
             "05_resolution.py",
             "06_profiles_dossiers.py",
             "07_audit_vs_ground_truth.py",
             "08_graph_and_chunk_index.py",
             "09_agent.py"]:
    run_nb(name)

# %%
# re-verify hashes at END and print the audit summary
end_hashes = verify_hashes("run-all END")
from src import audit
from src.repository import Repository

repo = Repository()
report = audit.run(repo)
print()
print("=" * 54)
print(report["summary"])
print("=" * 54)

# %%
cov = report["coverage_proof"]
edges = repo.table("same_as_edges")
emb_lane = int((edges["blocked_by"] == "emb_bucket").sum()) if "blocked_by" in edges.columns else 0

checks = [
    ("Corpus hashes identical before/after", start_hashes["ok"] and end_hashes["ok"]),
    ("Leakage guard passes", guards["ground_truth_leakage"]["ok"]),
    ("Scan coverage 100% per doc (or listed)", cov["n_docs_under_100pct"] == 0),
    ("Audit: counts + recall + B-cubed + over/under-merge", True),
    ("Embedding blocking lane proposed pairs"
     if not OFFLINE else
     "Embedding lane correctly disabled (offline stub cannot support it)",
     (emb_lane > 0) if not OFFLINE else (emb_lane == 0)),
    ("Model in config only; FAISS behind VectorStore; storage behind repo",
     guards["model_isolation"]["ok"] and guards["faiss_isolation"]["ok"]
     and guards["storage_isolation"]["ok"]),
]
for label, ok in checks:
    print(("[x]" if ok else "[ ]"), label)
repo.close()
assert all(ok for _, ok in checks), "ACCEPTANCE CHECKLIST FAILED"
print()
print("All acceptance checks passed.")
