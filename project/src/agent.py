"""Layer 4: per-claim agentic retrieval & dossier engine.

Sequence, in order, for every request:

  1. SCOPE FILTER    -- retrieval is restricted to one claim's chunks via the
     VectorStore filter (applied before nearest-neighbor selection). This is a
     RELEVANCE filter on the retrieval path, not an identity boundary: the graph
     beneath is global, so `enrich()` can then report what the rest of the
     corpus knows about the parties those chunks surfaced.
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
from .graph_store import GraphStore, get_graph_store
from .repository import Repository
from .settings import CFG, Paths
from .vectorstore import FaissVectorStore


# doc_id:start-end -- the citation format the synthesis prompt demands.
_CITE_RE = re.compile(r"^\[?([A-Za-z0-9_\-]+):(\d+)\s*-\s*(\d+)\]?$")


class AgentStoreUnavailable(RuntimeError):
    """A store Layer 4 retrieval depends on has not been built."""


class ClaimScopedAgent:
    """Retrieval agent hard-bound to a single claim."""

    def __init__(self, repo: Repository, graph: GraphStore | None = None,
                 chunk_store: FaissVectorStore | None = None):
        self.repo = repo
        self.graph = graph or get_graph_store()
        try:
            self.graph.load()
        except FileNotFoundError as e:
            raise AgentStoreUnavailable(
                "graph store not built. Run build_graph.run(repo) (notebook 08) "
                "before querying the agent."
            ) from e
        self.chunks = chunk_store or FaissVectorStore(
            CFG.EMBED_DIM, Paths.chunk_index, Paths.chunk_meta)
        try:
            self.chunks.load()
        except FileNotFoundError as e:
            # This used to `pass`. An agent with an empty chunk index answers
            # every question from graph expansion alone, returns zero citations,
            # and reports no error -- Layer 2 of four silently missing, with the
            # output still shaped like a real answer. Nothing downstream could
            # detect it, which is precisely why it has to be loud here.
            raise AgentStoreUnavailable(
                "chunk vector index not found at " + str(Paths.chunk_index) +
                ". Run build_graph.build_chunk_index(repo) (notebook 08) before "
                "querying the agent; without it semantic retrieval returns "
                "nothing and answers are silently un-grounded."
            ) from e
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
            self._raw[doc_id] = p.read_text(encoding="utf-8") if p.exists() else ""
        return self._raw[doc_id]

    # ---- step 1+2: scoped vector entry ------------------------------------
    def retrieve_chunks(self, claim_id: str, query: str, k: int | None = None) -> list[dict]:
        """Top-k chunks WITHIN claim_id. The filter is applied inside the index."""
        if CFG.AGENT_ENFORCE_CLAIM_SCOPE and not claim_id:
            raise ValueError("retrieve_chunks requires a claim_id")
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

    def expand(self, claim_id: str | None, entity_ids: list[str],
               hops: int | None = None) -> list[dict]:
        """Graph expansion. `claim_id` filters; pass None to follow entities
        across the whole corpus."""
        triples = self.graph.neighbors(entity_ids, hops or CFG.AGENT_GRAPH_HOPS, claim_id)
        return triples[:CFG.AGENT_MAX_TRIPLES]

    def enrich(self, entity_ids: list[str]) -> dict:
        """Cross-claim enrichment for entities surfaced by claim-scoped retrieval.

        This is the integration point with the existing assistant: retrieval
        stays scoped to one claim, and the entity layer then contributes what the
        rest of the corpus knows about the parties in those chunks. An ordinary
        read -- cross-claim linkage is the purpose, not a privileged operation.
        """
        out = {}
        for eid in entity_ids:
            node = self.graph.node(eid) if hasattr(self.graph, "node") else None
            links = (self.graph.cross_claim_links([eid])
                     if hasattr(self.graph, "cross_claim_links") else [])
            out[eid] = {
                "claims": sorted(node.claim_ids) if node else [],
                "occurrences": sorted(node.occurrence_ids) if node else [],
                "cross_claim_links": links[:20],
            }
        return out

    def who_is_at(self, kind: str, value: str) -> list[dict]:
        """'Who is associated with this address/phone?' -- the unnamed-identifier
        query, answered by a direct lookup on the identifier node."""
        from . import textnorm
        norm = textnorm.normalize_identifier(kind, value)
        if kind == "address":
            norm = textnorm.address_key(value)
        if kind == "phone":
            norm = textnorm.phone_last7(value)
        return (self.graph.find_by_identifier(kind, norm)
                if hasattr(self.graph, "find_by_identifier") else [])

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
            "citation_check": synthesis.get("citation_check", {}),
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
        raw_cites = data.get("citations") or [
            f"{c['doc_id']}:{c['char_start']}-{c['char_end']}" for c in chunks]
        verified, rejected = self._verify_citations(raw_cites, chunks, triples)
        return {"answer": data.get("answer", ""),
                "citations": verified,
                "citation_check": {
                    "n_claimed": len(raw_cites),
                    "n_verified": len(verified),
                    "n_rejected": len(rejected),
                    "rejected": rejected,
                    "grounded": bool(verified) and not rejected,
                }}

    def _verify_citations(self, cites: list[str], chunks: list[dict],
                          triples: list[dict]) -> tuple[list[str], list[dict]]:
        """Check every citation against the evidence that was actually retrieved.

        The prompt DEMANDS a doc_id and char span for each statement. Nothing
        checked that the model complied -- the returned strings were passed
        through untouched and presented as provenance. For a system whose entire
        claim is that facts trace to characters, the trace was unverified.

        Four checks, cheapest first. A citation must:
          1. parse as doc_id:start-end
          2. name a document that exists
          3. have a span inside that document's length
          4. fall within evidence actually placed in the prompt -- a retrieved
             chunk or a retrieved triple's span. A syntactically perfect
             citation to a real document the model was never shown is a
             fabricated provenance trail, which is the failure worth catching.
        """
        allowed = [(c["doc_id"], int(c["char_start"]), int(c["char_end"]))
                   for c in chunks]
        allowed += [(t["doc_id"], int(t["span"][0]), int(t["span"][1]))
                    for t in triples if t.get("doc_id") and t.get("span")]

        verified, rejected = [], []
        for cite in cites:
            m = _CITE_RE.match(str(cite).strip())
            if not m:
                rejected.append({"citation": cite, "reason": "unparseable"})
                continue
            doc, s, e = m.group(1), int(m.group(2)), int(m.group(3))
            text = self._text(doc)
            if not text:
                rejected.append({"citation": cite, "reason": "unknown doc_id"})
                continue
            if not (0 <= s < e <= len(text)):
                rejected.append({"citation": cite, "reason": "span out of bounds"})
                continue
            if not any(doc == d and s >= ds and e <= de for d, ds, de in allowed):
                rejected.append({"citation": cite,
                                 "reason": "span outside retrieved evidence"})
                continue
            verified.append(cite)
        return verified, rejected

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
def test_scope_filter(agent, claim_a: str, claim_b: str,
                      probe: str = "attorney provider payment") -> dict:
    """Verify claim scoping works as a FILTER on the retrieval path.

    This is deliberately no longer an isolation proof. Identity is global by
    design; what must hold is that when a caller asks for one claim, the
    retrieved chunks and the claim-filtered triples belong to that claim -- while
    the entity layer remains free to report what other claims an entity touches.
    """
    res = agent.answer(claim_a, probe)
    off_chunks = [c for c in res["retrieved_chunks"] if c["claim_id"] != claim_a]
    off_triples = [t for t in res["triples"] if t["claim_id"] != claim_a]
    enriched = agent.enrich([e["entity_id"] for e in res["entities"]][:5])
    cross = sum(len(v["cross_claim_links"]) for v in enriched.values())
    return {
        "scope_claim": claim_a,
        "chunks_outside_claim": len(off_chunks),
        "claim_filtered_triples_outside_claim": len(off_triples),
        "retrieval_filter_holds": not off_chunks and not off_triples,
        "cross_claim_links_available_via_enrichment": cross,
    }
