"""Notebook 04 engine: build per-mention node text, embed with Gemini
(EMBED_MODEL) and index it through the VectorStore interface (FAISS IndexFlatIP).

Node text = normalized name + class + local context window (raw chars around the
mention). A sidecar metadata dict per node (entity_class, doc_id, claim_id,
norm_surface) drives the class-filtered search used by the resolution embedding
pass. All vector ops go through VectorStore -- FAISS is never touched here.
"""
from __future__ import annotations

from . import genai
from .repository import Repository
from .settings import CFG, Paths
from .vectorstore import FaissVectorStore, VectorStore

CONTEXT_CHARS = 60


def build_node_text(norm_surface: str, entity_class: str, context: str) -> str:
    ctx = " ".join(context.split())
    return f"{norm_surface} | class={entity_class} | ctx: {ctx}"


def build_nodes(repo: Repository) -> list[dict]:
    mentions = repo.table("mentions")
    docs = repo.table("documents").set_index("doc_id")["claim_id"].to_dict()
    texts = {f.stem: f.read_text() for f in Paths.raw_notes.glob("*.txt")}
    nodes = []
    for _, m in mentions.iterrows():
        raw = texts.get(m["doc_id"], "")
        lo = max(0, int(m["char_start"]) - CONTEXT_CHARS)
        hi = min(len(raw), int(m["char_end"]) + CONTEXT_CHARS)
        ctx = raw[lo:hi]
        nodes.append({
            "mention_id": m["mention_id"],
            "node_text": build_node_text(m["norm_surface"] or m["surface"],
                                         m["entity_class"], ctx),
            "entity_class": m["entity_class"],
            "doc_id": m["doc_id"],
            "claim_id": docs.get(m["doc_id"], "UNKNOWN"),
            "norm_surface": m["norm_surface"] or "",
        })
    return nodes


def run(repo: Repository, store: VectorStore | None = None) -> dict:
    nodes = build_nodes(repo)
    if not nodes:
        return {"n_nodes": 0}
    vecs = genai.embed([n["node_text"] for n in nodes])
    store = store or FaissVectorStore(CFG.EMBED_DIM, Paths.faiss_index, Paths.faiss_meta)
    ids = [n["mention_id"] for n in nodes]
    meta = [{"entity_class": n["entity_class"], "doc_id": n["doc_id"],
             "claim_id": n["claim_id"], "norm_surface": n["norm_surface"]} for n in nodes]
    store.upsert(ids, vecs, meta)
    store.persist()
    from .settings import genai_mode
    return {"n_nodes": len(nodes), "dim": CFG.EMBED_DIM,
            "index": str(Paths.faiss_index), "mode": genai_mode()}
