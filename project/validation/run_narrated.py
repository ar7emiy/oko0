"""Manual validation run: process the fixed 60-document slice with full
narration, then dump raw, human-readable system output — one file per note.

WHAT THIS RUNS
--------------
The exact pipeline every measurement in designs/TODO.md is computed from:

    profiling -> Layer 1 extraction (pipeline_v2) -> embed -> Layer 2
    resolution (entity_resolution) -> graph assembly

over the fixed, named 60-document slice DOC00000..DOC00059. This is not a
sample of the corpus for this run -- it IS the slice every "60-doc" figure on
the board refers to, so what you see here is what those numbers were measured
against.

WHAT YOU WILL SEE
------------------
1. Live, on your console: the pipeline's own stage narration -- chunk counts,
   which extraction lane found what, identifier binding decisions, the
   resolver's calibration report (match prior, bits per evidence field, which
   comparisons Splink could not train). This is the SAME narration that ran
   during every measurement today; nothing here is dressed up for this run.
2. After it finishes: one text file per document at
   validation/system_output/<DOC_ID>.txt, listing -- in the order things
   appear in the note -- every name mention, every identifier and who it was
   bound to, every coreference link, and which resolved entity each mention
   ended up in (with cross-references to any OTHER document sharing that
   entity, so you can check the resolver's clustering decisions directly).

WHAT THIS DOES NOT INCLUDE
---------------------------
General entity-to-entity relationships (an attorney representing a claimant, a
provider treating them, a shop holding their vehicle) are NOT part of this
dump. relations.extract_relations exists and is measured on its own (T2.2),
but it is not called from this operational pipeline -- see D1 in
designs/TODO.md, still open. Run validation/run_relations_lane.py separately
for that lane; it costs real, uncached API calls, unlike this script.

USAGE
-----
    python validation/run_narrated.py            # all 60 documents
    python validation/run_narrated.py --limit 5   # first 5, for a quick look

COST. Every one of these 60 documents has been extracted and resolved many
times today under this exact prompt/model configuration, so almost every LLM
call hits the on-disk cache (store/genai_cache) and costs nothing. A --limit
run is for speed of inspection, not cost -- there is essentially no cost
difference.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import build_graph, embed_index, entity_resolution, pipeline_v2, profiling, runlog  # noqa: E402
from src.repository import Repository  # noqa: E402
from src.settings import Paths  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "system_output"


def _mention_row(m) -> str:
    return f"{m['surface']!r} [{int(m['char_start'])}:{int(m['char_end'])}]"


def dump_document(repo: Repository, doc_id: str, mentions_all, id_obs_all,
                  coref_all, mention_lookup: dict, mem_to_entity: dict,
                  entity_docs: dict, entities_by_id: dict, doc_row) -> str:
    """Build the full walkthrough text for one document, in reading order."""
    lines = []
    claim = doc_row.get("claim_id", "?")
    occ = doc_row.get("occurrence_id", "?")
    lines.append("=" * 88)
    lines.append(f"{doc_id}.txt   claim={claim}   occurrence={occ}")
    lines.append("=" * 88)

    ments = sorted((r for r in mentions_all if r["doc_id"] == doc_id),
                  key=lambda r: int(r["char_start"]))
    lines.append("")
    lines.append(f"--- NAME MENTIONS ({len(ments)}), in order of appearance ---")
    if not ments:
        lines.append("  (none)")
    for m in ments:
        eid = mem_to_entity.get(m["mention_id"])
        ename = entities_by_id.get(eid, {}).get("canonical_name") if eid else None
        other_docs = sorted(d for d in entity_docs.get(eid, set()) if d != doc_id) if eid else []
        tag = f"-> entity {eid} ({ename!r})" if eid else "-> UNRESOLVED (no entity)"
        share = f"  [also in: {', '.join(other_docs)}]" if other_docs else ""
        lines.append(f"  [{int(m['char_start']):>5}:{int(m['char_end']):<5}] "
                     f"{m['surface']!r:34s} class={m['entity_class']:16s} "
                     f"extractor={m['extractor']:20s} {tag}{share}")

    ids_ = sorted((r for r in id_obs_all if r["doc_id"] == doc_id),
                 key=lambda r: int(r["char_start"]))
    lines.append("")
    lines.append(f"--- IDENTIFIERS ({len(ids_)}), in order of appearance ---")
    if not ids_:
        lines.append("  (none)")
    for o in ids_:
        subj = o.get("subject_mention_id")
        owner = _mention_row(mention_lookup[subj]) if subj and subj in mention_lookup else "UNBOUND (orphan)"
        method = o.get("binding_method") or "-"
        lines.append(f"  [{int(o['char_start']):>5}:{int(o['char_end']):<5}] "
                     f"{o['kind']:8s} {o['value_raw']!r:28s} "
                     f"owner={owner:44s} method={method}")

    cor = sorted((r for r in coref_all if r["doc_id"] == doc_id),
                key=lambda r: int(r["anaphor_start"]))
    lines.append("")
    lines.append(f"--- COREFERENCE LINKS ({len(cor)}) ---")
    if not cor:
        lines.append("  (none)")
    for c in cor:
        ant_mid = c.get("antecedent_mention_id")
        ant = (_mention_row(mention_lookup[ant_mid]) if ant_mid and ant_mid in mention_lookup
              else (c.get("antecedent_surface") or "?"))
        lines.append(f"  [{int(c['anaphor_start']):>5}:{int(c['anaphor_end']):<5}] "
                     f"{c['anaphor_text']!r:20s} ({c['anaphor_kind']}) -> {ant}")

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60,
                    help="how many of the 60 documents to process (default: all)")
    args = ap.parse_args()

    docs = [f"DOC{i:05d}" for i in range(min(args.limit, 60))]

    repo = Repository()
    repo.reset()

    with runlog.stage("profile", "structural profiling"):
        profiling.run(repo)

    with runlog.stage("extract", f"Layer 1 over {len(docs)} documents"):
        pipeline_v2.run(repo, doc_ids=docs)

    with runlog.stage("embed", "one vector per mention"):
        embed_index.run(repo)

    with runlog.stage("resolve", "train the model, score the corpus"):
        entity_resolution.run(repo)

    with runlog.stage("graph", "assemble the entity graph"):
        build_graph.build_graph(repo)

    runlog.line("")
    runlog.line(f"writing per-document dumps to {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    mentions_all = repo.table("mentions").to_dict("records")
    id_obs_all = repo.table("identifier_observations").to_dict("records")
    coref_all = repo.table("coref_links").to_dict("records")
    members = repo.table("entity_members").to_dict("records")
    entities_all = repo.table("entities").to_dict("records")
    docs_df = repo.table("documents").set_index("doc_id")

    mention_lookup = {m["mention_id"]: m for m in mentions_all}
    mem_to_entity = {r["mention_id"]: r["entity_id"] for r in members}
    entities_by_id = {e["entity_id"]: e for e in entities_all}
    entity_docs: dict = defaultdict(set)
    for r in members:
        mid = r["mention_id"]
        if mid in mention_lookup:
            entity_docs[r["entity_id"]].add(mention_lookup[mid]["doc_id"])

    for doc_id in docs:
        doc_row = docs_df.loc[doc_id].to_dict() if doc_id in docs_df.index else {}
        text = dump_document(repo, doc_id, mentions_all, id_obs_all, coref_all,
                             mention_lookup, mem_to_entity, entity_docs,
                             entities_by_id, doc_row)
        (OUT_DIR / f"{doc_id}.txt").write_text(text, encoding="utf-8")

    runlog.line(f"done: {len(docs)} document dumps written")
    repo.close()


if __name__ == "__main__":
    main()
