"""Notebook 07 engine: honest evaluation against the sealed ground-truth manifest.

This module and the generator are the ONLY code permitted to read
data/ground_truth/. It joins pipeline outputs to the manifest and reports,
misses included:
  - GT entity count vs resolved-cluster count, with the GT<->system mapping.
  - Mention recall (found vs missed placements; misses itemized with
    doc_id+span+variant), broken out by segment_kind and hard-case category;
    precision including planted non_entities wrongly extracted.
  - Cluster quality: B-cubed precision/recall, plus over-merge/under-merge
    listings with the candidate-pair evidence trail that caused them.
  - Scan-coverage proof: per-doc % characters covered by the scan ledger,
    overall histogram, any doc < 100% with uncovered ranges, and overlap depth.
  - Corpus hash re-verification.
  - A one-line summary block.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from .hashing import verify_hashes
from .repository import Repository
from .settings import Paths


def _load_manifest() -> dict:
    return json.loads(Paths.manifest_json.read_text())


def _overlaps(s1, e1, s2, e2) -> bool:
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------------------
# Mention-level recall / precision
# ---------------------------------------------------------------------------
def mention_recall(repo: Repository, manifest: dict) -> dict:
    mentions = repo.table("mentions")
    men_by_doc = defaultdict(list)
    for _, m in mentions.iterrows():
        men_by_doc[m["doc_id"]].append((int(m["char_start"]), int(m["char_end"]),
                                        m["mention_id"], m["entity_class"]))

    ent_class = {e["gt_entity_id"]: e["class"] for e in manifest["entities"]}
    ent_tags = {e["gt_entity_id"]: e["hard_case_tags"] for e in manifest["entities"]}

    found = 0
    missed = []
    by_segment = defaultdict(lambda: [0, 0])   # kind -> [found, total]
    by_hardcase = defaultdict(lambda: [0, 0])
    placement_to_mention = {}

    for i, pl in enumerate(manifest["placements"]):
        cand = men_by_doc.get(pl["doc_id"], [])
        hit = None
        for (s, e, mid, mcls) in cand:
            if _overlaps(s, e, pl["char_start"], pl["char_end"]):
                hit = mid
                break
        seg = pl["segment_kind"]
        by_segment[seg][1] += 1
        tags = ent_tags.get(pl["gt_entity_id"], []) or ["(none)"]
        for t in tags:
            by_hardcase[t][1] += 1
        if hit:
            found += 1
            by_segment[seg][0] += 1
            for t in tags:
                by_hardcase[t][0] += 1
            placement_to_mention[i] = hit
        else:
            missed.append({"doc_id": pl["doc_id"], "span": [pl["char_start"], pl["char_end"]],
                           "surface_variant": pl["surface_variant"], "variant_kind": pl.get("variant_kind"),
                           "segment_kind": seg, "gt_entity_id": pl["gt_entity_id"],
                           "hard_cases": ent_tags.get(pl["gt_entity_id"], [])})

    total = len(manifest["placements"])
    return {
        "total_placements": total,
        "found": found,
        "recall": round(found / total, 4) if total else 0.0,
        "by_segment_kind": {k: {"found": v[0], "total": v[1], "recall": round(v[0]/v[1], 3)}
                            for k, v in sorted(by_segment.items())},
        "by_hard_case": {k: {"found": v[0], "total": v[1], "recall": round(v[0]/v[1], 3)}
                         for k, v in sorted(by_hardcase.items())},
        "missed_sample": missed[:40],
        "n_missed": len(missed),
        "_placement_to_mention": placement_to_mention,
    }


def mention_precision(repo: Repository, manifest: dict) -> dict:
    mentions = repo.table("mentions")
    placements_by_doc = defaultdict(list)
    for pl in manifest["placements"]:
        placements_by_doc[pl["doc_id"]].append((pl["char_start"], pl["char_end"], pl["gt_entity_id"]))
    non_by_doc = defaultdict(list)
    for ne in manifest["non_entities"]:
        non_by_doc[ne["doc_id"]].append((ne["char_start"], ne["char_end"], ne["kind"]))

    tp = 0
    fp_spurious = []
    fp_nonentity = 0
    mention_gold = {}
    for _, m in mentions.iterrows():
        s, e = int(m["char_start"]), int(m["char_end"])
        gold = None
        for (ps, pe, gid) in placements_by_doc.get(m["doc_id"], []):
            if _overlaps(s, e, ps, pe):
                gold = gid
                break
        if gold:
            tp += 1
            mention_gold[m["mention_id"]] = gold
        else:
            hit_ne = any(_overlaps(s, e, ns, nee) for (ns, nee, _) in non_by_doc.get(m["doc_id"], []))
            if hit_ne:
                fp_nonentity += 1
            fp_spurious.append({"doc_id": m["doc_id"], "surface": m["surface"],
                                "span": [s, e], "hit_nonentity": hit_ne})

    n = len(mentions)
    return {
        "n_mentions": n,
        "tp": tp,
        "fp": n - tp,
        "fp_nonentity_planted": fp_nonentity,
        "precision": round(tp / n, 4) if n else 0.0,
        "fp_sample": fp_spurious[:30],
        "_mention_gold": mention_gold,
    }


# ---------------------------------------------------------------------------
# Cluster quality (B-cubed) + over/under-merge
# ---------------------------------------------------------------------------
def cluster_quality(repo: Repository, mention_gold: dict) -> dict:
    members = repo.table("entity_members")
    mention_to_entity = {r["mention_id"]: r["entity_id"] for _, r in members.iterrows()}

    items = [(mid, gold, mention_to_entity.get(mid)) for mid, gold in mention_gold.items()
             if mention_to_entity.get(mid)]
    by_pred = defaultdict(list)
    by_gold = defaultdict(list)
    for mid, gold, pred in items:
        by_pred[pred].append((mid, gold))
        by_gold[gold].append((mid, pred))

    bp = br = 0.0
    for mid, gold, pred in items:
        same_pred = by_pred[pred]
        same_gold = by_gold[gold]
        correct_p = sum(1 for (_, g) in same_pred if g == gold)
        correct_r = sum(1 for (_, p) in same_gold if p == pred)
        bp += correct_p / len(same_pred)
        br += correct_r / len(same_gold)
    n = len(items) or 1
    bp /= n
    br /= n
    f1 = (2 * bp * br / (bp + br)) if (bp + br) else 0.0

    # over-merge: system cluster with >1 gold entity
    over = []
    for pred, lst in by_pred.items():
        golds = Counter(g for (_, g) in lst)
        if len(golds) > 1:
            over.append({"system_entity": pred, "gold_entities": dict(golds),
                         "n_mentions": len(lst)})
    # under-merge: gold entity split across >1 system cluster
    under = []
    for gold, lst in by_gold.items():
        preds = Counter(p for (_, p) in lst)
        if len(preds) > 1:
            under.append({"gold_entity": gold, "system_entities": dict(preds),
                          "n_mentions": len(lst)})

    return {
        "n_labeled_mentions": len(items),
        "bcubed_precision": round(bp, 4),
        "bcubed_recall": round(br, 4),
        "bcubed_f1": round(f1, 4),
        "n_over_merges": len(over),
        "n_under_merges": len(under),
        "over_merges_sample": sorted(over, key=lambda x: -x["n_mentions"])[:15],
        "under_merges_sample": sorted(under, key=lambda x: -x["n_mentions"])[:15],
    }


def over_merge_evidence(repo: Repository, over_sample: list) -> list:
    """Attach the candidate-pair evidence trail that caused each over-merge."""
    if not over_sample:
        return []
    members = repo.table("entity_members")
    ent_mentions = defaultdict(list)
    for _, r in members.iterrows():
        ent_mentions[r["entity_id"]].append(r["mention_id"])
    cp = repo.table("candidate_pairs")
    pair_idx = {}
    for _, r in cp.iterrows():
        pair_idx[frozenset((r["mention_id_a"], r["mention_id_b"]))] = r.to_dict()

    out = []
    for om in over_sample[:8]:
        mids = ent_mentions[om["system_entity"]]
        trail = []
        for i in range(len(mids)):
            for j in range(i + 1, len(mids)):
                pr = pair_idx.get(frozenset((mids[i], mids[j])))
                if pr and pr.get("band") in ("link", "adjudicate"):
                    feats = json.loads(pr["feature_json"]) if pr["feature_json"] else {}
                    trail.append({"pair": [mids[i], mids[j]], "gen_passes": pr["gen_passes"],
                                  "score": pr["score"], "verdict": pr.get("verdict"),
                                  "name_jw": feats.get("name_jw"),
                                  "adjudicator": feats.get("_adjudicator", {}).get("rationale")})
                if len(trail) >= 4:
                    break
            if len(trail) >= 4:
                break
        out.append({"system_entity": om["system_entity"], "gold_entities": om["gold_entities"],
                    "evidence_trail": trail})
    return out


# ---------------------------------------------------------------------------
# Entity-count mapping
# ---------------------------------------------------------------------------
def entity_mapping(repo: Repository, manifest: dict, mention_gold: dict) -> dict:
    members = repo.table("entity_members")
    mention_to_entity = {r["mention_id"]: r["entity_id"] for _, r in members.iterrows()}
    sys_to_gold = defaultdict(Counter)
    for mid, gold in mention_gold.items():
        eid = mention_to_entity.get(mid)
        if eid:
            sys_to_gold[eid][gold] += 1
    mapping = {eid: c.most_common(1)[0][0] for eid, c in sys_to_gold.items()}
    gold_covered = set(mapping.values())
    all_gold = {e["gt_entity_id"] for e in manifest["entities"]}
    return {
        "gt_entity_count": len(all_gold),
        "system_entity_count": int(repo.df("SELECT COUNT(*) c FROM entities")["c"].iloc[0]),
        "gt_entities_with_a_system_cluster": len(gold_covered),
        "gt_entities_never_recovered": sorted(all_gold - gold_covered)[:30],
        "n_gt_never_recovered": len(all_gold - gold_covered),
    }


# ---------------------------------------------------------------------------
# Scan-coverage proof
# ---------------------------------------------------------------------------
def coverage_proof(repo: Repository) -> dict:
    docs = repo.table("documents").set_index("doc_id")["n_chars"].to_dict()
    led = repo.table("scan_ledger")
    per_doc = {}
    hist = Counter()
    overlap_total = 0
    scanned_total = 0
    char_total = 0
    under = []
    for doc_id, n in docs.items():
        char_total += n
        depth = [0] * n
        for _, r in led[led["doc_id"] == doc_id].iterrows():
            for i in range(int(r["char_start"]), min(int(r["char_end"]), n)):
                depth[i] += 1
        covered = sum(1 for d in depth if d >= 1)
        overlap = sum(1 for d in depth if d >= 2)
        scanned_total += covered
        overlap_total += overlap
        pct = covered / n if n else 1.0
        per_doc[doc_id] = pct
        hist[round(pct, 1)] += 1
        if covered < n:
            ranges = _uncovered_ranges(depth)
            under.append({"doc_id": doc_id, "coverage": round(pct, 4), "uncovered_ranges": ranges[:10]})
    return {
        "overall_coverage": round(scanned_total / char_total, 6) if char_total else 1.0,
        "n_docs": len(docs),
        "n_docs_full_coverage": sum(1 for p in per_doc.values() if p >= 0.99999),
        "coverage_histogram": dict(sorted(hist.items())),
        "overlap_depth_chars": overlap_total,
        "overlap_fraction": round(overlap_total / char_total, 6) if char_total else 0.0,
        "docs_under_100pct": under[:20],
        "n_docs_under_100pct": len(under),
    }


def _uncovered_ranges(depth) -> list:
    ranges = []
    start = None
    for i, d in enumerate(depth):
        if d == 0 and start is None:
            start = i
        elif d != 0 and start is not None:
            ranges.append([start, i])
            start = None
    if start is not None:
        ranges.append([start, len(depth)])
    return ranges


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------
def run(repo: Repository) -> dict:
    manifest = _load_manifest()
    hashes = verify_hashes("audit")
    rec = mention_recall(repo, manifest)
    prec = mention_precision(repo, manifest)
    clu = cluster_quality(repo, prec["_mention_gold"])
    clu_ev = over_merge_evidence(repo, clu["over_merges_sample"])
    emap = entity_mapping(repo, manifest, prec["_mention_gold"])
    cov = coverage_proof(repo)

    top_misses = _top_miss_patterns(rec)
    summary = (
        f"GT entities: {emap['gt_entity_count']} | extracted+resolved: {emap['system_entity_count']} | "
        f"mention recall: {rec['recall']*100:.1f}% | precision: {prec['precision']*100:.1f}% | "
        f"B3 P/R: {clu['bcubed_precision']:.2f}/{clu['bcubed_recall']:.2f} | "
        f"coverage: {cov['overall_coverage']*100:.2f}% | "
        f"top miss patterns: {top_misses}"
    )
    report = {
        "summary": summary,
        "hash_verification": hashes,
        "entity_mapping": emap,
        "mention_recall": {k: v for k, v in rec.items() if not k.startswith("_")},
        "mention_precision": {k: v for k, v in prec.items() if not k.startswith("_")},
        "cluster_quality": clu,
        "over_merge_evidence": clu_ev,
        "coverage_proof": cov,
        "top_miss_patterns": top_misses,
    }
    return report


def _top_miss_patterns(rec: dict) -> list:
    pats = []
    for kind, v in rec["by_hard_case"].items():
        if v["total"] >= 5 and v["recall"] < 0.95:
            pats.append((f"hardcase:{kind}", round(1 - v["recall"], 2)))
    for kind, v in rec["by_segment_kind"].items():
        if v["total"] >= 5 and v["recall"] < 0.95:
            pats.append((f"segment:{kind}", round(1 - v["recall"], 2)))
    pats.sort(key=lambda x: -x[1])
    return [f"{k} (miss {int(r*100)}%)" for k, r in pats[:5]]
