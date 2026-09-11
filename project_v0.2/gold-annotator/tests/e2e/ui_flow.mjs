// End-to-end UI run in a real headless browser against a real server.
//   node tests/e2e/ui_flow.mjs            (from the gold-annotator folder)
// Screenshots go to tests/e2e/screens/. Fails on any JavaScript error or covered control.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, copyFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { launch } from "./cdp.mjs";

const ROOT = resolve(import.meta.dirname, "..", "..");
const SHOTS = join(ROOT, "tests", "e2e", "screens");
const STRESS = resolve(ROOT, "..", "python-annotator", "sample-data", "stress-packet");
const PORT = 8799;
const BASE = `http://localhost:${PORT}/`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

rmSync(SHOTS, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true });
const work = mkdtempSync(join(tmpdir(), "annot-srv-"));
mkdirSync(join(work, "notes"));
for (const n of ["C201_N01.txt", "C201_N04.txt"]) copyFileSync(join(STRESS, "notes", n), join(work, "notes", n));

const server = spawn("python", [join(ROOT, "run.py"), "--notes", join(work, "notes"), "--firm", join(STRESS, "client-export.csv"),
  "--db", join(work, "db.sqlite3"), "--port", String(PORT), "--no-browser"], { stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", (d) => (serverLog += d));
server.stderr.on("data", (d) => (serverLog += d));

const results = [];
let step = 0;
let b;
async function check(name, fn) {
  step++;
  const tag = String(step).padStart(2, "0");
  try {
    await fn();
    const junk = await b.eval(String.raw`(document.body.innerText.match(/\b(null|undefined|NaN)\b|\[object \w+\]/) || [""])[0]`);
    if (junk) throw new Error(`the page shows "${junk}" somewhere`);
    await b.shot(join(SHOTS, `${tag}-${name}.png`));
    results.push(["PASS", name]);
  } catch (e) {
    try { await b.shot(join(SHOTS, `${tag}-FAIL-${name}.png`)); } catch { /* ignore */ }
    results.push(["FAIL", name, e.message]);
    throw e;
  }
}
const visible = (sel) => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); return e && !e.hidden && e.getBoundingClientRect().width > 0; })()`;
const text = (sel) => `(document.querySelector(${JSON.stringify(sel)})?.textContent || "")`;

try {
  for (let i = 0; i < 40; i++) { try { await fetch(BASE); break; } catch { await sleep(250); } }
  b = await launch({ width: 1440, height: 900 });
  await b.send("Browser.grantPermissions", { origin: BASE.slice(0, -1), permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"] }).catch(() => {});

  await check("first-run-asks-for-name", async () => {
    await b.goto(BASE);
    await b.waitFor(visible("#modal"), "name dialog");
    const title = await b.eval(text("#modal-title"));
    if (!title.includes("Who")) throw new Error("expected the name dialog, got " + title);
  });
  await check("name-saved", async () => {
    await b.fill("#modal-body input", "Pat Reviewer");
    await b.clickText("#modal-foot .btn", "Continue");
    await b.waitFor(`!${visible("#modal")}`, "dialog closed");
    if ((await b.eval(text("#btn-reviewer"))) !== "Pat Reviewer") throw new Error("name chip not updated");
    await b.waitFor(`document.querySelectorAll(".note-link").length >= 3`, "notes listed");
  });

  await check("tour-step-1", async () => {
    await b.click("#welcome-tour", "Take the tour");
    await b.waitFor(visible("#tour"), "tour open");
  });
  await check("tour-menu-step", async () => {
    for (let i = 0; i < 3; i++) await b.click("#tour-next", "Next");
    await b.waitFor(visible("#action-menu"), "demo action menu");
    const says = await b.eval(text("#tour-text"));
    if (!says.includes("number key") || !says.includes("greyed out")) throw new Error("tour step should explain keys and greyed-out choices: " + says);
  });
  await check("tour-last-step", async () => {
    for (let i = 0; i < 5; i++) await b.click("#tour-next", "Next");
    if ((await b.eval(text("#tour-next"))) !== "Done") throw new Error("expected last step");
    await b.click("#tour-next", "Done");
    await b.waitFor(`!${visible("#tour")}`, "tour closed");
    await b.waitFor(`!${visible("#action-menu")}`, "demo menu closed");
  });

  await check("practice-note-open", async () => {
    if (!(await b.eval(text("#note-title"))).includes("Practice")) throw new Error("practice note not open");
    const t = await b.eval(`document.querySelector("#note-text").textContent`);
    if (!t.startsWith("Dr. Ada Monroe")) throw new Error("note text missing");
  });

  await check("select-opens-menu", async () => {
    await b.selectInNote("Dr. Ada Monroe", 0);
    await b.waitFor(visible("#action-menu"), "action menu");
    const disabled = await b.eval(`Array.from(document.querySelectorAll("#action-menu .menu-item")).filter(x => x.disabled).length`);
    if (disabled !== 4) throw new Error("with no entities yet, the 4 dependent kinds should be disabled; got " + disabled);
  });
  await check("entity-form", async () => {
    await b.key("1");
    await b.waitFor(visible("#modal"), "entity form");
    const pressed = await b.eval(`document.querySelector('#modal-body .choice[aria-pressed="true"]')?.textContent`);
    if (pressed !== "Person") throw new Error("Dr. should pre-select Person, got " + pressed);
  });
  await check("entity-saved", async () => {
    await b.clickText("#modal-foot .btn", "Save");
    await b.waitFor(`!${visible("#modal")}`, "form closed");
    await b.waitFor(`document.querySelector("#count-people").textContent === "1"`, "one entity");
    await b.waitFor(`document.querySelector(".hl-party")`, "highlight drawn");
  });
  await check("second-entity", async () => {
    await b.selectInNote("Northstar Orthopedics", 0);
    await b.key("1");
    await b.waitFor(visible("#modal"), "form");
    const pressed = await b.eval(`document.querySelector('#modal-body .choice[aria-pressed="true"]')?.textContent`);
    if (pressed !== "Organization") throw new Error("Orthopedics should pre-select Organization, got " + pressed);
    await b.key("Enter");
    await b.waitFor(`document.querySelector("#count-people").textContent === "2"`, "two entities");
  });
  await check("pronoun-mention-form", async () => {
    await b.selectInNote("She", 0);
    await b.key("2");
    await b.waitFor(visible("#modal"), "mention form");
    const form = await b.eval(`Array.from(document.querySelectorAll('#modal-body .choices .choice')).find(c => c.getAttribute("aria-pressed") === "true")?.textContent`);
    if (form !== "Pronoun") throw new Error("She should pre-select Pronoun, got " + form);
    const who = await b.eval(`document.querySelector('#modal-body .pick[aria-pressed="true"]')?.textContent || ""`);
    if (!who.includes("Ada")) throw new Error("nearest person before 'She' should be suggested, got " + who);
  });
  await check("pronoun-saved", async () => {
    await b.clickText("#modal-foot .btn", "Save");
    await b.waitFor(`document.querySelector("#count-records").textContent === "3"`, "three records");
  });
  await check("detail-form-guesses-TIN", async () => {
    await b.selectInNote("001234567", 0);
    await b.key("3");
    await b.waitFor(visible("#modal"), "detail form");
    const kind = await b.eval(`Array.from(document.querySelectorAll('#modal-body .choice')).find(c => c.getAttribute("aria-pressed") === "true" && c.textContent.includes("TIN"))?.textContent || ""`);
    if (!kind) throw new Error("9 digits should pre-select TIN");
    const value = await b.eval(`document.querySelector('#modal-body input[type=text]').value`);
    if (value !== "001234567") throw new Error("value should keep leading zeros, got " + value);
  });
  await check("detail-needs-right-owner", async () => {
    await b.clickText("#modal-body .pick", "E2", "Northstar");
    await b.clickText("#modal-foot .btn", "Save");
    await b.waitFor(`document.querySelector("#count-records").textContent === "4"`, "detail saved");
    const facts = await b.eval(`document.querySelector("#tab-people").textContent`);
    if (!facts.includes("001234567")) throw new Error("detail not shown under Northstar");
  });
  await check("validation-message", async () => {
    await b.selectInNote("they", 0);
    await b.key("6");
    await b.waitFor(visible("#modal"), "unclear form");
    await b.clickText("#modal-foot .btn", "Save");
    const err = await b.eval(`document.querySelector("#modal-body .problem:not([hidden])")?.textContent || ""`);
    if (!err.includes("why")) throw new Error("missing reason should be explained, got: " + err);
    await b.clickText("#modal-body .choice", "The note doesn’t say who");
    await b.clickText("#modal-foot .btn", "Save");
    await b.waitFor(`document.querySelector("#count-records").textContent === "5"`, "unclear saved");
  });
  await check("escape-closes-and-clears", async () => {
    await b.selectInNote("orthopedic surgeon", 0);
    await b.waitFor(visible("#action-menu"), "menu");
    await b.key("Escape");
    await b.waitFor(`!${visible("#action-menu")}`, "menu closed by Escape");
  });

  // ---- AI drafts ----
  await check("ai-modal", async () => {
    await b.click("#btn-ai", "Get AI drafts");
    await b.waitFor(visible("#modal"), "AI modal");
    await b.clickText("#modal-body .btn", "Copy for Copilot");
    await b.waitFor(`document.querySelector("#modal-body .help")?.textContent.includes("Copied") || document.querySelector("#modal-body .help")?.textContent.includes("Couldn't")`, "copy feedback");
    const clip = (await b.eval(`navigator.clipboard.readText().catch(() => "")`)).replace(/\r\n/g, "\n");
    if (clip && !clip.includes("KNOWN:\nE1 | Dr. Ada Monroe | person")) throw new Error("copied message should list recorded people; got: " + JSON.stringify(clip.slice(0, 160)));
  });
  await check("ai-preview", async () => {
    const reply = readFileSync(join(ROOT, "tests", "ai_samples", "practice_n01.reply.txt"), "utf8");
    await b.eval(`(() => { const t = document.querySelector("#modal-body textarea.paste"); t.value = ${JSON.stringify("Sure, here you go:\n" + reply)}; t.dispatchEvent(new Event("input", {bubbles: true})); })()`);
    await b.waitFor(`document.querySelector("#modal-body .report .num-chip.ok")`, "preview report");
    const report = await b.eval(text("#modal-body .report"));
    if (!/already recorded/.test(report)) throw new Error("drafts matching my own records should show as already recorded: " + report);
  });
  await check("ai-imported-review-starts", async () => {
    await b.clickText("#modal-foot .btn", "Add");
    await b.waitFor(`document.querySelector(".draft-card")`, "draft card");
    await b.waitFor(`document.querySelector(".hl-draft-current")`, "current draft highlighted");
  });
  await check("review-all-drafts-with-keyboard", async () => {
    for (let i = 0; i < 30; i++) {
      const pending = Number(await b.eval(text("#count-drafts")));
      if (!pending) break;
      const card = await b.eval(`document.querySelector(".draft-card")?.textContent || ""`);
      await b.key("a");
      await sleep(350);
      const err = await b.eval(`document.querySelector(".draft-card .problem:not([hidden])")?.textContent || ""`);
      if (err && Number(await b.eval(text("#count-drafts"))) === pending) throw new Error(`accept failed on "${card.slice(0, 80)}": ${err}`);
    }
    if ((await b.eval(text("#count-drafts"))) !== "0") throw new Error("drafts left");
  });
  await check("records-after-review", async () => {
    await b.click('#panel-tabs [data-tab="records"]', "Records tab");
    const n = Number(await b.eval(text("#count-records")));
    if (n < 18) throw new Error("expected most practice records after review, got " + n);
  });

  // ---- completion and comparison ----
  await check("complete-note", async () => {
    await b.click("#btn-complete", "Mark note complete");
    await b.waitFor(visible("#modal"), "completion dialog");
    const disabled = await b.eval(`Array.from(document.querySelectorAll("#modal-foot .btn")).find(x => x.textContent === "Mark complete").disabled`);
    if (!disabled) throw new Error("completion must require the attestation tick");
    await b.click("#attest", "attestation");
    await b.clickText("#modal-foot .btn", "Mark complete");
    await b.waitFor(`document.querySelector("#note-status").textContent === "Complete"`, "complete");
  });
  await check("claim-dossier-before-firm-output", async () => {
    await b.clickText(".claim-action", "Review claim evidence");
    await b.waitFor(visible("#view-review"), "claim review");
    if (!(await b.eval(`document.querySelector('#freeze-review').disabled`))) throw new Error("unreviewed entities must block freeze");
    const gate = await b.eval(`fetch('/api/compare?claim=PRACTICE&reviewer=Pat%20Reviewer').then(r=>r.status)`);
    if (gate !== 400) throw new Error("firm output visible before review");
  });
  await check("dossier-source-navigation-and-save", async () => {
    await b.eval(`(() => {const s=document.querySelector('#category-status');s.value='assigned';s.dispatchEvent(new Event('change'));})()`);
    await b.eval(`(() => {const s=document.querySelector('#category-value');s.value='medical provider';s.dispatchEvent(new Event('change'));})()`);
    await b.fill("#category-rationale", "The note identifies her as an orthopedic surgeon.");
    await b.clickText(".evidence-quote", "“orthopedic surgeon”");
    await b.waitFor(visible("#modal"), "source passage");
    if (!(await b.eval(`document.querySelector('.source-passage mark').textContent.includes('orthopedic surgeon')`))) throw new Error("wrong source highlight");
    await b.clickText("#modal-foot .btn", "Back to dossier");
    if (!(await b.eval(`document.querySelector('#category-rationale').value.includes('orthopedic surgeon')`))) throw new Error("source navigation lost draft");
    await b.eval(`(() => {const card=Array.from(document.querySelectorAll('.evidence-card')).find(c=>c.querySelector('.evidence-quote').textContent==='“orthopedic surgeon”'); const s=card.querySelector('select');s.value='supports';s.dispatchEvent(new Event('change'));})()`);
    await b.click("#category-save");
    await b.waitFor(`document.querySelector('#category-progress').textContent.startsWith('1 of 2')`, "first entity reviewed");
  });
  await check("second-dossier-category-and-unsaved-freeze-gate", async () => {
    await b.clickText(".dossier-nav button", "E2");
    await b.eval(`(() => {const s=document.querySelector('#category-status');s.value='assigned';s.dispatchEvent(new Event('change'));const c=document.querySelector('#category-value');c.value='medical provider';c.dispatchEvent(new Event('change'));})()`);
    await b.fill("#category-rationale", "The clinic is explicitly the medical provider.");
    await b.eval(`(() => {const card=Array.from(document.querySelectorAll('.evidence-card')).find(c=>c.querySelector('.evidence-quote').textContent==='“the medical provider”'); const s=card.querySelector('select');s.value='supports';s.dispatchEvent(new Event('change'));})()`);
    await b.click("#category-save");
    await b.waitFor(`document.querySelector('#category-progress').textContent.startsWith('2 of 2')`, "both entities reviewed");
    await b.fill("#category-rationale", "Unsaved change");
    if (!(await b.eval(`document.querySelector('#freeze-review').disabled`))) throw new Error("unsaved review must block freeze");
    await b.clickText(".category-form button", "Discard unsaved edits");
  });
  await check("finish-claim", async () => {
    await b.click("#freeze-review");
    await b.waitFor(visible("#modal"), "seal dialog");
    await b.click("#freeze-attest");
    await b.clickText("#modal-foot .btn", "Freeze and compare");
    await b.waitFor(visible("#view-compare"), "comparison");
    const rows = await b.eval(`document.querySelectorAll(".firm-card").length`);
    if (rows !== 3) throw new Error("practice claim has 3 firm rows, got " + rows);
  });
  await check("compare-answers", async () => {
    // The "who is this" dropdown is the first one on each card.
    const pick = async (card, label) => {
      await b.eval(`(() => { const s = document.querySelector(".firm-card:nth-of-type(${card}) select"); const o = Array.from(s.options).find(o => o.text.includes(${JSON.stringify(label)})); s.value = o.value; s.dispatchEvent(new Event("change", {bubbles: true})); })()`);
      await sleep(400);
    };
    const cited = await b.eval(`document.querySelector(".firm-card:nth-of-type(1) .firm-facts").textContent`);
    if (/object/.test(cited)) throw new Error("a note link rendered as text: " + cited);
    await pick(1, "Northstar");
    await pick(2, "Ada");
    await b.clickText(".firm-card:nth-of-type(2) .watch-box .choice", "Can't tell");
    await b.clickText(".firm-card:nth-of-type(2) .watch-box .choice", "Partly");
    await b.eval(`(() => { const t = document.querySelector(".firm-card:nth-of-type(2) textarea"); t.value = "Name matches but the note gives no identifier to confirm it."; t.dispatchEvent(new Event("blur")); })()`);
    await sleep(400);
    await pick(3, "Not in these notes");
    await b.waitFor(`document.querySelectorAll(".firm-card.done").length === 3`, "all rows done");
    // What the server stored must match what the screen shows, even after rapid clicks.
    await sleep(900);
    const saved = await b.eval(`fetch("/api/compare?claim=PRACTICE&reviewer=Pat%20Reviewer").then(r => r.json())`);
    const ada = saved.rows.find((r) => r.data.entity_name === "Dr. Ada Monroe");
    const w = ada.watchlist || {};
    if (w.decision !== "cant_tell" || w.note_supports !== "partly" || !(w.reason || "").includes("identifier"))
      throw new Error("stored watchlist answers don't match the screen: " + JSON.stringify(w));
    if (!saved.independent || saved.entities.find(e => e.label === 'Dr. Ada Monroe').decision.category !== 'medical provider') throw new Error("frozen category missing");
    const lake = saved.rows.find((r) => r.data.entity_name === "Lakeview Imaging");
    if (!(lake.pairing || {}).not_in_notes) throw new Error("'not in these notes' not stored");
  });
  await check("scores", async () => {
    await b.click("#btn-scores", "Scores");
    await b.waitFor(visible("#view-scores"), "scores view");
    await b.click("#sc-practice", "include practice");
    await b.waitFor(`document.querySelector("#view-scores > p")?.textContent.includes("Practice claim")`, "scores refreshed with the practice claim");
    const found = await b.eval(`Array.from(document.querySelectorAll(".score")).find(s => s.textContent.startsWith("Found rate"))?.querySelector(".frac").textContent`);
    if (!found.includes("2 ÷")) throw new Error("found rate should count the 2 paired entities: " + found);
  });
  await check("help", async () => {
    await b.click("#btn-help", "Help");
    await b.waitFor(visible("#modal"), "help");
    const rows = await b.eval(`document.querySelectorAll("#modal-body .guide-table tr").length`);
    if (rows !== 7) throw new Error("guide should list 6 record kinds");
    await b.key("Escape");
  });
  await check("accessible-names", async () => {
    const unnamed = await b.eval(`Array.from(document.querySelectorAll("button, input, select, textarea")).filter(e => e.offsetParent && !(e.getAttribute("aria-label") || e.textContent.trim() || e.labels?.length || e.placeholder || e.title)).map(e => e.outerHTML.slice(0, 80))`);
    if (unnamed.length) throw new Error("controls without an accessible name: " + unnamed.join(" | "));
  });
  if (b.errors.length) throw new Error("JavaScript errors: " + b.errors.join(" | "));
} catch (e) {
  if (!results.some((r) => r[0] === "FAIL")) results.push(["FAIL", "setup", e.message]);
} finally {
  if (b) await b.close();
  server.kill();
}
for (const [s, n, m] of results) console.log(`${s}  ${n}${m ? "  — " + m : ""}`);
if (b && b.errors.length) console.log("JS errors:", b.errors);
const failed = results.some((r) => r[0] === "FAIL");
if (failed) console.log("server log:\n" + serverLog.slice(-2000));
console.log(`${results.filter((r) => r[0] === "PASS").length} passed, ${results.filter((r) => r[0] === "FAIL").length} failed. Screens: ${SHOTS}`);
process.exit(failed ? 1 : 0);
