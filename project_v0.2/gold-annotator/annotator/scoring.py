"""The scores in EVALUATION.md, each computed as a plain fraction.

Only claims an SME has finished and compared ("sealed") are scored, because a
found rate is meaningless on notes nobody has finished reading. Firm rows the
SME hasn't paired yet are reported as pending, never guessed.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .firm import DETAIL_COLUMNS, NER_TO_TYPE, is_flagged
from .notes import PRACTICE_CLAIM
from .review import checkpoint

_SEPARATORS = re.compile(r"[\s\-\.\(\)/,]+")


def norm_value(kind: str, value: str) -> str:
    """Formatting differences don't count; different characters do (001234567 != 1234567)."""
    v = (value or "").strip().casefold()
    if kind in {"phone", "TIN", "zip_code"}:
        return _SEPARATORS.sub("", v)
    return re.sub(r"\s+", " ", v).strip(" .,;")


def fraction(num: int, den: int) -> dict:
    return {"numerator": num, "denominator": den,
            "value": (num / den) if den else None,
            "text": f"{num} ÷ {den} = {round(100 * num / den)}%" if den else f"{num} ÷ 0 — nothing to score yet"}


def _metric(mid: str, name: str, num: int, den: int, meaning: str, **extra) -> dict:
    return {"id": mid, "name": name, "meaning": meaning, **fraction(num, den), **extra}


def score(store, reviewer: str, include_practice: bool = False) -> dict:
    claims = sorted({r["claim"] for r in store.q("SELECT claim FROM claim_seal WHERE reviewer=?", (reviewer,))})
    if not include_practice:
        claims = [c for c in claims if c != PRACTICE_CLAIM]
    pairings = store.pairings(reviewer)
    watch = store.watchlist(reviewer)

    t = defaultdict(int)
    bins = {"95–100": [0, 0, 0], "85–94": [0, 0, 0], "75–84": [0, 0, 0], "below 75": [0, 0, 0]}
    by_method = {"exact": [0, 0, 0], "genai": [0, 0, 0]}
    per_claim = []

    for claim in claims:
        frozen = checkpoint(store, claim, reviewer)
        entities = frozen["entities"] if frozen else store.entities(claim, reviewer)
        records = frozen["records"] if frozen else store.current_records(claim=claim, reviewer=reviewer)
        category_by_entity = {e["id"]: e["decision"] for e in entities} if frozen else {}
        details = [r for r in records if r["kind"] == "detail"]
        rows = store.firm_rows(claim)
        gold_by_entity = defaultdict(lambda: defaultdict(set))
        gold_claim_kind = defaultdict(set)
        gold_any = set()
        for d in details:
            nv = norm_value(d["field"], d["value"] or d["quote"])
            gold_by_entity[d["entity_id"]][d["field"]].add(nv)
            gold_claim_kind[d["field"]].add(nv)
            gold_any.add(nv)
        paired_entities, pending, c_rows = set(), 0, defaultdict(int)
        for row in rows:
            data = row["data"]
            p = pairings.get(f"{row['id']}|{reviewer}")
            if not p or (not p["entity_id"] and not p["not_in_notes"]):
                pending += 1
                continue
            c_rows["decided"] += 1
            if p["entity_id"]:
                c_rows["paired"] += 1
                paired_entities.add(p["entity_id"])
                ent = next((e for e in entities if e["id"] == p["entity_id"]), None)
                gold_type = NER_TO_TYPE.get(data.get("entity_NER_tag", "").strip().upper())
                if ent and gold_type and ent["type"] in {"person", "organization", "location"}:
                    t["type_den"] += 1
                    t["type_num"] += int(gold_type == ent["type"])
                for col, kind in DETAIL_COLUMNS.items():
                    reported = data.get(col, "")
                    if not reported:
                        continue
                    nv = norm_value(kind, reported)
                    t["det_reported"] += 1
                    if nv in gold_by_entity[p["entity_id"]][kind]:
                        t["det_correct"] += 1
                        t["det_right_owner"] += 1
                    elif nv in gold_claim_kind[kind]:
                        t["det_correct"] += 1
                    if nv not in gold_any:
                        t["det_made_up"] += 1
            if p["entity_id"]:
                t["cat_eligible"] += 1
                decision = category_by_entity.get(p["entity_id"])
                if decision and decision["status"] == "assigned":
                    same = decision["category"].strip().casefold() == data.get("entity_category_name", "").strip().casefold()
                    t["cat_den"] += 1
                    t["cat_num"] += int(same)
                    t["cat_wrong"] += int(not same)
                else:
                    t["cat_unknown"] += 1

            if is_flagged(data):
                w = watch.get(f"{row['id']}|{reviewer}")
                if w and w["decision"]:
                    methods = []
                    if data.get("Exact_search_Note_ID"):
                        methods.append("exact")
                    if data.get("GenAI_search_Note_ID") or data.get("recordType") == "genai_only":
                        methods.append("genai")
                    for m in methods:
                        slot = by_method[m]
                        if w["decision"] == "same":
                            slot[0] += 1
                        elif w["decision"] == "different":
                            slot[1] += 1
                        else:
                            slot[2] += 1
                    t["watch_decided"] += 1
                    t["watch_cant"] += int(w["decision"] == "cant_tell")
                    sim = data.get("GenAI_tok_sort_similarity", "").strip()
                    if "genai" in methods and re.fullmatch(r"\d+(\.\d+)?", sim):
                        s = float(sim)
                        key = "95–100" if s >= 95 else "85–94" if s >= 85 else "75–84" if s >= 75 else "below 75"
                        b = bins[key]
                        b[0] += 1
                        b[1] += int(w["decision"] == "same")
                        b[2] += int(w["decision"] == "cant_tell")

        gold_details_comparable = [d for d in details if d["field"] in DETAIL_COLUMNS.values()]
        for d in gold_details_comparable:
            t["gold_details"] += 1
            reported_on_row = False
            for row in rows:
                p = pairings.get(f"{row['id']}|{reviewer}")
                if p and p["entity_id"] == d["entity_id"]:
                    col = next(c for c, k in DETAIL_COLUMNS.items() if k == d["field"])
                    if row["data"].get(col):
                        reported_on_row = True
            t["det_missed"] += int(not reported_on_row)

        t["ent_gold"] += len(entities)
        t["ent_found"] += len(paired_entities)
        t["rows_decided"] += c_rows["decided"]
        t["rows_paired"] += c_rows["paired"]
        t["rows_pending"] += pending
        per_claim.append({"claim": claim, "entities": len(entities), "firm_rows": len(rows),
                          "pending_rows": pending, "found": len(paired_entities)})

    metrics = [
        _metric("found_rate", "Found rate", t["ent_found"], t["ent_gold"],
                "People and companies both the firm and the SME found ÷ everyone the SME found"),
        _metric("right_rate", "Right rate", t["rows_paired"], t["rows_decided"],
                "Firm rows that match someone on the SME's list ÷ all firm rows the SME has paired"),
        _metric("detail_accuracy", "Detail accuracy", t["det_correct"], t["det_reported"],
                "Details the firm got exactly right ÷ details the firm reported"),
        _metric("missed_detail_rate", "Missed-detail rate", t["det_missed"], t["gold_details"],
                "Details in the notes the firm didn't report ÷ details the SME found"),
        _metric("made_up_rate", "Made-up rate", t["det_made_up"], t["det_reported"],
                "Details the firm reported that no note states ÷ details the firm reported"),
        _metric("right_owner_rate", "Right-owner rate", t["det_right_owner"], t["det_correct"],
                "Correct details on the correct person or company ÷ all correct details"),
        _metric("type_agreement", "Person/organization tag", t["type_num"], t["type_den"],
                "Firm rows whose PERSON/ORG tag matches the SME's type ÷ rows both label"),
        _metric("category_accuracy", "Category accuracy", t["cat_num"], t["cat_den"],
                "Paired firm rows matching a frozen independent category ÷ paired rows with an assigned frozen category",
                set_aside=t["cat_unknown"], wrong=t["cat_wrong"]),
        _metric("category_coverage", "Category coverage", t["cat_den"], t["cat_eligible"],
                "Paired firm rows with an assigned frozen category ÷ all paired firm rows; unresolved and legacy labels are excluded from accuracy"),
        _metric("cant_tell_rate", "Can't-tell rate", t["watch_cant"], t["watch_decided"],
                "Watchlist flags the SME couldn't decide ÷ all flags reviewed"),
    ]
    methods = []
    for m, (same, diff, cant) in by_method.items():
        methods.append({"method": "Exact search" if m == "exact" else "GenAI", **fraction(same, same + diff),
                        "same": same, "different": diff, "cant_tell": cant})
    return {
        "reviewer": reviewer,
        "claims": per_claim,
        "pending_rows": t["rows_pending"],
        "metrics": metrics,
        "watchlist_by_method": methods,
        "similarity_bins": [{"range": k, "flags": v[0], "confirmed_same": v[1], "cant_tell": v[2],
                             **fraction(v[1], v[0] - v[2])} for k, v in bins.items()],
        "wrong_category_count": t["cat_wrong"],
        "ai": ai_scores(store, reviewer, include_practice),
        "agreement": agreement(store, include_practice),
    }


def ai_scores(store, reviewer: str, include_practice: bool = False) -> dict:
    drafts = store.q("SELECT * FROM drafts WHERE reviewer=?", (reviewer,))
    if not include_practice:
        drafts = [d for d in drafts if d["claim"] != PRACTICE_CLAIM]
    accepted = [d for d in drafts if d["status"] == "accepted"]
    dismissed = [d for d in drafts if d["status"] == "dismissed"]
    edited = [d for d in accepted if d["edited"]]
    assisted_notes = {(d["claim"], d["note"]) for d in drafts}
    in_assisted = [r for r in store.current_records(reviewer=reviewer) if (r["claim"], r["note"]) in assisted_notes]
    manual = [r for r in in_assisted if r["source"] == "manual"]
    return {
        "draft_precision": fraction(len(accepted), len(accepted) + len(dismissed)),
        "correction_rate": fraction(len(edited), len(accepted)),
        "miss_rate": fraction(len(manual), len(in_assisted)),
        "counts": {"drafts": len(drafts), "accepted": len(accepted), "edited": len(edited),
                   "dismissed": len(dismissed),
                   "pending": len([d for d in drafts if d["status"] in {"ready", "needs_attention"}])},
    }


def agreement(store, include_practice: bool = False) -> list[dict]:
    """Exact agreement between reviewers who annotated the same note: shared ÷ either recorded."""
    rows = store.current_records()
    by_note = defaultdict(lambda: defaultdict(set))
    for r in rows:
        if r["claim"] == PRACTICE_CLAIM and not include_practice:
            continue
        by_note[(r["claim"], r["note"])][r["reviewer"]].add((r["kind"], r["start"], r["end"], r["field"] or ""))
    out = []
    for (claim, note), per in sorted(by_note.items()):
        names = sorted(per)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = per[names[i]], per[names[j]]
                out.append({"claim": claim, "note": note, "reviewers": [names[i], names[j]],
                            **fraction(len(a & b), len(a | b))})
    return out
