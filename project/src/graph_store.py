"""Layer 3: scoped knowledge graph (dual storage, half 2).

Every node and every edge MUST carry a `claim_id`. That single property is what
makes Layer 4's hard scope filter possible: an agent scoped to CLAIM_123 is
physically unable to traverse into another claim's subgraph, because the
traversal frontier is filtered on claim_id at every hop.

GRAPH DENSITY CONTROL: the predicate schema is a whitelist of domain-specific
verbs (CFG.GRAPH_PREDICATES). Generic edges (MENTIONED_IN, HAS_NOTE,
RELATED_TO, ASSOCIATED_WITH) are REJECTED at insert time -- dense generic edges
turn the graph into a "hairy ball" that dilutes retrieval precision.

Every edge carries provenance (doc_id + char span) so a fact surfaced through
the graph can be traced back to the exact characters that asserted it.
"""
from __future__ import annotations

import json
import pickle
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import igraph as ig

from .settings import CFG, Paths


# Reserved scope for links that are inherently CROSS-CLAIM (a repair shop reusing
# an address under a new TIN; one attorney on many files). These are exactly the
# fraud/network signals an investigator needs, but surfacing them inside a
# claim-scoped agent would breach the scope boundary. So they live under this
# reserved scope and are reachable ONLY through cross_claim_links(), a separate
# API that the per-claim agent never calls unless explicitly authorized.
CROSS_CLAIM_SCOPE = "__CROSS_CLAIM__"


class PredicateRejected(ValueError):
    """Raised when an edge uses a banned or non-whitelisted predicate."""


class ScopeViolation(RuntimeError):
    """Raised when an operation would cross a claim boundary."""


@dataclass
class GraphNode:
    node_id: str                 # canonical entity id (from Layer 2 ER)
    claim_id: str                # MANDATORY scope key
    label: str                   # entity class
    name: str
    description: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    predicate: str               # must be in CFG.GRAPH_PREDICATES
    claim_id: str                # MANDATORY scope key
    doc_id: str = ""             # provenance
    span: tuple = (0, 0)
    confidence: float = 1.0
    polarity: str = "asserted"


def validate_predicate(predicate: str) -> str:
    p = (predicate or "").upper()
    if p in {b.upper() for b in CFG.GRAPH_BANNED_PREDICATES}:
        raise PredicateRejected(
            f"predicate {p!r} is banned (generic edges dilute retrieval precision); "
            f"use one of {CFG.GRAPH_PREDICATES}")
    if p not in {x.upper() for x in CFG.GRAPH_PREDICATES}:
        raise PredicateRejected(
            f"predicate {p!r} is not in the restricted domain schema {CFG.GRAPH_PREDICATES}")
    return p


class GraphStore(ABC):
    """Abstract claim-scoped knowledge graph.

    Contract every implementation must honor:
      - upsert_nodes / upsert_edges: reject any node or edge lacking a claim_id,
        and reject any predicate outside the whitelist.
      - neighbors(node_ids, hops, claim_id): breadth-limited expansion that never
        leaves `claim_id`. Must return the triples traversed, with provenance.
      - subgraph(claim_id): everything inside one claim.
      - persist / load.

    ---------------------------------------------------------------------------
    To swap in Neo4j (Neo4jGraphStore), implement the same five methods:
      * upsert_nodes -> MERGE (n:Entity {node_id}) SET n.claim_id = $claim_id ...
        with an index on (claim_id, node_id).
      * upsert_edges -> MERGE (a)-[r:PREDICATE {claim_id}]->(b) after running the
        same validate_predicate() check.
      * neighbors    -> MATCH p=(a)-[*1..hops]-(b) WHERE a.node_id IN $ids AND
        ALL(r IN relationships(p) WHERE r.claim_id = $claim_id) -- the claim_id
        predicate MUST be inside the traversal, not a post-filter, or the scope
        boundary is unenforced.
      * subgraph / persist -> label-scoped MATCH and no-op respectively.
    Nothing in Layer 4 changes.
    ---------------------------------------------------------------------------
    """

    @abstractmethod
    def upsert_nodes(self, nodes: list[GraphNode]) -> int: ...

    @abstractmethod
    def upsert_edges(self, edges: list[GraphEdge]) -> int: ...

    @abstractmethod
    def neighbors(self, node_ids: list[str], hops: int, claim_id: str) -> list[dict]: ...

    @abstractmethod
    def subgraph(self, claim_id: str) -> dict: ...

    @abstractmethod
    def persist(self) -> None: ...

    @abstractmethod
    def load(self) -> None: ...


class IGraphStore(GraphStore):
    """igraph-backed implementation with claim_id-partitioned adjacency."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or (Paths.store / CFG.GRAPH_FILENAME))
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        # adjacency partitioned by claim so traversal cannot leak across claims
        self._adj: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    # ---- writes ----------------------------------------------------------
    def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        n = 0
        for nd in nodes:
            if not nd.claim_id:
                raise ScopeViolation(f"node {nd.node_id!r} has no claim_id; every node must be scoped")
            key = self._nkey(nd.node_id, nd.claim_id)
            self._nodes[key] = nd
            n += 1
        return n

    def upsert_edges(self, edges: list[GraphEdge]) -> int:
        n = 0
        for e in edges:
            if not e.claim_id:
                raise ScopeViolation(f"edge {e.src}->{e.dst} has no claim_id; every edge must be scoped")
            e.predicate = validate_predicate(e.predicate)
            idx = len(self._edges)
            self._edges.append(e)
            self._adj[e.claim_id][e.src].append(idx)
            self._adj[e.claim_id][e.dst].append(idx)   # undirected traversal, directed semantics
            n += 1
        return n

    @staticmethod
    def _nkey(node_id: str, claim_id: str) -> str:
        return f"{claim_id}::{node_id}"

    # ---- reads -----------------------------------------------------------
    def neighbors(self, node_ids: list[str], hops: int, claim_id: str) -> list[dict]:
        """BFS up to `hops`, never leaving `claim_id`.

        The claim filter is applied to the ADJACENCY ITSELF (we only ever read
        self._adj[claim_id]), so an edge belonging to another claim is not merely
        filtered out of the result -- it is unreachable.
        """
        if not claim_id:
            raise ScopeViolation("neighbors() requires a claim_id scope")
        if claim_id == CROSS_CLAIM_SCOPE:
            raise ScopeViolation(
                "cross-claim links are not traversable through neighbors(); "
                "use cross_claim_links() which is separately authorized")
        adj = self._adj.get(claim_id, {})
        seen_edges: set[int] = set()
        frontier = {nid for nid in node_ids}
        visited = set(frontier)
        triples: list[dict] = []
        for _ in range(max(0, hops)):
            nxt = set()
            for nid in frontier:
                for ei in adj.get(nid, []):
                    if ei in seen_edges:
                        continue
                    seen_edges.add(ei)
                    e = self._edges[ei]
                    if e.claim_id != claim_id:          # defense in depth
                        continue
                    triples.append(self._triple(e))
                    for other in (e.src, e.dst):
                        if other not in visited:
                            nxt.add(other)
                            visited.add(other)
            frontier = nxt
            if not frontier:
                break
        return triples

    def _triple(self, e: GraphEdge) -> dict:
        s = self._nodes.get(self._nkey(e.src, e.claim_id))
        d = self._nodes.get(self._nkey(e.dst, e.claim_id))
        return {
            "subject_id": e.src, "subject": s.name if s else e.src,
            "subject_class": s.label if s else "?",
            "predicate": e.predicate,
            "object_id": e.dst, "object": d.name if d else e.dst,
            "object_class": d.label if d else "?",
            "claim_id": e.claim_id, "doc_id": e.doc_id,
            "span": list(e.span), "confidence": e.confidence, "polarity": e.polarity,
        }

    def subgraph(self, claim_id: str) -> dict:
        if not claim_id:
            raise ScopeViolation("subgraph() requires a claim_id scope")
        nodes = [asdict(n) for k, n in self._nodes.items() if n.claim_id == claim_id]
        edges = [self._triple(e) for e in self._edges if e.claim_id == claim_id]
        return {"claim_id": claim_id, "nodes": nodes, "edges": edges}

    def cross_claim_links(self, node_ids: list[str], authorized: bool = False) -> list[dict]:
        """Cross-claim network links (shared address / phone / identifier).

        SEPARATELY AUTHORIZED. The per-claim retrieval agent must never call this
        with authorized=True unless the caller holds cross-claim investigation
        rights; a claim-scoped session cannot reach these edges via neighbors().
        Returns the links plus, for each, the claims each endpoint touches.
        """
        if not authorized:
            raise ScopeViolation(
                "cross_claim_links() requires authorized=True (cross-claim "
                "investigation scope); claim-scoped agents may not call it")
        ids = set(node_ids)
        out = []
        for e in self._edges:
            if e.claim_id != CROSS_CLAIM_SCOPE:
                continue
            if e.src in ids or e.dst in ids:
                t = self._triple(e)
                t["claims_of_subject"] = sorted(self._claims_of(e.src))
                t["claims_of_object"] = sorted(self._claims_of(e.dst))
                out.append(t)
        return out

    def _claims_of(self, node_id: str) -> set:
        return {n.claim_id for n in self._nodes.values()
                if n.node_id == node_id and n.claim_id != CROSS_CLAIM_SCOPE}

    def node(self, node_id: str, claim_id: str) -> GraphNode | None:
        return self._nodes.get(self._nkey(node_id, claim_id))

    def claim_ids(self) -> list[str]:
        return sorted({n.claim_id for n in self._nodes.values()})

    def stats(self) -> dict:
        from collections import Counter
        return {
            "n_nodes": len(self._nodes), "n_edges": len(self._edges),
            "n_claims": len(self.claim_ids()),
            "predicates": dict(Counter(e.predicate for e in self._edges)),
            "avg_edges_per_claim": round(len(self._edges) / max(1, len(self.claim_ids())), 2),
        }

    def to_igraph(self, claim_id: str) -> ig.Graph:
        """Materialize one claim's subgraph as an igraph object for analytics."""
        sub = self.subgraph(claim_id)
        ids = [n["node_id"] for n in sub["nodes"]]
        idx = {v: i for i, v in enumerate(ids)}
        g = ig.Graph(n=len(ids), directed=True)
        g.vs["node_id"] = ids
        g.vs["name_"] = [n["name"] for n in sub["nodes"]]
        g.vs["label_"] = [n["label"] for n in sub["nodes"]]
        es, preds = [], []
        for e in sub["edges"]:
            if e["subject_id"] in idx and e["object_id"] in idx:
                es.append((idx[e["subject_id"]], idx[e["object_id"]]))
                preds.append(e["predicate"])
        g.add_edges(es)
        if preds:
            g.es["predicate"] = preds
        return g

    # ---- persistence -----------------------------------------------------
    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "wb") as f:
            pickle.dump({"nodes": self._nodes, "edges": self._edges}, f)

    def load(self) -> None:
        with open(self.path, "rb") as f:
            data = pickle.load(f)
        self._nodes = data["nodes"]
        self._edges = data["edges"]
        self._adj = defaultdict(lambda: defaultdict(list))
        for i, e in enumerate(self._edges):
            self._adj[e.claim_id][e.src].append(i)
            self._adj[e.claim_id][e.dst].append(i)


def get_graph_store(backend: str | None = None) -> GraphStore:
    b = (backend or CFG.GRAPH_BACKEND).lower()
    if b == "neo4j":
        raise NotImplementedError(
            "Neo4jGraphStore is the production swap; implement GraphStore's five "
            "methods per the class docstring. Set GRAPH_BACKEND='igraph' to run locally.")
    return IGraphStore()
