"""Explicit comparison completion tied to the saved row decisions."""
from . import review
from .firm import is_flagged
from .store import UserError, now

SCHEMA = """CREATE TABLE IF NOT EXISTS comparison_completion (
claim TEXT NOT NULL, reviewer TEXT NOT NULL, basis TEXT NOT NULL, completed_at TEXT NOT NULL,
PRIMARY KEY(claim,reviewer));"""


def status(store, claim, reviewer):
    rows = store.firm_rows(claim)
    pairings, watches = store.pairings(reviewer), store.watchlist(reviewer)
    independent = bool(review.checkpoint(store, claim, reviewer))
    pending, state = [], []
    for r in rows:
        p = pairings.get(f"{r['id']}|{reviewer}") or {}
        w = watches.get(f"{r['id']}|{reviewer}") or {}
        paired = bool(p.get("entity_id")) != bool(p.get("not_in_notes"))
        cat = independent or p.get("not_in_notes") or (p.get("category_verdict") in {"right", "unknown"}) or (
            p.get("category_verdict") == "wrong" and bool(p.get("correct_category")))
        watch = not is_flagged(r["data"]) or (w.get("decision") in {"same", "different", "cant_tell"} and
            w.get("note_supports") in {"yes", "no", "partly"} and bool((w.get("reason") or "").strip()))
        if not (paired and cat and watch):
            pending.append(r["id"])
        state.append({"row": r, "pairing": p, "watchlist": w})
    basis = review.digest(state)
    saved = store.one("SELECT * FROM comparison_completion WHERE claim=? AND reviewer=?", (claim, reviewer))
    complete = bool(saved and saved["basis"] == basis and not pending)
    return {"complete": complete, "completed_at": saved["completed_at"] if complete else None,
            "pending": pending, "basis": basis, "rows": len(rows)}


def finish(app, d):
    reviewer, claim = app.reviewer(d), d["claim"]
    with app.store.tx() as db:
        if not app.store.sealed(claim, reviewer):
            raise UserError("Freeze the answer key before finishing comparison.")
        state = status(app.store, claim, reviewer)
        if state["pending"]:
            raise UserError(f"{len(state['pending'])} firm row(s) still need pairing, category or watchlist answers.")
        if not state["complete"]:
            db.execute("INSERT OR REPLACE INTO comparison_completion VALUES (?,?,?,?)", (claim, reviewer, state["basis"], now()))
        return {"ok": True, "comparison": status(app.store, claim, reviewer)}
