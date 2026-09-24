"use strict";
// GOKO search: one search bar, then a row of windows (at most three visible),
// each with a bubble in the header bar. Read-only; every view comes from the server.

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const maxVisible = () => (window.innerWidth < 900 ? 1 : 3);
const LENS_NOTE = { strict: "identifier-backed links only", default: "any basis, high confidence", broad: "adds weak and partial name matches" };

const state = { wins: [], start: 0, seq: 0 };

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

// ---------------------------------------------------------------- windows
function openWin(win, afterId) {
  win.id = ++state.seq;
  const at = afterId == null ? state.wins.length : state.wins.findIndex((w) => w.id === afterId) + 1;
  state.wins.splice(at, 0, win);
  reveal(win.id);
  return win;
}
function closeWin(id) {
  state.wins = state.wins.filter((w) => w.id !== id);
  state.start = Math.max(0, Math.min(state.start, state.wins.length - maxVisible()));
  render();
}
function reveal(id) {
  const i = state.wins.findIndex((w) => w.id === id);
  const n = maxVisible();
  if (i < state.start) state.start = i;
  else if (i >= state.start + n) state.start = i - n + 1;
  render();
}
function winById(id) { return state.wins.find((w) => w.id === id); }

async function loadView(win, req) {
  Object.assign(win, { kind: "loading", req });
  render();
  try {
    const q = new URLSearchParams({ kind: req.kind, id: req.id, lens: req.lens || "default" });
    if (req.span) q.set("span", JSON.stringify(req.span));
    win.data = await api("/api/view?" + q);
    win.kind = "view";
    win.label = win.label || win.data.title;
  } catch (e) { win.kind = "error"; win.error = e.message; }
  render();
}
function openView(req, label, fromId) {
  const w = openWin({ label, kind: "loading" }, fromId);
  loadView(w, req);
}

async function ask(win, query) {
  Object.assign(win, { kind: "thinking", label: query, query });
  render();
  try {
    const r = await api("/api/ask", { q: query });
    if (r.mode === "lookup" && r.view) {
      win.kind = "view"; win.data = r.view;
      win.req = { kind: r.view.kind, id: r.view.id, lens: r.view.lens || "default" };
    } else { win.kind = "answer"; win.data = r; }
  } catch (e) { win.kind = "error"; win.error = e.message; }
  render();
}

// ---------------------------------------------------------------- search box
function attachSearch(box, onPick, onEnter) {
  const input = $("input", box), list = $(".suggest", box);
  let items = [], active = -1, timer = null, lastQ = "";
  const draw = () => {
    if (!input.value.trim()) { list.hidden = true; return; }
    let html = "", group = null;
    items.forEach((s, i) => {
      if (s.kind !== group) { group = s.kind; html += `<div class="group">${esc({ entity: "Parties", identifier: "Identifiers", claim: "Claims", note: "Notes" }[group])}</div>`; }
      html += `<div class="item${i === active ? " active" : ""}" data-i="${i}"><span>${esc(s.label)}</span><span class="sub">${esc(s.sub)}</span></div>`;
    });
    html += `<div class="item ask${active === items.length ? " active" : ""}" data-i="${items.length}">Ask the librarian: “${esc(input.value.trim())}”</div>`;
    list.innerHTML = html;
    list.hidden = false;
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (q === lastQ) return;
      lastQ = q;
      items = q ? await api("/api/suggest?q=" + encodeURIComponent(q)).catch(() => []) : [];
      active = -1; draw();
    }, 120);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, -1); draw(); e.preventDefault(); }
    else if (e.key === "Escape") { list.hidden = true; }
    else if (e.key === "Enter") {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) return;
      list.hidden = true;
      if (active >= 0 && active < items.length) onPick(items[active], q); else onEnter(q);
    }
  });
  list.addEventListener("mousedown", (e) => {
    const it = e.target.closest(".item");
    if (!it) return;
    e.preventDefault();
    const i = +it.dataset.i;
    list.hidden = true;
    if (i < items.length) onPick(items[i], input.value.trim()); else onEnter(input.value.trim());
  });
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 120));
}

// home search: the first query becomes window 1
attachSearch($("[data-search]", $("#home")),
  (s) => openView({ kind: s.kind, id: s.id, lens: "default" }, s.label),
  (q) => { const w = openWin({ label: q, kind: "thinking" }); ask(w, q); });

$("#plus").addEventListener("click", () => openWin({ label: "New search", kind: "search" }));
$(".rolodex.left").addEventListener("click", () => { state.start = Math.max(0, state.start - 1); render(); });
$(".rolodex.right").addEventListener("click", () => { state.start = Math.min(state.wins.length - maxVisible(), state.start + 1); render(); });
window.addEventListener("resize", () => { state.start = Math.max(0, Math.min(state.start, state.wins.length - maxVisible())); render(); });

// ---------------------------------------------------------------- rendering
function render() {
  // a window redraws only when what it shows changed, so a half-typed search survives
  state.wins.forEach((w) => {
    const sig = w.kind + (w.data ? "+" : "-") + JSON.stringify(w.req || null);
    if (w._sig !== sig) { w._sig = sig; w.ver = (w.ver || 0) + 1; }
  });
  const any = state.wins.length > 0;
  $("#home").hidden = any; $("#bar").hidden = !any; $("#stage").hidden = !any;
  if (!any) { $("#home input").focus(); return; }
  const n = maxVisible(), vis = state.wins.slice(state.start, state.start + n);

  $("#bubbles").innerHTML = state.wins.map((w, i) => {
    const on = i >= state.start && i < state.start + n;
    return `<div class="bubble ${on ? "visible" : "hidden-win"}" data-id="${w.id}" title="${esc(w.label)}">
      <span class="label">${esc(w.label || "…")}</span><button class="x" data-close="${w.id}" aria-label="Close">×</button></div>`;
  }).join("");
  $("#bubbles").querySelectorAll(".bubble").forEach((b) => b.addEventListener("click", (e) => {
    if (e.target.dataset.close) { closeWin(+e.target.dataset.close); return; }
    reveal(+b.dataset.id);
  }));

  const left = $(".rolodex.left"), right = $(".rolodex.right");
  left.hidden = state.start === 0; left.textContent = `‹ ${state.start} more`;
  const after = state.wins.length - state.start - n;
  right.hidden = after <= 0; right.textContent = `${after} more ›`;

  const host = $("#windows");
  const keep = new Map([...host.children].map((el) => [+el.dataset.id, el]));
  host.innerHTML = "";
  vis.forEach((w) => {
    let el = keep.get(w.id);
    if (!el || el.dataset.ver !== String(w.ver)) {
      el = document.createElement("article");
      el.className = "win"; el.dataset.id = w.id;
      draw(el, w);
    }
    el.dataset.ver = w.ver;
    host.appendChild(el);
  });
}

function draw(el, w) {
  if (w.kind === "search") {
    el.innerHTML = `<div class="win-empty"><div class="search" data-search><input type="search" placeholder="Search or ask" autocomplete="off"><div class="suggest" hidden></div></div></div>`;
    attachSearch($("[data-search]", el),
      (s) => { w.label = s.label; loadView(w, { kind: s.kind, id: s.id, lens: "default" }); },
      (q) => ask(w, q));
    setTimeout(() => $("input", el).focus(), 0);
    return;
  }
  if (w.kind === "loading" || w.kind === "thinking") {
    el.innerHTML = `<div class="win-empty"><div class="thinking"><span class="dot"></span>${w.kind === "thinking" ? "The librarian is reading the graph…" : "Loading…"}</div></div>`;
    return;
  }
  if (w.kind === "error") { el.innerHTML = `<div class="win-empty err">${esc(w.error)}</div>`; return; }
  if (w.kind === "answer") return drawAnswer(el, w);
  const d = w.data;
  ({ entity: drawEntity, identifier: drawIdentifier, note: drawNote, claim: drawClaim }[d.kind] || drawEntity)(el, w, d);
  wireLinks(el, w);
}

// clickable references: data-open='{"kind":..,"id":..}'
function ref(kind, id, label, extra = {}) {
  return `<span class="link" data-open='${esc(JSON.stringify({ kind, id, label, ...extra }))}'>${esc(label)}</span>`;
}
function wireLinks(el, w) {
  GOKO.lens = (w.req && w.req.lens) || "default";
  GOKO.wire(el, { open: false });
  el.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", () => {
    const r = JSON.parse(a.dataset.open);
    openView({ kind: r.kind, id: r.id, lens: (w.req && w.req.lens) || "default", span: r.span }, r.label, w.id);
  }));
  el.querySelectorAll("[data-lens]").forEach((b) => b.addEventListener("click", () => {
    loadView(w, { ...w.req, lens: b.dataset.lens });
  }));
  el.querySelectorAll("[data-expand]").forEach((b) => b.addEventListener("click", async () => {
    const box = b.closest(".ev");
    const open = box.querySelector(".fulltext");
    if (open) { open.remove(); b.textContent = "Show in full note"; return; }
    const [note, s, e] = JSON.parse(b.dataset.expand);
    b.textContent = "Loading…";
    const v = await api("/api/view?" + new URLSearchParams({ kind: "note", id: note }));
    const div = document.createElement("div");
    div.className = "fulltext";
    div.innerHTML = esc(v.text.slice(0, s)) + `<mark>${esc(v.text.slice(s, e))}</mark>` + esc(v.text.slice(e));
    box.appendChild(div);
    b.textContent = "Hide full note";
    const m = div.querySelector("mark");
    div.scrollTop = m.offsetTop - div.clientHeight / 3;
  }));
}

function evidence(x) {
  if (!x) return `<div class="ev muted">no source span</div>`;
  return `<div class="ev">${x.clipped_left ? "…" : ""}${esc(x.before)}<mark>${esc(x.match)}</mark>${esc(x.after)}${x.clipped_right ? "…" : ""}
    <div class="src">${ref("note", x.note, x.note.replace("note:", "Note "), { span: x.span })}<span>${esc(x.claim_id)}</span>
    <span class="link" data-expand='${esc(JSON.stringify([x.note, x.span[0], x.span[1]]))}'>Show in full note</span></div></div>`;
}
const pct = (p) => (p == null ? "—" : p >= 0.9995 ? "1.00" : p.toFixed(2));
const basisChip = (b) => {
  const label = { identifier: "identifier", address: "address", dob: "name + date of birth", co_party: "name + anchored co-party", location: "name + location", name_only: "name only", none: "no agreement" }[b] || b;
  const cls = b === "identifier" ? "good" : b === "name_only" || b === "co_party" ? "warn" : "";
  return `<span class="chip ${cls}">${esc(label)}</span>`;
};
function lensBar(d) {
  return `<div><div class="lens">${d.lenses.map((l) => `<button data-lens="${l}" class="${l === d.lens ? "on" : ""}">${l[0].toUpperCase() + l.slice(1)}</button>`).join("")}</div>
    <span class="lens-note">${esc(LENS_NOTE[d.lens])}</span></div>`;
}

function drawEntity(el, w, d) {
  const conf = d.confidence == null ? `<span class="chip">single mention</span>`
    : `<span class="chip ${d.confidence >= 0.9 ? "good" : d.confidence >= 0.5 ? "" : "bad"}">weakest link ${pct(d.confidence)}</span>`;
  const cats = d.categories.map((c) => JSON.parse(c)).map((c) => `<span class="chip">${esc(c.value)}${c.subcategory ? " · " + esc(c.subcategory) : ""}</span>`).join("");
  let h = `<div class="win-head"><h1 class="title">${esc(d.title)}</h1>
    <div class="meta"><span>${esc(d.type)}</span><span>·</span>
    <span>${d.claims.map((c) => ref("claim", c, c)).join(", ")}</span>${d.flagged && d.flagged.length ? `<span class="chip bad" title="At this lens a mention of this party links to a record on the OIG exclusion list (LEIE). A lead to check, not a finding.">Flagged for review</span>` : ""}</div>
    ${GOKO.summaryHTML(d)}${GOKO.categoryHTML(d)}
    ${lensBar(d)}</div><div class="win-body">`;
  if (d.flagged && d.flagged.length) h += `<section class="block"><h2 title="Records on the OIG exclusion list that a mention of this party links to, admitted at this lens">Flagged for review — OIG exclusion list</h2>${d.flagged.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.watchlist_near && d.watchlist_near.length) h += `<section class="block"><h2 title="Watchlist links below this lens's threshold, or vetoed. They do not flag the entity here.">Exclusion-list links this lens does not admit</h2>${d.watchlist_near.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.details.length) {
    h += `<section class="block"><h2>Identifiers</h2>`;
    d.details.forEach((x) => {
      h += `<div class="card"><div class="row"><span class="chip">${esc(x.type.replaceAll("_", " "))}</span><span class="grow">${ref("identifier", x.ident, x.raw)}</span>
        <span class="muted">${esc(x.basis || "")}${x.checksum && x.checksum !== "n/a" ? " · checksum " + esc(x.checksum) : ""}</span></div>
        ${x.shared_with.length ? `<div class="muted" style="margin-top:4px">Also held by ${x.shared_with.map((s) => ref(s.kind, s.id, s.name)).join(", ")}</div>` : ""}
        ${x.evidence.slice(0, 2).map(evidence).join("")}</div>`;
    });
    h += `</section>`;
  }
  h += `<section class="block"><h2>Mentions (${d.members.length})</h2>`;
  d.members.forEach((m) => {
    const j = m.joined_by ? `<span class="muted">joined via “${esc(m.joined_by.with_name)}” · ${pct(m.joined_by.p)} · ${esc(m.joined_by.basis_class.replace("_", " "))} · ${esc(m.joined_by.distance.replace("_", " "))}</span>` : `<span class="muted">first mention</span>`;
    h += `<div class="card"><div class="row"><strong class="grow">${esc(m.name)}</strong>${j}</div>${evidence(m.evidence)}</div>`;
  });
  h += `</section>`;
  if (d.related.length) {
    h += `<section class="block"><h2>Appears with</h2><div class="meta">${d.related.slice(0, 16).map((r) => `<span class="chip">${ref(r.kind, r.id, r.name)} ×${r.count}</span>`).join("")}</div></section>`;
  }
  if (d.actions.length) {
    h += `<section class="block"><h2>Actions (${d.actions.length})</h2>`;
    d.actions.slice(0, 40).forEach((a) => {
      h += `<div class="card"><div class="row"><strong>${esc(a.type.replaceAll("_", " "))}</strong><span class="muted">as ${esc(a.role)}</span>
        ${a.stance && a.stance !== "asserted" ? `<span class="chip warn">${esc(a.stance)}</span>` : ""}${a.time ? `<span class="muted">${esc(a.time)}</span>` : ""}</div>
        ${a.others.length ? `<div class="muted">with ${a.others.map((o) => `${ref(o.kind, o.id, o.name)} (${esc(o.role)})`).join(", ")}</div>` : ""}
        ${evidence(a.evidence)}</div>`;
    });
    if (d.actions.length > 40) h += `<p class="muted">${d.actions.length - 40} more not shown.</p>`;
    h += `</section>`;
  }
  h += GOKO.candidatesHTML(d.candidates, d.lens);
  if (d.refused.length) h += `<section class="block"><h2>Refused merges</h2>${d.refused.map((r) => `<div class="muted">${esc(r.reason)}: ${esc(r.a)} / ${esc(r.b)}</div>`).join("")}</section>`;
  el.innerHTML = h + `</div>`;
}

function drawIdentifier(el, w, d) {
  let h = `<div class="win-head"><h1 class="title mono">${esc(d.title)}</h1>
    <div class="meta"><span class="chip">${esc(d.detail_type)}</span><span>${d.evidence.length} occurrence(s)</span><span>·</span><span>${d.claims.map((c) => ref("claim", c, c)).join(", ")}</span>
    ${d.suspicion ? `<span class="chip bad">shared across ${esc(d.distance.replaceAll("_", " "))}</span>` : ""}</div></div><div class="win-body">`;
  h += `<section class="block"><h2>Held by</h2>${d.holders.length ? d.holders.map((x) => `<div class="card row"><span class="grow">${ref(x.kind, x.id, x.name)}</span><span class="muted">${esc(x.type)} · ${x.claims.join(", ")}</span></div>`).join("") : `<p class="muted">No owner was assigned.</p>`}
    ${d.unassigned ? `<p class="muted">${d.unassigned} occurrence(s) with no owner (UNASSIGNED).</p>` : ""}</section>`;
  h += `<section class="block"><h2>Evidence</h2>${d.evidence.map(evidence).join("")}</section>`;
  el.innerHTML = h + `</div>`;
}

function drawNote(el, w, d) {
  let h = `<div class="win-head"><h1 class="title">${esc(d.title)}</h1><div class="meta">${ref("claim", d.claim_id, d.claim_id)}<span>·</span><span>${d.chars.toLocaleString()} characters</span>
    ${d.extraction_error ? `<span class="chip bad">extraction partial</span>` : ""}</div></div><div class="win-body">`;
  const seen = new Set();
  const ents = d.entities.filter((e) => !seen.has(e.id) && seen.add(e.id));
  h += `<section class="block"><h2>Parties in this note (${ents.length})</h2><div class="meta">${ents.map((e) => `<span class="chip">${ref(e.kind, e.id, e.name)}</span>`).join("")}</div></section>`;
  const t = d.text, s = d.highlight;
  const body = s ? esc(t.slice(0, s[0])) + `<mark>${esc(t.slice(s[0], s[1]))}</mark>` + esc(t.slice(s[1])) : esc(t);
  h += `<section class="block"><h2>Text</h2><div class="fulltext note-full">${body}</div></section>`;
  el.innerHTML = h + `</div>`;
  const m = el.querySelector("mark");
  if (m) setTimeout(() => { const box = m.closest(".win-body"); box.scrollTop = m.offsetTop - box.clientHeight / 3; }, 0);
}

function drawClaim(el, w, d) {
  let h = `<div class="win-head"><h1 class="title">${esc(d.title)}</h1><div class="meta"><span>${d.entities.length} parties</span><span>·</span><span>${d.notes.length} notes</span></div>
    ${lensBar({ ...d, lenses: ["strict", "default", "broad"] })}</div><div class="win-body">`;
  h += `<section class="block"><h2>Parties</h2>${d.entities.map((e) => `<div class="card"><div>${ref(e.kind, e.id, e.name)}</div>
      <div class="meta" style="margin-top:4px"><span>${esc(e.type)} · ${e.mentions} mention(s)${e.confidence != null ? " · weakest link " + pct(e.confidence) : ""}</span>
      ${e.elsewhere.length ? `<span class="chip warn">also in ${e.elsewhere.length} other claim(s)</span>` : ""}
      ${e.category ? `<span class="chip">${esc(e.category.value)}</span>` : ""}</div></div>`).join("")}</section>`;
  h += `<section class="block"><h2>Notes</h2>${d.notes.map((n) => `<div class="card row"><span class="grow">${ref("note", n.id, n.title)}</span><span class="muted">${n.chars.toLocaleString()} chars</span></div>`).join("")}</section>`;
  el.innerHTML = h + `</div>`;
}

function drawAnswer(el, w) {
  const d = w.data;
  // citations become numbered markers in order of first use, listed as sources below
  const order = [];
  const openAttr = (c) => esc(JSON.stringify({ kind: c.kind, id: c.id, label: c.label, span: c.span }));
  const text = esc(d.answer).replace(/\[([ea]\d+)\]/g, (m, a) => {
    const c = d.citations[a];
    if (!c) return "";
    if (!order.includes(a)) order.push(a);
    return `<span class="cite" data-open='${openAttr(c)}' title="${esc(c.label)}">${order.indexOf(a) + 1}</span>`;
  });
  const sources = order.map((a, i) => {
    const c = d.citations[a];
    const what = c.kind === "note" ? `${esc(c.label.replaceAll("_", " "))} · ${esc(c.id.replace("note:", "Note "))}` : esc(c.label);
    return `<div class="source"><span class="cite" data-open='${openAttr(c)}'>${i + 1}</span><span class="link" data-open='${openAttr(c)}'>${what}</span>
      <span class="muted">${c.kind === "note" ? "source passage" : "party"}</span></div>`;
  }).join("");
  let h = `<div class="win-head"><h1 class="title">${esc(d.question)}</h1><div class="meta"><span>answered from ${d.facts_used} retrieved facts</span>
    ${d.seconds ? `<span>· ${d.seconds}s</span>` : ""}<span>· lens ${esc(d.lens)}</span></div></div><div class="win-body">
    <div class="answer${d.error ? " err" : ""}">${text}</div>`;
  if (d.confidence_note) h += `<p class="muted" style="margin-top:14px">${esc(d.confidence_note)}</p>`;
  if (sources) h += `<section class="block"><h2>Sources</h2>${sources}</section>`;
  if (d.facts) h += `<section class="block"><h2>Retrieved facts</h2>${d.facts.map((f) => `<div class="muted mono" style="margin-bottom:6px">${esc(f)}</div>`).join("")}</section>`;
  if (d.dropped_citations && d.dropped_citations.length) h += `<p class="muted">Removed ${d.dropped_citations.length} citation(s) to facts that were not retrieved.</p>`;
  el.innerHTML = h + `</div>`;
  wireLinks(el, w);
}

// the decision card asks the app to open things through an event
document.addEventListener("goko:open", (e) => {
  const r = e.detail;
  openView({ kind: r.kind, id: r.id, lens: GOKO.lens || "default", span: r.span }, r.label);
});

render();
