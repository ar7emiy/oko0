"""The operational entrypoint: notes arrive, the dataset updates.

This is the product-shaped path, as distinct from the research-shaped one. The
difference is not cosmetic:

    RESEARCH PATH (notebooks 01-11)
        generate a corpus with a sealed ground-truth manifest, run every stage
        over the whole corpus, then audit the result against the manifest.
        Answers "how accurate is this system".

    OPERATIONAL PATH (this module)
        notes arrive from a feed. They are ingested, processed, and folded into
        the resolved dataset. No manifest exists, nothing is audited against
        ground truth, and the corpus is never reprocessed.
        Answers "what does this system do with a note".

Both run the SAME engines over the same tables. The leakage guard is what makes
that claim checkable: no pipeline module may read ground truth, so the research
path's manifest is genuinely invisible to everything the operational path uses.

TWO PHASES
----------
    backfill(repo)              -- onboarding. Full pass over the historical
                                   corpus; trains the Splink model by EM.
    ingest(repo, doc_ids)       -- steady state. Processes only the arriving
                                   notes and folds them into the existing
                                   dataset, at a cost proportional to the note
                                   rather than the corpus.

`ingest` refuses to run before `backfill` (there is no trained model to score
against, and no index to block against), rather than silently training a model
on one note.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import (build_graph, embed_index, entity_resolution, incremental,
               pipeline_v2, profiles, profiling, runlog)
from .repository import Repository
from .settings import CFG, Paths


class NotBackfilled(RuntimeError):
    """Steady-state ingest was called before the system was onboarded."""


# ---------------------------------------------------------------------------
# Arrival
# ---------------------------------------------------------------------------
def deliver(paths: list[Path], claim_of: dict | None = None) -> list[str]:
    """Copy notes into the watched folder -- stands in for the document feed.

    Real deployments receive notes from a claims system; here they are files.
    The important part is what this does NOT do: it never writes ground truth,
    so an ingested note carries no more information than a real one would.

    `claim_of` maps doc_id -> {claim_id, occurrence_id}. That is STRUCTURAL
    metadata the source system knows (which claim a note was filed under), not
    something inferred from the text -- see profiling.ingest_documents.
    """
    import json

    Paths.raw_notes.mkdir(parents=True, exist_ok=True)
    doc_ids = []
    for p in paths:
        dest = Paths.raw_notes / p.name
        shutil.copyfile(p, dest)
        doc_ids.append(dest.stem)

    if claim_of:
        idx_path = Paths.data / "doc_index.json"
        idx = {}
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        idx.update({d: claim_of[d] for d in doc_ids if d in claim_of})
        idx_path.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    return doc_ids


# ---------------------------------------------------------------------------
# Phase 1 -- onboarding
# ---------------------------------------------------------------------------
def backfill(repo: Repository, reset: bool = True) -> dict:
    """Full historical load. Trains the model everything afterwards scores against."""
    out = {}
    with runlog.stage("BACKFILL", "full historical load"):
        if reset:
            repo.reset()
            runlog.field("database", "reset to empty")

        with runlog.stage("profile", "segment every note"):
            out["profiling"] = profiling.run(repo)
            _log_profile(out["profiling"])

        with runlog.stage("extract", "Layer 1 over the corpus"):
            out["extraction"] = pipeline_v2.run(repo)
            _log_extract(repo, out["extraction"])

        with runlog.stage("embed", "one vector per mention"):
            out["embed"] = embed_index.run(repo)
            runlog.field("vectors", f"{out['embed'].get('n_nodes', 0)} -> "
                                    f"{Paths.mention_index.name}")

        with runlog.stage("resolve", "train the model and score the corpus"):
            out["resolution"] = entity_resolution.run(repo)
            _log_resolve(out["resolution"])

        with runlog.stage("profile entities", "bitemporal attributes and dossiers"):
            out["profiles"] = profiles.run(repo)
            _log_profiles(out["profiles"])

        with runlog.stage("store", "graph and retrieval index"):
            out["graph"] = build_graph.build_graph(repo)
            runlog.field("graph", f"{out['graph'].get('n_nodes')} nodes, "
                                  f"{out['graph'].get('n_edges')} edges")
            out["chunks"] = build_graph.build_chunk_index(repo)
            runlog.field("chunks", f"{out['chunks'].get('n_chunks')} indexed")

    return out


def is_backfilled(repo: Repository) -> bool:
    if not entity_resolution.MODEL_PATH.exists():
        return False
    if not Paths.mention_index.exists():
        return False
    try:
        return not repo.table("entities").empty
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Phase 2 -- steady state
# ---------------------------------------------------------------------------
def ingest(repo: Repository, doc_ids: list[str], rebuild_graph: bool = True) -> dict:
    """Process arriving notes and fold them into the resolved dataset.

    Cost is proportional to the arriving notes, not the corpus: only these notes
    are segmented, extracted and embedded, and only the pairs their mentions
    generate are scored -- against the model trained during backfill.
    """
    if not is_backfilled(repo):
        raise NotBackfilled(
            "ingest requires a trained model, a mention index and resolved "
            "entities. Run ingest.backfill(repo) first. Refusing rather than "
            "training a model on the arriving notes, which would silently "
            "recalibrate every probability already stored."
        )

    out = {"doc_ids": list(doc_ids)}
    t0 = time.perf_counter()
    with runlog.stage("INGEST", f"{len(doc_ids)} note(s): {', '.join(doc_ids)}"):
        for d in doc_ids:
            f = Paths.raw_notes / f"{d}.txt"
            runlog.field(d, f"{len(f.read_text(encoding='utf-8')):,} chars"
                            if f.exists() else "MISSING")

        with runlog.stage("profile", "segment the arriving notes"):
            out["profiling"] = profiling.run(repo, doc_ids=doc_ids)
            _log_profile(out["profiling"])

        with runlog.stage("extract", "Layer 1 on the arriving notes only"):
            out["extraction"] = pipeline_v2.run(repo, doc_ids=doc_ids)
            _log_extract(repo, out["extraction"], doc_ids=doc_ids)

        with runlog.stage("embed", "upsert their vectors into the index"):
            out["embed"] = embed_index.run(repo, doc_ids=doc_ids)
            runlog.field("vectors", f"{out['embed'].get('n_nodes', 0)} upserted")

        with runlog.stage("resolve", "score against the resolved corpus"):
            out["resolution"] = incremental.resolve_incremental(repo, doc_ids)
            _log_incremental(out["resolution"])

        with runlog.stage("profile entities", "rebuild dossiers for changed entities"):
            # Entity ids are content-derived, so a cluster that gained a mention
            # is a new id -- its dossier has to be rebuilt regardless. This is
            # pure table work, no model calls, so rebuilding all of them is
            # cheaper than working out which ones changed.
            out["profiles"] = profiles.run(repo)
            _log_profiles(out["profiles"])

        # The chunk index is NOT optional and is NOT behind rebuild_graph.
        #
        # This call was missing entirely. An arriving note was profiled,
        # extracted, embedded into mentions.faiss, resolved and added to the
        # graph -- but its chunks never entered chunks.faiss, so Layer 4
        # retrieval could only ever see the backfill corpus. It failed silently:
        # the agent still returned chunks, just never the new ones.
        #
        # Doc-scoped, so the cost is the arriving notes rather than the corpus.
        with runlog.stage("index", "add the arriving notes to the retrieval index"):
            out["chunks"] = build_graph.build_chunk_index(repo, doc_ids=doc_ids)
            runlog.field("chunks", f"{out['chunks'].get('n_chunks')} upserted "
                                   f"into {Paths.chunk_index.name}")

        if rebuild_graph:
            with runlog.stage("store", "refresh the graph"):
                out["graph"] = build_graph.build_graph(repo)
                runlog.field("graph", f"{out['graph'].get('n_nodes')} nodes, "
                                      f"{out['graph'].get('n_edges')} edges")
        else:
            # Say so. A stale graph is a real consequence, not a detail -- the
            # entities exist but nothing new points at them.
            runlog.note("graph NOT rebuilt (rebuild_graph=False): the graph is "
                        "now stale with respect to these notes")
    out["elapsed_s"] = round(time.perf_counter() - t0, 2)
    return out


# ---------------------------------------------------------------------------
# Log formatting -- what each stage decided, not just that it finished
# ---------------------------------------------------------------------------
def _log_profile(r: dict) -> None:
    runlog.field("documents", r.get("n_docs"))
    runlog.field("segments", f"{r.get('n_segments')} "
                             f"({r.get('n_likely_boilerplate_segments', 0)} boilerplate-ish, "
                             f"{r.get('n_case_blind_segments', 0)} case-blind)")
    dups = r.get("n_noncanonical_dups", 0)
    if dups:
        runlog.field("duplicates", f"{dups} segment(s) are near-copies of text already stored")


def _log_extract(repo: Repository, r: dict, doc_ids: list[str] | None = None) -> None:
    m = repo.table("mentions")
    if doc_ids is not None:
        m = m[m["doc_id"].isin(set(doc_ids))]
    runlog.field("mentions", len(m))
    if not m.empty:
        by_extractor = m["extractor"].value_counts().to_dict()
        runlog.field("found by", ", ".join(f"{k} {v}" for k, v in by_extractor.items()))
        runlog.field("classes", ", ".join(
            f"{k} {v}" for k, v in m["entity_class"].value_counts().items()))
    if r.get("n_orphan_identifiers"):
        runlog.field("orphan ids", f"{r['n_orphan_identifiers']} identifier(s) with no "
                                   "name to bind to -- kept, not dropped")


def _log_profiles(r: dict) -> None:
    for k in ("n_entities", "n_dossiers", "n_attributes", "n_conflicts"):
        if k in r:
            runlog.field(k.replace("n_", ""), r[k])


def _log_resolve(r: dict) -> None:
    runlog.field("mentions", r.get("n_mentions"))
    runlog.field("pairs scored", f"{r.get('n_edges_scored'):,}"
                 if r.get("n_edges_scored") else 0)
    runlog.field("suppressed", r.get("n_edges_suppressed"))
    runlog.field("entities", f"{r.get('n_entities')} at threshold "
                             f"{r.get('operating_threshold')}")
    lanes = r.get("blocking_lanes") or {}
    if lanes:
        emb = lanes.get("emb_bucket", 0)
        runlog.field("blocking", f"{sum(lanes.values()):,} pairs; "
                                 f"{emb:,} from the embedding lane alone")
    # SplinkResolver already logged the prior and the evidence ordering during
    # training; what belongs here is the consequence for what got stored.
    if r.get("n_edges_uncalibrated"):
        runlog.field("uncalibrated", f"{r['n_edges_uncalibrated']:,} of "
                                     f"{r.get('n_edges_scored'):,} edges used a "
                                     "substituted m/u value")


def _log_incremental(r: dict) -> None:
    if r.get("note"):
        runlog.note(r["note"])
        return
    runlog.field("new mentions", r.get("n_new_mentions"))
    runlog.field("pairs scored", r.get("n_pairs_scored"))
    runlog.field("above thresh", r.get("n_pairs_above_threshold"))
    for e in r.get("entities_matched_existing", []):
        extra = (f", merging {e['merged_prior_entities']} previously separate entities"
                 if (e.get("merged_prior_entities") or 0) > 1 else "")
        runlog.note(f"MATCHED an existing entity: {e['name']!r} "
                    f"now {e['n_mentions']} mentions{extra}")
    created = r.get("entities_created", [])
    if created:
        runlog.field("new entities", ", ".join(
            repr(c["name"]) for c in created[:6])
            + (f" (+{len(created) - 6} more)" if len(created) > 6 else ""))
    runlog.field("total entities", r.get("n_entities_total"))
