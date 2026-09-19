"""Independent category review: evidence, stale decisions, frozen scoring, and migration."""
import io
import json
import unittest
import zipfile

import test_app as fixtures
from test_app import ME
from annotator.store import UserError
from annotator import export, review


class ClaimReview(unittest.TestCase):
    setUp = fixtures.Workflow.setUp
    tearDown = fixtures.Workflow.tearDown
    note = fixtures.Workflow.note
    entity = fixtures.Workflow.entity
    record = fixtures.Workflow.record
    complete_all = fixtures.Workflow.complete_all
    review_all = fixtures.Workflow.review_all

    def prepare(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        uid = self.record("description", "orthopedic surgeon", {"entity_id": ada})
        self.record("detail", "STRESS-201", {"entity_id": ada, "field": "TIN", "value": "STRESS-201"}, note="N04")
        self.complete_all()
        return ada, uid

    def decision(self, entity_id, **overrides):
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        e = next(e for e in data["entities"] if e["id"] == entity_id)
        r = next(r for r in e["records"] if r["kind"] == "description")
        return {"claim": "C201", "reviewer": ME, "entity_id": entity_id, "basis": e["basis"], "revision": (e["decision"] or {}).get("revision", 0),
                "status": "assigned", "category": "medical provider", "rationale": "The note explicitly identifies a surgeon.",
                "evidence": [{"uid": r["uid"], "revision": r["revision"], "role": "supports"}], **overrides}

    def freeze(self):
        return self.app.claim_seal({"claim": "C201", "reviewer": ME, "attest": True})

    def test_cross_note_dossier_keeps_provenance_and_hides_firm(self):
        ada, uid = self.prepare()
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        self.assertEqual({r["note"] for r in data["entities"][0]["records"]}, {"N01", "N04"})
        self.assertEqual(next(r for r in data["records"] if r["uid"] == uid)["quote"], "orthopedic surgeon")
        self.assertNotIn("firm_rows", data)
        self.assertNotIn("category_verdict", json.dumps(data))
        with self.assertRaises(UserError):
            self.app.compare({"claim": "C201", "reviewer": ME})
        with self.assertRaisesRegex(UserError, "Review every entity"):
            self.freeze()

    def test_revision_change_requires_review_again_and_keeps_history(self):
        ada, uid = self.prepare()
        d = self.decision(ada)
        self.app.category_save(d)
        self.app.record_update({"uid": uid, "reviewer": ME, "fields": {"label": "qualified description"}})
        with self.assertRaisesRegex(UserError, "evidence changed"):
            self.app.category_save(d)
        with self.assertRaisesRegex(UserError, "Review every entity"):
            self.freeze()
        self.app.category_save(self.decision(ada))
        self.freeze()
        history = self.app.store.q("SELECT * FROM category_reviews")
        self.assertEqual([h["revision"] for h in history], [1, 2])
        snap = review.checkpoint(self.app.store, "C201", ME)
        self.assertEqual(snap["entities"][0]["decision"]["evidence"][0]["revision"], 2)

    def test_foreign_stale_duplicate_or_repeated_only_evidence_refused(self):
        ada, uid = self.prepare()
        d = self.decision(ada)
        for links in ([{"uid": "foreign", "revision": 1, "role": "supports"}],
                      [{"uid": uid, "revision": 99, "role": "supports"}], d["evidence"] * 2,
                      [{"uid": uid, "revision": 1, "role": "repeated"}]):
            with self.subTest(links=links), self.assertRaises(UserError):
                self.app.category_save({**d, "evidence": links})
        with self.assertRaises(UserError):
            self.app.category_save({**d, "reviewer": "Other reviewer"})

    def test_snapshot_survives_edits_and_drives_comparison_and_scores(self):
        ada, uid = self.prepare()
        self.app.category_save(self.decision(ada))
        self.freeze()
        frozen = review.checkpoint(self.app.store, "C201", ME)
        row = next(r for r in self.app.compare({"claim": "C201", "reviewer": ME})["rows"] if r["data"]["entity_name"] == "Dr. Ada Monroe")
        self.app.pairing({"firm_row_id": row["id"], "reviewer": ME, "entity_id": ada,
                          "category_verdict": "wrong", "correct_category": "legal"})
        before = self.app.scores({"reviewer": ME})["metrics"]
        self.app.record_delete({"uid": uid, "reviewer": ME})
        self.app.entity_update({"id": ada, "reviewer": ME, "label": "Edited name", "type": "other"})
        self.assertEqual(review.checkpoint(self.app.store, "C201", ME), frozen)
        self.assertEqual(self.app.scores({"reviewer": ME})["metrics"], before)
        self.assertEqual(self.app.compare({"claim": "C201", "reviewer": ME})["entities"][0]["label"], "Dr. Ada Monroe")
        with self.assertRaisesRegex(UserError, "already been unlocked"):
            self.app.category_save(self.decision(ada))
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store, ME)))
        self.assertEqual(json.loads(z.read("review_checkpoints.json")), [frozen])

    def test_unknown_and_conflicting_are_complete_but_not_accuracy_labels(self):
        for status in ("insufficient", "conflicting"):
            with self.subTest(status=status):
                ada, uid = self.prepare() if status == "insufficient" else (ada, uid)
                links = [] if status == "insufficient" else [{"uid": uid, "revision": 1, "role": "conflicts"}]
                self.app.category_save(self.decision(ada, status=status, evidence=links))
        self.freeze()
        row = self.app.compare({"claim": "C201", "reviewer": ME})["rows"][0]
        self.app.pairing({"firm_row_id": row["id"], "reviewer": ME, "entity_id": ada})
        m = {m["id"]: m for m in self.app.scores({"reviewer": ME})["metrics"]}
        self.assertEqual((m["category_accuracy"]["denominator"], m["category_accuracy"]["set_aside"]), (0, 1))
        self.assertEqual((m["category_coverage"]["numerator"], m["category_coverage"]["denominator"]), (0, 1))

    def test_changed_source_and_taxonomy_block_freeze(self):
        ada, _ = self.prepare()
        self.app.category_save(self.decision(ada))
        self.app.config.taxonomy = {**self.app.config.taxonomy, "version": "new-policy"}
        with self.assertRaisesRegex(UserError, "Review every entity"):
            self.freeze()
        self.app.category_save(self.decision(ada))
        path = self.tmp / "notes" / "C201_N04.txt"
        path.write_bytes(path.read_bytes() + b" Changed")
        with self.assertRaisesRegex(UserError, "note file changed"):
            self.freeze()

    def test_legacy_claims_cannot_be_backfilled_and_export_respects_blinding(self):
        ada, _ = self.prepare()
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store, ME)))
        self.assertNotIn("Dr. Ada Monroe", z.read("firm_rows.csv").decode("utf-8-sig"))
        self.app.store.seal("C201", ME)  # an old database's pre-upgrade seal
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        self.assertTrue(data["legacy"])
        with self.assertRaisesRegex(UserError, "already been unlocked"):
            self.app.category_save(self.decision(ada))
        row = self.app.compare({"claim": "C201", "reviewer": ME})["rows"][0]
        self.app.pairing({"firm_row_id": row["id"], "reviewer": ME, "entity_id": ada, "category_verdict": "right"})
        cat = next(m for m in self.app.scores({"reviewer": ME})["metrics"] if m["id"] == "category_accuracy")
        self.assertEqual(cat["denominator"], 0)

    def test_empty_claim_still_requires_attestation_and_unchanged_sources(self):
        self.complete_all()
        with self.assertRaisesRegex(UserError, "Confirm"):
            self.app.claim_seal({"claim": "C201", "reviewer": ME})
        path = self.tmp / "notes" / "C201_N01.txt"
        path.write_bytes(path.read_bytes() + b"Changed")
        self.assertFalse(self.note()["fingerprint_ok"])
        with self.assertRaisesRegex(UserError, "note file changed"):
            self.freeze()

    def test_unresolved_references_preserved_and_empty_claim_can_freeze(self):
        self.record("unclear", "Dr. Ada Monroe", {"reason": "Identity unresolved"})
        self.complete_all()
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        self.assertEqual(len(data["unresolved"]), 1)
        self.freeze()
        self.assertEqual(len(review.checkpoint(self.app.store, "C201", ME)["unresolved"]), 1)

    def test_ownership_correction_reopens_both_entity_reviews(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        north = self.entity("Northstar Orthopedics", "organization")
        uid = self.record("detail", "STRESS-201", {"entity_id": ada, "field": "TIN", "value": "STRESS-201"}, note="N04")
        self.complete_all()
        self.review_all()
        self.app.record_update({"uid": uid, "reviewer": ME, "fields": {"entity_id": north}})
        data = self.app.claim_review({"claim": "C201", "reviewer": ME})
        self.assertFalse(any(e["reviewed"] for e in data["entities"]))
        new_record = next(r for r in data["records"] if r["uid"] == uid)
        self.assertEqual((new_record["entity_id"], new_record["note"], new_record["revision"]), (north, "N04", 2))
        self.assertEqual(self.app.store.history(uid)[0]["entity_id"], ada)

    def test_subcategory_must_be_stated_and_pending_drafts_block_freeze(self):
        ada, uid = self.prepare()
        with self.assertRaisesRegex(UserError, "subcategory must appear"):
            self.app.category_save(self.decision(ada, subcategory="heart surgeon"))
        self.app.category_save(self.decision(ada, subcategory="orthopedic surgeon"))
        self.app.ai_import({"claim": "C201", "note": "N01", "reviewer": ME,
                            "answer": '{"type":"unclear","quote":"called regarding the claim","reason":"Check context"}'})
        with self.assertRaisesRegex(UserError, "remaining AI drafts"):
            self.freeze()

    def test_export_does_not_leak_other_reviewers_answers(self):
        ada, _ = self.prepare()
        self.app.category_save(self.decision(ada))
        self.freeze()
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store, "New reviewer")))
        self.assertEqual(json.loads(z.read("review_checkpoints.json")), [])
        self.assertNotIn("Dr. Ada Monroe", z.read("entities.csv").decode("utf-8-sig"))
        self.assertNotIn("Dr. Ada Monroe", z.read("firm_rows.csv").decode("utf-8-sig"))

    def test_repeat_save_is_idempotent_and_stale_tab_cannot_replace_decision(self):
        ada, _ = self.prepare()
        d = self.decision(ada)
        self.app.category_save(d)
        self.app.category_save(d)
        self.assertEqual(len(self.app.store.q("SELECT * FROM category_reviews")), 1)
        with self.assertRaisesRegex(UserError, "another view"):
            self.app.category_save({**d, "rationale": "Different view's change"})


if __name__ == "__main__":
    unittest.main()
