"""The librarian: decide whether a query is a lookup or a question, and answer questions.

ask_events() runs one query as the steps that really happen, and the server streams
them to the page as they happen. A lookup opens a dossier; a question gets an answer
built only from a retrieved subgraph and source passages, citing every claim it makes with
aliases ([e3], [a12], [p4]) the interface
turns into links. No citation, no claim: the prompt says so, and any alias the
answer uses that was not in the retrieved facts is dropped before it reaches the
screen.

Routing is cheap first: a short query that strongly matches a known entity,
identifier, note or claim is a lookup without asking a model. Only the rest go to
the model. With no key configured, everything that is not an obvious lookup is
answered as "no model configured" plus the retrieved facts, so the app stays usable.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class Model:
    """Minimal provider adapter. The key stays in this process; the browser never sees it."""

    def __init__(self, enabled=True):
        self.provider = None
        self.gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")) if enabled else None
        # answers need the stronger model; routing is a one-word decision
        self.gemini_model = os.environ.get("LIBRARIAN_MODEL", "gemini-3.5-flash")
        self.router_model = os.environ.get("LIBRARIAN_ROUTER_MODEL", "gemini-3.1-flash-lite")
        if self.gemini_key:
            self.provider = "gemini"

    @property
    def available(self):
        return self.provider is not None

    def json_call(self, system, user, schema, max_tokens=4096, timeout=180, model=None):
        if self.provider == "gemini":
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens + 8192,
                                         "responseMimeType": "application/json",
                                         "responseSchema": schema}}
            req = urllib.request.Request(
                GEMINI_URL.format(model=model or self.gemini_model), data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": self.gemini_key})
            d = None
            for attempt in range(4):         # a rate limit is a wait, not an answer
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        d = json.loads(r.read())
                    break
                except urllib.error.HTTPError as e:
                    body_txt = e.read().decode("utf-8", "replace")
                    if e.code not in (429, 500, 503) or attempt == 3 or "per_day" in body_txt:
                        raise RuntimeError(f"Gemini HTTP {e.code}: {body_txt[:300]}") from None
                    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', body_txt)
                    time.sleep(float(m.group(1)) + 1 if m else 2 ** attempt * 2)
            parts = d["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return json.loads(text)
        raise RuntimeError("no model configured")


ROUTE_SCHEMA = {"type": "object", "properties": {
    "mode": {"type": "string", "enum": ["lookup", "question"]},
    "lookup_text": {"type": "string", "nullable": True,
                    "description": "For a lookup: the name, identifier, note or claim to open."}},
    "required": ["mode", "lookup_text"], "propertyOrdering": ["mode", "lookup_text"]}

ANSWER_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"},
    "confidence_note": {"type": "string", "nullable": True}},
    "required": ["answer", "confidence_note"], "propertyOrdering": ["answer", "confidence_note"]}

ROUTE_SYSTEM = (
    "You route a search box for insurance-fraud investigators. Decide whether the input is a "
    "LOOKUP (the user wants to open one specific party, identifier, note or claim — e.g. a "
    "name, an NPI, a phone number) or a QUESTION (anything asking for a relationship, a "
    "pattern, a comparison, a count, or an explanation). For a lookup, return the text to "
    "look up, trimmed of filler words.")

ANSWER_SYSTEM = (
    "You answer an investigator's question using ONLY the facts provided. Each fact starts "
    "with an alias in brackets, like [e3] for an entity, [a12] for an action with its source "
    "quote, or [p4] for a PASSAGE of source text. Passages are the notes' own words around the "
    "question's terms and the matched parties: read them for relationships the extracted facts "
    "miss (who a group consists of, who acted for whom), and cite the passage for anything taken "
    "from it. Cite the alias right after every statement it supports, e.g. 'Nexray billed "
    "Allstate [e2][a7].' Never state anything that no fact supports; if the facts do not "
    "answer the question, say what is missing. Entities are merged views: when a fact shows "
    "merge_basis=['name_only'], say that the identity rests on the name alone. Mention "
    "NOT-MERGED LINK facts when they bear on the question. Be concise: a few short paragraphs "
    "or a short list. Plain text, no markdown headings.")


QUESTION_RE = re.compile(r"\?\s*$|^\s*(who|what|which|where|when|why|how|is|are|does|do|did|"
                         r"can|should|list|show|compare|find)\b", re.I)


def is_obvious_lookup(query, suggestions):
    q = query.strip()
    if not suggestions or "?" in q or len(q.split()) > 6:
        return None
    top = suggestions[0]
    if top["score"] >= 2.5 or (top["kind"] == "entity" and top["score"] >= 3.0):
        return top
    return None


def ask_events(query, run, model, lens="default"):
    """The whole ask, as the steps that really happen, one event per step: the routing
    decision, what retrieval matched and added, what was sent, the model call with its
    duration, and the citation check. The last event is always {"step": "result", ...}.
    Nothing here is decorative: a step that did not run is not reported."""
    t0 = time.time()

    def ev(step, **kw):
        return {"step": step, "t": round(time.time() - t0, 2), **kw}

    sugg = run.suggest(query)
    hit = is_obvious_lookup(query, sugg)
    if hit:
        yield ev("route", decision="lookup", by="match",
                 text=f"Matches {hit['label']} ({hit['kind']}) directly: opening it, no model needed.")
        yield ev("result", mode="lookup", target=hit, routed_by="match")
        return
    if QUESTION_RE.search(query):
        routed = "phrasing"
        yield ev("route", decision="question", by="phrasing", text="Phrased as a question: answering from the graph.")
    elif not model.available:
        routed = "no_model"
        yield ev("route", decision="question", by="no_model",
                 text="Not a clear lookup, and no model is configured to route it: treated as a question.")
    else:
        yield ev("model_start", purpose="routing", model=model.router_model)
        t1 = time.time()
        try:
            r = model.json_call(ROUTE_SYSTEM, query, ROUTE_SCHEMA, max_tokens=256, timeout=90,
                                model=model.router_model)
            yield ev("model_done", purpose="routing", model=model.router_model, seconds=round(time.time() - t1, 1))
        except Exception as ex:
            r = {}
            yield ev("model_failed", purpose="routing", error=f"{type(ex).__name__}: {ex}"[:300],
                     seconds=round(time.time() - t1, 1))
        if r.get("mode") == "lookup" and r.get("lookup_text"):
            s = run.suggest(r["lookup_text"])
            if s:
                yield ev("route", decision="lookup", by="model",
                         text=f"The routing model read it as a lookup of “{r['lookup_text']}”: opening {s[0]['label']}.")
                yield ev("result", mode="lookup", target=s[0], routed_by="model")
                return
        routed = "model" if r else "route_failed"
        yield ev("route", decision="question", by=routed,
                 text="The routing model read it as a question." if r else "Routing failed: treated as a question.")

    stats = {}
    facts, alias = run.retrieve(query, lens, stats=stats)
    seeds = stats.get("seeds", [])
    yield ev("match", n=len(seeds), entities=seeds[:8], by_words=stats.get("matched_by_words"),
             text=(f"Matched {len(seeds)} part{'y' if len(seeds) == 1 else 'ies'} by the words of the question"
                   if stats.get("matched_by_words") else
                   "No party matched the question's words: starting from the most-mentioned parties") + ".")
    yield ev("expand", added=stats.get("hop_added", 0), names=stats.get("hop_names", []),
             actions=stats.get("actions_sent", 0), actions_found=stats.get("actions_found", 0),
             links=stats.get("not_merged_links", 0), flags=stats.get("flag_facts", 0),
             text=f"One hop out: {stats.get('hop_added', 0)} co-participant(s) added, "
                  f"{stats.get('actions_sent', 0)} action(s) with source quotes, "
                  f"{stats.get('not_merged_links', 0)} not-merged link(s), "
                  f"{stats.get('flag_facts', 0)} flag(s) for review.")
    if stats.get("passages"):
        yield ev("passages", n=stats["passages"], notes=stats.get("passage_notes", []),
                 text=f"Read {stats['passages']} source passage(s) around the question's words and the "
                      f"matched parties, from {len(stats.get('passage_notes', []))} note(s).")
    yield ev("facts", n=len(facts), facts=facts, text=f"{len(facts)} facts assembled at lens {lens}.")
    base = {"mode": "answer", "question": query, "lens": lens, "facts_used": len(facts),
            "routed_by": routed}
    if not model.available:
        yield ev("model_skip", text="No model is configured: no answer is written, only the facts above.")
        yield ev("result", **base, answer="No model is configured, so this is not an answer — only the "
                 "facts retrieved for your question. Set GEMINI_API_KEY to enable answers.",
                 citations=alias, facts=facts[:40], no_model=True)
        return
    user = f"QUESTION: {query}\n\nFACTS:\n" + "\n".join(facts)
    yield ev("model_start", purpose="answer", model=model.gemini_model, facts=len(facts))
    t1 = time.time()
    try:
        r = model.json_call(ANSWER_SYSTEM, user, ANSWER_SCHEMA, max_tokens=2048)
    except Exception as ex:
        yield ev("model_failed", purpose="answer", error=f"{type(ex).__name__}: {ex}"[:300],
                 seconds=round(time.time() - t1, 1))
        yield ev("result", **base, answer=f"The model call failed ({type(ex).__name__}: {ex}). "
                 "Nothing below is an answer.", citations={}, error=True, facts=facts[:40])
        return
    secs = round(time.time() - t1, 1)
    yield ev("model_done", purpose="answer", model=model.gemini_model, seconds=secs)
    text = r.get("answer", "")
    used = set(re.findall(r"\[([eap]\d+)\]", text))
    unknown = used - set(alias)
    for u in unknown:                         # a citation to nothing is removed, not rendered
        text = text.replace(f"[{u}]", "")
    yield ev("citations", checked=len(used), kept=len(used - unknown), dropped=sorted(unknown),
             text=f"{len(used)} citation(s) checked against the facts sent; "
                  f"{len(unknown)} pointed at nothing and were removed.")
    yield ev("result", **base, answer=text, confidence_note=r.get("confidence_note"),
             citations={k: v for k, v in alias.items() if k in used},
             dropped_citations=sorted(unknown), seconds=secs, facts=facts[:40])
