"use strict";
// The decision card: how one identity link was decided, told as a sequence a reader can
// check. Everything comes from /api/link (links.json or watchlist_links.json, as the
// notebook wrote them); nothing is recomputed here except words and arithmetic on bits.
// Also: number formats, the entity summary sentence and the candidates panel, shared by
// every view that shows a link.

const GOKO = (window.GOKO = window.GOKO || {});
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  GOKO.esc = esc;

  // ---------------------------------------------------------------- numbers in words
  function fmtN(x) {
    if (!isFinite(x)) return "a vast number";
    if (x >= 1e15) return `2^${Math.round(Math.log2(x))}`;
    if (x >= 1e12) return `${(x / 1e12).toPrecision(2).replace(/\.0$/, "")} trillion`;
    if (x >= 1e9) return `${(x / 1e9).toPrecision(2).replace(/\.0$/, "")} billion`;
    if (x >= 100) return Number(x.toPrecision(2)).toLocaleString("en-US");
    if (x >= 10) return String(Math.round(x));
    return String(Number(x.toPrecision(2)));
  }
  const odds = (o) => (o >= 1 ? `${fmtN(o)} to 1` : `1 in ${fmtN(1 / o)}`);
  const prob = (p) => (p == null ? "—" : p >= 0.995 ? "> 0.99" : p < 0.005 ? "< 0.01" : p.toFixed(2));
  const band = (p) => (p >= 0.99 ? "very strong" : p >= 0.9 ? "strong" : p >= 0.8 ? "fairly strong" : p >= 0.5 ? "moderate" : p >= 0.1 ? "weak" : "very weak");
  const mult = (bits) => {
    if (bits == null) return "—";
    if (Math.abs(bits) < 0.05) return "×1";
    const m = Math.pow(2, bits);
    return bits > 0 ? `×${fmtN(m)}` : `÷${fmtN(1 / m)}`;
  };
  const probText = (p) => `${band(p)} (${prob(p)})`;
  Object.assign(GOKO, { fmtN, odds, prob, band, mult, probText });
  // the merge setting (the "lens"), in words: what a merge may rest on
  GOKO.LENS_LABEL = { strict: "Identifiers only", default: "Names + identifiers, confident", broad: "Also weak name matches" };

  // ---------------------------------------------------------------- vocabulary
  const DIST = {
    same_note: "two parts of the same note",
    same_claim: "two notes of the same claim",
    same_occurrence: "the same incident, another coverage",
    same_client: "the same insurer, another incident",
    different_client: "different insurers",
    watchlist: "one record on the OIG exclusion list",
  };
  const DIST_WHY = {
    same_note: "Two mentions in one note are often the same party. Starting odds are even (0.5) before any field is compared.",
    same_claim: "Within one claim, the same party is often named in several notes: prior 0.25.",
    same_occurrence: "Another coverage of the same incident often names the same parties: prior 0.1.",
    same_client: "Across incidents of one insurer: professionals and clinics are expected to recur (1 in 1,000), private persons are not (1 in a million).",
    different_client: "Across insurers: professionals and clinics can recur (1 in 10,000); a private person recurring is exceptional (1 in 10 million).",
    watchlist: "The chance this party is on the exclusion list at all, given its role (about 4% for professionals and organizations named in fraud files, 1% for private persons), spread over the list's ~84,000 records.",
  };
  const ROLE = { recurring: "professional or organization", private: "private person" };
  const BASIS = {
    identifier: ["shared identifier", "An identifier both sides state (NPI, TIN, SSN, VIN, bar or DEA number, license, phone, email, plate or bank account) agrees. The strict lens admits only these."],
    address: ["shared address", "Both sides give the same address. An address is weaker than an identifier: several parties share one."],
    dob: ["name + date of birth", "The names agree and so do stated dates of birth. A date of birth adds weight but is never an identifier on its own."],
    co_party: ["name + anchored co-party", "The names agree, and another party in both claims is linked on an identifier. Co-parties matching only by name never count."],
    location: ["name + location", "The names agree and so do ZIP, city or state (from the parties' addresses, or a watchlist record's city and state). Weaker than a shared address."],
    name_only: ["name only", "Only the name agrees: no identifier, address or anchored co-party. A rare name can score high and is still a name-only link."],
    none: ["nothing agreed", "No field agreed. A prior alone never merges anything."],
  };
  const RESTS = {
    identifier: "a shared identifier. This is the strongest basis: a coincidental match is assumed rare, and the strict lens admits it.",
    address: "a shared address, plus whatever the names add.",
    dob: "the name plus a matching date of birth. No identifier agrees.",
    co_party: "the name, strengthened by co-parties that are linked on an identifier in both claims.",
    location: "the name, plus a matching ZIP, city or state. No identifier or street address agrees.",
    name_only: "the name alone. No identifier, address or anchored co-party agrees: however high the score, a different party with the same name would look identical.",
    none: "nothing: no field agreed.",
  };
  const EXCL = {
    "1128a1": "conviction of a program-related crime", "1128a2": "conviction relating to patient abuse or neglect",
    "1128a3": "felony conviction relating to health care fraud", "1128a4": "felony conviction relating to controlled substances",
    "1128b1": "misdemeanor conviction relating to health care fraud", "1128b2": "conviction relating to obstruction of an investigation",
    "1128b3": "misdemeanor conviction relating to controlled substances", "1128b4": "license revocation, suspension or surrender",
    "1128b5": "exclusion or suspension under a federal or state health care program", "1128b6": "excessive claims or unnecessary services",
    "1128b7": "fraud, kickbacks and other prohibited activities", "1128b8": "entity controlled by a sanctioned individual",
    "1128b14": "default on a health education loan", "1128b15": "individual controlling a sanctioned entity",
    "1128b16": "false statement or misrepresentation of material fact", "1156": "failure to meet statutory obligations",
  };
  const vetoWords = (v) => {
    if (!v) return "";
    let m;
    if ((m = v.match(/^conflicting_(\w+?):(.*)$/))) return `Both sides state a ${m[1].replaceAll("_", " ")}, and they differ (${m[2]}). A party has only one, so these cannot be the same party.`;
    if ((m = v.match(/^credential_conflict:(.*)$/))) return `The two hold different primary licenses (${m[1]}). A person holds one, so these cannot be the same person.`;
    if ((m = v.match(/^distinct_org_names:(.*)$/))) return `Each name keeps a distinctive word the other lacks (${m[1]}): sibling companies, not one party under two names.`;
    if ((m = v.match(/^sibling_org_names:complete name vs one adding (.*)$/))) return `One is a complete company name, and the other adds ${m[1]} to it: a sibling company, not a short form of the same one.`;
    if ((m = v.match(/^sibling_org_names:(.*)$/))) return `The names start alike but each keeps a word the other lacks (${m[1]}): sibling companies, not one party.`;
    if ((m = v.match(/^kind_conflict:(\w+) vs (\w+)$/))) return `One is a ${m[1]}, the other a ${m[2]}: ${m[1] === "construct" || m[2] === "construct" ? "a legal construct (an enterprise, a scheme) is not the company it is named after" : "a group is not one of its members"}.`;
    if ((m = v.match(/^conflicting_driver_license:(\w+)/))) return `Both sides state a driver's license from ${m[1]}, and the numbers differ. A person holds one per state, so these cannot be the same person.`;
    return v;
  };
  const basisChip = (b) => {
    const [label, why] = BASIS[b] || [b, ""];
    const cls = b === "identifier" ? "good" : b === "none" ? "" : "warn";
    return `<span class="chip ${cls}" title="${esc(why)}">${esc(label)}</span>`;
  };
  Object.assign(GOKO, { basisChip, vetoWords, EXCL, BASIS, DIST });

  // ---------------------------------------------------------------- drawer
  function drawer() {
    let d = document.getElementById("drawer");
    if (d) return d;
    const scrim = document.createElement("div");
    scrim.id = "scrim"; scrim.hidden = true;
    scrim.addEventListener("click", closeDrawer);
    d = document.createElement("aside");
    d.id = "drawer"; d.className = "drawer"; d.hidden = true;
    d.setAttribute("role", "dialog"); d.setAttribute("aria-label", "Details");
    d.innerHTML = `<div class="drawer-head"><div class="drawer-title"></div><button class="icon-btn" data-close aria-label="Close" title="Close (Esc)">×</button></div><div class="drawer-body"></div>`;
    d.querySelector("[data-close]").addEventListener("click", closeDrawer);
    document.body.append(scrim, d);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !d.hidden) closeDrawer(); });
    return d;
  }
  function openDrawer(title, html) {
    const d = drawer();
    d.querySelector(".drawer-title").innerHTML = title;
    const body = d.querySelector(".drawer-body");
    body.innerHTML = html; body.scrollTop = 0;
    d.hidden = false; document.getElementById("scrim").hidden = false;
    wire(body);
    return body;
  }
  function closeDrawer() {
    const d = document.getElementById("drawer");
    if (d) { d.hidden = true; document.getElementById("scrim").hidden = true; }
  }
  // elements inside a card: data-card opens another card, data-open asks the app to open a view
  function wire(el, opts = {}) {
    el.querySelectorAll("[data-card]").forEach((x) => x.addEventListener("click", (e) => {
      e.stopPropagation();
      const [a, b] = JSON.parse(x.dataset.card);
      openCard(a, b, x.dataset.lens || GOKO.lens || "default");
    }));
    if (opts.open === false) return;
    el.querySelectorAll("[data-open]").forEach((x) => x.addEventListener("click", (e) => {
      e.stopPropagation();
      const r = JSON.parse(x.dataset.open);
      if (x.closest("#drawer")) closeDrawer();
      document.dispatchEvent(new CustomEvent("goko:open", { detail: r }));
    }));
  }
  Object.assign(GOKO, { openDrawer, closeDrawer, wire });

  const openAttr = (o) => `data-open='${esc(JSON.stringify(o))}'`;
  const cardAttr = (a, b) => `data-card='${esc(JSON.stringify([a, b]))}'`;
  GOKO.cardAttr = cardAttr;
  GOKO.openAttr = openAttr;

  // ---------------------------------------------------------------- the card
  async function openCard(a, b, lens) {
    openDrawer("Linkage decision", `<div class="thinking"><span class="dot"></span>Loading the decision…</div>`);
    try {
      const r = await fetch("/api/link?" + new URLSearchParams({ a, b, lens: lens || "default" }));
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      const d = await r.json();
      const title = `How “${esc(d.a.name)}” and “${esc(d.b.kind === "record" ? d.b.record.name : d.b.name)}” were compared`;
      openDrawer(title, renderCard(d));
    } catch (e) { openDrawer("Linkage decision", `<p class="err">${esc(e.message)}</p>`); }
  }
  GOKO.openCard = openCard;

  // Display only: runs of blank lines (page breaks in court filings) shrink to one, so the
  // highlighted words are in view. The span and the stored text are untouched.
  const squeeze = (s) => String(s || "").replace(/[ \t]*\n[ \t\n]*\n[ \t\n]*/g, "\n\n");
  function excerptHTML(x) {
    if (!x) return `<div class="ev muted">no source passage</div>`;
    return `<div class="ev">${x.clipped_left ? "…" : ""}${esc(squeeze(x.before).replace(/^\s+/, ""))}<mark>${esc(x.match)}</mark>${esc(squeeze(x.after).replace(/\s+$/, ""))}${x.clipped_right ? "…" : ""}</div>`;
  }
  GOKO.excerptHTML = excerptHTML;
  GOKO.squeeze = squeeze;
  function sideHTML(s, tag) {
    if (s.kind === "record") {
      const r = s.record || {};
      const ex = EXCL[r.excl_type];
      return `<div class="side"><div class="side-tag">${tag}</div><div class="side-name">${esc(r.name)}</div>
        <div class="muted">A record on the <span title="${esc(s.source || "OIG LEIE")}: federal health-care exclusion list, published by the HHS Office of Inspector General">OIG exclusion list</span>, not a mention in a note.</div>
        <dl class="kv"><dt>Listed as</dt><dd>${esc(r.general || "—")}${r.specialty ? " · " + esc(r.specialty) : ""}</dd>
        <dt>Location</dt><dd>${esc(titleCase(r.city))}${r.state ? ", " + esc(r.state) : ""}</dd>
        <dt>Excluded</dt><dd>${esc(r.excl_date || "—")} under <span class="term" title="${esc(ex ? "Exclusion authority " + r.excl_type + ": " + ex : "OIG exclusion authority " + r.excl_type)}">${esc(r.excl_type || "—")}</span>${ex ? ` (${esc(ex)})` : ""}</dd>
        <dt>NPI</dt><dd>${r.npi ? esc(r.npi) : `<span class="muted">none on the record</span>`}</dd></dl></div>`;
    }
    return `<div class="side"><div class="side-tag">${tag}</div>
      <div class="side-name">${esc(s.name)}</div>
      <div class="muted">${esc(s.type)} · <span title="Role class sets the starting odds: professionals and organizations recur across claims by nature, private persons do not">${esc((s.role_class || "").replace("_", " "))}</span> ·
        <span class="link" ${openAttr({ kind: "claim", id: s.claim_id, label: s.claim_id, why: "claim of a compared mention" })}>${esc(s.claim_id)}</span> ·
        <span class="link" ${openAttr({ kind: "note", id: s.note, label: s.note.replace("note:", "Note "), span: s.evidence && s.evidence.span, why: "note of a compared mention" })}>${esc(s.note.replace("note:", "Note "))}</span></div>
      ${s.name_as_extracted && s.name_as_extracted !== s.name ? `<div class="muted">the model named it “${esc(s.name_as_extracted)}”; the note's fuller form is used</div>` : ""}
      ${excerptHTML(s.evidence)}
      <div class="muted">In <span class="link" ${openAttr({ kind: "entity", id: s.entity.id, label: s.entity.name, why: "entity of a compared mention" })}>${esc(s.entity.name)}</span> at this lens</div></div>`;
  }
  const titleCase = (s) => String(s || "").toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());

  function commonWords(f) {
    const src = { census2010: "Census 2010 surnames", "ssa1930-2005": "SSA births 1930–2005", nppes: "NPPES organizations", FLAT: "no table: flat rate" };
    const S = (k) => src[k] || k || "assumed";
    switch (f.field) {
      case "last":
        if (f.level === "missing") return "—";
        if (f.level === "exact") return `about 1 in ${fmtN(1 / f.u)} people have this surname <span class="muted">(${esc(S(f.u_source))})</span>`;
        if (f.level === "close") return `spelling variants; the commoner is held by about 1 in ${fmtN(1 / Math.max(f.freq_a, f.freq_b))} <span class="muted">(${esc(S(f.u_source))})</span>`;
        return "different surnames";
      case "first":
        if (f.level === "missing") return "—";
        if (f.initial_share != null) return `${(100 * f.initial_share).toFixed(1)}% of first names start with ${esc((f.a || "?")[0])} <span class="muted">(${esc(S(f.u_source))})</span>`;
        if (f.level === "exact") return `about 1 in ${fmtN(1 / f.u)} people have this first name <span class="muted">(${esc(S(f.u_source))})</span>`;
        if (f.level === "close") return `spelling variants <span class="muted">(${esc(S(f.u_source))})</span>`;
        return "different first names";
      case "middle":
        return f.level === "missing" ? "—" : f.level === "exact" ? "1 in 15 share an initial (assumed)" : "different initials";
      case "org_name": {
        const w = (t) => `<span class="tok" title="${esc(`${t.t}: used by ${t.orgs_using.toLocaleString("en-US")} of ${t.orgs_total.toLocaleString("en-US")} organizations in NPPES; ${t.bits} bits of surprise`)}">${esc(t.t)} <span class="muted">1 in ${fmtN(Math.pow(2, t.bits))}</span></span>`;
        let h = f.shared.length ? `shared: ${f.shared.map(w).join(" ")}` : "no word in common";
        if (f.only_a.length || f.only_b.length) h += `<div class="muted">only one side: ${[...f.only_a, ...f.only_b].map(w).join(" ")}</div>`;
        return h;
      }
      case "identifier":
      case "dob":
        if (f.level === "exact") return f.type === "dob" ? `about 1 in ${fmtN(1 / f.u)} people share a birth date` : `a coincidental match is assumed at 1 in ${fmtN(1 / f.u)}${f.m < 0.9 ? "; one owner was inferred, so it counts for less" : ""}${f.note ? `; ${esc(f.note)}` : ""}`;
        return f.note ? esc(f.note) : f.level === "missing" ? "only one side states one" : "";
      case "location":
        if (f.level === "missing") return "not compared: " + (f.a ? "the record" : "the mention") + " has no location";
        return `${(100 * f.u).toFixed(1)}% of US residents live in ${esc((f.b || "").split(", ").pop())} <span class="muted">(2020 Census)</span>`;
      case "vehicle": return "fixed weights (assumed)";
      case "address":
        if (f.bits == null) return f.note ? esc(f.note) : "only one side states one";
        return `${esc({ exact: "the same address", same_street: "the same street and number; the unit differs or is missing", same_zip: "the same ZIP code", same_city: "the same city", same_state: "the same state" }[f.level] || f.level)}; two different parties agree this far about 1 in ${fmtN(1 / f.u)} times (assumed)`;
      case "specialty":
        return `${f.level === "exact" ? "the stated specialties agree" : "the stated specialties differ"}; supports the name, never an identifier`;
      case "co_party": return `${f.pairs.length} co-party pair(s) linked on an identifier in both claims; +${f.per_pair} bits each, at most ${f.max_pairs}`;
      default: return "";
    }
  }
  function compared(f) {
    const v = (x) => (Array.isArray(x) ? (x.length ? x.join(", ") : "—") : x == null || x === "" ? "—" : x);
    if (f.field === "org_name") return `${esc(f.a)} <span class="muted">↔</span> ${esc(f.b)}`;
    if (f.field === "co_party") return f.pairs.map((p) => esc(p.join(" ~ "))).slice(0, 2).join("<br>");
    return `${esc(v(f.a))} <span class="muted">↔</span> ${esc(v(f.b))}`;
  }
  const LEVEL = { exact: "exact", close: "close", initial: "initial", differ: "differ", missing: "missing", shared: "shared words", conflict: "conflict", anchored: "anchored",
    same_street: "same street", same_zip: "same ZIP",
    same_city: "same city", same_state: "same state", same_state_other_city: "same state", different_state: "different state" };
  const LEVEL_WHY = {
    exact: "The values are identical after normalization.", close: "Spelling variants (Jaro-Winkler ≥ 0.92).", initial: "One side gives only an initial, and it agrees.",
    differ: "The values differ.", missing: "One or both sides do not state it, so it was not compared.", shared: "The names share these words.",
    conflict: "Both sides state a value a party can hold only one of, and they differ.", anchored: "Linked on an identifier in both claims.",
  };
  function fieldRow(f) {
    const bits = f.bits;
    const scale = Math.min(1, Math.abs(bits || 0) / 30) * 50;
    const bar = bits == null ? "" : `<span class="fbar-fill ${bits >= 0 ? "pos" : "neg"}" style="${bits >= 0 ? "left:50%" : `left:${50 - scale}%`};width:${scale}%"></span>`;
    const label = f.field === "identifier" || f.field === "dob" ? f.label.replace(/\b(npi|ssn|tin|vin|dea)\b/gi, (m) => m.toUpperCase()) : f.label;
    const effect = f.veto ? `<span class="chip bad" title="${esc(vetoWords("conflicting_" + f.type + ":"))}">veto</span>`
      : bits == null ? `<span class="muted" title="Not scored">—</span>`
      : `<span class="mult ${bits >= 0 ? "pos" : "neg"}" title="${esc(`${bits >= 0 ? "+" : ""}${bits} bits${f.m != null && f.u != null ? ` = log2(m / u) = log2(${f.m} / ${Number(f.u.toPrecision(3))})` : ""}. m: how often this agrees when the two ARE one party; u: how often it agrees by coincidence.`)}">${mult(bits)}</span>`;
    return `<div class="frow"><div class="fname">${esc(label)}${f.identifier_basis ? ` <span class="chip good" title="Agreement on this makes the link identifier-backed">identifier</span>` : ""}</div>
      <div class="fcmp">${compared(f)}</div>
      <div class="flevel"><span class="chip" title="${esc(LEVEL_WHY[f.level] || "")}">${esc(LEVEL[f.level] || f.level)}</span></div>
      <div class="fcommon">${commonWords(f)}</div>
      <div class="feffect">${effect}<div class="fbar">${bar}<span class="fbar-mid"></span></div></div></div>`;
  }

  function lensRow(r, l, watch) {
    const name = GOKO.LENS_LABEL[r.lens] || r.lens;
    let status, why = "";
    if (!r.admitted) {
      status = `<span class="chip">not admitted</span>`;
      const notId = r.identifier_only && l.basis_class !== "identifier";
      why = r.why_not === "veto" ? vetoWords(l.veto)
        : r.why_not === "no_agreement" ? "No field agreed; a prior alone never merges anything."
        : notId ? `Strict admits only identifier-backed links; this one rests on ${esc((BASIS[l.basis_class] || [l.basis_class])[0])}${l.p < r.min_p ? `, and ${prob(l.p)} is below ${r.min_p.toFixed(2)} too` : ""}.`
        : `Its probability, ${prob(l.p)}, is below this lens's ${r.min_p.toFixed(2)}.`;
    } else if (watch) {
      status = `<span class="chip bad">flags for review</span>`;
      why = "Admitted: the entity this mention belongs to is Flagged for review at this lens.";
    } else if (r.refused) {
      status = `<span class="chip warn">admitted, union refused</span>`;
      why = r.refused.reason === "veto"
        ? `Joining would put ${r.refused.would_merge.map((x) => "“" + esc(x) + "”").join(" and ")} in one entity, and that pair is vetoed.`
        : `Joining would grow the entity to ${r.refused.would_reach} mentions, past the cluster-size alarm.`;
    } else if (r.merged) {
      status = `<span class="chip good">merged</span>`;
      why = r.by_this_link ? "Admitted, and this link is one of the links that build the entity." : "Admitted; the two were already in one entity through stronger links.";
    } else {
      status = `<span class="chip">admitted</span>`;
      why = "Admitted, but the two ended in different entities.";
    }
    return `<div class="lrow"><div class="lname" title="${esc(r.identifier_only ? "identifier-backed links only, p ≥ " + r.min_p : "any basis, p ≥ " + r.min_p)}">${name}</div><div>${status}</div><div class="muted">${why}</div></div>`;
  }

  function renderCard(d) {
    const l = d.link, watch = d.watchlist;
    const [dist, cls] = (l.prior_key || "").split("/");
    const prior = l.prior, priorOdds = prior / (1 - prior);
    const fields = l.fields || [];
    const finalOdds = l.p >= 1 ? Infinity : l.p / (1 - l.p);
    let h = `<div class="card-sim" title="Average Jaro-Winkler similarity of the compared names. A display aid: the probability below is what decides.">Name similarity <strong>${l.name_similarity_pct ?? Math.round(100 * (l.name_similarity || 0))}%</strong></div>`;
    h += `<section class="step"><h3><span class="n">1</span>The two ${watch ? "sides" : "mentions"} compared</h3><div class="sides">${sideHTML(d.a, "A")}${sideHTML(d.b, "B")}</div></section>`;
    h += `<section class="step"><h3><span class="n">2</span>Starting odds</h3>
      <p><strong>${odds(priorOdds)}</strong> — ${esc(cls ? ROLE[cls] : "")}${cls ? ", " : ""}${esc(DIST[dist] || dist)}
      <span class="help" title="${esc(DIST_WHY[dist] || "")} A stated assumption (notebook cell 18), not a measurement.">?</span></p>
      <p class="muted">Before any field is compared: how often two ${watch ? "sides" : "mentions"} like these are the same party.</p></section>`;
    h += `<section class="step"><h3><span class="n">3</span>The evidence, field by field</h3>
      <div class="fhead"><div>Field</div><div>Compared</div><div>Agreement</div><div>How common</div><div>Effect on the odds</div></div>
      ${fields.map(fieldRow).join("")}`;
    const ov = l.co_party && l.co_party.overlap;
    if (ov && !watch) h += `<div class="frow unscored"><div class="fname">co-parties matching by name</div><div class="fcmp" title="${esc((ov.names || []).join(", "))}">${ov.matched} of ${ov.of}</div>
      <div class="flevel"><span class="chip">shown only</span></div><div class="fcommon">Other parties of the two claims that also match each other by name. Not scored: coincidences cannot vouch for each other.</div><div class="feffect"><span class="muted">not scored</span></div></div>`;
    h += `</section>`;
    h += `<section class="step"><h3><span class="n">4</span>Result</h3>
      <p>${odds(priorOdds)} × ${mult(l.bits)} = <strong>${isFinite(finalOdds) ? odds(finalOdds) : "near certainty"}</strong>, a probability of <strong>${prob(l.p)}</strong>:
      <span class="chip ${l.p >= 0.9 ? "good" : l.p >= 0.5 ? "" : "warn"}" title="very strong ≥ 0.99, strong ≥ 0.90, fairly strong ≥ 0.80, moderate ≥ 0.50, weak ≥ 0.10, very weak below">${band(l.p)}</span></p>
      <p class="muted" title="${esc(`${l.bits} bits of evidence in total`)}">The evidence multiplies the starting odds by ${mult(l.bits)}. Fields are treated as independent, which they are not, so raw probabilities run high.</p>
      ${l.veto ? `<p class="err"><strong>Vetoed.</strong> ${esc(vetoWords(l.veto))} Whatever the probability, no lens can join these two.</p>` : ""}</section>`;
    h += `<section class="step"><h3><span class="n">5</span>What this rests on</h3><p>${basisChip(l.basis_class)} This link rests on ${RESTS[l.basis_class] || esc(l.basis_class)}</p></section>`;
    h += `<section class="step"><h3><span class="n">6</span>${watch ? "Flag" : "Merge"} outcome by lens</h3>${d.lenses.map((r) => lensRow(r, l, watch)).join("")}
      <p class="muted">Proposed by ${esc((l.proposed_by || []).join(", ") || "—")}.</p></section>`;
    return h;
  }
  GOKO.renderCard = renderCard;

  // ---------------------------------------------------------------- entity pieces
  function basisPhrase(classes) {
    const words = { identifier: "shared identifiers", address: "a shared address", dob: "name and date of birth", co_party: "name and anchored co-parties", location: "name and location", name_only: "name alone" };
    const c = classes.filter((x) => words[x]);
    if (!c.length) return "";
    if (c.length === 1) return `merged on ${words[c[0]]}`;
    return `merged on mixed evidence: ${c.map((x) => words[x]).join(", ")}`;
  }
  GOKO.summaryHTML = (d) => {
    const n = d.mention_count, k = d.claims.length;
    let s = `${n} mention${n === 1 ? "" : "s"} across ${k} claim${k === 1 ? "" : "s"}`;
    if (n > 1) s += `, ${basisPhrase(d.basis_classes)}`;
    s += ".";
    if (d.weakest_link) {
      const w = d.weakest_link;
      s += ` Weakest link <span class="link" ${cardAttr(w.a, w.b)} title="Open the decision card for this link">“${esc(w.a_name)}” ↔ “${esc(w.b_name)}”</span> is ${probText(w.p)}.`;
    }
    if (d.flagged && d.flagged.length) {
      const f = d.flagged[0];
      s += ` <span class="flag-inline">Flagged for review</span>: <span class="link" ${cardAttr(f.mention, f.record_id)}>linked to an OIG exclusion record</span>, ${probText(f.p)}, ${esc((BASIS[f.basis_class] || [f.basis_class])[0])}.`;
    }
    return `<p class="summary">${s}</p>`;
  };
  GOKO.categoryHTML = (d) => d.category_line && d.category_line.length
    ? `<p class="role-line"><span class="term" title="A category the model assigned from each claim's evidence. It describes what the party does in the claim; it plays no part in deciding identity.">Role (model's reading, not identity)</span>: ${d.category_line.map(esc).join(" / ")}</p>` : "";

  function candRow(r) {
    return `<div class="crow" ${cardAttr(r.a, r.b)} title="Open the decision card">
      <div class="cname">${esc(r.other.mention_name)}${r.other.name !== r.other.mention_name ? ` <span class="muted">in ${esc(r.other.name)}</span>` : ""}<div class="muted">${esc(DIST[r.distance] || r.distance)} · via “${esc(r.via)}”</div></div>
      <div class="csim" title="Name similarity (display aid)">${r.similarity}%</div>
      <div class="cp" title="Probability the two are one party">${esc(probText(r.p))}</div>
      <div>${basisChip(r.basis_class)}${r.veto ? ` <span class="chip bad" title="${esc(vetoWords(r.veto))}">veto</span>` : ""}</div></div>`;
  }
  GOKO.candidatesHTML = (c, lens) => {
    if (!c || (!c.merged.length && !c.not_merged.length)) return "";
    let h = `<section class="block"><h2 title="The links around this entity. Each row opens its decision card.">Candidates</h2>`;
    if (c.not_merged.length) h += `<div class="csub">Closest not merged at ${esc(lens)} (${c.not_merged.length}${c.not_merged_total > c.not_merged.length ? ` of ${c.not_merged_total}` : ""})</div>${c.not_merged.map(candRow).join("")}`;
    if (c.merged.length) h += `<div class="csub">Links that merged its mentions (${c.merged.length})</div>${c.merged.map(candRow).join("")}`;
    return h + `</section>`;
  };
  GOKO.watchRowHTML = (f) => {
    const r = f.record || {};
    const ex = EXCL[r.excl_type];
    return `<div class="crow" ${cardAttr(f.mention, f.record_id)} title="Open the decision card">
      <div class="cname">${esc(r.name)} <span class="muted">${esc(r.general || "")}${r.specialty ? " · " + esc(r.specialty) : ""}</span>
        <div class="muted">${esc(titleCase(r.city))}${r.state ? ", " + esc(r.state) : ""} · excluded ${esc(r.excl_date || "")} <span class="term" title="${esc(ex || "OIG exclusion authority")}">${esc(r.excl_type || "")}</span> · via “${esc(f.mention_name)}”${f.links > 1 ? ` and ${f.links - 1} more mention(s)` : ""}</div></div>
      <div class="cp">${esc(probText(f.p))}</div>
      <div>${basisChip(f.basis_class)}${f.veto ? ` <span class="chip bad" title="${esc(vetoWords(f.veto))}">veto</span>` : ""}</div>
      <div class="muted" title="The lenses at which this link flags the entity">${f.admitted.length ? "flags at " + esc(f.admitted.join(", ")) : "flags at no lens"}</div></div>`;
  };
})();
