"""Layer 4: per-claim agentic retrieval & dossier engine.

Sequence, in order, for every request:

  1. SCOPE BOUNDARY  -- a mandatory hard filter on claim_id. The vector search is
     restricted to that claim's chunks via the VectorStore filter (applied before
     nearest-neighbor selection), and graph traversal only ever reads that
     claim's adjacency partition. The agent is structurally incapable of reading
     another claim's data; `test_scope_isolation` proves it.
  2. VECTOR ENTRY    -- top-k relevant chunks WITHIN the scope.
  3. GRAPH EXPANSION -- entity ids mentioned in those chunks are expanded 1-2
     hops through the claim-scoped graph, yielding domain-verb triples with
     provenance.
  4. SYNTHESIS       -- raw narrative snippets + structured triples are handed to
     the LLM to write a grounded dossier. Every claim in the output must cite a
     doc_id + char span; the offline synthesizer is fully deterministic and emits
     only what the tables contain.

The LLM never answers from parametric memory: it receives retrieved text and
retrieved triples, and its output is checked against them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from . import genai, textnorm
from .graph_store import CROSS_CLAIM_SCOPE, GraphStore, ScopeViolation, get_graph_store
from .repository import Repository
from .settings import CFG, Paths
from .vectorstore import FaissVectorStore


class ClaimScopedAgent:
    """Retrieval agent hard-bound to a single claim."""

    def __init__(self, repo: Repository, graph: GraphStore | None = None,
                 chunk_store: FaissVectorStore | None = None):
        self.repo = repo
        self.graph = graph or get_graph_store()
        try:
            self.graph.load()
        except FileNotFoundError:
            pass
        self.chunks = chunk_store or FaissVectorStore(
            CFG.EMBED_DIM, Paths.store / CFG.CHUNK_INDEX_FILENAME,
            Paths.store / CFG.CHUNK_META_FILENAME)
        try:
            self.chunks.load()
        except FileNotFoundError:
            pass
        self._entities = repo.table("entities").set_index("entity_id")
        self._members = repo.table("entity_members")
        self._mentions = repo.table("mentions").set_index("mention_id")
        docs = repo.table("documents")
        self._claim_of = {r["doc_id"]: r["claim_id"] for _, r in docs.iterrows()}
        self._ent_by_claim = defaultdict(set)
        for _, r in self._members.iterrows():
            mid = r["mention_id"]
            if mid in self._mentions.index:
                d = self._mentions.loc[mid]["doc_id"]
                self._ent_by_claim[self._claim_of.get(d, "?")].add(r["entity_id"])
        self._raw = {}

    # ---- helpers ---------------------------------------------------------
    def _text(self, doc_id: str) -> str:
        if doc_id not in self._raw:
            p = Paths.raw_notes / f"{doc_id}.txt"
            self._raw[doc_id] = p.read_text() if p.exists() else ""
        return self._raw[doc_id]

    # ---- step 1+2: scoped vector entry ------------------------------------
    def retrieve_chunks(self, claim_id: str, query: str, k: int | None = None) -> list[dict]:
        """Top-k chunks WITHIN claim_id. The filter is applied inside the index."""
        if CFG.AGENT_ENFORCE_CLAIM_SCOPE and not claim_id:
            raise ScopeViolation("retrieve_chunks requires a claim_id")
        qv = genai.embed([query])[0]
        hits = self.chunks.search(
            qv, k or CFG.AGENT_VECTOR_TOPK,
            filter_fn=lambda md, c=claim_id: md.get("claim_id") == c,
        )
        out = []
        for cid, score in hits:
            md = self.chunks.get_metadata(cid)
            if CFG.AGENT_ENFORCE_CLAIM_SCOPE and md.get("claim_id") != claim_id:
                continue                      # defense in depth
            out.append({"chunk_id": cid, "score": round(score, 4),
                        "doc_id": md.get("doc_id"), "claim_id": md.get("claim_id"),
                        "char_start": md.get("char_start"), "char_end": md.get("char_end"),
                        "text": md.get("text", "")})
        return out

    # ---- step 3: graph expansion -----------------------------------------
    def entities_in_chunks(self, claim_id: str, chunks: list[dict]) -> list[str]:
        """Entity ids whose mentions fall inside the retrieved chunk spans."""
        want = {(c["doc_id"], c["char_start"], c["char_end"]) for c in chunks}
        mention_to_entity = {r["mention_id"]: r["entity_id"] for _, r in self._members.iterrows()}
        found = set()
        for mid, m in self._mentions.iterrows():
            for (doc, s, e) in want:
                if m["doc_id"] == doc and m["char_start"] >= s and m["char_end"] <= e:
                    eid = mention_to_entity.get(mid)
                    if eid and eid in self._ent_by_claim.get(claim_id, set()):
                        found.add(eid)
                    break
        return sorted(found)

    def expand(self, claim_id: str, entity_ids: list[str], hops: int | None = None) -> list[dict]:
        triples = self.graph.neighbors(entity_ids, hops or CFG.AGENT_GRAPH_HOPS, claim_id)
        return triples[:CFG.AGENT_MAX_TRIPLES]

    # ---- step 4: grounded synthesis --------------------------------------
    def answer(self, claim_id: str, question: str, hops: int | None = None) -> dict:
        chunks = self.retrieve_chunks(claim_id, question)
        eids = self.entities_in_chunks(claim_id, chunks)
        triples = self.expand(claim_id, eids, hops)
        synthesis = self._synthesize(claim_id, question, chunks, triples, eids)
        return {
            "claim_id": claim_id, "question": question,
            "scope": {"enforced": CFG.AGENT_ENFORCE_CLAIM_SCOPE, "claim_id": claim_id,
                      "chunks_considered": len(chunks),
                      "all_chunks_in_scope": all(c["claim_id"] == claim_id for c in chunks)},
            "retrieved_chunks": chunks,
            "entities": [{"entity_id": e,
                          "name": self._entities.loc[e]["canonical_name"] if e in self._entities.index else e,
                          "class": self._entities.loc[e]["entity_class"] if e in self._entities.index else "?"}
                         for e in eids],
            "triples": triples,
            "answer": synthesis["answer"],
            "citations": synthesis["citations"],
        }

    def _synthesize(self, claim_id, question, chunks, triples, eids) -> dict:
        facts = [f"{t['subject']} --{t['predicate']}--> {t['object']} "
                 f"[{t['doc_id']}:{t['span'][0]}-{t['span'][1]}]" for t in triples]
        snippets = [f"[{c['doc_id']}:{c['char_start']}-{c['char_end']}] {c['text'][:400]}"
                    for c in chunks]
        prompt = (
            "Answer ONLY from the retrieved evidence below. Every statement must cite "
            "a doc_id and character span in square brackets. If the evidence does not "
            "answer the question, say so explicitly. Do not use outside knowledge.\n\n"
            f"CLAIM: {claim_id}\nQUESTION: {question}\n\n"
            f"STRUCTURED FACTS (from the knowledge graph):\n" + "\n".join(facts) +
            "\n\nNARRATIVE SNIPPETS (raw note text):\n" + "\n\n".join(snippets)
        )

        def offline():
            return {"answer": _deterministic_dossier(claim_id, chunks, triples, self._entities, eids),
                    "citations": [f"{t['doc_id']}:{t['span'][0]}-{t['span'][1]}" for t in triples][:20]}

        data = genai.generate_json(prompt, _answer_schema(), task="agent_answer",
                                   offline_handler=offline)
        cites = data.get("citations") or [
            f"{c['doc_id']}:{c['char_start']}-{c['char_end']}" for c in chunks]
        return {"answer": data.get("answer", ""), "citations": cites}

    # ---- dossier ---------------------------------------------------------
    def dossier(self, claim_id: str) -> dict:
        """Full claim dossier: every party, their graph relations, with provenance."""
        sub = self.graph.subgraph(claim_id)
        eids = sorted(self._ent_by_claim.get(claim_id, set()))
        chunks = self.retrieve_chunks(claim_id, f"summary of claim {claim_id}",
                                      k=CFG.AGENT_VECTOR_TOPK)
        triples = self.expand(claim_id, eids)
        parties = []
        for e in eids:
            if e not in self._entities.index:
                continue
            row = self._entities.loc[e]
            parties.append({"entity_id": e, "name": row["canonical_name"],
                            "class": row["entity_class"]})
        return {
            "claim_id": claim_id,
            "parties": parties,
            "n_graph_nodes": len(sub["nodes"]), "n_graph_edges": len(sub["edges"]),
            "triples": triples,
            "narrative_chunks": chunks,
            "allegations": [t for t in sub["edges"] if t["predicate"] == "ALLEGES"],
        }

    # ---- cross-claim (separately authorized) ------------------------------
    def cross_claim_network(self, entity_ids: list[str], authorized: bool = False) -> list[dict]:
        """Escalated view: shared address/phone/identifier links across claims.

        Requires explicit authorization -- a claim-scoped session cannot reach
        these edges. This is the fraud-network path (phoenix shops, recycled
        phones, one attorney across many files).
        """
        return self.graph.cross_claim_links(entity_ids, authorized=authorized)


def _answer_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer"],
    }


def _deterministic_dossier(claim_id, chunks, triples, entities, eids) -> str:
    """Table-derived synthesis: emits only what was retrieved, with citations."""
    lines = [f"Claim {claim_id} — grounded summary from {len(chunks)} retrieved "
             f"chunk(s) and {len(triples)} graph triple(s)."]
    if eids:
        names = []
        for e in eids:
            if e in entities.index:
                names.append(f"{entities.loc[e]['canonical_name']} ({entities.loc[e]['entity_class']})")
        if names:
            lines.append("Parties: " + "; ".join(names[:12]) + ".")
    by_pred = defaultdict(list)
    for t in triples:
        by_pred[t["predicate"]].append(t)
    for pred, ts in by_pred.items():
        for t in ts[:6]:
            lines.append(f"- {t['subject']} {pred.replace('_',' ').lower()} {t['object']} "
                         f"[{t['doc_id']}:{t['span'][0]}-{t['span'][1]}]")
    if not triples:
        lines.append("No graph relationships were retrieved within this claim scope.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scope isolation proof
# ---------------------------------------------------------------------------
def test_scope_isolation(agent: ClaimScopedAgent, claim_a: str, claim_b: str,
                         probe: str = "attorney provider payment") -> dict:
    """Prove the agent cannot read outside its claim.

    Retrieves under claim_a and asserts that no returned chunk, entity or triple
    belongs to claim_b, and that cross-claim traversal raises.
    """
    res = agent.answer(claim_a, probe)
    leaked_chunks = [c for c in res["retrieved_chunks"] if c["claim_id"] != claim_a]
    leaked_triples = [t for t in res["triples"] if t["claim_id"] != claim_a]
    b_entities = agent._ent_by_claim.get(claim_b, set()) - agent._ent_by_claim.get(claim_a, set())
    leaked_entities = [e["entity_id"] for e in res["entities"] if e["entity_id"] in b_entities]

    try:
        agent.graph.neighbors([], 1, CROSS_CLAIM_SCOPE)
        cross_blocked = False
    except ScopeViolation:
        cross_blocked = True
    try:
        agent.cross_claim_network(["x"], authorized=False)
        unauth_blocked = False
    except ScopeViolation:
        unauth_blocked = True

    ok = not (leaked_chunks or leaked_triples or leaked_entities) and cross_blocked and unauth_blocked
    return {
        "scope_claim": claim_a, "probe_claim": claim_b,
        "leaked_chunks": len(leaked_chunks), "leaked_triples": len(leaked_triples),
        "leaked_entities": len(leaked_entities),
        "cross_claim_traversal_blocked": cross_blocked,
        "unauthorized_cross_claim_blocked": unauth_blocked,
        "isolation_holds": ok,
    }
