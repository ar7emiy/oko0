"use strict";
/* Claim Note Annotator — browser app. No framework, no build step, nothing fetched from the internet.
   All note text, AI output and user input is rendered with textContent, never innerHTML. */

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "data") for (const [dk, dv] of Object.entries(v)) el.dataset[dk] = dv;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ---------------------------------------------------------------------------
// Vocabulary shown to reviewers
// ---------------------------------------------------------------------------
const KINDS = {
  entity:      { label: "Person or company", cls: "party",   key: "1", help: "The first time someone or something is named: a person, company, clinic or place." },
  mention:     { label: "Another mention",   cls: "party",   key: "2", help: "A later reference to someone already recorded: the name again, a short name, “she”, “the clinic”." },
  detail:      { label: "Detail",            cls: "detail",  key: "3", help: "An address, city, state, ZIP code, phone, TIN or other identifier stated about someone." },
  description: { label: "Description",       cls: "desc",    key: "4", help: "Words that say what someone is: “orthopedic surgeon”, “the medical provider”." },
  action:      { label: "Action or link",    cls: "action",  key: "5", help: "What someone did, or how two parties are connected. Keep words like “not”." },
  unclear:     { label: "Unclear",           cls: "unclear", key: "6", help: "Words you can’t confidently link to one person or company. Say why." },
};
const ORDER = ["entity", "mention", "detail", "description", "action", "unclear"];
const ENTITY_TYPES = [["person", "Person"], ["organization", "Organization"], ["location", "Place"], ["other", "Other"], ["unknown", "Not sure"]];
const FORMS = [["name", "Name"], ["alias", "Short name or alias"], ["pronoun", "Pronoun"], ["description", "Description (“the clinic”)"]];
const FIELDS = [["address", "Street address"], ["city", "City"], ["state", "State"], ["zip_code", "ZIP code"], ["phone", "Phone"], ["TIN", "TIN (tax ID)"], ["other", "Other identifier"]];
const FIELD_LABEL = Object.fromEntries(FIELDS);
const TYPE_LABEL = Object.fromEntries(ENTITY_TYPES);
const FORM_LABEL = Object.fromEntries(FORMS);
const PRONOUNS = new Set("he she they him her them his hers their theirs it its himself herself themselves".split(" "));
const UNCLEAR_REASONS = ["The note doesn’t say who this is.", "It could be more than one person or company.", "The note gives conflicting information.", "It’s a report or allegation, not confirmed."];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const S = {
  reviewer: store.get("reviewer", ""),
  boot: null,
  claims: [],
  cur: null,            // {claim, note}
  data: null,           // note payload from the server
  sel: null,            // {start, end} in code points
  focus: null,          // entity id highlighted everywhere
  reviewId: null,       // draft being reviewed
  tab: "people",
  view: "welcome",
};

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Can't reach the annotator. Is its window still open?");
  }
  let payload = {};
  try { payload = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error(payload.error || `Request failed (${res.status}).`);
  return payload;
}
const qs = (o) => "?" + new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null))).toString();
const withMe = (o) => ({ ...o, reviewer: S.reviewer });

function toast(message, opts = {}) {
  const t = h("div", { class: "toast" + (opts.bad ? " bad" : ""), role: opts.bad ? "alert" : "status" }, message);
  if (opts.action) t.append(h("button", { class: "link", type: "button", text: opts.action.label, onclick: () => { opts.action.run(); t.remove(); } }));
  const box = $("#toasts");
  box.append(t);
  while (box.children.length > 2) box.firstElementChild.remove();
  setTimeout(() => t.remove(), opts.ms || (opts.bad ? 7000 : 2000));
}
const fail = (e) => toast(e.message || String(e), { bad: true });

// ---------------------------------------------------------------------------
// Positions: the server counts Unicode code points; JavaScript strings count UTF-16 units.
// ---------------------------------------------------------------------------
let TEXT = "";
let CP2U = null;           // null when the note has no characters outside the BMP (then they're equal)
let CPLEN = 0;

function setText(text) {
  TEXT = text;
  if (!/[\uD800-\uDFFF]/.test(text)) { CP2U = null; CPLEN = text.length; return; }
  const map = [];
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0xDC00 && c <= 0xDFFF && i > 0) { const p = text.charCodeAt(i - 1); if (p >= 0xD800 && p <= 0xDBFF) continue; }
    map.push(i);
  }
  map.push(text.length);
  CP2U = Int32Array.from(map);
  CPLEN = map.length - 1;
}
const u16 = (cp) => (CP2U ? CP2U[Math.max(0, Math.min(cp, CPLEN))] : cp);
function cpLen(s) {
  let n = s.length;
  for (let i = 1; i < s.length; i++) { const c = s.charCodeAt(i); if (c >= 0xDC00 && c <= 0xDFFF) { const p = s.charCodeAt(i - 1); if (p >= 0xD800 && p <= 0xDBFF) n--; } }
  return n;
}
const sliceCp = (a, b) => TEXT.slice(u16(a), u16(b));

// ---------------------------------------------------------------------------
// Claims list
// ---------------------------------------------------------------------------
async function loadClaims() {
  const { claims } = await api("/api/claims" + qs({ reviewer: S.reviewer }));
  S.claims = claims;
  renderClaims();
}

function renderClaims() {
  const box = $("#claims");
  box.replaceChildren();
  const term = $("#search").value.trim().toLowerCase();
  for (const c of S.claims) {
    const notes = c.notes.filter((n) => !term || (c.claim + " " + n.note).toLowerCase().includes(term));
    if (!notes.length) continue;
    const total = c.notes.length;
    const head = h("div", { class: "claim-head" }, h("span", { class: "claim-name", text: claimLabel(c.claim) }),
      c.practice ? h("span", { class: "tag", text: "practice" }) : null,
      h("span", { class: "claim-progress", text: `${c.complete}/${total} done` }));
    const bar = h("div", { class: "claim-bar" }, h("span"));
    bar.firstChild.style.width = `${(100 * c.complete) / Math.max(1, total)}%`;
    const list = notes.map((n) => {
      const active = S.cur && S.cur.claim === c.claim && S.cur.note === n.note && S.view === "note";
      const meta = [n.records ? `${n.records} rec` : null, n.pending ? `${n.pending} AI` : null].filter(Boolean).join(" · ");
      return h("button", {
        class: "note-link" + (active ? " active" : ""), type: "button",
        title: n.status === "complete" ? "Complete" : n.status === "in_progress" ? "In progress" : "Not started",
        onclick: () => openNote(c.claim, n.note),
      }, h("span", { class: "dot " + n.status, "aria-hidden": "true" }), `Note ${n.note}`, h("span", { class: "meta", text: meta }));
    });
    let action = null;
    if (c.sealed) action = h("button", { class: "btn small claim-action", type: "button", onclick: () => openCompare(c.claim) }, "Open firm comparison");
    else if (c.complete === total && total) action = h("button", { class: "btn primary small claim-action", type: "button", onclick: () => openClaimReview(c.claim) }, "Review claim evidence");
    box.append(h("div", { class: "claim", data: { claim: c.claim } }, head, bar, ...list, action));
  }
  if (!box.children.length) box.append(h("div", { class: "empty", text: term ? "No claims or notes match." : "No notes found. Ask your coordinator which folder to start the annotator with." }));
  const boot = S.boot || {};
  const foot = $("#sidebar-foot");
  foot.replaceChildren();
  if (boot.skipped && boot.skipped.length) foot.append(h("div", { text: `${boot.skipped.length} file(s) skipped — see the server window.` }));
  foot.append(h("div", { text: boot.notes_dir ? `Notes: ${boot.notes_dir}` : "Only the practice note is loaded." }));
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------
function showView(name) {
  S.view = name;
  for (const v of ["welcome", "note", "review", "compare", "scores"]) $("#view-" + v).hidden = v !== name;
  $("#panel").hidden = name !== "note";
  $(".shell").style.gridTemplateColumns = name === "note" ? "" : "272px minmax(0, 1fr)";
  renderCrumbs();
  renderClaims();
}

const claimLabel = (claim) => (claim === "PRACTICE" ? "Practice claim" : claim === "PRACTICE2" ? "Practice claim 2" : `Claim ${claim}`);

function renderCrumbs() {
  const c = $("#crumbs");
  c.replaceChildren();
  const sep = () => h("span", { "aria-hidden": "true", text: "›" });
  if (S.view === "note" && S.cur) c.append(h("b", { text: claimLabel(S.cur.claim) }), sep(), h("span", { text: `Note ${S.cur.note}` }));
  else if (S.view === "compare" && S.compareClaim) c.append(h("b", { text: claimLabel(S.compareClaim) }), sep(), h("span", { text: "Compare with the firm" }));
  else if (S.view === "scores") c.append(h("b", { text: "Scores" }));
  else if (S.view === "review") c.append(h("b", { text: claimLabel(S.claimReview.claim) }), sep(), "Review evidence and categories");
  if (S.view === "note" && S.claimReview?.claim === S.cur?.claim) c.append(h("button", {class: "btn small", type: "button", onclick: () => openClaimReview(S.cur.claim, S.dossierEntity)}, "Return to claim review"));
}

// ---------------------------------------------------------------------------
// Opening a note
// ---------------------------------------------------------------------------
async function openNote(claim, note, opts = {}) {
  if (!S.reviewer) return askReviewer();
  try {
    const data = await api("/api/note" + qs({ claim, note, reviewer: S.reviewer }));
    const sameNote = S.cur && S.cur.claim === claim && S.cur.note === note;
    S.cur = { claim, note };
    S.data = data;
    setText(data.text);
    if (!sameNote) { S.focus = null; S.reviewId = null; S.sel = null; }
    showView("note");
    renderNoteHead();
    renderNote();
    renderPanel();
    if (!sameNote && !opts.keepScroll) $("#workspace").scrollTop = 0;
  } catch (e) { fail(e); }
}

async function refresh() {
  const scroll = $("#workspace").scrollTop;
  await Promise.all([openNote(S.cur.claim, S.cur.note, { keepScroll: true }), loadClaims()]);
  $("#workspace").scrollTop = scroll;
}

function renderNoteHead() {
  const d = S.data;
  $("#note-title").textContent = d.claim === "PRACTICE" ? `Practice note ${d.note}` : `${claimLabel(d.claim)} · Note ${d.note}`;
  const st = $("#note-status");
  st.className = "pill " + d.status;
  st.textContent = { not_started: "Not started", in_progress: "In progress", complete: "Complete" }[d.status] || d.status;
  const flags = [];
  if (d.blind) flags.push("No AI drafts");
  if (d.sealed) flags.push("Compared with firm");
  flags.push(`${d.length.toLocaleString()} characters`);
  $("#note-flags").textContent = flags.join(" · ");
  const complete = d.status === "complete";
  $("#btn-complete").textContent = complete ? "Reopen note" : "Mark note complete";
  $("#btn-complete").className = "btn" + (complete ? "" : " primary");
  $("#btn-ai").disabled = d.blind;
  $("#btn-ai").title = d.blind ? "This note is annotated without AI drafts" : "Get draft records from Copilot, then review each one";
  const banner = $("#note-banner");
  banner.hidden = true;
  banner.className = "banner";
  if (!d.fingerprint_ok) {
    banner.hidden = false;
    banner.classList.add("bad");
    banner.textContent = "This note's file has changed since you started. Saved highlights may not line up any more, so saving is blocked. Tell your coordinator.";
  } else if (d.sealed) {
    banner.hidden = false;
    banner.textContent = "You've already compared this claim with the firm's output. Changes you make now are saved but marked as made after seeing it.";
  }
}

// ---------------------------------------------------------------------------
// Rendering the note with highlights
// ---------------------------------------------------------------------------
const recordClass = (r) => ({ mention: "hl-party", detail: "hl-detail", description: "hl-desc", action: "hl-action", unclear: "hl-unclear" }[r.kind]);

function pendingDrafts() {
  return (S.data?.drafts || []).filter((d) => d.status === "ready" || d.status === "needs_attention");
}

function renderNote() {
  const root = $("#note-text");
  const items = [];
  for (const r of S.data.records) {
    const cls = [recordClass(r)];
    if (S.focus && (r.entity_id === S.focus || r.entity2_id === S.focus)) cls.push("hl-focus");
    items.push({ start: r.start, end: r.end, cls, hit: "r:" + r.uid });
  }
  const current = S.reviewId && S.data.drafts.find((d) => d.id === S.reviewId);
  for (const d of pendingDrafts()) {
    if (d.start === null || d.start === undefined) continue;
    items.push({ start: d.start, end: d.end, cls: [d.id === S.reviewId ? "hl-draft-current" : "hl-draft"], hit: "d:" + d.id });
  }
  if (current && current.start === null && current.candidates) {
    for (const [a, b] of current.candidates) items.push({ start: a, end: b, cls: ["hl-candidate"], hit: null });
  }
  if (S.sel && S.pinSelection) items.push({ start: S.sel.start, end: S.sel.end, cls: ["hl-selection"], hit: null });

  const cuts = new Set([0, CPLEN]);
  for (const it of items) { cuts.add(it.start); cuts.add(it.end); }
  const points = Array.from(cuts).filter((p) => p >= 0 && p <= CPLEN).sort((a, b) => a - b);
  const frag = document.createDocumentFragment();
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    if (a === b) continue;
    const cover = items.filter((it) => it.start <= a && it.end >= b);
    const span = document.createElement("span");
    span.className = "seg" + (cover.length ? " " + cover.flatMap((c) => c.cls).join(" ") : "");
    span.dataset.s = String(a);
    const hits = cover.map((c) => c.hit).filter(Boolean);
    if (hits.length) span.dataset.hit = hits.join(" ");
    span.textContent = sliceCp(a, b);
    frag.append(span);
  }
  root.replaceChildren(frag);
}

function scrollToCp(cp, flash = true) {
  const segs = $$("#note-text .seg");
  let target = segs[0];
  for (const s of segs) { if (+s.dataset.s <= cp) target = s; else break; }
  if (!target) return;
  target.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  if (flash) { target.classList.add("hl-flash"); setTimeout(() => target.classList.remove("hl-flash"), 1300); }
}

// ---------------------------------------------------------------------------
// Selecting words
// ---------------------------------------------------------------------------
function pointCp(node, offset) {
  const root = $("#note-text");
  if (node.nodeType === Node.TEXT_NODE) {
    const seg = node.parentElement.closest(".seg");
    return +seg.dataset.s + cpLen(node.data.slice(0, offset));
  }
  if (node === root) {
    const kid = root.childNodes[offset];
    return kid ? +kid.dataset.s : CPLEN;
  }
  const seg = node.closest ? node.closest(".seg") : null;
  if (!seg) return null;
  return offset === 0 ? +seg.dataset.s : +seg.dataset.s + cpLen(seg.textContent);
}

function readSelection() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  const root = $("#note-text");
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  let a = pointCp(range.startContainer, range.startOffset);
  let b = pointCp(range.endContainer, range.endOffset);
  if (a === null || b === null) return null;
  if (a > b) [a, b] = [b, a];
  while (a < b && /\s/.test(sliceCp(a, a + 1))) a++;
  while (b > a && /\s/.test(sliceCp(b - 1, b))) b--;
  return a < b ? { start: a, end: b } : null;
}

function onNoteMouseUp(ev) {
  if (S.view !== "note") return;
  setTimeout(() => {
    const span = readSelection();
    if (span) {
      S.sel = span;
      hidePopover();
      const draft = S.reviewId && S.data.drafts.find((d) => d.id === S.reviewId);
      if (draft && (draft.start === null || draft.start === undefined) && S.tab === "drafts") {
        renderPanel();
        toast("Now press “Use the words I selected” on the draft.");
        return;
      }
      showActionMenu();
      return;
    }
    hideActionMenu();
    const seg = ev.target.closest && ev.target.closest(".seg[data-hit]");
    if (seg) showRecordsAt(seg, ev);
  }, 0);
}

// ---------------------------------------------------------------------------
// The action menu that appears on selection
// ---------------------------------------------------------------------------
function showActionMenu() {
  const menu = $("#action-menu");
  const quote = sliceCp(S.sel.start, S.sel.end);
  const noEntities = !S.data.entities.length;
  menu.replaceChildren(h("div", { class: "action-quote", title: quote, text: `“${quote}”` }));
  for (const kind of ORDER) {
    const k = KINDS[kind];
    const needsParty = ["mention", "detail", "description", "action"].includes(kind);
    const disabled = needsParty && noEntities;
    menu.append(h("button", {
      class: "menu-item", type: "button", role: "menuitem", disabled,
      title: disabled ? "Record a person or company first" : k.help,
      onclick: () => { hideActionMenu(); openRecordForm(kind, { ...S.sel }); },
    }, h("span", { class: "swatch sw-" + k.cls }), h("b", { text: k.label }), h("kbd", { text: k.key }),
       h("small", { text: disabled ? "Record a person or company first." : k.help })));
  }
  menu.hidden = false;
  const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
  const mh = menu.offsetHeight, mw = menu.offsetWidth;
  let top = rect.bottom + 8;
  if (top + mh > window.innerHeight - 10) top = Math.max(10, rect.top - mh - 8);
  let left = Math.min(Math.max(10, rect.left), window.innerWidth - mw - 10);
  menu.style.top = `${top}px`;
  menu.style.left = `${left}px`;
}
function hideActionMenu() { $("#action-menu").hidden = true; }
function hidePopover() { $("#popover").hidden = true; }

function showRecordsAt(seg, ev) {
  const pop = $("#popover");
  pop.replaceChildren();
  for (const hit of seg.dataset.hit.split(" ")) {
    const [type, id] = hit.split(":");
    if (type === "r") {
      const r = S.data.records.find((x) => x.uid === id);
      if (r) pop.append(recordCard(r, { compact: true }));
    } else {
      const d = S.data.drafts.find((x) => x.id === id);
      if (d) pop.append(h("div", { class: "card clickable", onclick: () => { hidePopover(); startReview(d.id); } },
        h("div", { class: "card-top" }, h("span", { class: "kind draft", text: "AI draft" }), h("span", { class: "card-title", text: KINDS[d.type].label })),
        h("div", { class: "card-sub", text: "Click to review this draft" })));
    }
  }
  pop.hidden = false;
  const x = Math.min(ev.clientX, window.innerWidth - 360), y = Math.min(ev.clientY + 12, window.innerHeight - pop.offsetHeight - 10);
  pop.style.left = `${Math.max(10, x)}px`;
  pop.style.top = `${Math.max(10, y)}px`;
}

// ---------------------------------------------------------------------------
// Form building blocks
// ---------------------------------------------------------------------------
function field(label, control, help) {
  const target = control.matches && control.matches("input, select, textarea") ? control : control.querySelector && control.querySelector("input[type=text], select, textarea");
  if (target && !target.getAttribute("aria-label")) target.setAttribute("aria-label", label);
  if (control.getAttribute && control.getAttribute("role") === "group") control.setAttribute("aria-label", label);
  return h("div", { class: "field" }, h("span", { class: "label", text: label }), control, help ? h("div", { class: "help", text: help }) : null);
}

function choiceGroup(options, value, onChange) {
  const box = h("div", { class: "choices", role: "group" });
  let current = value ?? null;
  for (const [val, label] of options) {
    box.append(h("button", {
      class: "choice", type: "button", "aria-pressed": String(val === current), data: { value: val },
      onclick: () => { current = val; $$(".choice", box).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === val))); onChange && onChange(val); },
    }, label));
  }
  box.get = () => current;
  return box;
}

function entityName(id) {
  const e = S.data?.entities.find((x) => x.id === id);
  return e ? `E${e.number} · ${e.label}` : "(removed)";
}

function nearestEntity(span, preferType) {
  let best = null;
  for (const r of S.data.records) {
    if (!r.entity_id || r.end > span.start) continue;
    const e = S.data.entities.find((x) => x.id === r.entity_id);
    if (!e) continue;
    if (preferType && e.type !== preferType) continue;
    if (!best || r.end > best.end) best = { end: r.end, id: e.id };
  }
  return best && best.id;
}

function entityPicker(selected, opts = {}) {
  const box = h("div", {});
  const list = h("div", { class: "picker", role: "listbox" });
  let current = selected || null;
  const ents = S.data.entities;
  let filter = null;
  if (ents.length > 7) {
    filter = h("input", { type: "text", placeholder: "Type to filter", "aria-label": "Filter people and companies" });
    filter.addEventListener("input", () => draw());
    box.append(filter);
  }
  function draw() {
    list.replaceChildren();
    const term = filter ? filter.value.toLowerCase() : "";
    if (opts.allowNone) list.append(pick(null, opts.noneLabel || "No one", ""));
    for (const e of ents) {
      if (term && !(`e${e.number} ${e.label}`.toLowerCase().includes(term))) continue;
      list.append(pick(e.id, `E${e.number} · ${e.label}`, e.id === opts.suggested ? opts.suggestedWhy || "suggested" : TYPE_LABEL[e.type] || ""));
    }
  }
  function pick(id, label, why) {
    return h("button", {
      class: "pick", type: "button", "aria-pressed": String(id === current),
      onclick: (ev) => { current = id; $$(".pick", list).forEach((b) => b.setAttribute("aria-pressed", "false")); ev.currentTarget.setAttribute("aria-pressed", "true"); },
    }, h("span", { text: label }), h("span", { class: "why", text: why }));
  }
  draw();
  box.append(list);
  box.get = () => current;
  return box;
}

function guessForm(quote) {
  const q = quote.trim().toLowerCase();
  if (PRONOUNS.has(q)) return "pronoun";
  if (/^(the|this|that|these|those)\s/.test(q)) return "description";
  for (const e of S.data.entities) if (e.label.toLowerCase() === q) return "name";
  return null;
}
function guessField(quote) {
  const q = quote.trim();
  if (/^\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$/.test(q)) return "phone";
  if (/^\d{2}-?\d{7}$/.test(q) || /^\d{3}-?\d{2}-?\d{4}$/.test(q)) return "TIN";
  if (/^\d{5}(-\d{4})?$/.test(q)) return "zip_code";
  if (/^[A-Z]{2}$/.test(q)) return "state";
  if (/^\d+\s+\S+/.test(q)) return "address";
  return null;
}
function guessType(label) {
  if (/^(dr|mr|mrs|ms|miss|prof)\.?\s/i.test(label)) return "person";
  if (/\b(inc|llc|ltd|corp|co|company|clinic|hospital|orthopedics|group|insurance|associates|center|centre|services|bank|law|legal|medical|auto|body|repair|imaging|pharmacy)\b\.?/i.test(label)) return "organization";
  return null;
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
let modalOnClose = null;
function openModal(title, body, buttons, opts = {}) {
  $("#modal-title").textContent = title;
  $("#modal-body").replaceChildren(body);
  const foot = $("#modal-foot");
  foot.replaceChildren();
  if (opts.left) foot.append(h("div", { class: "left" }, opts.left));
  for (const b of buttons) foot.append(b);
  $(".modal").classList.toggle("wide", !!opts.wide);
  $("#modal").hidden = false;
  modalOnClose = opts.onClose || null;
  const first = $("#modal-body input[type=text], #modal-body textarea, #modal-body .choice, #modal-body .pick, #modal-foot .btn.primary");
  setTimeout(() => (opts.focus ? opts.focus.focus() : first && first.focus()), 20);
}
function closeModal() {
  $("#modal").hidden = true;
  if (S.pinSelection && S.view === "note" && S.data) { S.pinSelection = false; renderNote(); }
  S.pinSelection = false;
  if (modalOnClose) { const f = modalOnClose; modalOnClose = null; f(); }
}
function modalButton(label, onclick, cls = "") {
  return h("button", { class: "btn " + cls, type: "button", onclick }, label);
}

// ---------------------------------------------------------------------------
// Recording something by hand
// ---------------------------------------------------------------------------
function quoteBox(span, kind) {
  const box = h("div", { class: "selected-quote" }, `“${sliceCp(span.start, span.end)}”`, h("span", { class: "where", text: `Characters ${span.start}–${span.end} of this note` }));
  box.style.borderLeftColor = `var(--k-${KINDS[kind].cls})`;
  return box;
}

function buildControls(kind, span, init = {}) {
  const quote = sliceCp(span.start, span.end);
  const c = {};
  const parts = [];
  if (kind === "entity") {
    c.name = h("input", { type: "text", value: init.name ?? quote });
    c.type = choiceGroup(ENTITY_TYPES, init.type ?? guessType(init.name ?? quote));
    parts.push(field("Name", c.name, "How you'd like it listed. The highlighted words are saved exactly as the note has them."),
      field("What is it?", c.type));
  }
  if (["mention", "detail", "description", "action"].includes(kind) || (kind === "unclear")) {
    const form = kind === "mention" ? (init.form ?? guessForm(quote)) : null;
    const suggested = init.entity_id ?? nearestEntity(span, form === "pronoun" ? "person" : null) ?? nearestEntity(span);
    const label = kind === "unclear" ? "Might refer to (optional)" : kind === "action" ? "Who did it" : kind === "detail" ? "Whose detail is this?" : "Who is this about?";
    c.entity = entityPicker(kind === "unclear" ? (init.entity_id ?? null) : suggested, {
      allowNone: kind === "unclear", noneLabel: "Leave unlinked",
      suggested: init.entity_id ? null : suggested, suggestedWhy: "nearest before — check it",
    });
    parts.push(field(label, c.entity, kind === "detail" ? "A clinic's address belongs to the clinic, not a doctor who works there." : null));
    if (kind === "mention") {
      c.form = choiceGroup(FORMS, form);
      parts.push(field("How does the note refer to them?", c.form));
    }
  }
  if (kind === "detail") {
    c.field = choiceGroup(FIELDS, init.field ?? guessField(quote));
    c.value = h("input", { type: "text", value: init.value ?? quote });
    parts.push(field("Kind of detail", c.field), field("Value", c.value, "Exactly as the note states it. Keep leading zeros: 001234567 stays 001234567."));
  }
  if (kind === "action") {
    c.entity2 = entityPicker(init.entity2_id ?? null, { allowNone: true, noneLabel: "No second party" });
    parts.push(field("Second party (optional)", c.entity2, "Only when another person or company is part of it — e.g. “with Northstar Orthopedics”."));
  }
  if (kind === "description" || kind === "action") {
    c.label = h("input", { type: "text", value: init.label ?? "", placeholder: "Optional" });
    parts.push(field("Your label (optional)", c.label, kind === "action" ? "Make sure the highlighted words keep “not”, “reportedly”, dates and times." : "Only if you want to add your own interpretation."));
  }
  if (kind === "unclear") {
    c.reason = h("textarea", { placeholder: "Why can't this be linked confidently?" });
    c.reason.value = init.reason ?? "";
    const chips = h("div", { class: "choices" }, UNCLEAR_REASONS.map((r) => h("button", { class: "choice", type: "button", onclick: () => { c.reason.value = r; c.reason.focus(); } }, r)));
    parts.splice(0, 0, field("Why is it unclear?", h("div", {}, c.reason, chips), "Required. Pick a common reason or write your own."));
  }
  c.read = () => {
    const out = {};
    if (c.name) out.name = c.name.value.trim();
    if (c.type) out.type = c.type.get();
    if (c.entity) out.entity_id = c.entity.get();
    if (c.form) out.form = c.form.get();
    if (c.field) out.field = c.field.get();
    if (c.value) out.value = c.value.value.trim();
    if (c.entity2) out.entity2_id = c.entity2.get();
    if (c.label) out.label = c.label.value.trim();
    if (c.reason) out.reason = c.reason.value.trim();
    return out;
  };
  c.check = (v) => {
    if (kind === "entity" && !v.name) return "Give the person or company a name.";
    if (kind === "entity" && !v.type) return "Choose what it is: person, organization, place, other or not sure.";
    if (["mention", "detail", "description", "action"].includes(kind) && !v.entity_id) return "Choose who this belongs to.";
    if (kind === "mention" && !v.form) return "Choose how the note refers to them.";
    if (kind === "detail" && !v.field) return "Choose the kind of detail.";
    if (kind === "detail" && !v.value) return "Enter the value exactly as the note states it.";
    if (kind === "action" && v.entity2_id && v.entity2_id === v.entity_id) return "The second party must be someone different.";
    if (kind === "unclear" && !v.reason) return "Say why this is unclear.";
    return null;
  };
  c.parts = parts;
  return c;
}

function openRecordForm(kind, span, existing) {
  S.sel = span;
  S.pinSelection = true;
  renderNote();
  const init = existing ? { ...existing, name: existing.entityLabel, type: existing.entityType } : {};
  const c = buildControls(kind, span, init);
  const err = h("div", { class: "problem", role: "alert", hidden: true });
  const body = h("div", { class: "form" }, quoteBox(span, kind), h("div", { class: "help", text: KINDS[kind].help }), ...c.parts, err);
  const save = async () => {
    const v = c.read();
    const problem = c.check(v);
    if (problem) { err.textContent = problem; err.hidden = false; return; }
    try {
      if (existing && existing.uid) {
        await api("/api/record/update", withMe({ uid: existing.uid, fields: v }));
        toast("Saved.");
      } else if (kind === "entity") {
        await api("/api/entity/create", withMe({ ...S.cur, start: span.start, end: span.end, label: v.name, type: v.type }));
        toast(`Recorded ${v.name}.`);
      } else {
        await api("/api/record/create", withMe({ ...S.cur, kind, start: span.start, end: span.end, fields: v }));
        toast(`${KINDS[kind].label} saved.`);
      }
      closeModal();
      window.getSelection().removeAllRanges();
      S.sel = null;
      await refresh();
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  };
  body.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && ev.target.tagName !== "TEXTAREA" && !ev.target.classList.contains("choice") && !ev.target.classList.contains("pick")) { ev.preventDefault(); save(); } });
  const buttons = [];
  if (existing && existing.uid && !existing.is_first) buttons.push(modalButton("Delete", () => deleteRecord(existing.uid), "danger"));
  buttons.push(modalButton("Cancel", closeModal), modalButton(existing ? "Save changes" : "Save", save, "primary"));
  openModal(existing ? `Edit: ${KINDS[kind].label}` : KINDS[kind].label, body, buttons,
    { left: existing && existing.uid ? h("button", { class: "link", type: "button", onclick: () => showHistory(existing.uid), text: "History" }) : null });
}

async function deleteRecord(uid) {
  try {
    await api("/api/record/delete", withMe({ uid }));
    closeModal();
    toast("Deleted. It stays in the history.");
    await refresh();
  } catch (e) { fail(e); }
}

async function showHistory(uid) {
  try {
    const { history } = await api("/api/record/history" + qs({ uid }));
    const t = h("table", { class: "plain" }, h("tr", {}, ["Version", "When (UTC)", "State", "Words", "Details"].map((x) => h("th", { text: x }))),
      history.map((r) => h("tr", {}, h("td", { class: "num", text: r.revision }), h("td", { text: r.created_at.replace("T", " ").replace("+00:00", "") }),
        h("td", { text: r.state === "retired" ? "deleted" : "saved" }), h("td", { text: r.quote }),
        h("td", { text: [r.form, r.field && FIELD_LABEL[r.field], r.value, r.label, r.reason].filter(Boolean).join(" · ") }))));
    openModal("History of this record", t, [modalButton("Close", closeModal, "primary")], { wide: true });
  } catch (e) { fail(e); }
}

function editEntity(e) {
  const name = h("input", { type: "text", value: e.label });
  const type = choiceGroup(ENTITY_TYPES, e.type);
  const err = h("div", { class: "problem", hidden: true });
  const body = h("div", { class: "form" }, field("Name", name), field("What is it?", type), err);
  openModal(`Edit E${e.number}`, body, [
    modalButton("Delete", async () => {
      try { await api("/api/entity/delete", withMe({ id: e.id })); closeModal(); if (S.focus === e.id) S.focus = null; toast("Deleted."); await refresh(); }
      catch (x) { err.textContent = x.message; err.hidden = false; }
    }, "danger"),
    modalButton("Cancel", closeModal),
    modalButton("Save", async () => {
      try { await api("/api/entity/update", withMe({ id: e.id, label: name.value, type: type.get() })); closeModal(); toast("Saved."); await refresh(); }
      catch (x) { err.textContent = x.message; err.hidden = false; }
    }, "primary"),
  ]);
}

// ---------------------------------------------------------------------------
// Right panel
// ---------------------------------------------------------------------------
function setTab(tab) {
  S.tab = tab;
  $$("#panel-tabs .tab").forEach((b) => { const on = b.dataset.tab === tab; b.classList.toggle("active", on); b.setAttribute("aria-selected", String(on)); });
  for (const t of ["people", "records", "drafts"]) $("#tab-" + t).hidden = t !== tab;
}

function renderPanel() {
  const d = S.data;
  $("#count-people").textContent = d.entities.length;
  $("#count-records").textContent = d.records.length;
  $("#count-drafts").textContent = pendingDrafts().length;
  renderPeople();
  renderRecords();
  renderDrafts();
}

function renderPeople() {
  const box = $("#tab-people");
  box.replaceChildren();
  if (!S.data.entities.length) {
    box.append(h("div", { class: "empty" }, "No one recorded in this claim yet.", h("br"), "Select a name in the note and choose ", h("b", { text: "Person or company" }), "."));
    return;
  }
  const list = h("div", { class: "list" });
  for (const e of S.data.entities) {
    const facts = h("ul", { class: "facts" });
    for (const desc of e.descriptions.slice(0, 3)) facts.append(h("li", { text: `“${desc}”` }));
    for (const det of e.details.slice(0, 6)) facts.append(h("li", { text: `${FIELD_LABEL[det.field] || det.field}: ${det.value}` }));
    list.append(h("div", {
      class: "card clickable" + (S.focus === e.id ? " focused" : ""),
      onclick: () => {
        S.focus = S.focus === e.id ? null : e.id;
        renderNote(); renderPeople();
        const first = S.data.records.find((r) => r.entity_id === e.id || r.entity2_id === e.id);
        if (S.focus && first) scrollToCp(first.start, false);
      },
    }, h("div", { class: "card-top" }, h("span", { class: "handle", text: `E${e.number}` }), h("span", { class: "card-title", text: e.label }),
        h("span", { class: "card-actions" }, h("button", { class: "btn ghost small", type: "button", onclick: (ev) => { ev.stopPropagation(); editEntity(e); } }, "Edit"))),
      h("div", { class: "card-sub", text: `${TYPE_LABEL[e.type]} · ${e.in_note ?? 0} in this note · ${e.count} in claim` }), facts.children.length ? facts : null));
  }
  box.append(h("div", { class: "help muted small", text: "Click someone to light up every place they appear in this note." }), list);
}

function recordCard(r, opts = {}) {
  const k = r.kind === "mention" && r.is_first ? KINDS.entity : KINDS[r.kind];
  const who = r.entity_id ? entityName(r.entity_id) : null;
  const sub = [];
  if (r.kind === "mention") sub.push(r.is_first ? "first named here" : FORM_LABEL[r.form] || r.form);
  if (r.kind === "detail") sub.push(`${FIELD_LABEL[r.field] || r.field}: ${r.value}`);
  if (r.kind === "action" && r.entity2_id) sub.push(`with ${entityName(r.entity2_id)}`);
  if (r.label) sub.push(`label: ${r.label}`);
  if (r.reason) sub.push(r.reason);
  const ent = S.data.entities.find((e) => e.id === r.entity_id);
  return h("div", { class: "card clickable", onclick: () => { hidePopover(); scrollToCp(r.start); } },
    h("div", { class: "card-top" }, h("span", { class: "kind " + k.cls, text: k.label }), r.source === "ai" ? h("span", { class: "ai-mark", title: "Accepted from an AI draft", text: "AI" }) : null,
      h("span", { class: "card-actions" }, h("button", {
        class: "btn ghost small", type: "button",
        onclick: (ev) => {
          ev.stopPropagation(); hidePopover();
          if (r.is_first && ent) return editEntity(ent);
          openRecordForm(r.kind, { start: r.start, end: r.end }, { ...r });
        },
      }, "Edit"))),
    h("div", { class: "quote", text: `“${r.quote}”` }),
    h("div", { class: "card-sub", text: [who, ...sub].filter(Boolean).join(" · ") }));
}

function renderRecords() {
  const box = $("#tab-records");
  box.replaceChildren();
  if (!S.data.records.length) { box.append(h("div", { class: "empty", text: "Nothing recorded in this note yet. Select words in the note to start." })); return; }
  box.append(h("div", { class: "list" }, S.data.records.map((r) => recordCard(r))));
}

// ---------------------------------------------------------------------------
// AI drafts: reviewing one at a time
// ---------------------------------------------------------------------------
function reviewQueue() {
  return pendingDrafts().slice().sort((a, b) => (a.start ?? 1e15) - (b.start ?? 1e15) || (a.type === "entity" ? -1 : 0) - (b.type === "entity" ? -1 : 0) || a.seq - b.seq);
}

function startReview(id) {
  const q = reviewQueue();
  S.reviewId = id || (q[0] && q[0].id) || null;
  setTab("drafts");
  renderNote();
  renderDrafts();
  const d = S.data.drafts.find((x) => x.id === S.reviewId);
  if (d && d.start !== null) scrollToCp(d.start, false);
  else if (d && d.candidates && d.candidates.length) scrollToCp(d.candidates[0][0], false);
}

function nextDraft(step = 1) {
  const q = reviewQueue();
  if (!q.length) { S.reviewId = null; renderNote(); renderDrafts(); toast("All AI drafts for this note are decided."); return; }
  const i = q.findIndex((d) => d.id === S.reviewId);
  const next = q[(i + step + q.length) % q.length] || q[0];
  startReview(next.id);
}

function renderDrafts() {
  const box = $("#tab-drafts");
  box.replaceChildren();
  const all = S.data.drafts;
  if (S.data.blind) { box.append(h("div", { class: "empty", text: "This note is set to be annotated without AI drafts, so your work can be compared with AI-assisted notes." })); return; }
  if (!all.length) {
    box.append(h("div", { class: "empty" }, "No AI drafts for this note.", h("br"), "Drafts are optional. Use ", h("b", { text: "Get AI drafts" }), " to have Copilot suggest records — you check every one."));
    return;
  }
  const count = (st) => all.filter((d) => d.status === st).length;
  box.append(h("div", { class: "run-summary" }, h("b", { text: "AI drafts for this note" }),
    h("div", { class: "nums" }, h("span", { text: `${count("ready") + count("needs_attention")} to review` }), h("span", { text: `${count("accepted")} accepted` }),
      h("span", { text: `${count("dismissed")} dismissed` }), count("duplicate") ? h("span", { text: `${count("duplicate")} already recorded` }) : null)));
  const current = all.find((d) => d.id === S.reviewId && (d.status === "ready" || d.status === "needs_attention"));
  if (current) box.append(draftCard(current));
  else if (pendingDrafts().length) box.append(h("button", { class: "btn primary", type: "button", onclick: () => startReview() }, `Review ${pendingDrafts().length} draft(s) in reading order`));
  const list = h("div", { class: "list" });
  list.style.gap = "0";
  for (const d of all.slice().sort((a, b) => (a.start ?? 1e15) - (b.start ?? 1e15))) {
    const label = { ready: "to review", needs_attention: "needs you", accepted: d.edited ? "accepted, edited" : "accepted", dismissed: "dismissed", duplicate: "already recorded" }[d.status];
    list.append(h("div", { class: "draft-row", onclick: () => { if (d.status === "ready" || d.status === "needs_attention") startReview(d.id); else if (d.start !== null) scrollToCp(d.start); } },
      h("span", { class: "kind " + (KINDS[d.type]?.cls || "draft"), text: KINDS[d.type]?.label || d.type }),
      h("span", { class: "quote", text: d.quote ? `“${d.quote.slice(0, 60)}”` : "(no words)" }), h("span", { class: "st " + d.status, text: label })));
  }
  box.append(h("h2", { class: "section", text: "All drafts" }), list);
}

function contextSnippet(a, b) {
  const pre = sliceCp(Math.max(0, a - 36), a).replace(/\s+/g, " ");
  const post = sliceCp(b, Math.min(CPLEN, b + 36)).replace(/\s+/g, " ");
  return h("span", {}, "…" + pre, h("b", { text: sliceCp(a, b) }), post + "…");
}

function draftCard(d) {
  const q = reviewQueue();
  const pos = q.findIndex((x) => x.id === d.id) + 1;
  const card = h("div", { class: "draft-card" });
  card.append(h("div", { class: "head" }, h("span", { class: "kind " + KINDS[d.type].cls, text: KINDS[d.type].label }), h("span", { class: "ai-mark", text: "AI draft" }),
    h("span", { class: "progress", text: `${pos} of ${q.length} left` })));
  const hasSpan = d.start !== null && d.start !== undefined;
  if (hasSpan) card.append(h("div", { class: "quote", text: `“${sliceCp(d.start, d.end)}”` }));
  else card.append(h("div", { class: "quote muted", text: d.quote ? `Copilot quoted: “${d.quote}”` : "Copilot gave no words from the note." }));
  for (const p of d.problems.filter((p) => !(hasSpan && ["not_found", "ambiguous", "no_quote"].includes(p.code)))) card.append(h("div", { class: "problem", text: p.text }));
  for (const n of d.notes) card.append(h("div", { class: "notice", text: n }));

  if (!hasSpan) {
    const useSel = h("button", { class: "btn small", type: "button", disabled: !S.sel, onclick: () => setDraftSpan(d, S.sel) }, "Use the words I selected");
    card.append(h("div", { class: "help", text: "Select the right words in the note, then press the button. Or dismiss this draft." }), useSel);
    if (d.candidates && d.candidates.length) {
      card.append(h("div", { class: "help", text: "Or pick where it is:" }),
        h("div", { class: "candidates" }, d.candidates.slice(0, 8).map(([a, b], i) => h("button", { class: "candidate", type: "button", onclick: () => setDraftSpan(d, { start: a, end: b }) }, `${i + 1}. `, contextSnippet(a, b)))));
    }
  }

  const span = hasSpan ? { start: d.start, end: d.end } : S.sel || { start: 0, end: 0 };
  const f = d.fields || {};
  const resolved = d.resolved || {};
  let controls = null;
  let linkChoice = null;
  if (d.type === "entity") {
    if (d.suggest_link) {
      linkChoice = choiceGroup([["link", `Same as ${entityName(d.suggest_link)}`], ["new", "A new person or company"]], "link");
      card.append(field("Already recorded?", linkChoice, "Someone with this name is already in the claim. Link it as another mention unless it's genuinely someone else."));
    }
    controls = buildControls("entity", span, { name: f.name, type: f.kind });
  } else if (d.type === "unclear") {
    controls = buildControls("unclear", span, { reason: f.reason, entity_id: null });
  } else {
    controls = buildControls(d.type, span, { entity_id: resolved.key || null, entity2_id: resolved.key2 || null, form: f.form, field: f.field, value: f.value, label: f.label });
    if (d.key && !resolved.key) {
      const blocker = S.data.drafts.find((x) => x.type === "entity" && (x.key || "").toUpperCase() === d.key.toUpperCase() && (x.status === "ready" || x.status === "needs_attention"));
      if (blocker) card.append(h("div", { class: "notice" }, `Copilot linked this to ${d.key} (“${blocker.fields.name || blocker.quote}”), which isn't accepted yet. `,
        h("button", { class: "link", type: "button", onclick: () => startReview(blocker.id), text: "Review that first" }), ", or choose someone below."));
    } else if (d.key && resolved.key) {
      card.append(h("div", { class: "help", text: `Copilot linked this to ${d.key}, which is ${entityName(resolved.key)}.` }));
    }
  }
  card.append(h("div", { class: "form" }, ...controls.parts));
  const err = h("div", { class: "problem", role: "alert", hidden: true });
  card.append(err);

  const accept = async () => {
    const v = controls.read();
    const linking = linkChoice && linkChoice.get() === "link";
    const problem = linking ? null : controls.check(v);
    if (!hasSpan) { err.textContent = "Pick the words in the note first."; err.hidden = false; return; }
    if (problem) { err.textContent = problem; err.hidden = false; return; }
    const body = { id: d.id, fields: {} };
    if (d.type === "entity") {
      if (linking) body.link_entity_id = d.suggest_link;
      else body.fields = { name: v.name, kind: v.type };
    } else {
      body.fields = { form: v.form, field: v.field, value: v.value, label: v.label, reason: v.reason };
      if (d.type !== "unclear") body.entity_id = v.entity_id;
      else body.entity_id = v.entity_id || null;
      if (d.type === "action") body.entity2_id = v.entity2_id || null;
    }
    try {
      const res = await api("/api/draft/accept", withMe(body));
      toast(res.edited ? "Accepted with your changes." : "Accepted.");
      const q2 = reviewQueue();
      const i = q2.findIndex((x) => x.id === d.id);
      const following = q2[i + 1] || q2[0];
      await refresh();
      if (following && following.id !== d.id && pendingDrafts().some((x) => x.id === following.id)) startReview(following.id); else nextDraft(0);
    } catch (e) {
      const m = /^NEEDS_ENTITY:([^:]+):(.*)$/.exec(e.message);
      if (m) { toast(m[2], { action: { label: "Review it", run: () => startReview(m[1]) } }); return; }
      err.textContent = e.message; err.hidden = false;
    }
  };
  const dismiss = async () => {
    try {
      const q2 = reviewQueue();
      const i = q2.findIndex((x) => x.id === d.id);
      const following = q2[i + 1];
      await api("/api/draft/dismiss", withMe({ id: d.id }));
      toast("Dismissed.");
      await refresh();
      if (following) startReview(following.id); else nextDraft(0);
    } catch (e) { fail(e); }
  };
  card.append(h("div", { class: "draft-actions" },
    h("button", { class: "btn primary", type: "button", onclick: accept, title: "Accept (A)" }, "Accept ", h("kbd", { text: "A" })),
    h("button", { class: "btn", type: "button", onclick: dismiss, title: "Dismiss (X)" }, "Dismiss ", h("kbd", { text: "X" })),
  ), h("div", { class: "draft-nav" },
    h("button", { class: "btn ghost small", type: "button", onclick: () => nextDraft(-1), title: "Previous draft (←)" }, "← Previous"),
    h("button", { class: "btn ghost small", type: "button", onclick: () => nextDraft(1), title: "Skip for now (→)" }, "Skip for now →")));
  card.accept = accept;
  card.dismiss = dismiss;
  S.activeCard = card;
  return card;
}

async function setDraftSpan(d, span) {
  if (!span) return;
  try {
    await api("/api/draft/span", withMe({ id: d.id, start: span.start, end: span.end }));
    window.getSelection().removeAllRanges();
    S.sel = null;
    await refresh();
    startReview(d.id);
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------------------
// Getting AI drafts from Copilot
// ---------------------------------------------------------------------------
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall back */ }
  const ta = h("textarea", {});
  ta.value = text;
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

function openAiModal() {
  if (S.data.blind) return toast("This note is annotated without AI drafts.");
  const parts = S.data.parts;
  const partSel = parts.length > 1 ? h("select", { "aria-label": "Which part" }, parts.map(([a, b], i) => h("option", { value: i + 1, text: `Part ${i + 1} of ${parts.length} (characters ${a.toLocaleString()}–${b.toLocaleString()})` }))) : null;
  const full = h("input", { type: "checkbox", id: "ai-full" });
  const copyBtn = h("button", { class: "btn primary", type: "button" }, "Copy for Copilot");
  const copyInfo = h("div", { class: "help" });
  copyBtn.addEventListener("click", async () => {
    try {
      const m = await api("/api/ai/message" + qs(withMe({ ...S.cur, part: partSel ? partSel.value : 1, full: full.checked ? "1" : "0" })));
      const ok = await copyText(m.message);
      copyInfo.textContent = ok ? `Copied ${m.chars.toLocaleString()} characters. Paste it into Copilot and send it.` : "Couldn't copy automatically. Select the note in the box below and copy it yourself.";
      if (!ok) { ta.value = m.message; ta.select(); }
      else toast("Copied. Paste it into Copilot.");
    } catch (e) { fail(e); }
  });
  const ta = h("textarea", { class: "paste", placeholder: "Paste Copilot's whole reply here — the code block, and any text around it is fine.", "aria-label": "Copilot's reply" });
  const report = h("div", { class: "report", "aria-live": "polite" });
  const importBtn = h("button", { class: "btn primary", type: "button", disabled: true }, "Add drafts to review");
  let lastGood = null;

  const preview = debounce(async () => {
    const answer = ta.value;
    report.replaceChildren();
    importBtn.disabled = true;
    lastGood = null;
    if (!answer.trim()) return;
    try {
      const r = await api("/api/ai/preview", withMe({ ...S.cur, answer }));
      renderReport(report, r);
      if (!r.errors.length && r.drafts.length) { lastGood = answer; importBtn.disabled = false; importBtn.textContent = `Add ${r.counts.ready + r.counts.needs_attention} draft(s) to review`; }
    } catch (e) { report.replaceChildren(h("div", { class: "problem", text: e.message })); }
  }, 350);
  ta.addEventListener("input", preview);
  importBtn.addEventListener("click", async () => {
    if (!lastGood) return;
    try {
      const res = await api("/api/ai/import", withMe({ ...S.cur, answer: lastGood }));
      closeModal();
      toast(`Added ${res.counts.ready + res.counts.needs_attention} draft(s). Review each one.`);
      await refresh();
      startReview();
    } catch (e) { fail(e); }
  });

  const body = h("div", { class: "steps" },
    h("div", { class: "step" }, h("h3", {}, h("span", { class: "step-num", text: "1" }), "Copy the note for Copilot"),
      h("p", { class: "small muted", text: "This copies the note, plus the people and companies you've already recorded so Copilot doesn't draft them again." }),
      partSel ? field("This note is long, so it goes in parts", partSel, "Do one part at a time: paste the reply below before copying the next part.") : null,
      h("label", { class: "check-row", for: "ai-full" }, full, h("span", {}, h("b", { text: "Include the full instructions. " }), "Tick this if you're using plain Copilot chat rather than the firm's Copilot agent.")),
      h("div", { class: "draft-actions" }, copyBtn), copyInfo),
    h("div", { class: "step" }, h("h3", {}, h("span", { class: "step-num", text: "2" }), "Paste Copilot's reply"),
      h("p", { class: "small muted", text: "Use the copy button on Copilot's code block. If the reply was cut off, ask Copilot to “continue” and paste that too, as a second batch." }),
      ta, report));
  openModal("Get AI drafts", body, [modalButton("Cancel", closeModal), importBtn], { wide: true, focus: copyBtn });
}

function renderReport(box, r) {
  box.replaceChildren();
  for (const e of r.errors) box.append(h("div", { class: "problem", text: e }));
  for (const w of r.warnings) box.append(h("div", { class: "notice", text: w }));
  if (r.errors.length) return;
  const c = r.counts;
  box.append(h("div", { class: "nums" },
    h("span", { class: "num-chip ok", text: `${c.ready} ready` }),
    c.needs_attention ? h("span", { class: "num-chip att", text: `${c.needs_attention} need you` }) : null,
    c.duplicate ? h("span", { class: "num-chip", text: `${c.duplicate} already recorded` }) : null,
    c.rejected ? h("span", { class: "num-chip att", text: `${c.rejected} line(s) couldn't be read` }) : null));
  if (r.repairs.length) box.append(h("div", { class: "help", text: `Fixed small formatting slips: ${r.repairs.join("; ")}.` }));
  for (const x of r.rejected.slice(0, 5)) box.append(h("div", { class: "problem", text: `Line ${x.line}: ${x.why}` }));
  const att = r.drafts.filter((d) => d.status === "needs_attention").slice(0, 6);
  for (const d of att) box.append(h("div", { class: "help", text: `• ${KINDS[d.type]?.label || d.type} “${(d.quote || "").slice(0, 50)}”: ${d.problems.map((p) => p.text).join(" ")}` }));
  if (r.meta && r.meta.summary) box.append(h("div", { class: "help", text: `Copilot's summary: ${r.meta.summary}` }));
}

// ---------------------------------------------------------------------------
// Completing a note, and the "More" menu
// ---------------------------------------------------------------------------
function openComplete() {
  if (S.data.status === "complete") {
    return api("/api/note/reopen", withMe({ ...S.cur })).then(() => { toast("Reopened."); return refresh(); }).catch(fail);
  }
  const pending = pendingDrafts().length;
  if (pending) {
    return openModal("A few AI drafts still need you", h("p", { text: `${pending} AI draft(s) haven't been accepted or dismissed. Decide each one, then mark the note complete.` }),
      [modalButton("Not now", closeModal), modalButton("Review drafts", () => { closeModal(); startReview(); }, "primary")]);
  }
  const box = h("input", { type: "checkbox", id: "attest" });
  const done = modalButton("Mark complete", async () => {
    if (!box.checked) return;
    try { await api("/api/note/complete", withMe({ ...S.cur, attest: true })); closeModal(); toast("Note complete."); await refresh(); } catch (e) { fail(e); }
  }, "primary");
  done.disabled = true;
  box.addEventListener("change", () => { done.disabled = !box.checked; });
  const body = h("div", { class: "form" },
    h("p", { text: "Before you mark it complete, check you've:" }),
    h("ul", {}, h("li", { text: "read the whole note, from the first word to the last;" }), h("li", { text: "recorded every person or company, and every later mention of them;" }),
      h("li", { text: "recorded every stated detail on the right owner;" }), h("li", { text: "marked anything you couldn't link as Unclear, with a reason." })),
    h("label", { class: "check-row", for: "attest" }, box, h("span", { text: "I've read this whole note and recorded everything the guide asks for." })));
  openModal("Mark note complete", body, [modalButton("Cancel", closeModal), done]);
}

function openMore(ev) {
  const pop = $("#popover");
  const hasDrafts = S.data.drafts.length > 0;
  pop.replaceChildren(
    h("button", { class: "menu-item", type: "button", disabled: hasDrafts && !S.data.blind, onclick: async () => {
      hidePopover();
      try { await api("/api/note/blind", withMe({ ...S.cur, blind: !S.data.blind })); toast(S.data.blind ? "AI drafts allowed again." : "This note will be done without AI drafts."); await refresh(); } catch (e) { fail(e); }
    } }, h("span", { class: "swatch sw-draft" }), h("b", { text: S.data.blind ? "Allow AI drafts for this note" : "Do this note without AI drafts" }), null,
      h("small", { text: hasDrafts && !S.data.blind ? "Not available: this note already has AI drafts." : "Lets the firm measure whether AI drafts change what gets recorded." })),
    h("button", { class: "menu-item", type: "button", onclick: () => { hidePopover(); openHelp(); } }, h("span", { class: "swatch sw-party" }), h("b", { text: "Quick guide" }), null, h("small", { text: "What each kind of record means, with examples." })));
  pop.hidden = false;
  const r = ev.currentTarget.getBoundingClientRect();
  pop.style.top = `${r.bottom + 6}px`;
  pop.style.left = `${Math.max(10, r.right - 340)}px`;
}

// ---------------------------------------------------------------------------
// Finishing a claim and comparing with the firm's output
// ---------------------------------------------------------------------------
function confirmSeal(claim) {
  if ([...categoryDrafts.entries()].some(([k,d]) => k.startsWith(`${S.reviewer}|${claim}|`) && d.dirty)) return fail(new Error("Save or discard the unsaved entity reviews first."));
  const body = h("div", { class: "form" },
    h("p", { text: "Freeze the reviewed entities, category decisions and exact evidence versions. Later annotation edits will not change this evaluated answer key." }));
  const attest = h("input", {type: "checkbox", id: "freeze-attest"});
  body.append(h("label", {}, attest, " I reviewed the claim entities, evidence ownership and unresolved references before seeing the firm's output."));
  const save = modalButton("Freeze and compare", async () => {
    try { await api("/api/claim/seal", withMe({ claim, attest: attest.checked })); closeModal(); await loadClaims(); openCompare(claim); } catch (e) { fail(e); }
  }, "primary");
  save.disabled = true;
  attest.addEventListener("change", () => { save.disabled = !attest.checked; });
  openModal(`Freeze claim ${claim}`, body, [modalButton("Not yet", closeModal), save]);
}

// A dossier retains each note's source record; categories never come from firm rows.
const categoryDrafts = new Map();
async function openClaimReview(claim, entityId) {
  try {
    S.claimReview = await api("/api/claim/review" + qs(withMe({claim})));
    for (const [key] of categoryDrafts) {
      if (key.startsWith(`${S.reviewer}|${claim}|`) && !S.claimReview.entities.some(e => key === `${S.reviewer}|${claim}|${e.id}`)) categoryDrafts.delete(key);
    }
    S.dossierEntity = entityId || S.claimReview.entities.find(e => !e.reviewed)?.id || S.claimReview.entities[0]?.id;
    showView("review"); renderClaimReview();
  } catch (e) { fail(e); }
}

async function showEvidence(record) {
  try {
    const data = await api("/api/note" + qs(withMe({claim: record.claim, note: record.note})));
    const chars = Array.from(data.text);
    const source = S.claimReview.sources.find(s => s.note === record.note);
    const exact = data.fingerprint_ok && source && source.fingerprint === data.source_fingerprint && chars.slice(record.start, record.end).join("") === record.quote;
    if (!exact) throw new Error("The source file differs from the reviewed evidence. Restore the original file to inspect this position.");
    const mark = h("mark", {text: record.quote});
    const body = h("div", {}, h("p", {text: `Note ${record.note} · characters ${record.start}–${record.end} · revision ${record.revision}`}),
      h("div", {class: "source-passage"}, chars.slice(0, record.start).join(""), mark, chars.slice(record.end).join("")));
    openModal("Original note evidence", body, [modalButton("Open note to correct annotation", async () => {
      closeModal(); await openNote(record.claim, record.note); scrollToCp(record.start);
      if (!record.is_first) openRecordForm(record.kind, {start: record.start, end: record.end}, {...record});
    }), modalButton("Back to dossier", closeModal, "primary")], {wide: true});
    mark.scrollIntoView({block: "center"});
  } catch (e) { fail(e); }
}

function renderClaimReview() {
  const data = S.claimReview, view = $("#view-review");
  view.replaceChildren();
  const readOnly = data.frozen || data.legacy;
  const count = data.entities.filter(e => e.reviewed).length;
  const unsaved = [...categoryDrafts.entries()].some(([k,d]) => k.startsWith(`${S.reviewer}|${data.claim}|`) && d.dirty);
  const freeze = h("button", {id: "freeze-review", class: "btn primary", type: "button", disabled: count !== data.entities.length || readOnly || unsaved,
    onclick: () => confirmSeal(data.claim)}, "Freeze and compare");
  view.append(h("div", {class: "note-head"}, h("div", {}, h("h1", {text: "Review the claim evidence"}),
    h("p", {id: "category-progress", text: `${count} of ${data.entities.length} entities reviewed`})), freeze),
    h("p", {text: data.frozen ? "This is the frozen answer key. Later annotation edits do not change it." : data.legacy ? "This claim was already exposed to firm output. Its categories cannot be backfilled as independent labels." : "Review each entity across all notes, then choose its broad role or an unresolved outcome. The firm's output stays hidden."}),
    h("details", {}, h("summary", {text: `Category guide · ${data.taxonomy.version}`}), h("p", {text: data.taxonomy.scope}),
      data.taxonomy.categories.map(c => h("p", {}, h("b", {text: c.name + ": "}), c.definition))));
  if (data.unresolved.length) view.append(h("details", {class: "unresolved-review"}, h("summary", {text: `${data.unresolved.length} unresolved references — inspect before freezing`}),
    data.unresolved.map(r => h("p", {}, h("button", {type: "button", class: "link", onclick: () => showEvidence(r), text: `${r.note}: “${r.quote}”`}), " — ", r.reason))));
  if (!data.entities.length) { view.append(h("p", {text: "No entities were recorded. Check the unresolved references and confirm the supplied packet before freezing."})); return; }
  const grid = h("div", {class: "dossier-grid"});
  const nav = h("nav", {class: "dossier-nav", "aria-label": "Claim entities"}, data.entities.map(e => h("button", {
    type: "button", class: "btn" + (e.id === S.dossierEntity ? " primary" : ""), onclick: () => { S.dossierEntity = e.id; renderClaimReview(); }
  }, `E${e.number} · ${e.label} · ${e.reviewed ? "Reviewed" : "Needs review"}`)));
  const e = data.entities.find(e => e.id === S.dossierEntity) || data.entities[0];
  const key = `${S.reviewer}|${data.claim}|${e.id}`;
  let draft = categoryDrafts.get(key);
  if (!draft || draft.basis !== e.basis || readOnly) {
    const retained = !readOnly && draft?.dirty ? draft : e.decision;
    draft = {...(retained || {}), basis: e.basis, evidence: structuredClone(retained?.evidence || []).filter(x => e.records.some(r => r.uid === x.uid && r.revision === x.revision)), dirty: !readOnly && !!retained?.dirty};
    categoryDrafts.set(key, draft);
  }
  const content = h("article", {class: "dossier-content"}, h("h2", {text: `E${e.number} · ${e.label}`}),
    h("p", {class: "muted", text: "Evidence belongs to its original note. Supporting records are not automatically independent; mark copied or repeated evidence explicitly."}));
  content.append(h("button", {class:"btn small",type:"button",onclick:()=>$(".category-form").scrollIntoView({block:"start"})}, "Jump to category decision"));
  if (e.decision && !e.reviewed) content.append(h("p", {class: "banner", text: "Evidence or entity details changed since the saved decision. Review and save again."}));
  let lastNote = null;
  for (const r of e.records) {
    if (lastNote !== r.note) { content.append(h("h3", {text: `Note ${r.note}`})); lastNote = r.note; }
    const role = h("select", {class: "evidence-role", "aria-label": `Evidence role: ${r.note} ${r.quote}`, disabled: readOnly},
      [["", "Not used for this category"], ["supports", "Supports"], ["conflicts", "Conflicts"], ["repeated", "Repeated / copied"]].map(([v,t]) => h("option", {value:v,text:t})));
    role.value = draft.evidence.find(x => x.uid === r.uid && x.revision === r.revision)?.role || "";
    role.addEventListener("change", () => {
      draft.evidence = draft.evidence.filter(x => x.uid !== r.uid);
      if (role.value) draft.evidence.push({uid:r.uid, revision:r.revision, role:role.value});
      changed();
    });
    const other = r.entity_id === e.id ? r.entity2_id : r.entity_id;
    const partner = data.entities.find(x => x.id === other);
    content.append(h("div", {class: "evidence-card"}, h("div", {class: "muted small", text: `${r.is_first ? "First named" : KINDS[r.kind]?.label || r.kind} · revision ${r.revision}${partner ? ` · linked with ${partner.label}` : ""}`}),
      h("button", {class: "link evidence-quote", type:"button", onclick: () => showEvidence(r), text: `“${r.quote}”`}),
      r.field ? h("p", {text: `${FIELD_LABEL[r.field] || r.field}: ${r.value}`}) : null,
      r.reason || r.label ? h("p", {text:r.reason || r.label}) : null, role));
  }
  const form = h("div", {class:"category-form form"});
  const status = h("select", {id:"category-status", disabled:readOnly}, [["", "Choose outcome…"], ["assigned", "Assign a broad category"], ["insufficient", "Insufficient evidence"], ["conflicting", "Conflicting evidence"]].map(([v,t])=>h("option",{value:v,text:t})));
  const category = h("select", {id:"category-value", disabled:readOnly}, h("option",{value:"",text:"Choose category…"}), data.taxonomy.categories.map(c=>h("option",{value:c.name,text:c.name})));
  const subcategory = h("input", {id:"category-sub", type:"text", disabled:readOnly, value:draft.subcategory || ""});
  const rationale = h("textarea", {id:"category-rationale", disabled:readOnly}); rationale.value = draft.rationale || "";
  status.value = draft.status || ""; category.value = draft.category || "";
  const catField = field("Broad claim role", category);
  catField.hidden = status.value !== "assigned";
  const message = h("p", {id:"category-save-status", role:"status", text:draft.dirty ? "Unsaved changes" : e.reviewed ? "Saved" : "Not yet reviewed"});
  function changed() { draft.dirty = true; freeze.disabled = true; message.textContent = "Unsaved changes — retained while navigating this page; save before closing."; }
  status.addEventListener("change", () => {draft.status = status.value; catField.hidden = status.value !== "assigned"; changed();});
  category.addEventListener("change", () => {draft.category = category.value; changed();});
  subcategory.addEventListener("input", () => {draft.subcategory = subcategory.value; changed();});
  rationale.addEventListener("input", () => {draft.rationale = rationale.value; changed();});
  const save = h("button", {id:"category-save", type:"button", class:"btn primary", disabled:readOnly, onclick:async () => {
    save.disabled = true;
    try {
      await api("/api/category/save", withMe({claim:data.claim, entity_id:e.id, ...draft}));
      categoryDrafts.delete(key);
      await openClaimReview(data.claim, e.id);
      toast("Category review saved.");
    } catch(err) { message.textContent = err.message; save.disabled = false; }
  }}, "Save entity review");
  form.append(h("h3", {text:"Category decision"}), field("Review outcome", status), catField,
    field("Subcategory (optional, only when stated)", subcategory), field("Why? Cite the evidence or explain what is missing", rationale), message, save,
    h("button", {type:"button",class:"btn",disabled:readOnly,onclick:()=>{categoryDrafts.delete(key);renderClaimReview();}}, "Discard unsaved edits"));
  content.append(form); grid.append(nav, content); view.append(grid);
  const index = data.entities.findIndex(x=>x.id===e.id);
  form.append(h("div", {class:"draft-nav"},
    h("button", {type:"button",class:"btn small",disabled:index===0,onclick:()=>{S.dossierEntity=data.entities[index-1].id;renderClaimReview();$("#view-review").scrollIntoView();}}, "Previous entity"),
    h("button", {type:"button",class:"btn small",disabled:index===data.entities.length-1,onclick:()=>{S.dossierEntity=data.entities[index+1].id;renderClaimReview();$("#view-review").scrollIntoView();}}, "Next entity")));
}

window.addEventListener("beforeunload", ev => {
  if ([...categoryDrafts.values()].some(d => d.dirty)) { ev.preventDefault(); ev.returnValue = ""; }
});

async function openCompare(claim) {
  try {
    const data = await api("/api/compare" + qs(withMe({ claim })));
    S.compareClaim = claim;
    S.compare = data;
    showView("compare");
    renderCompare();
  } catch (e) { fail(e); }
}

const FIRM_FIELDS = [["entity_category_name", "Category"], ["entity_subcategory_name", "Subcategory"], ["entity_NER_tag", "Person/org tag"], ["entity_address", "Address"],
  ["entity_city", "City"], ["entity_state", "State"], ["entity_zip_code", "ZIP"], ["entity_phone", "Phone"], ["entity_TIN", "TIN"], ["recordType", "Record type"]];

function rowDone(r) {
  const p = r.pairing, w = r.watchlist;
  const paired = p.entity_id || p.not_in_notes;
  const cat = S.compare.independent || p.not_in_notes || p.category_verdict;
  const watch = !r.flagged || (w.decision && w.note_supports && w.reason);
  return !!(paired && cat && watch);
}

function renderCompare() {
  const v = $("#view-compare");
  const data = S.compare;
  for (const r of data.rows) {
    r.pairing = { entity_id: null, not_in_notes: 0, category_verdict: null, correct_category: null, ...(r.pairing || {}) };
    r.watchlist = { decision: null, note_supports: null, reason: null, ...(r.watchlist || {}) };
    r.chain = Promise.resolve();
  }
  v.replaceChildren(
    h("div", { class: "note-head" }, h("div", { class: "note-title" }, h("h1", { text: `Compare ${claimLabel(data.claim).replace("Claim", "claim")} with the firm's output` }),
      h("span", { class: "pill", id: "compare-progress" }))),
    h("div", { class: "compare-intro" },
      h("p", {}, h("b", { text: "For each row the firm's tool reported, answer: " }), "which of your people or companies is it; and, if it was flagged against the watchlist, is it really the same person or company. Category agreement uses your frozen review."),
      h("p", { class: "muted small", text: "Answers save as you go. The firm's category matters beyond the label: GenAI only compares a name with watchlist entries of the same category, so a wrong category can switch that check off." })));
  const grid = h("div", { class: "compare-grid" });
  v.append(h("div", {class:"comparison-finish"}, h("p", {id:"comparison-status",role:"status"}),
    h("button", {id:"finish-comparison",class:"btn primary",type:"button",onclick:async ev=>{
      ev.currentTarget.disabled = true;
      try {
        await Promise.all(S.compare.rows.map(r=>r.chain));
        const result = await api("/api/comparison/finish", withMe({claim:data.claim}));
        S.compare.comparison = result.comparison; updateCompareProgress();
        toast("Comparison complete. Your saved results are ready to export.");
      } catch(e) {fail(e);updateCompareProgress();}
    }}, "Finish comparison"), h("button", {class:"btn",type:"button",onclick:openExport}, "Export results")));
  v.append(h("button", {type:"button",class:"btn small",onclick:()=>openClaimReview(data.claim)}, "View reviewed evidence"));
  const col = h("div", {});
  if (!data.rows.length) col.append(h("div", { class: "empty", text: "The firm's export has no rows for this claim." }));
  for (const r of data.rows) col.append(firmCard(r, data));
  const ref = h("div", { class: "ref-list" }, h("h2", { class: "section", text: "Your answer key" }),
    h("div", { class: "list" }, data.entities.map((e) => h("div", { class: "card" }, h("div", { class: "card-top" }, h("span", { class: "handle", text: `E${e.number}` }), h("span", { class: "card-title", text: e.label })),
      h("div", { class: "card-sub", text: [TYPE_LABEL[e.type], ...e.descriptions.slice(0, 2).map((x) => `“${x}”`)].join(" · ") }),
      e.details.length ? h("ul", { class: "facts" }, e.details.map((x) => h("li", { text: `${FIELD_LABEL[x.field] || x.field}: ${x.value}` }))) : null))));
  grid.append(col, ref);
  v.append(grid);
  updateCompareProgress();
}

function updateCompareProgress() {
  const rows = S.compare.rows;
  const done = rows.filter(rowDone).length;
  const pill = $("#compare-progress");
  if (!pill) return;
  pill.textContent = `${done} of ${rows.length} rows done`;
  pill.className = "pill " + (done === rows.length ? "complete" : "in_progress");
  const finish = $("#finish-comparison"), status = $("#comparison-status");
  if (finish) {
    const complete = S.compare.comparison?.complete;
    finish.disabled = !!complete || done !== rows.length;
    finish.textContent = complete ? "Comparison completed" : "Finish comparison";
    status.textContent = complete ? "Comparison complete — results are ready to export." : done === rows.length ? "All rows answered. Finish comparison to confirm this stage is complete." : "Answer the remaining rows, including watchlist reasons, then finish comparison.";
  }
}

// Saves for one row go one at a time and always send the row's latest full answers,
// so quick successive clicks can never overwrite each other with stale values.
function queueSave(r, kind, onSaved) {
  if (S.compare.comparison) S.compare.comparison.complete = false;
  updateCompareProgress();
  r.chain = r.chain.then(async () => {
    try {
      if (kind === "pairing") {
        const p = r.pairing;
        await api("/api/pairing", withMe({ firm_row_id: r.id, entity_id: p.entity_id || null, not_in_notes: !!p.not_in_notes,
          category_verdict: p.category_verdict || null, correct_category: p.correct_category || null }));
      } else {
        const w = r.watchlist;
        await api("/api/watchlist", withMe({ firm_row_id: r.id, decision: w.decision || null, note_supports: w.note_supports || null, reason: w.reason || null }));
      }
      onSaved && onSaved();
    } catch (e) { fail(e); }
  });
  return r.chain;
}

function firmCard(r, data) {
  const d = r.data;
  const p = r.pairing;
  const w = r.watchlist;
  const card = h("article", { class: "firm-card", data: { row: r.id } });
  const status = h("span", { class: "pill" });
  const refreshStatus = () => {
    const ok = rowDone(r);
    card.classList.toggle("done", ok);
    status.className = "pill" + (ok ? " complete" : "");
    status.textContent = ok ? "Done" : "Needs answers";
    updateCompareProgress();
  };
  card.append(h("header", {}, h("h3", { text: d.entity_name || "(no name)" }), r.flagged ? h("span", { class: "tag", text: "watchlist flag" }) : null,
    h("span", { class: "spacer" }), status));
  const dl = h("dl", {});
  for (const [k, label] of FIRM_FIELDS) if (d[k]) dl.append(h("dt", { text: label }), h("dd", { text: d[k] }));
  if (r.cited.length) dl.append(h("dt", { text: "Cites note" }), h("dd", {}, r.cited.map((n, i) => [i ? ", " : "", h("button", { class: "link", type: "button", onclick: () => openNote(data.claim, n), text: n })])));
  const facts = h("div", { class: "firm-facts" }, h("div", { class: "label muted small", text: "What the firm reported" }), dl);
  const qs_ = h("div", { class: "firm-qs" });

  const who = h("select", { "aria-label": "Which of your people or companies is this?" },
    h("option", { value: "", text: "Choose…" }), data.entities.map((e) => h("option", { value: e.id, text: `E${e.number} · ${e.label}` })), h("option", { value: "__none", text: "Not in these notes" }));
  who.value = p.not_in_notes ? "__none" : p.entity_id || "";
  qs_.append(h("div", { class: "q" }, h("span", { class: "label", text: "Which of your people or companies is this?" }), who));

  const catWrap = h("div", { class: "q" });
  const correct = h("select", { "aria-label": "What should the category be?" }, h("option", { value: "", text: "Choose…" }), data.categories.map((c) => h("option", { value: c, text: c })));
  correct.value = p.correct_category || "";
  const correctRow = field("What should it be?", correct);
  correctRow.hidden = p.category_verdict !== "wrong";
  const verdict = choiceGroup([["right", "Right"], ["wrong", "Wrong"], ["unknown", "The notes don't say"]], p.category_verdict, (val) => {
    p.category_verdict = val;
    if (val !== "wrong") p.correct_category = null;
    correctRow.hidden = val !== "wrong";
    refreshStatus();
    queueSave(r, "pairing");
  });
  catWrap.append(h("span", { class: "label", text: `The firm's category is “${d.entity_category_name || "(none)"}”. Is it right?` }), verdict, correctRow);
  const showFrozenCategory = () => {
    if (!data.independent) return;
    const decision = data.entities.find(e => e.id === p.entity_id)?.decision;
    catWrap.replaceChildren(h("p", {text: !decision ? "Pair this row to see its frozen category." : decision.status === "assigned" ?
      `Frozen category: ${decision.category}. ${decision.category.toLowerCase() === (d.entity_category_name || "").trim().toLowerCase() ? "Matches" : "Differs from"} the firm's category.` :
      `Frozen outcome: ${decision.status === "conflicting" ? "Conflicting" : "Insufficient"} evidence — excluded from category accuracy.`}));
  };
  showFrozenCategory();
  catWrap.hidden = !!p.not_in_notes;
  qs_.append(catWrap);

  who.addEventListener("change", () => {
    p.not_in_notes = who.value === "__none" ? 1 : 0;
    p.entity_id = who.value && who.value !== "__none" ? who.value : null;
    catWrap.hidden = !!p.not_in_notes;
    showFrozenCategory();
    refreshStatus();
    queueSave(r, "pairing");
  });
  correct.addEventListener("change", () => { p.correct_category = correct.value || null; queueSave(r, "pairing"); });

  if (r.flagged) {
    const method = [d.Exact_search_Note_ID ? "exact search" : null, d.GenAI_search_Note_ID || d.recordType === "genai_only" ? "GenAI" : null].filter(Boolean).join(" and ");
    const change = (key) => (val) => { w[key] = val; refreshStatus(); queueSave(r, "watch"); };
    const reason = h("textarea", { placeholder: "e.g. Name matches, but the note gives no address or TIN to confirm it." });
    reason.value = w.reason || "";
    const saveReason = () => { if ((reason.value.trim() || null) !== (w.reason || null)) { w.reason = reason.value.trim() || null; refreshStatus(); queueSave(r, "watch"); } };
    reason.addEventListener("input", debounce(saveReason, 700));
    reason.addEventListener("blur", saveReason);
    const box = h("div", { class: "watch-box" },
      h("div", { class: "help", text: `Flagged by ${method || "the firm's tool"} against watchlist entry “${d.Watchlist_entity_name || d.Exact_search_matched_watchlist_entity_name || "?"}”${d.GenAI_tok_sort_similarity ? `, similarity ${d.GenAI_tok_sort_similarity}` : ""}.` }),
      h("div", { class: "q" }, h("span", { class: "label", text: "Is the watchlist entry the same person or company?" }),
        choiceGroup([["same", "Same"], ["different", "Different"], ["cant_tell", "Can't tell"]], w.decision, change("decision"))),
      h("div", { class: "q" }, h("span", { class: "label", text: "Does the cited note support your answer?" }),
        choiceGroup([["yes", "Yes"], ["partly", "Partly"], ["no", "No"]], w.note_supports, change("note_supports"))),
      field("Why? (required)", reason, "A name alone isn't proof. Say what in the note does or doesn't confirm it."));
    const wl = [["Watchlist_entity_name", "Name"], ["watchlist_address", "Address"], ["watchlist_city", "City"], ["watchlist_state", "State"], ["watchlist_zip_code", "ZIP"], ["watchlist_phone", "Phone"], ["watchlist_TIN", "TIN"]];
    const wdl = h("dl", {});
    for (const [k, label] of wl) if (d[k]) wdl.append(h("dt", { text: label }), h("dd", { text: d[k] }));
    facts.append(h("div", { class: "label muted small watch-label", text: "Watchlist entry" }), wdl);
    qs_.append(box);
  }
  card.append(h("div", { class: "firm-body" }, facts, qs_));
  refreshStatus();
  return card;
}

// ---------------------------------------------------------------------------
// Scores
// ---------------------------------------------------------------------------
async function openScores() {
  if (!S.reviewer) return askReviewer();
  try {
    const practice = store.get("scoresPractice", "0");
    const s = await api("/api/scores" + qs(withMe({ practice })));
    showView("scores");
    const v = $("#view-scores");
    const toggle = h("input", { type: "checkbox", id: "sc-practice" });
    toggle.checked = practice === "1";
    toggle.addEventListener("change", () => { store.set("scoresPractice", toggle.checked ? "1" : "0"); openScores(); });
    v.replaceChildren(h("div", { class: "note-head" }, h("div", { class: "note-title" }, h("h1", { text: "How the firm's tool scores against your answer key" })),
      h("label", { class: "check-row", for: "sc-practice" }, toggle, h("span", { text: "Include the practice claim" }))),
      h("p", { class: "muted", text: `Answer keys used: ${s.claims.map((c) => claimLabel(c.claim)).join(", ") || "none yet"}. ${s.provisional ? "Provisional: finish the remaining comparisons before interpreting these scores." : ""} ${s.pending_rows ? `${s.pending_rows} firm row(s) still need your answers and aren't counted.` : ""}` }));
    const grid = h("div", { class: "score-grid" });
    for (const m of s.metrics) grid.append(h("div", { class: "score" }, h("div", { class: "name", text: m.name }), h("div", { class: "frac" + (m.denominator ? "" : " none"), text: m.text }), h("div", { class: "meaning", text: m.meaning })));
    v.append(grid);
    v.append(h("h2", { class: "section", text: "Watchlist flags by search method" }), h("table", { class: "plain" }, h("tr", {}, ["Method", "Same", "Different", "Can't tell", "Accuracy (same ÷ decided)"].map((x) => h("th", { text: x }))),
      s.watchlist_by_method.map((m) => h("tr", {}, h("td", { text: m.method }), h("td", { class: "num", text: m.same }), h("td", { class: "num", text: m.different }), h("td", { class: "num", text: m.cant_tell }), h("td", { class: "num", text: m.text })))));
    v.append(h("h2", { class: "section", text: "Is the GenAI similarity score trustworthy?" }), h("table", { class: "plain" }, h("tr", {}, ["Similarity score", "Flags", "Confirmed same", "Can't tell", "Accuracy"].map((x) => h("th", { text: x }))),
      s.similarity_bins.map((b) => h("tr", {}, h("td", { text: b.range }), h("td", { class: "num", text: b.flags }), h("td", { class: "num", text: b.confirmed_same }), h("td", { class: "num", text: b.cant_tell }), h("td", { class: "num", text: b.text })))));
    const ai = s.ai;
    v.append(h("h2", { class: "section", text: "AI drafts" }), h("div", { class: "score-grid" },
      h("div", { class: "score" }, h("div", { class: "name", text: "Draft acceptance rate" }), h("div", { class: "frac", text: ai.draft_precision.text }), h("div", { class: "meaning", text: "Drafts accepted ÷ drafts decided; a review diagnostic, not independent accuracy" })),
      h("div", { class: "score" }, h("div", { class: "name", text: "Correction rate" }), h("div", { class: "frac", text: ai.correction_rate.text }), h("div", { class: "meaning", text: "Accepted drafts you had to edit ÷ drafts accepted" })),
      h("div", { class: "score" }, h("div", { class: "name", text: "Manual-addition share" }), h("div", { class: "frac", text: ai.miss_rate.text }), h("div", { class: "meaning", text: "Records you added yourself ÷ all records, in notes that had AI drafts; not measured recall" }))));
    if (s.agreement.length) {
      v.append(h("h2", { class: "section", text: "Agreement between reviewers" }), h("table", { class: "plain" }, h("tr", {}, ["Note", "Reviewers", "Agreement (same ÷ either recorded)"].map((x) => h("th", { text: x }))),
        s.agreement.map((a) => h("tr", {}, h("td", { text: `${a.claim} ${a.note}` }), h("td", { text: a.reviewers.join(" and ") }), h("td", { class: "num", text: a.text })))));
    }
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------------------
// Help: quick guide and tour
// ---------------------------------------------------------------------------
function openHelp() {
  const rows = [
    ["entity", "Dr. Ada Monroe", "The first time each person or company is named in the claim."],
    ["mention", "She · Dr. Monroe · the clinic", "Later references to someone already recorded. Link it only when the note makes it clear."],
    ["detail", "001234567 → TIN", "Put it on the right owner. A clinic's address belongs to the clinic."],
    ["description", "orthopedic surgeon", "How the note characterizes someone. No category list — just the note's own words."],
    ["action", "did not schedule surgery", "Keep “not”, “reportedly”, dates and times inside the highlighted words."],
    ["unclear", "they (who?)", "When you can't tell who it is. Always say why."],
  ];
  const table = h("table", { class: "plain guide-table" }, h("tr", {}, ["Record", "Example", "Tip"].map((x) => h("th", { text: x }))),
    rows.map(([k, ex, tip]) => h("tr", {}, h("td", {}, h("span", { class: "kind " + KINDS[k].cls, text: KINDS[k].label }), " ", h("kbd", { text: KINDS[k].key })), h("td", { class: "quote", text: ex }), h("td", { text: tip }))));
  const keys = h("table", { class: "plain" }, [["Select words, then 1–6", "Record them as one of the six kinds"], ["A / X", "Accept or dismiss the AI draft you're reviewing"], ["Esc", "Close a menu or window"], ["?", "Open this help"]]
    .map(([k, d]) => h("tr", {}, h("td", { text: k }), h("td", { text: d }))));
  const body = h("div", { class: "form" },
    h("p", { text: "Read the note, select words, choose what they are. Every record keeps the note's exact words and their position, so anyone can check it later." }),
    table, h("p", {text:"After all notes are complete, review each entity's evidence across the claim. Assign a broad category or an unresolved outcome, mark supporting/conflicting/repeated evidence, and save. Freeze this answer key before comparing with the firm. Repeated text is not automatically independent corroboration."}),
    h("p",{text:"Ctrl+Z (Cmd+Z on Mac) or Undo reverses the last saved annotation, entity edit/delete, or AI accept/dismiss. Inside a text field it undoes typing. Frozen answer keys and firm exposure are not undone."}),
    h("p",{text:"After pairing and watchlist review, click Finish comparison. Use Export and tick Include practice data to download fictional practice work."}), h("h2", { class: "section", text: "Keyboard" }), keys);
  openModal("Quick guide", body, [modalButton("Take the tour", () => { closeModal(); startTour(); }), modalButton("Close", closeModal, "primary")], { wide: true });
}

const TOUR = [
  { title: "Welcome", target: null, text: ["You're building the answer key: a careful record of what each claim note says. The firm's extraction tool gets graded against it.", "This tour uses the practice note. Nothing you do there counts."] },
  { title: "Your notes", target: "#sidebar", text: ["Claims and their notes are listed here. The dot shows progress: empty, half, or full when complete."] },
  { title: "Read the note", target: "#note-text", text: ["Read here, top to bottom. You record things by selecting the words — no typing quotes, no counting occurrences."] },
  { title: "Select, then choose", target: "#action-menu", before: "demoMenu", text: ["Select any words and this menu appears beside them. Pick what the words are, or press its number key: 1 to 6.", "Four choices stay greyed out until you've recorded at least one person or company, because each of them has to belong to someone.", "Each kind has its own colour in the note, and the legend above the note shows which is which."] },
  { title: "People and companies", target: "#panel", before: "tabPeople", text: ["Everyone you record appears here. Click someone to light up every place they appear in the note."] },
  { title: "Optional: AI drafts", target: "#btn-ai", text: ["Copy the note for Copilot, paste its reply back, then review each draft. You accept, fix or dismiss every one — nothing is accepted automatically."] },
  { title: "Finish the note", target: "#btn-complete", text: ["When you've read every word and recorded everything, mark the note complete."] },
  { title: "Review the claim, then compare", target: "#claims", text: ["After every note is complete, review each entity's evidence across notes. Assign a broad category or an unresolved outcome, then freeze your answer key. Only then pair the firm's rows and review watchlist flags. Category agreement is calculated from your frozen decisions."] },
  { title: "Help any time", target: "#btn-help", text: ["Press this, or the ? key, for the quick guide or this tour."] },
];
let tourIndex = 0;

async function startTour() {
  const practice = S.claims.find((c) => c.practice);
  if (practice && !(S.cur && S.cur.claim === practice.claim && S.view === "note")) await openNote(practice.claim, practice.notes[0].note);
  tourIndex = 0;
  $("#tour").hidden = false;
  showTourStep();
}
function endTour() {
  $("#tour").hidden = true;
  hideActionMenu();
  window.getSelection().removeAllRanges();
  store.set("toured", "1");
}
function showTourStep() {
  const step = TOUR[tourIndex];
  if (step.before === "demoMenu" && S.view === "note") {
    const i = TEXT.indexOf("Dr. Ada Monroe");
    const segs = $$("#note-text .seg");
    const seg = segs.find((s) => +s.dataset.s <= i && +s.dataset.s + cpLen(s.textContent) > i) || segs[0];
    if (seg && seg.firstChild) {
      const off = i - +seg.dataset.s;
      const range = document.createRange();
      range.setStart(seg.firstChild, Math.max(0, off));
      range.setEnd(seg.firstChild, Math.min(seg.firstChild.length, off + 14));
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      S.sel = readSelection() || { start: i, end: i + 14 };
      showActionMenu();
    }
  } else hideActionMenu();
  if (step.before === "tabPeople") setTab("people");
  $("#tour-step").textContent = `${tourIndex + 1} of ${TOUR.length}`;
  $("#tour-title").textContent = step.title;
  const text = $("#tour-text");
  text.replaceChildren(...step.text.map((t) => h("p", { text: t })));
  if (step.list) text.append(h("ul", {}, step.list.map((l) => h("li", { text: l }))));
  $("#tour-back").disabled = tourIndex === 0;
  $("#tour-next").textContent = tourIndex === TOUR.length - 1 ? "Done" : "Next";
  const spot = $("#tour-spot"), card = $("#tour-card");
  const el = step.target ? $(step.target) : null;
  const visible = el && !el.hidden && el.getBoundingClientRect().width > 0;
  requestAnimationFrame(() => {
    const cw = card.offsetWidth, ch = card.offsetHeight;
    if (!visible) {
      spot.style.cssText = "";
      Object.assign(spot.style, { left: "50%", top: "40%", width: "0px", height: "0px" });
      Object.assign(card.style, { left: `${(innerWidth - cw) / 2}px`, top: `${Math.max(20, innerHeight * 0.3)}px` });
      return;
    }
    const r = el.getBoundingClientRect();
    const pad = 6;
    Object.assign(spot.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
    let left = r.right + 16, top = r.top;
    if (left + cw > innerWidth - 12) left = r.left - cw - 16;
    if (left < 12) { left = Math.min(Math.max(12, r.left), innerWidth - cw - 12); top = r.bottom + 14; }
    if (top + ch > innerHeight - 12) top = Math.max(12, innerHeight - ch - 12);
    Object.assign(card.style, { left: `${left}px`, top: `${Math.max(12, top)}px` });
  });
  $("#tour-next").focus();
}

// ---------------------------------------------------------------------------
// Reviewer name
// ---------------------------------------------------------------------------
function askReviewer() {
  const input = h("input", { type: "text", value: S.reviewer, placeholder: "e.g. Pat Morgan", "aria-label": "Your name" });
  const err = h("div", { class: "problem", hidden: true });
  const save = async () => {
    const name = input.value.trim();
    if (!name) { err.textContent = "Enter your name."; err.hidden = false; return; }
    S.reviewer = name;
    store.set("reviewer", name);
    $("#btn-reviewer").textContent = name;
    closeModal();
    await loadClaims();
    if (S.view === "note" && S.cur) openNote(S.cur.claim, S.cur.note);
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  const known = (S.boot && S.boot.reviewers) || [];
  const body = h("div", { class: "form" },
    field("Your name", input, "Your records are saved under this name. If two people annotate the same note, their work is kept separate so it can be compared."),
    known.length ? field("Or continue as", h("div", { class: "choices" }, known.map((n) => h("button", { class: "choice", type: "button", onclick: () => { input.value = n; save(); } }, n)))) : null, err);
  openModal("Who's annotating?", body, [modalButton("Continue", save, "primary")], { focus: input });
}

// ---------------------------------------------------------------------------
// Keyboard and wiring
// ---------------------------------------------------------------------------
function typing(el) { return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable); }

function openExport() {
  if (!S.reviewer) return askReviewer();
  const practice = h("input", {type:"checkbox",id:"export-practice"});
  const layout = h("select", {id:"export-layout"}, h("option",{value:"analysis",text:"3 analysis tables (recommended)"}), h("option",{value:"detailed",text:"Detailed audit files"}));
  const practiceCount = S.claims.filter(c=>c.practice).reduce((n,c)=>n+c.notes.reduce((m,x)=>m+x.records,0),0);
  const realCount = S.claims.filter(c=>!c.practice).reduce((n,c)=>n+c.notes.reduce((m,x)=>m+x.records,0),0);
  const notice = h("p", {id:"export-scope",role:"status"});
  const download = h("a", {id:"download-export",class:"btn primary",download:""}, "Download ZIP");
  const update = () => {
    notice.textContent = practice.checked ? "Includes fictional practice rows, clearly marked is_practice. These are not real-data performance results." :
      !realCount && practiceCount ? "Your saved work is practice data. Real-only export will have empty answer-key tables. Tick Include practice data to download your work." : "Real claims only. Practice rows are excluded.";
    download.href = "/api/export" + qs({reviewer:S.reviewer,practice:practice.checked?"1":"0",layout:layout.value});
  };
  practice.addEventListener("change",update);layout.addEventListener("change",update);update();
  openModal("Export your review", h("div",{class:"form"},
    h("p",{text:"The analysis export combines your work into entity_comparison.csv, evidence.csv and kpi_summary.csv. Frozen answer keys are used where available; unfinished work is labeled."}),
    field("Export format",layout),h("label",{},practice," Include practice data (fictional)"),notice,
    h("p",{class:"muted",text:"Import identifiers and TIN/ZIP columns as text to preserve leading zeros. The detailed option retains revision history and raw AI replies."})),
    [modalButton("Cancel",closeModal),download]);
}

async function undoAnnotation() {
  if (S.undoing || !S.reviewer) return;
  if (!$("#modal").hidden || !$("#tour").hidden) return fail(new Error("Close the dialog first to undo a saved annotation. Ctrl+Z in a text field undoes typing."));
  S.undoing = true; $("#btn-undo").disabled = true;
  try {
    const result = await api("/api/annotation/undo", withMe({}));
    hideActionMenu(); hidePopover(); S.sel = null; S.reviewId = null;
    await loadClaims();
    if (S.view === "review" && S.claimReview.claim === result.claim) await openClaimReview(result.claim, S.dossierEntity);
    else if (result.note) await openNote(result.claim, result.note);
    else if (S.cur?.claim === result.claim) await refresh();
    toast(result.message);
  } catch (e) { fail(e); }
  finally { S.undoing = false; $("#btn-undo").disabled = false; }
}

document.addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && ev.key.toLowerCase() === "z") {
    if (!typing(document.activeElement) && $("#modal").hidden && $("#tour").hidden) {
      ev.preventDefault(); if (!ev.repeat) undoAnnotation();
    }
    return;
  }
  if (ev.key === "Escape") {
    if (!$("#tour").hidden) return endTour();
    if (!$("#modal").hidden) return closeModal();
    hideActionMenu(); hidePopover();
    return;
  }
  if (!$("#tour").hidden) {
    if (ev.key === "ArrowRight") { ev.preventDefault(); $("#tour-next").click(); }
    if (ev.key === "ArrowLeft") { ev.preventDefault(); $("#tour-back").click(); }
    return;
  }
  if (!$("#modal").hidden || typing(document.activeElement) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (ev.key === "?") { ev.preventDefault(); openHelp(); return; }
  if (S.view !== "note") return;
  if (!$("#action-menu").hidden && /^[1-6]$/.test(ev.key)) {
    ev.preventDefault();
    const kind = ORDER[+ev.key - 1];
    const btn = $$("#action-menu .menu-item")[+ev.key - 1];
    if (btn && !btn.disabled) { hideActionMenu(); openRecordForm(kind, { ...S.sel }); }
    return;
  }
  if (S.reviewId && S.activeCard && S.tab === "drafts") {
    if (ev.key === "a" || ev.key === "A") { ev.preventDefault(); S.activeCard.accept(); }
    else if (ev.key === "x" || ev.key === "X") { ev.preventDefault(); S.activeCard.dismiss(); }
    else if (ev.key === "ArrowRight") { ev.preventDefault(); nextDraft(1); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); nextDraft(-1); }
  }
});

document.addEventListener("mousedown", (ev) => {
  if (!$("#action-menu").hidden && !ev.target.closest("#action-menu")) hideActionMenu();
  if (!$("#popover").hidden && !ev.target.closest("#popover") && !ev.target.closest("#btn-more")) hidePopover();
});
window.addEventListener("resize", () => { hideActionMenu(); hidePopover(); if (!$("#tour").hidden) showTourStep(); });
$("#workspace").addEventListener("scroll", () => { hideActionMenu(); hidePopover(); });

function wire() {
  $("#note-text").addEventListener("mouseup", onNoteMouseUp);
  $("#note-text").addEventListener("keyup", (ev) => { if (ev.shiftKey) onNoteMouseUp(ev); });
  $("#search").addEventListener("input", renderClaims);
  $("#btn-ai").addEventListener("click", openAiModal);
  $("#btn-complete").addEventListener("click", openComplete);
  $("#btn-more").addEventListener("click", openMore);
  $("#btn-help").addEventListener("click", openHelp);
  $("#btn-undo").addEventListener("click", undoAnnotation);
  $("#btn-scores").addEventListener("click", openScores);
  $("#btn-reviewer").addEventListener("click", askReviewer);
  $("#btn-export").addEventListener("click", ev => {
    ev.preventDefault();openExport();
  });
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("mousedown", (ev) => { if (ev.target.id === "modal") closeModal(); });
  $("#welcome-tour").addEventListener("click", startTour);
  $("#welcome-practice").addEventListener("click", () => { const p = S.claims.find((c) => c.practice); if (p) openNote(p.claim, p.notes[0].note); });
  $("#tour-next").addEventListener("click", () => { if (tourIndex >= TOUR.length - 1) return endTour(); tourIndex++; showTourStep(); });
  $("#tour-back").addEventListener("click", () => { if (tourIndex > 0) { tourIndex--; showTourStep(); } });
  $("#tour-close").addEventListener("click", endTour);
  $$("#panel-tabs .tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
}

async function init() {
  wire();
  $("#btn-reviewer").textContent = S.reviewer || "Enter your name";
  try { S.boot = await api("/api/bootstrap"); } catch (e) { fail(e); }
  showView("welcome");
  if (!S.reviewer) { askReviewer(); return; }
  try { await loadClaims(); } catch (e) { fail(e); }
}

init();
