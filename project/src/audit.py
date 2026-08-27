"""Honest evaluation against the sealed ground-truth manifest (schema v2).

This module and src/corpus_gen.py + src/ablation.py are the only code permitted
to read data/ground_truth. This one is the auditor.

Reports, misses included:
  * entity mention recall / precision, broken out by segment kind and hard case
  * IDENTIFIER recall, with the orphan (no name co-located) subset called out
    separately -- that subset is the direct test of identifier-first resolution
  * COREFERENCE referent accuracy BY HOP COUNT -- the direct test of the
    multi-hop "hopping" failure mode
  * EVENT mention recall
  * cluster quality (B-cubed) across resolution thresholds, since identity is
    threshold-derived rather than a single stored merge
  * scan coverage -- reported as a HYGIENE CHECK, not a quality metric: it
    proves the extractor looked at every character, not that it found what was
    there. It is necessary, not sufficient.
  * corpus hash re-verification
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


def _placements(manifest, kind):
    return [p for p in manifest["placements"] if p["kind"] == kind]


# ---------------------------------------------------------------------------
# Entity mentions
# ---------------------------------------------------------------------------
def entity_recall(repo: Repository, manifest: dict) -> dict:
    mentions = repo.table("mentions")
    by_doc = defaultdict(list)
    for _, m in mentions.iterrows():
        by_doc[m["doc_id"]].append((int(m["char_start"]), int(m["char_end"]),
                                    m["mention_id"]))

    tags = {e["gt_entity_id"]: e["hard_case_tags"] for e in manifest["entities"]}
    placements = _placements(manifest, "entity")

    found, missed = 0, []
    by_segment = defaultdict(lambda: [0, 0])
    by_hardcase = defaultdict(lambda: [0, 0])
    by_variant = defaultdict(lambda: [0, 0])

    for pl in placements:
        hit = None
        for (s, e, mid) in by_doc.get(pl["doc_id"], []):
            if _overlaps(s, e, pl["char_start"], pl["char_end"]):
                hit = mid
                break
        seg = pl["segment_kind"]
        vk = pl.get("variant_kind", "?")
        by_segment[seg][1] += 1
        by_variant[vk][1] += 1
        t = tags.get(pl["gt_id"], []) or ["(none)"]
        for x in t:
            by_hardcase[x][1] += 1
        if hit:
            found += 1
            by_segment[seg][0] += 1
            by_variant[vk][0] += 1
            for x in t:
                by_hardcase[x][0] += 1
        else:
            missed.append({"doc_id": pl["doc_id"],
                           "span": [pl["char_start"], pl["char_end"]],
                           "surface": pl["surface"], "variant_kind": vk,
                           "segment_kind": seg, "hard_cases": tags.get(pl["gt_id"], [])})

    n = len(placements)
    rate = lambda d: {k: {"found": v[0], "total": v[1],
                          "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                      for k, v in sorted(d.items())}
    return {
        "total": n, "found": found,
        "recall": round(found / n, 4) if n else 0.0,
        "n_missed": len(missed),
        "by_segment_kind": rate(by_segment),
        "by_variant_kind": rate(by_variant),
        "by_hard_case": rate(by_hardcase),
        "missed_sample": missed[:25],
    }


def entity_precision(repo: Repository, manifest: dict) -> dict:
    """Precision of emitted name mentions, plus the mention->gold map for B-cubed."""
    mentions = repo.table("mentions")
    gold_by_doc = defaultdict(list)
    for pl in _placements(manifest, "entity"):
        gold_by_doc[pl["doc_id"]].append((pl["char_start"], pl["char_end"], pl["gt_id"]))
    non_by_doc = defaultdict(list)
    for ne in manifest["non_entities"]:
        non_by_doc[ne["doc_id"]].append((ne["char_start"], ne["char_end"]))

    tp, fp, fp_non = 0, [], 0
    mention_gold = {}
    for _, m in mentions.iterrows():
        s, e = int(m["char_start"]), int(m["char_end"])
        gold = None
        for (ps, pe, gid) in gold_by_doc.get(m["doc_id"], []):
            if _overlaps(s, e, ps, pe):
                gold = gid
                break
        if gold:
            tp += 1
            mention_gold[m["mention_id"]] = gold
        else:
            hit_ne = any(_overlaps(s, e, a, b) for (a, b) in non_by_doc.get(m["doc_id"], []))
            fp_non += 1 if hit_ne else 0
            fp.append({"doc_id": m["doc_id"], "surface": m["surface"],
                       "span": [s, e], "hit_planted_non_entity": hit_ne})
    n = len(mentions)
    return {
        "n_mentions": n, "tp": tp, "fp": n - tp,
        "precision": round(tp / n, 4) if n else 0.0,
        "fp_planted_non_entity": fp_non,
        "fp_sample": fp[:20],
        "_mention_gold": mention_gold,
    }


# ---------------------------------------------------------------------------
# Identifiers -- the orphan subset is the real test
# ---------------------------------------------------------------------------
def identifier_recall(repo: Repository, manifest: dict) -> dict:
    """Recall over planted identifier mentions.

    `orphan` mentions have no name co-located, so recovering them proves the
    identifier itself was extracted rather than inferred from a nearby name.
    """
    spans_by_doc = defaultdict(list)
    try:
        obs = repo.table("identifier_observations")
        for _, o in obs.iterrows():
            spans_by_doc[o["doc_id"]].append((int(o["char_start"]), int(o["char_end"])))
    except Exception:
        pass
    # fall back to assertion spans for identifiers that did bind to a subject
    for _, a in repo.table("assertions").iterrows():
        spans_by_doc[a["source_doc_id"]].append(
            (int(a["source_span_start"]), int(a["source_span_end"])))

    placements = _placements(manifest, "identifier")
    found = 0
    by_kind = defaultdict(lambda: [0, 0])
    orphan = [0, 0]
    named = [0, 0]
    missed = []
    for pl in placements:
        kind = pl.get("identifier_kind", "?")
        is_orphan = bool(pl.get("orphan"))
        by_kind[kind][1] += 1
        (orphan if is_orphan else named)[1] += 1
        hit = any(_overlaps(s, e, pl["char_start"], pl["char_end"])
                  for (s, e) in spans_by_doc.get(pl["doc_id"], []))
        if hit:
            found += 1
            by_kind[kind][0] += 1
            (orphan if is_orphan else named)[0] += 1
        else:
            missed.append({"doc_id": pl["doc_id"], "kind": kind,
                           "surface": pl["surface"], "orphan": is_orphan,
                           "span": [pl["char_start"], pl["char_end"]]})
    n = len(placements)
    return {
        "total": n, "found": found,
        "recall": round(found / n, 4) if n else 0.0,
        "by_kind": {k: {"found": v[0], "total": v[1],
                        "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                    for k, v in sorted(by_kind.items())},
        "orphan": {"found": orphan[0], "total": orphan[1],
                   "recall": round(orphan[0] / orphan[1], 4) if orphan[1] else 0.0},
        "named": {"found": named[0], "total": named[1],
                  "recall": round(named[0] / named[1], 4) if named[1] else 0.0},
        "missed_sample": missed[:20],
    }


# ---------------------------------------------------------------------------
# Coreference -- accuracy BY HOP COUNT
# ---------------------------------------------------------------------------
def coref_accuracy(repo: Repository, manifest: dict) -> dict:
    """Did coref bind each anaphor to the RIGHT entity, and how does that decay
    as the chain lengthens?

    An anaphor is scored correct when the antecedent the resolver chose overlaps
    a planted mention of the true referent entity. Broken out by hop count: hop 1
    points straight at a name, hop >= 2 points at another anaphor.
    """
    try:
        links = repo.table("coref_links")
    except Exception:
        return {"available": False, "reason": "coref_links table absent"}
    if links.empty:
        return {"available": False, "reason": "no coref links produced"}

    # planted entity mention spans, per doc, by entity
    ent_spans = defaultdict(list)
    for pl in _placements(manifest, "entity"):
        ent_spans[pl["doc_id"]].append((pl["char_start"], pl["char_end"], pl["gt_id"]))

    by_anaphor = {}
    for _, l in links.iterrows():
        by_anaphor[(l["doc_id"], int(l["anaphor_start"]), int(l["anaphor_end"]))] = l

    total = correct = attempted = 0
    by_hop = defaultdict(lambda: [0, 0, 0])     # hops -> [correct, attempted, total]
    by_kind = defaultdict(lambda: [0, 0, 0])
    wrong = []

    for c in manifest["coref_chains"]:
        key = (c["doc_id"], c["anaphor_start"], c["anaphor_end"])
        hops = c["hops"]
        kind = c["anaphor_kind"]
        total += 1
        by_hop[hops][2] += 1
        by_kind[kind][2] += 1
        link = by_anaphor.get(key)
        if link is None:
            continue                       # not attempted by the resolver
        attempted += 1
        by_hop[hops][1] += 1
        by_kind[kind][1] += 1
        a_s, a_e = link["antecedent_start"], link["antecedent_end"]
        if a_s is None:
            continue
        ok = any(_overlaps(int(a_s), int(a_e), s, e) and gid == c["referent_gt_entity_id"]
                 for (s, e, gid) in ent_spans.get(c["doc_id"], []))
        if ok:
            correct += 1
            by_hop[hops][0] += 1
            by_kind[kind][0] += 1
        elif len(wrong) < 20:
            wrong.append({"doc_id": c["doc_id"], "anaphor": c["anaphor_text"],
                          "hops": hops, "true_referent": c["referent_gt_entity_id"],
                          "chose": link["antecedent_surface"]})

    def fmt(d):
        return {k: {"correct": v[0], "attempted": v[1], "total": v[2],
                    "accuracy_of_attempted": round(v[0] / v[1], 3) if v[1] else 0.0,
                    "accuracy_of_all": round(v[0] / v[2], 3) if v[2] else 0.0}
                for k, v in sorted(d.items())}

    return {
        "available": True,
        "total_anaphora": total, "attempted": attempted, "correct": correct,
        "coverage": round(attempted / total, 4) if total else 0.0,
        "accuracy_of_attempted": round(correct / attempted, 4) if attempted else 0.0,
        "accuracy_overall": round(correct / total, 4) if total else 0.0,
        "by_hops": fmt(by_hop),
        "by_kind": fmt(by_kind),
        "wrong_sample": wrong,
    }


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def event_recall(repo: Repository, manifest: dict) -> dict:
    """Recall over planted event mentions (dated actions with no external id)."""
    spans_by_doc = defaultdict(list)
    for _, a in repo.table("assertions").iterrows():
        spans_by_doc[a["source_doc_id"]].append(
            (int(a["source_span_start"]), int(a["source_span_end"])))
    for _, m in repo.table("mentions").iterrows():
        spans_by_doc[m["doc_id"]].append((int(m["char_start"]), int(m["char_end"])))

    placements = _placements(manifest, "event")
    found = 0
    by_type = defaultdict(lambda: [0, 0])
    for pl in placements:
        et = pl.get("event_type", "?")
        by_type[et][1] += 1
        if any(_overlaps(s, e, pl["char_start"], pl["char_end"])
               for (s, e) in spans_by_doc.get(pl["doc_id"], [])):
            found += 1
            by_type[et][0] += 1
    n = len(placements)
    return {
        "total": n, "found": found,
        "recall": round(found / n, 4) if n else 0.0,
        "by_type": {k: {"found": v[0], "total": v[1],
                        "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                    for k, v in sorted(by_type.items())},
        "note": "event extraction is not yet implemented; a low number here is expected",
    }


# ---------------------------------------------------------------------------
# Cluster quality
# ---------------------------------------------------------------------------
def cluster_quality(repo: Repository, mention_gold: dict) -> dict:
    members = repo.table("entity_members")
    if members.empty:
        return {"available": False, "reason": "no resolved entities"}
    m2e = {r["mention_id"]: r["entity_id"] for _, r in members.iterrows()}
    items = [(mid, g, m2e[mid]) for mid, g in mention_gold.items() if mid in m2e]
    if not items:
        return {"available": False, "reason": "no labeled mentions in clusters"}

    by_pred, by_gold = defaultdict(list), defaultdict(list)
    for mid, g, p in items:
        by_pred[p].append(g)
        by_gold[g].append(p)

    bp = br = 0.0
    for mid, g, p in items:
        bp += by_pred[p].count(g) / len(by_pred[p])
        br += by_gold[g].count(p) / len(by_gold[g])
    n = len(items)
    bp, br = bp / n, br / n
    f1 = (2 * bp * br / (bp + br)) if (bp + br) else 0.0

    over = [{"system_entity": p, "gold_entities": dict(Counter(gs)), "n": len(gs)}
            for p, gs in by_pred.items() if len(set(gs)) > 1]
    under = [{"gold_entity": g, "system_entities": dict(Counter(ps)), "n": len(ps)}
             for g, ps in by_gold.items() if len(set(ps)) > 1]
    return {
        "available": True,
        "n_labeled_mentions": n,
        "bcubed_precision": round(bp, 4), "bcubed_recall": round(br, 4),
        "bcubed_f1": round(f1, 4),
        "n_over_merges": len(over), "n_under_merges": len(under),
        "over_merges_sample": sorted(over, key=lambda x: -x["n"])[:10],
        "under_merges_sample": sorted(under, key=lambda x: -x["n"])[:10],
    }


def bcubed_sweep(repo: Repository, mention_gold: dict,
                 thresholds=None) -> dict:
    """B-cubed at every threshold, because identity is a threshold-derived view.

    A single B-cubed number is misleading under this architecture: the same
    stored edges yield different partitions at different read thresholds. The
    operating point should be chosen from this curve, not assumed.
    """
    from .settings import CFG
    from . import entity_resolution as er
    thresholds = thresholds or CFG.ER_THRESHOLD_SWEEP
    edges = repo.table("same_as_edges")
    if edges.empty:
        return {"available": False}
    live = edges[edges["suppressed_reason"].isna()].rename(
        columns={"mention_id_a": "mention_id_l", "mention_id_b": "mention_id_r",
                 "probability": "match_probability"})
    mention_ids = repo.table("mentions")["mention_id"].tolist()

    rows = []
    for t in thresholds:
        labels = er.cluster_at(live, mention_ids, t)
        by_pred, by_gold = defaultdict(list), defaultdict(list)
        items = [(m, g, labels[m]) for m, g in mention_gold.items() if m in labels]
        for m, g, p in items:
            by_pred[p].append(g)
            by_gold[g].append(p)
        if not items:
            continue
        bp = sum(by_pred[p].count(g) / len(by_pred[p]) for _, g, p in items) / len(items)
        br = sum(by_gold[g].count(p) / len(by_gold[g]) for _, g, p in items) / len(items)
        f1 = (2 * bp * br / (bp + br)) if (bp + br) else 0.0
        rows.append({"threshold": t, "n_entities": len(set(labels.values())),
                     "bcubed_precision": round(bp, 4), "bcubed_recall": round(br, 4),
                     "bcubed_f1": round(f1, 4)})
    best = max(rows, key=lambda r: r["bcubed_f1"]) if rows else None
    return {"available": True, "curve": rows, "best_by_f1": best}


def entity_mapping(repo: Repository, manifest: dict, mention_gold: dict) -> dict:
    members = repo.table("entity_members")
    m2e = {r["mention_id"]: r["entity_id"] for _, r in members.iterrows()} if not members.empty else {}
    sys_to_gold = defaultdict(Counter)
    for mid, g in mention_gold.items():
        if mid in m2e:
            sys_to_gold[m2e[mid]][g] += 1
    covered = {c.most_common(1)[0][0] for c in sys_to_gold.values()}
    all_gold = {e["gt_entity_id"] for e in manifest["entities"]}
    n_sys = int(repo.df("SELECT COUNT(*) c FROM entities")["c"].iloc[0])
    return {
        "gt_entity_count": len(all_gold),
        "system_entity_count": n_sys,
        "gt_recovered": len(covered),
        "n_gt_never_recovered": len(all_gold - covered),
        "gt_never_recovered_sample": sorted(all_gold - covered)[:20],
    }


# ---------------------------------------------------------------------------
# Scan coverage -- HYGIENE CHECK, not a quality metric
# ---------------------------------------------------------------------------
def coverage_check(repo: Repository) -> dict:
    docs = repo.table("documents").set_index("doc_id")["n_chars"].to_dict()
    led = repo.table("scan_ledger")
    covered_total = char_total = 0
    under = []
    for doc_id, n in docs.items():
        char_total += n
        mask = bytearray(n)
        for _, r in led[led["doc_id"] == doc_id].iterrows():
            for i in range(int(r["char_start"]), min(int(r["char_end"]), n)):
                mask[i] = 1
        c = sum(mask)
        covered_total += c
        if c < n:
            under.append({"doc_id": doc_id, "coverage": round(c / n, 4)})
    return {
        "overall_coverage": round(covered_total / char_total, 6) if char_total else 1.0,
        "n_docs": len(docs),
        "n_docs_under_100pct": len(under),
        "docs_under_sample": under[:10],
        "interpretation": ("HYGIENE CHECK ONLY: proves every character was read by "
                           "some extractor. It does NOT indicate anything was found "
                           "correctly -- necessary, not sufficient."),
    }


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------
def run(repo: Repository) -> dict:
    manifest = _load_manifest()
    hashes = verify_hashes("audit")

    ent_r = entity_recall(repo, manifest)
    ent_p = entity_precision(repo, manifest)
    ident = identifier_recall(repo, manifest)
    coref = coref_accuracy(repo, manifest)
    events = event_recall(repo, manifest)
    clu = cluster_quality(repo, ent_p["_mention_gold"])
    emap = entity_mapping(repo, manifest, ent_p["_mention_gold"])
    cov = coverage_check(repo)

    summary = (
        f"GT entities: {emap['gt_entity_count']} | resolved: {emap['system_entity_count']} | "
        f"entity recall: {ent_r['recall']*100:.1f}% | precision: {ent_p['precision']*100:.1f}% | "
        f"identifier recall: {ident['recall']*100:.1f}% (orphan {ident['orphan']['recall']*100:.1f}%) | "
        f"coref: {coref.get('accuracy_overall', 0)*100:.1f}% | "
        f"B3 P/R: {clu.get('bcubed_precision', 0):.2f}/{clu.get('bcubed_recall', 0):.2f}"
    )
    return {
        "summary": summary,
        "manifest_schema_version": manifest.get("schema_version"),
        "hash_verification": hashes,
        "entity_recall": {k: v for k, v in ent_r.items() if not k.startswith("_")},
        "entity_precision": {k: v for k, v in ent_p.items() if not k.startswith("_")},
        "identifier_recall": ident,
        "coref_accuracy": coref,
        "event_recall": events,
        "cluster_quality": clu,
        "entity_mapping": emap,
        "coverage_check": cov,
        "top_miss_patterns": _top_misses(ent_r),
    }


def _top_misses(ent_r: dict) -> list:
    pats = []
    for k, v in ent_r["by_hard_case"].items():
        if v["total"] >= 20 and v["recall"] < 0.95:
            pats.append((f"hardcase:{k}", 1 - v["recall"]))
    for k, v in ent_r["by_segment_kind"].items():
        if v["total"] >= 20 and v["recall"] < 0.95:
            pats.append((f"segment:{k}", 1 - v["recall"]))
    for k, v in ent_r["by_variant_kind"].items():
        if v["total"] >= 20 and v["recall"] < 0.95:
            pats.append((f"variant:{k}", 1 - v["recall"]))
    pats.sort(key=lambda x: -x[1])
    return [f"{k} (miss {r*100:.0f}%)" for k, r in pats[:6]]
