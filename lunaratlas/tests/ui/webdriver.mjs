// The same user at the keyboard and mouse as cdp.mjs, for the browsers that have no Chrome DevTools protocol: Firefox
// (geckodriver) and Safari (safaridriver), through the W3C WebDriver protocol (no packages: Node's own fetch).
// Clicks, drags, the wheel and keys go through WebDriver's input actions, so they are trusted and hit-tested like a
// user's. The page-level helpers (target, click, hover, until, text, visible, choose) are cdp.mjs's own.
//
// What WebDriver cannot do, and what stands in for it:
//   - console errors and uncaught exceptions: a hook in the page records them (each script call installs it and
//     collects what it saw), so errors thrown before the first call on a freshly loaded page are not seen;
//   - alert/confirm: the hook records the message and answers them (accept);
//   - the OS file chooser: the hook stops it from opening and remembers its <input>; the files are then given to the
//     page as a user's choice gives them (File objects with name, type, size and contents); dropped files likewise;
//   - the time zone and clipboard permissions: setTimezone throws, grantClipboard does nothing.
import { spawn } from 'node:child_process';
import { openSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { basename, extname, join } from 'node:path';
import { Browser, sleep } from './cdp.mjs';

const KEYS = {
  Enter: '', Escape: '', Delete: '', Backspace: '', Tab: '', ArrowDown: '',
  ArrowUp: '', ArrowLeft: '', ArrowRight: '', Home: '', End: '',
};
const MODS = { shift: '', ctrl: '', alt: '', meta: '' };
const TYPES = { '.tif': 'image/tiff', '.tiff': 'image/tiff', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.txt': 'text/plain' };

const CAPS = {
  firefox: { browserName: 'firefox', 'moz:firefoxOptions': { args: process.env.LUNARATLAS_HEADLESS === '0' ? [] : ['-headless'] } },
  // Safari has no headless mode: it opens a real window (remote automation enabled once: sudo safaridriver --enable)
  safari: { browserName: 'safari' },
};
const DRIVER_ARGS = { firefox: (port) => ['--port', String(port)], safari: (port) => ['-p', String(port)] };

// installed by every script call, once per page
const HOOK = `if (!window.__wd) {
  const w = window.__wd = { errors: [], dialogs: [], chooser: null };
  addEventListener('error', (e) => w.errors.push('exception: ' + ((e.error && e.error.stack) || e.message)));
  addEventListener('unhandledrejection', (e) => w.errors.push('exception: ' + ((e.reason && e.reason.stack) || e.reason)));
  const ce = console.error.bind(console);
  console.error = (...a) => { w.errors.push('console.error: ' + a.map(String).join(' ')); ce(...a); };
  const say = (v) => (m) => { w.dialogs.push(String(m)); return v; };
  window.alert = say(undefined); window.confirm = say(true); window.prompt = say('');
  const P = HTMLInputElement.prototype, click = P.click, showPicker = P.showPicker;
  P.click = function () { if (this.type === 'file') { w.chooser = this; return; } return click.call(this); };
  if (showPicker) P.showPicker = function () { if (this.type === 'file') { w.chooser = this; return; } return showPicker.call(this); };
  document.addEventListener('click', (e) => {
    const t = e.target, inp = t instanceof HTMLInputElement ? t : t.closest && t.closest('label') && t.closest('label').control;
    if (inp && inp.type === 'file') { e.preventDefault(); w.chooser = inp; }
  }, true);
}
const __wdDrain = () => ({ e: window.__wd.errors.splice(0), d: window.__wd.dialogs.splice(0) });`;

// files given to the page as a user's choice gives them: args[0] = [{ name, type, b64, mtime }]
const FILES = `const dt = new DataTransfer();
for (const f of args[0]) {
  const bin = atob(f.b64), a = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  dt.items.add(new File([a], f.name, { type: f.type, lastModified: f.mtime }));
}`;

function freePort() {
  return new Promise((res, rej) => {
    const s = createServer();
    s.once('error', rej);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => res(port)); });
  });
}

function fileArgs(files) {
  return files.map((p) => ({ name: basename(p), type: TYPES[extname(p).toLowerCase()] || '', b64: readFileSync(p).toString('base64'), mtime: statSync(p).mtimeMs }));
}

export class WebDriverBrowser extends Browser {
  static async launch(driver, kind, dir, { width = 1400, height = 900 } = {}) {
    if (!CAPS[kind]) throw new Error(`no WebDriver set-up for ${kind} (firefox or safari)`);
    const port = await freePort();
    const log = openSync(join(dir, `${kind}-driver.log`), 'w');
    const proc = spawn(driver, DRIVER_ARGS[kind](port), { stdio: ['ignore', log, log] });
    const b = new WebDriverBrowser(proc, `http://127.0.0.1:${port}`, width, height);
    for (let i = 0; i < 150; i++) {
      try { const r = await fetch(b.server + '/status'); if (r.ok && (await r.json()).value.ready !== false) break; }
      catch { /* not up yet */ }
      if (proc.exitCode !== null) throw new Error(`${driver} stopped (see ${kind}-driver.log)`);
      await sleep(100);
    }
    try {
      const s = await b.cmd('POST', '/session', { capabilities: { alwaysMatch: { ...CAPS[kind], unhandledPromptBehavior: 'accept' } } }, false);
      b.session = s.sessionId;
      await b.cmd('POST', '/timeouts', { script: 120000, pageLoad: 60000 });
      await b.size(width, height);
    } catch (e) { await b.close(); throw e; }
    return b;
  }

  constructor(proc, server, width, height) {
    super(proc, null, width, height);
    this.server = server; this.session = null;
  }

  async cmd(method, path, body, inSession = true) {
    const url = this.server + (inSession ? `/session/${this.session}` : '') + path;
    const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || (j.value && j.value.error)) throw new Error(`${method} ${path}: ${j.value?.error || r.status}: ${String(j.value?.message || '').split('\n')[0]}`);
    return j.value;
  }

  // the viewport (not the window) at width × height, as cdp.mjs sets it
  async size(width, height) {
    for (let i = 0; i < 4; i++) {
      const [w, h] = await this.js('[innerWidth, innerHeight]');
      if (w === width && h === height) return;
      const r = await this.cmd('GET', '/window/rect');
      await this.cmd('POST', '/window/rect', { width: r.width + width - w, height: r.height + height - h });
    }
  }

  async close() {
    if (this.session) { try { await Promise.race([this.cmd('DELETE', ''), sleep(5000)]); } catch { /* gone */ } this.session = null; }
    if (this.proc.exitCode === null) {
      const gone = new Promise((r) => this.proc.once('exit', r));
      this.proc.kill();
      await Promise.race([gone, sleep(5000)]);
    }
  }

  // ---------------------------------------------------------------- page
  // body: an async function body with args; what the page's hook saw meanwhile is collected
  async exec(body, args = []) {
    const script = `${HOOK}
const done = arguments[arguments.length - 1], args = [...arguments].slice(0, -1);
Promise.resolve().then(async () => { ${body} }).then((v) => done({ v, ...__wdDrain() }), (e) => done({ x: e ? (e.name || 'Error') + ': ' + (e.message || e) + ' | ' + (e.stack || '') : String(e), ...__wdDrain() }));`;
    const r = await this.cmd('POST', '/execute/async', { script, args });
    if (!r) return undefined;
    this.errors.push(...(r.e || []));
    this.dialogs.push(...(r.d || []));
    if ('x' in r) throw new Error(r.x);
    return r.v;
  }
  async js(expr) {
    try { return await this.exec(`return (${expr});`); }
    catch (e) { throw new Error(expr.slice(0, 100) + ': ' + e.message); }
  }
  async collect() { /* no V8 coverage outside Chrome */ }
  async goto(url, ready = 'document.readyState === "complete"') {
    await this.js('0').catch(() => {});              // what the old page's hook saw, before it is gone
    await this.cmd('POST', '/url', { url });
    await this.until(ready, 20000, `page ${url}`);
  }
  async screenshot(path) { writeFileSync(path, Buffer.from(await this.cmd('GET', '/screenshot'), 'base64')); }

  // ---------------------------------------------------------------- input
  async act(pointer, mods = []) {
    const pause = { type: 'pause', duration: 0 }, K = mods.map((m) => MODS[m]);
    const actions = [{ type: 'pointer', id: 'mouse', parameters: { pointerType: 'mouse' }, actions: [...K.map(() => pause), ...pointer, ...K.map(() => pause)] }];
    if (K.length) actions.push({ type: 'key', id: 'keyboard', actions: [...K.map((value) => ({ type: 'keyDown', value })), ...pointer.map(() => pause), ...K.map((value) => ({ type: 'keyUp', value }))] });
    await this.cmd('POST', '/actions', { actions });
  }
  at(x, y, duration = 0) {
    return { type: 'pointerMove', origin: 'viewport', duration, x: Math.max(0, Math.min(this.width - 1, Math.round(x))), y: Math.max(0, Math.min(this.height - 1, Math.round(y))) };
  }
  async move(x, y) { await this.act([this.at(x, y)]); }
  async clickAt(x, y, { mods = [], count = 1 } = {}) {
    const clicks = [];
    for (let c = 0; c < count; c++) clicks.push({ type: 'pointerDown', button: 0 }, { type: 'pointerUp', button: 0 });
    await this.act([this.at(x, y), ...clicks], mods);
    await sleep(60);
  }
  async drag(x0, y0, x1, y1, { mods = [], steps = 8 } = {}) {
    const moves = [];
    for (let i = 1; i <= steps; i++) moves.push(this.at(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, 16));
    await this.act([this.at(x0, y0), { type: 'pointerDown', button: 0 }, ...moves, { type: 'pointerUp', button: 0 }], mods);
    await sleep(80);
  }
  async wheel(x, y, deltaY) {
    await this.move(x, y);
    const { x: rx, y: ry } = this.at(x, y);
    try {
      await this.cmd('POST', '/actions', { actions: [{ type: 'wheel', id: 'wheel', actions: [{ type: 'scroll', origin: 'viewport', x: rx, y: ry, deltaX: 0, deltaY, duration: 0 }] }] });
    } catch {                                          // a driver without wheel actions: the event the page listens to
      await this.exec(`document.elementFromPoint(args[0], args[1]).dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: args[0], clientY: args[1], deltaY: args[2], deltaMode: 0 }));`, [rx, ry, deltaY]);
    }
    await sleep(80);
  }
  async press(key, mods = []) {
    const K = mods.map((m) => MODS[m]), value = KEYS[key] || key;
    await this.cmd('POST', '/actions', { actions: [{ type: 'key', id: 'keyboard', actions: [
      ...K.map((v) => ({ type: 'keyDown', value: v })), { type: 'keyDown', value }, { type: 'keyUp', value }, ...K.reverse().map((v) => ({ type: 'keyUp', value: v }))] }] });
    await sleep(40);
  }
  async type(text) {
    const actions = [];
    for (const ch of text) actions.push({ type: 'keyDown', value: ch }, { type: 'keyUp', value: ch });
    await this.cmd('POST', '/actions', { actions: [{ type: 'key', id: 'keyboard', actions }] });
    await sleep(60);
  }

  // ---------------------------------------------------------------- files
  async answerChooser(files, ms = 3000) {
    try { await this.until('!!(window.__wd && window.__wd.chooser)', ms, 'a file chooser'); } catch { return false; }
    const given = await this.exec(`const inp = window.__wd.chooser; window.__wd.chooser = null; ${FILES}
      inp.files = dt.files; inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true })); return true;`, [fileArgs(files)]);
    await sleep(150);
    return given;
  }
  async dropFile(x, y, files) {
    await this.exec(`const el = document.elementFromPoint(args[1], args[2]); ${FILES}
      for (const type of ['dragenter', 'dragover', 'drop']) {
        el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, clientX: args[1], clientY: args[2], dataTransfer: dt }));
        await new Promise((r) => setTimeout(r, 60));
      }`, [fileArgs(files), x, y]);
  }

  // ---------------------------------------------------------------- the browser's surroundings
  async setTimezone() { throw new Error('WebDriver cannot set the page\'s time zone'); }
  async grantClipboard() { /* WebDriver has no permissions call that Firefox and Safari both take */ }
}
