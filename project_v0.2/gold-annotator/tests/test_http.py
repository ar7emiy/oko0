"""The real HTTP server: routing, error shape, headers, static files, export download."""
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from annotator.server import serve  # noqa: E402
from test_app import make_app  # noqa: E402


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.app = make_app(cls.tmp)
        cls.httpd = serve(cls.app, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.app.store.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, dict(r.headers), r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_index_and_headers(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body[:200].lower())
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_static_assets_have_right_types(self):
        for path, ctype in (("/app.js", "javascript"), ("/app.css", "text/css")):
            status, headers, _ = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(ctype, headers["Content-Type"])

    def test_path_traversal_is_refused(self):
        for bad in ("/../run.py", "/static/../annotator/server.py", "/%2e%2e/run.py"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(bad)
            self.assertEqual(ctx.exception.code, 404)

    def test_user_errors_come_back_as_readable_json(self):
        status, body = self.post("/api/record/create", {"claim": "C201", "note": "N01", "reviewer": "",
                                                         "kind": "unclear", "start": 0, "end": 3})
        self.assertEqual(status, 400)
        self.assertIn("name", body["error"])

    def test_bad_json_and_unknown_route(self):
        req = urllib.request.Request(self.base + "/api/record/create", data=b"{not json", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        status, _ = self.post("/api/nope", {})
        self.assertEqual(status, 404)

    def test_round_trip_and_export(self):
        status, note = 200, json.loads(self.get("/api/note?claim=C201&note=N01&reviewer=Http%20Tester")[2])
        self.assertEqual(note["text"][:14], "Dr. Ada Monroe")
        status, body = self.post("/api/entity/create", {"claim": "C201", "note": "N01", "reviewer": "Http Tester",
                                                         "start": 0, "end": 14, "label": "Dr. Ada Monroe",
                                                         "type": "person"})
        self.assertEqual(status, 200, body)
        status, headers, data = self.get("/api/export?reviewer=Http%20Tester")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertTrue(data.startswith(b"PK"))

    def test_claim_review_routes_and_blind_export(self):
        status, _, body = self.get("/api/claim/review?claim=C201&reviewer=Review%20Tester")
        self.assertEqual(status, 200)
        self.assertNotIn("firm_rows", json.loads(body))
        status, body = self.post("/api/category/save", {"claim":"C201", "reviewer":"Review Tester", "entity_id":"fake"})
        self.assertEqual(status, 400)
        self.assertIn("Finish every note", body["error"])
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/export")
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
