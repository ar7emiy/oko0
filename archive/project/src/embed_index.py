"""Mention vector index -- the input to the embedding blocking lane in Layer 2.

WHAT THIS IS FOR
----------------
One vector per MENTION (not per entity: entities do not exist yet at this point,
and resolving them is what this index is for). ``src/blocking.py`` reads the
index, runs a class-filtered k-NN over it, and turns the neighbor graph into an
``emb_bucket`` column that Splink blocks on alongside its nine deterministic
rules. That is the index's only consumer.

This module previously wrote ``entities.faiss`` for a v1 resolution pass that
was deleted when v2 moved to Splink. Nobody removed the builder, so the index
was written on every run and read by nothing. It now feeds a live lane and is
named for what it actually holds.

NODE TEXT AND THE CONTEXT TRADEOFF
----------------------------------
Node text is ``normalized name | class | local context``. The context window is
the knob that matters and it cuts both ways:

  * MORE context  -> vectors encode what the mention was DOING (treated, billed,
    represented). Two different people who share a name drift apart, which helps
    precision. But two mentions of the SAME person doing different things also
    drift apart, which HURTS the blocking recall this lane exists to provide.
  * LESS context  -> nearly pure name+class similarity. Maximum recall, and the
    lane contributes more candidate pairs for Splink to reject.

Blocking is a recall net; Splink is where precision is decided. So the default
window is deliberately short. Set ``EMB_BLOCK_CONTEXT_CHARS = 0`` for pure
name+class blocking. The tradeoff is measurable -- notebook 04 sweeps it.

All vector ops go through the VectorStore interface; FAISS is never touched
here.
"""
from __future__ import annotations

from . import genai
from .repository import Repository
from .settings import CFG, Paths, genai_mode


class MentionIndexUnavailable(RuntimeError):
    """The mention vector index is missing or unreadable.

    Defined here because this module owns that index. `blocking` re-exports it,
    so `except blocking.MentionIndexUnavailable` keeps working -- they must stay
    the SAME class object, or a caller catching one would sail past the other.

    Raised rather than skipping: silently resolving without the embedding recall
    net produces a smaller entity count that looks like a clean run, and nothing
    downstream can tell the difference.
    """
from .vectorstore import FaissVectorStore, VectorStore


def build_node_text(norm_surface: str, entity_class: str, context: str) -> str:
    """Name first so it dominates the embedding; class next; context last."""
    head = f"{norm_surface} | class={entity_class}"
    ctx = " ".join(context.split())
    return f"{head} | ctx: {ctx}" if ctx else head


def build_nodes(repo: Repository, doc_ids: list[str] | None = None) -> list[dict]:
    win = CFG.EMB_BLOCK_CONTEXT_CHARS
    mentions = repo.table("mentions")
    if doc_ids is not None:
        mentions = mentions[mentions["doc_id"].isin(set(doc_ids))]
    docs = repo.table("documents").set_index("doc_id")["claim_id"].to_dict()
    texts = {f.stem: f.read_text(encoding="utf-8") for f in Paths.raw_notes.glob("*.txt")}
    nodes = []
    for _, m in mentions.iterrows():
        raw = texts.get(m["doc_id"], "")
        if win > 0:
            lo = max(0, int(m["char_start"]) - win)
            hi = min(len(raw), int(m["char_end"]) + win)
            ctx = raw[lo:hi]
        else:
            ctx = ""
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


def open_store() -> FaissVectorStore:
    """The one place the mention index paths are resolved."""
    return FaissVectorStore(CFG.EMBED_DIM, Paths.mention_index, Paths.mention_meta)


def run(repo: Repository, store: VectorStore | None = None,
        doc_ids: list[str] | None = None) -> dict:
    """Embed mentions and index them.

    With `doc_ids` this embeds only those notes' mentions and UPSERTS them into
    the existing index, which is what an arriving note needs -- the store keys on
    mention_id and replaces in place, so re-ingesting a note re-embeds only it.
    Without it, the whole corpus is embedded into a fresh index.
    """
    nodes = build_nodes(repo, doc_ids)
    if not nodes:
        return {"n_nodes": 0}
    vecs = genai.embed([n["node_text"] for n in nodes])
    store = store or open_store()
    if doc_ids is not None:
        # Load what is already indexed so the upsert adds to it rather than
        # replacing it. A missing index on the incremental path is a real error
        # -- it means the backfill never ran.
        try:
            store.load()
        except FileNotFoundError as e:
            raise MentionIndexUnavailable(
                "incremental embed asked to add to " + str(Paths.mention_index) +
                ", which does not exist. Run the backfill first."
            ) from e
    ids = [n["mention_id"] for n in nodes]
    meta = [{"entity_class": n["entity_class"], "doc_id": n["doc_id"],
             "claim_id": n["claim_id"], "norm_surface": n["norm_surface"]} for n in nodes]
    store.upsert(ids, vecs, meta)
    store.persist()
    return {"n_nodes": len(nodes), "dim": CFG.EMBED_DIM,
            "context_chars": CFG.EMB_BLOCK_CONTEXT_CHARS,
            "index": str(Paths.mention_index), "mode": genai_mode()}
