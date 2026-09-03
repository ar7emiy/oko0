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

from src import (agent, audit, blocking, build_graph, corpus_gen,  # noqa: E402
                 embed_index, entity_resolution, leakage_guard,
                 pipeline_v2, profiling)
from src.hashing import verify_hashes, write_hashes  # noqa: E402
from src.repository import Repository  # noqa: E402
from src.settings import CFG, Paths  # noqa: E402


def _assert_query_vocabulary_is_served():
    """Every field offered to the query planner must have an executor branch.

    `ssn` sat in contracts.query_plan_schema for months with nothing in
    app._apply_filter to answer it, and `dob` alongside it. The planner would
    emit a valid plan filtering on ssn, the executor's haystack stayed empty,
    nothing matched, and the user was told there were no such entities -- for an
    identifier the store held. A capability gap that reads as a factual answer.

    Cheap to check, so it is checked rather than remembered.
    """
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
    unserved = declared - app._SERVED_FIELDS
    assert not unserved, (
        f"query_plan_schema offers {sorted(unserved)} to the planner but "
        "app._apply_filter has no branch for them; filtering on one would "
        "silently return nothing and read as 'no such entity'")
    undeclared = app._SERVED_FIELDS - declared
    assert not undeclared, (
        f"app._apply_filter serves {sorted(undeclared)} that the planner is "
        "never told about, so the capability is unreachable")
    print(f"      query vocabulary: {len(declared)} fields, all served")


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
    print("[1/9] generate corpus v2 + seal hashes")
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

    print("[2/9] guards")
    _assert_no_silent_fallback()
    g = leakage_guard.run_all_guards()
    assert all(v["ok"] for v in g.values())
    _assert_query_vocabulary_is_served()

    print("[3/9] profiling")
    repo = Repository()
    repo.reset()
    profiling.run(repo)
    docs = repo.table("documents")
    assert int((docs.claim_id == "UNKNOWN").sum()) == 0, "notes unattributed to a claim"
    assert docs.occurrence_id.nunique() > 1, "occurrence hierarchy missing"

    print("[4/9] layer 1 extraction")
    r = pipeline_v2.run(repo)
    assert r["n_orphan_identifiers"] > 0, "orphan identifiers not being recorded"

    print("[5/9] audit: extraction quality")
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

    print("[6/9] mention vector index")
    idx = embed_index.run(repo)
    assert idx["n_nodes"] > 0, "no mention vectors indexed"
    assert Paths.mention_index.exists(), "mention index not written to disk"
    print(f"      {idx['n_nodes']} mention vectors, dim {idx['dim']}")

    print("[7/9] entity resolution (Splink + embedding recall net)")
    from src.settings import genai_mode

    if genai_mode() == "offline":
        # The lane must REFUSE the offline stub rather than emit meaningless
        # buckets: the stub hashes character shingles, and its true/false pair
        # distributions overlap, so no threshold separates them. Assert the
        # refusal, then resolve deterministically for the rest of the run.
        try:
            blocking.attach_buckets(entity_resolution.build_mention_frame(repo))
        except blocking.EmbeddingBackendUnsuitable:
            print("      lane correctly refuses the offline embedding stub")
        else:
            raise AssertionError(
                "embedding lane accepted the offline stub; it must refuse, "
                "because lexical-overlap vectors cannot support semantic blocking")
        CFG.EMB_BLOCK_ENABLED = False

    out = entity_resolution.run(repo)
    assert out["n_entities"] > 1, "resolution produced no clusters"

    sae = repo.table("same_as_edges")
    assert "blocked_by" in sae.columns, "per-edge blocking provenance not stored"
    lanes = out["blocking_lanes"]
    assert lanes, "match_key provenance missing; lane contribution unmeasurable"
    assert sae["blocked_by"].notna().any(), "no edge recorded which rule found it"

    if CFG.EMB_BLOCK_ENABLED:
        # Online: the lane must actually be running, not silently disabled. A
        # resolution that quietly loses a whole candidate generator still
        # produces clusters, still passes every other assertion here, and simply
        # merges less.
        blk = out["embedding_blocking"]
        assert blk.get("enabled"), f"embedding blocking lane did not run: {blk}"
        assert blk["n_knn_edges"] > 0, "embedding lane proposed no neighbours at all"
        print(f"      lane yield: {lanes.get('emb_bucket', 0)} pairs no "
              f"deterministic rule proposed (of {len(sae)} scored)")
    else:
        print(f"      deterministic blocking only; {len(sae)} pairs scored")
    # ---- calibration ------------------------------------------------------
    # These exist because the match prior was 16x too low for as long as this
    # resolver had existed, and NOTHING here caught it: the B-cubed assertion
    # below passed at 0.79 while the operating point was splitting 42 entities
    # into 515. A gate insensitive to a 0.20 F1 defect is not a gate.
    cal = out["calibration"]
    lam = cal["probability_two_random_records_match"]
    assert lam != 0.0001, ("match prior is Splink's untouched 1e-4 default; the "
                           "deterministic estimate silently failed")
    assert 1e-4 < lam < 0.5, (
        f"match prior {lam} is outside any defensible band -- it claims "
        f"1 in {1 / lam:.0f} random mention pairs co-refer")

    # The label-free check: a globally unique identifier must outrank a name.
    # Comparisons with a substituted parameter are exempt -- npi's m cannot be
    # trained from 7 non-null values, and pretending otherwise is the failure
    # this whole block exists to prevent.
    weights = cal["agreement_weights_bits"]
    substituted = set(cal["by_comparison"])
    name_bits = weights.get("name_sorted", {}).get("match_weight_bits", 0.0)
    inverted = [(k, w["match_weight_bits"]) for k, w in weights.items()
                if k in ("npi", "email", "phone7", "dob")
                and k not in substituted
                and w["match_weight_bits"] < name_bits]
    if inverted:
        # KNOWN-FAILING, tracked as T0.5: u is inflated 3-37x because Splink's
        # random-pair sample is contaminated with true matches, which costs the
        # identifier comparisons more than the dense name ones. Reported rather
        # than asserted until a label-free u estimator exists; promote this to
        # an assert when T0.5 lands.
        print(f"      [T0.5] {len(inverted)} identifier comparisons still score "
              f"below name ({name_bits:+.1f}b): "
              + ", ".join(f"{k} {v:+.1f}b" for k, v in inverted))

    gold = audit.entity_precision(repo, m)["_mention_gold"]
    sweep = audit.bcubed_sweep(repo, gold)
    best = sweep["best_by_f1"]
    assert best["bcubed_f1"] > 0.6, f"B-cubed F1 regressed to {best['bcubed_f1']}"

    # Entity COUNT at the operating point, not just F1. B-cubed precision RISES
    # under over-splitting, so a badly fragmented run can post 0.97 precision and
    # a respectable best-F1 somewhere on the curve while the shipped threshold
    # produces six times too many entities. That is exactly what happened.
    # 4x is deliberately loose. The defect it exists to catch measured 12.3x
    # (515 entities against 42) on a 60-document subset, and a tight bound here
    # would be a fragile gate that fires on ordinary corpus variation instead of
    # on a broken prior. Tighten it once T0.5 lands and the residual ~1.9x
    # over-split closes.
    n_gold = len(set(gold.values()))
    ratio = out["n_entities"] / max(n_gold, 1)
    assert ratio < 4.0, (
        f"{out['n_entities']} entities at the operating threshold "
        f"{out['operating_threshold']} against {n_gold} in ground truth "
        f"({ratio:.1f}x) -- the corpus is being over-split. Check the match "
        f"prior (currently {lam:.6f}) before touching the threshold.")

    print(f"      {out['n_entities']} entities @ {out['operating_threshold']} "
          f"vs {n_gold} gold ({ratio:.2f}x); best F1 {best['bcubed_f1']:.3f} "
          f"@ {best['threshold']}")
    print(f"      match prior {lam:.6f}; "
          f"{cal['n_untrained_parameters']} substituted m/u parameters; "
          f"{out['n_edges_uncalibrated']} edges flagged")

    print("[8/9] global graph")
    gr = build_graph.build_graph(repo)
    kinds = gr["node_kinds"]
    for required in ("party", "identifier", "claim", "occurrence"):
        assert kinds.get(required, 0) > 0, f"graph missing {required} nodes"
    assert gr["n_orphan_identifier_edges"] > 0, "orphan identifiers absent from graph"
    print(f"      {gr['n_nodes']} nodes / {gr['n_edges']} edges; kinds {kinds}")

    print("[9/9] chunk index + layer 4 agent")
    ci = build_graph.build_chunk_index(repo)
    assert ci["n_chunks"] > 0, "no chunks indexed"
    assert Paths.chunk_index.exists(), "chunk index not written to disk"
    # Constructing the agent IS the assertion: it raises AgentStoreUnavailable
    # if either store is missing. This step exists because build_chunk_index was
    # never on the tested path, so the agent ran against an empty index and
    # answered from graph expansion alone without saying so.
    a = agent.ClaimScopedAgent(repo)
    claim = repo.table("documents")["claim_id"].iloc[0]
    hits = a.retrieve_chunks(claim, "who treated the claimant")
    assert hits, "scoped vector retrieval returned nothing"
    assert all(h["claim_id"] == claim for h in hits), "claim scope leaked"

    # INVARIANT: every document in the database is reachable by retrieval.
    #
    # This guards a bug that shipped and was invisible: ingest() never called
    # build_chunk_index, so notes arriving after backfill were resolved into
    # entities and added to the graph while their text never entered
    # chunks.faiss. Querying a claim with text copied verbatim out of one of
    # those notes returned zero chunks. Nothing failed -- the agent still
    # answered, from the backfill corpus only.
    indexed = {m.get("doc_id") for m in a.chunks._meta.values()}
    stored = set(repo.table("documents")["doc_id"])
    orphaned = stored - indexed
    assert not orphaned, (
        f"{len(orphaned)} document(s) exist but are absent from the chunk "
        f"index, so retrieval cannot reach them: {sorted(orphaned)[:5]}")

    # And citations must be checked, not trusted. The synthesis prompt demands
    # doc_id:span for every statement; before this, the returned strings were
    # passed through unverified and presented as provenance.
    fake = ["NO_SUCH_DOC:0-10", "banana", f"{hits[0]['doc_id']}:999999-1000000"]
    ok = [f"{hits[0]['doc_id']}:{hits[0]['char_start']}-{hits[0]['char_end']}"]
    verified, rejected = a._verify_citations(fake + ok, hits, [])
    assert verified == ok, f"a valid citation was rejected: {verified}"
    assert len(rejected) == len(fake), (
        f"fabricated citations passed verification: {rejected}")
    print(f"      citation check: {len(rejected)}/{len(fake)} fabrications caught")

    # INVARIANT: the exact lane can find what the indexer indexed.
    #
    # who_is_at applied its own normalization (phone_last7, address_key) while
    # build_graph keyed identifier nodes on normalize_identifier. The lookup
    # asked for ID::phone::7979442 while the index held ID::phone::3237979442,
    # so it returned [] for every phone and every address, always -- invisible
    # because answer() never called the exact lane. One shared normalization
    # function is the fix; this asserts the two sides still agree.
    obs = repo.table("identifier_observations")
    bound = obs[obs["subject_mention_id"].notna()]
    checked = resolved = 0
    for _, o in bound.iterrows():
        if checked >= 25:
            break
        checked += 1
        if a.who_is_at(o["kind"], o["value_raw"]):
            resolved += 1
    assert checked == 0 or resolved > 0, (
        "exact identifier lookup resolved none of "
        f"{checked} bound observations -- index and lookup normalization have "
        "drifted apart again")
    print(f"      exact lane: {resolved}/{checked} bound identifiers resolvable")
    print(f"      {ci['n_chunks']} chunks; {len(hits)} retrieved in scope")

    repo.close()
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main(full="--fast" not in sys.argv)
