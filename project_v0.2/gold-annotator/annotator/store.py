"""SQLite storage for the answer key.

Append-only for annotations: an edit writes a new revision of the same record,
a delete writes a "retired" revision. Nothing an SME accepted is ever
overwritten, so every change keeps its history. Notes themselves are not
stored -- only their path, a fingerprint, and positions into their text.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
  claim TEXT NOT NULL, note TEXT NOT NULL, path TEXT NOT NULL, practice INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (claim, note));
CREATE TABLE IF NOT EXISTS note_work (
  claim TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_started', blind INTEGER NOT NULL DEFAULT 0,
  fingerprint TEXT, opened_at TEXT, completed_at TEXT,
  PRIMARY KEY (claim, note, reviewer));
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY, claim TEXT NOT NULL, reviewer TEXT NOT NULL, number INTEGER NOT NULL,
  label TEXT NOT NULL, type TEXT NOT NULL, created_at TEXT NOT NULL,
  retired INTEGER NOT NULL DEFAULT 0, after_seal INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS records (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, revision INTEGER NOT NULL,
  state TEXT NOT NULL, kind TEXT NOT NULL, claim TEXT NOT NULL, note TEXT NOT NULL,
  reviewer TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, quote TEXT NOT NULL,
  entity_id TEXT, entity2_id TEXT, form TEXT, field TEXT, value TEXT, label TEXT, reason TEXT,
  is_first INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, draft_id TEXT,
  after_seal INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS records_uid ON records(uid, revision);
CREATE INDEX IF NOT EXISTS records_note ON records(claim, note, reviewer);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, claim TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL,
  created_at TEXT NOT NULL, raw TEXT NOT NULL, report TEXT NOT NULL, prompt_version TEXT);
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, claim TEXT NOT NULL, note TEXT NOT NULL,
  reviewer TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, key TEXT, key2 TEXT,
  quote TEXT, start INTEGER, end INTEGER, match TEXT, candidates TEXT, fields TEXT,
  problems TEXT, notes TEXT, status TEXT NOT NULL, duplicate_of TEXT, outcome_uid TEXT,
  edited INTEGER, raw TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS run_keys (
  run_id TEXT NOT NULL, key TEXT NOT NULL, entity_id TEXT NOT NULL, PRIMARY KEY (run_id, key));
CREATE TABLE IF NOT EXISTS claim_seal (
  claim TEXT NOT NULL, reviewer TEXT NOT NULL, sealed_at TEXT NOT NULL, PRIMARY KEY (claim, reviewer));
CREATE TABLE IF NOT EXISTS firm_rows (
  id TEXT PRIMARY KEY, claim TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL, source TEXT);
CREATE TABLE IF NOT EXISTS pairings (
  firm_row_id TEXT NOT NULL, reviewer TEXT NOT NULL, entity_id TEXT, not_in_notes INTEGER NOT NULL DEFAULT 0,
  category_verdict TEXT, correct_category TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (firm_row_id, reviewer));
CREATE TABLE IF NOT EXISTS watchlist (
  firm_row_id TEXT NOT NULL, reviewer TEXT NOT NULL, decision TEXT, note_supports TEXT, reason TEXT,
  updated_at TEXT NOT NULL, PRIMARY KEY (firm_row_id, reviewer));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, reviewer TEXT, action TEXT NOT NULL, detail TEXT);
"""

RECORD_KINDS = {"mention", "detail", "description", "action", "unclear"}
ENTITY_TYPES = {"person", "organization", "location", "other", "unknown"}
MENTION_FORMS = {"name", "alias", "pronoun", "description"}
DETAIL_FIELDS = {"address", "city", "state", "zip_code", "phone", "TIN", "other"}
CATEGORY_VERDICTS = {"right", "wrong", "unknown"}
WATCH_DECISIONS = {"same", "different", "cant_tell"}
SUPPORT = {"yes", "no", "partly"}


class UserError(ValueError):
    """A problem the reviewer can fix; its message is shown to them as-is."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    # -- plumbing ---------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def tx(self):
        store = self

        class _Tx:
            def __enter__(self):
                store.lock.acquire()
                store.db.execute("BEGIN IMMEDIATE")
                return store.db

            def __exit__(self, exc_type, *_):
                try:
                    store.db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store.lock.release()
                return False
        return _Tx()

    def log(self, reviewer: str | None, action: str, detail: dict | str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(at, reviewer, action, detail) VALUES (?,?,?,?)",
                            (now(), reviewer, action, json.dumps(detail) if not isinstance(detail, str) else detail))

    # -- notes and per-reviewer work ---------------------------------------
    def sync_notes(self, notes) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM notes")
            db.executemany("INSERT INTO notes(claim, note, path, practice) VALUES (?,?,?,?)",
                           [(n.claim, n.note, str(n.path), int(n.practice)) for n in notes])

    def note_row(self, claim: str, note: str) -> dict:
        row = self.one("SELECT * FROM notes WHERE claim=? AND note=?", (claim, note))
        if row is None:
            raise UserError(f"Claim {claim} note {note} isn't in the notes folder.")
        return row

    def work(self, claim: str, note: str, reviewer: str) -> dict:
        row = self.one("SELECT * FROM note_work WHERE claim=? AND note=? AND reviewer=?", (claim, note, reviewer))
        return row or {"claim": claim, "note": note, "reviewer": reviewer, "status": "not_started",
                       "blind": 0, "fingerprint": None, "opened_at": None, "completed_at": None}

    def _ensure_work(self, db, claim: str, note: str, reviewer: str) -> None:
        db.execute("INSERT OR IGNORE INTO note_work(claim, note, reviewer) VALUES (?,?,?)", (claim, note, reviewer))

    def open_note(self, claim: str, note: str, reviewer: str, sha: str) -> bool:
        """Record first opening and the note's fingerprint. False if the file changed after work began."""
        with self.tx() as db:
            self._ensure_work(db, claim, note, reviewer)
            row = db.execute("SELECT * FROM note_work WHERE claim=? AND note=? AND reviewer=?",
                             (claim, note, reviewer)).fetchone()
            has_work = db.execute("SELECT 1 FROM records WHERE claim=? AND note=? AND reviewer=? LIMIT 1",
                                  (claim, note, reviewer)).fetchone() is not None
            if row["opened_at"] is None:
                db.execute("UPDATE note_work SET opened_at=? WHERE claim=? AND note=? AND reviewer=?",
                           (now(), claim, note, reviewer))
            if row["status"] == "not_started":
                db.execute("UPDATE note_work SET status='in_progress' WHERE claim=? AND note=? AND reviewer=?",
                           (claim, note, reviewer))
            if row["fingerprint"] is None or not has_work:
                db.execute("UPDATE note_work SET fingerprint=? WHERE claim=? AND note=? AND reviewer=?",
                           (sha, claim, note, reviewer))
                return True
            return row["fingerprint"] == sha

    def set_status(self, claim: str, note: str, reviewer: str, status: str) -> None:
        with self.tx() as db:
            self._ensure_work(db, claim, note, reviewer)
            db.execute("UPDATE note_work SET status=?, completed_at=? WHERE claim=? AND note=? AND reviewer=?",
                       (status, now() if status == "complete" else None, claim, note, reviewer))

    def set_blind(self, claim: str, note: str, reviewer: str, blind: bool) -> None:
        with self.tx() as db:
            self._ensure_work(db, claim, note, reviewer)
            db.execute("UPDATE note_work SET blind=? WHERE claim=? AND note=? AND reviewer=?",
                       (int(blind), claim, note, reviewer))

    def sealed(self, claim: str, reviewer: str) -> str | None:
        row = self.one("SELECT sealed_at FROM claim_seal WHERE claim=? AND reviewer=?", (claim, reviewer))
        return row["sealed_at"] if row else None

    def seal(self, claim: str, reviewer: str) -> None:
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO claim_seal(claim, reviewer, sealed_at) VALUES (?,?,?)",
                       (claim, reviewer, now()))

    # -- entities ------------------------------------------------------------
    def entities(self, claim: str, reviewer: str) -> list[dict]:
        return self.q("SELECT * FROM entities WHERE claim=? AND reviewer=? AND retired=0 ORDER BY number",
                      (claim, reviewer))

    def entity(self, entity_id: str) -> dict:
        row = self.one("SELECT * FROM entities WHERE id=?", (entity_id,))
        if row is None or row["retired"]:
            raise UserError("That person or company no longer exists.")
        return row

    def entity_by_number(self, claim: str, reviewer: str, number: int) -> dict | None:
        return self.one("SELECT * FROM entities WHERE claim=? AND reviewer=? AND number=? AND retired=0",
                        (claim, reviewer, number))

    def create_entity(self, *, claim: str, note: str, reviewer: str, start: int, end: int, quote: str,
                      label: str, type: str, source: str = "manual", draft_id: str | None = None) -> tuple[str, str]:
        label = (label or quote).strip()
        if type not in ENTITY_TYPES:
            raise UserError("Choose whether this is a person, an organization, a location, other, or unknown.")
        if not label:
            raise UserError("Give the person or company a name.")
        with self.tx() as db:
            number = db.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM entities WHERE claim=? AND reviewer=?",
                                (claim, reviewer)).fetchone()[0]
            entity_id = new_id("E")
            after = int(self.sealed(claim, reviewer) is not None)
            db.execute("INSERT INTO entities(id, claim, reviewer, number, label, type, created_at, after_seal) "
                       "VALUES (?,?,?,?,?,?,?,?)", (entity_id, claim, reviewer, number, label, type, now(), after))
            uid = self._insert_record(db, uid=None, revision=1, kind="mention", claim=claim, note=note,
                                      reviewer=reviewer, start=start, end=end, quote=quote,
                                      entity_id=entity_id, form="name", is_first=1, source=source,
                                      draft_id=draft_id)
        self.log(reviewer, "entity.create", {"entity": entity_id, "claim": claim, "note": note})
        return entity_id, uid

    def update_entity(self, entity_id: str, reviewer: str, label: str, type: str) -> None:
        ent = self.entity(entity_id)
        if ent["reviewer"] != reviewer:
            raise UserError("You can only edit your own records.")
        if type not in ENTITY_TYPES or not label.strip():
            raise UserError("A name and a type are both needed.")
        with self.tx() as db:
            db.execute("UPDATE entities SET label=?, type=? WHERE id=?", (label.strip(), type, entity_id))
        self.log(reviewer, "entity.update", {"entity": entity_id})

    def delete_entity(self, entity_id: str, reviewer: str) -> None:
        ent = self.entity(entity_id)
        if ent["reviewer"] != reviewer:
            raise UserError("You can only delete your own records.")
        deps = [r for r in self.current_records(claim=ent["claim"], reviewer=reviewer)
                if (r["entity_id"] == entity_id and not r["is_first"]) or r["entity2_id"] == entity_id]
        if deps:
            raise UserError(f"{ent['label']} still has {len(deps)} record(s) pointing to them. "
                            f"Delete or re-link those first.")
        with self.tx() as db:
            for r in self.current_records(claim=ent["claim"], reviewer=reviewer):
                if r["entity_id"] == entity_id and r["is_first"]:
                    self._retire(db, r)
            db.execute("UPDATE entities SET retired=1 WHERE id=?", (entity_id,))
        self.log(reviewer, "entity.delete", {"entity": entity_id})

    # -- records -------------------------------------------------------------
    def _insert_record(self, db, *, uid, revision, kind, claim, note, reviewer, start, end, quote,
                       entity_id=None, entity2_id=None, form=None, field=None, value=None, label=None,
                       reason=None, is_first=0, source="manual", draft_id=None, state="accepted") -> str:
        uid = uid or new_id("R")
        after = int(self.sealed(claim, reviewer) is not None)
        db.execute(
            "INSERT INTO records(uid, revision, state, kind, claim, note, reviewer, start, end, quote, entity_id, "
            "entity2_id, form, field, value, label, reason, is_first, source, draft_id, after_seal, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, revision, state, kind, claim, note, reviewer, start, end, quote, entity_id, entity2_id, form,
             field, value, label, reason, is_first, source, draft_id, after, now()))
        return uid

    def _retire(self, db, row: dict) -> None:
        cols = {k: row[k] for k in ("kind", "claim", "note", "reviewer", "start", "end", "quote", "entity_id",
                                    "entity2_id", "form", "field", "value", "label", "reason", "is_first",
                                    "source", "draft_id")}
        self._insert_record(db, uid=row["uid"], revision=row["revision"] + 1, state="retired", **cols)

    def current_records(self, *, claim: str | None = None, note: str | None = None,
                        reviewer: str | None = None) -> list[dict]:
        where, args = ["r.state='accepted'"], []
        for col, val in (("claim", claim), ("note", note), ("reviewer", reviewer)):
            if val is not None:
                where.append(f"r.{col}=?")
                args.append(val)
        sql = ("SELECT r.* FROM records r JOIN (SELECT uid, MAX(revision) AS rev FROM records GROUP BY uid) m "
               "ON r.uid=m.uid AND r.revision=m.rev WHERE " + " AND ".join(where) + " ORDER BY r.start, r.end")
        return self.q(sql, tuple(args))

    def record(self, uid: str) -> dict:
        row = self.one("SELECT * FROM records WHERE uid=? ORDER BY revision DESC LIMIT 1", (uid,))
        if row is None or row["state"] != "accepted":
            raise UserError("That record no longer exists.")
        return row

    def validate(self, kind: str, fields: dict, claim: str, reviewer: str) -> dict:
        """Check a record's fields; returns the cleaned fields or raises UserError."""
        if kind not in RECORD_KINDS:
            raise UserError("Unknown kind of record.")
        clean = {k: (fields.get(k) or None) for k in ("entity_id", "entity2_id", "form", "field", "value",
                                                       "label", "reason")}
        for k in ("value", "label", "reason"):
            if clean[k] is not None:
                clean[k] = str(clean[k]).strip() or None
        if kind in {"mention", "detail", "description", "action"} and not clean["entity_id"]:
            raise UserError("Choose which person or company this belongs to.")
        for key in ("entity_id", "entity2_id"):
            if clean[key]:
                ent = self.entity(clean[key])
                if ent["claim"] != claim or ent["reviewer"] != reviewer:
                    raise UserError("That person or company belongs to a different claim.")
        if kind == "unclear" and clean["entity_id"]:
            self.entity(clean["entity_id"])
        if kind == "mention":
            if clean["form"] not in MENTION_FORMS:
                raise UserError("Choose how the note refers to them: name, alias, pronoun or description.")
        else:
            clean["form"] = None
        if kind == "detail":
            if clean["field"] not in DETAIL_FIELDS:
                raise UserError("Choose what kind of detail this is.")
            if not clean["value"]:
                raise UserError("Enter the detail's value exactly as the note states it.")
        else:
            clean["field"] = None
            if kind != "detail":
                clean["value"] = None
        if kind == "unclear" and not clean["reason"]:
            raise UserError("Say why this can't be linked confidently. A short reason is enough.")
        if kind != "action":
            clean["entity2_id"] = None
        if kind == "action" and clean["entity2_id"] == clean["entity_id"]:
            raise UserError("The second party must be someone different.")
        return clean

    def _check_span(self, text: str, start: int, end: int) -> str:
        if not (isinstance(start, int) and isinstance(end, int)) or not (0 <= start < end <= len(text)):
            raise UserError("Select some words in the note first.")
        quote = text[start:end]
        if not quote.strip():
            raise UserError("The selection is only spaces. Select some words.")
        return quote

    def add_record(self, *, kind: str, claim: str, note: str, reviewer: str, text: str, start: int, end: int,
                   fields: dict, source: str = "manual", draft_id: str | None = None) -> str:
        quote = self._check_span(text, start, end)
        clean = self.validate(kind, fields, claim, reviewer)
        dup = self.find_identical(claim, note, reviewer, kind, start, end, clean)
        if dup:
            raise UserError("You've already recorded exactly this. Open it from the records list to change it.")
        with self.tx() as db:
            uid = self._insert_record(db, uid=None, revision=1, kind=kind, claim=claim, note=note,
                                      reviewer=reviewer, start=start, end=end, quote=quote, source=source,
                                      draft_id=draft_id, **clean)
        self.log(reviewer, "record.add", {"uid": uid, "kind": kind})
        return uid

    def update_record(self, uid: str, reviewer: str, text: str, fields: dict,
                      start: int | None = None, end: int | None = None) -> str:
        row = self.record(uid)
        if row["reviewer"] != reviewer:
            raise UserError("You can only edit your own records.")
        start = row["start"] if start is None else start
        end = row["end"] if end is None else end
        quote = self._check_span(text, start, end)
        merged = {k: row[k] for k in ("entity_id", "entity2_id", "form", "field", "value", "label", "reason")}
        merged.update({k: v for k, v in fields.items() if k in merged})
        clean = self.validate(row["kind"], merged, row["claim"], reviewer)
        if row["is_first"]:
            clean["form"] = "name"
        with self.tx() as db:
            self._insert_record(db, uid=uid, revision=row["revision"] + 1, kind=row["kind"], claim=row["claim"],
                                note=row["note"], reviewer=reviewer, start=start, end=end, quote=quote,
                                is_first=row["is_first"], source=row["source"], draft_id=row["draft_id"], **clean)
        self.log(reviewer, "record.update", {"uid": uid})
        return uid

    def delete_record(self, uid: str, reviewer: str) -> None:
        row = self.record(uid)
        if row["reviewer"] != reviewer:
            raise UserError("You can only delete your own records.")
        if row["is_first"]:
            raise UserError("This is where the person or company was first named. Delete them from the "
                            "people and companies list instead.")
        with self.tx() as db:
            self._retire(db, row)
        self.log(reviewer, "record.delete", {"uid": uid})

    def find_identical(self, claim, note, reviewer, kind, start, end, fields) -> str | None:
        for r in self.current_records(claim=claim, note=note, reviewer=reviewer):
            if r["kind"] != kind or r["start"] != start or r["end"] != end:
                continue
            if kind == "detail" and r["field"] != fields.get("field"):
                continue
            if kind in {"mention", "detail", "description", "action"} and r["entity_id"] != fields.get("entity_id"):
                continue
            if kind == "action" and r["entity2_id"] != fields.get("entity2_id"):
                continue
            return r["uid"]
        return None

    def history(self, uid: str) -> list[dict]:
        return self.q("SELECT * FROM records WHERE uid=? ORDER BY revision", (uid,))

    # -- AI runs and drafts ---------------------------------------------------
    def create_run(self, *, claim, note, reviewer, raw, report: dict, prompt_version: str) -> str:
        run_id = new_id("RUN")
        with self.tx() as db:
            db.execute("INSERT INTO runs(id, claim, note, reviewer, created_at, raw, report, prompt_version) "
                       "VALUES (?,?,?,?,?,?,?,?)", (run_id, claim, note, reviewer, now(), raw,
                                                    json.dumps({k: v for k, v in report.items() if k != 'drafts'}),
                                                    prompt_version))
            for d in report["drafts"]:
                db.execute(
                    "INSERT INTO drafts(id, run_id, claim, note, reviewer, seq, type, key, key2, quote, start, end, "
                    "match, candidates, fields, problems, notes, status, duplicate_of, raw) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("D"), run_id, claim, note, reviewer, d["seq"], d["type"], d["key"], d["key2"],
                     d["quote"], d["start"], d["end"], d["match"], json.dumps(d["candidates"]),
                     json.dumps(d["fields"]), json.dumps(d["problems"]), json.dumps(d["notes"]),
                     d["status"], d["duplicate_of"], d["raw"]))
        self.log(reviewer, "ai.import", {"run": run_id, "claim": claim, "note": note,
                                         "drafts": len(report["drafts"])})
        return run_id

    def drafts(self, claim: str, note: str, reviewer: str) -> list[dict]:
        rows = self.q("SELECT * FROM drafts WHERE claim=? AND note=? AND reviewer=? ORDER BY "
                      "CASE WHEN start IS NULL THEN 1 ELSE 0 END, start, "
                      "CASE type WHEN 'entity' THEN 0 ELSE 1 END, seq", (claim, note, reviewer))
        for r in rows:
            for k in ("candidates", "fields", "problems", "notes"):
                r[k] = json.loads(r[k]) if r[k] else ([] if k != "fields" else {})
        return rows

    def draft(self, draft_id: str) -> dict:
        row = self.one("SELECT * FROM drafts WHERE id=?", (draft_id,))
        if row is None:
            raise UserError("That AI draft no longer exists.")
        for k in ("candidates", "fields", "problems", "notes"):
            row[k] = json.loads(row[k]) if row[k] else ([] if k != "fields" else {})
        return row

    def update_draft(self, draft_id: str, **cols) -> None:
        sets, args = [], []
        for k, v in cols.items():
            sets.append(f"{k}=?")
            args.append(json.dumps(v) if k in ("candidates", "fields", "problems", "notes") else v)
        with self.tx() as db:
            db.execute(f"UPDATE drafts SET {', '.join(sets)} WHERE id=?", (*args, draft_id))

    def run_key(self, run_id: str, key: str) -> str | None:
        row = self.one("SELECT entity_id FROM run_keys WHERE run_id=? AND key=?", (run_id, key.upper()))
        return row["entity_id"] if row else None

    def set_run_key(self, run_id: str, key: str, entity_id: str) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO run_keys(run_id, key, entity_id) VALUES (?,?,?)",
                       (run_id, key.upper(), entity_id))

    # -- firm output, pairing, watchlist --------------------------------------
    def load_firm_rows(self, rows: list[dict], source: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM firm_rows")
            db.executemany("INSERT INTO firm_rows(id, claim, seq, data, source) VALUES (?,?,?,?,?)",
                           [(r["id"], r["claim"], r["seq"], json.dumps(r["data"]), source) for r in rows])

    def firm_rows(self, claim: str | None = None) -> list[dict]:
        rows = self.q("SELECT * FROM firm_rows" + (" WHERE claim=?" if claim else "") + " ORDER BY claim, seq",
                      (claim,) if claim else ())
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    def pairings(self, reviewer: str | None = None) -> dict[str, dict]:
        rows = self.q("SELECT * FROM pairings" + (" WHERE reviewer=?" if reviewer else ""),
                      (reviewer,) if reviewer else ())
        return {f"{r['firm_row_id']}|{r['reviewer']}": r for r in rows}

    def save_pairing(self, firm_row_id: str, reviewer: str, *, entity_id: str | None, not_in_notes: bool,
                     category_verdict: str | None, correct_category: str | None) -> None:
        if category_verdict and category_verdict not in CATEGORY_VERDICTS:
            raise UserError("Choose right, wrong, or the notes don't say.")
        if entity_id:
            self.entity(entity_id)
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO pairings(firm_row_id, reviewer, entity_id, not_in_notes, "
                       "category_verdict, correct_category, updated_at) VALUES (?,?,?,?,?,?,?)",
                       (firm_row_id, reviewer, entity_id, int(not_in_notes), category_verdict,
                        (correct_category or "").strip() or None, now()))
        self.log(reviewer, "pairing.save", {"row": firm_row_id})

    def watchlist(self, reviewer: str | None = None) -> dict[str, dict]:
        rows = self.q("SELECT * FROM watchlist" + (" WHERE reviewer=?" if reviewer else ""),
                      (reviewer,) if reviewer else ())
        return {f"{r['firm_row_id']}|{r['reviewer']}": r for r in rows}

    def save_watchlist(self, firm_row_id: str, reviewer: str, *, decision: str | None,
                       note_supports: str | None, reason: str | None) -> None:
        if decision and decision not in WATCH_DECISIONS:
            raise UserError("Choose same, different, or can't tell.")
        if note_supports and note_supports not in SUPPORT:
            raise UserError("Choose yes, no, or partly.")
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO watchlist(firm_row_id, reviewer, decision, note_supports, reason, "
                       "updated_at) VALUES (?,?,?,?,?,?)",
                       (firm_row_id, reviewer, decision, note_supports, (reason or "").strip() or None, now()))
        self.log(reviewer, "watchlist.save", {"row": firm_row_id})

    def reviewers(self) -> list[str]:
        rows = self.q("SELECT DISTINCT reviewer FROM note_work UNION SELECT DISTINCT reviewer FROM records "
                      "ORDER BY 1")
        return [r["reviewer"] for r in rows if r["reviewer"]]
