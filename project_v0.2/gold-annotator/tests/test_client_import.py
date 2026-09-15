"""Client header mapping, XLSX decoding and claim-local citation navigation."""
import csv
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from annotator import firm, workbook
from annotator.server import App, Config
from annotator.store import Store

HEADERS = "Claim_Number|RecordType (Entity/ GenAI_only/ Exact_search)|entity_category|entity_subcategory|Entity_Name|entity_address|entity_city|entity_state|entity_zip|entity_phone|entity_tin|entity_NER|entity_watchlist_flag|exact_search_Note_ID|exact_search_Matched_Watchlist_Entity_Name|GenAI_Note_ID|GenAI_entityNameCleaned|GenAI_tok_sort_similarity|Watchlist_Entity_ID|Watchlist_Entity_Name|Watchlist_Address|Watchlist_State|Watchlist_Zip_Code|Watchlist_Phone|Watchlist_TIN".split("|")
CLAIM = "123456-123456-12-12"


def xlsx(sheet_xml, shared=None):
    """Independent minimal SpreadsheetML fixture with a nondefault sheet path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Client" sheetId="7" r:id="rId7"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/client.xml"/></Relationships>')
        z.writestr("xl/worksheets/client.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + sheet_xml + '</sheetData></worksheet>')
        z.writestr("xl/styles.xml", '<styleSheet><numFmts><numFmt numFmtId="164" formatCode="00000"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>')
        if shared:
            z.writestr("xl/sharedStrings.xml", '<sst>' + ''.join('<si><t>' + escape(s) + '</t></si>' for s in shared) + '</sst>')
    return buf.getvalue()


def inline_row(number, values):
    return '<row>' + ''.join(f'<c r="{chr(65+i)}{number}" t="inlineStr"><is><t>{escape(v)}</t></is></c>' for i, v in enumerate(values)) + '</row>'


class ClientImport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def csv_file(self, name, headers, rows):
        path = self.root / name
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def test_exact_client_headers_and_original_cells(self):
        values = [CLAIM, "GenAI_only", "legal", "attorney", "Ada", "Road", "Town", "IL", "00123", "0012345678", "001234567", "PERSON", "yes", "0000000123.0", "Ada", "0000000123.0, 1234567890.0", "Ada Cleaned", "93", "W1", "Ada", "Road", "IL", "00123", "0012345678", "001234567"]
        path = self.csv_file("client.csv", HEADERS, [values])
        rows, warnings, _ = firm.load([path])
        self.assertEqual(len(rows), 1)
        d = rows[0]["data"]
        self.assertEqual(d["recordType"], "GenAI_only")
        self.assertEqual(d["GenAI_entityNameClearned"], "Ada Cleaned")
        self.assertEqual(d["entity_category_name"], "legal")
        self.assertEqual(d["entity_NER_tag"], "PERSON")
        self.assertEqual(d["entity_TIN"], "001234567")
        self.assertEqual(d["entity_zip_code"], "00123")
        self.assertTrue(firm.is_flagged(d))
        self.assertEqual(d["GenAI_Note_ID"], values[15])
        self.assertEqual(firm.cited_notes(d), ["0000000123", "1234567890"])
        self.assertEqual(len(warnings), 1)  # no Watchlist_City supplied
        self.assertIn("watchlist_city", warnings[0])

    def test_token_normalization_is_text_only_and_not_overbroad(self):
        self.assertEqual(firm.note_ids(" 0012345678.0,0012345678.00,,123.5, N01.0,123 "),
                         ["0012345678", "123.5", "N01.0", "123"])

    def test_real_xlsx_aliases_and_sparse_cells(self):
        path = self.root / "client_entity_data.xlsx"
        path.write_bytes(xlsx(inline_row(1, ["Claim_Number", "Entity_Name", "GenAI_Note_ID", "entity_zip"]) +
                              '<row><c r="A2" t="s"><v>0</v></c><c r="C2" t="s"><v>1</v></c><c r="D2" s="1"><v>123</v></c></row>',
                              [CLAIM, "1234567890.0, 2345678901.0"]))
        rows, _, _ = firm.load([path])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"]["entity_name"], "")
        self.assertEqual(rows[0]["data"]["entity_zip_code"], "00123")
        self.assertEqual(firm.cited_notes(rows[0]["data"]), ["1234567890", "2345678901"])

    def test_formula_without_cached_value_warns_instead_of_empty_data(self):
        path = self.root / "formula.xlsx"
        path.write_bytes(xlsx('<row><c r="A1"><f>1+1</f></c></row>'))
        rows, warnings, _ = firm.load([path])
        self.assertEqual(rows, [])
        self.assertIn("formula has no saved value", warnings[0])

    def test_cached_formula_and_excel_error(self):
        data = xlsx('<row><c r="A1"><f>1+1</f><v>2</v></c></row>')
        self.assertEqual(list(workbook.tables(data))[0][1], [["2"]])
        with self.assertRaisesRegex(ValueError, "Excel error"):
            list(workbook.tables(xlsx('<row><c r="A1" t="e"><v>#REF!</v></c></row>')))

    def test_csv_multiline_values_and_repeated_claims_across_files(self):
        one = self.csv_file("one.csv", ["claim_number", "entity_name"], [[CLAIM, "Ada\nMonroe"]])
        two = self.csv_file("two.csv", ["claim_number", "entity_name"], [[CLAIM, "Bob"]])
        rows, _, _ = firm.load([one, two])
        self.assertEqual([r["id"] for r in rows], [CLAIM + "#1", CLAIM + "#2"])
        self.assertEqual(rows[0]["data"]["entity_name"], "Ada\nMonroe")

    def test_ambiguous_header_aliases_are_rejected(self):
        path = self.csv_file("bad.csv", ["Claim_Number", "claim_number", "Entity_Name"], [[CLAIM, CLAIM, "Ada"]])
        rows, warnings, _ = firm.load([path])
        self.assertEqual(rows, [])
        self.assertIn("ambiguous", warnings[0])

    def test_shared_note_id_keeps_claim_work_separate_and_citations_local(self):
        packet = self.root / "oko_gt_notes_data"
        packet.mkdir()
        other = "654321-654321-21-21"
        for claim in [CLAIM, other]:
            (packet / f"{claim}_1234567890.txt").write_text("Ada called.", encoding="utf-8")
        (packet / f"{other}_2345678901.txt").write_text("Other claim only.", encoding="utf-8")
        path = self.csv_file("client.csv", ["Claim_Number", "Entity_Name", "GenAI_Note_ID"],
                             [[CLAIM, "Ada", "1234567890.0,2345678901.0"]])
        store = Store(self.root / "test.sqlite3")
        self.addCleanup(store.db.close)
        app = App(store, Config(packet, [path]))
        app.entity_create({"claim": CLAIM, "note": "1234567890", "reviewer": "SME", "start": 0, "end": 3, "label": "Ada", "type": "person"})
        self.assertEqual(app.note({"claim": other, "note": "1234567890", "reviewer": "SME"})["records"], [])
        with store.tx() as db:
            db.execute("INSERT INTO claim_seal(claim,reviewer,sealed_at) VALUES (?,?,?)", (CLAIM, "SME", "test"))
        result = app.compare({"claim": CLAIM, "reviewer": "SME"})
        self.assertEqual(result["rows"][0]["cited"], ["1234567890", "2345678901"])
        self.assertEqual(result["notes"], ["1234567890"])


if __name__ == "__main__":
    unittest.main()
