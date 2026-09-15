"""The HTTP server: a JSON API plus the static browser app. Standard library only.

Binds to localhost unless told otherwise. There are no logins: the reviewer
name is whatever the browser sends. Fine on one machine; a shared deployment
needs the firm's IT to put authentication in front of it.
"""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import PROMPT_VERSION, ai_import, copilot, export, firm, notes, scoring, review, undo, completion
from .store import Store, UserError, now

STATIC = Path(__file__).resolve().parent.parent / "static"
EXISTING_KEY = re.compile(r"^E(\d+)$", re.IGNORECASE)
DEFAULT_CATEGORIES = ["medical provider", "legal", "claimant", "financier", "repair shop", "witness"]


@dataclass
class Config:
    notes_dir: Path | None
    firm_files: list[Path]
    part_size: int = 12000
    skipped: list[str] = field(default_factory=list)
    firm_warnings: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    taxonomy: dict = field(default_factory=review.load_taxonomy)


class App:
    def __init__(self, store: Store, config: Config):
        self.store = store
        self.config = config
        self.store.db.executescript(review.SCHEMA)
        had_undo = self.store.one("SELECT name FROM sqlite_master WHERE type='table' AND name='undo_actions'")
        self.store.db.executescript(undo.SCHEMA)
        self.store.db.executescript(completion.SCHEMA)
        if not had_undo:
            undo.seed_legacy(self)
        self.reload()

    # -- setup ---------------------------------------------------------------
    def reload(self) -> None:
        found, skipped = notes.discover(self.config.notes_dir)
        self.store.sync_notes(found)
        self.config.skipped = skipped
        practice_firm = notes.PRACTICE_DIR / "PRACTICE_firm.csv"
        rows, warnings, source = firm.load([practice_firm, *self.config.firm_files])
        self.store.load_firm_rows(rows, source)
        self.config.firm_warnings = warnings
        self.config.categories = [c["name"] for c in self.config.taxonomy["categories"]]

    # -- helpers -------------------------------------------------------------
    def text(self, claim: str, note: str) -> notes.NoteText:
        row = self.store.note_row(claim, note)
        path = Path(row["path"])
        if not path.exists():
            raise UserError(f"The file for claim {claim} note {note} is missing: {path}")
        try:
            return notes.read(path)
        except UnicodeDecodeError as exc:
            raise UserError(f"Claim {claim} note {note} isn't valid UTF-8 ({exc.reason} at byte {exc.start}). "
                            f"Ask the coordinator to re-save it as UTF-8.") from exc

    def checked_text(self, claim: str, note: str, reviewer: str) -> str:
        nt = self.text(claim, note)
        if not self.store.open_note(claim, note, reviewer, nt.sha256):
            raise UserError("This note's file has changed since you started annotating it, so saved positions "
                            "may no longer line up. Nothing was saved. Tell your coordinator.")
        return nt.text

    @staticmethod
    def reviewer(data: dict) -> str:
        name = str(data.get("reviewer") or "").strip()
        if not name:
            raise UserError("Enter your name first (top right).")
        if len(name) > 80:
            raise UserError("That name is too long.")
        return name

    def entity_view(self, claim: str, reviewer: str, note: str | None = None) -> list[dict]:
        ents = self.store.entities(claim, reviewer)
        records = self.store.current_records(claim=claim, reviewer=reviewer)
        for e in ents:
            mine = [r for r in records if r["entity_id"] == e["id"] or r["entity2_id"] == e["id"]]
            e["count"] = len(mine)
            e["in_note"] = sum(1 for r in mine if r["note"] == note) if note else None
            e["details"] = [{"field": r["field"], "value": r["value"]} for r in mine if r["kind"] == "detail"]
            e["descriptions"] = sorted({r["quote"] for r in mine if r["kind"] == "description"})
        return ents

    # -- read endpoints --------------------------------------------------------
    def bootstrap(self, q: dict) -> dict:
        return {
            "reviewers": self.store.reviewers(),
            "part_size": self.config.part_size,
            "categories": self.config.categories,
            "prompt_version": PROMPT_VERSION,
            "skipped": self.config.skipped,
            "firm_warnings": self.config.firm_warnings,
            "notes_dir": str(self.config.notes_dir) if self.config.notes_dir else None,
        }

    def claims(self, q: dict) -> dict:
        reviewer = q.get("reviewer", "")
        rows = self.store.q("SELECT * FROM notes ORDER BY practice DESC, claim")
        work = {(w["claim"], w["note"]): w for w in self.store.q("SELECT * FROM note_work WHERE reviewer=?", (reviewer,))}
        rec_counts = {(r["claim"], r["note"]): r["n"] for r in self.store.q(
            "SELECT r.claim, r.note, COUNT(*) AS n FROM records r JOIN (SELECT uid, MAX(revision) rev FROM records "
            "GROUP BY uid) m ON r.uid=m.uid AND r.revision=m.rev WHERE r.state='accepted' AND r.reviewer=? "
            "GROUP BY r.claim, r.note", (reviewer,))}
        pending = {(d["claim"], d["note"]): d["n"] for d in self.store.q(
            "SELECT claim, note, COUNT(*) AS n FROM drafts WHERE reviewer=? AND status IN ('ready','needs_attention') "
            "GROUP BY claim, note", (reviewer,))}
        firm_counts = {r["claim"]: r["n"] for r in self.store.q("SELECT claim, COUNT(*) AS n FROM firm_rows GROUP BY claim")}
        claims: dict[str, dict] = {}
        for r in rows:
            c = claims.setdefault(r["claim"], {"claim": r["claim"], "practice": bool(r["practice"]), "notes": [],
                                                "sealed": self.store.sealed(r["claim"], reviewer) if reviewer else None,
                                                "firm_rows": firm_counts.get(r["claim"], 0)})
            w = work.get((r["claim"], r["note"]), {})
            c["notes"].append({"note": r["note"], "status": w.get("status", "not_started"),
                               "blind": bool(w.get("blind", 0)), "records": rec_counts.get((r["claim"], r["note"]), 0),
                               "pending": pending.get((r["claim"], r["note"]), 0)})
        out = list(claims.values())
        for c in out:
            c["notes"].sort(key=lambda n: notes._natural(n["note"]))
            c["complete"] = sum(1 for n in c["notes"] if n["status"] == "complete")
        return {"claims": out}

    def note(self, q: dict) -> dict:
        claim, note, reviewer = q.get("claim", ""), q.get("note", ""), self.reviewer(q)
        nt = self.text(claim, note)
        ok = self.store.open_note(claim, note, reviewer, nt.sha256)
        work = self.store.work(claim, note, reviewer)
        ents = self.entity_view(claim, reviewer, note)
        drafts = self.store.drafts(claim, note, reviewer)
        labels = {e["label"].casefold(): e for e in ents}
        for d in drafts:
            if d["type"] == "entity" and d["status"] in {"ready", "needs_attention"}:
                name = (d["fields"].get("name") or d["quote"] or "").casefold()
                match = labels.get(name) or labels.get((d["quote"] or "").casefold())
                d["suggest_link"] = match["id"] if match else None
            d["resolved"] = self.resolve_keys(d)
        return {
            "claim": claim, "note": note, "text": nt.text, "length": len(nt.text), "fingerprint_ok": ok, "source_fingerprint": nt.sha256,
            "status": work["status"], "blind": bool(work["blind"]), "sealed": self.store.sealed(claim, reviewer),
            "entities": ents, "records": self.store.current_records(claim=claim, note=note, reviewer=reviewer),
            "drafts": drafts, "parts": [list(p) for p in ai_import.split_parts(nt.text, self.config.part_size)],
        }

    def resolve_keys(self, d: dict) -> dict:
        out = {}
        for attr in ("key", "key2"):
            ref = d.get(attr)
            if not ref:
                continue
            m = EXISTING_KEY.match(ref.upper())
            if m:
                ent = self.store.entity_by_number(d["claim"], d["reviewer"], int(m.group(1)))
                out[attr] = ent["id"] if ent else None
            else:
                out[attr] = self.store.run_key(d["run_id"], ref)
        return out

    def history(self, q: dict) -> dict:
        return {"history": self.store.history(q.get("uid", ""))}

    def ai_message(self, q: dict) -> dict:
        claim, note, reviewer = q.get("claim", ""), q.get("note", ""), self.reviewer(q)
        nt = self.text(claim, note)
        return copilot.build_message(claim=claim, note=note, text=nt.text,
                                     entities=self.store.entities(claim, reviewer),
                                     part=int(q.get("part") or 1), part_size=self.config.part_size,
                                     include_instructions=q.get("full") == "1")

    def instructions(self, q: dict) -> dict:
        text = copilot.instructions()
        return {"instructions": text, "chars": len(text), "version": PROMPT_VERSION}

    def compare(self, q: dict) -> dict:
        claim, reviewer = q.get("claim", ""), self.reviewer(q)
        if not self.store.sealed(claim, reviewer):
            raise UserError("Finish every note in this claim first. The firm's output stays hidden until then, "
                            "so your answer key isn't influenced by it.")
        pairings, watch = self.store.pairings(reviewer), self.store.watchlist(reviewer)
        rows = []
        for r in self.store.firm_rows(claim):
            d = r["data"]
            cited = firm.cited_notes(d)
            rows.append({"id": r["id"], "data": d, "flagged": firm.is_flagged(d),
                         "cited": sorted(set(cited)),
                         "pairing": pairings.get(f"{r['id']}|{reviewer}"),
                         "watchlist": watch.get(f"{r['id']}|{reviewer}")})
        frozen = review.checkpoint(self.store, claim, reviewer)
        entities = frozen["entities"] if frozen else self.entity_view(claim, reviewer)
        if frozen:
            for e in entities:
                e["details"] = [{"field": r["field"], "value": r["value"]} for r in e["records"] if r["kind"] == "detail"]
                e["descriptions"] = [r["quote"] for r in e["records"] if r["kind"] == "description"]
        return {"claim": claim, "rows": rows, "entities": entities, "independent": bool(frozen),
                "comparison": completion.status(self.store, claim, reviewer),
                "categories": self.config.categories,
                "notes": [n["note"] for n in self.store.q("SELECT note FROM notes WHERE claim=?", (claim,))]}

    def scores(self, q: dict) -> dict:
        reviewer = self.reviewer(q)
        return scoring.score(self.store, reviewer, include_practice=q.get("practice") == "1")

    # -- write endpoints -------------------------------------------------------
    @undo.journal
    def entity_create(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        text = self.checked_text(d["claim"], d["note"], reviewer)
        start, end = int(d["start"]), int(d["end"])
        quote = self.store._check_span(text, start, end)
        entity_id, uid = self.store.create_entity(claim=d["claim"], note=d["note"], reviewer=reviewer, start=start,
                                                  end=end, quote=quote, label=d.get("label") or quote,
                                                  type=d.get("type") or "unknown")
        return {"entity_id": entity_id, "uid": uid}

    @undo.journal
    def entity_update(self, d: dict) -> dict:
        self.store.update_entity(d["id"], self.reviewer(d), d.get("label", ""), d.get("type", ""))
        return {"ok": True}

    @undo.journal
    def entity_delete(self, d: dict) -> dict:
        self.store.delete_entity(d["id"], self.reviewer(d))
        return {"ok": True}

    @undo.journal
    def record_create(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        text = self.checked_text(d["claim"], d["note"], reviewer)
        uid = self.store.add_record(kind=d["kind"], claim=d["claim"], note=d["note"], reviewer=reviewer, text=text,
                                    start=int(d["start"]), end=int(d["end"]), fields=d.get("fields") or {})
        return {"uid": uid}

    @undo.journal
    def record_update(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        row = self.store.record(d["uid"])
        text = self.checked_text(row["claim"], row["note"], reviewer)
        start = int(d["start"]) if d.get("start") is not None else None
        end = int(d["end"]) if d.get("end") is not None else None
        self.store.update_record(d["uid"], reviewer, text, d.get("fields") or {}, start, end)
        return {"uid": d["uid"]}

    @undo.journal
    def record_delete(self, d: dict) -> dict:
        self.store.delete_record(d["uid"], self.reviewer(d))
        return {"ok": True}

    def ai_preview(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        report = self._read(d, reviewer)
        return report.to_dict()

    def _read(self, d: dict, reviewer: str):
        claim, note = d["claim"], d["note"]
        if self.store.work(claim, note, reviewer)["blind"]:
            raise UserError("This note is set to be annotated without AI drafts.")
        text = self.text(claim, note).text
        existing = {e["number"]: e["id"] for e in self.store.entities(claim, reviewer)}

        mine = self.store.current_records(claim=claim, note=note, reviewer=reviewer)

        def already(kind, start, end, fields):
            """Identical work the SME already has: same words, same kind (and same detail kind)."""
            want = "mention" if kind == "entity" else kind
            for r in mine:
                if r["kind"] != want or r["start"] != start or r["end"] != end:
                    continue
                if want == "detail" and r["field"] != fields.get("field"):
                    continue
                return r["uid"]
            return None

        return ai_import.read_answer(d.get("answer") or "", text, claim=claim, note=note,
                                     existing_entities=existing, part_size=self.config.part_size,
                                     already_recorded=already)

    def ai_import(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        report = self._read(d, reviewer)
        if report.errors or not report.drafts:
            raise UserError(" ".join(report.errors) or "Nothing to import.")
        self.checked_text(d["claim"], d["note"], reviewer)
        run_id = self.store.create_run(claim=d["claim"], note=d["note"], reviewer=reviewer, raw=d["answer"],
                                       report=report.to_dict(), prompt_version=PROMPT_VERSION)
        # An entity draft that duplicates the SME's own work hands its key to that entity,
        # so everything Copilot attached to the key links up without the SME re-picking it.
        for draft in self.store.q("SELECT key, duplicate_of FROM drafts WHERE run_id=? AND type='entity' "
                                  "AND status='duplicate' AND key IS NOT NULL AND duplicate_of LIKE 'R-%'",
                                  (run_id,)):
            existing = self.store.one("SELECT entity_id FROM records WHERE uid=? ORDER BY revision DESC LIMIT 1",
                                      (draft["duplicate_of"],))
            if existing and existing["entity_id"]:
                self.store.set_run_key(run_id, draft["key"], existing["entity_id"])
        return {"run_id": run_id, "counts": report.counts()}

    def draft_span(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        draft = self.store.draft(d["id"])
        if draft["reviewer"] != reviewer:
            raise UserError("That draft belongs to someone else.")
        text = self.checked_text(draft["claim"], draft["note"], reviewer)
        start, end = int(d["start"]), int(d["end"])
        quote = self.store._check_span(text, start, end)
        problems = [p for p in draft["problems"] if p["code"] not in {"not_found", "ambiguous", "no_quote"}]
        self.store.update_draft(d["id"], start=start, end=end, quote=quote, match="chosen by SME",
                                problems=problems, status="needs_attention" if problems else "ready")
        return {"ok": True}

    @undo.journal
    def draft_dismiss(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        draft = self.store.draft(d["id"])
        if draft["reviewer"] != reviewer:
            raise UserError("That draft belongs to someone else.")
        self.store.update_draft(d["id"], status="dismissed", decided_at=now())
        self.store.log(reviewer, "draft.dismiss", {"draft": d["id"]})
        return {"ok": True}

    @undo.journal
    def draft_accept(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        draft = self.store.draft(d["id"])
        if draft["reviewer"] != reviewer:
            raise UserError("That draft belongs to someone else.")
        if draft["status"] not in {"ready", "needs_attention"}:
            raise UserError("This draft has already been decided.")
        text = self.checked_text(draft["claim"], draft["note"], reviewer)
        start = int(d["start"]) if d.get("start") is not None else draft["start"]
        end = int(d["end"]) if d.get("end") is not None else draft["end"]
        if start is None or end is None:
            raise UserError("Select the right words in the note for this draft first.")
        quote = self.store._check_span(text, start, end)
        proposed = draft["fields"]
        final = {**proposed, **(d.get("fields") or {})}
        claim, note, run = draft["claim"], draft["note"], draft["run_id"]
        resolved = self.resolve_keys(draft)

        if draft["type"] == "entity":
            link_to = d.get("link_entity_id")
            if link_to:
                uid = self.store.add_record(kind="mention", claim=claim, note=note, reviewer=reviewer, text=text,
                                            start=start, end=end, fields={"entity_id": link_to, "form": "name"},
                                            source="ai", draft_id=draft["id"])
                entity_id = link_to
            else:
                entity_id, uid = self.store.create_entity(claim=claim, note=note, reviewer=reviewer, start=start,
                                                          end=end, quote=quote, label=final.get("name") or quote,
                                                          type=final.get("kind") or "unknown", source="ai",
                                                          draft_id=draft["id"])
            if draft["key"]:
                self.store.set_run_key(run, draft["key"], entity_id)
        else:
            entity_id = d.get("entity_id") or resolved.get("key")
            entity2 = d.get("entity2_id") if "entity2_id" in d else resolved.get("key2")
            if draft["type"] != "unclear" and not entity_id:
                blocker = self.store.one("SELECT id FROM drafts WHERE run_id=? AND type='entity' AND UPPER(key)=? "
                                         "AND status IN ('ready','needs_attention')",
                                         (run, (draft["key"] or "").upper()))
                if blocker:
                    raise UserError(f"NEEDS_ENTITY:{blocker['id']}:Accept or link {draft['key']} first — this "
                                    f"draft points to that person or company.")
                raise UserError("Choose which person or company this belongs to.")
            kind = {"mention": "mention", "detail": "detail", "description": "description",
                    "action": "action", "unclear": "unclear"}[draft["type"]]
            fields = {"entity_id": entity_id, "entity2_id": entity2, "form": final.get("form"),
                      "field": final.get("field"), "value": final.get("value"), "label": final.get("label"),
                      "reason": final.get("reason")}
            if kind == "unclear":
                fields["entity_id"] = d.get("entity_id") or None
            uid = self.store.add_record(kind=kind, claim=claim, note=note, reviewer=reviewer, text=text, start=start,
                                        end=end, fields=fields, source="ai", draft_id=draft["id"])

        edited = int(start != draft["start"] or end != draft["end"] or bool(d.get("link_entity_id"))
                     or any(str(final.get(k) or "") != str(proposed.get(k) or "")
                            for k in ("name", "kind", "form", "field", "value", "label", "reason"))
                     or (draft["type"] not in {"entity", "unclear"}
                         and d.get("entity_id") not in (None, resolved.get("key"))))
        self.store.update_draft(d["id"], status="accepted", outcome_uid=uid, edited=edited, decided_at=now())
        self.store.log(reviewer, "draft.accept", {"draft": d["id"], "uid": uid, "edited": edited})
        return {"uid": uid, "edited": bool(edited)}

    def note_complete(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        claim, note = d["claim"], d["note"]
        self.checked_text(claim, note, reviewer)
        if not d.get("attest"):
            raise UserError("Confirm that you've read the whole note.")
        pending = [x for x in self.store.drafts(claim, note, reviewer) if x["status"] in {"ready", "needs_attention"}]
        if pending:
            raise UserError(f"{len(pending)} AI draft(s) still need a decision. Accept or dismiss each one first.")
        self.store.set_status(claim, note, reviewer, "complete")
        self.store.log(reviewer, "note.complete", {"claim": claim, "note": note})
        return {"ok": True}

    def note_reopen(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        self.store.set_status(d["claim"], d["note"], reviewer, "in_progress")
        self.store.log(reviewer, "note.reopen", {"claim": d["claim"], "note": d["note"]})
        return {"ok": True}

    def note_blind(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        pending = [x for x in self.store.drafts(d["claim"], d["note"], reviewer)]
        if d.get("blind") and pending:
            raise UserError("This note already has AI drafts, so it can't be marked as done without them.")
        self.store.set_blind(d["claim"], d["note"], reviewer, bool(d.get("blind")))
        return {"ok": True}

    def claim_seal(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        claim = d["claim"]
        rows = self.store.q("SELECT note FROM notes WHERE claim=?", (claim,))
        unfinished = [r["note"] for r in rows if self.store.work(claim, r["note"], reviewer)["status"] != "complete"]
        if unfinished:
            raise UserError(f"Finish these notes first: {', '.join(unfinished)}.")
        return review.freeze(self, d)

    def claim_review(self, q: dict) -> dict:
        return review.dossier(self, q["claim"], self.reviewer(q))

    def category_save(self, d: dict) -> dict:
        return review.save(self, d)

    def annotation_undo(self, d: dict) -> dict:
        return undo.perform(self, d)

    def comparison_finish(self, d: dict) -> dict:
        return completion.finish(self, d)

    def pairing(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        row = self.store.one("SELECT claim FROM firm_rows WHERE id=?", (d["firm_row_id"],))
        if not row or not self.store.sealed(row["claim"], reviewer):
            raise UserError("Finish the claim before comparing with the firm's output.")
        entity_id = d.get("entity_id") or None
        frozen = review.checkpoint(self.store, row["claim"], reviewer)
        if entity_id:
            ent = next((e for e in frozen["entities"] if e["id"] == entity_id), None) if frozen else self.store.entity(entity_id)
            if not ent:
                raise UserError("That entity is not in the frozen answer key.")
            if ent["claim"] != row["claim"] or ent["reviewer"] != reviewer:
                raise UserError("That person or company isn't in this claim's answer key.")
        if entity_id and d.get("not_in_notes"):
            raise UserError("Choose an entity or not in the notes, not both.")
        self.store.save_pairing(d["firm_row_id"], reviewer, entity_id=entity_id,
                                allow_retired=bool(frozen),
                                not_in_notes=bool(d.get("not_in_notes")),
                                category_verdict=None if frozen else d.get("category_verdict") or None,
                                correct_category=None if frozen else d.get("correct_category") or None)
        return {"ok": True}

    def watchlist(self, d: dict) -> dict:
        reviewer = self.reviewer(d)
        row = self.store.one("SELECT claim FROM firm_rows WHERE id=?", (d["firm_row_id"],))
        if not row or not self.store.sealed(row["claim"], reviewer):
            raise UserError("Finish the claim before reviewing watchlist flags.")
        self.store.save_watchlist(d["firm_row_id"], reviewer, decision=d.get("decision") or None,
                                  note_supports=d.get("note_supports") or None, reason=d.get("reason") or None)
        return {"ok": True}


GET_ROUTES = {"/api/bootstrap": "bootstrap", "/api/claims": "claims", "/api/note": "note",
              "/api/claim/review": "claim_review",
              "/api/record/history": "history", "/api/ai/message": "ai_message",
              "/api/ai/instructions": "instructions", "/api/compare": "compare", "/api/scores": "scores"}
POST_ROUTES = {"/api/entity/create": "entity_create", "/api/entity/update": "entity_update",
               "/api/comparison/finish": "comparison_finish",
               "/api/annotation/undo": "annotation_undo",
               "/api/category/save": "category_save",
               "/api/entity/delete": "entity_delete", "/api/record/create": "record_create",
               "/api/record/update": "record_update", "/api/record/delete": "record_delete",
               "/api/ai/preview": "ai_preview", "/api/ai/import": "ai_import", "/api/draft/span": "draft_span",
               "/api/draft/accept": "draft_accept", "/api/draft/dismiss": "draft_dismiss",
               "/api/note/complete": "note_complete", "/api/note/reopen": "note_reopen",
               "/api/note/blind": "note_blind", "/api/claim/seal": "claim_seal", "/api/pairing": "pairing",
               "/api/watchlist": "watchlist"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClaimAnnotator/1"

        def log_message(self, fmt, *args):  # quiet console
            pass

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _dispatch(self, name: str, arg) -> None:
            try:
                self._json(200, getattr(app, name)(arg))
            except UserError as exc:
                self._json(400, {"error": str(exc)})
            except (KeyError, ValueError, TypeError) as exc:
                self._json(400, {"error": f"The request was missing or had a bad value: {exc}"})
            except Exception:  # noqa: BLE001 - never leak a stack trace to the page
                traceback.print_exc()
                self._json(500, {"error": "Something went wrong on the server. Your last change may not be saved; "
                                          "reload the page and check."})

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path in GET_ROUTES:
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                return self._dispatch(GET_ROUTES[url.path], q)
            if url.path == "/api/export":
                try:
                    q = {k: v[0] for k, v in parse_qs(url.query).items()}
                    data = export.build(app.store, app.reviewer(q), q.get("practice") == "1", q.get("layout", "analysis"))
                except UserError as exc:
                    return self._json(400, {"error": str(exc)})
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    return self._json(500, {"error": "The export failed. Check the server window."})
                stamp = now().replace(":", "").replace("-", "")[:15]
                return self._send(200, data, "application/zip",
                                  {"Content-Disposition": f'attachment; filename="answer-key-{stamp}.zip"'})
            path = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            if path.startswith("static/"):
                path = path[len("static/"):]
            target = (STATIC / path).resolve()
            inside = STATIC.resolve() in target.parents
            if not inside or not target.is_file():
                return self._json(404, {"error": "Not found"})
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path not in POST_ROUTES:
                return self._json(404, {"error": "Not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > 25 * 1024 * 1024:
                return self._json(413, {"error": "That's too large to send."})
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "The request wasn't valid JSON."})
            if not isinstance(data, dict):
                return self._json(400, {"error": "The request wasn't a JSON object."})
            self._dispatch(POST_ROUTES[url.path], data)

    return Handler


def serve(app: App, host: str, port: int) -> ThreadingHTTPServer:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    return ThreadingHTTPServer((host, port), make_handler(app))
