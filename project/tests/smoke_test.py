"""End-to-end smoke test asserting the research invariants on corpus v2.

Runs the whole pipeline offline (no API key) and asserts the properties that
must not regress. Exit 0 = all invariants hold.

Usage:  python tests/smoke_test.py
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import (audit, build_graph, corpus_gen, entity_resolution,  # noqa: E402
                 leakage_guard, pipeline_v2, profiling)
from src.hashing import verify_hashes, write_hashes  # noqa: E402
from src.repository import Repository  # noqa: E402
from src.settings import Paths  # noqa: E402


def _assert_no_silent_fallback():
    """A run must never quietly substitute a research stand-in for a model.

    This is a regression guard, not a style check. Both substitutions used to
    happen automatically: a missing GLiNER install fell through to the regex
    scanner, and a missing API key returned that same scanner's output tagged
    as the LLM lane. Either one produces output shaped exactly like a real run,
    so nothing downstream -- including the recall numbers -- could tell.
    """
    import os
    from src import ner_ensemble
    from src.settings import genai_mode, genai_mode_is_forced

    saved = os.environ.pop("NER_BACKEND", None)
    try:
        ner_ensemble.get_token_ner("gliner")
    except ner_ensemble.NERBackendUnavailable:
        pass          # correct: refuses rather than degrading
    except Exception as e:
        raise AssertionError(f"expected NERBackendUnavailable, got {e!r}")
    else:
        pass          # GLiNER really is available; also fine
    finally:
        if saved is not None:
            os.environ["NER_BACKEND"] = saved

    if genai_mode() == "offline" and not genai_mode_is_forced():
        raise AssertionError(
            "offline GenAI was fallen into rather than chosen; the LLM lane "
            "must refuse instead of substituting the research stub")
    print("      no-silent-fallback guards OK")


def main(full: bool = True):
    print("[1/7] generate corpus v2 + seal hashes")
    summ = corpus_gen.generate_corpus()
    write_hashes(overwrite=True)
    assert verify_hashes("smoke")["ok"], "hash verification failed"
    assert summ["schema_version"] == 2

    man = json.loads(Paths.manifest_json.read_text())
    cache = {}

    def txt(d):
        if d not in cache:
            cache[d] = (Paths.raw_notes / f"{d}.txt").read_text()
        return cache[d]

    # every planted span must be byte-accurate: entity, identifier and event
    bad = sum(1 for p in man["placements"]
              if txt(p["doc_id"])[p["char_start"]:p["char_end"]] != p["surface"])
    assert bad == 0, f"{bad} placement offsets are not byte-accurate"
    cbad = sum(1 for c in man["coref_chains"]
               if txt(c["doc_id"])[c["anaphor_start"]:c["anaphor_end"]] != c["anaphor_text"])
    assert cbad == 0, f"{cbad} coref anaphor offsets are not byte-accurate"
    print(f"      {len(man['placements'])} placements + {len(man['coref_chains'])} "
          f"coref chains, 0 offset errors")

    # the fixture must actually exercise the hard cases
    orphans = [p for p in man["placements"]
               if p["kind"] == "identifier" and p.get("orphan")]
    assert orphans, "fixture has no name-less identifier mentions to test"
    hops = {c["hops"] for c in man["coref_chains"]}
    assert max(hops) >= 2, "fixture has no multi-hop coreference chains"
    multi = [e for e in man["entities"] if len(e["claims"]) > 1]
    assert len(multi) / len(man["entities"]) > 0.2, "cross-claim overlap too rare"
    print(f"      {len(orphans)} orphan identifiers, hops up to {max(hops)}, "
          f"{100*len(multi)//len(man['entities'])}% cross-claim entities")

    print("[2/7] guards")
    _assert_no_silent_fallback()
    g = leakage_guard.run_all_guards()
    assert all(v["ok"] for v in g.values())

    print("[3/7] profiling")
    repo = Repository()
    repo.reset()
    profiling.run(repo)
    docs = repo.table("documents")
    assert int((docs.claim_id == "UNKNOWN").sum()) == 0, "notes unattributed to a claim"
    assert docs.occurrence_id.nunique() > 1, "occurrence hierarchy missing"

    print("[4/7] layer 1 extraction")
    r = pipeline_v2.run(repo)
    assert r["n_orphan_identifiers"] > 0, "orphan identifiers not being recorded"

    print("[5/7] audit: extraction quality")
    m = audit._load_manifest()
    ident = audit.identifier_recall(repo, m)
    assert ident["orphan"]["recall"] > 0.95, (
        f"orphan identifier recall regressed to {ident['orphan']['recall']} -- "
        "identifiers must be recorded even when no name binds")
    er_ = audit.entity_recall(repo, m)
    assert er_["recall"] > 0.75, f"entity recall regressed to {er_['recall']}"
    cov = audit.coverage_check(repo)
    assert cov["n_docs_under_100pct"] == 0, "scan coverage below 100% on some docs"
    print(f"      entity recall {er_['recall']:.3f} | identifier recall "
          f"{ident['recall']:.3f} (orphan {ident['orphan']['recall']:.3f})")

    if not full:
        repo.close()
        print("\nSMOKE TEST PASSED (extraction only; --full for resolution)")
        return

    print("[6/7] entity resolution (Splink)")
    out = entity_resolution.run(repo)
    assert out["n_entities"] > 1, "resolution produced no clusters"
    gold = audit.entity_precision(repo, m)["_mention_gold"]
    sweep = audit.bcubed_sweep(repo, gold)
    best = sweep["best_by_f1"]
    assert best["bcubed_f1"] > 0.6, f"B-cubed F1 regressed to {best['bcubed_f1']}"
    print(f"      {out['n_entities']} entities @ {out['operating_threshold']}; "
          f"best F1 {best['bcubed_f1']:.3f} @ {best['threshold']}")

    print("[7/7] global graph")
    gr = build_graph.build_graph(repo)
    kinds = gr["node_kinds"]
    for required in ("party", "identifier", "claim", "occurrence"):
        assert kinds.get(required, 0) > 0, f"graph missing {required} nodes"
    assert gr["n_orphan_identifier_edges"] > 0, "orphan identifiers absent from graph"
    print(f"      {gr['n_nodes']} nodes / {gr['n_edges']} edges; kinds {kinds}")

    repo.close()
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main(full="--fast" not in sys.argv)
