"""Layer 2 candidate generation: the embedding recall net.

WHY THIS EXISTS
---------------
Splink's nine deterministic blocking rules only propose a pair when the two
mentions SHARE A KEY -- the same email, npi, sorted name, soundex last name and
so on. That is fast, exact and completely explainable, and it is also a hard
ceiling: a pair no rule proposes is never scored, so it can never be merged no
matter how good the comparison model is. Blocking recall bounds ER recall.

The pairs that ceiling costs you are the realistic ones:

    "Bob Miller"        vs  "Robert Miller Jr"      -- no shared key
    "Valley Auto Body"  vs  "Valley Auto Body & Paint"
    an entity written differently in every note it appears in

This module is a SECOND candidate generator, unioned with those rules:

    mention vectors (embed_index) -> class-filtered k-NN -> keep edges at or
    above EMB_BLOCK_SIM -> connected components -> one `emb_bucket` per
    mention, which Splink blocks on exactly like any other column.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It never decides a merge. It proposes pairs; Splink scores every one of them
with the same EM-trained Fellegi-Sunter model it applies to deterministic
candidates. So an embedding-found link carries the same calibrated probability
and the same comparison-level breakdown as any other, and stays as auditable.
Splink's `match_key` records which blocking rule surfaced each pair, so the
lane's contribution is measured rather than asserted -- see
`entity_resolution.lane_provenance`.

That split is the whole point. Embeddings buy recall, which is what they are
good at, and are kept out of the scoring decision, where "the vectors were
close" is not an explanation anyone can audit.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from .settings import CFG, Paths, genai_mode


class EmbeddingBackendUnsuitable(RuntimeError):
    """The configured embedding backend cannot support this lane.

    Specifically: the offline stub. genai._offline_embedding hashes character
    shingles into a fixed-width vector, which measures LEXICAL OVERLAP, not
    meaning. That is fine for keeping the pipeline runnable without a network,
    and useless here, because lexical overlap is what the deterministic name
    rules already do -- better, exactly, and explainably.

    Measured on the notebook 04 probe set, offline, same-class pairs:

        true co-referring : min 0.7708  max 0.9040
        non-co-referring  : min 0.5180  max 0.8354

    The distributions OVERLAP -- the hardest false pair ('Dr. Alicia Reyes' vs
    'Dr. Alan Reyes', 0.8354) scores above six of the eight true pairs. So no
    threshold separates them: this is not a calibration problem that a different
    EMB_BLOCK_SIM could fix, and the lane would emit buckets that look like
    output and mean nothing.

    Set EMB_BLOCK_ENABLED=False to resolve on deterministic blocking alone.
    """


class EmbeddingThresholdMiscalibrated(RuntimeError):
    """EMB_BLOCK_SIM sits above every similarity the index actually contains.

    Not a tuning complaint -- a structural one. If no pair anywhere in the corpus
    reaches the floor, the lane cannot propose anything, and a lane that proposes
    nothing is indistinguishable in every downstream number from a lane that
    found nothing worth proposing.

    This is the concrete failure it catches: EMB_BLOCK_SIM was first set to 0.86,
    a reasonable-looking floor carried over from sentence-transformer intuition.
    gemini-embedding-001 puts co-referring pairs at ~0.30 and unrelated pairs at
    ~0.27, so the lane produced exactly zero edges. Resolution still ran, still
    produced clusters, and still passed every assertion -- it simply merged less,
    with nothing anywhere saying why. Swapping EMBED_MODEL re-creates that
    failure, which is why this is an exception and not a log line.
    """


# Defined in embed_index, which owns the index, and re-exported here so that
# `blocking.MentionIndexUnavailable` keeps working for existing callers. Same
# class object, deliberately -- two classes sharing a name is a bug waiting to
# happen, since catching one would not catch the other.
from .embed_index import MentionIndexUnavailable  # noqa: E402,F401


def connected_components(pairs, nodes) -> dict:
    """Union-find over `pairs`, returning {node: root}. Every node appears."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    return {n: find(n) for n in nodes}


def knn_edges(store, mention_ids: list[str], classes: dict) -> list:
    """Class-filtered k-NN over the mention index.

    Returns unique (id_l, id_r, similarity) with id_l < id_r. The class filter is
    applied inside the index (IDSelector), before nearest-neighbor selection, so
    the top-k is exact over the filtered set rather than a post-filtered guess
    that can silently drop true neighbours.
    """
    if CFG.EMB_BLOCK_SAME_CLASS:
        groups = defaultdict(list)
        for mid in mention_ids:
            groups[classes.get(mid, "")].append(mid)
    else:
        groups = {"": list(mention_ids)}

    seen = {}
    # Running max and count, not the full list: at corpus scale this loop sees
    # ~n*k similarities and only the maximum is needed for the calibration check.
    n_compared = 0
    best_seen = float("-inf")
    for members in groups.values():
        if len(members) < 2:
            continue        # nothing to pair with; a search would only find self
        # k+1 because a mention's own vector is always its nearest neighbour.
        # One batched query per class group, not one per mention -- see
        # FaissVectorStore.knn_within for why that distinction matters at scale.
        for mid, other, sim in store.knn_within(members, CFG.EMB_BLOCK_TOPK + 1):
            n_compared += 1
            if sim > best_seen:
                best_seen = sim
            if sim < CFG.EMB_BLOCK_SIM:
                continue
            key = (mid, other) if mid < other else (other, mid)
            if sim > seen.get(key, -1.0):
                seen[key] = sim

    edges = [(a, b, s) for (a, b), s in seen.items()]
    if n_compared and not edges:
        hi = best_seen
        if hi < CFG.EMB_BLOCK_SIM:
            raise EmbeddingThresholdMiscalibrated(
                f"EMB_BLOCK_SIM={CFG.EMB_BLOCK_SIM} exceeds the highest similarity "
                f"in the whole index ({hi:.4f} over {n_compared} compared pairs). "
                f"The lane cannot propose anything. EMBED_MODEL is "
                f"{CFG.EMBED_MODEL!r}; the threshold was calibrated for "
                f"{getattr(CFG, 'EMB_BLOCK_SIM_CALIBRATED_FOR', 'an unrecorded model')!r}. "
                "Re-run the calibration cell in notebook 04, or set "
                "EMB_BLOCK_ENABLED=False to resolve on deterministic blocking alone."
            )
    return edges


def embedding_buckets(mention_ids: list[str], classes: dict,
                      store=None) -> tuple:
    """Compute the `emb_bucket` column. Returns ({mention_id: bucket|None}, stats).

    A bucket of None means "this mention contributes nothing to the embedding
    lane" -- Splink excludes NULLs from blocking, so those mentions are covered
    by the nine deterministic rules alone. Two cases produce None:

      * a singleton component -- no neighbour cleared EMB_BLOCK_SIM, so the
        bucket would propose no pairs anyway;
      * an oversize component -- see below.
    """
    from .embed_index import open_store

    store = store or open_store()
    try:
        store.load()
    except FileNotFoundError as e:
        raise MentionIndexUnavailable(
            "mention vector index not found at " + str(Paths.mention_index) +
            ". Run embed_index.run(repo) (notebook 04) before resolution, or "
            "set EMB_BLOCK_ENABLED=False in config to resolve on deterministic "
            "blocking alone."
        ) from e

    edges = knn_edges(store, mention_ids, classes)
    roots = connected_components([(a, b) for a, b, _ in edges], mention_ids)
    sims = sorted(s for _, _, s in edges)

    members = defaultdict(list)
    for mid, root in roots.items():
        members[root].append(mid)

    buckets = {}
    n_oversize = n_singleton = 0
    sizes = []
    for root, mem in members.items():
        if len(mem) < 2:
            n_singleton += 1
            for m in mem:
                buckets[m] = None
            continue
        if len(mem) > CFG.EMB_BLOCK_MAX_BUCKET:
            # Transitive chaining: A~B, B~C, C~D with A nothing like D. One
            # runaway component of n mentions costs n^2/2 pairs and its
            # membership is not defensible anyway, so it contributes nothing
            # rather than contributing noise. Those mentions keep every
            # deterministic rule.
            n_oversize += 1
            for m in mem:
                buckets[m] = None
            continue
        sizes.append(len(mem))
        # The component root is a mention_id, which is already unique, so the
        # label is unique per component. Not truncated: two components whose
        # roots happened to share a suffix would silently block together.
        label = "EB" + str(root)
        for m in mem:
            buckets[m] = label

    stats = {
        "enabled": True,
        "n_mentions": len(mention_ids),
        "n_knn_edges": len(edges),
        "n_buckets": len(sizes),
        "n_mentions_bucketed": sum(sizes),
        "n_singleton_components": n_singleton,
        "n_oversize_components_dropped": n_oversize,
        "largest_bucket": max(sizes) if sizes else 0,
        "sim_threshold": CFG.EMB_BLOCK_SIM,
        "sim_min": round(sims[0], 4) if sims else None,
        "sim_median": round(sims[len(sims) // 2], 4) if sims else None,
        "sim_max": round(sims[-1], 4) if sims else None,
        "topk": CFG.EMB_BLOCK_TOPK,
        "embed_model": CFG.EMBED_MODEL,
    }
    return buckets, stats


def attach_buckets(frame: pd.DataFrame, store=None) -> tuple:
    """Add the `emb_bucket` column to a mention frame.

    When the lane is disabled the column is still added, all NULL, so the Splink
    settings never change shape between runs: a blocking rule over an all-NULL
    column proposes nothing, which is exactly the intended behaviour.
    """
    frame = frame.copy()
    if not CFG.EMB_BLOCK_ENABLED:
        frame["emb_bucket"] = None
        return frame, {"enabled": False, "reason": "EMB_BLOCK_ENABLED=False"}

    if genai_mode() == "offline":
        raise EmbeddingBackendUnsuitable(
            "the embedding blocking lane is enabled but GenAI is in offline "
            "mode, so vectors come from the character-shingle stub rather than "
            "a real embedding model. Measured on the notebook 04 probe set the "
            "stub's true and false pair distributions overlap, so no threshold "
            "separates them and the buckets would be meaningless. Provide an "
            "API key, or set EMB_BLOCK_ENABLED=False to resolve on "
            "deterministic blocking alone."
        )

    mention_ids = frame["mention_id"].tolist()
    classes = dict(zip(mention_ids, frame["entity_class"].tolist()))
    buckets, stats = embedding_buckets(mention_ids, classes, store=store)
    frame["emb_bucket"] = frame["mention_id"].map(buckets)
    return frame, stats


def buckets_for_new(new_ids: list[str], classes: dict,
                    existing_buckets: dict, store=None) -> tuple:
    """Assign emb_bucket to arriving mentions against an index that already has them.

    The batch form (`embedding_buckets`) computes components over the whole k-NN
    graph at once. That is not available incrementally: the existing mentions
    already carry bucket labels that other stored rows and edges refer to, so a
    new note must JOIN the existing structure rather than re-partition it.

    Rules, in order:
      1. A new mention whose nearest qualifying neighbour already has a bucket
         adopts that bucket. This is the case that matters -- it is how an
         arriving "R. Miller" lands in the same block as a stored "Bob Miller".
      2. New mentions with no bucketed neighbour but with qualifying neighbours
         among THEMSELVES form a fresh bucket together.
      3. Everything else gets NULL and is covered by the deterministic rules.

    This can under-merge relative to a full re-partition: if an arriving mention
    bridges two previously separate buckets, the batch form would have merged
    them and this does not -- it joins one. That is the deliberate trade. Bucket
    labels are referenced by stored edges, so silently re-partitioning them
    underneath would invalidate provenance already written down. A periodic full
    re-resolve is the place to collapse those, not the ingest path.
    """
    from .embed_index import open_store

    store = store or open_store()
    try:
        store.load()
    except FileNotFoundError as e:
        raise MentionIndexUnavailable(
            "mention vector index not found at " + str(Paths.mention_index) +
            ". The backfill must run before notes can be ingested incrementally."
        ) from e

    if not CFG.EMB_BLOCK_ENABLED:
        return {m: None for m in new_ids}, {"enabled": False,
                                            "reason": "EMB_BLOCK_ENABLED=False"}
    if genai_mode() == "offline":
        raise EmbeddingBackendUnsuitable(
            "incremental bucketing needs real embeddings; the offline stub's "
            "true and false similarity distributions overlap. Set "
            "EMB_BLOCK_ENABLED=False to ingest on deterministic blocking alone."
        )

    new_set = set(new_ids)
    out: dict[str, str | None] = {}
    n_joined = n_created = 0

    # Search each arriving mention against its whole class -- stored and new --
    # so it can attach to an existing block or to a sibling in this batch.
    by_class: dict[str, list[str]] = defaultdict(list)
    for mid in new_ids:
        by_class[classes.get(mid, "")].append(mid)

    all_by_class: dict[str, list[str]] = defaultdict(list)
    for mid, cls in classes.items():
        all_by_class[cls].append(mid)

    pairs_among_new = []
    for cls, members in by_class.items():
        pool = all_by_class.get(cls, [])
        if len(pool) < 2:
            continue
        for mid, other, sim in store.knn_within(pool, CFG.EMB_BLOCK_TOPK + 1):
            if mid not in new_set or sim < CFG.EMB_BLOCK_SIM:
                continue
            if other in new_set:
                pairs_among_new.append((mid, other))
            elif existing_buckets.get(other) and mid not in out:
                out[mid] = existing_buckets[other]
                n_joined += 1

    # Rule 2: arriving mentions that found each other but no stored block.
    unplaced = [m for m in new_ids if m not in out]
    if unplaced:
        roots = connected_components(
            [(a, b) for a, b in pairs_among_new if a in set(unplaced) and b in set(unplaced)],
            unplaced)
        members: dict[str, list[str]] = defaultdict(list)
        for m, root in roots.items():
            members[root].append(m)
        for root, mem in members.items():
            if len(mem) < 2 or len(mem) > CFG.EMB_BLOCK_MAX_BUCKET:
                for m in mem:
                    out[m] = None
            else:
                label = "EB" + str(root)
                n_created += 1
                for m in mem:
                    out[m] = label

    stats = {
        "enabled": True,
        "n_new": len(new_ids),
        "n_joined_existing_bucket": n_joined,
        "n_new_buckets_formed": n_created,
        "n_unbucketed": sum(1 for v in out.values() if v is None),
        "sim_threshold": CFG.EMB_BLOCK_SIM,
    }
    return out, stats
