"""Durable operation undo. Record history and frozen checkpoints are never deleted."""
import functools
import json

from .store import UserError, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS undo_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, reviewer TEXT NOT NULL, claim TEXT NOT NULL,
 label TEXT NOT NULL, payload TEXT NOT NULL, undone_at TEXT);
"""
OPERATIONS = {"entity_create": "create entity", "entity_update": "edit entity", "entity_delete": "delete entity",
              "record_create": "create annotation", "record_update": "edit annotation", "record_delete": "delete annotation",
              "draft_accept": "accept AI draft", "draft_dismiss": "dismiss AI draft"}


def capture(store, claim, reviewer):
    records = store.q("SELECT r.* FROM records r JOIN (SELECT uid,MAX(revision) rev FROM records GROUP BY uid) m "
                      "ON r.uid=m.uid AND r.revision=m.rev WHERE r.claim=? AND r.reviewer=?", (claim, reviewer))
    return {
        "entities": {r["id"]: r for r in store.q("SELECT * FROM entities WHERE claim=? AND reviewer=?", (claim, reviewer))},
        "records": {r["uid"]: r for r in records},
        "drafts": {r["id"]: r for r in store.q("SELECT * FROM drafts WHERE claim=? AND reviewer=?", (claim, reviewer))},
        "run_keys": {r["run_id"] + "|" + r["key"]: r for r in store.q(
            "SELECT k.* FROM run_keys k JOIN runs r ON r.id=k.run_id WHERE r.claim=? AND r.reviewer=?", (claim, reviewer))},
    }


def diff(before, after):
    return {table: {key: {"before": before[table].get(key), "after": after[table].get(key)}
                    for key in before[table].keys() | after[table].keys() if before[table].get(key) != after[table].get(key)}
            for table in before}


def journal(fn):
    @functools.wraps(fn)
    def wrapped(app, d):
        reviewer = app.reviewer(d)
        with app.store.tx():
            if "claim" in d:
                claim = d["claim"]
            elif fn.__name__.startswith("entity"):
                claim = app.store.entity(d["id"])["claim"]
            elif fn.__name__.startswith("draft"):
                claim = app.store.draft(d["id"])["claim"]
            else:
                claim = app.store.record(d["uid"])["claim"]
            before = capture(app.store, claim, reviewer)
            result = fn(app, d)
            delta = diff(before, capture(app.store, claim, reviewer))
            if any(delta.values()):
                app.store.db.execute("INSERT INTO undo_actions(reviewer,claim,label,payload) VALUES (?,?,?,?)",
                                     (reviewer, claim, OPERATIONS[fn.__name__], json.dumps(delta)))
            return result
    return wrapped


def seed_legacy(app):
    """One-time recovery of a pre-upgrade user's latest reconstructible manual change."""
    for reviewer in app.store.reviewers():
        event = app.store.one("SELECT * FROM events WHERE reviewer=? ORDER BY id DESC LIMIT 1", (reviewer,))
        if not event:
            continue
        detail = json.loads(event["detail"])
        action = event["action"]
        delta = {t: {} for t in ("entities", "records", "drafts", "run_keys")}
        if action in {"record.add", "record.update", "record.delete"}:
            history = app.store.q("SELECT * FROM records WHERE uid=? ORDER BY revision", (detail["uid"],))
            if not history or history[-1]["reviewer"] != reviewer:
                continue
            row = history[-1]
            delta["records"][row["uid"]] = {"before": history[-2] if len(history) > 1 else None, "after": row}
            claim = row["claim"]
        elif action == "entity.create":
            ent = app.store.entity(detail["entity"])
            records = app.store.current_records(claim=ent["claim"], reviewer=reviewer)
            mine = [r for r in records if ent["id"] in (r["entity_id"], r["entity2_id"])]
            if len(mine) != 1 or not mine[0]["is_first"]:
                continue
            delta["entities"][ent["id"]] = {"before": None, "after": ent}
            delta["records"][mine[0]["uid"]] = {"before": None, "after": mine[0]}
            claim = ent["claim"]
        else:
            continue
        app.store.db.execute("INSERT INTO undo_actions(reviewer,claim,label,payload) VALUES (?,?,?,?)",
                             (reviewer, claim, action.replace(".", " "), json.dumps(delta)))


def comparable(table, row):
    if row is None:
        return None
    skip = {"row_id", "revision", "created_at", "after_seal"} if table == "records" else set()
    return {k: v for k, v in row.items() if k not in skip}


def perform(app, d):
    reviewer = app.reviewer(d)
    with app.store.lock:
        action = app.store.one("SELECT * FROM undo_actions WHERE reviewer=? AND undone_at IS NULL ORDER BY id DESC LIMIT 1", (reviewer,))
        if not action:
            raise UserError("No saved annotation changes left to undo.")
        delta = json.loads(action["payload"])
        claim = action["claim"]
        current = capture(app.store, claim, reviewer)
        for table, changes in delta.items():
            for key, change in changes.items():
                if comparable(table, current[table].get(key)) != comparable(table, change["after"]):
                    raise UserError("This item changed outside the undo history. Reload and correct it directly.")
        # Validate the intended resulting entity graph before writing any inverse.
        entities = {k: dict(v) for k, v in current["entities"].items()}
        for key, c in delta["entities"].items():
            entities[key] = c["before"] or {**c["after"], "retired": 1}
        resulting = dict(current["records"])
        for key, c in delta["records"].items():
            resulting[key] = c["before"] or {**c["after"], "state": "retired"}
        for r in resulting.values():
            if r["state"] == "accepted":
                for key in (r["entity_id"], r["entity2_id"]):
                    if key and (key not in entities or entities[key]["retired"]):
                        raise UserError("Undo would leave another annotation without its entity. Correct that link first.")
        keys = dict(current["run_keys"])
        for key, c in delta["run_keys"].items():
            if c["before"]:
                keys[key] = c["before"]
            else:
                keys.pop(key, None)
        if any(k["entity_id"] not in entities or entities[k["entity_id"]]["retired"] for k in keys.values()):
            raise UserError("An AI run still refers to this entity. Correct that dependency before undoing it.")
        affected = set()
        for c in delta["records"].values():
            r = c["before"] or c["after"]
            nt = app.text(claim, r["note"])
            fingerprint = app.store.work(claim, r["note"], reviewer)["fingerprint"]
            if nt.sha256 != fingerprint or nt.text[r["start"]:r["end"]] != r["quote"]:
                raise UserError("The source note changed. Restore it before undoing this annotation.")
            affected.add(r["note"])
        with app.store.tx() as db:
            for key, c in delta["entities"].items():
                r = c["before"] or {**c["after"], "retired": 1}
                db.execute("UPDATE entities SET label=?,type=?,retired=? WHERE id=?", (r["label"], r["type"], r["retired"], key))
            for key, c in delta["records"].items():
                r = c["before"] or {**c["after"], "state": "retired"}
                cols = {k: v for k, v in r.items() if k not in {"row_id", "revision", "created_at", "after_seal"}}
                app.store._insert_record(db, revision=current["records"][key]["revision"] + 1, **cols)
            for key, c in delta["drafts"].items():
                r = c["before"]
                if r:
                    cols = {k: v for k, v in r.items() if k != "id"}
                    db.execute("UPDATE drafts SET " + ",".join(k + "=?" for k in cols) + " WHERE id=?", (*cols.values(), key))
                    affected.add(r["note"])
            for c in delta["run_keys"].values():
                r = c["before"] or c["after"]
                db.execute("DELETE FROM run_keys WHERE run_id=? AND key=?", (r["run_id"], r["key"]))
                if c["before"]:
                    db.execute("INSERT INTO run_keys VALUES (?,?,?)", (r["run_id"], r["key"], r["entity_id"]))
            for note in affected:
                db.execute("UPDATE note_work SET status='in_progress',completed_at=NULL WHERE claim=? AND note=? AND reviewer=?", (claim, note, reviewer))
            db.execute("UPDATE undo_actions SET undone_at=? WHERE id=?", (now(), action["id"]))
            db.execute("INSERT INTO events(at,reviewer,action,detail) VALUES (?,?,?,?)", (now(), reviewer, "annotation.undo", json.dumps({"undo_id": action["id"], "label": action["label"]})))
        return {"ok": True, "message": "Undid " + action["label"] + ".", "claim": claim,
                "note": sorted(affected)[0] if affected else None}
