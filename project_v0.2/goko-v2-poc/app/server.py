"""GOKO search app: a local, read-only server over one pipeline run.

    python app/server.py --run poc_output/courtlistener          # then open http://127.0.0.1:8765

The model key is read from the environment (GEMINI_API_KEY) or from the repository's
.env file, and never leaves this process.
"""
import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # goko/
sys.path.insert(0, str(HERE))

from graph import Run                          # noqa: E402
import librarian                               # noqa: E402
from goko.net import prefer_ipv4               # noqa: E402

prefer_ipv4()

STATIC = HERE / "static"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def load_dotenv():
    for p in [HERE.parent / "settings.env", *[d / ".env" for d in HERE.parents]]:
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    run = None
    model = None

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), TYPES[".html"])
        if u.path.startswith("/static/"):
            f = (STATIC / u.path[len("/static/"):]).resolve()
            if STATIC in f.parents and f.exists():
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            return self._send(404, {"error": "not found"})
        if u.path == "/api/meta":
            r = self.run
            return self._send(200, {"claims": sorted({m["claim_id"] for m in r.mentions.values()}),
                                    "mentions": len(r.mentions), "links": len(r.links),
                                    "notes": len(r.notes), "model": self.model.provider,
                                    "run": r.info})
        if u.path == "/api/suggest":
            return self._send(200, self.run.suggest(q.get("q", "")))
        if u.path == "/api/view":
            span = json.loads(q["span"]) if q.get("span") else None
            v = self.run.view(q.get("kind"), q.get("id"), q.get("lens", "default"), span)
            return self._send(200, v) if v else self._send(404, {"error": "nothing found"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/ask":
            query = (body.get("q") or "").strip()
            if not query:
                return self._send(400, {"error": "empty query"})
            r = librarian.route(query, self.run, self.model)
            if r["mode"] == "lookup":
                t = r["target"]
                v = self.run.view(t["kind"], t["id"], body.get("lens", "default"))
                return self._send(200, {"mode": "lookup", "routed_by": r["routed_by"], "view": v})
            a = librarian.answer(query, self.run, self.model, body.get("lens", "default"))
            return self._send(200, {**a, "routed_by": r["routed_by"]})
        return self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(HERE.parent / "poc_output" / "courtlistener"))
    ap.add_argument("--notes", help="notes folder, if the run has no run_info.json")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    load_dotenv()
    Handler.run = Run(a.run, a.notes)
    Handler.model = librarian.Model()
    r = Handler.run
    print(f"run {a.run}: {len(r.mentions)} mentions, {len(r.links)} links, {len(r.notes)} notes; "
          f"librarian model: {Handler.model.provider or 'none (lookups only)'}")
    print(f"open http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
