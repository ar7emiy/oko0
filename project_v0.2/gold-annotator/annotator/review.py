"""Independent claim review and immutable evaluation checkpoints."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import notes
from .store import UserError, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS category_reviews (
  claim TEXT NOT NULL, reviewer TEXT NOT NULL, entity_id TEXT NOT NULL,
  revision INTEGER NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (claim, reviewer, entity_id, revision));
CREATE TABLE IF NOT EXISTS review_checkpoints (
  claim TEXT NOT NULL, reviewer TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (claim, reviewer));
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_taxonomy(path=None):
    obj = json.loads(Path(path or Path(__file__).resolve().parents[1] / "taxonomy.json").read_text(encoding="utf-8-sig"))
    if not obj.get("version") or not obj.get("scope") or not obj.get("categories"):
        raise UserError("Taxonomy needs a version, scope and category definitions.")
    names = []
    for cat in obj["categories"]:
        if not isinstance(cat.get("name"), str) or not cat["name"].strip() or not cat.get("definition"):
            raise UserError("Every taxonomy category needs a name and definition.")
        names.append(cat["name"].casefold())
    if len(set(names)) != len(names):
        raise UserError("Taxonomy category names must be unique.")
    return obj


def checkpoint(store, claim, reviewer):
    row = store.one("SELECT payload FROM review_checkpoints WHERE claim=? AND reviewer=?", (claim, reviewer))
    return json.loads(row["payload"]) if row else None


def decisions(store, claim, reviewer):
    rows = store.q("SELECT payload FROM category_reviews WHERE claim=? AND reviewer=? ORDER BY revision", (claim, reviewer))
    return {d["entity_id"]: d for d in (json.loads(r["payload"]) for r in rows)}


def basis(entity, records, sources, taxonomy):
    return digest({"entity": entity, "records": records, "sources": sources, "taxonomy": taxonomy})


def dossier(app, claim, reviewer):
    frozen = checkpoint(app.store, claim, reviewer)
    if frozen:
        return {**frozen, "frozen": True, "legacy": False}
    with app.store.lock:
        rows = app.store.q("SELECT * FROM notes WHERE claim=? ORDER BY note", (claim,))
        if not rows:
            raise UserError("This claim has no registered notes.")
        sources = []
        for row in rows:
            nt = app.text(claim, row["note"])
            work = app.store.work(claim, row["note"], reviewer)
            sources.append({"note": row["note"], "fingerprint": nt.sha256, "status": work["status"],
                            "valid": work["fingerprint"] == nt.sha256})
        records = app.store.current_records(claim=claim, reviewer=reviewer)
        saved = decisions(app.store, claim, reviewer)
        entities = []
        for ent in app.store.entities(claim, reviewer):
            mine = sorted([r for r in records if ent["id"] in (r["entity_id"], r["entity2_id"])],
                          key=lambda r: (notes._natural(r["note"]), r["start"], r["uid"]))
            token = basis(ent, mine, sources, app.config.taxonomy)
            decision = saved.get(ent["id"])
            entities.append({**ent, "records": mine, "basis": token, "decision": decision,
                             "reviewed": bool(decision and decision["basis"] == token)})
        return {"claim": claim, "reviewer": reviewer, "entities": entities, "records": records,
                "sources": sources, "taxonomy": app.config.taxonomy,
                "unresolved": [r for r in records if r["kind"] == "unclear" and not r["entity_id"]],
                "frozen": False, "legacy": bool(app.store.sealed(claim, reviewer))}


def ensure_complete(data):
    if any(s["status"] != "complete" for s in data["sources"]):
        raise UserError("Finish every note before saving the claim review.")
    if any(not s["valid"] for s in data["sources"]):
        raise UserError("A note file changed or was not reviewed. Restore the reviewed source before freezing.")


def save(app, d):
    reviewer = app.reviewer(d)
    with app.store.lock:
        data = dossier(app, d["claim"], reviewer)
        if data["frozen"] or data["legacy"]:
            raise UserError("The firm's output has already been unlocked. Independent category decisions cannot be changed or backfilled.")
        ensure_complete(data)
        ent = next((e for e in data["entities"] if e["id"] == d["entity_id"]), None)
        if not ent or ent["basis"] != d.get("basis"):
            raise UserError("The evidence changed. Reload the dossier and review it again.")
        status = d.get("status")
        if status not in {"assigned", "insufficient", "conflicting"}:
            raise UserError("Choose a category decision or an unresolved outcome.")
        category = d.get("category") if status == "assigned" else None
        if status == "assigned" and category not in {c["name"] for c in data["taxonomy"]["categories"]}:
            raise UserError("Choose a category from the study taxonomy.")
        rationale = str(d.get("rationale") or "").strip()
        if not rationale:
            raise UserError("Explain the category or unresolved decision briefly.")
        links = d.get("evidence", [])
        if not isinstance(links, list):
            raise UserError("Evidence links must be a list.")
        valid = {(r["uid"], r["revision"]) for r in ent["records"]}
        seen, roles = set(), set()
        clean = []
        for link in links:
            key = (link["uid"], link["revision"])
            role = link["role"]
            if key not in valid or key in seen or role not in {"supports", "conflicts", "repeated"}:
                raise UserError("Use distinct current evidence from this entity and a valid evidence role.")
            seen.add(key)
            roles.add(role)
            clean.append({"uid": key[0], "revision": key[1], "role": role})
        if status == "assigned" and "supports" not in roles:
            raise UserError("Select at least one supporting record.")
        if status == "conflicting" and "conflicts" not in roles:
            raise UserError("Select the conflicting evidence.")
        subcategory = str(d.get("subcategory") or "").strip()
        if subcategory and not any(subcategory.casefold() in r["quote"].casefold() and
                                   (r["uid"], r["revision"]) in seen for r in ent["records"]):
            raise UserError("An optional subcategory must appear in the selected evidence. Otherwise leave it blank.")
        revision = (ent["decision"] or {}).get("revision", 0) + 1
        payload = {"claim": d["claim"], "reviewer": reviewer, "entity_id": ent["id"], "revision": revision,
                   "status": status, "category": category, "subcategory": subcategory,
                   "rationale": rationale, "evidence": clean, "basis": ent["basis"],
                   "taxonomy_version": data["taxonomy"]["version"], "created_at": now()}
        prior = ent["decision"]
        compare_fields = [k for k in payload if k not in {"revision", "created_at"}]
        if prior and all(prior[k] == payload[k] for k in compare_fields):
            return {"ok": True, "decision": prior}
        if d.get("revision", 0) != (prior or {}).get("revision", 0):
            raise UserError("This category decision changed in another view. Reload before replacing it.")
        with app.store.tx() as db:
            db.execute("INSERT INTO category_reviews VALUES (?,?,?,?,?)",
                       (d["claim"], reviewer, ent["id"], revision, json.dumps(payload)))
        return {"ok": True, "decision": payload}


def freeze(app, d):
    reviewer = app.reviewer(d)
    with app.store.lock:
        data = dossier(app, d["claim"], reviewer)
        if data["frozen"]:
            return {"ok": True}
        if data["legacy"]:
            raise UserError("This claim was already exposed to firm output; it cannot be frozen as an independent review.")
        ensure_complete(data)
        if any(not e["reviewed"] for e in data["entities"]):
            raise UserError("Review every entity's category and current evidence before freezing.")
        if app.store.one("SELECT 1 FROM drafts WHERE claim=? AND reviewer=? AND status IN ('ready','needs_attention')",
                         (d["claim"], reviewer)):
            raise UserError("Resolve the remaining AI drafts before freezing.")
        if d.get("attest") is not True:
            raise UserError("Confirm you reviewed the claim evidence before freezing.")
        data["frozen_at"] = now()
        data["frozen"] = True
        data["attestation"] = "I reviewed the claim entities, evidence ownership and unresolved references before seeing the firm's output."
        with app.store.tx() as db:
            db.execute("INSERT INTO review_checkpoints VALUES (?,?,?)", (d["claim"], reviewer, json.dumps(data)))
            db.execute("INSERT INTO claim_seal VALUES (?,?,?)", (d["claim"], reviewer, data["frozen_at"]))
        return {"ok": True}
