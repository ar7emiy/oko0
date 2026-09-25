"""GOKO search app: a local, read-only server over one pipeline run.

    python app/server.py --run poc_output/courtlistener          # then open http://127.0.0.1:8765
    python app/server.py --demo                                  # offline demo, opens the browser

The model key is read from the environment (GEMINI_API_KEY) or from the repository's
.env file, and never leaves this process.
"""
import argparse
import difflib
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
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


DEMO = HERE.parent / "demo"


def _qkey(q):
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in q).split())


class Demo:
    """Offline demo: answers recorded from the live system, replayed step by step.

    Nothing here calls a model. A recorded question replays its real events at their
    recorded pace (capped, so a demo never stalls). Any other question still runs the local
    retrieval and says plainly that no answer was recorded for it."""

    MAX_GAP_S = 4.0

    def __init__(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.answers = {_qkey(a["question"]): a for a in data["answers"]}

    def find(self, query):
        k = _qkey(query)
        if k in self.answers:
            return self.answers[k]
        best = max(self.answers, key=lambda x: difflib.SequenceMatcher(None, k, x).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, k, best).ratio() >= 0.9:
            return self.answers[best]
        return None

    def events(self, query, run, lens):
        rec = self.find(query)
        if rec:
            last = 0.0
            for e in rec["events"]:
                time.sleep(min(self.MAX_GAP_S, max(0.0, e.get("t", last) - last)))
                last = e.get("t", last)
                yield e
            return
        offline = librarian.Model(enabled=False)
        for e in librarian.ask_events(query, run, offline, lens):
            if e.get("step") == "model_skip":
                e = {**e, "text": "Offline demo: no model is called. Only recorded questions have answers."}
            if e.get("step") == "result" and e.get("mode") == "answer":
                listed = "\n".join(f"• {a['question']}" for a in self.answers.values())
                e = {**e, "answer": "This is an offline demo, and no answer was recorded for this question. "
                                    "The facts it would be answered from are listed below. Recorded questions:\n"
                                    + listed}
            yield e


class Handler(BaseHTTPRequestHandler):
    run = None
    model = None
    demo = None

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
        if u.path == "/api/entities":
            lens = q.get("lens", "default")
            return self._send(200, {"lens": lens, "entities": self.run.entity_list(lens),
                                    "watchlist": {"source": self.run.watchlist.get("source"),
                                                  "records_on_list": self.run.watchlist.get("records_on_list")}})
        if u.path == "/api/notes":
            return self._send(200, self.run.notes_list())
        if u.path == "/api/suggest":
            return self._send(200, self.run.suggest(q.get("q", "")))
        if u.path == "/api/link":
            v = self.run.link_card(q.get("a"), q.get("b"), q.get("lens", "default"))
            return self._send(200, v) if v else self._send(404, {"error": "no such link"})
        if u.path == "/api/view":
            span = json.loads(q["span"]) if q.get("span") else None
            v = self.run.view(q.get("kind"), q.get("id"), q.get("lens", "default"), span)
            return self._send(200, v) if v else self._send(404, {"error": "nothing found"})
        return self._send(404, {"error": "not found"})

    def _lookup_result(self, e, lens):
        if e.get("step") == "result" and e.get("mode") == "lookup":
            t = e["target"]
            e = {**e, "view": self.run.view(t["kind"], t["id"], lens)}
        return e

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/ask_stream":
            # Server-sent events over one response: each real step as it happens, then the
            # result. The page reads it with fetch(), so nothing reconnects and re-asks.
            query, lens = (body.get("q") or "").strip(), body.get("lens", "default")
            if not query:
                return self._send(400, {"error": "empty query"})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            events = (self.demo.events(query, self.run, lens) if self.demo
                      else librarian.ask_events(query, self.run, self.model, lens))
            try:
                for e in events:
                    e = self._lookup_result(e, lens)
                    self.wfile.write(f"event: {e['step']}\ndata: {json.dumps(e)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass                                   # the reader went away
            except Exception as ex:                    # report, do not hang the page
                err = {"step": "result", "mode": "error", "error": f"{type(ex).__name__}: {ex}"}
                self.wfile.write(f"event: result\ndata: {json.dumps(err)}\n\n".encode("utf-8"))
            return
        if u.path == "/api/ask":
            query = (body.get("q") or "").strip()
            if not query:
                return self._send(400, {"error": "empty query"})
            # the same steps as /api/ask_stream, returned at once with the log attached
            lens = body.get("lens", "default")
            events = (self.demo.events(query, self.run, lens) if self.demo
                      else librarian.ask_events(query, self.run, self.model, lens))
            log = [self._lookup_result(e, lens) for e in events]
            return self._send(200, {**log[-1], "log": log[:-1]})
        return self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(HERE.parent / "poc_output" / "courtlistener"))
    ap.add_argument("--notes", help="notes folder, if the run has no run_info.json")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-model", action="store_true",
                    help="never call a model, whatever keys the environment holds (lookups and "
                         "retrieved facts only)")
    ap.add_argument("--demo", action="store_true",
                    help="offline demo: serve the committed demo run and replay recorded answers; "
                         "never reads keys or calls a model; opens the browser")
    ap.add_argument("--no-browser", action="store_true", help="with --demo: do not open a browser")
    a = ap.parse_args()
    if a.demo:
        a.run, a.notes, a.no_model = str(DEMO / "run"), str(HERE.parent / "corpus" / "courtlistener" / "notes"), True
        Handler.demo = Demo(DEMO / "answers.json")
    if not a.no_model:
        load_dotenv()
    Handler.run = Run(a.run, a.notes)
    Handler.model = librarian.Model(enabled=not a.no_model)
    r = Handler.run
    url = f"http://127.0.0.1:{a.port}"
    print(f"run {a.run}: {len(r.mentions)} mentions, {len(r.links)} links, {len(r.notes)} notes; "
          f"librarian: {'offline demo, ' + str(len(Handler.demo.answers)) + ' recorded answers' if a.demo else Handler.model.provider or 'none (lookups only)'}")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError:
        sys.exit(f"port {a.port} is in use. Close the other server, or add --port 8766")
    print(f"open {url}   (Ctrl+C to stop)")
    if a.demo and not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
