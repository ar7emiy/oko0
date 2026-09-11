"""Three joinable analysis tables. Frozen evidence is preferred to later edits."""
import json
from .notes import is_practice
from .firm import COLUMNS
from .review import checkpoint
from .completion import status as comparison_status
from .scoring import score

COMMON = ["reviewer", "claim", "is_practice", "answer_key_basis", "frozen_at", "comparison_complete"]
ENTITY_COLUMNS = COMMON + ["row_kind", "entity_id", "entity_number", "entity_label", "entity_type", "firm_row_id",
    "pairing_status", "category_status", "gold_category", "subcategory", "category_rationale", "category_evidence_json",
    "gold_details_json", "watchlist_decision", "note_supports", "watchlist_reason"] + ["firm_" + c for c in COLUMNS]
EVIDENCE_COLUMNS = COMMON + ["uid", "revision", "note", "source_path", "source_fingerprint", "kind", "start", "end", "quote",
    "entity_id", "entity_label", "entity2_id", "entity2_label", "form", "is_first", "field", "value", "label", "reason",
    "source", "draft_id", "after_seal", "created_at", "category_evidence_roles_json"]
KPI_COLUMNS = ["reviewer", "scope", "group", "metric", "name", "numerator", "denominator", "value", "text", "meaning",
    "set_aside", "completed_comparisons", "total_scored_claims", "pending_firm_rows", "provisional"]


def tables(store, reviewer=None, include_practice=False):
    reviewers = [reviewer] if reviewer else store.reviewers()
    entities_out, evidence_out, kpis = [], [], []
    for rv in reviewers:
        claims = sorted({r["claim"] for r in store.q("SELECT claim FROM notes")})
        for claim in claims:
            if is_practice(claim) and not include_practice:
                continue
            frozen = checkpoint(store, claim, rv)
            sealed = store.sealed(claim, rv)
            ents = frozen["entities"] if frozen else store.entities(claim, rv)
            recs = frozen["records"] if frozen else store.current_records(claim=claim, reviewer=rv)
            by_id = {e["id"]: e for e in ents}
            comp = comparison_status(store, claim, rv)
            common = {"reviewer": rv, "claim": claim, "is_practice": int(is_practice(claim)),
                      "answer_key_basis": "frozen" if frozen else "legacy_exposed" if sealed else "in_progress",
                      "frozen_at": frozen["frozen_at"] if frozen else "", "comparison_complete": int(comp["complete"])}
            rows = store.firm_rows(claim) if sealed else []
            pairings, watches = store.pairings(rv), store.watchlist(rv)
            paired_ids = set()
            def entity_row(e, row=None):
                p = pairings.get(f"{row['id']}|{rv}", {}) if row else {}
                w = watches.get(f"{row['id']}|{rv}", {}) if row else {}
                decision = (e or {}).get("decision") or {}
                details = [{"field": r["field"], "value": r["value"], "uid": r["uid"]} for r in recs if e and r["entity_id"] == e["id"] and r["kind"] == "detail"]
                return {**common, "row_kind": "firm_row" if row else "gold_only", "entity_id": (e or {}).get("id"),
                    "entity_number": (e or {}).get("number"), "entity_label": (e or {}).get("label"), "entity_type": (e or {}).get("type"),
                    "firm_row_id": row["id"] if row else "", "pairing_status": "paired" if p.get("entity_id") else "not_in_notes" if p.get("not_in_notes") else "pending" if row else "no_paired_firm_row",
                    "category_status": decision.get("status"), "gold_category": decision.get("category"), "subcategory": decision.get("subcategory"),
                    "category_rationale": decision.get("rationale"), "category_evidence_json": json.dumps(decision.get("evidence", []), ensure_ascii=False),
                    "gold_details_json": json.dumps(details, ensure_ascii=False), "watchlist_decision": w.get("decision"),
                    "note_supports": w.get("note_supports"), "watchlist_reason": w.get("reason"),
                    **({"firm_" + k: v for k, v in row["data"].items()} if row else {})}
            for row in rows:
                p = pairings.get(f"{row['id']}|{rv}", {})
                ent = by_id.get(p.get("entity_id"))
                if ent:
                    paired_ids.add(ent["id"])
                entities_out.append(entity_row(ent, row))
            for e in ents:
                if e["id"] not in paired_ids:
                    entities_out.append(entity_row(e))
            sources = {s["note"]: s["fingerprint"] for s in frozen["sources"]} if frozen else {}
            for r in recs:
                source = store.one("SELECT path FROM notes WHERE claim=? AND note=?", (claim, r["note"])) or {}
                roles = [{"entity_id": e["id"], "role": link["role"]} for e in ents for link in (e.get("decision") or {}).get("evidence", []) if link["uid"] == r["uid"] and link["revision"] == r["revision"]]
                evidence_out.append({**r, **common, "source_path": source.get("path"),
                    "source_fingerprint": sources.get(r["note"]) or store.work(claim, r["note"], rv)["fingerprint"],
                    "entity_label": by_id.get(r["entity_id"], {}).get("label"), "entity2_label": by_id.get(r["entity2_id"], {}).get("label"),
                    "category_evidence_roles_json": json.dumps(roles, ensure_ascii=False)})
        result = score(store, rv, include_practice)
        completed = sum(comparison_status(store, c["claim"], rv)["complete"] for c in result["claims"])
        common_kpi = {"reviewer": rv, "scope": "includes_practice" if include_practice else "real_only",
                      "completed_comparisons": completed, "total_scored_claims": len(result["claims"]),
                      "pending_firm_rows": result["pending_rows"], "provisional": int(completed != len(result["claims"]))}
        for m in result["metrics"]:
            kpis.append({**common_kpi, **m, "group": "firm_vs_gold", "metric": m["id"]})
        for group, key, name in [("watchlist", "watchlist_by_method", "method"), ("similarity", "similarity_bins", "range")]:
            for m in result[key]:
                kpis.append({**common_kpi, **m, "group": group, "metric": m[name], "name": m[name], "set_aside": m.get("cant_tell")})
        for key in ("draft_precision", "correction_rate", "miss_rate"):
            kpis.append({**common_kpi, **result["ai"][key], "group": "ai_review_diagnostic", "metric": key,
                         "meaning": "Reviewer decisions, not independent model accuracy"})
        for a in result["agreement"]:
            kpis.append({**common_kpi, **a, "group": "annotation_overlap", "metric": f"{a['claim']}/{a['note']}: {' + '.join(a['reviewers'])}",
                         "meaning": "Exact span/kind/field overlap; does not score entity identity or category agreement"})
    return {"entity_comparison.csv": (entities_out, ENTITY_COLUMNS), "evidence.csv": (evidence_out, EVIDENCE_COLUMNS),
            "kpi_summary.csv": (kpis, KPI_COLUMNS)}
