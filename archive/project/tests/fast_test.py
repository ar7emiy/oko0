"""Fast tier: the invariants, over a fixed 60-document slice.

WHY THIS EXISTS (T0.6)
----------------------
`smoke_test.py` regenerates all 2,000 notes and re-extracts them through the LLM
lanes. Measured: ~46 model calls a minute, and a run still inside Layer 1 after
50 minutes. It is the right gate and it is not affordable per change, so in
practice it stops being run and changes ship behind ad-hoc checks nobody has
audited. This is that gate, scoped.

It is NOT a replacement. The full run is what refreshes the published corpus
figures; this is what says "nothing structural broke" in about ten minutes.

WHAT IT ASSERTS, AND WHY EACH ONE IS HERE
-----------------------------------------
Every assertion below exists because the thing it checks was once silently
false. None of them is hypothetical.

* **Span grounding.** 349 of 1051 mentions once had a span that did not contain
  their own surface (D25). One of the four stated invariants, and nothing
  checked it for mentions.
* **Query vocabulary.** `ssn` and `dob` were offered to the query planner with
  no executor branch, so a plan filtering on them matched nothing and read as
  "no such entity" (D24).
* **Calibration.** The match prior was 16x too low for the life of the resolver
  because no run output ever named it (D17).
* **Entity count at the OPERATING point**, not the best point on the curve. The
  old gate asserted best-F1 > 0.6 and passed at 0.79 while the shipped
  threshold was splitting 42 entities into 515. Assert where the system runs.
* **The uncalibrated flag's NULLs.** A pandas NaN stored into a TEXT column
  becomes a REAL, and `WHERE uncalibrated IS NULL` then silently misses every
  calibrated edge.

THE SUBSET IS FIXED AND NAMED, deliberately. "The first N documents" would make
numbers incomparable across runs the moment the corpus regenerates differently.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import (audit, build_graph, embed_index, entity_resolution,  # noqa: E402
                 incremental, pipeline_v2, profiling)
from src.repository import Repository  # noqa: E402
from src.settings import CFG, Paths  # noqa: E402

BACKFILL = [f"DOC{i:05d}" for i in range(60)]
ARRIVING = [f"DOC{i:05d}" for i in range(60, 63)]

# Floors, not targets. Set below the measured values with room for ordinary
# run-to-run variation, so a failure means something structural broke rather
# than that a number wobbled.
MIN_SPAN_GROUNDING = 1.0        # this one is exact: it is an invariant
MIN_MENTION_PRECISION = 0.75    # measured 0.868
MIN_ENTITY_RECALL = 0.90        # measured 0.971
MIN_BCUBED_F1 = 0.75            # measured 0.887 at its best point
MAX_ENTITY_RATIO = 2.5          # measured 1.02x; the defect it catches was 12.3x


def main() -> None:
    repo = Repository()
    repo.reset()

    print("[1/7] guards")
    _assert_query_vocabulary_is_served()

    print("[2/7] profiling")
    profiling.run(repo)

    print(f"[3/7] extraction over {len(BACKFILL)} documents")
    r = pipeline_v2.run(repo, doc_ids=BACKFILL)
    print(f"      {r.get('n_mentions')} mentions; "
          f"{r.get('dropped_shape')} dropped by shape, "
          f"{r.get('dropped_identifier_shape')} by identifier shape")
    assert r["n_orphan_identifiers"] > 0, "orphan identifiers not being recorded"

    print("[4/7] invariant: every mention locates its own surface")
    ments = repo.table("mentions")
    bad = []
    for _, m in ments.iterrows():
        raw = (Paths.raw_notes / f"{m['doc_id']}.txt").read_text(encoding="utf-8")
        if raw[int(m["char_start"]):int(m["char_end"])] != m["surface"]:
            bad.append((m["doc_id"], int(m["char_start"]), m["surface"]))
    rate = 1 - len(bad) / max(len(ments), 1)
    assert rate >= MIN_SPAN_GROUNDING, (
        f"{len(bad)} of {len(ments)} mentions do not locate their own surface, "
        f"e.g. {bad[:3]}. Span grounding is an invariant: a mention whose "
        "offsets do not find its own text cannot be cited, highlighted, or "
        "matched to ground truth by overlap.")
    print(f"      {len(ments)}/{len(ments)} grounded")

    print("[5/7] extraction quality vs ground truth")
    man = json.loads(Paths.manifest_json.read_text(encoding="utf-8"))
    ep = audit.entity_precision(repo, man)
    rc = audit.entity_recall(repo, man)
    assert ep["precision"] >= MIN_MENTION_PRECISION, \
        f"mention precision regressed to {ep['precision']}"
    assert rc["recall"] >= MIN_ENTITY_RECALL, \
        f"entity recall regressed to {rc['recall']}"
    assert rc["n_docs_scored"] == len(BACKFILL), (
        f"recall was scored over {rc['n_docs_scored']} documents, not "
        f"{len(BACKFILL)} -- the scope is wrong, so the number is meaningless")
    print(f"      precision {ep['precision']:.3f} | recall {rc['recall']:.3f} "
          f"over {rc['n_docs_scored']} docs")
    worst = min(rc["by_variant_kind"].items(), key=lambda kv: kv[1]["recall"])
    print(f"      weakest variant: {worst[0]} {worst[1]['recall']:.3f}")

    print("[6/7] resolution + calibration")
    embed_index.run(repo)
    out = entity_resolution.run(repo)
    cal = out["calibration"]
    lam = cal["probability_two_random_records_match"]
    assert lam != 0.0001, "match prior is Splink's untouched 1e-4 default"
    assert 1e-4 < lam < 0.5, f"match prior {lam} is outside any defensible band"
    assert not cal["untrainable_agreement"], (
        f"{cal['untrainable_agreement']} kept an agreement level Splink had to "
        "invent; the two-pass prune should have dropped them")

    sae = repo.table("same_as_edges")
    n_flagged = int(sae["uncalibrated"].notna().sum())
    nulls = repo.conn.execute(
        "SELECT COUNT(*) FROM same_as_edges WHERE uncalibrated IS NULL").fetchone()[0]
    assert nulls == len(sae) - n_flagged, (
        f"{nulls} SQL NULLs but {len(sae) - n_flagged} unflagged rows -- NaN "
        "leaked into the column, so 'WHERE uncalibrated IS NULL' is unreliable")

    gold = ep["_mention_gold"]
    n_gold = len(set(gold.values()))
    sweep = audit.bcubed_sweep(repo, gold)
    best = sweep["best_by_f1"]
    ratio = out["n_entities"] / max(n_gold, 1)
    assert best["bcubed_f1"] >= MIN_BCUBED_F1, \
        f"B-cubed F1 regressed to {best['bcubed_f1']}"
    assert ratio < MAX_ENTITY_RATIO, (
        f"{out['n_entities']} entities at the operating threshold "
        f"{out['operating_threshold']} against {n_gold} gold ({ratio:.1f}x). "
        f"Check the match prior (currently {lam:.6f}) before the threshold.")
    print(f"      lambda {lam:.6f}; dropped as untrainable "
          f"{cal.get('dropped_untrainable')}; {n_flagged} edges flagged")
    print(f"      {out['n_entities']} entities vs {n_gold} gold ({ratio:.2f}x); "
          f"best F1 {best['bcubed_f1']:.3f} @ {best['threshold']}")

    print(f"[7/7] incremental ingest of {ARRIVING}")
    build_graph.build_graph(repo)
    build_graph.build_chunk_index(repo)
    pipeline_v2.run(repo, doc_ids=ARRIVING)
    embed_index.run(repo)
    inc = incremental.resolve_incremental(repo, ARRIVING, CFG.ER_LINK_THRESHOLD)
    sae2 = repo.table("same_as_edges")
    assert len(sae2) > len(sae), "the incremental pass appended no edges"
    nulls2 = repo.conn.execute(
        "SELECT COUNT(*) FROM same_as_edges WHERE uncalibrated IS NULL").fetchone()[0]
    assert nulls2 == len(sae2) - int(sae2["uncalibrated"].notna().sum()), \
        "NaN leaked into uncalibrated on the incremental path"
    print(f"      {inc.get('n_new_mentions')} new mentions, "
          f"{inc.get('n_pairs_scored')} pairs scored")

    repo.close()
    print("\nFAST TEST PASSED")


def _assert_query_vocabulary_is_served() -> None:
    """Every field offered to the query planner must have an executor branch."""
    from src import app, contracts

    def _field_enum(node):
        if isinstance(node, dict):
            if node.get("properties", {}).get("field", {}).get("enum"):
                return node["properties"]["field"]["enum"]
            for v in node.values():
                if (r := _field_enum(v)):
                    return r
        if isinstance(node, list):
            for v in node:
                if (r := _field_enum(v)):
                    return r
        return None

    declared = set(_field_enum(contracts.query_plan_schema()) or [])
    assert declared, "query_plan_schema exposes no field enum to check"
    assert declared == app._SERVED_FIELDS, (
        f"declared-but-unserved {sorted(declared - app._SERVED_FIELDS)}; "
        f"served-but-undeclared {sorted(app._SERVED_FIELDS - declared)}. A "
        "field the planner is offered but the executor cannot answer returns "
        "nothing and reads as 'no such entity'.")
    print(f"      query vocabulary: {len(declared)} fields, all served")


if __name__ == "__main__":
    main()
