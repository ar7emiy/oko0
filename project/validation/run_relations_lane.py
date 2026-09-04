"""Run the RELATIONS lane over the 60-document slice and dump raw triples.

WHY THIS IS SEPARATE FROM run_narrated.py
------------------------------------------
relations.extract_relations produces span-grounded subject -> predicate ->
object triples ("Marge Wilson represents Robert Miller"). It is NOT called
from the operational pipeline (pipeline_v2.py never touches object_mention_id
at all) -- see D1 in designs/TODO.md, still open. It is exercised today only
as a standalone research lane, from notebooks/20_relation_extraction.py.

So if you want to validate relationships, this is the lane you are actually
testing -- an unfinished capability that has not been wired into the entity
graph, not something the "system run" in run_narrated.py will show you.

RUN run_narrated.py FIRST. This script reads the mentions table it populates
to build a per-claim roster of known party names (see extract_relations'
`known_parties` argument) -- without it, any sentence that refers to someone
by role only ("the claimant", "counsel") produces an unresolvable relation.

COST. Unlike run_narrated.py, this calls the API fresh for every chunk --
notebook 20 is the only thing that has ever exercised this lane, and it was
not run today. Expect ~3 calls per document, all on gemini-3.7-flash (not the
cheaper routed model). Use --limit for a cheap first look before running all 60.

USAGE
-----
    python validation/run_relations_lane.py --limit 5
    python validation/run_relations_lane.py            # all 60
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import chunking, relations, runlog  # noqa: E402
from src.repository import Repository  # noqa: E402
from src.settings import Paths  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "system_output"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    docs = [f"DOC{i:05d}" for i in range(min(args.limit, 60))]

    repo = Repository()
    ments = repo.table("mentions")
    if ments.empty:
        raise SystemExit(
            "no mentions in the store -- run validation/run_narrated.py first "
            "so this script has a party roster to resolve role references against."
        )
    docs_df = repo.table("documents").set_index("doc_id")

    # known_parties per CLAIM (not per doc): a party is often named only in the
    # first note of a claim, and every later note refers to them by role.
    names_by_claim: dict = defaultdict(set)
    for _, m in ments.iterrows():
        claim = docs_df.loc[m["doc_id"], "claim_id"] if m["doc_id"] in docs_df.index else None
        if claim:
            names_by_claim[claim].add(m["surface"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with runlog.stage("relations", f"{len(docs)} documents, one API call per chunk"):
        for i, doc_id in enumerate(docs):
            runlog.every(10, i, len(docs), doc_id)
            text = (Paths.raw_notes / f"{doc_id}.txt").read_text(encoding="utf-8")
            claim = docs_df.loc[doc_id, "claim_id"] if doc_id in docs_df.index else "UNKNOWN"
            roster = sorted(names_by_claim.get(claim, set()))
            chunks = chunking.chunk_document(doc_id, claim, text)

            lines = [f"{doc_id}.txt  claim={claim}   "
                     f"(relations lane -- NOT wired into the operational graph, D1)",
                     "=" * 88, ""]
            n = 0
            for ch in chunks:
                rels = relations.extract_relations(ch.text, ch.char_start,
                                                    known_parties=roster)
                for r in rels:
                    n += 1
                    lines.append(
                        f"  {r.subject_text!r} --[{r.predicate}]--> {r.object_text!r}"
                        f"   ({r.polarity})")
                    lines.append(f"      evidence [{r.evidence_start}:{r.evidence_end}]: "
                                 f"{r.evidence_text!r}")
            if n == 0:
                lines.append("  (no relations extracted)")
            (OUT_DIR / f"{doc_id}_relations.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")

    runlog.line(f"done: {len(docs)} relation dumps written to {OUT_DIR}")
    repo.close()


if __name__ == "__main__":
    main()
