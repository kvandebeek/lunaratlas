// A user at the keyboard and mouse, through the Chrome DevTools protocol (no packages: Node's own WebSocket).
// Input goes through Chrome's input pipeline (Input.dispatch*), so events are trusted and hit-tested like a real
// click: a button under a panel, a zero-size control or a disabled one fails instead of "working".
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MOD = { alt: 1, ctrl: 2, meta: 4, shift: 8 };
// the platform's own shortcut key, as a user presses it
export const CMD = process.platform === 'darwin' ? 'meta' : 'ctrl';

const KEYS = {
  Enter: [13, 'Enter', '\r'], Escape: [27, 'Escape'], Delete: [46, 'Delete'], Backspace: [8, 'Backspace'],
  Tab: [9, 'Tab'], ArrowDown: [40, 'ArrowDown'], ArrowUp: [38, 'ArrowUp'], ArrowLeft: [37, 'ArrowLeft'],
  ArrowRight: [39, 'ArrowRight'], Home: [36, 'Home'], End: [35, 'End'], ' ': [32, 'Space', ' '],
  '=': [187, 'Equal', '='], '+': [187, 'Equal', '+'], '-': [189, 'Minus', '-'], '/': [191, 'Slash', '/'],
};
function keyInfo(k) {
  if (KEYS[k]) { const [vk, code, text] = KEYS[k]; return { vk, code, text }; }
  if (/^[a-z]$/i.test(k)) return { vk: k.toUpperCase().charCodeAt(0), code: 'Key' + k.toUpperCase(), text: k };
  if (/^\d$/.test(k)) return { vk: k.charCodeAt(0), code: 'Digit' + k, text: k };
  return { vk: 0, code: '', text: k };
}

export class Browser {
  static async launch(chrome, dir, { width = 1400, height = 900 } = {}) {
    const profile = join(dir, 'chrome-profile');
    rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    mkdirSync(profile, { recursive: true });
    // without the three "background" switches a headless window can count as hidden (macOS occlusion) and its
    // animation frames stop: a flight to a feature would then never arrive
    const proc = spawn(chrome, ['--headless=new', '--use-mock-keychain', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
      '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling',
      '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars', '--mute-audio',
      '--force-color-profile=srgb', '--disable-features=Translate,MediaRouter', `--window-size=${width},${height}`,
      // Edge on Linux ships without Chrome's setuid sandbox helper, so without this it never writes
      // DevToolsActivePort and exits silently; harmless here since this only ever opens our own test pages.
      ...(process.platform === 'linux' ? ['--no-sandbox'] : []),
      'about:blank'], { stdio: 'ignore' });
    const portFile = join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 150 && !existsSync(portFile); i++) await sleep(100);
    if (!existsSync(portFile)) { proc.kill(); throw new Error('Chrome did not start'); }
    const port = readFileSync(portFile, 'utf8').split('\n')[0].trim();
    let page;
    for (let i = 0; i < 50 && !page; i++) {
      try { page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page'); }
      catch { /* not up yet */ }
      if (!page) await sleep(100);
    }
    const b = new Browser(proc, page.webSocketDebuggerUrl, width, height);
    await b.open();
    return b;
  }

  constructor(proc, url, width, height) {
    Object.assign(this, { proc, url, width, height, seq: 0, pending: new Map(), listeners: [] });
    this.errors = []; this.dialogs = []; this.chooser = null; this.coverage = [];
  }

  async open() {
    this.ws = new WebSocket(this.url);
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && this.pending.has(d.id)) {
        const { res, rej } = this.pending.get(d.id); this.pending.delete(d.id);
        d.error ? rej(new Error(d.error.message)) : res(d.result);
      } else for (const l of [...this.listeners]) l(d);
    };
    this.on('Runtime.exceptionThrown', (p) => this.errors.push('exception: ' + (p.exceptionDetails.exception?.description || p.exceptionDetails.text)));
    this.on('Runtime.consoleAPICalled', (p) => { if (p.type === 'error') this.errors.push('console.error: ' + p.args.map((a) => a.value ?? a.description).join(' ')); });
    this.on('Page.javascriptDialogOpening', (p) => { this.dialogs.push(p.message); this.send('Page.handleJavaScriptDialog', { accept: true }); });
    this.on('Page.fileChooserOpened', (p) => { this.chooser = p; });
    await this.send('Page.enable'); await this.send('Runtime.enable'); await this.send('DOM.enable');
    await this.send('Page.setInterceptFileChooserDialog', { enabled: true });
    await this.send('Emulation.setDeviceMetricsOverride', { width: this.width, height: this.height, deviceScaleFactor: 1, mobile: false });
    if (process.env.LUNARATLAS_JS_COVERAGE) {        // V8 block coverage of the page's scripts (tests/ui/js_coverage.mjs)
      this.scripts = new Map();                     // scriptId -> source length: a snapshot lists only what ran since the last
      this.on('Debugger.scriptParsed', (p) => this.scripts.set(p.scriptId, p.length));
      await this.send('Debugger.enable');
      await this.send('Profiler.enable');
      await this.send('Profiler.startPreciseCoverage', { callCount: true, detailed: true });
      this.on('Page.frameRequestedNavigation', () => { this.collect(); });
    }
  }

  // the coverage so far, kept before a navigation throws the page's scripts away
  async collect() {
    if (!process.env.LUNARATLAS_JS_COVERAGE) return;
    try {
      const { result } = await this.send('Profiler.takePreciseCoverage');
      this.coverage.push(...result.filter((r) => /^http:\/\/(localhost|127\.0\.0\.1):/.test(r.url)).map(({ scriptId, url, functions }) => ({ url, length: this.scripts.get(scriptId), functions })));
    } catch { /* the page is gone */ }
  }

  send(method, params = {}) {
    return new Promise((res, rej) => { const id = ++this.seq; this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  on(method, fn) { const l = (d) => { if (d.method === method) fn(d.params); }; this.listeners.push(l); return () => this.listeners.splice(this.listeners.indexOf(l), 1); }

  async close() {
    try { await Promise.race([this.send('Browser.close'), sleep(3000)]); } catch { /* gone */ }
    try { this.ws.close(); } catch { /* gone */ }
    if (this.proc.exitCode === null) {
      const gone = new Promise((r) => this.proc.once('exit', r));
      this.proc.kill('SIGKILL');
      await Promise.race([gone, sleep(5000)]);
    }
  }

  // ---------------------------------------------------------------- page
  async js(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, userGesture: false });
    if (r.exceptionDetails) throw new Error(expr.slice(0, 100) + ': ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  // waits for this navigation itself (a reload of the same URL too), not for a page that is still the old one
  async goto(url, ready = 'document.readyState === "complete"') {
    await this.collect();
    const from = await this.js('location.href').catch(() => '');
    const inDoc = url.includes('#') && from.split('#')[0] === url.split('#')[0];
    let off;
    const arrived = new Promise((res) => { off = this.on(inDoc ? 'Page.navigatedWithinDocument' : 'Page.loadEventFired', res); });
    await this.send('Page.navigate', { url });
    await Promise.race([arrived, sleep(20000)]);
    off();
    await this.until(ready, 20000, `page ${url}`);
  }
  async until(expr, ms = 10000, what = expr) {
    const t0 = Date.now();
    let last;
    while (Date.now() - t0 < ms) {
      try { last = await this.js(expr); if (last) return last; } catch (e) { last = e.message; }
      await sleep(100);
    }
    throw new Error(`timed out waiting for ${what}${last ? ` (last: ${String(last).slice(0, 120)})` : ''}`);
  }
  text(sel) { return this.js(`(document.querySelector(${JSON.stringify(sel)})||{}).textContent||''`); }
  visible(sel) {
    return this.js(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el || el.closest('[hidden]')) return false;
      const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0; })()`);
  }
  async screenshot(path) {
    const { data } = await this.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(path, Buffer.from(data, 'base64'));
  }

  // ---------------------------------------------------------------- mouse
  // Where a user would click sel, and a check that the click would land on it (not on something covering it).
  async target(sel) {
    const r = await this.js(`(() => {
      let el = document.querySelector(${JSON.stringify(sel)});
      if (!el) return { err: 'no element ' + ${JSON.stringify(sel)} };
      const small = (e) => { const b = e.getBoundingClientRect(); return b.width < 2 || b.height < 2 || getComputedStyle(e).opacity === '0'; };
      if (el.tagName === 'INPUT' && small(el)) el = el.closest('label') || document.querySelector('label[for="' + el.id + '"]') || el;
      if (el.closest('[hidden]')) return { err: 'hidden' };
      if (el.disabled) return { err: 'disabled' };
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      const b = el.getBoundingClientRect(), s = getComputedStyle(el);
      if (b.width < 1 || b.height < 1 || s.visibility === 'hidden' || s.display === 'none') return { err: 'not visible' };
      if (s.pointerEvents === 'none') return { err: 'does not take clicks (pointer-events: none)' };
      const x = b.left + b.width / 2, y = b.top + b.height / 2, hit = document.elementFromPoint(x, y);
      const ok = hit && (hit === el || el.contains(hit) || (hit.tagName === 'LABEL' && (hit.contains(el) || hit.control === el)));
      if (!ok) { const d = hit ? hit.tagName.toLowerCase() + (hit.id ? '#' + hit.id : '') + (hit.className && typeof hit.className === 'string' ? '.' + hit.className.split(' ')[0] : '') : 'nothing';
        return { err: 'covered by ' + d }; }
      return { x, y };
    })()`);
    if (r.err) throw new Error(`cannot click ${sel}: ${r.err}`);
    return r;
  }
  async move(x, y, modifiers = 0, buttons = 0) {
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, modifiers, buttons, button: buttons ? 'left' : 'none' });
  }
  async clickAt(x, y, { mods = [], count = 1 } = {}) {
    await this.collect();                          // a click may navigate: keep what ran on this page
    const modifiers = mods.reduce((a, m) => a | MOD[m], 0);
    await this.move(x, y, modifiers);
    for (let c = 1; c <= count; c++) {
      await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: c, modifiers });
      await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: c, modifiers });
    }
    await sleep(60);
  }
  async click(sel, opts) { const { x, y } = await this.target(sel); await this.clickAt(x, y, opts); }
  async hover(sel) { const { x, y } = await this.target(sel); await this.move(x, y); await sleep(80); }
  async drag(x0, y0, x1, y1, { mods = [], steps = 8 } = {}) {
    const modifiers = mods.reduce((a, m) => a | MOD[m], 0);
    await this.move(x0, y0, modifiers);
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x0, y: y0, button: 'left', buttons: 1, clickCount: 1, modifiers });
    for (let i = 1; i <= steps; i++) { await this.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, modifiers, 1); await sleep(16); }
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x1, y: y1, button: 'left', buttons: 0, clickCount: 1, modifiers });
    await sleep(80);
  }
  async wheel(x, y, deltaY, mods = []) {
    const modifiers = mods.reduce((a, m) => a | MOD[m], 0);
    await this.move(x, y);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY, modifiers });
    await sleep(80);
  }

  // ---------------------------------------------------------------- keyboard
  async press(key, mods = []) {
    await this.collect();
    const modifiers = mods.reduce((a, m) => a | MOD[m], 0), k = keyInfo(key);
    const printable = k.text && !(modifiers & (MOD.ctrl | MOD.meta | MOD.alt));
    const base = { key, code: k.code, windowsVirtualKeyCode: k.vk, modifiers };
    // keyDown, never rawKeyDown: a raw Escape also reaches Chrome's own "stop" shortcut, after which headless Chrome
    // produces no more frames (animations stop, and mouse input is never acknowledged)
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, ...(printable ? { text: k.text, unmodifiedText: k.text } : {}) });
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
    await sleep(40);
  }
  async type(text) { for (const ch of text) { if (/^[\x20-\x7e]$/.test(ch)) await this.press(ch, /[A-Z]/.test(ch) ? ['shift'] : []); else await this.send('Input.insertText', { text: ch }); } await sleep(60); }

  // Native <select> popups and date pickers are drawn by the OS, outside the page: those two are set like a form
  // filler would, with the same events the page listens to.
  async choose(sel, value) {
    await this.target(sel);
    const ok = await this.js(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.focus();
      if (![...(el.options || [])].some((o) => o.value === ${JSON.stringify(value)}) && el.tagName === 'SELECT') return false;
      el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
    if (!ok) throw new Error(`${sel} has no option ${value}`);
  }

  // ---------------------------------------------------------------- files
  // clicking a file input's opener shows the OS file chooser; here the chooser is answered with these files
  async chooseFile(openerSel, files) {
    this.chooser = null;
    await this.click(openerSel);
    if (!(await this.answerChooser(files, 5000))) throw new Error(`clicking ${openerSel} opened no file chooser`);
  }
  // the file chooser some action opened (a key, a click by the page's own script) answered with these files
  async answerChooser(files, ms = 3000) {
    const t0 = Date.now();
    while (!this.chooser && Date.now() - t0 < ms) await sleep(50);
    if (!this.chooser) return false;
    await this.send('DOM.setFileInputFiles', { files, backendNodeId: this.chooser.backendNodeId });
    this.chooser = null;
    await sleep(150);
    return true;
  }
  async dropFile(x, y, files) {
    const data = { items: [], files, dragOperationsMask: 1 };
    for (const type of ['dragEnter', 'dragOver', 'drop']) { await this.send('Input.dispatchDragEvent', { type, x, y, data }); await sleep(60); }
  }

  // ---------------------------------------------------------------- the browser's surroundings
  setTimezone(timezoneId) { return this.send('Emulation.setTimezoneOverride', { timezoneId }); }
  grantClipboard(origin) {
    return this.send('Browser.grantPermissions', { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'], origin }).catch(() => {});
  }
}

// ---------------------------------------------------------------- journeys: PASS/FAIL lines, a screenshot per failure
// launch: (out) => a started browser; without it, Chrome (or Edge) at chrome through this file's own protocol
export async function runJourney(name, fn, { chrome, launch, out, base }) {
  mkdirSync(out, { recursive: true });
  const b = await (launch ? launch(out) : Browser.launch(chrome, out));
  let fails = 0, n = 0;
  const ok = async (cond, msg) => {
    n++;
    if (cond) { console.log('PASS ' + msg); return true; }
    fails++;
    console.log('FAIL ' + msg);
    try { const p = join(out, `${name}-fail-${fails}.png`); await b.screenshot(p); console.log('SHOT ' + p); } catch { /* no page */ }
    return false;
  };
  try {
    if (process.env.LUNARATLAS_UI_TOKEN) await b.goto(`${base}/?t=${process.env.LUNARATLAS_UI_TOKEN}`);     // the token link: the cookie
    await fn(b, ok, base);
  } catch (e) {
    // js() embeds the failed expression's own source ahead of the real reason, and that source may itself span
    // many lines: slicing by line let a multi-line expression use up the whole line budget before the actual
    // error or a stack frame ever appeared. Collapse to one line and bound by length instead.
    await ok(false, 'stopped: ' + (e.stack || e.message).replace(/\s+/g, ' ').slice(0, 300));
  }
  const errs = b.errors.filter((e) => !/Failed to load resource/.test(e));
  await ok(errs.length === 0, `no script errors on the page${errs.length ? ': ' + errs.slice(0, 5).join(' || ') : ''}`);
  if (process.env.LUNARATLAS_JS_COVERAGE) {
    await b.collect();
    mkdirSync(process.env.LUNARATLAS_JS_COVERAGE, { recursive: true });
    writeFileSync(join(process.env.LUNARATLAS_JS_COVERAGE, `${name}.json`), JSON.stringify(b.coverage));
  }
  await b.close();
  console.log(`DONE ${n} checks, ${fails} failed`);
  return fails;
}
