"""Everything a data scientist needs, as CSV files in one zip. The practice claim is left out."""
from __future__ import annotations

import csv
import io
import json
import zipfile

from .firm import COLUMNS
from .notes import PRACTICE_CLAIM
from .scoring import score

README = """Claim note answer key export
=============================

Positions (start, end) are 0-based, end-exclusive Unicode code-point offsets
into the note file's text, read as UTF-8 with any byte-order mark removed and
line breaks kept as they are (CRLF is two characters). note_text[start:end]
in Python always equals the quote column.

Files
  notes.csv               every note file and its path
  note_work.csv           per reviewer: status, whether AI drafts were allowed (blind), fingerprint, times
  entities.csv            people and companies each reviewer recorded (retired = deleted later)
  mentions.csv            every mention; is_first marks where the entity was first named
  details.csv             stated details (address, city, state, zip_code, phone, TIN, other) and their owner
  descriptions.csv        how the note characterizes someone ("orthopedic surgeon")
  actions.csv             what someone did, or how two parties relate
  unclear.csv             words the reviewer couldn't link confidently, with the reason
  record_history.csv      every revision of every record, including deleted ones
  ai_runs.csv             each pasted Copilot answer, raw text and parse report
  ai_drafts.csv           each AI draft: what it proposed, and whether it was accepted, edited or dismissed
  firm_rows.csv           the firm's export, with the row id used below
  pairings.csv            per reviewer: which of their entities each firm row is, and the category judgment
  watchlist_reviews.csv   per reviewer: same / different / cant_tell, and whether the note supports it
  scores.json             the EVALUATION.md scores, per reviewer
  category_reviews.csv    every category decision revision, with evidence links in its JSON payload
  review_checkpoints.json frozen independent answer keys (entities, record revisions, taxonomy and source hashes)

Record kinds map to the earlier workbench's names: mention = Mentions, detail =
Fields, description = Context, action = Statements, unclear = Uncertain.

after_seal = 1 marks work done after the reviewer had seen the firm's output.
The ordinary annotation CSVs show current work. Independent evaluation uses
review_checkpoints.json, which later edits never replace. Legacy claims without
a checkpoint have no independent category accuracy score. Repeated evidence is
not proof of independent corroboration. Sources remain in their original files.
"""


def _csv(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in columns})
    return buf.getvalue().encode("utf-8-sig")


def build(store, reviewer: str | None = None) -> bytes:
    def real(rows):
        return [r for r in rows if r.get("claim") != PRACTICE_CLAIM and
                (reviewer is None or "reviewer" not in r or r["reviewer"] == reviewer)]

    entities = {e["id"]: e for e in store.q("SELECT * FROM entities")}
    current = real(store.current_records())
    for r in current:
        r["entity_label"] = entities.get(r["entity_id"], {}).get("label", "")
        r["entity_number"] = entities.get(r["entity_id"], {}).get("number", "")
        r["entity2_label"] = entities.get(r["entity2_id"], {}).get("label", "")
    rec_cols = ["uid", "revision", "claim", "note", "reviewer", "start", "end", "quote", "entity_id",
                "entity_number", "entity_label"]
    by_kind = {
        "mentions.csv": ("mention", rec_cols + ["form", "is_first"]),
        "details.csv": ("detail", rec_cols + ["field", "value"]),
        "descriptions.csv": ("description", rec_cols + ["label"]),
        "actions.csv": ("action", rec_cols + ["entity2_id", "entity2_label", "label"]),
        "unclear.csv": ("unclear", rec_cols + ["reason"]),
    }
    tail = ["source", "draft_id", "after_seal", "created_at"]

    firm = [r for r in real(store.firm_rows()) if reviewer is None or store.sealed(r["claim"], reviewer)]
    firm_flat = [{"firm_row_id": r["id"], **r["data"]} for r in firm]
    pairings = []
    for p in store.pairings(reviewer).values():
        e = entities.get(p["entity_id"]) or {}
        pairings.append({**p, "entity_label": e.get("label", ""), "entity_number": e.get("number", "")})
    reviewers = [reviewer] if reviewer else store.reviewers()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        z.writestr("category_reviews.csv", _csv(real(store.q("SELECT * FROM category_reviews ORDER BY claim, reviewer, entity_id, revision")),
                                               ["claim", "reviewer", "entity_id", "revision", "payload"]))
        z.writestr("review_checkpoints.json", json.dumps([json.loads(r["payload"]) for r in real(store.q("SELECT * FROM review_checkpoints"))],
                                                       ensure_ascii=False, indent=2))
        z.writestr("notes.csv", _csv(real(store.q("SELECT * FROM notes")), ["claim", "note", "path"]))
        z.writestr("note_work.csv", _csv(real(store.q("SELECT * FROM note_work")),
                                         ["claim", "note", "reviewer", "status", "blind", "fingerprint",
                                          "opened_at", "completed_at"]))
        z.writestr("entities.csv", _csv(real(store.q("SELECT * FROM entities")),
                                        ["id", "claim", "reviewer", "number", "label", "type", "retired",
                                         "after_seal", "created_at"]))
        for name, (kind, cols) in by_kind.items():
            z.writestr(name, _csv([r for r in current if r["kind"] == kind], cols + tail))
        z.writestr("record_history.csv", _csv(real(store.q("SELECT * FROM records ORDER BY uid, revision")),
                                              ["uid", "revision", "state", "kind", "claim", "note", "reviewer",
                                               "start", "end", "quote", "entity_id", "entity2_id", "form",
                                               "field", "value", "label", "reason", "is_first"] + tail))
        z.writestr("ai_runs.csv", _csv(real(store.q("SELECT * FROM runs")),
                                       ["id", "claim", "note", "reviewer", "created_at", "prompt_version",
                                        "report", "raw"]))
        z.writestr("ai_drafts.csv", _csv(real(store.q("SELECT * FROM drafts")),
                                         ["id", "run_id", "claim", "note", "reviewer", "seq", "type", "key", "key2",
                                          "quote", "start", "end", "match", "fields", "problems", "status",
                                          "edited", "outcome_uid", "duplicate_of", "decided_at", "raw"]))
        z.writestr("firm_rows.csv", _csv(firm_flat, ["firm_row_id"] + COLUMNS))
        z.writestr("pairings.csv", _csv([p for p in pairings if not p["firm_row_id"].startswith(PRACTICE_CLAIM + "#")],
                                        ["firm_row_id", "reviewer", "entity_id", "entity_number", "entity_label",
                                         "not_in_notes", "category_verdict", "correct_category", "updated_at"]))
        z.writestr("watchlist_reviews.csv",
                   _csv([w for w in store.watchlist(reviewer).values() if not w["firm_row_id"].startswith(PRACTICE_CLAIM + "#")],
                        ["firm_row_id", "reviewer", "decision", "note_supports", "reason", "updated_at"]))
        z.writestr("scores.json", json.dumps({rv: score(store, rv) for rv in reviewers}, indent=2, ensure_ascii=False))
    return out.getvalue()
