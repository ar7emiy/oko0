"""End-to-end offline smoke test asserting the research invariants.

Runs the whole pipeline with no API key (deterministic offline mode) and asserts:
  - planted-offset fidelity is byte-accurate
  - 100% scan-coverage per doc
  - leakage / model / faiss / storage guards pass
  - corpus hashes verify (immutability)
  - audit produces B-cubed + recall and a dossier exports with a highlightable span

Usage:  python tests/smoke_test.py   (from project/ root)
Exit code 0 = all invariants hold.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import (audit, corpus_gen, embed_index, extraction, leakage_guard,  # noqa: E402
                 profiles, profiling, resolution, app)
from src.hashing import verify_hashes, write_hashes  # noqa: E402
from src.repository import Repository  # noqa: E402
from src.settings import Paths  # noqa: E402


def main():
    print("[1/7] generate corpus + seal hashes")
    summ = corpus_gen.generate_corpus()
    write_hashes(overwrite=True)
    assert verify_hashes("smoke")["ok"], "hash verify failed"

    man = json.loads(Paths.manifest_json.read_text())
    bad = 0
    cache = {}
    for pl in man["placements"]:
        t = cache.setdefault(pl["doc_id"], (Paths.raw_notes / f"{pl['doc_id']}.txt").read_text())
        if t[pl["char_start"]:pl["char_end"]] != pl["surface_variant"]:
            bad += 1
    assert bad == 0, f"{bad} planted offsets are not byte-accurate"
    print(f"      entities={summ['n_entities']} docs={summ['n_docs']} placements={summ['n_placements']} offset_errors=0")

    print("[2/7] guards")
    g = leakage_guard.run_all_guards()
    assert all(v["ok"] for v in g.values()), "a guard failed"

    print("[3/7] profiling -> extraction -> embed")
    repo = Repository(); repo.reset()
    profiling.run(repo)
    ex = extraction.run(repo)
    embed_index.run(repo)

    print("[4/7] resolution -> profiles")
    resolution.run(repo)
    profiles.run(repo)

    print("[5/7] audit")
    rep = audit.run(repo)
    cov = rep["coverage_proof"]
    assert cov["n_docs_under_100pct"] == 0, "coverage below 100% on some docs"
    assert cov["overall_coverage"] >= 0.99999, "overall coverage < 100%"
    cq = rep["cluster_quality"]
    rc = rep["mention_recall"]["recall"]
    print(f"      recall={rc} coverage={cov['overall_coverage']} "
          f"B3 P/R={cq['bcubed_precision']}/{cq['bcubed_recall']}")
    assert rc > 0.7, "mention recall unexpectedly low"

    print("[6/7] dossier export + span traceability")
    idx = app.EntityIndex(repo)
    eid = max(idx.dossiers, key=lambda e: idx.dossiers[e]["n_mentions"])
    path = app.export_dossier_html(repo, eid)
    html = Path(path).read_text()
    assert "<mark" in html and "https://" not in html, "dossier not self-contained/traceable"

    print("[7/7] NL query -> plan -> table answer")
    out = app.answer_question(repo, idx, "Show all attorneys and everything we know about them.")
    assert "intent" in out["plan"], "no structured plan produced"
    repo.close()

    print("\nSMOKE TEST PASSED —", rep["summary"])


if __name__ == "__main__":
    main()
