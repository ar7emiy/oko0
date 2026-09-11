import csv
import io
import json
import unittest
import zipfile
import test_app as fixtures
from test_app import ME
from annotator import export
from annotator.store import UserError


def csv_rows(z, name):
    return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))


class AnalysisExport(unittest.TestCase):
    setUp = fixtures.Workflow.setUp
    tearDown = fixtures.Workflow.tearDown
    note = fixtures.Workflow.note
    entity = fixtures.Workflow.entity
    record = fixtures.Workflow.record
    complete_all = fixtures.Workflow.complete_all
    review_all = fixtures.Workflow.review_all

    def test_three_table_practice_opt_in_and_text_identifiers(self):
        self.entity("Dr. Ada Monroe", "person", claim="PRACTICE")
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store, ME, False, "analysis")))
        self.assertEqual(csv_rows(z,"evidence.csv"), [])
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store, ME, True, "analysis")))
        self.assertEqual(set(z.namelist()), {"entity_comparison.csv","evidence.csv","kpi_summary.csv","README.txt"})
        evidence = csv_rows(z,"evidence.csv")
        self.assertEqual((evidence[0]["quote"],evidence[0]["is_practice"]), ("Dr. Ada Monroe","1"))
        entities = csv_rows(z,"entity_comparison.csv")
        self.assertEqual(entities[0]["answer_key_basis"], "in_progress")
        self.assertFalse(any(e["firm_entity_name"] for e in entities))

    def test_completion_requires_all_answers_and_reopens_after_edits(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        self.complete_all();self.review_all()
        self.app.claim_seal({"claim":"C201","reviewer":ME,"attest":True})
        with self.assertRaisesRegex(UserError,"still need"):
            self.app.comparison_finish({"claim":"C201","reviewer":ME})
        rows = self.app.compare({"claim":"C201","reviewer":ME})["rows"]
        for row in rows:
            self.app.pairing({"firm_row_id":row["id"],"reviewer":ME,"entity_id":ada})
            if row["flagged"]:
                self.app.watchlist({"firm_row_id":row["id"],"reviewer":ME,"decision":"cant_tell","note_supports":"partly","reason":"Name alone."})
        self.app.comparison_finish({"claim":"C201","reviewer":ME})
        self.assertTrue(self.app.compare({"claim":"C201","reviewer":ME})["comparison"]["complete"])
        self.app.pairing({"firm_row_id":rows[0]["id"],"reviewer":ME,"not_in_notes":True})
        self.assertFalse(self.app.compare({"claim":"C201","reviewer":ME})["comparison"]["complete"])

    def test_analysis_uses_frozen_evidence_and_joins_firm_row(self):
        ada = self.entity("Dr. Ada Monroe", "person")
        uid = self.record("detail","STRESS-201",{"entity_id":ada,"field":"TIN","value":"STRESS-201"},note="N04")
        self.complete_all();self.review_all()
        self.app.claim_seal({"claim":"C201","reviewer":ME,"attest":True})
        row = self.app.compare({"claim":"C201","reviewer":ME})["rows"][0]
        self.app.pairing({"firm_row_id":row["id"],"reviewer":ME,"entity_id":ada})
        self.app.record_delete({"uid":uid,"reviewer":ME})
        z = zipfile.ZipFile(io.BytesIO(export.build(self.app.store,ME,False,"analysis")))
        evidence = csv_rows(z,"evidence.csv")
        self.assertTrue(any(r["uid"]==uid and r["answer_key_basis"]=="frozen" for r in evidence))
        joined = next(r for r in csv_rows(z,"entity_comparison.csv") if r["firm_row_id"]==row["id"])
        self.assertEqual(joined["entity_id"],ada)
        self.assertEqual(json.loads(joined["gold_details_json"])[0]["value"],"STRESS-201")

    def test_second_practice_claim_is_reserved_and_excluded_by_default(self):
        self.entity("Elena Rivera","person",claim="PRACTICE2")
        self.assertTrue(next(c for c in self.app.claims({"reviewer":ME})["claims"] if c["claim"]=="PRACTICE2")["practice"])
        z=zipfile.ZipFile(io.BytesIO(export.build(self.app.store,ME,False,"analysis")))
        self.assertEqual(csv_rows(z,"entity_comparison.csv"),[])

    def test_missed_details_require_matching_value_and_deduplicate_evidence(self):
        ada=self.entity("Dr. Ada Monroe","person")
        self.record("detail","STRESS-201",{"entity_id":ada,"field":"TIN","value":"001234567"},note="N04")
        self.record("detail","orthopedic surgeon",{"entity_id":ada,"field":"TIN","value":"001234567"})
        self.complete_all();self.review_all()
        self.app.claim_seal({"claim":"C201","reviewer":ME,"attest":True})
        row=self.app.compare({"claim":"C201","reviewer":ME})["rows"][0]
        self.app.pairing({"firm_row_id":row["id"],"reviewer":ME,"entity_id":ada})
        metric=next(m for m in self.app.scores({"reviewer":ME})["metrics"] if m["id"]=="missed_detail_rate")
        self.assertEqual((metric["numerator"],metric["denominator"]),(1,1))

    def test_unsupported_details_on_not_in_notes_rows_count(self):
        self.complete_all()
        self.app.claim_seal({"claim":"C201","reviewer":ME,"attest":True})
        rows=self.app.compare({"claim":"C201","reviewer":ME})["rows"]
        for row in rows:self.app.pairing({"firm_row_id":row["id"],"reviewer":ME,"not_in_notes":True})
        metric=next(m for m in self.app.scores({"reviewer":ME})["metrics"] if m["id"]=="made_up_rate")
        self.assertEqual((metric["numerator"],metric["denominator"]),(6,6))
