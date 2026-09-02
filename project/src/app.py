"""Notebook 08 engine: lookup + NL query app.

- Name search -> fuzzy match over entity profiles -> full dossier.
- Evidence items are CLICKABLE: the exported viewer opens the raw note with the
  exact span highlighted and scrolled into view, machine_annotation alongside.
- NL question box: Gemini (online) / deterministic parser (offline) translates the
  question into a STRUCTURED query plan (contracts.query_plan_schema). The plan is
  executed by deterministic code over the entity/attribute/identifier/link tables.
  The LLM plans; the tables answer -- answers are never generated straight from the
  model. The generated plan is shown for verification.

Everything renders as a self-contained HTML page (works in Colab via Gradio and
as a static snapshot export). Gradio is imported lazily so this module imports
fine without it.
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict

from . import contracts, genai, textnorm
from .repository import Repository
from .settings import Paths, genai_mode

EXAMPLE_QUESTIONS = [
    "Show all attorneys and everything we know about them.",
    "Is there an attorney with an email ending @xyzlawgroup.com working on claims?",
    "Which attorneys share the email domain xyzlawgroup.com across different claims?",
    "Find medical providers that share a building address with another provider.",
    "Which repair shop reused another shop's address and phone (possible phoenix shop)?",
    "Show entities that share a phone number with a different entity.",
    "List every entity appearing on claim CLM0005 and how they are linked.",
    "Where has any entity interacted with the address key tied to a provider?",
    "Find people recorded with more than one distinct address over time.",
    "Show any entity flagged with a Jr/Sr suffix conflict at the same address.",
]


# ---------------------------------------------------------------------------
# In-memory index over dossiers (deterministic executor input)
# ---------------------------------------------------------------------------
class EntityIndex:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.dossiers = {d["entity_id"]: d for d in repo.all_dossiers()}
        self.by_identifier = defaultdict(set)
        for eid, d in self.dossiers.items():
            idn = d.get("identity", {})
            for e in idn.get("emails", []):
                self.by_identifier[("email", e)].add(eid)
                dom = textnorm.email_domain(e)
                if dom:
                    self.by_identifier[("email_domain", dom)].add(eid)
            for e in idn.get("email_domains", []):
                self.by_identifier[("email_domain", e)].add(eid)
            for p in idn.get("phones", []):
                self.by_identifier[("phone", p)].add(eid)
                self.by_identifier[("phone_last7", textnorm.phone_last7(p))].add(eid)
            for a in idn.get("addresses", []):
                self.by_identifier[("address_key", a)].add(eid)
            for n in idn.get("npis", []):
                self.by_identifier[("npi", n)].add(eid)
            for t in idn.get("tins", []):
                self.by_identifier[("tin", t)].add(eid)

    def search_name(self, query: str, k: int = 10):
        q = textnorm.normalize_name(query)
        scored = []
        for eid, d in self.dossiers.items():
            name = d.get("canonical_name", "")
            s = textnorm.token_set_jw(q, name)
            if s > 0.4:
                scored.append((s, eid))
        scored.sort(reverse=True)
        return [eid for _, eid in scored[:k]]


# ---------------------------------------------------------------------------
# Query planning (Gemini online / deterministic offline)
# ---------------------------------------------------------------------------
CLASS_WORDS = {
    "attorney": "attorney", "attorneys": "attorney", "counsel": "attorney", "lawyer": "attorney",
    "claimant": "claimant", "claimants": "claimant",
    "provider": "medical_provider", "providers": "medical_provider", "physician": "medical_provider",
    "doctor": "medical_provider", "medical": "medical_provider",
    "shop": "repair_shop", "shops": "repair_shop", "repair": "repair_shop",
    "adjuster": "adjuster", "adjusters": "adjuster", "rep": "adjuster",
}


def plan_query(question: str) -> dict:
    prompt = (
        "Translate the user's question about an insurance-claim entity graph into a "
        "STRUCTURED query plan (do NOT answer it). Fields: intent(find_entities|"
        "describe_entity|find_links), target_class, filters[{field,op,value}], "
        "link_via[], cross_reference, want(dossier|list|count).\n"
        f"Question: {question}"
    )

    def offline():
        return _offline_plan(question)

    return genai.generate_json(prompt, contracts.query_plan_schema(),
                               task="query_plan", offline_handler=offline)


def _offline_plan(question: str) -> dict:
    q = question.lower()
    plan = {"intent": "find_entities", "target_class": "any", "filters": [],
            "link_via": [], "cross_reference": "", "want": "list"}
    for w, cls in CLASS_WORDS.items():
        if re.search(rf"\b{w}\b", q):
            plan["target_class"] = cls
            break
    # email domain
    m = re.search(r"@([a-z0-9.\-]+\.[a-z]{2,})", q) or re.search(r"ending\s+([a-z0-9.\-]+\.[a-z]{2,})", q)
    if m:
        plan["filters"].append({"field": "email_domain", "op": "eq", "value": m.group(1).lstrip("@")})
    # claim id
    m = re.search(r"\b(clm\d{3,4})\b", q)
    if m:
        plan["filters"].append({"field": "claim_id", "op": "eq", "value": m.group(1).upper()})
        plan["intent"] = "find_links"
        plan["link_via"] = ["shared_claim"]
    # named entity
    m = re.search(r"named\s+([a-z][a-z'.\- ]+?)(?:[.?]|$)", question, re.I)
    if m:
        plan["filters"].append({"field": "name", "op": "fuzzy", "value": m.group(1).strip()})
        plan["intent"] = "describe_entity"
        plan["want"] = "dossier"
        plan["target_class"] = "any"   # a specific name overrides any class guess
    # link/shared intents
    if "share" in q and ("address" in q or "building" in q):
        plan["link_via"].append("shared_address")
        plan["intent"] = "find_links"
    if "share" in q and "phone" in q:
        plan["link_via"].append("shared_identifier")
        plan["intent"] = "find_links"
    if "phoenix" in q or ("reused" in q and ("address" in q or "phone" in q)):
        plan["link_via"] = ["shared_address"]
        plan["intent"] = "find_links"
        plan["target_class"] = "repair_shop"
    if "domain" in q and "share" in q:
        plan["link_via"].append("same_firm")
        plan["intent"] = "find_links"
    if "more than one" in q and "address" in q:
        plan["filters"].append({"field": "address", "op": "exists", "value": ""})
        plan["cross_reference"] = "multi_address"
    if "jr/sr" in q or "suffix" in q:
        plan["cross_reference"] = "jr_sr_conflict"
    if "interact" in q or "where has" in q:
        plan["intent"] = "find_links"
    return plan


# ---------------------------------------------------------------------------
# Deterministic plan execution
# ---------------------------------------------------------------------------
def execute_plan(index: EntityIndex, plan: dict) -> dict:
    eids = set(index.dossiers.keys())
    tc = plan.get("target_class", "any")
    if tc and tc != "any":
        eids = {e for e in eids if index.dossiers[e].get("class") == tc}

    trace = []
    for f in plan.get("filters", []):
        eids, note = _apply_filter(index, eids, f)
        trace.append(note)

    # link handling
    link_via = plan.get("link_via", [])
    cross = plan.get("cross_reference", "")
    if "shared_claim" in link_via:
        claim = next((f["value"] for f in plan.get("filters", []) if f["field"] == "claim_id"), None)
        if claim:
            eids = {e for e in index.dossiers if claim in index.dossiers[e].get("roles_per_claim", {})}
            trace.append(f"entities on claim {claim}: {len(eids)}")
    if "shared_address" in link_via:
        eids = _entities_sharing(index, eids, "address_key")
        trace.append(f"restricted to entities sharing an address: {len(eids)}")
    if "shared_identifier" in link_via:
        eids = _entities_sharing(index, eids, "phone_last7", also=("email", "npi", "tin"))
        trace.append(f"restricted to entities sharing an identifier: {len(eids)}")
    if "same_firm" in link_via:
        eids = _entities_sharing(index, eids, "email_domain")
        trace.append(f"restricted to entities sharing an email domain: {len(eids)}")
    if cross == "multi_address":
        eids = {e for e in eids if len(index.dossiers[e].get("identity", {}).get("addresses", [])) > 1}
        trace.append(f"entities with >1 distinct address: {len(eids)}")
    if cross == "jr_sr_conflict":
        eids = {e for e in eids if any("jr_sr" in (le.get("annotation", "").lower())
                                       for le in index.dossiers[e].get("linked_entities", []))
                or "jr" in index.dossiers[e].get("canonical_name", "").lower()
                or "sr" in index.dossiers[e].get("canonical_name", "").lower()}
        trace.append("filtered to Jr/Sr suffix cases")

    result = sorted(eids, key=lambda e: -index.dossiers[e].get("n_mentions", 0))
    return {"entity_ids": result, "n": len(result), "trace": trace, "plan": plan}


def _apply_filter(index, eids, f):
    field, op, val = f.get("field"), f.get("op", "eq"), (f.get("value") or "")
    vlow = val.lower()
    keep = set()
    for e in eids:
        d = index.dossiers[e]
        idn = d.get("identity", {})
        hay = []
        if field == "name":
            hay = [d.get("canonical_name", "")]
        elif field in ("email",):
            hay = idn.get("emails", [])
        elif field == "email_domain":
            hay = idn.get("email_domains", []) + [textnorm.email_domain(x) for x in idn.get("emails", [])]
        elif field in ("phone", "phone_last7"):
            hay = idn.get("phones", [])
        elif field in ("address", "address_key"):
            hay = idn.get("addresses", [])
        elif field == "npi":
            hay = idn.get("npis", [])
        elif field == "tin":
            hay = idn.get("tins", [])
        elif field == "role":
            hay = list(d.get("roles_per_claim", {}).values())
        elif field == "claim_id":
            hay = list(d.get("roles_per_claim", {}).keys())
        elif field == "allegation_text":
            hay = [a.get("snippet", "") for a in d.get("facts_vs_allegations", {}).get("allegations", [])]
        elif field == "firm":
            hay = [d.get("canonical_name", "")]
        ok = False
        for h in hay:
            hl = str(h).lower()
            if op == "exists":
                ok = bool(h)
            elif op == "eq":
                ok = hl == vlow or vlow in hl
            elif op == "contains":
                ok = vlow in hl
            elif op == "endswith":
                ok = hl.endswith(vlow)
            elif op == "startswith":
                ok = hl.startswith(vlow)
            elif op == "fuzzy":
                ok = textnorm.token_set_jw(vlow, hl) > 0.7 or vlow in hl
            if ok:
                break
        if ok:
            keep.add(e)
    return keep, f"filter {field} {op} '{val}' -> {len(keep)}"


def _entities_sharing(index, eids, primary, also=()):
    """Keep entities whose identifier is shared with a DIFFERENT entity."""
    fields = (primary,) + tuple(also)
    keep = set()
    for e in eids:
        d = index.dossiers[e]
        idn = d.get("identity", {})
        vals = []
        if primary == "address_key":
            vals = [("address_key", a) for a in idn.get("addresses", [])]
        elif primary == "email_domain":
            vals = [("email_domain", x) for x in idn.get("email_domains", [])]
            vals += [("email_domain", textnorm.email_domain(x)) for x in idn.get("emails", [])]
        else:
            for fld in fields:
                if fld == "phone_last7":
                    vals += [("phone_last7", textnorm.phone_last7(p)) for p in idn.get("phones", [])]
                elif fld == "email":
                    vals += [("email", x) for x in idn.get("emails", [])]
                elif fld == "npi":
                    vals += [("npi", x) for x in idn.get("npis", [])]
                elif fld == "tin":
                    vals += [("tin", x) for x in idn.get("tins", [])]
        for key in vals:
            if len(index.by_identifier.get(key, set())) > 1:
                keep.add(e)
                break
    return keep


# ---------------------------------------------------------------------------
# HTML rendering (self-contained, clickable evidence)
# ---------------------------------------------------------------------------
def _load_notes_for_dossier(dossier: dict) -> dict:
    docs = set()
    for ev in dossier.get("evidence", []):
        docs.add(ev["doc_id"])
    for al in dossier.get("facts_vs_allegations", {}).get("allegations", []):
        docs.add(al["doc_id"])
    notes = {}
    for d in docs:
        p = Paths.raw_notes / f"{d}.txt"
        if p.exists():
            notes[d] = p.read_text(encoding="utf-8")
    return notes


def export_dossier_html(repo: Repository, entity_id: str, out_path=None) -> str:
    """Write a standalone, self-contained HTML snapshot of one dossier.

    Evidence items are clickable: clicking highlights the exact span in the raw
    note viewer, scrolls it into view, and shows the machine_annotation. All raw
    note text needed is embedded, so the file works offline with no server."""
    dossier = repo.get_dossier(entity_id)
    if dossier is None:
        raise KeyError(entity_id)
    notes = _load_notes_for_dossier(dossier)
    payload = json.dumps({"dossier": dossier, "notes": notes})
    page = _HTML_TEMPLATE.replace("__PAYLOAD__", html.escape(payload, quote=True))
    out_path = out_path or (Paths.store / f"dossier_{entity_id}.html")
    from pathlib import Path
    Path(out_path).write_text(page, encoding="utf-8")
    return str(out_path)


_HTML_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Entity Dossier</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;margin:0;color:#1a1a1a;background:#fff}
 .wrap{display:grid;grid-template-columns:1fr 1fr;gap:0;height:100vh}
 .pane{overflow:auto;padding:16px}
 .left{border-right:1px solid #ddd}
 h1{font-size:18px;margin:0 0 8px} h2{font-size:14px;color:#444;margin:16px 0 6px;text-transform:uppercase;letter-spacing:.03em}
 .ev{cursor:pointer;border:1px solid #e2e2e2;border-radius:6px;padding:8px;margin:6px 0;background:#fafafa}
 .ev:hover{background:#eef4ff;border-color:#9db8ff}
 .ann{font-family:ui-monospace,monospace;font-size:11px;color:#555;margin-top:4px;white-space:pre-wrap}
 .snip{font-size:12px;color:#333}
 .alleg{border-left:3px solid #d9822b;background:#fff7ec}
 .fact{border-left:3px solid #2b8a3e}
 .note{white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;line-height:1.5}
 mark{background:#ffe08a;outline:2px solid #f59f00}
 .pill{display:inline-block;background:#eef;border-radius:10px;padding:1px 8px;margin:2px;font-size:11px}
 .link{font-size:12px;color:#333;border:1px solid #eee;border-radius:6px;padding:6px;margin:4px 0}
 .muted{color:#888}
</style></head><body>
<div class="wrap">
 <div class="pane left">
   <h1 id="title"></h1>
   <div id="identity"></div>
   <h2>Roles per claim</h2><div id="roles"></div>
   <h2>Attribute timelines</h2><div id="timelines"></div>
   <h2>Linked entities</h2><div id="linked"></div>
   <h2>Allegations <span class="muted">(segregated from facts)</span></h2><div id="allegations"></div>
   <h2>Evidence <span class="muted">(click to trace)</span></h2><div id="evidence"></div>
 </div>
 <div class="pane">
   <h2>Raw note viewer <span id="viewerdoc" class="muted"></span></h2>
   <div id="annbox" class="ann"></div>
   <div id="note" class="note muted">Click an evidence item to view its source span.</div>
 </div>
</div>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
const raw = document.getElementById('data').textContent;
const doc = new DOMParser().parseFromString(raw,'text/html').documentElement.textContent;
const P = JSON.parse(doc);
const D = P.dossier, NOTES = P.notes;
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
document.getElementById('title').textContent = D.canonical_name+'  ['+D.class+']  ('+D.n_mentions+' mentions, '+D.n_claims+' claims)';
const idn=D.identity||{};
document.getElementById('identity').innerHTML = Object.entries(idn).filter(([k,v])=>v&&v.length)
  .map(([k,v])=>'<div><b>'+k+':</b> '+v.map(x=>'<span class="pill">'+esc(x)+'</span>').join('')+'</div>').join('');
document.getElementById('roles').innerHTML = Object.entries(D.roles_per_claim||{})
  .map(([c,r])=>'<span class="pill">'+esc(c)+': '+esc(r)+'</span>').join('') || '<span class=muted>none</span>';
document.getElementById('timelines').innerHTML = Object.entries(D.attribute_timelines||{})
  .map(([a,rows])=>'<div><b>'+esc(a)+'</b><br>'+rows.map(r=>'<span class="pill">'+esc(r.value)+' ['+r.tier+(r.conflict_flag?' CONFLICT':'')+(r.known_to==='retracted'?' RETRACTED':'')+']</span>').join('')+'</div>').join('');
document.getElementById('linked').innerHTML = (D.linked_entities||[])
  .map(l=>'<div class="link"><b>'+esc(l.canonical_name)+'</b> ['+esc(l.entity_class)+', deg '+l.degree+']<br><span class="ann">'+esc(l.annotation||'')+'</span><br>'+ (l.shared||[]).map(s=>'<span class="pill">'+esc(s)+'</span>').join('')+'</div>').join('') || '<span class=muted>none</span>';
function evItem(ev,cls){
  const div=document.createElement('div'); div.className='ev '+cls;
  div.innerHTML='<div class="snip">'+esc(ev.snippet)+'</div><div class="ann">'+esc(ev.machine_annotation||'')+'</div>';
  div.onclick=()=>showSpan(ev); return div;
}
const evbox=document.getElementById('evidence');
(D.evidence||[]).forEach(ev=>evbox.appendChild(evItem(ev,'fact')));
const albox=document.getElementById('allegations');
((D.facts_vs_allegations||{}).allegations||[]).forEach(ev=>albox.appendChild(evItem(ev,'alleg')));
if(!albox.children.length) albox.innerHTML='<span class=muted>none</span>';
function showSpan(ev){
  const t=NOTES[ev.doc_id]||''; const s=ev.span[0], e=ev.span[1];
  document.getElementById('viewerdoc').textContent='('+ev.doc_id+' ['+s+':'+e+'])';
  document.getElementById('annbox').textContent=ev.machine_annotation||'';
  const note=document.getElementById('note'); note.className='note';
  note.innerHTML=esc(t.slice(0,s))+'<mark id="hl">'+esc(t.slice(s,e))+'</mark>'+esc(t.slice(e));
  const hl=document.getElementById('hl'); if(hl) hl.scrollIntoView({block:'center'});
}
</script></body></html>"""


def answer_question(repo: Repository, index: EntityIndex, question: str) -> dict:
    plan = plan_query(question)
    res = execute_plan(index, plan)
    return {"question": question, "plan": plan, "result": res}


# ---------------------------------------------------------------------------
# Gradio app (lazy import; runs in Colab)
# ---------------------------------------------------------------------------
def build_app(repo: Repository):
    import gradio as gr
    index = EntityIndex(repo)

    def do_name_search(q):
        eids = index.search_name(q)
        if not eids:
            return "No match.", "", "{}"
        html_path = export_dossier_html(repo, eids[0])
        from pathlib import Path
        return (f"Top match: {index.dossiers[eids[0]]['canonical_name']} "
                f"(+{len(eids)-1} more)"), Path(html_path).read_text(encoding="utf-8"), "{}"

    def do_nl(q):
        out = answer_question(repo, index, q)
        ids = out["result"]["entity_ids"]
        listing = "\n".join(f"- {index.dossiers[e]['canonical_name']} [{index.dossiers[e]['class']}]"
                            for e in ids[:25]) or "(no matches)"
        dossier_html = export_and_read(repo, ids[0]) if ids else "<i>no entity</i>"
        return (json.dumps(out["plan"], indent=2), "\n".join(out["result"]["trace"]),
                listing, dossier_html)

    def export_and_read(repo, eid):
        from pathlib import Path
        return Path(export_dossier_html(repo, eid)).read_text(encoding="utf-8")

    with gr.Blocks(title="Entity Intelligence Lookup") as demo:
        gr.Markdown("# Entity Intelligence Lookup\nName search + NL questions (LLM plans, tables answer).")
        with gr.Tab("Name search"):
            nq = gr.Textbox(label="Name")
            nbtn = gr.Button("Search")
            nstatus = gr.Markdown()
            ndoss = gr.HTML()
            nbtn.click(do_name_search, nq, [nstatus, ndoss, gr.State()])
        with gr.Tab("NL question"):
            qq = gr.Textbox(label="Question")
            with gr.Row():
                for ex in EXAMPLE_QUESTIONS:
                    gr.Button(ex, size="sm").click(lambda e=ex: e, None, qq)
            qbtn = gr.Button("Ask")
            with gr.Accordion("Generated query plan (verifiable)", open=False):
                plan_out = gr.Code(language="json")
            trace_out = gr.Textbox(label="Execution trace")
            list_out = gr.Textbox(label="Matching entities")
            doss_out = gr.HTML()
            qbtn.click(do_nl, qq, [plan_out, trace_out, list_out, doss_out])
    return demo
