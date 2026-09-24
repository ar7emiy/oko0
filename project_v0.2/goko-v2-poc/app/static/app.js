"use strict";
// GOKO search. Every entity in a list on the left; one dossier in the main pane; a trail of
// how you got there, and why each step was opened; an optional pinned dossier beside it for
// comparison; a librarian that streams the steps it really takes. Read-only: every view is
// computed by the server from one pipeline run, at the lens chosen in the top bar.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = GOKO.esc;
const S = { lens: "default", list: [], trail: [], cur: -1, pinned: null, meta: null };
GOKO.lens = S.lens;

// Recent searches live in this browser only; a private window or blocked storage just
// means no history, never a broken page.
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
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

// ---------------------------------------------------------------- navigation and trail
function navigate(req, label, why) {
  S.trail = S.trail.slice(0, S.cur + 1);
  const item = { req, label, why, state: "loading" };
  S.trail.push(item);
  if (S.trail.length > 40) S.trail.shift();
  S.cur = S.trail.length - 1;
  renderTrail();
  loadItem(item);
}
function goBack(i) {
  S.cur = i;
  renderTrail();
  const it = S.trail[i];
  if (it.kind !== "answer" && (it.lens !== S.lens || it.state !== "view")) loadItem(it); else renderMain();
}
async function loadItem(item, target = "main") {
  item.state = "loading"; item.lens = S.lens;
  target === "main" ? renderMain() : renderPinned();
  try {
    const q = new URLSearchParams({ kind: item.req.kind, id: item.req.id, lens: S.lens });
    if (item.req.span) q.set("span", JSON.stringify(item.req.span));
    item.data = await api("/api/view?" + q);
    item.state = "view";
    if (!item.label) item.label = item.data.title;
  } catch (e) { item.state = "error"; item.error = e.message; }
  target === "main" ? (renderMain(), renderTrail(), renderList()) : renderPinned();
}
function renderTrail() {
  const ol = $("#trail-list");
  ol.innerHTML = S.trail.map((t, i) => `<li class="${i === S.cur ? "cur" : ""}" data-i="${i}" title="${esc(`${t.label} — ${t.why}`)}">
      <span class="t-why">${esc(t.why || "")}</span><span class="t-label">${esc(t.label || "…")}</span></li>`).join("")
    || `<li class="empty">Steps appear here as you open things.</li>`;
  $$("li[data-i]", ol).forEach((li) => li.addEventListener("click", () => goBack(+li.dataset.i)));
  const c = $("li.cur", ol);
  if (c) c.scrollIntoView({ block: "nearest" });
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-go]");
  if (!a) return;
  e.preventDefault();
  const r = JSON.parse(a.dataset.go);
  if (a.closest("#drawer")) GOKO.closeDrawer();
  navigate({ kind: r.kind, id: r.id, span: r.span, key: r.key }, r.label, r.why || "opened");
});
document.addEventListener("goko:open", (e) => {
  const r = e.detail;
  navigate({ kind: r.kind, id: r.id, span: r.span }, r.label, r.why || "from a decision card");
});

// ---------------------------------------------------------------- lens
function setLens(l) {
  S.lens = l; GOKO.lens = l;
  $$("#lens button").forEach((b) => b.classList.toggle("on", b.dataset.lens === l));
  loadList();
  const it = S.trail[S.cur];
  if (it && it.kind !== "answer") loadItem(it);
  if (S.pinned) loadItem(S.pinned, "pinned");
}
$$("#lens button").forEach((b) => b.addEventListener("click", () => setLens(b.dataset.lens)));

// ---------------------------------------------------------------- the entity list
async function loadList() {
  $("#list-meta").textContent = "Loading…";
  try {
    const r = await api("/api/entities?lens=" + S.lens);
    S.list = r.entities; S.watch = r.watchlist;
  } catch (e) { $("#list-meta").textContent = e.message; return; }
  renderList();
}
function renderList() {
  const f = norm($("#filter").value);
  const rows = S.list.filter((e) => !f || norm(e.name).includes(f) || e.forms.some((x) => norm(x).includes(f)));
  const flagged = S.list.filter((e) => e.flag).length;
  $("#list-meta").innerHTML = `${rows.length}${f ? ` of ${S.list.length}` : ""} parties at <span class="term" title="The lens set in the top bar decides what counts as one party and what is flagged">${esc(S.lens)}</span>` +
    (flagged ? ` · <span class="flag-text" title="Parties with a mention linked to a record on the OIG exclusion list at this lens">${flagged} flagged for review</span>` : "");
  const it = S.trail[S.cur];
  const curId = it && it.data && it.data.kind === "entity" ? it.data.id : null;
  $("#entity-list").innerHTML = rows.map((e) => {
    const badge = e.flag
      ? `<span class="flag-badge" title="${esc(`Flagged for review: linked to the OIG exclusion record ${e.flag.record}, ${GOKO.probText(e.flag.p)}, ${(GOKO.BASIS[e.flag.basis_class] || [e.flag.basis_class])[0]}. A lead to check, not a finding.`)}">Flagged · ${esc(GOKO.band(e.flag.p))}</span>`
      : e.near ? `<span class="near-badge" title="${esc(`An exclusion-list link exists (${GOKO.probText(e.near.p)}) but this lens does not admit it${e.near.admitted.length ? "; it flags at " + e.near.admitted.join(", ") : ""}.`)}">possible match</span>` : "";
    return `<div class="erow${e.id === curId ? " on" : ""}" role="listitem" data-id="${esc(e.id)}" data-name="${esc(e.name)}" tabindex="0">
      <div class="ename"><span class="tdot t-${esc(e.type)}" title="${esc(TYPE_WORD[e.type] || e.type)}"></span>${esc(e.name)}</div>
      <div class="esub">${esc(TYPE_WORD[e.type] || e.type)} · ${e.mentions} mention${e.mentions === 1 ? "" : "s"} · ${e.claims} claim${e.claims === 1 ? "" : "s"} ${badge}</div></div>`;
  }).join("") || `<p class="muted pad">No party matches.</p>`;
  $$("#entity-list .erow").forEach((r) => {
    const open = () => navigate({ kind: "entity", id: r.dataset.id }, r.dataset.name, "from the list");
    r.addEventListener("click", open);
    r.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}
$("#filter").addEventListener("input", renderList);

// ---------------------------------------------------------------- the Ask pane
function openAsk() {
  $("#left").classList.add("asking");
  $("#list-pane").hidden = true; $("#ask-pane").hidden = false;
  renderIdeas();
  setTimeout(() => $("#ask-input").focus(), 30);
}
function closeAsk() {
  $("#left").classList.remove("asking");
  $("#ask-pane").hidden = true; $("#list-pane").hidden = false;
  $(".suggest", $("#ask-pane")).hidden = true;
}
$("#ask-btn").addEventListener("click", openAsk);
$("#ask-close").addEventListener("click", closeAsk);
document.addEventListener("keydown", (e) => {
  const drawerOpen = $("#drawer") && !$("#drawer").hidden;
  if (e.key === "Escape" && !$("#ask-pane").hidden && !drawerOpen) closeAsk();
  if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) && !drawerOpen) {
    e.preventDefault(); $("#ask-pane").hidden ? $("#filter").focus() : $("#ask-input").focus();
  }
});
function recent() { return store.get("goko.recent", []); }
function remember(q) {
  const r = [q, ...recent().filter((x) => x !== q)].slice(0, 8);
  store.set("goko.recent", r);
}
function contextIdeas() {
  const it = S.trail[S.cur], d = it && it.data, out = [];
  if (it && it.kind !== "answer" && d) {
    if (d.kind === "entity") {
      if (d.flagged && d.flagged.length) out.push(`Why is ${d.title} flagged for review?`);
      d.details.slice(0, 2).forEach((x) => out.push(`Who else shares ${x.raw}?`));
      out.push(`Which claims mention ${d.title}?`);
      if (d.related.length) out.push(`How is ${d.title} connected to ${d.related[0].name}?`);
    } else if (d.kind === "identifier") out.push(`Who else shares ${d.title}?`);
    else if (d.kind === "claim") out.push(`Which parties in ${d.title} appear in other claims?`);
    else if (d.kind === "note") out.push(`Who are the parties named in ${d.title}?`);
  }
  if (!out.length) out.push("Who is flagged for review?", "Which parties appear in more than one claim?");
  return [...new Set(out)].slice(0, 5);
}
function renderIdeas() {
  const ctx = contextIdeas(), rec = recent().filter((q) => !ctx.includes(q)).slice(0, 6);
  const it = S.trail[S.cur];
  let h = `<div class="ideas-h" title="Built from the dossier open in the main pane">${it && it.data ? `About ${esc(it.data.title || it.label)}` : "To start"}</div>` +
    ctx.map((q) => `<button class="idea" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  if (rec.length) h += `<div class="ideas-h" title="Stored in this browser only">Recent</div>` + rec.map((q) => `<button class="idea recent" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  $("#ask-ideas").innerHTML = h;
  $$("#ask-ideas .idea").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q)));
}

function attachSearch(box, onPick, onEnter) {
  const input = $("input", box), list = $(".suggest", box);
  let items = [], active = -1, timer = null, lastQ = "";
  const labels = { entity: "Parties", identifier: "Identifiers", claim: "Claims", note: "Notes" };
  const draw = () => {
    if (!input.value.trim()) { list.hidden = true; return; }
    let html = "", group = null;
    items.forEach((s, i) => {
      if (s.kind !== group) { group = s.kind; html += `<div class="group">${esc(labels[group])}</div>`; }
      html += `<div class="item${i === active ? " active" : ""}" data-i="${i}"><span class="lab">${esc(s.label)}</span><span class="sub">${esc(s.sub)}</span></div>`;
    });
    html += `<div class="item ask${active === items.length ? " active" : ""}" data-i="${items.length}" title="The librarian decides: a lookup opens a dossier, a question gets an answer with sources">Ask the librarian: “${esc(input.value.trim())}”</div>`;
    list.innerHTML = html; list.hidden = false;
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
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 150));
}
attachSearch($("#ask-pane [data-search]"),
  (s, q) => { remember(q); closeAsk(); navigate({ kind: s.kind, id: s.id }, s.label, `search “${q}”`); },
  (q) => ask(q));

// ---------------------------------------------------------------- the librarian, streamed
async function ask(q) {
  remember(q);
  closeAsk();
  $("#ask-input").value = "";
  S.trail = S.trail.slice(0, S.cur + 1);
  const item = { kind: "answer", q, label: q, why: "asked", lens: S.lens, log: [], result: null, state: "answer", t0: performance.now() };
  S.trail.push(item); S.cur = S.trail.length - 1;
  renderTrail(); renderMain();
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
        if (line) onAskEvent(item, JSON.parse(line.slice(6)));
      }
    }
    if (!item.result) throw new Error("the answer stream ended without a result");
  } catch (e) {
    item.result = { mode: "error", error: e.message };
    if (S.trail[S.cur] === item) renderMain();
  }
}
function onAskEvent(item, e) {
  if (e.step !== "result") {
    item.log.push(e);
    if (S.trail[S.cur] === item) renderAnswerLog(item);
    return;
  }
  item.result = e;
  if (e.mode === "lookup" && e.view) {
    // a lookup is a navigation, not an answer: the step becomes the dossier it opened
    Object.assign(item, { kind: undefined, req: { kind: e.view.kind, id: e.view.id }, data: e.view, state: "view",
      label: e.view.title, why: `search “${item.q}”` });
    renderTrail(); renderList();
  }
  if (S.trail[S.cur] === item) renderMain();
}

// ---------------------------------------------------------------- rendering
function renderMain() {
  const it = S.trail[S.cur];
  const el = $("#main");
  if (!it) {
    el.innerHTML = welcome();
    return;
  }
  renderPane(el, it, false);
}
function renderPinned() {
  const el = $("#pinned");
  el.hidden = !S.pinned;
  document.body.classList.toggle("has-pin", !!S.pinned);
  if (S.pinned) renderPane(el, S.pinned, true);
}
function paneHead(title, it, pinned, meta = "") {
  const btn = pinned
    ? `<button class="pill ghost" data-unpin title="Remove the pinned dossier">Unpin</button>`
    : it.kind === "answer" ? "" : `<button class="pill ghost" data-pin title="Keep this dossier beside the main pane for comparison">Pin</button>`;
  return `<div class="pane-head">${pinned ? `<div class="pin-tag" title="Pinned for comparison. It follows the lens; links in it open in the main pane.">Pinned</div>` : ""}
    <div class="row"><h1 class="title grow">${title}</h1>${btn}</div>${meta}</div>`;
}
function renderPane(el, it, pinned) {
  if (it.kind === "answer") { el.innerHTML = drawAnswer(it); wireAnswer(el, it); return; }
  if (it.state === "loading") { el.innerHTML = `${paneHead(esc(it.label || "…"), it, pinned)}<div class="pane-body"><div class="thinking"><span class="dot"></span>Loading…</div></div>`; wirePane(el, it, pinned); return; }
  if (it.state === "error") { el.innerHTML = `${paneHead(esc(it.label || "Error"), it, pinned)}<div class="pane-body"><p class="err">${esc(it.error)}</p></div>`; wirePane(el, it, pinned); return; }
  const d = it.data;
  const html = { entity: drawEntity, identifier: drawIdentifier, note: drawNote, claim: drawClaim }[d.kind](d, it, pinned);
  el.innerHTML = html;
  wirePane(el, it, pinned);
  if (d.kind === "note") afterNote(el, it);
}
function wirePane(el, it, pinned) {
  GOKO.wire(el);
  const p = $("[data-pin]", el);
  if (p) p.addEventListener("click", () => { S.pinned = { req: it.req, label: it.label, why: "pinned", data: it.data, state: it.state, lens: it.lens }; renderPinned(); });
  const u = $("[data-unpin]", el);
  if (u) u.addEventListener("click", () => { S.pinned = null; renderPinned(); });
  $$("[data-more]", el).forEach((b) => b.addEventListener("click", () => {
    b.closest("section").querySelectorAll(".extra").forEach((x) => x.classList.remove("extra"));
    b.remove();
  }));
}
function welcome() {
  return `<div class="welcome"><h1 class="title">One run, read-only</h1>
    <p>Pick a party on the left to open its dossier. Parties <span class="flag-text">flagged for review</span> come first: a mention of them links to a record on the federal health-care exclusion list (OIG LEIE) at the lens chosen above.</p>
    <p><strong>Ask</strong> opens the librarian: type a name, an identifier, a claim or a note to open it, or ask a question to get an answer built only from the graph, with every step it took shown as it happens.</p>
    <p>The <strong>trail</strong> records every step and why you took it; click one to go back. <strong>Pin</strong> keeps a dossier beside the main pane to compare two parties.</p>
    <p class="muted">Every merge is a read-time view of scored links. The lens decides which links count: Strict admits identifier-backed links only, Default any basis at p ≥ 0.80, Broad adds weak name matches. Click any link sentence, candidate or flag to see how it was decided.</p></div>`;
}

// ---------------------------------------------------------------- evidence
function evidence(x, why, key) {
  if (!x) return `<div class="ev muted">no source passage</div>`;
  return `${GOKO.excerptHTML(x)}<div class="src">${go("note", x.note, x.note.replace("note:", "Note "), why, { span: x.span, key })}
    <span class="muted">${esc(x.claim_id)}</span></div>`;
}
const more = (n, shown, what) => (n > shown ? `<button class="pill ghost small" data-more>Show all ${n} ${what}</button>` : "");

// ---------------------------------------------------------------- entity
function drawEntity(d, it, pinned) {
  const T = d.title;
  const flagged = d.flagged && d.flagged.length;
  const meta = `<div class="meta"><span title="Entity type, as the model read it">${esc(d.type)}</span><span>·</span>
      <span>${d.claims.map((c) => go("claim", c, c, `claim of ${T}`)).join(", ")}</span>
      ${flagged ? `<span class="chip bad" title="At this lens a mention of this party links to a record on the OIG exclusion list (LEIE). A lead to check, not a finding.">Flagged for review</span>` : ""}</div>
    ${GOKO.summaryHTML(d)}${GOKO.categoryHTML(d)}`;
  let h = paneHead(esc(T), it, pinned, meta) + `<div class="pane-body">`;
  if (flagged) h += `<section class="block"><h2 title="Exclusion-list records a mention of this party links to, admitted at this lens. Each row opens its decision card.">Flagged for review · OIG exclusion list</h2>${d.flagged.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.details.length) {
    h += `<section class="block"><h2 title="Identifiers the notes attribute to this party. SSNs and bank accounts show their last four digits only.">Identifiers</h2>`;
    d.details.forEach((x, i) => {
      h += `<div class="card${i >= 6 ? " extra" : ""}"><div class="row"><span class="chip" title="Identifier type">${esc(cap(x.type))}</span><span class="grow">${go("identifier", x.ident, x.raw, `identifier of ${T}`)}</span>
        <span class="muted" title="stated: the note says whose it is; inferred: the model concluded it">${esc(x.basis || "")}${x.checksum && x.checksum !== "n/a" ? ` · <span title="Check-digit test on the value">checksum ${esc(x.checksum)}</span>` : ""}</span></div>
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
    h += `<div class="card${i >= 5 ? " extra" : ""}"><div class="mhead"><strong>${esc(m.name)}</strong><div class="how">${how}</div></div>${evidence(m.evidence, `mention of ${T}`, m.key)}</div>`;
  });
  h += more(d.members.length, 5, "mentions") + `</section>`;
  if (d.related.length) h += `<section class="block"><h2 title="Parties that take part in the same actions, with how often">Appears with</h2><div class="meta">${d.related.slice(0, 16).map((r) => `<span class="chip">${go(r.kind, r.id, r.name, `appears with ${T}`)} ×${r.count}</span>`).join("")}</div></section>`;
  if (d.actions.length) {
    h += `<section class="block"><h2 title="What the notes say this party did or had done to it, with the source passage">Actions (${d.actions.length})</h2>`;
    d.actions.slice(0, 40).forEach((a, i) => {
      h += `<div class="card${i >= 6 ? " extra" : ""}"><div class="row"><strong>${esc(cap(a.type))}</strong><span class="muted">as ${esc(a.role)}</span>
        ${a.stance && a.stance !== "asserted" ? `<span class="chip warn" title="How the text presents the event">${esc(a.stance)}</span>` : ""}${a.time ? `<span class="muted">${esc(a.time)}</span>` : ""}</div>
        ${a.others.length ? `<div class="muted">with ${a.others.map((o) => `${go(o.kind, o.id, o.name, `co-party of ${T}`)} (${esc(o.role)})`).join(", ")}</div>` : ""}
        ${evidence(a.evidence, `action of ${T}`)}</div>`;
    });
    h += more(Math.min(d.actions.length, 40), 6, "actions") + `</section>`;
  }
  h += GOKO.candidatesHTML(d.candidates, d.lens);
  if (d.watchlist_near && d.watchlist_near.length) h += `<section class="block"><h2 title="Exclusion-list links below this lens's threshold, or vetoed. They do not flag the party here.">Exclusion-list links this lens does not admit</h2>${d.watchlist_near.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.refused.length) h += `<section class="block"><h2 title="Unions the projection refused: a veto, or the cluster-size alarm">Refused merges</h2>${d.refused.map((r) => `<div class="card"><span class="link" ${GOKO.cardAttr(r.a, r.b)}>${esc(r.reason === "veto" ? "would join a vetoed pair" : "would pass the cluster-size alarm")}</span></div>`).join("")}</section>`;
  return h + `</div>`;
}

// ---------------------------------------------------------------- identifier, claim
function drawIdentifier(d, it, pinned) {
  const meta = `<div class="meta"><span class="chip" title="Identifier type">${esc(cap(d.detail_type))}</span><span>${d.evidence.length} occurrence(s)</span><span>·</span>
    <span>${d.claims.map((c) => go("claim", c, c, `claim with ${d.title}`)).join(", ")}</span>
    ${d.suspicion ? `<span class="chip bad" title="The same value appears across ${esc(cap(d.distance))}: shared details are relationships worth a look, not identities">shared across ${esc(cap(d.distance))}</span>` : ""}
    ${d.masked ? `<span class="chip" title="Shown as its last four digits; the full value never reaches this page">masked</span>` : ""}</div>`;
  let h = paneHead(`<span class="mono">${esc(d.title)}</span>`, it, pinned, meta) + `<div class="pane-body">`;
  h += `<section class="block"><h2>Held by</h2>${d.holders.length ? d.holders.map((x) => `<div class="card row"><span class="grow">${go(x.kind, x.id, x.name, `holds ${d.title}`)}</span><span class="muted">${esc(x.type)} · ${esc(x.claims.join(", "))}</span></div>`).join("") : `<p class="muted">No owner was assigned.</p>`}
    ${d.unassigned ? `<p class="muted" title="A pattern or the model found the value, but not whose it is">${d.unassigned} occurrence(s) with no owner (unassigned).</p>` : ""}</section>`;
  h += `<section class="block"><h2>Evidence</h2>${d.evidence.map((x) => `<div class="card">${evidence(x, `passage with ${d.title}`)}</div>`).join("")}</section>`;
  return h + `</div>`;
}
function drawClaim(d, it, pinned) {
  const meta = `<div class="meta"><span>${d.entities.length} parties</span><span>·</span><span>${d.notes.length} notes</span></div>`;
  let h = paneHead(esc(d.title), it, pinned, meta) + `<div class="pane-body">`;
  h += `<section class="block"><h2>Parties</h2>${d.entities.map((e) => `<div class="card"><div>${go(e.kind, e.id, e.name, `party in ${d.title}`)}</div>
      <div class="meta"><span>${esc(e.type)} · ${e.mentions} mention(s)${e.confidence != null ? " · weakest link " + esc(GOKO.probText(e.confidence)) : ""}</span>
      ${e.elsewhere.length ? `<span class="chip warn" title="The same entity, at this lens, also appears in these claims">also in ${e.elsewhere.length} other claim(s)</span>` : ""}
      ${e.category ? `<span class="chip" title="Role, the model's reading, not identity">${esc(e.category.value === "insufficient_evidence" ? "undetermined" : cap(e.category.value))}</span>` : ""}</div></div>`).join("")}</section>`;
  h += `<section class="block"><h2>Notes</h2>${d.notes.map((n) => `<div class="card row"><span class="grow">${go("note", n.id, n.title, `note of ${d.title}`)}</span><span class="muted">${n.chars.toLocaleString()} chars</span></div>`).join("")}</section>`;
  return h + `</div>`;
}

// ---------------------------------------------------------------- note reader
function drawNote(d, it, pinned) {
  const meta = `<div class="meta">${go("claim", d.claim_id, d.claim_id, `claim of ${d.title}`)}<span>·</span><span>${d.chars.toLocaleString()} characters</span>
    ${d.extraction_error ? `<span class="chip bad" title="${esc(d.extraction_error)}">extraction partial</span>` : ""}
    <span class="legend" title="Every extracted mention is highlighted by entity type. Click one for its dossier summary."><span class="m t-person">person</span><span class="m t-organization">organization</span><span class="m t-vehicle">vehicle</span></span></div>`;
  const t = d.text, hl = (it.req && it.req.span) || d.highlight;
  const ms = d.entities.filter((e) => e.span).sort((a, b) => a.span[0] - b.span[0] || b.span[1] - a.span[1]);
  let pos = 0, body = "", hlDone = false;
  const hlMark = (s, e) => `<mark class="hl" id="hl">${esc(t.slice(s, e))}</mark>`;
  for (const m of ms) {
    const [s, e] = m.span;
    if (s < pos) continue;
    if (hl && !hlDone && hl[0] >= pos && hl[1] <= s) { body += esc(t.slice(pos, hl[0])) + hlMark(hl[0], hl[1]); pos = hl[1]; hlDone = true; }
    const isHl = hl && !hlDone && hl[0] < e && s < hl[1];
    if (isHl) hlDone = true;
    body += esc(t.slice(pos, s)) + `<mark class="m t-${esc(m.type)}${m.flagged ? " flagged" : ""}${isHl ? " hl" : ""}" data-key="${esc(m.key)}" data-entity="${esc(m.id)}" data-name="${esc(m.name)}" tabindex="0"
      title="${esc(`${m.mention_name} · ${m.type}${m.flagged ? " · flagged for review" : ""}. Click for its dossier summary.`)}">${esc(t.slice(s, e))}</mark>`;
    pos = e;
  }
  if (hl && !hlDone && hl[0] >= pos) { body += esc(t.slice(pos, hl[0])) + hlMark(hl[0], hl[1]); pos = hl[1]; }
  body += esc(t.slice(pos));
  return paneHead(esc(d.title), it, pinned, meta) + `<div class="pane-body"><div class="reader" data-note="${esc(d.id)}">${body}</div></div>`;
}
function afterNote(el, it) {
  $$(".reader mark.m", el).forEach((m) => {
    const open = () => peek(m.dataset.key, m.dataset.entity, m.dataset.name, $(".reader", el).dataset.note);
    m.addEventListener("click", open);
    m.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
  const target = (it.req && it.req.key && $(`.reader mark[data-key="${CSS.escape(it.req.key)}"]`, el)) || $(".reader .hl", el);
  if (target) setTimeout(() => flash(target), 30);
}
function flash(m) {
  m.scrollIntoView({ block: "center" });
  m.classList.remove("flash"); void m.offsetWidth; m.classList.add("flash");
}
// the mention drawer: the dossier in brief, and every mention of the party to jump to
async function peek(key, entityId, name, noteId) {
  const body = GOKO.openDrawer(esc(name), `<div class="thinking"><span class="dot"></span>Loading…</div>`);
  let d;
  try { d = await api("/api/view?" + new URLSearchParams({ kind: "entity", id: key, lens: S.lens })); }
  catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  let h = `<div class="meta">${esc(d.type)} · ${d.claims.map(esc).join(", ")}</div>${GOKO.summaryHTML(d)}${GOKO.categoryHTML(d)}
    <p><button class="pill" ${goAttr({ kind: "entity", id: d.id, label: d.title, why: `from ${noteId.replace("note:", "Note ")}` })}>Open the full dossier</button></p>`;
  if (d.flagged && d.flagged.length) h += `<section class="block"><h2>Flagged for review</h2>${d.flagged.map(GOKO.watchRowHTML).join("")}</section>`;
  if (d.details.length) h += `<section class="block"><h2>Identifiers</h2>${d.details.slice(0, 8).map((x) => `<div class="row"><span class="chip">${esc(cap(x.type))}</span><span class="mono">${esc(x.raw)}</span></div>`).join("")}</section>`;
  h += `<section class="block"><h2 title="Click one to jump to it in the note, or to open the note it is in">Mentions (${d.members.length})</h2>` +
    d.members.map((m) => `<div class="peek-m${m.key === key ? " on" : ""}" data-note="${esc(m.note)}" data-key="${esc(m.key)}" data-span='${esc(JSON.stringify(m.evidence ? m.evidence.span : null))}'>
      <strong>${esc(m.name)}</strong> <span class="muted">${esc(m.note.replace("note:", "Note "))}${m.note === noteId ? " · this note" : ""} · ${esc(m.claim_id)}</span></div>`).join("") + `</section>`;
  body.innerHTML = h;
  GOKO.wire(body, { open: false });
  $$(".peek-m", body).forEach((x) => x.addEventListener("click", () => {
    const span = JSON.parse(x.dataset.span);
    const here = $(`#main .reader[data-note="${CSS.escape(x.dataset.note)}"]`);
    if (here) {
      const m = $(`mark[data-key="${CSS.escape(x.dataset.key)}"]`, here);
      if (m) flash(m);
      $$(".peek-m", body).forEach((y) => y.classList.toggle("on", y === x));
      return;
    }
    GOKO.closeDrawer();
    navigate({ kind: "note", id: x.dataset.note, span, key: x.dataset.key }, x.dataset.note.replace("note:", "Note "), `mention of ${d.title}`);
  }));
}

// ---------------------------------------------------------------- answers
const STEP_ICON = { route: "Route", match: "Match", expand: "Expand", facts: "Facts", model_start: "Model", model_done: "Model", model_failed: "Model", model_skip: "Model", citations: "Cite" };
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
function drawAnswer(it) {
  const r = it.result, running = !r;
  const facts = (it.log.find((e) => e.step === "facts") || {}).facts || (r && r.facts) || [];
  const secs = r ? ((it.log.length ? it.log[it.log.length - 1].t : 0)).toFixed(1) : null;
  let h = `<div class="pane-head"><div class="row"><h1 class="title grow">${esc(it.q)}</h1></div>
    <div class="meta"><span title="The lens the answer was built at">lens ${esc(it.lens)}</span>${r && r.routed_by ? `<span>· routed by ${esc(cap(r.routed_by))}</span>` : ""}${r && r.facts_used ? `<span>· ${r.facts_used} facts</span>` : ""}</div></div><div class="pane-body">`;
  const open = running || it.logOpen || (r && r.no_model && it.logOpen !== false);
  h += `<details class="log"${open ? " open" : ""}><summary title="The steps the server actually took, as they happened">${running ? `<span class="dot"></span> Working…` : `${it.log.length} steps · ${secs} s`}</summary><ol>${it.log.map(logLine).join("")}</ol></details>`;
  const factsBox = `<div class="facts" hidden><div class="ideas-h">What was sent (${facts.length} facts)</div>${facts.map((f) => `<div class="fact mono">${esc(f)}</div>`).join("")}</div>`;
  if (!r) return h + `<p class="thinking"><span class="dot"></span>The librarian is reading the graph…</p>${factsBox}</div>`;
  if (r.mode === "error") return h + `<p class="err">${esc(r.error)}</p></div>`;
  const order = [];
  const text = esc(r.answer || "").replace(/\[([ea]\d+)\]/g, (m, a) => {
    const c = (r.citations || {})[a];
    if (!c) return "";
    if (!order.includes(a)) order.push(a);
    return `<span class="cite" ${goAttr({ kind: c.kind, id: c.id, label: c.label, span: c.span, why: `cited in “${it.q.slice(0, 40)}”` })} title="${esc(c.label)}">${order.indexOf(a) + 1}</span>`;
  });
  h += `<div class="answer${r.error ? " err" : ""}${r.no_model ? " muted" : ""}">${text}</div>`;
  if (r.confidence_note) h += `<p class="muted">${esc(r.confidence_note)}</p>`;
  if (order.length) h += `<section class="block"><h2>Sources</h2>${order.map((a, i) => {
    const c = r.citations[a];
    const what = c.kind === "note" ? `${esc(cap(c.label))} · ${esc(c.id.replace("note:", "Note "))}` : esc(c.label);
    return `<div class="source"><span class="cite" ${goAttr({ kind: c.kind, id: c.id, label: c.label, span: c.span, why: "source of an answer" })}>${i + 1}</span><span class="link" ${goAttr({ kind: c.kind, id: c.id, label: c.label, span: c.span, why: "source of an answer" })}>${what}</span><span class="muted">${c.kind === "note" ? "source passage" : "party"}</span></div>`;
  }).join("")}</section>`;
  if (facts.length) h += `<p><button class="pill ghost small" data-show-facts title="The exact facts, with their aliases, that ${r.no_model ? "a model would have received" : "the model received"}">show what was sent (${facts.length} facts)</button></p>`;
  return h + factsBox + `</div>`;
}
function renderAnswerLog(it) {
  const el = $("#main");
  const ol = $("details.log ol", el);
  if (!ol) return renderMain();
  ol.innerHTML = it.log.map(logLine).join("");
  wireAnswer(el, it);
}
function wireAnswer(el, it) {
  $$("[data-show-facts]", el).forEach((x) => x.addEventListener("click", () => {
    const f = $(".facts", el);
    f.hidden = !f.hidden;
    $$("[data-show-facts]", el).forEach((y) => { y.textContent = y.textContent.replace(f.hidden ? "hide" : "show", f.hidden ? "show" : "hide"); });
    if (!f.hidden) f.scrollIntoView({ block: "start", behavior: "smooth" });
  }));
  const det = $("details.log", el);
  if (det) det.addEventListener("toggle", () => { if (it.result) it.logOpen = det.open; });
}

// ---------------------------------------------------------------- start
(async () => {
  $$("#lens button").forEach((b) => b.classList.toggle("on", b.dataset.lens === S.lens));
  renderTrail(); renderMain();
  try {
    const m = await api("/api/meta");
    S.meta = m;
    $("#run-meta").innerHTML = `<span title="${esc(m.run && m.run.model ? "Extracted by " + m.run.model : "")}">${m.mentions.toLocaleString()} mentions · ${m.claims.length} claims · ${m.notes} notes</span> · <span title="${m.model ? "The librarian writes answers with a model; the key stays on the server" : "No model configured: lookups and retrieved facts only"}">librarian: ${esc(m.model || "no model")}</span>`;
  } catch { /* meta is decoration; the list below still loads */ }
  loadList();
})();
