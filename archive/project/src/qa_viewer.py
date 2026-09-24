"""Interactive QA tool: ground truth vs. extraction overlay, entity-resolution
match lineage, and a ground-truth correction queue.

This is the real implementation of the workflow sketched in
designs/qa-viewer-mockup.html, wired to the actual repository, manifest, and
Splink output instead of canned sample data. Three Gradio tabs:

  1. Document overlay -- one note's text with TP/FN/FP spans highlighted,
     seeded from the documents audit.py already flags as having misses or
     false positives.
  2. Resolution drill-down -- pick a ground-truth entity, see which of its
     mentions entity resolution actually links at a chosen threshold (real
     connected components over the real same_as_edges, recomputed live), and
     a field-by-field match-lineage table for any specific pair, computed on
     demand via Splink's compare_two_records() against the trained model
     entity_resolution.run() saves to store/splink_model.json (see
     load_lineage_linker / comparison_level_labels). Coreference-derived
     mentions ("he", "the claimant") are shown separately: they never reach
     the `mentions` table (see pipeline_v2.py), so entity resolution never
     sees them at any threshold -- that is a structural fact, not a display
     choice.
  3. Correct ground truth -- a field guide (the real vocabulary from
     corpus_gen.py) plus a boundary reference (every word's real character
     offsets) for queuing a correction. Corrections are appended to
     data/gt_corrections.json, a patch file audit.py applies on top of the
     sealed manifest at read time -- the manifest itself is never touched, so
     corpus_gen.py + seed still regenerates the identical base file.

This module reads the ground-truth manifest, so -- like audit.py and
ablation.py -- it is in the leakage guard's GT_ALLOWED_FILES rather than
PIPELINE_MODULES: it is an audit-side tool, not part of the extraction
pipeline the guard polices.
"""
from __future__ import annotations

import datetime
import json
import math
import re
import uuid
from collections import Counter, defaultdict

from . import audit
from . import entity_resolution as er
from .repository import Repository
from .settings import Paths

CORRECTIONS_PATH = Paths.data / "gt_corrections.json"

HARD_CASE_TAGS = [
    "jr_sr", "phoenix_shop", "shared_address", "recycled_phone",
    "address_change", "identifier_reassigned", "high_fanout", "cross_occurrence",
]

FIELD_GUIDE_MD = """
### Span kind
- **entity** -- a person or organization mention
- **identifier** -- address / phone / email / NPI / TIN / SSN / VIN
- **event** -- a dated action (filed, scheduled, paid...)
- **non_entity** -- a planted look-alike that should stay untagged; it tests
  precision, not recall

### entity_class
**person** or **organization** -- nothing else. Role (attorney, claimant,
medical_provider, repair_shop, adjuster) is a separate field -- don't conflate
them.

### gt_entity_id
Reuse the existing ID if this mention belongs to an entity already in the
manifest -- search the dropdown below by name first. Only mint a new
`gt_eNNNNN` if it's genuinely new, and double-check: ground truth is meant to
be generator-derived, not hand-authored piecemeal.

### hard_case_tags (attach any that apply)
- **jr_sr** -- Jr/Sr suffix conflict at the same address
- **phoenix_shop** -- repair shop reopened under a new name at an old address
- **shared_address** -- two distinct entities share one address
- **recycled_phone** -- a phone number reassigned to a different entity later
- **address_change** -- this entity's address changed over time
- **identifier_reassigned** -- an identifier moved from one entity to another
- **high_fanout** -- entity recurs across an unusually large number of claims
- **cross_occurrence** -- entity appears across more than one occurrence

### orphan (identifiers only)
Check this when no name is co-located with the identifier mention -- it's the
case identifier-first resolution exists to handle.
"""

_COMPARISON_DISPLAY = {
    "first_name_last_name": "name (first + last)",
    "name_sorted": "name_sorted (token-sorted Jaro-Winkler)",
    "email": "email",
    "phone7": "phone (last 7 digits)",
    "npi": "npi",
    "address_key": "address_key",
    "dob": "dob",
}


def _overlap(s1, e1, s2, e2) -> bool:
    return s1 < e2 and s2 < e1


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Screen 1: document overlay
# ---------------------------------------------------------------------------
def interesting_docs(repo: Repository, manifest: dict, limit: int = 40) -> list[dict]:
    """Docs with at least one miss or false positive, worst first.

    Seeded from the same samples audit.py already computes -- this tool does
    not recompute recall/precision differently, it just makes the existing
    numbers browsable.
    """
    ent_r = audit.entity_recall(repo, manifest)
    ent_p = audit.entity_precision(repo, manifest)
    ident = audit.identifier_recall(repo, manifest)

    counts = defaultdict(lambda: {"fn": 0, "fp": 0, "fn_ident": 0})
    for m in ent_r["missed_sample"]:
        counts[m["doc_id"]]["fn"] += 1
    for f in ent_p["fp_sample"]:
        counts[f["doc_id"]]["fp"] += 1
    for m in ident["missed_sample"]:
        counts[m["doc_id"]]["fn_ident"] += 1

    out = []
    for doc_id, c in counts.items():
        total = c["fn"] + c["fp"] + c["fn_ident"]
        out.append({"doc_id": doc_id, "n_issues": total, **c})
    out.sort(key=lambda d: -d["n_issues"])
    return out[:limit]


def doc_overlay(repo: Repository, manifest: dict, doc_id: str) -> dict:
    """TP/FN/FP spans for one document, entities + identifiers + coref."""
    text = (Paths.raw_notes / f"{doc_id}.txt").read_text(encoding="utf-8")

    ent_tags = {e["gt_entity_id"]: e["hard_case_tags"] for e in manifest["entities"]}
    gt_ent = [p for p in manifest["placements"] if p["kind"] == "entity" and p["doc_id"] == doc_id]
    gt_ident = [p for p in manifest["placements"] if p["kind"] == "identifier" and p["doc_id"] == doc_id]
    gt_event = [p for p in manifest["placements"] if p["kind"] == "event" and p["doc_id"] == doc_id]
    gt_coref = [c for c in manifest["coref_chains"] if c["doc_id"] == doc_id]

    mentions = repo.table("mentions")
    mentions = mentions[mentions["doc_id"] == doc_id]
    try:
        idobs = repo.table("identifier_observations")
        idobs = idobs[idobs["doc_id"] == doc_id]
    except Exception:
        idobs = None
    try:
        clinks = repo.table("coref_links")
        clinks = clinks[clinks["doc_id"] == doc_id]
    except Exception:
        clinks = None

    spans = []  # {start, end, status, kind, surface, detail}
    matched_mention_ids = set()

    for pl in gt_ent:
        hit_id = None
        for _, m in mentions.iterrows():
            if _overlap(int(m["char_start"]), int(m["char_end"]), pl["char_start"], pl["char_end"]):
                hit_id = m["mention_id"]
                break
        status = "tp" if hit_id else "fn"
        if hit_id:
            matched_mention_ids.add(hit_id)
        spans.append({
            "start": pl["char_start"], "end": pl["char_end"], "status": status,
            "kind": "entity", "surface": pl["surface"],
            "detail": f"entity · {pl['segment_kind']} · variant:{pl.get('variant_kind', '?')}"
                      + (f" · {', '.join(ent_tags.get(pl['gt_id'], []))}" if ent_tags.get(pl["gt_id"]) else ""),
            "gt_id": pl["gt_id"],
        })

    for _, m in mentions.iterrows():
        if m["mention_id"] in matched_mention_ids:
            continue
        hit_ne = any(_overlap(int(m["char_start"]), int(m["char_end"]), ne["char_start"], ne["char_end"])
                     for ne in manifest["non_entities"] if ne["doc_id"] == doc_id)
        spans.append({
            "start": int(m["char_start"]), "end": int(m["char_end"]), "status": "fp",
            "kind": "entity", "surface": m["surface"],
            "detail": f"entity · {m['entity_class']} · extractor:{m['extractor']}"
                      + (" · hits a planted non-entity" if hit_ne else ""),
            "gt_id": None,
        })

    for pl in gt_ident:
        hit = False
        if idobs is not None:
            hit = any(_overlap(int(o["char_start"]), int(o["char_end"]), pl["char_start"], pl["char_end"])
                      for _, o in idobs.iterrows())
        spans.append({
            "start": pl["char_start"], "end": pl["char_end"], "status": "tp" if hit else "fn",
            "kind": "identifier", "surface": pl["surface"],
            "detail": f"identifier · {pl.get('identifier_kind', '?')}"
                      + (" · orphan (no name co-located)" if pl.get("orphan") else " · named"),
            "gt_id": None,
        })

    if idobs is not None:
        gt_ident_spans = [(p["char_start"], p["char_end"]) for p in gt_ident]
        for _, o in idobs.iterrows():
            if any(_overlap(int(o["char_start"]), int(o["char_end"]), s, e) for s, e in gt_ident_spans):
                continue
            spans.append({
                "start": int(o["char_start"]), "end": int(o["char_end"]), "status": "fp",
                "kind": "identifier", "surface": o["value_raw"],
                "detail": f"identifier · {o['kind']} · not in ground truth",
                "gt_id": None,
            })

    for pl in gt_event:
        hit = any(_overlap(int(m["char_start"]), int(m["char_end"]), pl["char_start"], pl["char_end"])
                   for _, m in mentions.iterrows())
        spans.append({
            "start": pl["char_start"], "end": pl["char_end"], "status": "tp" if hit else "fn",
            "kind": "event", "surface": pl["surface"],
            "detail": f"event · {pl.get('event_type', '?')} · event extraction not implemented",
            "gt_id": None,
        })

    for c in gt_coref:
        hit = False
        if clinks is not None and not clinks.empty:
            for _, l in clinks.iterrows():
                if (_overlap(int(l["anaphor_start"]), int(l["anaphor_end"]), c["anaphor_start"], c["anaphor_end"])
                        and l["antecedent_mention_id"] in matched_mention_ids):
                    hit = True
                    break
        spans.append({
            "start": c["anaphor_start"], "end": c["anaphor_end"], "status": "tp" if hit else "fn",
            "kind": "coref", "surface": c["anaphor_text"],
            "detail": f"coref · hop {c['hops']} · {c['anaphor_kind']} -> {c['referent_gt_entity_id']}",
            "gt_id": c["referent_gt_entity_id"],
        })

    spans.sort(key=lambda s: s["start"])
    return {"doc_id": doc_id, "text": text, "spans": spans}


_STATUS_COLOR = {"tp": "#DFEDE5", "fn": "#F6E0DB", "fp": "#F5EDCF"}
_STATUS_BORDER = {"tp": "#2F6B4F", "fn": "#A33A2A", "fp": "#9C7B12"}
_STATUS_LABEL = {"tp": "TP", "fn": "FN (miss)", "fp": "FP"}


def render_doc_overlay_html(data: dict) -> str:
    text, spans = data["text"], data["spans"]
    # non-overlapping only for display; identical/overlapping spans (e.g. an
    # entity placement and a coref anaphor that happen to coincide) keep both
    # rows in the sidebar table but only the first drawn on the text itself.
    drawn = sorted(spans, key=lambda s: s["start"])
    out, pos = [], 0
    for s in drawn:
        if s["start"] < pos:
            continue
        out.append(_esc(text[pos:s["start"]]))
        color, border = _STATUS_COLOR[s["status"]], _STATUS_BORDER[s["status"]]
        out.append(f'<mark style="background:{color};box-shadow:inset 0 -2px 0 {border};'
                   f'border-radius:2px;padding:1px 2px" title="{_esc(s["detail"])}">'
                   f'{_esc(text[s["start"]:s["end"]])}</mark>')
        pos = s["end"]
    out.append(_esc(text[pos:]))
    body = "".join(out)
    legend = "".join(
        f'<span style="margin-right:16px;font-family:ui-monospace,monospace;font-size:11px">'
        f'<span style="display:inline-block;width:10px;height:10px;background:{_STATUS_COLOR[k]};'
        f'box-shadow:inset 0 -2px 0 {_STATUS_BORDER[k]};border-radius:2px;margin-right:5px"></span>{v}</span>'
        for k, v in _STATUS_LABEL.items()
    )
    return (f'<div style="font-family:ui-monospace,monospace;font-size:11px;color:#666;'
            f'margin-bottom:10px">{legend}</div>'
            f'<div style="font-family:ui-monospace,monospace;font-size:13.5px;line-height:1.9;'
            f'white-space:pre-wrap;padding:14px;border:1px solid #ddd;border-radius:4px">{body}</div>')


def doc_overlay_table(data: dict) -> list[list]:
    return [[s["kind"], _STATUS_LABEL[s["status"]], s["surface"], s["detail"], f'[{s["start"]}, {s["end"]})']
            for s in sorted(data["spans"], key=lambda s: s["start"])]


# ---------------------------------------------------------------------------
# Screen 2: resolution drill-down
# ---------------------------------------------------------------------------
def gt_entities_for_drilldown(repo: Repository, manifest: dict, limit: int = 80) -> list[tuple[str, str]]:
    """[(gt_entity_id, label)], most-mentioned entities first."""
    counts = Counter(p["gt_id"] for p in manifest["placements"] if p["kind"] == "entity")
    names = {e["gt_entity_id"]: e.get("canonical", {}).get("name", e["gt_entity_id"])
              for e in manifest["entities"]}
    out = [(gid, f"{gid} -- {names.get(gid, '?')} ({n} mentions)")
           for gid, n in counts.most_common(limit) if n >= 2]
    return out


def entity_ground_truth_items(manifest: dict, gt_entity_id: str) -> dict:
    """Every ground-truth item for one entity: name-bearing placements (which
    entity resolution can act on) and coreference-only anaphora (which it
    structurally cannot -- anaphora never become `mentions` rows; see
    pipeline_v2.py)."""
    named = [p for p in manifest["placements"]
             if p["kind"] == "entity" and p["gt_id"] == gt_entity_id]
    named.sort(key=lambda p: (p["doc_id"], p["char_start"]))
    coref = [c for c in manifest["coref_chains"] if c["referent_gt_entity_id"] == gt_entity_id]
    coref.sort(key=lambda c: (c["doc_id"], c["anaphor_start"]))
    return {"named": named, "coref": coref}


def _find_mention_id(repo: Repository, doc_id: str, start: int, end: int) -> str | None:
    row = repo.df(
        "SELECT mention_id FROM mentions WHERE doc_id=? AND char_start<? AND char_end>? LIMIT 1",
        (doc_id, end, start),
    )
    return row.iloc[0]["mention_id"] if not row.empty else None


def load_live_edges(repo: Repository):
    """Full scored-and-not-suppressed edge set, in the shape cluster_at() and
    audit.bcubed_sweep() expect. Load once per session -- recomputing
    connected components at a new threshold is cheap; re-reading the table
    from disk on every slider tick is not."""
    edges = repo.table("same_as_edges")
    live = edges[edges["suppressed_reason"].isna()].rename(columns={
        "mention_id_a": "mention_id_l", "mention_id_b": "mention_id_r",
        "probability": "match_probability"})
    mention_ids = repo.table("mentions")["mention_id"].tolist()
    return live, mention_ids


def resolve_at_threshold(repo: Repository, manifest: dict, gt_entity_id: str,
                          threshold: float, live_edges, all_mention_ids) -> dict:
    """For each of this GT entity's name-bearing mentions: did extraction find
    it, and if so what does it resolve into at this threshold -- and does
    that resolved cluster also contain mentions from OTHER ground-truth
    entities (over-merge)?
    """
    items = entity_ground_truth_items(manifest, gt_entity_id)
    labels = er.cluster_at(live_edges, all_mention_ids, threshold)

    rows = []
    resolved_ids_seen = set()
    for p in items["named"]:
        mid = _find_mention_id(repo, p["doc_id"], p["char_start"], p["char_end"])
        if mid is None:
            rows.append({"doc_id": p["doc_id"], "surface": p["surface"], "mention_id": None,
                         "status": "not_extracted", "resolved_entity": None})
            continue
        rid = labels.get(mid)
        if rid:
            resolved_ids_seen.add(rid)
        rows.append({"doc_id": p["doc_id"], "surface": p["surface"], "mention_id": mid,
                     "status": "extracted", "resolved_entity": rid})

    # over-merge check: what else shares a resolved cluster with this entity?
    contamination = {}
    if resolved_ids_seen:
        gt_by_span = defaultdict(list)
        for pl in manifest["placements"]:
            if pl["kind"] == "entity":
                gt_by_span[pl["doc_id"]].append((pl["char_start"], pl["char_end"], pl["gt_id"]))
        for rid in resolved_ids_seen:
            members = [m for m, r in labels.items() if r == rid]
            foreign = set()
            mrows = repo.df(
                f"SELECT mention_id, doc_id, char_start, char_end FROM mentions "
                f"WHERE mention_id IN ({','.join('?' for _ in members)})", tuple(members))
            for _, m in mrows.iterrows():
                for s, e, gid in gt_by_span.get(m["doc_id"], []):
                    if gid != gt_entity_id and _overlap(int(m["char_start"]), int(m["char_end"]), s, e):
                        foreign.add(gid)
            if foreign:
                contamination[rid] = sorted(foreign)

    n_clusters = len({r["resolved_entity"] for r in rows if r["resolved_entity"]})
    return {"rows": rows, "coref_only": items["coref"], "n_resolved_clusters": n_clusters,
            "contamination": contamination}


def edge_meta(repo: Repository, mention_a: str, mention_b: str) -> dict | None:
    """Was this pair actually proposed by blocking and scored? (Not the
    lineage itself -- just whether an edge exists and whether it was
    suppressed by a hard constraint before clustering.)
    """
    df = repo.df(
        "SELECT probability, suppressed_reason, uncalibrated FROM same_as_edges "
        "WHERE (mention_id_a=? AND mention_id_b=?) OR (mention_id_a=? AND mention_id_b=?)",
        (mention_a, mention_b, mention_b, mention_a),
    )
    return df.iloc[0].to_dict() if not df.empty else None


def load_lineage_linker(repo: Repository):
    """Load the trained Splink model (saved by entity_resolution.run()) plus
    the current mention frame, for on-demand pairwise re-scoring via
    linker.inference.compare_two_records(). Real Splink output, computed once
    per lookup instead of serialized for every one of the (possibly millions
    of) scored edges up front -- see entity_resolution.SplinkResolver.resolve.
    Returns (linker, frame_indexed_by_mention_id) or (None, None) if no
    trained model has been saved yet.
    """
    model_path = Paths.store / "splink_model.json"
    if not model_path.exists():
        return None, None
    from splink import DuckDBAPI, Linker

    frame = er.build_mention_frame(repo)
    linker = Linker(frame, settings=str(model_path), db_api=DuckDBAPI())
    return linker, frame.set_index("mention_id", drop=False)


def _weight_to_prob(w: float) -> float:
    try:
        odds = 2.0 ** w
        return odds / (1.0 + odds)
    except OverflowError:
        return 1.0 if w > 0 else 0.0


def mention_lineage_rows(linker, frame_by_id, mention_a: str, mention_b: str,
                         meta: dict | None) -> dict:
    """Field-by-field match lineage for one specific pair, computed live via
    Splink's compare_two_records against the trained model -- the same
    comparisons and calibrated m/u weights resolve() scored the whole corpus
    with, just re-applied to one pair on demand.
    """
    if mention_a not in frame_by_id.index or mention_b not in frame_by_id.index:
        return {"available": False, "reason": "mention not found in the current frame"}
    # Single-row DataFrame slices, not .to_dict(): a bare Python dict loses
    # the corpus-wide column dtype, and DuckDB then infers a fully-null
    # 2-record column (e.g. both mentions lack an email) as DOUBLE instead
    # of VARCHAR, which breaks the email comparison's regexp_extract call.
    rec_a = frame_by_id.loc[[mention_a]]
    rec_b = frame_by_id.loc[[mention_b]]
    pred = linker.inference.compare_two_records(rec_a, rec_b)
    row = pred.as_pandas_dataframe().iloc[0]

    labels_map = er.comparison_level_labels()
    match_weight = float(row.get("match_weight") or 0.0)
    match_probability = float(row.get("match_probability") or 0.0)

    entries = []
    total_contrib = 0.0
    for name, _, raw_cols in er.comparison_specs():
        gcol = f"gamma_{name}"
        if gcol not in row.index:
            continue
        bf = row.get(f"bf_{name}")
        bf = float(bf) if bf not in (None, "") else 1.0
        contrib = math.log2(bf) if bf and bf > 0 else 0.0
        total_contrib += contrib
        bf_tf = row.get(f"bf_tf_adj_{name}")
        bf_tf = float(bf_tf) if bf_tf not in (None, "") else None
        tf_contrib = 0.0
        if bf_tf and bf_tf > 0 and abs(bf_tf - 1.0) > 1e-9:
            tf_contrib = math.log2(bf_tf)
            total_contrib += tf_contrib
        gamma = int(row.get(gcol)) if row.get(gcol) is not None else -1
        label = labels_map.get(name, {}).get(gamma, f"level {gamma}")
        l_vals = [row.get(f"{c}_l") for c in raw_cols]
        r_vals = [row.get(f"{c}_r") for c in raw_cols]
        l_vals = [v for v in l_vals if v not in (None, "")]
        r_vals = [v for v in r_vals if v not in (None, "")]
        entries.append({
            "field": _COMPARISON_DISPLAY.get(name, name),
            "value_l": " ".join(str(v) for v in l_vals) or "∅",
            "value_r": " ".join(str(v) for v in r_vals) or "∅",
            "outcome": label, "contribution": round(contrib, 3),
            "tf_contribution": round(tf_contrib, 3) if tf_contrib else None,
        })

    prior_weight = match_weight - total_contrib
    running = prior_weight
    out_rows = [{"field": "prior", "value_l": "—", "value_r": "—",
                "outcome": "population base rate",
                "running_probability": round(_weight_to_prob(running), 4)}]
    for e in entries:
        running += e["contribution"]
        out_rows.append({"field": e["field"], "value_l": e["value_l"], "value_r": e["value_r"],
                         "outcome": e["outcome"],
                         "running_probability": round(_weight_to_prob(running), 4)})
        if e["tf_contribution"]:
            running += e["tf_contribution"]
            out_rows.append({"field": e["field"] + " (term-frequency adj.)", "value_l": "", "value_r": "",
                             "outcome": "adjusts for how common this value is corpus-wide",
                             "running_probability": round(_weight_to_prob(running), 4)})

    was_blocked = meta is not None
    return {"available": True, "rows": out_rows,
            "final_probability": round(match_probability, 4),
            "was_proposed_by_blocking": was_blocked,
            "suppressed_reason": (meta or {}).get("suppressed_reason"),
            # Which comparisons contributed a value Splink invented rather than
            # estimated. This is the screen where a reviewer decides whether to
            # trust a specific merge, so "part of this number is not calibrated"
            # belongs next to the number, not only in the run summary.
            "uncalibrated": (meta or {}).get("uncalibrated")}


# ---------------------------------------------------------------------------
# Screen 3: ground-truth correction queue
# ---------------------------------------------------------------------------
def token_offsets(text: str, start: int = 0, end: int | None = None) -> list[dict]:
    """Real character offsets for every word in a slice of doc text."""
    end = len(text) if end is None else end
    slice_ = text[start:end]
    return [{"text": m.group(0), "start": start + m.start(), "end": start + m.end()}
            for m in re.finditer(r"\S+", slice_)]


def render_token_offsets_html(text: str, start: int = 0, end: int | None = None) -> str:
    toks = token_offsets(text, start, end)
    spans = "".join(
        f'<span style="padding:2px 3px">{_esc(t["text"])}'
        f'<sup style="font-size:8px;color:#8a97a8;margin-left:1px">{t["start"]}–{t["end"]}</sup></span> '
        for t in toks
    )
    return (f'<div style="font-family:ui-monospace,monospace;font-size:14px;line-height:2.4;'
            f'white-space:pre-wrap;padding:14px;background:#EDF0F4;border:1px solid #ddd;'
            f'border-radius:4px">{spans}</div>')


def load_corrections() -> list[dict]:
    if not CORRECTIONS_PATH.exists():
        return []
    return json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))


def queue_correction(*, doc_id: str, char_start: int, char_end: int, span_kind: str,
                     entity_class: str | None, gt_entity_id: str | None,
                     hard_case_tags: list[str], orphan: bool, note: str,
                     orig_char_start: int | None = None, orig_char_end: int | None = None,
                     created_by: str = "") -> dict:
    """Append one correction to data/gt_corrections.json. Never touches
    data/ground_truth/manifest.json -- audit.py applies this patch at read
    time, so corpus_gen.py + seed still regenerates the identical sealed
    base file.

    orig_char_start/orig_char_end identify the EXISTING placement being
    corrected (audit.py matches on doc_id + that span and replaces it in
    place); leave both None when ground truth is missing this item outright
    and the correction should add a new placement instead.
    """
    record = {
        "correction_id": f"corr_{uuid.uuid4().hex[:12]}",
        "doc_id": doc_id, "char_start": int(char_start), "char_end": int(char_end),
        "span_kind": span_kind, "entity_class": entity_class, "gt_entity_id": gt_entity_id,
        "hard_case_tags": hard_case_tags or [], "orphan": bool(orphan), "note": note,
        "created_by": created_by,
        "created_ts": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    if orig_char_start is not None and orig_char_end is not None:
        record["orig_char_start"] = int(orig_char_start)
        record["orig_char_end"] = int(orig_char_end)
    records = load_corrections()
    records.append(record)
    CORRECTIONS_PATH.write_text(json.dumps(records, indent=1), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Gradio app
# ---------------------------------------------------------------------------
def build_app(repo: Repository):
    import gradio as gr

    manifest = audit._load_manifest()
    docs = interesting_docs(repo, manifest)
    doc_choices = [d["doc_id"] for d in docs] or repo.table("documents")["doc_id"].tolist()[:40]
    doc_labels = {d["doc_id"]: f"{d['doc_id']} — {d['n_issues']} issue(s) "
                                f"({d['fn']} entity miss, {d['fp']} FP, {d['fn_ident']} identifier miss)"
                  for d in docs}

    ent_choices = gt_entities_for_drilldown(repo, manifest)
    live_edges, all_mention_ids = load_live_edges(repo)
    lineage_linker, lineage_frame = load_lineage_linker(repo)

    def do_load_doc(doc_id):
        if not doc_id:
            return "", []
        data = doc_overlay(repo, manifest, doc_id)
        return render_doc_overlay_html(data), doc_overlay_table(data)

    def do_load_entity(gt_id, threshold):
        if not gt_id:
            return "", [], gr.update(choices=[])
        res = resolve_at_threshold(repo, manifest, gt_id, threshold, live_edges, all_mention_ids)
        rows = []
        for r in res["rows"]:
            if r["status"] == "not_extracted":
                rows.append([r["doc_id"], r["surface"], "not extracted", "-", "-"])
            else:
                contam = res["contamination"].get(r["resolved_entity"])
                rows.append([r["doc_id"], r["surface"], "extracted",
                            r["resolved_entity"][:14], ", ".join(contam) if contam else ""])
        for c in res["coref_only"]:
            rows.append([c["doc_id"], c["anaphor_text"], "coref-only (ER cannot link this)", "-", "-"])
        summary = (f"**{gt_id}**: {len(res['rows'])} name-bearing mention(s), "
                  f"resolving into **{res['n_resolved_clusters']}** cluster(s) at threshold {threshold:.2f}. "
                  f"{len(res['coref_only'])} coreference-only mention(s) are never reachable by entity "
                  f"resolution at any threshold (see column 3).")
        picker_choices = [f'{r["doc_id"]} :: {r["surface"]} :: {r["mention_id"]}'
                          for r in res["rows"] if r["mention_id"]]
        return summary, rows, gr.update(choices=picker_choices, value=None)

    def do_lineage(gt_id, picked):
        if not gt_id or not picked:
            return []
        base = entity_ground_truth_items(manifest, gt_id)["named"]
        anchor = None
        for p in base:
            mid = _find_mention_id(repo, p["doc_id"], p["char_start"], p["char_end"])
            if mid:
                anchor = mid
                break
        target = picked.split(" :: ")[-1]
        if anchor is None or target == anchor:
            return [["(anchor mention -- nothing to compare)", "", "", "", ""]]
        if lineage_linker is None:
            return [["no trained model saved yet", "-", "-",
                    "run entity_resolution.run() first -- it saves store/splink_model.json, "
                    "which this tab re-scores individual pairs against", "-"]]
        meta = edge_meta(repo, anchor, target)
        lineage = mention_lineage_rows(lineage_linker, lineage_frame, anchor, target, meta)
        if not lineage["available"]:
            return [[lineage.get("reason", "lineage unavailable"), "", "", "", ""]]
        rows = [[r["field"], r["value_l"], r["value_r"], r["outcome"], r["running_probability"]]
               for r in lineage["rows"]]
        if not lineage["was_proposed_by_blocking"]:
            rows.append(["NOTE", "-", "-",
                        "blocking never proposed this exact pair as a candidate -- this row is a "
                        "live re-score, not the pair resolve() actually clustered on; if they're "
                        "in the same resolved cluster it's via a transitive chain through a third "
                        "mention", "-"])
        elif lineage["suppressed_reason"]:
            rows.append(["SUPPRESSED", "-", "-", lineage["suppressed_reason"],
                        "excluded from clustering regardless of probability"])
        if lineage.get("uncalibrated"):
            rows.append(["UNCALIBRATED", "-", "-",
                        f"{lineage['uncalibrated']} contributed an m or u value "
                        "Splink INVENTED rather than estimated -- EM never "
                        "reached that level (e.g. only 7 of 922 mentions carry "
                        "an NPI, so there is nothing to learn from). The rest "
                        "of this breakdown is calibrated; this row is not.",
                        "treat this probability as partly uncalibrated"])
        return rows

    def do_load_doc_for_correction(doc_id):
        if not doc_id:
            return ""
        text = (Paths.raw_notes / f"{doc_id}.txt").read_text(encoding="utf-8")
        return render_token_offsets_html(text)

    def do_preview_boundary(doc_id, start, end):
        if not doc_id:
            return ""
        text = (Paths.raw_notes / f"{doc_id}.txt").read_text(encoding="utf-8")
        start, end = int(start or 0), int(end or 0)
        if end <= start or end > len(text):
            return "(invalid range)"
        return text[start:end]

    def do_queue(doc_id, start, end, orig_start, orig_end, span_kind, entity_class,
                gt_id, tags, orphan, note):
        record = queue_correction(
            doc_id=doc_id, char_start=start, char_end=end, span_kind=span_kind,
            entity_class=entity_class, gt_entity_id=gt_id, hard_case_tags=tags,
            orphan=orphan, note=note,
            orig_char_start=(orig_start if orig_start not in (None, "") else None),
            orig_char_end=(orig_end if orig_end not in (None, "") else None),
            created_by="yalovenko.artem@gmail.com")
        rows = [[r["created_ts"], r["doc_id"], f'[{r["char_start"]}, {r["char_end"]})',
                r["span_kind"], r["gt_entity_id"], ", ".join(r["hard_case_tags"])]
               for r in load_corrections()]
        return rows, f"Queued {record['correction_id']}."

    def do_refresh_pending():
        return [[r["created_ts"], r["doc_id"], f'[{r["char_start"]}, {r["char_end"]})',
                r["span_kind"], r["gt_entity_id"], ", ".join(r["hard_case_tags"])]
               for r in load_corrections()]

    with gr.Blocks(title="Extraction QA Viewer") as demo:
        gr.Markdown("# Extraction QA Viewer\n"
                    "Real data: the sealed manifest, the live repository, and the "
                    "Splink comparison columns retained at resolution time.")

        with gr.Tab("1. Document overlay"):
            gr.Markdown("Docs are ranked by how many ground-truth misses or false "
                       "positives they contain -- the interesting ones surface first.")
            doc_pick = gr.Dropdown(choices=[(doc_labels.get(d, d), d) for d in doc_choices],
                                   label="Document")
            overlay_html = gr.HTML()
            overlay_table = gr.Dataframe(headers=["kind", "status", "surface", "detail", "span"],
                                         label="Spans in this document")
            doc_pick.change(do_load_doc, doc_pick, [overlay_html, overlay_table])

        with gr.Tab("2. Resolution drill-down"):
            gr.Markdown("Pick a ground-truth entity and a threshold; clusters are "
                       "recomputed live from the real, stored `same_as_edges`.")
            with gr.Row():
                ent_pick = gr.Dropdown(choices=[(lbl, gid) for gid, lbl in ent_choices],
                                       label="Ground-truth entity")
                thr_slider = gr.Slider(minimum=0.1, maximum=0.95, step=0.05, value=0.45,
                                       label="Match threshold")
            dd_summary = gr.Markdown()
            dd_table = gr.Dataframe(
                headers=["doc_id", "surface", "status", "resolved_entity", "also_contains"],
                label="This entity's mentions at the current threshold")
            mention_pick = gr.Dropdown(label="Inspect match lineage for mention")
            lineage_table = gr.Dataframe(
                headers=["field", "anchor value", "this mention", "comparison outcome", "running P(match)"],
                label="Match lineage vs. this entity's anchor mention")
            ent_pick.change(do_load_entity, [ent_pick, thr_slider],
                            [dd_summary, dd_table, mention_pick])
            thr_slider.release(do_load_entity, [ent_pick, thr_slider],
                               [dd_summary, dd_table, mention_pick])
            mention_pick.change(do_lineage, [ent_pick, mention_pick], lineage_table)

        with gr.Tab("3. Correct ground truth"):
            with gr.Row():
                with gr.Column(scale=4):
                    gr.Markdown(FIELD_GUIDE_MD)
                with gr.Column(scale=6):
                    cf_doc = gr.Dropdown(choices=[(doc_labels.get(d, d), d) for d in doc_choices],
                                         label="Document")
                    token_html = gr.HTML()
                    with gr.Row():
                        start_in = gr.Number(label="corrected start offset", precision=0)
                        end_in = gr.Number(label="corrected end offset", precision=0)
                    boundary_preview = gr.Textbox(label="Resulting surface", interactive=False)
                    gr.Markdown("Leave the two fields below blank if ground truth is "
                               "missing this item outright (this queues an *add*, not "
                               "an edit to an existing placement).")
                    with gr.Row():
                        orig_start_in = gr.Number(label="original start offset (optional)", precision=0)
                        orig_end_in = gr.Number(label="original end offset (optional)", precision=0)
                    with gr.Row():
                        kind_in = gr.Dropdown(["entity", "identifier", "event", "non_entity"],
                                              value="entity", label="span kind")
                        class_in = gr.Dropdown(["person", "organization"], value="person",
                                               label="entity_class")
                    gtid_in = gr.Dropdown(
                        choices=[(lbl, gid) for gid, lbl in ent_choices],
                        label="gt_entity_id (search existing, or type a new gt_eNNNNN below)",
                        allow_custom_value=True)
                    tags_in = gr.CheckboxGroup(HARD_CASE_TAGS, label="hard_case_tags")
                    orphan_in = gr.Checkbox(label="orphan (identifiers only)")
                    note_in = gr.Textbox(label="note", lines=2)
                    queue_btn = gr.Button("Queue correction", variant="primary")
                    queue_status = gr.Markdown()
            pending_table = gr.Dataframe(
                headers=["created_ts", "doc_id", "span", "kind", "gt_entity_id", "hard_case_tags"],
                label="Pending corrections (data/gt_corrections.json)",
                value=do_refresh_pending())

            cf_doc.change(do_load_doc_for_correction, cf_doc, token_html)
            for trig in (start_in, end_in):
                trig.change(do_preview_boundary, [cf_doc, start_in, end_in], boundary_preview)
            queue_btn.click(do_queue,
                            [cf_doc, start_in, end_in, orig_start_in, orig_end_in,
                             kind_in, class_in, gtid_in, tags_in, orphan_in, note_in],
                            [pending_table, queue_status])

    return demo
