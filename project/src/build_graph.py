"""Layer 3 builder: populate the global entity graph + the chunk vector index.

Node kinds, all first-class:
  party         resolved person (claimant / attorney / adjuster / provider)
  organization  firm, practice, shop
  identifier    address / phone / email / npi / tin / ssn  -- their own nodes,
                which is what makes an unnamed identifier mention resolvable
  event         dated action with no external id
  claim         containment
  occurrence    containment (claims group under it)

Predicates are an OPEN vocabulary: whatever the relation extractor supports is
emitted, normalized toward canonical forms. Only bulk provenance is rejected.
"""
from __future__ import annotations

from collections import defaultdict

from . import chunking, genai, profiling, textnorm
from .graph_store import GraphEdge, GraphNode, GraphStore, get_graph_store
from .repository import Repository
from .settings import CFG, Paths
from .vectorstore import FaissVectorStore


class ChunkIndexUnavailable(RuntimeError):
    """Incremental chunk indexing was asked to extend an index that is absent.

    Distinct from agent.AgentStoreUnavailable, which is the query-time failure.
    This one means the backfill never ran, so there is nothing to add to.
    """

# entity class -> the verb linking it to the claimant on that claim
ROLE_PREDICATE = {
    "attorney": "REPRESENTED_BY",
    "medical_provider": "TREATED_BY",
    "repair_shop": "REPAIRED_BY",
    "adjuster": "ADJUSTED_BY",
}
ORG_CLASSES = {"repair_shop"}


def build_chunk_index(repo: Repository, store: FaissVectorStore | None = None,
                      doc_ids: list[str] | None = None) -> dict:
    """Embed chunks; claim_id and occurrence_id ride in the metadata so the RAG
    path can filter to a claim without the graph being partitioned.

    `doc_ids` restricts the pass to arriving notes and UPSERTS them into the
    existing index. Without it the whole corpus is re-chunked and re-embedded.

    This parameter is not an optimisation. `ingest()` did not call this function
    at all, so chunks from an arriving note never entered chunks.faiss and Layer
    4 retrieval could only ever see the backfill corpus -- silently, since the
    agent still returned chunks, just never the new ones.
    """
    docs = repo.table("documents")
    claim_of = {r["doc_id"]: r["claim_id"] for _, r in docs.iterrows()}
    occ_of = ({r["doc_id"]: r.get("occurrence_id") for _, r in docs.iterrows()}
              if "occurrence_id" in docs.columns else {})
    texts = {f.stem: f.read_text(encoding="utf-8")
             for f in profiling.note_files(doc_ids)}
    doc_map = {d: (claim_of.get(d, "UNKNOWN"), t) for d, t in texts.items()}
    chunks = chunking.chunk_corpus(doc_map)

    store = store or FaissVectorStore(
        CFG.EMBED_DIM, Paths.chunk_index, Paths.chunk_meta)
    if doc_ids is not None:
        # Add to what is already indexed rather than replacing it.
        try:
            store.load()
        except FileNotFoundError as e:
            raise ChunkIndexUnavailable(
                "incremental chunk indexing asked to add to " +
                str(Paths.chunk_index) + ", which does not exist. Run the "
                "backfill first."
            ) from e

    if not chunks:
        return {"n_chunks": 0, "index": str(store.index_path)}
    vecs = genai.embed([c.text for c in chunks])
    store.upsert([c.chunk_id for c in chunks], vecs,
                 [{**c.to_meta(), "occurrence_id": occ_of.get(c.doc_id) or "",
                   "text": c.text} for c in chunks])
    store.persist()
    return {"n_chunks": len(chunks), "index": str(store.index_path),
            "scope": "incremental" if doc_ids is not None else "full"}


def build_graph(repo: Repository, graph: GraphStore | None = None) -> dict:
    graph = graph or get_graph_store()

    entities = repo.table("entities")
    if entities.empty:
        return {"error": "no resolved entities; run entity_resolution first"}
    entities = entities.set_index("entity_id")
    members = repo.table("entity_members")
    mentions = repo.table("mentions").set_index("mention_id")
    docs = repo.table("documents").set_index("doc_id")
    claim_of = docs["claim_id"].to_dict()
    occ_of = docs["occurrence_id"].to_dict() if "occurrence_id" in docs.columns else {}

    # entity -> the claims/occurrences it touches, plus provenance per claim
    ent_claims: dict[str, dict] = defaultdict(dict)
    ent_occ: dict[str, set] = defaultdict(set)
    mention_to_entity: dict[str, str] = {}
    for _, r in members.iterrows():
        mid = r["mention_id"]
        mention_to_entity[mid] = r["entity_id"]
        if mid not in mentions.index:
            continue
        m = mentions.loc[mid]
        c = claim_of.get(m["doc_id"], "UNKNOWN")
        o = occ_of.get(m["doc_id"]) or ""
        ent_claims[r["entity_id"]].setdefault(
            c, {"doc_id": m["doc_id"],
                "span": (int(m["char_start"]), int(m["char_end"]))})
        if o:
            ent_occ[r["entity_id"]].add(o)

    nodes, edges = [], []

    # ---- party / organization nodes (one per ENTITY, spanning all claims) ---
    for eid, claims in ent_claims.items():
        if eid not in entities.index:
            continue
        ent = entities.loc[eid]
        kind = "organization" if ent["entity_class"] in ORG_CLASSES else "party"
        nodes.append(GraphNode(
            node_id=eid, kind=kind, label=ent["entity_class"],
            name=ent["canonical_name"] or eid,
            claim_ids=set(claims), occurrence_ids=set(ent_occ.get(eid, ())),
            attrs={"n_mentions": int(ent["n_mentions"])}))

    # ---- containment: claim + occurrence -----------------------------------
    claims_seen = {c for cs in ent_claims.values() for c in cs}
    for c in claims_seen:
        nodes.append(GraphNode(node_id=f"CLAIM::{c}", kind="claim", name=c,
                               claim_ids={c}))
    occ_claims = defaultdict(set)
    for d, c in claim_of.items():
        o = occ_of.get(d)
        if o:
            occ_claims[o].add(c)
    for o, cs in occ_claims.items():
        nodes.append(GraphNode(node_id=f"OCC::{o}", kind="occurrence", name=o,
                               claim_ids=set(cs), occurrence_ids={o}))
        for c in cs:
            edges.append(GraphEdge(src=f"CLAIM::{c}", dst=f"OCC::{o}",
                                   predicate="PART_OF", claim_id=c, occurrence_id=o))

    for eid, claims in ent_claims.items():
        for c, prov in claims.items():
            edges.append(GraphEdge(src=eid, dst=f"CLAIM::{c}", predicate="PARTY_TO",
                                   claim_id=c, doc_id=prov["doc_id"],
                                   span=prov["span"]))

    # ---- role edges, anchored on the claimant of each claim ----------------
    by_claim = defaultdict(list)
    for eid, claims in ent_claims.items():
        for c in claims:
            by_claim[c].append(eid)
    for c, eids in by_claim.items():
        anchors = [e for e in eids
                   if e in entities.index and entities.loc[e]["entity_class"] == "claimant"]
        anchor = anchors[0] if anchors else None
        if not anchor:
            continue
        for eid in eids:
            if eid == anchor or eid not in entities.index:
                continue
            pred = ROLE_PREDICATE.get(entities.loc[eid]["entity_class"])
            if pred:
                prov = ent_claims[eid][c]
                edges.append(GraphEdge(src=anchor, dst=eid, predicate=pred, claim_id=c,
                                       doc_id=prov["doc_id"], span=prov["span"],
                                       confidence=0.9))

    # ---- identifier nodes: first-class, including orphans -------------------
    n_orphan_edges = 0
    try:
        obs = repo.table("identifier_observations")
    except Exception:
        obs = None
    if obs is not None and not obs.empty:
        for _, o in obs.iterrows():
            val = o["value_norm"] or o["value_raw"]
            if not val:
                continue
            nid = f"ID::{o['kind']}::{val}"
            c = claim_of.get(o["doc_id"], "UNKNOWN")
            oc = occ_of.get(o["doc_id"]) or ""
            nodes.append(GraphNode(node_id=nid, kind="identifier", label=o["kind"],
                                   name=str(o["value_raw"]), claim_ids={c},
                                   occurrence_ids={oc} if oc else set()))
            subj = o["subject_mention_id"]
            eid = mention_to_entity.get(subj) if subj else None
            if eid:
                edges.append(GraphEdge(
                    src=eid, dst=nid, predicate="HAS_IDENTIFIER", claim_id=c,
                    occurrence_id=oc, doc_id=o["doc_id"],
                    span=(int(o["char_start"]), int(o["char_end"])),
                    confidence=0.95 if o["validated"] else 0.7))
            else:
                # orphan: no name bound. It still connects to the claim, which is
                # what lets a later query attribute it through the identifier.
                edges.append(GraphEdge(
                    src=nid, dst=f"CLAIM::{c}", predicate="OBSERVED_ON", claim_id=c,
                    occurrence_id=oc, doc_id=o["doc_id"],
                    span=(int(o["char_start"]), int(o["char_end"])),
                    confidence=0.6))
                n_orphan_edges += 1

    graph.upsert_nodes(nodes)
    graph.upsert_edges(edges)
    graph.persist()
    st = graph.stats()
    st["n_orphan_identifier_edges"] = n_orphan_edges
    st["hubs"] = graph.hub_nodes(5) if hasattr(graph, "hub_nodes") else []
    return st


def run(repo: Repository) -> dict:
    return {"chunk_index": build_chunk_index(repo), "graph": build_graph(repo)}
