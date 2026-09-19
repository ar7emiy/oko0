"""Incremental entity resolution: score an arriving note, do not re-resolve the world.

THE PROBLEM
-----------
`entity_resolution.run()` is a whole-corpus operation. It builds a frame over
every mention, trains a Splink model by EM, scores every blocked pair, and
rewrites `same_as_edges` from scratch. On the measured corpus that is 23k
mentions and 2.9M scored pairs, about two minutes. Doing that per arriving note
is absurd, and it is also wrong: retraining on every note means the model --
and therefore every probability already written down -- changes underneath
records a human may already have reviewed.

THE SHAPE OF THE FIX
--------------------
Split it the way a production linkage system does:

    BACKFILL (once, per client onboarding)
        full run: train the model by EM, score the historical corpus, save the
        trained parameters to splink_model.json.

    INGEST (per arriving note, forever after)
        block the new mentions against the existing frame, score ONLY the pairs
        the new mentions generate, using the ALREADY-TRAINED model, append those
        edges, and recompute clusters.

The cost of an ingest is then proportional to the arriving note, not the corpus.

WHY RE-CLUSTERING THE WHOLE CORPUS IS STILL FINE
------------------------------------------------
Clustering is union-find over stored edges -- cheap, and linear in edges. It is
also the design: identity is a THRESHOLD-DERIVED VIEW, never a stored merge, so
recomputing it is the normal operation rather than a rebuild. This is what lets
one arriving note legitimately merge two entities that were previously
separate, without anything being un-written.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
The model is not retrained on ingest. Its m/u parameters are the calibration
that every stored probability was computed against; silently re-estimating them
would mean two edges with the same probability were scored by different models.
Retraining is a backfill operation, and a periodic re-backfill is the honest way
to pick up drift.
"""
from __future__ import annotations

import pandas as pd

from . import blocking, entity_resolution as er, runlog
from .repository import Repository
from .settings import CFG, Paths


class ModelNotTrained(RuntimeError):
    """No saved Splink model, so there is nothing to score an arriving note against.

    Raised rather than quietly training one on the spot: a model trained on a
    single arriving note would be meaningless, and a model trained silently is
    one nobody knows the provenance of.
    """


def resolve_incremental(repo: Repository, new_doc_ids: list[str],
                        threshold: float | None = None) -> dict:
    """Score arriving notes' mentions against the resolved corpus and re-cluster.

    Returns what CHANGED, not just totals -- which entities were created, which
    grew, and which merged -- because that is the thing an operator watching an
    ingest actually needs to see.
    """
    from splink import DuckDBAPI, Linker, block_on

    threshold = CFG.ER_LINK_THRESHOLD if threshold is None else threshold
    if not er.MODEL_PATH.exists():
        raise ModelNotTrained(
            f"no trained model at {er.MODEL_PATH}. Run the backfill "
            "(entity_resolution.run) before ingesting notes incrementally."
        )

    frame = er.build_mention_frame(repo)
    if frame.empty:
        return {"error": "no mentions"}

    new_ids = set(frame.loc[frame["doc_id"].isin(set(new_doc_ids)), "mention_id"])
    if not new_ids:
        return {"n_new_mentions": 0, "note": "arriving notes produced no mentions"}

    # ---- membership BEFORE, so the diff at the end is real -----------------
    before = {}
    try:
        members = repo.table("entity_members")
        before = dict(zip(members["mention_id"], members["entity_id"]))
    except Exception:
        pass

    # ---- blocking column ---------------------------------------------------
    # Existing mentions keep the bucket they were assigned at backfill; arriving
    # ones attach to it. Re-partitioning would invalidate the blocked_by
    # provenance already stored against existing edges.
    stored_buckets = {}
    try:
        prev = repo.table("mention_blocks")
        stored_buckets = {m: b for m, b in zip(prev["mention_id"], prev["emb_bucket"])
                          if b and not pd.isna(b)}
    except Exception:
        pass

    classes = dict(zip(frame["mention_id"], frame["entity_class"]))
    if CFG.EMB_BLOCK_ENABLED:
        new_buckets, bstats = blocking.buckets_for_new(
            sorted(new_ids), classes, stored_buckets)
    else:
        new_buckets, bstats = {m: None for m in new_ids}, {"enabled": False}
    all_buckets = {**stored_buckets, **new_buckets}
    frame["emb_bucket"] = frame["mention_id"].map(all_buckets)
    runlog.field("blocking", f"{bstats.get('n_joined_existing_bucket', 0)} joined an "
                             f"existing block, {bstats.get('n_new_buckets_formed', 0)} new")

    # ---- score ONLY the arriving mentions against the corpus ---------------
    existing = frame[~frame["mention_id"].isin(new_ids)]
    arriving = frame[frame["mention_id"].isin(new_ids)]
    if existing.empty:
        return {"n_new_mentions": len(new_ids),
                "note": "nothing resolved yet; run the backfill first"}

    # Refuse to score arriving notes with a model trained under a different
    # evidence set. Silently reusing a stale model puts edges calibrated two
    # different ways into one store, and nothing downstream can tell them apart.
    er.check_model_current(frame)

    linker = Linker(existing, str(er.MODEL_PATH), db_api=DuckDBAPI())
    rules = [block_on(*rule) for rule in er.BLOCKING_RULES]

    # The frozen model carries the backfill's untrained parameters with it, so an
    # arriving edge is uncalibrated in exactly the same places. Recording it here
    # too keeps the column meaning one thing across both paths -- a NULL must
    # mean "calibrated", never "written by the incremental path".
    cal = er.training_completeness(linker)
    if not cal["fully_trained"]:
        runlog.note(f"model was frozen with {cal['n_untrained_parameters']} "
                    f"untrained m/u parameters "
                    f"({', '.join(sorted(cal['by_comparison']))}); "
                    "affected arriving edges are marked uncalibrated")

    # NaN -> None before handing records to Splink.
    #
    # find_matches_to_new_records registers the records through pyarrow, which
    # infers each column's type from the values it sees. pandas represents a
    # missing string as float NaN, so a column whose arriving rows are mostly
    # empty infers as double and then fails on the first real value:
    #   ArrowInvalid: Could not convert 'a@b.com' with type str: tried to
    #   convert to double
    # The identifier columns are exactly the sparse ones (build_mention_frame
    # deliberately nulls them, since blocking on "" would be catastrophic), so
    # this fires on ordinary data rather than as an edge case.
    records = (arriving.astype(object)
               .where(pd.notna(arriving), None)
               .to_dict("records"))
    preds = linker.inference.find_matches_to_new_records(
        records, blocking_rules=rules,
    ).as_pandas_dataframe()
    edges = _normalise_pairs(preds, new_ids, cal)
    n_vs_existing = len(edges)

    # SECOND PASS: arriving vs arriving.
    #
    # find_matches_to_new_records scores the new records against the INDEXED
    # dataset only -- it never compares them to each other. With a one-note
    # batch that is nearly harmless; with a four-note batch it is plainly wrong,
    # and it showed up as three separate entities all called "Kim Spine
    # Institute", one per note, because no pair among them was ever scored.
    #
    # Same trained model, so these pairs are calibrated identically to every
    # other edge; only the candidate set differs.
    if len(arriving) > 1:
        within = Linker(arriving, str(er.MODEL_PATH), db_api=DuckDBAPI())
        try:
            wp = within.inference.predict(
                threshold_match_probability=0.01).as_pandas_dataframe()
            w_edges = _normalise_pairs(wp, new_ids, cal)
            edges = pd.concat([edges, w_edges], ignore_index=True)
        except Exception as e:      # noqa: BLE001
            runlog.note(f"within-batch scoring failed ({type(e).__name__}: {e}); "
                        "arriving notes were compared to the corpus but not to "
                        "each other, so a party appearing only in this batch may "
                        "be split across entities")

    # A pair can surface from both passes; keep the higher-scoring copy.
    if not edges.empty:
        key = edges.apply(
            lambda r: tuple(sorted((r["mention_id_l"], r["mention_id_r"]))), axis=1)
        edges = (edges.assign(_k=key)
                 .sort_values("match_probability", ascending=False)
                 .drop_duplicates("_k", keep="first")
                 .drop(columns="_k")
                 .reset_index(drop=True))
    runlog.field("scored", f"{len(edges)} pairs "
                           f"({n_vs_existing} vs the corpus, "
                           f"{len(edges) - n_vs_existing} within the batch)")

    # ---- suppress structurally impossible pairs, same rules as backfill ----
    feat = frame.set_index("mention_id").to_dict("index")
    reasons = []
    for la, rb in zip(edges["mention_id_l"].to_numpy(), edges["mention_id_r"].to_numpy()):
        a, b = feat.get(la), feat.get(rb)
        reasons.append(er.cannot_link_reason(a, b) if (a and b) else None)
    edges = edges.assign(suppressed_reason=reasons)
    n_suppressed = sum(1 for r in reasons if r)

    unc = (edges["uncalibrated"] if "uncalibrated" in edges.columns
           else pd.Series([None] * len(edges), index=edges.index))

    # ---- append, never rewrite --------------------------------------------
    repo.add_same_as_edges([
        {"mention_id_a": a, "mention_id_b": b, "probability": float(p),
         "match_weight": float(w), "backend": "splink-incremental",
         "blocked_by": k, "uncalibrated": uc, "suppressed_reason": sr}
        for a, b, p, w, k, uc, sr in zip(
            edges["mention_id_l"].to_numpy(), edges["mention_id_r"].to_numpy(),
            edges["match_probability"].to_numpy(), edges["match_weight"].to_numpy(),
            edges["blocked_by"].to_numpy(), unc.to_numpy(),
            edges["suppressed_reason"].to_numpy())
    ])
    persist_blocks(repo, all_buckets)

    # ---- recompute identity over ALL edges --------------------------------
    all_edges = repo.table("same_as_edges").rename(
        columns={"mention_id_a": "mention_id_l", "mention_id_b": "mention_id_r",
                 "probability": "match_probability"})
    live = all_edges[all_edges["suppressed_reason"].isna()]
    mention_ids = frame["mention_id"].tolist()
    labels = er.cluster_at(live, mention_ids, threshold)
    after = _materialise(repo, frame, labels, threshold)

    return {
        "n_new_mentions": len(new_ids),
        "n_pairs_scored": len(edges),
        "n_pairs_suppressed": n_suppressed,
        "n_pairs_above_threshold": int((edges["match_probability"] >= threshold).sum()),
        "embedding_blocking": bstats,
        "blocking_lanes": edges["blocked_by"].value_counts().to_dict(),
        **_diff(before, labels, new_ids, after),
    }


def _normalise_pairs(preds: pd.DataFrame, new_ids: set,
                     calibration: dict | None = None) -> pd.DataFrame:
    """find_matches_to_new_records returns the search record on one side.

    Which side is not guaranteed, and downstream code assumes nothing about
    order, so both columns are normalised to plain mention ids and the lane name
    is resolved the same way the backfill resolves it.

    The uncalibrated flag is derived HERE rather than after the fact, because
    it needs this frame's gamma columns and they do not survive the projection.
    """
    out = pd.DataFrame({
        "mention_id_l": preds["mention_id_l"].astype(str),
        "mention_id_r": preds["mention_id_r"].astype(str),
        "match_probability": preds["match_probability"].astype(float),
        "match_weight": preds.get("match_weight", pd.Series(0.0, index=preds.index)).fillna(0.0),
        "blocked_by": (preds["match_key"].map(er._rule_name)
                       if "match_key" in preds.columns else None),
        "uncalibrated": (er.SplinkResolver._uncalibrated_column(preds, calibration)
                         if calibration else None),
    })
    # Drop self-pairs and any pair not actually involving an arriving mention.
    keep = (out["mention_id_l"] != out["mention_id_r"]) & (
        out["mention_id_l"].isin(new_ids) | out["mention_id_r"].isin(new_ids))
    return out[keep].reset_index(drop=True)


def persist_blocks(repo: Repository, buckets: dict) -> None:
    """Store emb_bucket per mention so the next ingest can attach to it.

    Called by BOTH paths. Without the backfill writing these, the first ingest
    would find no existing blocks to join, and arriving mentions could only
    bucket with each other -- the embedding lane would be quietly weaker on the
    ingest path than on the backfill path, for no reason a reader would spot.
    """
    # Table lives in contracts.DDL like every other one -- created here only as
    # a safety net for a database opened before it was added to the schema.
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS mention_blocks ("
        "mention_id TEXT PRIMARY KEY, emb_bucket TEXT)")
    # Only real labels. A NaN would round-trip as a bucket, because bool(nan)
    # is True -- an unbucketed mention would come back looking bucketed.
    rows = [(m, str(b)) for m, b in buckets.items()
            if b is not None and not (isinstance(b, float) and pd.isna(b))]
    repo.conn.executemany(
        "INSERT OR REPLACE INTO mention_blocks (mention_id, emb_bucket) VALUES (?,?)",
        rows)
    repo.conn.commit()


def _materialise(repo: Repository, frame: pd.DataFrame, labels: dict,
                 threshold: float) -> dict:
    """Rewrite the identity VIEW at this threshold. Edges are untouched."""
    from collections import Counter, defaultdict

    by_entity = defaultdict(list)
    for mid, eid in labels.items():
        by_entity[eid].append(mid)

    cls_of = frame.set_index("mention_id")["entity_class"].to_dict()
    name_of = repo.table("mentions").set_index("mention_id")["surface"].to_dict()

    repo.conn.execute("PRAGMA foreign_keys=OFF")
    for t in ("entity_snapshot", "entity_members", "entities"):
        repo.conn.execute(f"DELETE FROM {t}")
    repo.conn.commit()
    repo.conn.execute("PRAGMA foreign_keys=ON")

    ent_rows, mem_rows, snap_rows = [], [], []
    for eid, members in by_entity.items():
        cname = Counter(name_of.get(m, "") for m in members).most_common(1)[0][0]
        kls = Counter(cls_of.get(m, "claimant") for m in members).most_common(1)[0][0]
        ent_rows.append({"entity_id": eid, "entity_class": kls,
                         "canonical_name": cname,
                         "version_id": f"{eid}.t{threshold}",
                         "n_mentions": len(members)})
        for m in members:
            mem_rows.append({"entity_id": eid, "mention_id": m,
                             "version_id": f"{eid}.t{threshold}"})
            snap_rows.append({"entity_id": eid, "mention_id": m, "threshold": threshold})
    repo.add_entities(ent_rows)
    repo.add_entity_members(mem_rows)
    repo.add_entity_snapshot(snap_rows)
    return {e["entity_id"]: e for e in ent_rows}


def _diff(before: dict, labels: dict, new_ids: set, after: dict) -> dict:
    """What actually changed -- the part an operator watching an ingest cares about.

    Entity ids are content-derived (uuid5 over sorted members), so an entity that
    GAINS a mention gets a new id. Comparing ids alone would report every growth
    as a create+delete, so growth is detected by tracking the old-membership of
    each new cluster.
    """
    # Invert once: the naive form rescans every label per arriving mention,
    # which is O(new x corpus).
    from collections import defaultdict
    by_entity = defaultdict(list)
    for m, e in labels.items():
        by_entity[e].append(m)

    grew, created = [], []
    for mid in new_ids:
        eid = labels.get(mid)
        if eid is None:
            continue
        siblings = [m for m in by_entity[eid] if m not in new_ids]
        if siblings:
            prior = {before.get(s) for s in siblings if before.get(s)}
            grew.append({"entity_id": eid,
                         "name": after.get(eid, {}).get("canonical_name"),
                         "n_mentions": after.get(eid, {}).get("n_mentions"),
                         "absorbed_new_mention": mid,
                         "merged_prior_entities": len(prior)})
        else:
            created.append({"entity_id": eid,
                            "name": after.get(eid, {}).get("canonical_name")})
    # Deduplicate: several arriving mentions can land in one entity.
    seen, grew_u = set(), []
    for g in grew:
        if g["entity_id"] not in seen:
            seen.add(g["entity_id"])
            grew_u.append(g)
    seen, created_u = set(), []
    for c in created:
        if c["entity_id"] not in seen:
            seen.add(c["entity_id"])
            created_u.append(c)
    return {"n_entities_total": len(set(labels.values())),
            "entities_matched_existing": grew_u,
            "entities_created": created_u}
