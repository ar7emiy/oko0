"""Layer 3: the entity graph.

THREE CORRECTIONS FROM THE FIRST BUILD
--------------------------------------
1. **Identity is global, not claim-partitioned.** The first version partitioned
   adjacency by claim_id so a traversal physically could not leave a claim. That
   was the wrong boundary: a person is the same person across every claim in the
   corpus, and cross-claim linkage is the point of the system, not a hazard.
   `claim_id` and `occurrence_id` are now node/edge PROPERTIES and containment
   edges. Claim scoping is a QUERY-TIME FILTER, which is what the RAG path needs.

2. **Cross-claim edges are ordinary edges.** The first version quarantined them
   behind an authorization gate. Removed: cross-claim linkage is axiomatic here.

3. **Predicates are an OPEN vocabulary.** The first version enforced a
   whitelist of four role verbs, which silently dropped or force-fit everything
   else (witnessed, referred, co_counsel, supervises, subcontracts_to,
   opposing_counsel, ...). Now any predicate is accepted; only bulk
   provenance-as-edge is rejected, and a normalization map folds surface forms
   toward canonical types over time.

Density is controlled by confidence and hub down-weighting, not by banning edge
types. Every edge carries a probability and a doc_id + char span.
"""
from __future__ import annotations

import pickle
import re
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import igraph as ig

from .settings import CFG, Paths


class PredicateRejected(ValueError):
    """Raised only for bulk provenance-as-edge, never for an unfamiliar verb."""


# ---------------------------------------------------------------------------
# Node / edge records
# ---------------------------------------------------------------------------
NODE_KINDS = ("party", "organization", "identifier", "event", "claim",
              "occurrence", "allegation")


@dataclass
class GraphNode:
    node_id: str
    kind: str                    # one of NODE_KINDS
    label: str = ""              # entity class / identifier kind / event type
    name: str = ""
    claim_ids: set = field(default_factory=set)
    occurrence_ids: set = field(default_factory=set)
    attrs: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["claim_ids"] = sorted(self.claim_ids)
        d["occurrence_ids"] = sorted(self.occurrence_ids)
        return d


@dataclass
class GraphEdge:
    src: str
    dst: str
    predicate: str
    claim_id: str = ""           # property, NOT a partition key
    occurrence_id: str = ""
    doc_id: str = ""
    span: tuple = (0, 0)
    confidence: float = 1.0
    polarity: str = "asserted"


# ---------------------------------------------------------------------------
# Predicate handling -- open vocabulary
# ---------------------------------------------------------------------------
# Bulk provenance is not a relationship: it is already carried as doc_id + span
# properties on every real edge, and as an edge to the claim node. Emitting it
# as its own edge type is what produces an unnavigable "hairy ball".
BANNED_PREDICATES = {"MENTIONED_IN", "HAS_NOTE", "APPEARS_IN", "REFERENCED_BY"}

# Surface forms folded toward a canonical type. This grows into a taxonomy;
# anything not listed passes through unchanged rather than being dropped.
PREDICATE_NORMALIZATION = {
    "WENT_TO": "TREATED_BY", "WAS_SEEN_AT": "TREATED_BY", "VISITED": "TREATED_BY",
    "SEEN_BY": "TREATED_BY", "TREATS": "TREATED_BY",
    "REPRESENTS": "REPRESENTED_BY", "COUNSEL_FOR": "REPRESENTED_BY",
    "REPAIRS": "REPAIRED_BY", "FIXED": "REPAIRED_BY",
    "ADJUSTS": "ADJUSTED_BY", "HANDLED_BY": "ADJUSTED_BY",
    "WORKS_FOR": "EMPLOYED_BY", "EMPLOYED_AT": "EMPLOYED_BY",
}


def normalize_predicate(predicate: str) -> str:
    """Fold a surface predicate toward its canonical form.

    Unknown predicates pass through: an open vocabulary is the point. A closed
    set drops real relationships or force-fits them into the wrong semantics.
    """
    p = re.sub(r"\s+", "_", (predicate or "").strip()).upper()
    if p in BANNED_PREDICATES:
        raise PredicateRejected(
            f"{p!r} is bulk provenance, not a relationship -- it is already "
            "carried as doc_id + span on every edge")
    return PREDICATE_NORMALIZATION.get(p, p)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
class GraphStore(ABC):
    """Global entity graph.

    Contract:
      - upsert_nodes / upsert_edges: accept any predicate except bulk
        provenance; normalize surface forms; carry confidence + provenance.
      - neighbors(node_ids, hops, claim_id=None): breadth-limited expansion over
        the GLOBAL graph. `claim_id` is an optional filter, not a wall -- pass it
        to answer "within this claim", omit it to follow an entity anywhere.
      - subgraph(claim_id) / persist / load.

    To swap in Neo4j: implement these methods with (claim_id) as an indexed
    property and an optional WHERE clause, NOT as a partition or label.
    """

    @abstractmethod
    def upsert_nodes(self, nodes: list[GraphNode]) -> int: ...

    @abstractmethod
    def upsert_edges(self, edges: list[GraphEdge]) -> int: ...

    @abstractmethod
    def neighbors(self, node_ids: list[str], hops: int,
                  claim_id: str | None = None,
                  min_confidence: float = 0.0) -> list[dict]: ...

    @abstractmethod
    def subgraph(self, claim_id: str) -> dict: ...

    @abstractmethod
    def persist(self) -> None: ...

    @abstractmethod
    def load(self) -> None: ...


class IGraphStore(GraphStore):
    """In-memory global graph with a single adjacency index."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or (Paths.store / CFG.GRAPH_FILENAME))
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._adj: dict[str, list[int]] = defaultdict(list)   # GLOBAL, not per-claim

    # ---- writes ----------------------------------------------------------
    def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        for nd in nodes:
            cur = self._nodes.get(nd.node_id)
            if cur is None:
                self._nodes[nd.node_id] = nd
            else:
                cur.claim_ids |= nd.claim_ids
                cur.occurrence_ids |= nd.occurrence_ids
                cur.attrs.update(nd.attrs)
                if nd.name and not cur.name:
                    cur.name = nd.name
        return len(nodes)

    def upsert_edges(self, edges: list[GraphEdge]) -> int:
        n = 0
        for e in edges:
            e.predicate = normalize_predicate(e.predicate)
            idx = len(self._edges)
            self._edges.append(e)
            self._adj[e.src].append(idx)
            self._adj[e.dst].append(idx)
            n += 1
        return n

    # ---- reads -----------------------------------------------------------
    def neighbors(self, node_ids: list[str], hops: int,
                  claim_id: str | None = None,
                  min_confidence: float = 0.0) -> list[dict]:
        """BFS over the global graph.

        `claim_id` filters which edges may be traversed; omitting it follows an
        entity across every claim and occurrence in the corpus, which is the
        whole point of a global identity graph.
        """
        seen_edges: set[int] = set()
        frontier = set(node_ids)
        visited = set(frontier)
        triples = []
        for _ in range(max(0, hops)):
            nxt = set()
            for nid in frontier:
                for ei in self._adj.get(nid, []):
                    if ei in seen_edges:
                        continue
                    seen_edges.add(ei)
                    e = self._edges[ei]
                    if claim_id is not None and e.claim_id != claim_id:
                        continue
                    if e.confidence < min_confidence:
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
        s, d = self._nodes.get(e.src), self._nodes.get(e.dst)
        return {
            "subject_id": e.src, "subject": s.name if s else e.src,
            "subject_kind": s.kind if s else "?",
            "predicate": e.predicate,
            "object_id": e.dst, "object": d.name if d else e.dst,
            "object_kind": d.kind if d else "?",
            "claim_id": e.claim_id, "occurrence_id": e.occurrence_id,
            "doc_id": e.doc_id, "span": list(e.span),
            "confidence": e.confidence, "polarity": e.polarity,
        }

    def subgraph(self, claim_id: str) -> dict:
        nodes = [n.to_dict() for n in self._nodes.values() if claim_id in n.claim_ids]
        edges = [self._triple(e) for e in self._edges if e.claim_id == claim_id]
        return {"claim_id": claim_id, "nodes": nodes, "edges": edges}

    def cross_claim_links(self, node_ids: list[str],
                          min_confidence: float = 0.0) -> list[dict]:
        """Edges connecting a node to entities on OTHER claims.

        An ordinary read. No authorization gate: cross-claim linkage is the
        system's purpose, and quarantining it behind a permission check made the
        fraud/network signal unreachable by the very queries that need it.
        """
        ids = set(node_ids)
        out = []
        for e in self._edges:
            if e.confidence < min_confidence:
                continue
            if e.src in ids or e.dst in ids:
                other = e.dst if e.src in ids else e.src
                nd = self._nodes.get(other)
                mine = self._nodes.get(e.src if e.src in ids else e.dst)
                if nd and mine and (nd.claim_ids - mine.claim_ids):
                    t = self._triple(e)
                    t["other_claims"] = sorted(nd.claim_ids - mine.claim_ids)
                    out.append(t)
        return out

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def find_by_identifier(self, kind: str, value_norm: str) -> list[dict]:
        """Everything ever associated with an identifier -- the 'address with no
        name' query, as a direct lookup."""
        nid = f"ID::{kind}::{value_norm}"
        if nid not in self._nodes:
            return []
        return self.neighbors([nid], hops=1)

    def stats(self) -> dict:
        return {
            "n_nodes": len(self._nodes),
            "n_edges": len(self._edges),
            "node_kinds": dict(Counter(n.kind for n in self._nodes.values())),
            "predicates": dict(Counter(e.predicate for e in self._edges)),
            "n_claims": len({c for n in self._nodes.values() for c in n.claim_ids}),
            "n_occurrences": len({o for n in self._nodes.values() for o in n.occurrence_ids}),
        }

    def to_igraph(self) -> ig.Graph:
        ids = list(self._nodes)
        idx = {v: i for i, v in enumerate(ids)}
        g = ig.Graph(n=len(ids), directed=True)
        g.vs["node_id"] = ids
        g.vs["kind"] = [self._nodes[i].kind for i in ids]
        es, preds = [], []
        for e in self._edges:
            if e.src in idx and e.dst in idx:
                es.append((idx[e.src], idx[e.dst]))
                preds.append(e.predicate)
        g.add_edges(es)
        if preds:
            g.es["predicate"] = preds
        return g

    def hub_nodes(self, top_n: int = 20) -> list[dict]:
        """Highest-degree nodes -- the density control surface.

        Hubs are down-weighted at query time rather than removed: a shared office
        address is real information, it just should not imply that everyone who
        ever billed from it is the same operation.
        """
        deg = Counter()
        for e in self._edges:
            deg[e.src] += 1
            deg[e.dst] += 1
        out = []
        for nid, d in deg.most_common(top_n):
            n = self._nodes.get(nid)
            out.append({"node_id": nid, "kind": n.kind if n else "?",
                        "name": n.name if n else nid, "degree": d})
        return out

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
        self._adj = defaultdict(list)
        for i, e in enumerate(self._edges):
            self._adj[e.src].append(i)
            self._adj[e.dst].append(i)


def get_graph_store(backend: str | None = None) -> GraphStore:
    b = (backend or CFG.GRAPH_BACKEND).lower()
    if b == "neo4j":
        raise NotImplementedError(
            "Neo4jGraphStore is the production swap; implement GraphStore's "
            "methods with claim_id as an indexed PROPERTY, not a partition.")
    return IGraphStore()
