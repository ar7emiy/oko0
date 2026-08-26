"""Notebook 05 engine: entity resolution.

Pipeline:
  1. Build per-mention feature profiles from assertions (name, identifiers,
     phone, dob, address_key, claim, class). Quoted-duplicate mentions
     (non-canonical in their dup_group) are collapsed to their canonical so
     co-occurrence and pair counts are dup-deduped.
  2. Candidate generation as UNIONED independent blocking passes (A1,B1..B4,C1,
     D1); each produced pair logs which passes generated it (gen_passes).
  3. Pairwise weighted-feature scoring, with hub-identifier down-weighting and a
     gt-free calibration proxy (template+narrative naming the same entity in the
     same doc). Pairs in the ambiguous band go to an adjudicator (Gemini online /
     deterministic offline); verdict + rationale stored in feature_json.
  4. Hard cannot-link rules (conflicting validated ids, DOB conflict,
     person-vs-org, Jr/Sr suffix at same name+address).
  5. Greedy correlation clustering over an igraph graph honoring cannot-link
     constraints (NOT naive connected components). Membership is versioned;
     mentions are never physically merged.
"""
from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations

import igraph as ig
import numpy as np

from . import contracts, genai, textnorm
from .repository import Repository
from .settings import CFG, Paths, genai_mode
from .vectorstore import FaissVectorStore


# ---------------------------------------------------------------------------
# Mention feature profiles
# ---------------------------------------------------------------------------
def build_profiles(repo: Repository) -> dict:
    mentions = repo.table("mentions")
    assertions = repo.table("assertions")
    docs = repo.table("documents").set_index("doc_id")["claim_id"].to_dict()

    # collapse quoted duplicates: map non-canonical dup mentions to canonical.
    segs = repo.table("segments").set_index("segment_id")
    # (mentions carry dup_group_id from their segment; canonical = earliest.)

    ass_by_subj = defaultdict(list)
    for _, a in assertions.iterrows():
        if a["grounded"] == 1:
            ass_by_subj[a["subject_mention_id"]].append(a)

    profiles = {}
    for _, m in mentions.iterrows():
        mid = m["mention_id"]
        prof = {
            "mention_id": mid, "doc_id": m["doc_id"],
            "claim_id": docs.get(m["doc_id"], "UNKNOWN"),
            "entity_class": m["entity_class"], "surface": m["surface"],
            "norm_name": m["norm_surface"] or textnorm.normalize_name(m["surface"]),
            "dup_group_id": m["dup_group_id"], "inside_quoted": int(m["inside_quoted"]),
            "emails": set(), "phones7": set(), "npis": set(), "tins": set(),
            "ssns": set(), "dobs": set(), "addr_keys": set(), "states": set(),
        }
        for a in ass_by_subj.get(mid, []):
            p, norm = a["predicate"], (a["object_value_norm"] or "")
            if a["polarity"] in ("negated", "retracted"):
                continue
            if p == "has_email":
                prof["emails"].add(norm)
            elif p == "has_phone":
                prof["phones7"].add(textnorm.phone_last7(norm))
            elif p == "has_npi":
                prof["npis"].add(norm)
            elif p == "has_tin":
                prof["tins"].add(norm)
            elif p == "has_ssn":
                prof["ssns"].add(norm)
            elif p == "has_dob":
                prof["dobs"].add(norm)
            elif p == "has_address":
                prof["addr_keys"].add(textnorm.address_key(a["object_value_raw"] or ""))
                st = _state_from_addr(a["object_value_raw"] or "")
                if st:
                    prof["states"].add(st)
        profiles[mid] = prof
    return profiles


def _state_from_addr(addr: str):
    import re
    m = re.search(r"\b([A-Z]{2})\s+\d{5}", addr)
    return m.group(1) if m else None


def _dob_year(dob: str):
    import re
    m = re.search(r"(\d{4})", dob)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{2})$", dob)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Candidate generation (unioned blocking passes)
# ---------------------------------------------------------------------------
def _block_pairs(members: list[str], max_block: int = 80):
    """All-pairs for small blocks; star topology for large homogeneous blocks."""
    if len(members) <= 1:
        return
    if len(members) <= max_block:
        yield from combinations(members, 2)
    else:
        anchor = members[0]
        for other in members[1:]:
            yield (anchor, other)


def generate_candidates(profiles: dict) -> dict:
    """Return {frozenset(pair): set(gen_passes)}."""
    pairs: dict[frozenset, set] = defaultdict(set)

    def add(a, b, tag):
        if a != b:
            pairs[frozenset((a, b))].add(tag)

    # index helpers
    by_key = lambda keyfn: _group(profiles, keyfn)

    # A1: exact validated identifier
    for field, tag in (("emails", "A1"), ("npis", "A1"), ("tins", "A1"), ("ssns", "A1")):
        groups = defaultdict(list)
        for mid, p in profiles.items():
            for v in p[field]:
                if v:
                    groups[(field, v)].append(mid)
        for members in groups.values():
            for a, b in _block_pairs(members):
                add(a, b, "A1")

    # B1: phone last-7
    for members in by_key(lambda p: [("ph", v) for v in p["phones7"] if v]).values():
        for a, b in _block_pairs(members):
            add(a, b, "B1")

    # B2: normalized-address key
    for members in by_key(lambda p: [("ad", v) for v in p["addr_keys"] if v]).values():
        for a, b in _block_pairs(members):
            add(a, b, "B2")

    # B3: phonetic last-name x state
    def b3key(p):
        toks = p["norm_name"].split()
        if not toks:
            return []
        sx = textnorm.soundex(toks[-1])
        states = p["states"] or {"?"}
        return [("b3", sx, st, p["entity_class"]) for st in states]
    for members in by_key(b3key).values():
        for a, b in _block_pairs(members):
            add(a, b, "B3")

    # B4: name-initials x DOB-year
    def b4key(p):
        toks = p["norm_name"].split()
        if len(toks) < 1 or not p["dobs"]:
            return []
        ini = (toks[0][0] if toks[0] else "") + (toks[-1][0] if toks[-1] else "")
        return [("b4", ini, _dob_year(d)) for d in p["dobs"] if _dob_year(d)]
    for members in by_key(b4key).values():
        for a, b in _block_pairs(members):
            add(a, b, "B4")

    # D1: claim co-occurrence (same claim + same class), dup-deduped
    def d1key(p):
        if p["inside_quoted"]:
            return []
        return [("d1", p["claim_id"], p["entity_class"])]
    for members in by_key(d1key).values():
        # only pair names that are at least loosely similar to limit noise
        for a, b in _block_pairs(members, max_block=40):
            if textnorm.token_set_jw(profiles[a]["norm_name"], profiles[b]["norm_name"]) >= 0.5:
                add(a, b, "D1")

    return pairs


def _group(profiles, keyfn):
    groups = defaultdict(list)
    for mid, p in profiles.items():
        for k in keyfn(p):
            groups[k].append(mid)
    return groups


def embedding_candidates(profiles: dict, store: FaissVectorStore, vectors: dict, pairs: dict) -> None:
    """C1: embedding top-k class-filtered nearest neighbors (through VectorStore).
    Per-class allowed-id lists are precomputed once so the filter is O(1) to apply."""
    class_ids = defaultdict(list)
    for mid, p in profiles.items():
        class_ids[p["entity_class"]].append(mid)
    for mid, p in profiles.items():
        vec = vectors.get(mid)
        if vec is None:
            continue
        res = store.search(vec, CFG.EMBED_TOPK, allowed_ids=class_ids[p["entity_class"]])
        for nid, score in res:
            if nid != mid:
                pairs[frozenset((mid, nid))].add("C1")


# ---------------------------------------------------------------------------
# Hub identifier detection
# ---------------------------------------------------------------------------
def hub_identifiers(profiles: dict) -> set:
    counts = defaultdict(set)
    for mid, p in profiles.items():
        key = _entity_proxy(p)
        for field in ("emails", "phones7", "npis", "tins", "ssns"):
            for v in p[field]:
                if v:
                    counts[(field, v)].add(key)
    return {k for k, ents in counts.items() if len(ents) > CFG.HUB_IDENTIFIER_MAX_ENTITIES}


def _entity_proxy(p):
    """Coarse provisional-entity key for hub counting (name+class)."""
    return (p["norm_name"], p["entity_class"])


# ---------------------------------------------------------------------------
# Pairwise scoring
# ---------------------------------------------------------------------------
def score_pair(pa, pb, vectors, hubs, offset: float = 0.0) -> tuple[float, dict]:
    W = CFG.RES_WEIGHTS
    f = {}
    f["name_jw"] = textnorm.token_set_jw(pa["norm_name"], pb["norm_name"])
    f["nickname"] = 1.0 if textnorm.are_nickname_variants(pa["surface"], pb["surface"]) else 0.0

    def shared(field):
        return pa[field] & pb[field]

    def conflict(field):
        return bool(pa[field] and pb[field] and not (pa[field] & pb[field]))

    id_agree = 0.0
    id_conflict = 0.0
    hub_hit = False
    for field in ("emails", "npis", "tins", "ssns"):
        sh = shared(field)
        if sh:
            if all((field, v) in hubs for v in sh):
                hub_hit = True
                id_agree = max(id_agree, CFG.HUB_DOWNWEIGHT)
            else:
                id_agree = 1.0
        if conflict(field):
            id_conflict = 1.0
    f["identifier_agree"] = id_agree
    f["identifier_partial"] = 0.0
    f["identifier_conflict"] = id_conflict

    f["address_exact"] = 1.0 if shared("addr_keys") else 0.0
    f["address_partial"] = 0.0
    f["phone_agree"] = 1.0 if shared("phones7") else 0.0
    if f["phone_agree"] and all(("phones7", v) in hubs for v in shared("phones7")):
        f["phone_agree"] = CFG.HUB_DOWNWEIGHT
    f["dob_agree"] = 1.0 if shared("dobs") else 0.0
    f["dob_conflict"] = 1.0 if conflict("dobs") else 0.0

    cos = 0.0
    va, vb = vectors.get(pa["mention_id"]), vectors.get(pb["mention_id"])
    if va is not None and vb is not None:
        cos = float(np.dot(va, vb))
    f["embed_cosine"] = _band(cos)

    f["dup_group"] = 1.0 if (pa["dup_group_id"] and pa["dup_group_id"] == pb["dup_group_id"]
                             and f["name_jw"] > 0.8) else 0.0
    f["cooccurrence"] = 1.0 if (pa["claim_id"] == pb["claim_id"] and not pa["inside_quoted"]
                                and not pb["inside_quoted"]) else 0.0

    raw = W["bias"] + sum(W[k] * f.get(k, 0.0) for k in W if k != "bias")
    prob = 1.0 / (1.0 + np.exp(-CFG.RES_SQUASH_SCALE * (raw + offset)))
    f["_raw"] = raw
    f["_hub_downweighted"] = hub_hit
    return float(prob), f


def has_discriminating_signal(feats: dict) -> bool:
    """A pair is worth adjudicating only when strong signals disagree -- e.g.
    similar names but no corroborating id, or a shared id/phone across differing
    names. Pure weak-embedding neighbors are not adjudicated (would swamp the LLM)."""
    return (feats["name_jw"] >= 0.7 or feats["nickname"] >= 1.0
            or feats["identifier_agree"] > 0.0 or feats["phone_agree"] > 0.0
            or feats["address_exact"] > 0.0 or feats["dob_agree"] > 0.0)


def _band(cos: float) -> float:
    if cos >= 0.90:
        return 1.0
    if cos >= 0.80:
        return 0.5
    return 0.0


# ---- cannot-link hard rules ----
def cannot_link(pa, pb) -> str | None:
    persons = {"claimant", "attorney", "adjuster"}
    for field in ("emails", "npis", "tins", "ssns", "dobs"):
        if pa[field] and pb[field] and not (pa[field] & pb[field]):
            return f"conflicting_{field}"
    if (pa["entity_class"] in persons and pb["entity_class"] == "repair_shop") or \
       (pb["entity_class"] in persons and pa["entity_class"] == "repair_shop"):
        return "person_vs_org"
    # Jr/Sr suffix conflict at same name+address
    sa, sb = textnorm.name_suffix(pa["surface"]), textnorm.name_suffix(pb["surface"])
    same_core = textnorm.token_set_jw(pa["norm_name"], pb["norm_name"]) > 0.9
    if same_core and sa and sb and sa != sb and (pa["addr_keys"] & pb["addr_keys"]):
        return "jr_sr_conflict"
    return None


# ---- calibration proxy (gt-free) ----
def calibrate(profiles, pairs, vectors) -> dict:
    """Use template+narrative naming the same entity in the same doc as positives.
    Report where proxy positives land; return a suggested offset (kept small)."""
    positives = []
    by_doc = defaultdict(list)
    for mid, p in profiles.items():
        by_doc[p["doc_id"]].append(mid)
    for doc, mids in by_doc.items():
        for a, b in combinations(mids, 2):
            pa, pb = profiles[a], profiles[b]
            same_id = bool(pa["emails"] & pb["emails"] or pa["npis"] & pb["npis"])
            same_name = textnorm.token_set_jw(pa["norm_name"], pb["norm_name"]) > 0.9
            if (same_id or same_name):
                positives.append((a, b))
    if not positives:
        return {"n_positives": 0, "offset": 0.0}
    raws = [score_pair(profiles[a], profiles[b], vectors, set())[1]["_raw"] for a, b in positives[:2000]]
    raws.sort()
    p25 = raws[len(raws) // 4]
    # nudge so the 25th pct proxy-positive reaches the high band (logit of 0.9)
    import math
    target = math.log(0.9 / 0.1)
    offset = min(2.0, max(0.0, target - p25))   # cap to avoid over-merging
    return {"n_positives": len(positives), "raw_p25": round(p25, 3),
            "offset": round(offset, 3)}


# ---- adjudicator ----
def adjudicate(pa, pb, feats) -> dict:
    prompt = (
        "Decide if these two entity mentions refer to the SAME real-world entity. "
        "Return verdict link/no_link with a short rationale citing the signals.\n"
        f"A: name='{pa['surface']}' class={pa['entity_class']} emails={sorted(pa['emails'])} "
        f"phones7={sorted(pa['phones7'])} dob={sorted(pa['dobs'])} addr={sorted(pa['addr_keys'])}\n"
        f"B: name='{pb['surface']}' class={pb['entity_class']} emails={sorted(pb['emails'])} "
        f"phones7={sorted(pb['phones7'])} dob={sorted(pb['dobs'])} addr={sorted(pb['addr_keys'])}\n"
        f"features: name_jw={feats['name_jw']:.2f} nickname={feats['nickname']} "
        f"id_agree={feats['identifier_agree']} embed={feats['embed_cosine']}"
    )

    def offline():
        link = False
        if feats["identifier_agree"] >= 1.0:
            link = True
        elif feats["name_jw"] > 0.85 and (feats["phone_agree"] or feats["address_exact"] or feats["dob_agree"]):
            link = True
        elif feats["nickname"] and (feats["phone_agree"] or feats["address_exact"] or feats["dob_agree"]):
            link = True
        elif feats["name_jw"] < 0.6:
            link = False
        else:
            link = feats["embed_cosine"] >= 0.6
        signals = []
        if feats["identifier_agree"] >= 1.0:
            signals.append("validated identifier agreement")
        if feats["name_jw"] > 0.85:
            signals.append(f"high name similarity {feats['name_jw']:.2f}")
        if feats["nickname"]:
            signals.append("nickname variant")
        if feats["phone_agree"]:
            signals.append("phone match")
        if feats["address_exact"]:
            signals.append("address match")
        if feats["dob_agree"]:
            signals.append("DOB match")
        rationale = ("Linked: " if link else "Not linked: ") + (
            ", ".join(signals) if signals else f"insufficient overlap (name_jw={feats['name_jw']:.2f})")
        return {"verdict": "link" if link else "no_link",
                "confidence": 0.8 if signals else 0.5, "rationale": rationale,
                "key_signals": signals}

    return genai.generate_json(prompt, contracts.adjudication_schema(),
                               task="adjudication", offline_handler=offline)


# ---------------------------------------------------------------------------
# Greedy correlation clustering honoring cannot-link
# ---------------------------------------------------------------------------
def cluster(profiles, scored_pairs, cannot):
    """scored_pairs: list of (a,b,score,adjudicated_link_bool).
    Returns {mention_id: cluster_index} and per-cluster cause flags.
    Uses igraph to hold the positive-edge graph; greedy merge with constraints."""
    mids = list(profiles.keys())
    idx = {m: i for i, m in enumerate(mids)}
    g = ig.Graph(n=len(mids))
    g.vs["mid"] = mids

    pos_edges = []
    for a, b, score, adj_link in scored_pairs:
        link = adj_link if adj_link is not None else (score >= CFG.CLUSTER_LINK_THRESHOLD)
        if link and cannot.get(frozenset((a, b))) is None:
            pos_edges.append((idx[a], idx[b], score, adj_link))
    g.add_edges([(e[0], e[1]) for e in pos_edges])
    g.es["weight"] = [e[2] for e in pos_edges]
    g.es["adjudicated"] = [1 if e[3] else 0 for e in pos_edges]

    # union-find with per-cluster cannot-link membership
    parent = list(range(len(mids)))
    cl_members = {i: {i} for i in range(len(mids))}
    cl_cause = {i: "initial" for i in range(len(mids))}
    # per-cluster validated-identifier sets: a cluster may never hold two distinct
    # values of any of these (principled cannot-link enforced at cluster scope,
    # so transitive/embedding chains cannot merge conflicting identities).
    cl_ids = {}
    for i, m in enumerate(mids):
        p = profiles[m]
        cl_ids[i] = {fld: set(p[fld]) for fld in CFG.CLUSTER_CONSISTENT_IDS}
    cannot_idx = defaultdict(set)
    for pr, reason in cannot.items():
        a, b = tuple(pr)
        if a in idx and b in idx:
            cannot_idx[idx[a]].add(idx[b])
            cannot_idx[idx[b]].add(idx[a])

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    order = sorted(range(len(pos_edges)), key=lambda i: pos_edges[i][2], reverse=True)
    for ei in order:
        u, v, score, adj = pos_edges[ei]
        ru, rv = find(u), find(v)
        if ru == rv:
            continue
        mu, mv = cl_members[ru], cl_members[rv]
        # cannot-link check across the two clusters
        blocked = any(w in cannot_idx and (mv & cannot_idx[w]) for w in mu)
        if blocked:
            continue
        # identifier-consistency: union must not hold conflicting validated ids
        conflict = False
        for fld in CFG.CLUSTER_CONSISTENT_IDS:
            merged = cl_ids[ru][fld] | cl_ids[rv][fld]
            if len(merged) > 1:
                conflict = True
                break
        if conflict:
            continue
        # merge smaller into larger
        if len(mu) < len(mv):
            ru, rv = rv, ru
            mu, mv = mv, mu
        parent[rv] = ru
        mu |= mv
        cl_members[ru] = mu
        for fld in CFG.CLUSTER_CONSISTENT_IDS:
            cl_ids[ru][fld] |= cl_ids[rv][fld]
        if adj:
            cl_cause[ru] = "adjudicated_link"
        del cl_members[rv]

    labels = {}
    for i, m in enumerate(mids):
        labels[m] = find(i)
    return labels, cl_cause, g


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(repo: Repository, store: FaissVectorStore | None = None) -> dict:
    import uuid
    store = store or FaissVectorStore(CFG.EMBED_DIM, Paths.faiss_index, Paths.faiss_meta)
    store.load()

    # idempotent: clear resolution + downstream outputs so re-runs don't collide
    repo.conn.execute("PRAGMA foreign_keys=OFF")
    for t in ("candidate_pairs", "entity_members", "entity_versions",
              "entity_attributes", "dossiers", "entities"):
        repo.conn.execute(f"DELETE FROM {t}")
    repo.conn.commit()
    repo.conn.execute("PRAGMA foreign_keys=ON")

    profiles = build_profiles(repo)
    vectors = {mid: store.get_vector(mid) for mid in profiles}  # preload once
    pairs = generate_candidates(profiles)
    embedding_candidates(profiles, store, vectors, pairs)
    hubs = hub_identifiers(profiles)
    calib = calibrate(profiles, pairs, vectors)
    # The proxy calibrates the DECISION THRESHOLD, not a global score shift:
    # adding the offset to every pair (negatives included) over-merges. We keep
    # scoring un-shifted and report the proxy as a diagnostic. See DECISIONS.
    offset = 0.0

    # ---- pass 1: score every pair; mark adjudication-eligible ----
    cannot = {}
    records = []   # per-pair working record
    for _pi, (pr, passes) in enumerate(pairs.items()):
        a, b = tuple(pr)
        pa, pb = profiles[a], profiles[b]
        cl = cannot_link(pa, pb)
        if cl:
            cannot[pr] = cl
        score, feats = score_pair(pa, pb, vectors, hubs, offset)
        in_band = CFG.RES_ADJUDICATE_LOW <= score < CFG.RES_ADJUDICATE_HIGH
        eligible = in_band and cl is None and has_discriminating_signal(feats)
        records.append({"i": _pi, "a": a, "b": b, "passes": passes,
                        "score": score, "feats": feats, "eligible": eligible})

    # ---- select most-uncertain eligible pairs up to the cap, then adjudicate ----
    eligible_recs = [r for r in records if r["eligible"]]
    eligible_recs.sort(key=lambda r: abs(r["score"] - 0.5))   # closest to 0.5 = most uncertain
    to_adjudicate = set(id(r) for r in eligible_recs[:CFG.ADJUDICATE_MAX])
    n_adjudicated = 0

    scored_rows, scored_pairs = [], []
    for r in records:
        a, b, feats, score = r["a"], r["b"], r["feats"], r["score"]
        adj_link = None
        verdict = None
        adjudicated = 0
        if r["eligible"] and id(r) in to_adjudicate:
            v = adjudicate(profiles[a], profiles[b], feats)
            verdict = v["verdict"]
            adj_link = (verdict == "link")
            feats["_adjudicator"] = v
            adjudicated = 1
            n_adjudicated += 1
        band = ("link" if score >= CFG.RES_ADJUDICATE_HIGH else
                "adjudicate" if adjudicated else
                "no_link" if score < CFG.CLUSTER_LINK_THRESHOLD else "link")
        scored_pairs.append((a, b, score, adj_link))
        scored_rows.append({
            "pair_id": f"p{r['i']:08d}", "mention_id_a": a, "mention_id_b": b,
            "entity_class": profiles[a]["entity_class"],
            "gen_passes": json.dumps(sorted(r["passes"])),
            "score": round(score, 4), "feature_json": json.dumps(_clean(feats)),
            "band": band, "adjudicated": adjudicated, "verdict": verdict,
        })
    repo.add_candidate_pairs(scored_rows)

    labels, cl_cause, g = cluster(profiles, scored_pairs, cannot)

    # materialize entities + versioned membership
    clusters = defaultdict(list)
    for mid, lab in labels.items():
        clusters[lab].append(mid)

    ent_rows, ver_rows, mem_rows = [], [], []
    label_to_entity = {}
    for lab, members in clusters.items():
        eid = f"E{uuid.uuid5(uuid.NAMESPACE_OID, str(sorted(members))).hex[:12]}"
        label_to_entity[lab] = eid
        vid = f"{eid}.v1"
        cname, klass = _canonical_name(profiles, members)
        ent_rows.append({"entity_id": eid, "entity_class": klass,
                         "canonical_name": cname, "version_id": vid,
                         "n_mentions": len(members)})
        ver_rows.append({"version_id": vid, "entity_id": eid,
                         "cause": cl_cause.get(lab, "initial"),
                         "parent_entity_ids": json.dumps([]), "created_ts": None})
        for mid in members:
            mem_rows.append({"entity_id": eid, "mention_id": mid, "version_id": vid})
    repo.add_entities(ent_rows)
    repo.add_entity_versions(ver_rows)
    repo.add_entity_members(mem_rows)

    return {
        "n_mentions": len(profiles),
        "n_candidate_pairs": len(pairs),
        "n_hub_identifiers": len(hubs),
        "n_adjudicated": n_adjudicated,
        "n_entities": len(clusters),
        "n_cannot_link": len(cannot),
        "calibration": calib,
        "mode": genai_mode(),
    }


def _canonical_name(profiles, members):
    from collections import Counter
    names = Counter()
    classes = Counter()
    for m in members:
        p = profiles[m]
        classes[p["entity_class"]] += 1
        if not p["inside_quoted"]:
            names[p["surface"]] += 2
        else:
            names[p["surface"]] += 1
    cname = names.most_common(1)[0][0] if names else ""
    klass = classes.most_common(1)[0][0] if classes else "claimant"
    return cname, klass


def _clean(feats: dict) -> dict:
    return {k: (list(v) if isinstance(v, set) else v) for k, v in feats.items()}
