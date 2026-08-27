"""Layer 3 builder: populate the dual storage system.

Reads Layer 1/2 output from the repository and writes:
  1. the claim-scoped knowledge graph (nodes + domain-verb edges + provenance)
  2. the chunk vector index (chunk embeddings + metadata carrying claim_id)

Relationship inference is deliberately conservative and schema-restricted: only
the domain verbs in CFG.GRAPH_PREDICATES are emitted, derived from resolved
entity roles, co-membership on a claim, and shared identifiers/addresses. No
generic MENTIONED_IN edges.
"""
from __future__ import annotations

from collections import defaultdict

from . import chunking, genai, textnorm
from .graph_store import (CROSS_CLAIM_SCOPE, GraphEdge, GraphNode, GraphStore,
                          get_graph_store)
from .repository import Repository
from .settings import CFG, Paths
from .vectorstore import FaissVectorStore

# entity class -> the predicate linking it to the claimant of that claim
ROLE_PREDICATE = {
    "attorney": "REPRESENTED_BY",
    "medical_provider": "TREATED_BY",
    "repair_shop": "REPAIRED_BY",
    "adjuster": "ADJUSTED_BY",
}


def build_chunk_index(repo: Repository, store: FaissVectorStore | None = None) -> dict:
    """Embed every chunk and index it with claim_id in the metadata payload."""
    docs = repo.table("documents")
    claim_of = {r["doc_id"]: r["claim_id"] for _, r in docs.iterrows()}
    texts = {f.stem: f.read_text() for f in Paths.raw_notes.glob("*.txt")}
    doc_map = {d: (claim_of.get(d, "UNKNOWN"), t) for d, t in texts.items()}
    chunks = chunking.chunk_corpus(doc_map)

    vecs = genai.embed([c.text for c in chunks])
    store = store or FaissVectorStore(
        CFG.EMBED_DIM, Paths.store / CFG.CHUNK_INDEX_FILENAME,
        Paths.store / CFG.CHUNK_META_FILENAME)
    store.upsert([c.chunk_id for c in chunks], vecs,
                 [{**c.to_meta(), "text": c.text} for c in chunks])
    store.persist()
    return {"n_chunks": len(chunks), "index": str(store.index_path)}


def build_graph(repo: Repository, graph: GraphStore | None = None) -> dict:
    """Derive claim-scoped nodes and domain-verb edges from resolved entities."""
    graph = graph or get_graph_store()

    entities = repo.table("entities").set_index("entity_id")
    members = repo.table("entity_members")
    mentions = repo.table("mentions").set_index("mention_id")
    docs = repo.table("documents").set_index("doc_id")["claim_id"].to_dict()
    assertions = repo.table("assertions")

    # entity -> claims it appears on, with a representative mention per claim
    ent_claims: dict[str, dict[str, dict]] = defaultdict(dict)
    for _, r in members.iterrows():
        mid = r["mention_id"]
        if mid not in mentions.index:
            continue
        m = mentions.loc[mid]
        claim = docs.get(m["doc_id"], "UNKNOWN")
        ent_claims[r["entity_id"]].setdefault(claim, {
            "doc_id": m["doc_id"], "span": (int(m["char_start"]), int(m["char_end"])),
        })

    # ---- nodes: one per (entity, claim) so every node carries a claim scope --
    nodes: list[GraphNode] = []
    for eid, claims in ent_claims.items():
        if eid not in entities.index:
            continue
        ent = entities.loc[eid]
        for claim in claims:
            nodes.append(GraphNode(
                node_id=eid, claim_id=claim,
                label=ent["entity_class"], name=ent["canonical_name"] or eid,
                description=f"{ent['entity_class']} on claim {claim}",
                attrs={"n_mentions": int(ent["n_mentions"])},
            ))
    graph.upsert_nodes(nodes)

    # ---- edges --------------------------------------------------------------
    edges: list[GraphEdge] = []
    by_claim: dict[str, list[str]] = defaultdict(list)
    for eid, claims in ent_claims.items():
        for c in claims:
            by_claim[c].append(eid)

    for claim, eids in by_claim.items():
        claimants = [e for e in eids if e in entities.index
                     and entities.loc[e]["entity_class"] == "claimant"]
        anchor = claimants[0] if claimants else None
        for eid in eids:
            if eid not in entities.index:
                continue
            cls = entities.loc[eid]["entity_class"]
            prov = ent_claims[eid][claim]
            # PARTY_TO: every resolved entity is a party to the claim it appears on
            edges.append(GraphEdge(src=eid, dst=f"CLAIM::{claim}", predicate="PARTY_TO",
                                   claim_id=claim, doc_id=prov["doc_id"], span=prov["span"]))
            pred = ROLE_PREDICATE.get(cls)
            if pred and anchor and eid != anchor:
                edges.append(GraphEdge(src=anchor, dst=eid, predicate=pred, claim_id=claim,
                                       doc_id=prov["doc_id"], span=prov["span"], confidence=0.9))
        # the claim node itself
        graph.upsert_nodes([GraphNode(node_id=f"CLAIM::{claim}", claim_id=claim,
                                      label="claim", name=claim,
                                      description=f"claim file {claim}")])

    # ---- allegation + shared-identifier edges (within claim scope) ----------
    grounded = assertions[assertions["grounded"] == 1]
    mention_to_entity = {r["mention_id"]: r["entity_id"] for _, r in members.iterrows()}

    alleg_n = 0
    for _, a in grounded[grounded["predicate"] == "allegation"].iterrows():
        eid = mention_to_entity.get(a["subject_mention_id"])
        if not eid:
            continue
        claim = docs.get(a["source_doc_id"], "UNKNOWN")
        if claim not in ent_claims.get(eid, {}):
            continue
        node_id = f"ALLEG::{a['assertion_id']}"
        graph.upsert_nodes([GraphNode(node_id=node_id, claim_id=claim, label="allegation",
                                      name=(a["object_value_raw"] or "")[:120],
                                      description="allegation (segregated from fact)")])
        edges.append(GraphEdge(src=eid, dst=node_id, predicate="ALLEGES", claim_id=claim,
                               doc_id=a["source_doc_id"],
                               span=(int(a["source_span_start"]), int(a["source_span_end"])),
                               polarity="alleged", confidence=0.7))
        alleg_n += 1

    # shared identifier / address links, emitted only inside a shared claim scope
    ident_index: dict[tuple, set] = defaultdict(set)
    for _, a in grounded.iterrows():
        eid = mention_to_entity.get(a["subject_mention_id"])
        if not eid:
            continue
        p = a["predicate"]
        if p in ("has_email", "has_phone", "has_npi", "has_tin", "has_ssn"):
            ident_index[(p, a["object_value_norm"])].add(eid)
        elif p == "has_address":
            k = textnorm.address_key(a["object_value_raw"] or "")
            if k:
                ident_index[("addr", k)].add(eid)

    # Shared identifiers link entities that are usually on DIFFERENT claims (a
    # phoenix shop, one attorney across many files). Emitting those inside a
    # claim scope would breach the boundary, so they go to the reserved
    # cross-claim scope, reachable only via graph.cross_claim_links(authorized=True).
    shared_same_claim = 0
    shared_cross_claim = 0
    for (kind, val), eids in ident_index.items():
        if len(eids) < 2:
            continue
        eids = sorted(eids)
        pred = ("SHARES_ADDRESS_WITH" if kind == "addr"
                else "SHARES_PHONE_WITH" if kind == "has_phone"
                else "SHARES_IDENTIFIER_WITH")
        for i in range(len(eids)):
            for j in range(i + 1, len(eids)):
                a_, b_ = eids[i], eids[j]
                claims_a = set(ent_claims.get(a_, {}))
                claims_b = set(ent_claims.get(b_, {}))
                common = claims_a & claims_b
                for claim in common:
                    prov = ent_claims[a_][claim]
                    edges.append(GraphEdge(src=a_, dst=b_, predicate=pred, claim_id=claim,
                                           doc_id=prov["doc_id"], span=prov["span"],
                                           confidence=0.8))
                    shared_same_claim += 1
                if claims_a - common and claims_b - common:
                    prov = ent_claims[a_][sorted(claims_a)[0]]
                    edges.append(GraphEdge(src=a_, dst=b_, predicate=pred,
                                           claim_id=CROSS_CLAIM_SCOPE,
                                           doc_id=prov["doc_id"], span=prov["span"],
                                           confidence=0.8))
                    shared_cross_claim += 1
                    for nid in (a_, b_):
                        if nid in entities.index:
                            graph.upsert_nodes([GraphNode(
                                node_id=nid, claim_id=CROSS_CLAIM_SCOPE,
                                label=entities.loc[nid]["entity_class"],
                                name=entities.loc[nid]["canonical_name"] or nid,
                                description="cross-claim network node")])

    graph.upsert_edges(edges)
    graph.persist()
    st = graph.stats()
    st.update({"n_allegation_edges": alleg_n,
               "n_shared_same_claim": shared_same_claim,
               "n_shared_cross_claim": shared_cross_claim})
    return st


def run(repo: Repository) -> dict:
    idx = build_chunk_index(repo)
    g = build_graph(repo)
    return {"chunk_index": idx, "graph": g}
