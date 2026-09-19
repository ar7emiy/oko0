import unittest
from unittest.mock import patch
import test_app as fixtures
from test_app import ME
from annotator import undo, review
from annotator.server import App
from annotator.store import UserError


class Undo(unittest.TestCase):
    setUp = fixtures.Workflow.setUp
    tearDown = fixtures.Workflow.tearDown
    note = fixtures.Workflow.note
    entity = fixtures.Workflow.entity
    record = fixtures.Workflow.record
    complete_all = fixtures.Workflow.complete_all
    review_all = fixtures.Workflow.review_all

    def undo(self):
        return self.app.annotation_undo({"reviewer": ME})

    def test_create_edit_delete_and_repeated_undo_preserve_history(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        uid = self.record("description", "orthopedic surgeon", {"entity_id": ada})
        self.app.record_update({"uid":uid,"reviewer":ME,"fields":{"label":"wrong label"}})
        self.app.record_delete({"uid":uid,"reviewer":ME})
        self.undo()
        self.assertEqual(self.app.store.record(uid)["label"], "wrong label")
        self.undo()
        self.assertIsNone(self.app.store.record(uid)["label"])
        self.undo()
        self.assertEqual(len(self.note()["records"]), 1)
        self.undo()
        self.assertEqual(self.note()["entities"], [])
        self.assertEqual(len(self.app.store.history(uid)), 6)
        with self.assertRaisesRegex(UserError, "No saved"):
            self.undo()

    def test_entity_rename_and_delete_can_be_undone(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        self.app.entity_update({"id":ada,"reviewer":ME,"label":"Wrong name","type":"other"})
        self.app.entity_delete({"id":ada,"reviewer":ME})
        self.undo()
        self.assertEqual(self.app.store.entity(ada)["label"], "Wrong name")
        self.undo()
        self.assertEqual(self.app.store.entity(ada)["label"], "Dr. Ada Monroe")

    def test_ai_accept_and_dismiss_are_single_undo_operations(self):
        self.app.ai_import({"claim":"C201","note":"N01","reviewer":ME,"answer":fixtures.Workflow.AI})
        drafts = {d["seq"]:d for d in self.note()["drafts"]}
        self.app.draft_accept({"id":drafts[1]["id"],"reviewer":ME})
        self.undo()
        self.assertEqual(self.note()["entities"], [])
        self.assertEqual(self.app.store.draft(drafts[1]["id"])["status"], "ready")
        self.assertIsNone(self.app.store.run_key(drafts[1]["run_id"], "P1"))
        self.app.draft_dismiss({"id":drafts[2]["id"],"reviewer":ME})
        self.undo()
        self.assertEqual(self.app.store.draft(drafts[2]["id"])["status"], "ready")

    def test_history_survives_restart_and_reviewers_are_isolated(self):
        self.entity("Dr. Ada Monroe", "person")
        self.app = App(self.app.store, self.app.config)
        with self.assertRaisesRegex(UserError, "No saved"):
            self.app.annotation_undo({"reviewer":"Someone else"})
        self.undo()
        self.assertEqual(self.note()["entities"], [])

    def test_legacy_last_manual_annotation_can_be_recovered(self):
        self.entity("Dr. Ada Monroe", "person")
        self.app.store.db.execute("DROP TABLE undo_actions")
        self.app = App(self.app.store, self.app.config)
        self.undo()
        self.assertEqual(self.note()["entities"], [])

    def test_changed_source_blocks_undo_without_consuming_history(self):
        self.entity("Dr. Ada Monroe", "person")
        path = self.tmp / "notes" / "C201_N01.txt"
        before = path.read_bytes()
        path.write_bytes(b"Changed " + before)
        with self.assertRaisesRegex(UserError, "source note changed"):
            self.undo()
        path.write_bytes(before)
        self.undo()
        self.assertEqual(self.note()["entities"], [])

    def test_undo_does_not_change_frozen_key_or_break_frozen_pairing(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        self.complete_all(); self.review_all()
        self.app.claim_seal({"claim":"C201","reviewer":ME,"attest":True})
        snapshot = review.checkpoint(self.app.store, "C201", ME)
        self.undo()
        self.assertEqual(review.checkpoint(self.app.store,"C201",ME), snapshot)
        row = self.app.compare({"claim":"C201","reviewer":ME})["rows"][0]
        self.app.pairing({"firm_row_id":row["id"],"reviewer":ME,"entity_id":ada})
        self.assertEqual(self.app.store.work("C201","N01",ME)["status"], "in_progress")

    def test_failed_mutation_rolls_back_with_undo_journal(self):
        with patch.object(self.app.store, "log", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                self.entity("Dr. Ada Monroe", "person")
        self.assertEqual(self.note()["entities"], [])
        self.assertEqual(self.app.store.q("SELECT * FROM undo_actions"), [])
