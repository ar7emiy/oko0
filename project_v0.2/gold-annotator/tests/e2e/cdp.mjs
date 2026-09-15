// Minimal Chrome DevTools Protocol driver using Node's built-in WebSocket and fetch.
// Real mouse clicks land at screen coordinates, so a button hidden under an overlay fails the test.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BROWSERS = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch({ width = 1440, height = 900, port = 9333 } = {}) {
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) throw new Error("No Edge or Chrome found");
  const profile = mkdtempSync(join(tmpdir(), "annot-e2e-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    `--window-size=${width},${height}`, "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"],
    { stdio: "ignore" });
  let targets = [];
  for (let i = 0; i < 60; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.some((t) => t.type === "page")) break; } catch { /* starting */ }
    await sleep(250);
  }
  const page = targets.find((t) => t.type === "page");
  if (!page) throw new Error("Browser did not start");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const pending = new Map();
  const listeners = [];
  let id = 0;
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { const { res, rej } = pending.get(msg.id); pending.delete(msg.id); msg.error ? rej(new Error(msg.error.message)) : res(msg.result); }
    else if (msg.method) listeners.forEach((l) => l(msg));
  };
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  const b = new Browser(send, listeners, proc, width, height);
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  return b;
}

class Browser {
  constructor(send, listeners, proc, width, height) {
    this.send = send; this.proc = proc; this.width = width; this.height = height;
    this.errors = [];
    listeners.push((msg) => {
      if (msg.method === "Runtime.exceptionThrown") this.errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
      if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") this.errors.push(msg.params.args.map((a) => a.value || a.description).join(" "));
    });
  }
  async goto(url) { await this.send("Page.navigate", { url }); await sleep(900); }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error("eval failed: " + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async waitFor(expr, what, timeout = 6000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) { if (await this.eval(`!!(${expr})`)) return; await sleep(80); }
    throw new Error(`Timed out waiting for: ${what || expr}`);
  }
  async rect(sel) {
    return this.eval(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null; el.scrollIntoView({block:"center"}); const r = el.getBoundingClientRect(); return {x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, h:r.height}; })()`);
  }
  // A real mouse click at the element's centre; fails if something else is on top.
  async click(sel, label) {
    const r = await this.rect(sel);
    if (!r || !r.w) throw new Error(`Not visible: ${label || sel}`);
    const top = await this.eval(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); const hit = document.elementFromPoint(${r.x}, ${r.y}); return el === hit || el.contains(hit) ? "" : (hit ? hit.outerHTML.slice(0, 120) : "nothing"); })()`);
    if (top) throw new Error(`${label || sel} is covered by: ${top}`);
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      await this.send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: "left", clickCount: 1 });
    }
    await sleep(160);
  }
  async clickText(sel, text, label) {
    const idx = await this.eval(`Array.from(document.querySelectorAll(${JSON.stringify(sel)})).findIndex(e => e.textContent.trim().startsWith(${JSON.stringify(text)}))`);
    if (idx < 0) throw new Error(`No ${sel} starting with "${text}"`);
    const marker = `e2e-${Math.random().toString(36).slice(2)}`;
    await this.eval(`document.querySelectorAll(${JSON.stringify(sel)})[${idx}].setAttribute("data-e2e", "${marker}")`);
    await this.click(`[data-e2e="${marker}"]`, label || text);
  }
  async key(key) {
    const code = key.length === 1 ? key.toUpperCase().charCodeAt(0) : { Escape: 27, Enter: 13, ArrowRight: 39, ArrowLeft: 37 }[key];
    await this.send("Input.dispatchKeyEvent", { type: "keyDown", key, windowsVirtualKeyCode: code, text: key.length === 1 ? key : undefined });
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: code });
    await sleep(160);
  }
  async type(text) { await this.send("Input.insertText", { text }); await sleep(80); }
  async fill(sel, text) {
    await this.eval(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.focus(); el.value = ""; })()`);
    await this.type(text);
    await this.eval(`document.querySelector(${JSON.stringify(sel)}).dispatchEvent(new Event("input", {bubbles:true}))`);
  }
  // Select the nth occurrence of `text` in the note with the real selection API, then release the mouse there.
  async selectInNote(text, occurrence = 0) {
    const r = await this.eval(`(() => {
      const root = document.querySelector("#note-text"); const full = root.textContent; let idx = -1;
      for (let i = 0; i <= ${occurrence}; i++) { idx = full.indexOf(${JSON.stringify(text)}, idx + 1); if (idx < 0) return null; }
      const end = idx + ${text.length}; const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let pos = 0, n, sN, sO, eN, eO;
      while ((n = w.nextNode())) { const L = n.data.length; if (!sN && idx < pos + L) { sN = n; sO = idx - pos; } if (sN && end <= pos + L) { eN = n; eO = end - pos; break; } pos += L; }
      const range = document.createRange(); range.setStart(sN, sO); range.setEnd(eN, eO);
      sN.parentElement.scrollIntoView({block: "center"});
      const s = getSelection(); s.removeAllRanges(); s.addRange(range);
      const b = range.getBoundingClientRect(); return {x: b.right - 2, y: b.top + b.height / 2};
    })()`);
    if (!r) throw new Error(`"${text}" (occurrence ${occurrence + 1}) not in the note`);
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: r.x, y: r.y, button: "left", clickCount: 1 });
    await sleep(200);
  }
  async shot(path) {
    const { data } = await this.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(path, Buffer.from(data, "base64"));
  }
  async close() { try { await this.send("Browser.close"); } catch { /* gone */ } this.proc.kill(); }
}
