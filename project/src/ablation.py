"""Recall ablation: does the hybrid union + sweep actually approach zero misses?

This is the instrument that tests the architecture's central claim. It reads the
sealed ground-truth manifest (so it lives on the AUDIT side of the leakage guard,
alongside audit.py -- never imported by the extraction path) and measures
span-level recall for each cumulative configuration:

    A. llm_only            -- single semantic pass (the baseline being argued against)
    B. + token_ner         -- union with the token-level span scanner
    C. + gazetteer         -- union with deterministic regex/checksum patterns
    D. + sweep             -- pass-2 differential audit over unmapped tokens

It reports recall, the marginal lift of each stage, precision (so a recall gain
bought purely with noise is visible), and which extractor uniquely rescued each
recovered mention. Misses that survive the full stack are itemized.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from . import chunking, ner_ensemble, sweep
from .ner_ensemble import SpanCandidate
from .settings import Paths

STAGES = ("llm_only", "plus_token_ner", "plus_gazetteer", "plus_sweep")

STAGE_FLAGS = {
    "llm_only":       dict(use_llm=True, use_token_ner=False, use_gazetteer=False, use_sweep=False),
    "plus_token_ner": dict(use_llm=True, use_token_ner=True,  use_gazetteer=False, use_sweep=False),
    "plus_gazetteer": dict(use_llm=True, use_token_ner=True,  use_gazetteer=True,  use_sweep=False),
    "plus_sweep":     dict(use_llm=True, use_token_ner=True,  use_gazetteer=True,  use_sweep=True),
}


def load_manifest() -> dict:
    return json.loads(Paths.manifest_json.read_text(encoding="utf-8"))


def _overlaps(s1, e1, s2, e2) -> bool:
    return s1 < e2 and s2 < e1


def extract_stage(chunks, token_ner, flags) -> dict[str, list[SpanCandidate]]:
    """Run one ablation configuration over all chunks -> {doc_id: [spans]}."""
    by_doc: dict[str, list[SpanCandidate]] = defaultdict(list)
    for ch in chunks:
        spans = ner_ensemble.extract_chunk(
            ch, token_ner,
            use_llm=flags["use_llm"],
            use_gazetteer=flags["use_gazetteer"],
            use_token_ner=flags["use_token_ner"],
        )
        if flags["use_sweep"]:
            spans = spans + sweep.sweep_chunk(ch, spans)
        by_doc[ch.doc_id].extend(spans)
    # merge across overlapping chunks within each doc
    return {d: ner_ensemble.union_spans([s]) for d, s in by_doc.items()}


def score_against_gt(by_doc: dict[str, list[SpanCandidate]], manifest: dict) -> dict:
    """Span-level recall/precision of entity-name placements vs ground truth."""
    placements = manifest["placements"]
    ent_tags = {e["gt_entity_id"]: e["hard_case_tags"] for e in manifest["entities"]}

    spans_by_doc = {d: sorted(v, key=lambda c: c.start) for d, v in by_doc.items()}

    found = 0
    missed = []
    rescued_by = Counter()      # which extractor provenance covered this placement
    by_segment = defaultdict(lambda: [0, 0])
    by_hardcase = defaultdict(lambda: [0, 0])

    for pl in placements:
        cands = spans_by_doc.get(pl["doc_id"], [])
        hit = None
        for c in cands:
            if _overlaps(c.start, c.end, pl["char_start"], pl["char_end"]):
                hit = c
                break
        seg = pl["segment_kind"]
        by_segment[seg][1] += 1
        tags = ent_tags.get(pl["gt_entity_id"], []) or ["(none)"]
        for t in tags:
            by_hardcase[t][1] += 1
        if hit is not None:
            found += 1
            by_segment[seg][0] += 1
            for t in tags:
                by_hardcase[t][0] += 1
            rescued_by[tuple(sorted(hit.extractors))] += 1
        else:
            missed.append({
                "doc_id": pl["doc_id"], "span": [pl["char_start"], pl["char_end"]],
                "surface": pl["surface_variant"], "variant_kind": pl.get("variant_kind"),
                "segment_kind": seg, "hard_cases": ent_tags.get(pl["gt_entity_id"], []),
            })

    # precision: how many emitted NAME-ish spans hit a real placement
    gt_by_doc = defaultdict(list)
    for pl in placements:
        gt_by_doc[pl["doc_id"]].append((pl["char_start"], pl["char_end"]))
    non_ent_by_doc = defaultdict(list)
    for ne in manifest["non_entities"]:
        non_ent_by_doc[ne["doc_id"]].append((ne["char_start"], ne["char_end"]))

    NAME_LABELS = {"person", "organization", "medical_provider", "attorney",
                   "claimant", "adjuster", "repair_shop", "law_firm"}
    tp = fp = fp_nonentity = 0
    for d, cands in spans_by_doc.items():
        for c in cands:
            if c.label not in NAME_LABELS:
                continue                      # identifiers scored separately
            if any(_overlaps(c.start, c.end, a, b) for (a, b) in gt_by_doc.get(d, [])):
                tp += 1
            else:
                fp += 1
                if any(_overlaps(c.start, c.end, a, b) for (a, b) in non_ent_by_doc.get(d, [])):
                    fp_nonentity += 1

    total = len(placements)
    return {
        "total_placements": total,
        "found": found,
        "recall": round(found / total, 4) if total else 0.0,
        "n_missed": len(missed),
        "name_span_precision": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "n_name_spans": tp + fp,
        "fp_nonentity_planted": fp_nonentity,
        "by_segment_kind": {k: {"found": v[0], "total": v[1],
                                "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                            for k, v in sorted(by_segment.items())},
        "by_hard_case": {k: {"found": v[0], "total": v[1],
                             "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                         for k, v in sorted(by_hardcase.items())},
        "provenance_of_found": {"+".join(k): v for k, v in rescued_by.most_common()},
        "missed_sample": missed[:25],
        "_missed_keys": {(m["doc_id"], tuple(m["span"])) for m in missed},
    }


def identifier_recall(by_doc: dict[str, list[SpanCandidate]], manifest: dict,
                      docs: dict[str, tuple[str, str]]) -> dict:
    """Recall over STRUCTURED identifier values, which is what gazetteers are for.

    Ground-truth placements only mark entity NAME mentions, so scoring the
    gazetteer layer on them understates it. Here we take every identifier value
    the manifest assigns to an entity (email/npi/tin/ssn/dob/phone/address),
    locate its literal occurrences in the raw text, and ask whether the stage's
    spans cover them.
    """
    values = []
    for e in manifest["entities"]:
        for k, v in (e.get("canonical") or {}).items():
            if k in ("email", "npi", "tin", "ssn", "dob") and v:
                values.append((k, str(v)))
        for aw in e.get("attribute_windows", []):
            if aw.get("value"):
                values.append((aw["attribute"].replace("has_", ""), str(aw["value"])))
    values = list({(k, v) for k, v in values})

    occurrences = []           # (doc_id, start, end, kind)
    for doc_id, (_claim, text) in docs.items():
        for kind, val in values:
            start = 0
            while True:
                i = text.find(val, start)
                if i < 0:
                    break
                occurrences.append((doc_id, i, i + len(val), kind))
                start = i + 1

    covered = 0
    by_kind = defaultdict(lambda: [0, 0])
    for (doc_id, s, e, kind) in occurrences:
        by_kind[kind][1] += 1
        hit = any(_overlaps(c.start, c.end, s, e) for c in by_doc.get(doc_id, []))
        if hit:
            covered += 1
            by_kind[kind][0] += 1
    n = len(occurrences)
    return {
        "n_identifier_occurrences": n,
        "identifier_recall": round(covered / n, 4) if n else 0.0,
        "by_kind": {k: {"found": v[0], "total": v[1],
                        "recall": round(v[0] / v[1], 3) if v[1] else 0.0}
                    for k, v in sorted(by_kind.items())},
    }


def run(limit_docs: int | None = None, stages: tuple = STAGES) -> dict:
    """Execute the ablation. `limit_docs` samples for a fast pass."""
    manifest = load_manifest()
    claim_of = {d["doc_id"]: d["claim_id"] for d in manifest["documents"]}
    files = sorted(Paths.raw_notes.glob("*.txt"))
    if limit_docs:
        files = files[:limit_docs]
    docs = {f.stem: (claim_of.get(f.stem, "UNKNOWN"), f.read_text(encoding="utf-8")) for f in files}

    keep = set(docs)
    manifest = dict(manifest)
    manifest["placements"] = [p for p in manifest["placements"] if p["doc_id"] in keep]
    manifest["non_entities"] = [n for n in manifest["non_entities"] if n["doc_id"] in keep]

    chunks = chunking.chunk_corpus(docs)
    token_ner = ner_ensemble.get_token_ner()

    results = {}
    prev_missed = None
    prev_recall = None
    for stage in stages:
        by_doc = extract_stage(chunks, token_ner, STAGE_FLAGS[stage])
        sc = score_against_gt(by_doc, manifest)
        sc["identifiers"] = identifier_recall(by_doc, manifest, docs)
        missed_keys = sc.pop("_missed_keys")
        if prev_missed is not None:
            sc["newly_rescued_vs_prev"] = len(prev_missed - missed_keys)
            sc["newly_lost_vs_prev"] = len(missed_keys - prev_missed)
            sc["recall_lift"] = round(sc["recall"] - prev_recall, 4)
        prev_missed = missed_keys
        prev_recall = sc["recall"]
        results[stage] = sc

    chunk_stats = {
        "n_docs": len(docs), "n_chunks": len(chunks),
        "chunks_per_doc": round(len(chunks) / max(1, len(docs)), 3),
        "docs_multi_chunk": sum(1 for d in docs
                                if sum(1 for c in chunks if c.doc_id == d) > 1),
        "token_ner_backend": token_ner.name,
    }
    return {"chunking": chunk_stats, "stages": results,
            "summary": _summarize(results, chunk_stats)}


def _summarize(results: dict, chunk_stats: dict) -> str:
    parts = []
    for stage, sc in results.items():
        lift = sc.get("recall_lift")
        lift_s = f" (+{lift:.3f})" if lift is not None else ""
        parts.append(f"{stage}: R={sc['recall']:.3f}{lift_s} P={sc['name_span_precision']:.3f}")
    return (f"[token_ner={chunk_stats['token_ner_backend']}, "
            f"{chunk_stats['n_chunks']} chunks/{chunk_stats['n_docs']} docs]  " + "  |  ".join(parts))
