"use strict";
// GOKO search. Home is one search bar over the full entity list. Opening anything turns the
// search and the list into a left sidebar, and the rest of the screen becomes a rolodex of
// cards (at most three side by side, extra cards behind edge buttons, one bubble tab per open
// card; up to two pinned at the left). The trail keeps every card ever opened, closed ones
// too; a trace (cards, pins, merge settings, times) can be saved in this browser and reopened.
// A separate note investigation reads one note with everything extracted from it highlighted.
// Read-only: every view is computed by the server from one pipeline run.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = GOKO.esc;
const LENS = GOKO.LENS_LABEL;                    // strict / default / broad, in words
const PIN_MAX = 2;

const S = {
  lens: "default", list: [], watch: null, meta: null, tab: "entities",
  mode: "home",                  // home | work
  view: "cards",                 // cards | investigate (within the work view)
  cards: [],                     // every card opened in this trace, in the order it was opened
  order: [],                     // open, unpinned cards in display order (ids)
  start: 0,                      // first unpinned card in view
  seq: 0,
  inv: null,                     // the note investigation: {note, showActions, drill: [], data}
  trace: null,                   // {id, name, created} once saved or reopened
};
GOKO.lens = S.lens;

// Browser storage is a convenience: a private window or blocked storage means no saved
// traces and no recent searches, never a broken page.
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
};

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const cap = (s) => String(s || "").replaceAll("_", " ");
const goAttr = (o) => `data-go='${esc(JSON.stringify(o))}'`;
const go = (kind, id, label, why, extra = {}) => `<span class="link" ${goAttr({ kind, id, label, why, ...extra })}>${esc(label)}</span>`;
const TYPE_WORD = { person: "person", organization: "organization", vehicle: "vehicle" };
const now = () => new Date().toISOString();
const clock = (iso) => { try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
const day = (iso) => { try { return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

// ================================================================ mode: home / work
function setMode(mode) {
  S.mode = mode;
  document.body.classList.toggle("at-home", mode === "home");
  document.body.classList.toggle("at-work", mode === "work");
  $("#work").hidden = mode !== "work";
  if (mode === "work") { renderWork(); } else { setTimeout(() => $("#q").focus(), 20); }
}
const openCards = () => S.cards.filter((c) => !c.closedAt);
const cardById = (id) => S.cards.find((c) => c.id === id);
const lensOf = (c) => (c.kind === "answer" ? c.lens : c.lensOverride || S.lens);
const keyOf = (req) => `${req.kind}|${req.id}`;

// ================================================================ the rolodex
function slots() {
  const w = ($("#stage") && $("#stage").clientWidth) || window.innerWidth - 320;
  return w >= 1040 ? 3 : w >= 620 ? 2 : 1;
}
function arrangement() {
  const pinned = openCards().filter((c) => c.pinned).sort((a, b) => a.pinnedAt - b.pinnedAt);
  const unp = S.order.map(cardById).filter((c) => c && !c.closedAt && !c.pinned);
  const n = slots();
  const pv = Math.min(pinned.length, Math.max(0, n - 1));
  const browse = n - pv;
  S.start = Math.max(0, Math.min(S.start, unp.length - browse));
  const vis = [...pinned.slice(0, pv), ...unp.slice(S.start, S.start + browse)];
  return { pinned, unp, vis, browse, before: S.start + (pinned.length - pv), after: Math.max(0, unp.length - S.start - browse) };
}
function reveal(id) {
  const c = cardById(id);
  if (!c || c.closedAt) return;
  S.view = "cards";
  if (c.pinned) {
    const { pinned } = arrangement();
    const n = Math.max(0, slots() - 1);
    if (pinned.indexOf(c) >= n) c.pinnedAt = Math.min(...pinned.map((p) => p.pinnedAt)) - 1;   // bring it to the front
  } else {
    const a = arrangement(), i = a.unp.indexOf(c);
    if (i < S.start) S.start = i; else if (i >= S.start + a.browse) S.start = i - a.browse + 1;
  }
  S.focus = id;
  renderWork();
}
function openCard(req, label, why, fromId) {
  // a card already open for the same thing is brought into view (a note moves to the new passage)
  const same = openCards().find((c) => c.req && keyOf(c.req) === keyOf(req));
  if (same) {
    if (req.span || req.key) { same.req = { ...same.req, span: req.span, key: req.key }; loadCard(same); }
    if (S.mode !== "work") setMode("work");
    return reveal(same.id);
  }
  const c = { id: ++S.seq, kind: "view", req, label: label || "…", why: why || "opened", openedAt: now(), closedAt: null,
              pinned: false, pinnedAt: 0, lensOverride: null, state: "loading" };
  S.cards.push(c);
  const at = fromId != null && S.order.includes(fromId) ? S.order.indexOf(fromId) + 1 : S.order.length;
  S.order.splice(at, 0, c.id);
  if (S.mode !== "work") setMode("work");
  reveal(c.id);
  loadCard(c);
  return c;
}
function closeCard(id) {
  const c = cardById(id);
  if (!c) return;
  c.closedAt = now(); c.pinned = false;
  S.order = S.order.filter((x) => x !== id);
  renderWork();
}
function restoreCard(id) {
  const c = cardById(id);
  if (!c || !c.closedAt) return reveal(id);
  c.closedAt = null;
  S.order.push(id);
  if (c.kind === "view" && c.state !== "view") loadCard(c);
  reveal(id);
}
function togglePin(id) {
  const c = cardById(id);
  if (!c) return;
  if (c.pinned) {
    c.pinned = false;
    S.order.unshift(id);                                  // back to the head of the browsing row
  } else {
    const pinned = openCards().filter((x) => x.pinned);
    if (pinned.length >= PIN_MAX) { flashNote(`At most ${PIN_MAX} pinned cards: the third slot stays free for browsing. Unpin one first.`); return; }
    c.pinned = true; c.pinnedAt = Date.now();
    S.order = S.order.filter((x) => x !== id);
  }
  renderWork();
}
async function loadCard(c) {
  if (c.kind !== "view") return;
  c.state = "loading"; c.ver = (c.ver || 0) + 1;
  renderWork();
  const lens = lensOf(c);
  try {
    const q = new URLSearchParams({ kind: c.req.kind, id: c.req.id, lens });
    if (c.req.span) q.set("span", JSON.stringify(c.req.span));
    const d = await api("/api/view?" + q);
    if (lensOf(c) !== lens) return;                       // a newer load is on its way
    c.data = d; c.state = "view";
    if (!c.label || c.label === "…") c.label = d.title;
  } catch (e) { c.state = "error"; c.error = e.message; }
  c.ver = (c.ver || 0) + 1;
  renderWork();
}

// clicks on references inside cards open a new card to the right of the one clicked in
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-go]");
  if (!a) return;
  e.preventDefault();
  const r = JSON.parse(a.dataset.go);
  const from = a.closest("[data-card-id]");
  if (a.closest("#drawer")) GOKO.closeDrawer();
  openCard({ kind: r.kind, id: r.id, span: r.span, key: r.key }, r.label, r.why || "opened", from ? +from.dataset.cardId : null);
});
document.addEventListener("goko:open", (e) => {
  const r = e.detail;
  openCard({ kind: r.kind, id: r.id, span: r.span }, r.label, r.why || "from a decision card");
});

// ================================================================ rendering the work view
function renderWork() {
  if (S.mode !== "work") return;
  const inv = S.view === "investigate";
  $("#investigate").hidden = !inv;
  $("#stage").hidden = inv;
  renderBubbles();
  if (inv) return renderInvestigation();
  const a = arrangement();
  const host = $("#cards");
  const keep = new Map($$(".cardwin", host).map((el) => [+el.dataset.cardId, el]));
  host.innerHTML = "";
  host.style.setProperty("--slots", a.vis.length || 1);
  a.vis.forEach((c) => {
    let el = keep.get(c.id);
    const sig = `${c.ver || 0}|${c.state}|${c.pinned}|${lensOf(c)}|${c.lensOverride}|${S.lens}|${(c.log || []).length}|${c.result ? 1 : 0}`;
    if (!el || el.dataset.sig !== sig) {
      el = document.createElement("article");
      el.className = "cardwin"; el.dataset.cardId = c.id;
      drawCard(el, c);
      el.dataset.sig = sig;
    }
    el.classList.toggle("pinned", c.pinned);
    el.classList.toggle("focus", S.focus === c.id);
    host.appendChild(el);
  });
  if (!a.vis.length) host.innerHTML = `<div class="stage-empty muted">No card is open. Pick a party on the left, restore one from the Trail, or ask a question.</div>`;
  const L = $(".edge.left"), R = $(".edge.right");
  L.hidden = a.before <= 0; L.innerHTML = `<span>‹ ${a.before} more</span>`;
  R.hidden = a.after <= 0; R.innerHTML = `<span>${a.after} more ›</span>`;
  renderList();
}
function renderBubbles() {
  const a = arrangement();
  const visible = new Set(a.vis.map((c) => c.id));
  const all = [...a.pinned, ...a.unp];
  let h = S.inv ? `<div class="bubble inv${S.view === "investigate" ? " visible" : ""}" data-inv title="${esc(S.inv.note ? `Investigating ${S.inv.note.replace("note:", "Note ")}` : "Note investigation")}"><span class="label">${esc(S.inv.note ? S.inv.note.replace("note:", "Note ") : "Investigation")}</span><span class="kind">investigation</span></div>` : "";
  h += all.map((c) => `<div class="bubble${visible.has(c.id) && S.view === "cards" ? " visible" : ""}${c.pinned ? " is-pinned" : ""}" data-id="${c.id}" title="${esc(`${c.label} — ${c.why}`)}">
      ${c.pinned ? `<span class="pin-glyph" title="Pinned">●</span>` : ""}<span class="label">${esc(c.kind === "answer" ? "? " + c.label : c.label)}</span>
      <button class="x" data-close="${c.id}" aria-label="Close ${esc(c.label)}" title="Close (it stays in the Trail)">×</button></div>`).join("");
  $("#bubbles").innerHTML = h;
  $$("#bubbles .bubble[data-id]").forEach((b) => b.addEventListener("click", (e) => {
    if (e.target.dataset.close) { closeCard(+e.target.dataset.close); return; }
    reveal(+b.dataset.id);
  }));
  const ib = $("#bubbles [data-inv]");
  if (ib) ib.addEventListener("click", () => { S.view = "investigate"; renderWork(); });
}
$(".edge.left").addEventListener("click", () => { S.start = Math.max(0, S.start - 1); renderWork(); });
$(".edge.right").addEventListener("click", () => { S.start += 1; renderWork(); });
let _rz = null;
window.addEventListener("resize", () => { clearTimeout(_rz); _rz = setTimeout(renderWork, 80); });

function flashNote(msg) {
  let n = $("#toast");
  if (!n) { n = document.createElement("div"); n.id = "toast"; document.body.append(n); }
  n.textContent = msg; n.classList.remove("show"); void n.offsetWidth; n.classList.add("show");
}

// ---------------------------------------------------------------- one card
function cardHead(c, title, meta = "") {
  const lens = lensOf(c);
  const ov = c.lensOverride ? `<span class="chip warn override-note" title="This card uses its own merge setting instead of the one in the top bar">overridden: ${esc(LENS[c.lensOverride].toLowerCase())}</span>` : "";
  const sel = c.kind === "view" ? `<select class="card-lens" title="Merge setting for this card only" aria-label="Merge setting for this card">
      <option value="">Merge as set above</option>${Object.keys(LENS).map((k) => `<option value="${k}"${c.lensOverride === k ? " selected" : ""}>${esc(LENS[k])}</option>`).join("")}</select>` : "";
  return `<div class="card-head">
      <div class="card-tools"><span class="why" title="Why this card was opened">${esc(c.why)}</span><div class="grow"></div>${sel}
        <button class="mini${c.pinned ? " on" : ""}" data-pin title="${c.pinned ? "Unpin" : "Pin this card to the left end of the rolodex (at most two)"}">${c.pinned ? "Unpin" : "Pin"}</button>
        <button class="mini x" data-close title="Close (it stays in the Trail)" aria-label="Close">×</button></div>
      <h1 class="title">${title}</h1>${ov}${meta}<div class="lens-now muted" title="What counts as one party in this card">merge on: ${esc(LENS[lens].toLowerCase())}</div></div>`;
}
function drawCard(el, c) {
  if (c.kind === "answer") { el.innerHTML = drawAnswer(c); wireCard(el, c); wireAnswer(el, c); return; }
  if (c.state === "loading" && !c.data) { el.innerHTML = cardHead(c, esc(c.label)) + `<div class="card-body"><div class="thinking"><span class="dot"></span>Loading…</div></div>`; wireCard(el, c); return; }
  if (c.state === "error") { el.innerHTML = cardHead(c, esc(c.label)) + `<div class="card-body"><p class="err">${esc(c.error)}</p></div>`; wireCard(el, c); return; }
  const d = c.data;
  el.innerHTML = ({ entity: drawEntity, identifier: drawIdentifier, note: drawNote, claim: drawClaim }[d.kind])(d, c);
  if (c.state === "loading") $(".card-head", el).insertAdjacentHTML("beforeend", `<div class="thinking small"><span class="dot"></span>Updating…</div>`);
  wireCard(el, c);
  if (d.kind === "note") afterReader(el, c);
}
function wireCard(el, c) {
  GOKO.lens = lensOf(c);
  GOKO.wire(el);
  const p = $("[data-pin]", el); if (p) p.addEventListener("click", () => togglePin(c.id));
  const x = $("[data-close]", el); if (x) x.addEventListener("click", () => closeCard(c.id));
  const sel = $(".card-lens", el);
  if (sel) sel.addEventListener("change", () => { c.lensOverride = sel.value || null; loadCard(c); });
  $$("[data-more]", el).forEach((b) => b.addEventListener("click", () => {
    b.closest("section").querySelectorAll(".extra").forEach((y) => y.classList.remove("extra"));
    b.remove();
  }));
  el.addEventListener("mousedown", () => { if (S.focus !== c.id) { S.focus = c.id; $$(".cardwin").forEach((w) => w.classList.toggle("focus", +w.dataset.cardId === c.id)); } });
}

// ================================================================ merge setting
function setLens(l) {
  S.lens = l; GOKO.lens = l;
  $$("#lens button").forEach((b) => b.classList.toggle("on", b.dataset.lens === l));
  loadList();
  openCards().forEach((c) => { if (c.kind === "view" && !c.lensOverride) loadCard(c); });
  if (S.inv && S.inv.note) loadInvestigation(S.inv.note);
}
$$("#lens button").forEach((b) => {
  b.title = { strict: "Only identifier-backed links (p ≥ 0.90) merge or flag", default: "Any basis, p ≥ 0.80: names count when the link is confident", broad: "Any basis, p ≥ 0.10: adds weak and partial name matches" }[b.dataset.lens];
  b.addEventListener("click", () => setLens(b.dataset.lens));
});

// ================================================================ the finder: search + list
async function loadList() {
  $("#list-meta").textContent = "Loading…";
  try {
    const r = await api("/api/entities?lens=" + S.lens);
    S.list = r.entities; S.watch = r.watchlist;
  } catch (e) { $("#list-meta").textContent = e.message; return; }
  renderList();
}
function renderList() {
  if (S.tab === "traces") return renderTraces();
  const f = norm($("#q").value);
  const rows = S.list.filter((e) => !f || norm(e.name).includes(f) || e.forms.some((x) => norm(x).includes(f)));
  const flagged = S.list.filter((e) => e.flag).length;
  $("#list-meta").innerHTML = `${rows.length}${f ? ` of ${S.list.length}` : ""} parties · merge on <span class="term" title="Set in the top bar">${esc(LENS[S.lens].toLowerCase())}</span>` +
    (flagged ? ` · <span class="flag-text" title="Parties with a mention linked to a record on the OIG exclusion list at this setting">${flagged} flagged for review</span>` : "");
  const openIds = new Set(openCards().filter((c) => c.data && c.data.kind === "entity").map((c) => c.data.id));
  const shown = rows.slice(0, 400);
  $("#entity-list").innerHTML = shown.map((e) => {
    const badge = e.flag
      ? `<span class="flag-badge" title="${esc(`Flagged for review: linked to the OIG exclusion record ${e.flag.record}, ${GOKO.probText(e.flag.p)}, ${(GOKO.BASIS[e.flag.basis_class] || [e.flag.basis_class])[0]}. A lead to check, not a finding.`)}">Flagged · ${esc(GOKO.band(e.flag.p))}</span>`
      : e.near ? `<span class="near-badge" title="${esc(`An exclusion-list link exists (${GOKO.probText(e.near.p)}) but this setting does not admit it${e.near.admitted.length ? "; it flags at " + e.near.admitted.map((x) => LENS[x].toLowerCase()).join(", ") : ""}.`)}">possible match</span>` : "";
    const kind = e.kind && e.kind !== "party" ? ` · <span class="kind-tag" title="${esc(e.kind === "group" ? "A collective the note defines (e.g. “the No-Fault Attorneys”); its members are linked to it" : "A legal construct the filing names (an enterprise or scheme), not a party")}">${esc(e.kind)}</span>` : "";
    return `<div class="erow${openIds.has(e.id) ? " on" : ""}" role="listitem" data-id="${esc(e.id)}" data-name="${esc(e.name)}" tabindex="0">
      <div class="ename"><span class="tdot t-${esc(e.type)}" title="${esc(TYPE_WORD[e.type] || e.type)}"></span>${esc(e.name)}</div>
      <div class="esub">${esc(TYPE_WORD[e.type] || e.type)}${kind} · ${e.mentions} mention${e.mentions === 1 ? "" : "s"} · ${e.claims} claim${e.claims === 1 ? "" : "s"} ${badge}</div></div>`;
  }).join("") + (rows.length > shown.length ? `<p class="muted pad">${rows.length - shown.length} more: keep typing to narrow.</p>` : "") || `<p class="muted pad">No party matches.</p>`;
  $$("#entity-list .erow").forEach((r) => {
    const open = () => openCard({ kind: "entity", id: r.dataset.id }, r.dataset.name, "from the list");
    r.addEventListener("click", open);
    r.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}
$$(".switch button").forEach((b) => b.addEventListener("click", () => {
  S.tab = b.dataset.tab;
  $$(".switch button").forEach((x) => x.classList.toggle("on", x === b));
  $("#entity-list").hidden = S.tab !== "entities";
  $("#trace-list").hidden = S.tab !== "traces";
  renderList();
}));
$("#q").addEventListener("input", () => { if (S.tab !== "entities") $(".switch [data-tab=entities]").click(); renderList(); });

function attachSearch(box, onPick, onEnter) {
  const input = $("input", box), list = $(".suggest", box);
  let items = [], active = -1, timer = null, lastQ = "";
  const labels = { entity: "Parties", identifier: "Identifiers", claim: "Claims", note: "Notes" };
  const draw = () => {
    if (!input.value.trim() || document.activeElement !== input) { list.hidden = true; return; }
    let html = "", group = null;
    items.forEach((s, i) => {
      if (s.kind !== group) { group = s.kind; html += `<div class="group">${esc(labels[group] || group)}</div>`; }
      html += `<div class="item${i === active ? " active" : ""}" data-i="${i}"><span class="lab">${esc(s.label)}</span><span class="sub">${esc(s.sub)}</span></div>`;
    });
    html += `<div class="item ask${active === items.length ? " active" : ""}" data-i="${items.length}" title="Enter: the librarian decides. A name opens its card; a question gets an answer built from the graph, with sources.">Ask the librarian: “${esc(input.value.trim())}” <span class="kbd">Enter</span></div>`;
    list.innerHTML = html; list.hidden = false;
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (q === lastQ) return draw();
      lastQ = q;
      items = q ? await api("/api/suggest?q=" + encodeURIComponent(q)).catch(() => []) : [];
      active = -1; draw();
    }, 110);
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
  input.addEventListener("focus", () => { if (input.value.trim()) draw(); });
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 150));
}
attachSearch($("#finder [data-search]"),
  (s, q) => { remember(q); openCard({ kind: s.kind, id: s.id }, s.label, `search “${q}”`); },
  (q) => ask(q));
document.addEventListener("keydown", (e) => {
  const drawerOpen = $("#drawer") && !$("#drawer").hidden;
  if (e.key === "Escape") { $$(".pop").forEach((p) => (p.hidden = true)); }
  if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) && !drawerOpen) { e.preventDefault(); $("#q").focus(); }
});
function recent() { return store.get("goko.recent", []); }
function remember(q) { store.set("goko.recent", [q, ...recent().filter((x) => x !== q)].slice(0, 8)); }

// ================================================================ the librarian, streamed
async function ask(q) {
  remember(q);
  $("#q").value = ""; renderList();
  const c = { id: ++S.seq, kind: "answer", q, label: q, why: "asked the librarian", openedAt: now(), closedAt: null,
              pinned: false, pinnedAt: 0, lensOverride: null, lens: S.lens, log: [], result: null, state: "answer" };
  S.cards.push(c); S.order.push(c.id);
  if (S.mode !== "work") setMode("work");
  reveal(c.id);
  try {
    const r = await fetch("/api/ask_stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q, lens: S.lens }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) onAskEvent(c, JSON.parse(line.slice(6)));
      }
    }
    if (!c.result) throw new Error("the answer stream ended without a result");
  } catch (e) {
    c.result = { mode: "error", error: e.message };
    renderWork();
  }
}
function onAskEvent(c, e) {
  if (e.step !== "result") {
    c.log.push(e);
    const el = $(`.cardwin[data-card-id="${c.id}"]`);
    if (el && $("details.log ol", el)) { $("details.log ol", el).innerHTML = c.log.map(logLine).join(""); el.dataset.sig = ""; wireAnswer(el, c); }
    else renderWork();
    return;
  }
  c.result = e;
  if (e.mode === "lookup" && e.view) {
    // a lookup is a navigation, not an answer: the card becomes the view it opened
    Object.assign(c, { kind: "view", req: { kind: e.view.kind, id: e.view.id }, data: e.view, state: "view",
      label: e.view.title, why: `search “${c.q}”` });
  }
  c.ver = (c.ver || 0) + 1;
  renderWork();
}
const STEP_ICON = { route: "Route", match: "Match", expand: "Expand", passages: "Read", facts: "Facts", model_start: "Model", model_done: "Model", model_failed: "Model", model_skip: "Model", citations: "Cite" };
function logLine(e) {
  let text = e.text;
  if (e.step === "model_start") text = `Calling ${e.model} to ${e.purpose === "routing" ? "route the query" : `write the answer from ${e.facts} facts`}…`;
  if (e.step === "model_done") text = `${e.model} ${e.purpose === "routing" ? "routed it" : "answered"} in ${e.seconds} s.`;
  if (e.step === "model_failed") text = `The ${e.purpose} call failed after ${e.seconds} s: ${e.error}`;
  let extra = "";
  if (e.step === "match" && e.entities && e.entities.length) extra = `<div class="muted">${e.entities.map(esc).join(", ")}</div>`;
  if (e.step === "expand" && e.names && e.names.length) extra = `<div class="muted">added: ${e.names.map(esc).join(", ")}</div>`;
  if (e.step === "facts") extra = ` <span class="link" data-show-facts>show what was sent</span>`;
  if (e.step === "citations" && e.dropped && e.dropped.length) extra = `<div class="muted">removed: ${e.dropped.map(esc).join(", ")}</div>`;
  return `<li class="s-${esc(e.step)}"><span class="lt">${e.t.toFixed(1)} s</span><span class="lk">${esc(STEP_ICON[e.step] || e.step)}</span><span class="lx">${esc(text || "")}${extra}</span></li>`;
}
function drawAnswer(c) {
  const r = c.result, running = !r;
  const facts = (c.log.find((e) => e.step === "facts") || {}).facts || (r && r.facts) || [];
  const secs = r ? ((c.log.length ? c.log[c.log.length - 1].t : 0)).toFixed(1) : null;
  const meta = `<div class="meta">${r && r.routed_by ? `<span>routed by ${esc(cap(r.routed_by))}</span>` : ""}${r && r.facts_used ? `<span>· ${r.facts_used} facts</span>` : ""}</div>`;
  let h = cardHead(c, esc(c.q), meta) + `<div class="card-body">`;
  const open = running || c.logOpen || (r && r.no_model && c.logOpen !== false);
  h += `<details class="log"${open ? " open" : ""}><summary title="The steps the server actually took, as they happened">${running ? `<span class="dot"></span> Working…` : `${c.log.length} steps · ${secs} s`}</summary><ol>${c.log.map(logLine).join("")}</ol></details>`;
  const factsBox = `<div class="facts" hidden><div class="ideas-h">What was sent (${facts.length} facts)</div>${facts.map((f) => `<div class="fact mono">${esc(f)}</div>`).join("")}</div>`;
  if (!r) return h + `<p class="thinking"><span class="dot"></span>The librarian is reading the graph…</p>${factsBox}</div>`;
  if (r.mode === "error") return h + `<p class="err">${esc(r.error)}</p></div>`;
  const order = [];
  const text = esc(r.answer || "").replace(/\[([eap]\d+)\]/g, (m, a) => {
    const x = (r.citations || {})[a];
    if (!x) return "";
    if (!order.includes(a)) order.push(a);
    return `<span class="cite" ${goAttr({ kind: x.kind, id: x.id, label: x.label, span: x.span, why: `cited in “${c.q.slice(0, 40)}”` })} title="${esc(x.label)}">${order.indexOf(a) + 1}</span>`;
  });
  h += `<div class="answer${r.error ? " err" : ""}${r.no_model ? " muted" : ""}">${text}</div>`;
  if (r.confidence_note) h += `<p class="muted">${esc(r.confidence_note)}</p>`;
  if (order.length) h += `<section class="block"><h2>Sources</h2>${order.map((a, i) => {
    const x = r.citations[a];
    const what = x.kind === "note" ? `${esc(cap(x.label))} · ${esc(x.id.replace("note:", "Note "))}` : esc(x.label);
    const kindWord = a.startsWith("p") ? "passage read" : x.kind === "note" ? "action, source passage" : "party";
    return `<div class="source"><span class="cite" ${goAttr({ kind: x.kind, id: x.id, label: x.label, span: x.span, why: "source of an answer" })}>${i + 1}</span><span class="link" ${goAttr({ kind: x.kind, id: x.id, label: x.label, span: x.span, why: "source of an answer" })}>${what}</span><span class="muted">${kindWord}</span></div>`;
  }).join("")}</section>`;
  if (facts.length) h += `<p><button class="pill ghost small" data-show-facts title="The exact facts, with their aliases, that ${r.no_model ? "a model would have received" : "the model received"}">show what was sent (${facts.length} facts)</button></p>`;
  return h + factsBox + `</div>`;
}
function wireAnswer(el, c) {
  $$("[data-show-facts]", el).forEach((x) => x.addEventListener("click", () => {
    const f = $(".facts", el);
    f.hidden = !f.hidden;
    $$("[data-show-facts]", el).forEach((y) => { y.textContent = y.textContent.replace(f.hidden ? "hide" : "show", f.hidden ? "show" : "hide"); });
    if (!f.hidden) f.scrollIntoView({ block: "start", behavior: "smooth" });
  }));
  const det = $("details.log", el);
  if (det) det.addEventListener("toggle", () => { if (c.result) c.logOpen = det.open; });
}

// ================================================================ card contents
function evidence(x, why, key) {
  if (!x) return `<div class="ev muted">no source passage</div>`;
  return `${GOKO.excerptHTML(x)}<div class="src">${go("note", x.note, x.note.replace("note:", "Note "), why, { span: x.span, key })}
    <span class="muted">${esc(x.claim_id)}</span></div>`;
}
const more = (n, shown, what) => (n > shown ? `<button class="pill ghost small" data-more>Show all ${n} ${what}</button>` : "");
function detailLine(x) {
  const bits = [];
  if (x.subtype) bits.push(`<span class="chip" title="${esc(x.type === "phone" ? "Line type as stated. A work line counts less as identity evidence: several people share one." : "License type")}">${esc(x.subtype)}</span>`);
  if (x.parts) {
    const p = x.parts;
    const street = [p.number, p.direction, p.street, p.street_type].filter(Boolean).join(" ");
    const txt = [street, p.unit ? "unit " + p.unit : "", [p.city, p.state].filter(Boolean).join(" "), p.zip].filter(Boolean).join(" · ");
    if (txt) bits.push(`<span class="muted" title="Address parts, used for the graded comparison: exact, same street and number, same ZIP, same city, same state">${esc(txt)}</span>`);
  }
  return bits.join(" ");
}

function drawEntity(d, c) {
  const T = d.title;
  const flagged = d.flagged && d.flagged.length;
  const kind = d.kind_of_party && d.kind_of_party !== "party" ? `<span class="chip" title="${esc(d.kind_of_party === "group" ? "A collective the note defines; its members are listed below" : "A legal construct the filing names (an enterprise or scheme), kept apart from the parties that form it")}">${esc(d.kind_of_party)}</span>` : "";
  const meta = `<div class="meta"><span title="Entity type, as the model read it">${esc(d.type)}</span>${kind}<span>·</span>
      <span>${d.claims.map((x) => go("claim", x, x, `claim of ${T}`)).join(", ")}</span>
      ${flagged ? `<span class="chip bad" title="At this merge setting a mention of this party links to a record on the OIG exclusion list (LEIE). A lead to check, not a finding.">Flagged for review</span>` : ""}</div>
    ${GOKO.summaryHTML(d)}${GOKO.categoryHTML(d)}${d.specialties && d.specialties.length ? `<p class="role-line"><span class="term" title="As stated in the notes. Supporting evidence for identity, never an identifier">Specialty</span>: ${d.specialties.map(esc).join(" / ")}</p>` : ""}`;
  let h = cardHead(c, esc(T), meta) + `<div class="card-body">`;
  if (flagged) h += `<section class="block"><h2 title="Exclusion-list records a mention of this party links to, admitted at this setting. Each row opens its decision card.">Flagged for review · OIG exclusion list</h2>${d.flagged.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.group_members && d.group_members.length) h += `<section class="block"><h2 title="Parties the notes name as members of this group">Members (${d.group_members.length})</h2>${d.group_members.map((m) => `<div class="card"><div class="row"><span class="grow">${go(m.kind, m.id, m.name, `member of ${T}`)}</span><span class="muted">${esc(m.type)}</span></div>${evidence(m.evidence, `membership in ${T}`)}</div>`).join("")}</section>`;
  if (d.member_of && d.member_of.length) h += `<section class="block"><h2 title="Groups the notes put this party in">Member of</h2><div class="meta">${d.member_of.map((g) => `<span class="chip">${go(g.kind, g.id, g.name, `group of ${T}`)}</span>`).join("")}</div></section>`;
  if (d.details.length) {
    h += `<section class="block"><h2 title="Identifiers the notes attribute to this party. SSNs and bank accounts show their last four digits only.">Identifiers</h2>`;
    d.details.forEach((x, i) => {
      h += `<div class="card${i >= 6 ? " extra" : ""}"><div class="row"><span class="chip" title="Identifier type">${esc(cap(x.type))}</span><span class="grow">${go("identifier", x.ident, x.raw, `identifier of ${T}`)}</span>
        <span class="muted" title="stated: the note says whose it is; inferred: the model concluded it">${esc(x.basis || "")}${x.checksum && x.checksum !== "n/a" ? ` · <span title="Check-digit test on the value">checksum ${esc(x.checksum)}</span>` : ""}</span></div>
        ${detailLine(x) ? `<div class="row">${detailLine(x)}</div>` : ""}
        ${x.shared_with.length ? `<div class="muted">Also held by ${x.shared_with.map((s) => go(s.kind, s.id, s.name, `shares ${cap(x.type)} with ${T}`)).join(", ")}</div>` : ""}
        ${evidence(x.evidence[0], `passage for ${T}`)}</div>`;
    });
    h += more(d.details.length, 6, "identifiers") + `</section>`;
  }
  h += `<section class="block"><h2 title="Each mention is one place a note names this party. Merging is by scored links; each line shows the link that pulled the mention in.">Mentions (${d.members.length})</h2>`;
  d.members.forEach((m, i) => {
    const j = m.joined_by;
    const how = j ? `<span class="link" ${GOKO.cardAttr(m.key, j.with)} title="Open the decision card for this link">joined via “${esc(j.with_name)}” · ${esc(GOKO.probText(j.p))} · ${esc((GOKO.BASIS[j.basis_class] || [j.basis_class])[0])}</span>`
      : `<span class="muted" title="The mention the entity is anchored on (its lowest key)">first mention</span>`;
    h += `<div class="card${i >= 4 ? " extra" : ""}"><div class="mhead"><strong>${esc(m.name)}</strong><div class="how">${how}</div></div>${evidence(m.evidence, `mention of ${T}`, m.key)}</div>`;
  });
  h += more(d.members.length, 4, "mentions") + `</section>`;
  if (d.related.length) h += `<section class="block"><h2 title="Parties that take part in the same actions, with how often">Appears with</h2><div class="meta">${d.related.slice(0, 16).map((r) => `<span class="chip">${go(r.kind, r.id, r.name, `appears with ${T}`)} ×${r.count}</span>`).join("")}</div></section>`;
  if (d.actions.length) {
    h += `<section class="block"><h2 title="What the notes say this party did or had done to it, with the source passage">Actions (${d.actions.length})</h2>`;
    d.actions.slice(0, 40).forEach((a, i) => {
      h += `<div class="card${i >= 5 ? " extra" : ""}"><div class="row"><strong>${esc(cap(a.type))}</strong><span class="muted">as ${esc(a.role)}</span>
        ${a.stance && a.stance !== "asserted" ? `<span class="chip warn" title="How the text presents the event">${esc(a.stance)}</span>` : ""}${a.time ? `<span class="muted">${esc(a.time)}</span>` : ""}</div>
        ${a.others.length ? `<div class="muted">with ${a.others.map((o) => `${go(o.kind, o.id, o.name, `co-party of ${T}`)} (${esc(o.role)})`).join(", ")}</div>` : ""}
        ${evidence(a.evidence, `action of ${T}`)}</div>`;
    });
    h += more(Math.min(d.actions.length, 40), 5, "actions") + `</section>`;
  }
  h += GOKO.candidatesHTML(d.candidates, d.lens);
  if (d.watchlist_near && d.watchlist_near.length) h += `<section class="block"><h2 title="Exclusion-list links below this setting's threshold, or vetoed. They do not flag the party here.">Exclusion-list links this setting does not admit</h2>${d.watchlist_near.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.refused.length) h += `<section class="block"><h2 title="Unions the projection refused: a veto, or the cluster-size alarm">Refused merges</h2>${d.refused.map((r) => `<div class="card"><span class="link" ${GOKO.cardAttr(r.a, r.b)}>${esc(r.reason === "veto" ? "would join a vetoed pair" : "would pass the cluster-size alarm")}</span></div>`).join("")}</section>`;
  return h + `</div>`;
}
function drawIdentifier(d, c) {
  const meta = `<div class="meta"><span class="chip" title="Identifier type">${esc(cap(d.detail_type))}</span><span>${d.evidence.length} occurrence(s)</span><span>·</span>
    <span>${d.claims.map((x) => go("claim", x, x, `claim with ${d.title}`)).join(", ")}</span>
    ${d.suspicion ? `<span class="chip bad" title="The same value appears across ${esc(cap(d.distance))}: shared details are relationships worth a look, not identities">shared across ${esc(cap(d.distance))}</span>` : ""}
    ${d.masked ? `<span class="chip" title="Shown as its last four digits; the full value never reaches this page">masked</span>` : ""}</div>`;
  let h = cardHead(c, `<span class="mono">${esc(d.title)}</span>`, meta) + `<div class="card-body">`;
  h += `<section class="block"><h2>Held by</h2>${d.holders.length ? d.holders.map((x) => `<div class="card row"><span class="grow">${go(x.kind, x.id, x.name, `holds ${d.title}`)}</span><span class="muted">${esc(x.type)} · ${esc(x.claims.join(", "))}</span></div>`).join("") : `<p class="muted">No owner was assigned.</p>`}
    ${d.unassigned ? `<p class="muted" title="A pattern or the model found the value, but not whose it is">${d.unassigned} occurrence(s) with no owner (unassigned).</p>` : ""}</section>`;
  h += `<section class="block"><h2>Evidence</h2>${d.evidence.map((x) => `<div class="card">${evidence(x, `passage with ${d.title}`)}</div>`).join("")}</section>`;
  return h + `</div>`;
}
function drawClaim(d, c) {
  const meta = `<div class="meta"><span>${d.entities.length} parties</span><span>·</span><span>${d.notes.length} notes</span></div>`;
  let h = cardHead(c, esc(d.title), meta) + `<div class="card-body">`;
  h += `<section class="block"><h2>Parties</h2>${d.entities.map((e) => `<div class="card"><div>${go(e.kind, e.id, e.name, `party in ${d.title}`)}</div>
      <div class="meta"><span>${esc(e.type)} · ${e.mentions} mention(s)${e.confidence != null ? " · weakest link " + esc(GOKO.probText(e.confidence)) : ""}</span>
      ${e.elsewhere.length ? `<span class="chip warn" title="The same entity, at this setting, also appears in these claims">also in ${e.elsewhere.length} other claim(s)</span>` : ""}
      ${e.category ? `<span class="chip" title="Role, the model's reading, not identity">${esc(e.category.value === "insufficient_evidence" ? "undetermined" : cap(e.category.value))}</span>` : ""}</div></div>`).join("")}</section>`;
  h += `<section class="block"><h2>Notes</h2>${d.notes.map((n) => `<div class="card row"><span class="grow">${go("note", n.id, n.title, `note of ${d.title}`)}</span><span class="muted">${n.chars.toLocaleString()} chars</span></div>`).join("")}</section>`;
  return h + `</div>`;
}

// ================================================================ the note reader
// One renderer for note cards and the investigation: every entity mention (and every other
// place its own note names it), every detail, and optionally every action, as layered marks.
const LAYER_RANK = { entity: 4, occurrence: 3, detail: 2, action: 1 };
function readerItems(d, showActions) {
  const items = [];
  (d.entities || []).forEach((m) => {
    if (m.span) items.push({ s: m.span[0], e: m.span[1], layer: "entity", m });
    (m.occurrences || []).forEach((o) => items.push({ s: o[0], e: o[1], layer: "occurrence", m }));
  });
  (d.details || []).forEach((x) => { if (x.span) items.push({ s: x.span[0], e: x.span[1], layer: "detail", x }); });
  if (showActions) (d.actions || []).forEach((a) => { if (a.span) items.push({ s: a.span[0], e: a.span[1], layer: "action", a }); });
  return items.filter((i) => i.e > i.s);
}
function readerHTML(d, showActions, target) {
  const t = d.text, items = readerItems(d, showActions);
  const cuts = new Set([0, t.length]);
  items.forEach((i) => { cuts.add(Math.max(0, i.s)); cuts.add(Math.min(t.length, i.e)); });
  if (target) { cuts.add(target[0]); cuts.add(target[1]); }
  const pts = [...cuts].sort((a, b) => a - b);
  // sweep: items sorted by start, an active list pruned as segments pass their end
  const byStart = items.slice().sort((a, b) => a.s - b.s);
  let k = 0, active = [], out = "";
  for (let p = 0; p < pts.length - 1; p++) {
    const s = pts[p], e = pts[p + 1];
    while (k < byStart.length && byStart[k].s <= s) active.push(byStart[k++]);
    active = active.filter((i) => i.e > s);
    const cover = active.filter((i) => i.s <= s && i.e >= e);
    const seg = esc(t.slice(s, e));
    const inTarget = target && s >= target[0] && e <= target[1];
    if (!cover.length) { out += inTarget ? `<mark class="hl">${seg}</mark>` : seg; continue; }
    const top = cover.reduce((a, b) => (LAYER_RANK[b.layer] > LAYER_RANK[a.layer] ? b : a));
    const layers = new Set(cover.map((i) => i.layer));
    let cls = ["x"], attrs = "";
    if (layers.has("action")) cls.push("x-act");
    if (top.layer === "entity" || top.layer === "occurrence") {
      const m = top.m;
      cls.push(top.layer === "entity" ? "x-ent" : "x-occ", `t-${m.type}`);
      if (m.flagged) cls.push("flagged");
      attrs = `data-key="${esc(m.key)}" data-entity="${esc(m.id)}" data-name="${esc(m.name)}" tabindex="0" title="${esc(`${m.mention_name} · ${m.type}${top.layer === "occurrence" ? " · another way this note names it" : ""}${m.flagged ? " · flagged for review" : ""}. Click for its summary.`)}"`;
    } else if (top.layer === "detail") {
      const x = top.x;
      cls.push("x-det");
      attrs = `data-detail='${esc(JSON.stringify({ ident: x.ident, raw: x.raw, type: x.type, owner: x.owner, owner_name: x.owner_name, owner_entity: x.owner_entity, subtype: x.subtype }))}' tabindex="0" title="${esc(`${cap(x.type)}${x.subtype ? " (" + x.subtype + ")" : ""}${x.owner_name ? " of " + x.owner_name : " · no owner assigned"}. Click for details.`)}"`;
    } else {
      const a = top.a;
      attrs = `data-action='${esc(JSON.stringify({ id: a.id, type: a.type, who: a.who }))}' title="${esc(`${cap(a.type)}: ${a.who.join(", ")}`)}"`;
    }
    if (inTarget) cls.push("hl");
    out += `<span class="${cls.join(" ")}" ${attrs}>${seg}</span>`;
  }
  return out;
}
function legendHTML(showActions) {
  return `<span class="legend" title="Every extracted mention is highlighted by type; lighter marks are other places the same note names the party. Details are outlined; actions underlined when shown.">
    <span class="x x-ent t-person">person</span><span class="x x-ent t-organization">organization</span><span class="x x-ent t-vehicle">vehicle</span><span class="x x-det">detail</span>${showActions ? `<span class="x x-act">action</span>` : ""}</span>`;
}
function drawNote(d, c) {
  const meta = `<div class="meta">${go("claim", d.claim_id, d.claim_id, `claim of ${d.title}`)}<span>·</span><span>${d.chars.toLocaleString()} characters</span>
    ${d.extraction_error ? `<span class="chip bad" title="${esc(d.extraction_error)}">extraction partial</span>` : ""}${legendHTML(false)}</div>`;
  const hl = (c.req && c.req.span) || d.highlight;
  return cardHead(c, esc(d.title), meta) + `<div class="card-body"><div class="reader" data-note="${esc(d.id)}">${readerHTML(d, false, hl)}</div></div>`;
}
function afterReader(el, c, opts = {}) {
  const reader = $(".reader", el);
  if (!reader) return;
  reader.addEventListener("click", (e) => {
    const m = e.target.closest("[data-entity]");
    if (m) return peek(m.dataset.key, m.dataset.entity, m.dataset.name, reader.dataset.note, opts);
    const x = e.target.closest("[data-detail]");
    if (x) return peekDetail(JSON.parse(x.dataset.detail), reader.dataset.note, opts);
  });
  reader.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("[tabindex]")) e.target.click(); });
  const key = c && c.req && c.req.key;
  const target = (key && $(`[data-key="${CSS.escape(key)}"].x-ent`, reader)) || $(".hl", reader);
  if (target) setTimeout(() => flash(target), 40);
}
function flash(m) {
  m.scrollIntoView({ block: "center" });
  m.classList.remove("flash"); void m.offsetWidth; m.classList.add("flash");
}
// the side drawer: an entity's summary, and every mention of it to jump to
async function peek(key, entityId, name, noteId, opts = {}) {
  const body = GOKO.openDrawer(esc(name), `<div class="thinking"><span class="dot"></span>Loading…</div>`);
  let d;
  try { d = await api("/api/view?" + new URLSearchParams({ kind: "entity", id: key, lens: S.lens })); }
  catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const inDrill = S.inv && S.inv.drill.some((x) => x.id === d.id);
  let h = `<div class="meta">${esc(d.type)} · ${d.claims.map(esc).join(", ")}</div>${GOKO.summaryHTML(d)}${GOKO.categoryHTML(d)}
    <p class="row"><button class="pill" ${goAttr({ kind: "entity", id: d.id, label: d.title, why: `from ${noteId.replace("note:", "Note ")}` })}>Open as a card</button>
    ${opts.investigate ? `<button class="pill${inDrill ? " on" : ""}" data-drill title="Collect it; the collected parties open together as cards">${inDrill ? "Pinned for drill-down" : "Pin for drill-down"}</button>` : ""}</p>`;
  if (d.flagged && d.flagged.length) h += `<section class="block"><h2>Flagged for review</h2>${d.flagged.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.member_of && d.member_of.length) h += `<section class="block"><h2>Member of</h2>${d.member_of.map((g) => `<span class="chip">${esc(g.name)}</span>`).join(" ")}</section>`;
  if (d.group_members && d.group_members.length) h += `<section class="block"><h2>Members</h2>${d.group_members.map((g) => `<span class="chip">${esc(g.name)}</span>`).join(" ")}</section>`;
  if (d.details.length) h += `<section class="block"><h2>Identifiers</h2>${d.details.slice(0, 8).map((x) => `<div class="row"><span class="chip">${esc(cap(x.type))}</span><span class="mono">${esc(x.raw)}</span>${detailLine(x)}</div>`).join("")}</section>`;
  h += `<section class="block"><h2 title="Click one to jump to it in the note, or to open the note it is in">Mentions (${d.members.length})</h2>` +
    d.members.map((m) => `<div class="peek-m${m.key === key ? " on" : ""}" data-note="${esc(m.note)}" data-key="${esc(m.key)}" data-span='${esc(JSON.stringify(m.evidence ? m.evidence.span : null))}'>
      <strong>${esc(m.name)}</strong> <span class="muted">${esc(m.note.replace("note:", "Note "))}${m.note === noteId ? " · this note" : ""} · ${esc(m.claim_id)}</span></div>`).join("") + `</section>`;
  body.innerHTML = h;
  GOKO.wire(body, { open: false });
  const dr = $("[data-drill]", body);
  if (dr) dr.addEventListener("click", () => { toggleDrill({ kind: "entity", id: d.id, name: d.title, type: d.type }); dr.textContent = S.inv.drill.some((x) => x.id === d.id) ? "Pinned for drill-down" : "Pin for drill-down"; dr.classList.toggle("on"); });
  $$(".peek-m", body).forEach((x) => x.addEventListener("click", () => {
    const span = JSON.parse(x.dataset.span);
    const here = $$(`.reader[data-note="${CSS.escape(x.dataset.note)}"]`).find((r) => r.offsetParent);
    if (here) {
      const m = $(`[data-key="${CSS.escape(x.dataset.key)}"].x-ent`, here);
      if (m) flash(m);
      $$(".peek-m", body).forEach((y) => y.classList.toggle("on", y === x));
      return;
    }
    GOKO.closeDrawer();
    openCard({ kind: "note", id: x.dataset.note, span, key: x.dataset.key }, x.dataset.note.replace("note:", "Note "), `mention of ${d.title}`);
  }));
}
function peekDetail(x, noteId, opts = {}) {
  let h = `<div class="meta"><span class="chip">${esc(cap(x.type))}</span>${x.subtype ? `<span class="chip">${esc(x.subtype)}</span>` : ""}<span class="mono">${esc(x.raw)}</span></div>
    <p>${x.owner_name ? `Attributed to <strong>${esc(x.owner_name)}</strong>.` : `No owner assigned: the value was found, not whose it is.`}</p><p class="row">`;
  if (x.ident) h += `<button class="pill" ${goAttr({ kind: "identifier", id: x.ident, label: x.raw, why: `from ${noteId.replace("note:", "Note ")}` })}>Open the identifier as a card</button>`;
  if (x.owner_entity) h += `<button class="pill" ${goAttr({ kind: "entity", id: x.owner_entity, label: x.owner_name, why: `owner of ${x.raw}` })}>Open ${esc(x.owner_name)}</button>`;
  if (opts.investigate && x.owner_entity) h += `<button class="pill" data-drill>Pin ${esc(x.owner_name)} for drill-down</button>`;
  const body = GOKO.openDrawer(esc(cap(x.type)), h + `</p>`);
  const dr = $("[data-drill]", body);
  if (dr) dr.addEventListener("click", () => { toggleDrill({ kind: "entity", id: x.owner_entity, name: x.owner_name, type: "" }, true); dr.textContent = "Pinned for drill-down"; });
}

// ================================================================ note investigation
function startInvestigation(noteId) {
  if (!S.inv) S.inv = { note: null, showActions: false, drill: [], data: null, openedAt: now() };
  S.view = "investigate";
  if (S.mode !== "work") setMode("work"); else renderWork();
  if (noteId) loadInvestigation(noteId);
  else setTimeout(() => { const i = $("#inv-note"); if (i) i.focus(); }, 30);
}
$("#inv-btn").addEventListener("click", () => startInvestigation(null));
async function loadInvestigation(noteId) {
  S.inv.note = noteId; S.inv.data = null; S.inv.state = "loading";
  const tr = S.cards.find((c) => c.inv && c.note === noteId);
  if (!tr) S.cards.push({ id: ++S.seq, kind: "investigation", inv: true, note: noteId, label: noteId.replace("note:", "Note "), why: "investigated", openedAt: now(), closedAt: now() });
  renderWork();
  try { S.inv.data = await api("/api/view?" + new URLSearchParams({ kind: "note", id: noteId, lens: S.lens })); S.inv.state = "view"; }
  catch (e) { S.inv.state = "error"; S.inv.error = e.message; }
  renderWork();
}
function toggleDrill(ref, onlyAdd) {
  const i = S.inv.drill.findIndex((x) => x.id === ref.id);
  if (i >= 0) { if (!onlyAdd) S.inv.drill.splice(i, 1); } else S.inv.drill.push(ref);
  renderDrill();
}
function renderDrill() {
  const box = $("#drill");
  if (!box) return;
  const n = S.inv.drill.length;
  box.innerHTML = `<h2 title="Parties collected from the note. They open together as rolodex cards.">Pinned for drill-down (${n})</h2>` +
    (n ? S.inv.drill.map((x) => `<div class="drow"><span class="grow">${esc(x.name)}</span><button class="mini x" data-undrill="${esc(x.id)}" aria-label="Remove">×</button></div>`).join("") +
      `<button class="pill strong" data-drill-open>Open ${n} as cards</button>`
      : `<p class="muted">Click a highlight, then “Pin for drill-down”.</p>`);
  $$("[data-undrill]", box).forEach((b) => b.addEventListener("click", () => toggleDrill({ id: b.dataset.undrill })));
  const o = $("[data-drill-open]", box);
  if (o) o.addEventListener("click", () => {
    const from = S.inv.note ? S.inv.note.replace("note:", "Note ") : "the note";
    S.inv.drill.forEach((x) => openCard({ kind: x.kind, id: x.id }, x.name, `drill-down from ${from}`));
    S.view = "cards"; renderWork();
  });
}
function renderInvestigation() {
  const I = S.inv, el = $("#investigate");
  const cards = openCards().filter((c) => c.kind !== "investigation").length;
  let h = `<div class="inv-head"><div class="row"><h1 class="title grow">Investigate a note</h1>
      ${cards ? `<button class="pill ghost" data-to-cards title="Back to the rolodex">Cards (${cards}) ›</button>` : ""}</div>
    <div class="row inv-controls"><div class="search small" data-inv-search><input id="inv-note" type="search" placeholder="Note id, e.g. 720001" value="${esc(I.note ? I.note.replace("note:", "") : "")}" autocomplete="off" spellcheck="false" aria-label="Note id"><div class="suggest" hidden></div></div>
      <label class="toggle" title="Underline every extracted action too"><input type="checkbox" id="inv-acts"${I.showActions ? " checked" : ""}> actions</label>
      ${legendHTML(I.showActions)}</div></div>`;
  h += `<div class="inv-body"><div class="inv-read">`;
  if (!I.note) h += `<p class="muted pad">Type a note id above. Every extracted mention and detail in it is highlighted; click one for a summary.</p>`;
  else if (I.state === "loading") h += `<div class="thinking"><span class="dot"></span>Loading ${esc(I.note)}…</div>`;
  else if (I.state === "error") h += `<p class="err">${esc(I.error)}</p>`;
  else {
    const d = I.data;
    const counts = `${d.entities.length} mentions, ${d.entities.reduce((n, m) => n + (m.occurrences || []).length, 0)} other namings, ${d.details.length} details, ${d.actions.length} actions`;
    h += `<div class="meta">${go("claim", d.claim_id, d.claim_id, `claim of ${d.title}`)}<span>·</span><span>${d.chars.toLocaleString()} characters</span><span>·</span><span title="What the pipeline extracted from this note">${counts}</span>
      ${d.review_count ? `<span class="chip warn" title="Quotes that could not be placed, or were placed with a caveat">${d.review_count} review item(s)</span>` : ""}</div>
      <div class="reader" data-note="${esc(d.id)}">${readerHTML(d, I.showActions)}</div>`;
  }
  h += `</div><aside id="drill"></aside></div>`;
  el.innerHTML = h;
  renderDrill();
  const tc = $("[data-to-cards]", el);
  if (tc) tc.addEventListener("click", () => { S.view = "cards"; renderWork(); });
  $("#inv-acts", el).addEventListener("change", (e) => { I.showActions = e.target.checked; renderWork(); });
  attachNoteSearch($("[data-inv-search]", el));
  if (I.state === "view") afterReader(el, null, { investigate: true });
}
let NOTES = null;
function attachNoteSearch(box) {
  const input = $("input", box), list = $(".suggest", box);
  let items = [], active = -1;
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    items = (NOTES || []).filter((n) => !q || n.id.includes(q) || n.claim_id.toLowerCase().includes(q)).slice(0, 10);
    list.innerHTML = items.map((n, i) => `<div class="item${i === active ? " active" : ""}" data-i="${i}"><span class="lab">Note ${esc(n.note_id)}</span><span class="sub">${esc(n.claim_id)} · ${n.chars.toLocaleString()} chars · ${n.mentions} mentions</span></div>`).join("") || `<div class="item muted">No note matches.</div>`;
    list.hidden = false;
  };
  const pick = (n) => { list.hidden = true; input.value = String(n.note_id); loadInvestigation(n.id); };
  input.addEventListener("focus", async () => { if (!NOTES) NOTES = await api("/api/notes").catch(() => []); draw(); });
  input.addEventListener("input", () => { active = -1; draw(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); draw(); e.preventDefault(); }
    else if (e.key === "Enter") { e.preventDefault(); const n = items[Math.max(active, 0)]; if (n) pick(n); }
    else if (e.key === "Escape") list.hidden = true;
  });
  list.addEventListener("mousedown", (e) => { const it = e.target.closest("[data-i]"); if (!it) return; e.preventDefault(); pick(items[+it.dataset.i]); });
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 150));
}

// ================================================================ trail and traces
function renderTrail() {
  const ol = $("#trail-list");
  const rows = S.cards;
  ol.innerHTML = rows.map((c, i) => {
    const closed = !!c.closedAt && !c.inv;
    const tag = c.inv ? "investigation" : c.kind === "answer" ? "question" : c.req ? c.req.kind : "";
    return `<li class="${closed ? "closed" : ""}${c.inv ? " inv" : ""}" data-id="${c.id}">
      <span class="t-n">${i + 1}</span><span class="t-main"><span class="t-label">${esc(c.label)}</span>
      <span class="t-why">${esc(c.why)} · ${esc(tag)} · ${esc(clock(c.openedAt))}${closed ? ` · closed ${esc(clock(c.closedAt))}` : ""}${c.pinned ? " · pinned" : ""}</span></span>
      ${c.inv ? "" : closed ? `<button class="mini" data-restore="${c.id}" title="Open it again as a bubble">Restore</button>` : `<span class="muted">open</span>`}</li>`;
  }).join("") || `<li class="muted">Nothing opened yet.</li>`;
  $$("li[data-id]", ol).forEach((li) => li.addEventListener("click", (e) => {
    const c = cardById(+li.dataset.id);
    if (!c) return;
    if (c.inv) { S.view = "investigate"; if (c.note && (!S.inv || S.inv.note !== c.note)) { if (!S.inv) S.inv = { note: null, showActions: false, drill: [] }; loadInvestigation(c.note); } renderWork(); }
    else if (e.target.dataset.restore) restoreCard(c.id);
    else if (!c.closedAt) reveal(c.id);
    else return;
    $("#trail-pop").hidden = true;
  }));
}
$("#trail-btn").addEventListener("click", () => { const p = $("#trail-pop"); $("#save-pop").hidden = true; p.hidden = !p.hidden; if (!p.hidden) renderTrail(); });
$$("[data-close-pop]").forEach((b) => b.addEventListener("click", () => (b.closest(".pop").hidden = true)));

function traceName() {
  const first = S.cards.find((c) => c.kind === "view" || c.kind === "answer");
  return (S.trace && S.trace.name) || `${first ? first.label : "Trace"} · ${new Date().toLocaleDateString([], { month: "short", day: "numeric" })}`;
}
$("#save-btn").addEventListener("click", () => {
  $("#trail-pop").hidden = true;
  const p = $("#save-pop");
  p.hidden = !p.hidden;
  if (!p.hidden) { $("#trace-name").value = traceName(); setTimeout(() => $("#trace-name").select(), 20); }
});
$("#trace-name").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#save-go").click(); });
$("#save-go").addEventListener("click", () => {
  const name = $("#trace-name").value.trim() || traceName();
  const t = snapshot(name);
  const all = store.get("goko.traces", []).filter((x) => x.id !== t.id);
  const ok = store.set("goko.traces", [t, ...all].slice(0, 50));
  $("#save-pop").hidden = true;
  resetWork();
  setMode("home");
  $(".switch [data-tab=traces]").click();
  flashNote(ok ? `Saved “${name}”.` : "This browser blocks storage: the trace could not be saved.");
});
function snapshot(name) {
  const keep = (c) => ({ id: c.id, kind: c.kind, req: c.req, label: c.label, why: c.why, openedAt: c.openedAt, closedAt: c.closedAt,
    pinned: !!c.pinned, pinnedAt: c.pinnedAt || 0, lensOverride: c.lensOverride || null, inv: c.inv || undefined, note: c.note,
    q: c.q, lens: c.lens, log: c.kind === "answer" ? c.log : undefined, result: c.kind === "answer" ? c.result : undefined });
  const created = (S.trace && S.trace.created) || (S.cards[0] && S.cards[0].openedAt) || now();
  return { id: (S.trace && S.trace.id) || `t${Date.now()}`, name, created, saved: now(), lens: S.lens,
    cards: S.cards.map(keep), order: S.order.slice(), start: S.start, view: S.view, seq: S.seq,
    inv: S.inv ? { note: S.inv.note, showActions: S.inv.showActions, drill: S.inv.drill } : null };
}
function resetWork() {
  Object.assign(S, { cards: [], order: [], start: 0, seq: 0, inv: null, trace: null, view: "cards", focus: null });
  GOKO.closeDrawer();
  $("#cards").innerHTML = "";
}
function restoreTrace(t) {
  resetWork();
  Object.assign(S, { trace: { id: t.id, name: t.name, created: t.created }, seq: t.seq || 0, order: t.order || [], start: t.start || 0,
    view: t.view || "cards", cards: t.cards.map((c) => ({ ...c, state: c.kind === "answer" ? "answer" : "loading", data: null })) });
  if (t.lens && t.lens !== S.lens) { S.lens = t.lens; GOKO.lens = t.lens; $$("#lens button").forEach((b) => b.classList.toggle("on", b.dataset.lens === S.lens)); loadList(); }
  S.inv = t.inv ? { ...t.inv, data: null } : null;
  setMode("work");
  openCards().forEach((c) => { if (c.kind === "view") loadCard(c); });
  if (S.inv && S.inv.note) loadInvestigation(S.inv.note);
  renderWork();
}
function renderTraces() {
  const ts = store.get("goko.traces", []);
  $("#list-meta").innerHTML = `${ts.length} saved trace${ts.length === 1 ? "" : "s"} <span class="muted">· kept in this browser only</span>`;
  $("#trace-list").innerHTML = ts.map((t) => {
    const n = t.cards.filter((c) => !c.inv).length, open = t.cards.filter((c) => !c.inv && !c.closedAt).length;
    return `<div class="trow" data-id="${esc(t.id)}"><div class="row"><input class="tname" value="${esc(t.name)}" aria-label="Trace name" title="Rename: edit and press Enter">
        <button class="mini x" data-del title="Delete this saved trace" aria-label="Delete">×</button></div>
      <div class="esub">${n} card${n === 1 ? "" : "s"} (${open} open) · ${t.inv && t.inv.note ? `investigation of ${esc(t.inv.note.replace("note:", "Note "))} · ` : ""}merge on ${esc(LENS[t.lens].toLowerCase())} · saved ${esc(day(t.saved))}</div>
      <button class="pill small" data-open-trace>Open</button></div>`;
  }).join("") || `<p class="muted pad">No saved traces yet. In the work view, “Save trace” keeps the cards, pins and settings here.</p>`;
  $$("#trace-list .trow").forEach((r) => {
    const t = ts.find((x) => x.id === r.dataset.id);
    $("[data-open-trace]", r).addEventListener("click", () => restoreTrace(t));
    $("[data-del]", r).addEventListener("click", () => { store.set("goko.traces", store.get("goko.traces", []).filter((x) => x.id !== t.id)); renderTraces(); });
    const inp = $(".tname", r);
    const rename = () => { const all = store.get("goko.traces", []); const x = all.find((y) => y.id === t.id); if (x && inp.value.trim()) { x.name = inp.value.trim(); store.set("goko.traces", all); } };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { rename(); inp.blur(); } });
    inp.addEventListener("change", rename);
  });
}

// ================================================================ start
(async () => {
  $$("#lens button").forEach((b) => b.classList.toggle("on", b.dataset.lens === S.lens));
  setMode("home");
  try {
    const m = await api("/api/meta");
    S.meta = m;
    $("#run-meta").innerHTML = `<span title="${esc(m.run && m.run.model ? "Extracted by " + m.run.model : "")}">${m.mentions.toLocaleString()} mentions · ${m.claims.length} claims · ${m.notes} notes</span> · <span title="${m.model ? "The librarian writes answers with a model; the key stays on the server" : "No model configured: lookups and retrieved facts only"}">librarian: ${esc(m.model || "no model")}</span>`;
  } catch { /* meta is decoration; the list below still loads */ }
  loadList();
})();
