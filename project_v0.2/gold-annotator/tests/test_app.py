"""The whole reviewer workflow through the App layer: manual work, AI drafts, completion, comparison, scores."""
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from annotator.server import App, Config  # noqa: E402
from annotator.store import Store, UserError  # noqa: E402

SAMPLE = ROOT.parent / "python-annotator" / "sample-data" / "stress-packet"
ME = "Pat Reviewer"


def make_app(tmp: Path, *, firm=True) -> App:
    notes_dir = tmp / "notes"
    notes_dir.mkdir()
    for n in ("C201_N01.txt", "C201_N04.txt"):
        shutil.copy(SAMPLE / "notes" / n, notes_dir / n)
    (notes_dir / "badname.txt").write_text("x", encoding="utf-8")
    store = Store(tmp / "db.sqlite3")
    files = [SAMPLE / "client-export.csv"] if firm else []
    return App(store, Config(notes_dir=notes_dir, firm_files=files, part_size=12000))


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = make_app(self.tmp)

    def tearDown(self):
        self.app.store.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, note="N01", claim="C201"):
        return self.app.note({"claim": claim, "note": note, "reviewer": ME})

    def entity(self, quote, type_, note="N01", occurrence=0, claim="C201"):
        text = self.note(note, claim)["text"]
        start = -1
        for _ in range(occurrence + 1):
            start = text.index(quote, start + 1)
        return self.app.entity_create({"claim": claim, "note": note, "reviewer": ME, "start": start,
                                       "end": start + len(quote), "label": quote, "type": type_})["entity_id"]

    def record(self, kind, quote, fields, note="N01", occurrence=0):
        text = self.note(note)["text"]
        start = -1
        for _ in range(occurrence + 1):
            start = text.index(quote, start + 1)
        return self.app.record_create({"claim": "C201", "note": note, "reviewer": ME, "kind": kind, "start": start,
                                       "end": start + len(quote), "fields": fields})["uid"]

    # -- discovery ------------------------------------------------------------
    def test_discovery_reports_bad_names_and_includes_practice(self):
        claims = {c["claim"]: c for c in self.app.claims({"reviewer": ME})["claims"]}
        self.assertEqual(set(claims), {"PRACTICE", "PRACTICE2", "C201"})
        self.assertEqual([n["note"] for n in claims["C201"]["notes"]], ["N01", "N04"])
        self.assertTrue(any("badname" in s for s in self.app.config.skipped))

    # -- manual annotation ---------------------------------------------------
    def test_manual_annotation_end_to_end(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        first = self.note()["records"][0]
        self.assertEqual((first["start"], first["end"], first["is_first"], first["form"]), (0, 14, 1, "name"))
        self.record("mention", "Dr. Ada Monroe", {"entity_id": ada, "form": "name"}, occurrence=1)
        self.record("description", "orthopedic surgeon", {"entity_id": ada})
        north = self.entity("Northstar Orthopedics", "organization")
        self.record("action", "with Northstar Orthopedics", {"entity_id": ada, "entity2_id": north})
        self.record("detail", "STRESS-201", {"entity_id": north, "field": "TIN", "value": "STRESS-201"}, note="N04")
        recs = self.note()["records"]
        self.assertEqual([r["quote"] for r in recs][:2], ["Dr. Ada Monroe", "called regarding the claim"][:1] +
                         ["Dr. Ada Monroe"])
        self.assertEqual(len(recs), 5)
        text = self.note()["text"]
        for r in recs:
            self.assertEqual(text[r["start"]:r["end"]], r["quote"])

    def test_validation_messages(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        with self.assertRaisesRegex(UserError, "belongs to"):
            self.record("mention", "Dr. Ada Monroe", {"form": "name"}, occurrence=1)
        with self.assertRaisesRegex(UserError, "kind of detail"):
            self.record("detail", "orthopedic surgeon", {"entity_id": ada, "field": "shoe", "value": "x"})
        with self.assertRaisesRegex(UserError, "why"):
            self.record("unclear", "the medical provider", {})
        with self.assertRaisesRegex(UserError, "already recorded"):
            self.record("description", "orthopedic surgeon", {"entity_id": ada})
            self.record("description", "orthopedic surgeon", {"entity_id": ada})
        with self.assertRaisesRegex(UserError, "Select some words"):
            self.app.record_create({"claim": "C201", "note": "N01", "reviewer": ME, "kind": "unclear",
                                    "start": 5, "end": 5, "fields": {"reason": "x"}})
        with self.assertRaisesRegex(UserError, "name first"):
            self.app.note({"claim": "C201", "note": "N01", "reviewer": " "})

    def test_edit_and_delete_keep_history(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        uid = self.record("description", "orthopedic surgeon", {"entity_id": ada})
        self.app.record_update({"uid": uid, "reviewer": ME, "fields": {"label": "surgeon"}})
        self.app.record_delete({"uid": uid, "reviewer": ME})
        hist = self.app.history({"uid": uid})["history"]
        self.assertEqual([h["state"] for h in hist], ["accepted", "accepted", "retired"])
        self.assertEqual(hist[1]["label"], "surgeon")
        self.assertEqual(len(self.note()["records"]), 1)

    def test_entity_with_dependents_cannot_be_deleted(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        self.record("description", "orthopedic surgeon", {"entity_id": ada})
        with self.assertRaisesRegex(UserError, "still has 1 record"):
            self.app.entity_delete({"id": ada, "reviewer": ME})

    def test_other_reviewers_work_is_separate(self):
        self.entity("Dr. Ada Monroe", "person")
        other = self.app.note({"claim": "C201", "note": "N01", "reviewer": "Sam Second"})
        self.assertEqual(other["records"], [])
        self.assertEqual(other["entities"], [])

    # -- AI drafts -------------------------------------------------------------
    AI = "\n".join([
        "Here you go:", "```",
        '{"type":"meta","claim":"C201","note":"N01","part":1,"parts":1,"read_all":true,"summary":"ok"}',
        '{"type":"entity","key":"P1","quote":"Dr. Ada Monroe","name":"Dr. Ada Monroe","kind":"person"}',
        '{"type":"action","key":"P1","quote":"called regarding the claim"}',
        '{"type":"mention","key":"P1","quote":"Dr. Ada Monroe","before":"regarding the claim.","form":"name"}',
        '{"type":"description","key":"P1","quote":"orthopedic surgeon"}',
        '{"type":"entity","key":"O1","quote":"Northstar Orthopedics","name":"Northstar Orthopedics","kind":"organization"}',
        '{"type":"action","key":"P1","key2":"O1","quote":"with Northstar Orthopedics"}',
        '{"type":"description","key":"O1","quote":"the medical provider"}', "```"])

    def import_ai(self, expect_ready=7):
        preview = self.app.ai_preview({"claim": "C201", "note": "N01", "reviewer": ME, "answer": self.AI})
        self.assertEqual(preview["counts"]["ready"], expect_ready, preview)
        self.app.ai_import({"claim": "C201", "note": "N01", "reviewer": ME, "answer": self.AI})
        return {d["seq"]: d for d in self.note()["drafts"]}

    def test_ai_drafts_accept_edit_dismiss(self):
        drafts = self.import_ai()
        # A dependent can't be accepted before the entity it points to.
        with self.assertRaisesRegex(UserError, "NEEDS_ENTITY"):
            self.app.draft_accept({"id": drafts[2]["id"], "reviewer": ME})
        self.app.draft_accept({"id": drafts[1]["id"], "reviewer": ME})
        self.app.draft_accept({"id": drafts[2]["id"], "reviewer": ME})
        self.app.draft_accept({"id": drafts[3]["id"], "reviewer": ME})
        # SME edits the description before accepting.
        self.app.draft_accept({"id": drafts[4]["id"], "reviewer": ME, "fields": {"label": "surgeon (edited)"}})
        self.app.draft_accept({"id": drafts[5]["id"], "reviewer": ME})
        self.app.draft_accept({"id": drafts[6]["id"], "reviewer": ME})
        self.app.draft_dismiss({"id": drafts[7]["id"], "reviewer": ME})
        after = {d["seq"]: d for d in self.note()["drafts"]}
        self.assertEqual([after[i]["status"] for i in range(1, 8)], ["accepted"] * 6 + ["dismissed"])
        self.assertEqual([after[i]["edited"] for i in range(1, 7)], [0, 0, 0, 1, 0, 0])
        action = next(r for r in self.note()["records"] if r["quote"] == "with Northstar Orthopedics")
        self.assertIsNotNone(action["entity2_id"])
        self.assertEqual({r["source"] for r in self.note()["records"]}, {"ai"})

    def test_duplicate_paste_is_recognized(self):
        drafts = self.import_ai()
        self.app.draft_accept({"id": drafts[1]["id"], "reviewer": ME})
        again = self.app.ai_preview({"claim": "C201", "note": "N01", "reviewer": ME, "answer": self.AI})
        self.assertEqual(again["counts"]["duplicate"], 1)

    def test_entity_draft_can_link_to_an_existing_entity(self):
        ada = self.entity("Dr. Ada Monroe", "person", note="N01")
        drafts = self.import_ai(expect_ready=6)
        # The entity draft duplicates the SME's own first mention, so it's recognized as already recorded...
        self.assertEqual(drafts[1]["status"], "duplicate")
        # ...and its key P1 now means the SME's Ada, so drafts attached to P1 link up with no re-picking.
        self.assertEqual(drafts[3]["resolved"]["key"], ada)
        self.app.draft_accept({"id": drafts[3]["id"], "reviewer": ME})
        self.app.draft_accept({"id": drafts[4]["id"], "reviewer": ME})
        self.assertEqual(len([r for r in self.note()["records"] if r["entity_id"] == ada]), 3)

    def test_needs_attention_draft_fixed_by_choosing_words(self):
        answer = ('{"type":"meta","claim":"C201","note":"N01"}\n'
                  '{"type":"entity","key":"O1","quote":"Northstar Orthopedic Group","kind":"organization"}')
        self.app.ai_import({"claim": "C201", "note": "N01", "reviewer": ME, "answer": answer})
        d = self.note()["drafts"][0]
        self.assertEqual(d["status"], "needs_attention")
        text = self.note()["text"]
        s = text.index("Northstar Orthopedics")
        self.app.draft_span({"id": d["id"], "reviewer": ME, "start": s, "end": s + 21})
        self.assertEqual(self.note()["drafts"][0]["status"], "ready")
        self.app.draft_accept({"id": d["id"], "reviewer": ME, "fields": {"name": "Northstar Orthopedics"}})
        self.assertEqual(self.note()["entities"][0]["label"], "Northstar Orthopedics")

    def test_blind_note_refuses_ai(self):
        self.app.note_blind({"claim": "C201", "note": "N01", "reviewer": ME, "blind": True})
        with self.assertRaisesRegex(UserError, "without AI"):
            self.app.ai_preview({"claim": "C201", "note": "N01", "reviewer": ME, "answer": self.AI})

    def test_message_for_copilot(self):
        self.entity("Dr. Ada Monroe", "person")
        m = self.app.ai_message({"claim": "C201", "note": "N01", "reviewer": ME, "part": "1"})
        self.assertIn("KNOWN:\nE1 | Dr. Ada Monroe | person", m["message"])
        self.assertIn("<<<NOTE\nDr. Ada Monroe called", m["message"])
        full = self.app.ai_message({"claim": "C201", "note": "N01", "reviewer": ME, "full": "1"})
        self.assertIn("QUOTE RULES", full["message"])

    # -- completion, comparison, scores, export ---------------------------------
    def complete_all(self):
        for n in ("N01", "N04"):
            self.note(n)
            self.app.note_complete({"claim": "C201", "note": n, "reviewer": ME, "attest": True})

    def review_all(self, category="medical provider"):
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        for e in data["entities"]:
            r = e["records"][0]
            self.app.category_save({"claim": "C201", "reviewer": ME, "entity_id": e["id"], "basis": e["basis"],
                                    "status": "assigned", "category": category, "rationale": "Synthetic category scoring fixture.",
                                    "evidence": [{"uid": r["uid"], "revision": r["revision"], "role": "supports"}]})

    def test_completion_gates(self):
        self.import_ai()
        with self.assertRaisesRegex(UserError, "still need a decision"):
            self.app.note_complete({"claim": "C201", "note": "N01", "reviewer": ME, "attest": True})
        with self.assertRaisesRegex(UserError, "Finish these notes"):
            self.app.claim_seal({"claim": "C201", "reviewer": ME})
        with self.assertRaisesRegex(UserError, "Finish every note"):
            self.app.compare({"claim": "C201", "reviewer": ME})

    def test_file_change_after_work_began_blocks_saving(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        path = self.tmp / "notes" / "C201_N01.txt"
        path.write_text("Changed. " + path.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertFalse(self.note()["fingerprint_ok"])
        with self.assertRaisesRegex(UserError, "changed since you started"):
            self.record("description", "orthopedic surgeon", {"entity_id": ada})

    def test_compare_score_export(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        north = self.entity("Northstar Orthopedics", "organization")
        for field, quote in [("address", "101 Alder Avenue"), ("city", "Lakeview"), ("state", "IL"),
                             ("zip_code", "60101"), ("phone", "555-201-0101"), ("TIN", "STRESS-201")]:
            self.record("detail", quote, {"entity_id": north, "field": field, "value": quote}, note="N04")
        self.complete_all()
        self.review_all()
        self.app.claim_seal({"claim": "C201", "reviewer": ME, "attest": True})
        cmp = self.app.compare({"claim": "C201", "reviewer": ME})
        rows = {r["data"]["entity_name"]: r for r in cmp["rows"]}
        self.assertEqual(set(rows), {"Northstar Orthopedics", "Dr. Ada Monroe"})
        self.assertTrue(rows["Dr. Ada Monroe"]["flagged"])
        self.app.pairing({"firm_row_id": rows["Northstar Orthopedics"]["id"], "reviewer": ME, "entity_id": north,
                          "category_verdict": "right"})
        self.app.pairing({"firm_row_id": rows["Dr. Ada Monroe"]["id"], "reviewer": ME, "entity_id": ada,
                          "category_verdict": "right"})
        self.app.watchlist({"firm_row_id": rows["Dr. Ada Monroe"]["id"], "reviewer": ME, "decision": "cant_tell",
                            "note_supports": "partly", "reason": "Name only."})
        s = self.app.scores({"reviewer": ME})
        m = {x["id"]: x for x in s["metrics"]}
        self.assertEqual((m["found_rate"]["numerator"], m["found_rate"]["denominator"]), (2, 2))
        self.assertEqual((m["detail_accuracy"]["numerator"], m["detail_accuracy"]["denominator"]), (6, 6))
        self.assertEqual(m["right_owner_rate"]["text"], "6 ÷ 6 = 100%")
        self.assertEqual(m["made_up_rate"]["numerator"], 0)
        self.assertEqual(m["category_accuracy"]["text"], "2 ÷ 2 = 100%")
        self.assertEqual(m["cant_tell_rate"]["text"], "1 ÷ 1 = 100%")
        self.assertEqual(s["similarity_bins"][0]["flags"], 1)

        data = self.app.store and __import__("annotator.export", fromlist=["build"]).build(self.app.store)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("details.csv", z.namelist())
        details = z.read("details.csv").decode("utf-8-sig")
        self.assertIn("STRESS-201", details)
        self.assertNotIn("PRACTICE", z.read("firm_rows.csv").decode("utf-8-sig"))
        scores = json.loads(z.read("scores.json"))
        self.assertIn(ME, scores)

    def test_wrong_owner_and_made_up_details_are_scored(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        north = self.entity("Northstar Orthopedics", "organization")
        # SME puts the phone on Ada; the firm has it on Northstar.
        self.record("detail", "555-201-0101", {"entity_id": ada, "field": "phone", "value": "555-201-0101"}, note="N04")
        self.complete_all()
        self.review_all("legal")
        self.app.claim_seal({"claim": "C201", "reviewer": ME, "attest": True})
        rows = {r["data"]["entity_name"]: r for r in self.app.compare({"claim": "C201", "reviewer": ME})["rows"]}
        self.app.pairing({"firm_row_id": rows["Northstar Orthopedics"]["id"], "reviewer": ME, "entity_id": north,
                          "category_verdict": "wrong", "correct_category": "legal"})
        m = {x["id"]: x for x in self.app.scores({"reviewer": ME})["metrics"]}
        self.assertEqual(m["detail_accuracy"]["numerator"], 1)        # the phone value is right...
        self.assertEqual(m["right_owner_rate"]["numerator"], 0)       # ...but on the wrong owner
        self.assertEqual(m["made_up_rate"]["numerator"], 5)           # 5 values no gold detail states
        self.assertEqual(m["category_accuracy"]["text"], "0 ÷ 1 = 0%")
        self.assertEqual(m["right_rate"]["text"], "1 ÷ 1 = 100%")


if __name__ == "__main__":
    unittest.main()
