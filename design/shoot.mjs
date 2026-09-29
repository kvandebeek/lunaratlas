// Screenshots of every LunarAtlas screen and state, via the Chrome DevTools protocol (no packages: Node's WebSocket).
// LUNARATLAS_TOKEN=any-secret node shoot.mjs BASE_URL OUT_DIR WORK_FOLDER   (the app started with the same LUNARATLAS_TOKEN)
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';

const [BASE, OUT, WORK] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PROFILE = join(OUT, '..', 'chrome-profile');
rmSync(PROFILE, { recursive: true, force: true });
// The browser is driven through a pipe (--remote-debugging-pipe): unlike a debugging port, nothing else on the machine
// can attach to it while the screenshots are taken. Messages are JSON ended by a NUL byte, fd 3 in and fd 4 out.
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-pipe', `--user-data-dir=${PROFILE}`, '--no-first-run',
  '--hide-scrollbars', '--force-color-profile=srgb', '--window-size=1440,900', 'about:blank'], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let seq = 0, session;
const pending = new Map(), listeners = [];
function receive(d) {
  if (d.id && pending.has(d.id)) { const { res, rej } = pending.get(d.id); pending.delete(d.id); d.error ? rej(new Error(d.error.message)) : res(d.result); }
  else if (!d.sessionId || d.sessionId === session) for (const l of listeners) l(d);
}
let buf = '';
chrome.stdio[4].setEncoding('utf8');
chrome.stdio[4].on('data', (chunk) => {
  buf += chunk;
  for (let i; (i = buf.indexOf('\0')) >= 0;) { const m = buf.slice(0, i); buf = buf.slice(i + 1); if (m) receive(JSON.parse(m)); }
});
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq;
  pending.set(id, { res, rej });
  const browserLevel = /^(Browser|Target)\./.test(method);
  chrome.stdio[3].write(JSON.stringify({ id, method, params, ...(session && !browserLevel ? { sessionId: session } : {}) }) + '\0');
});
async function connect() {
  let page;
  for (let i = 0; i < 50 && !page; i++) {
    try { page = (await send('Target.getTargets')).targetInfos.find((t) => t.type === 'page'); } catch (e) { /* not up yet */ }
    if (!page) await sleep(200);
  }
  session = (await send('Target.attachToTarget', { targetId: page.targetId, flatten: true })).sessionId;
}
const once = (method) => new Promise((r) => { const l = (d) => { if (d.method === method) { listeners.splice(listeners.indexOf(l), 1); r(d.params); } }; listeners.push(l); });
async function js(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(expr.slice(0, 80) + ': ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
}
async function go(path, wait = 1500) { const l = once('Page.loadEventFired'); await send('Page.navigate', { url: BASE + path }); await l; await sleep(wait); }
async function size(w, h) { await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 2, mobile: false }); }
const shots = [];
async function shot(name, note) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, name + '.png'), Buffer.from(data, 'base64'));
  shots.push([name, note]); console.log('shot', name);
}
async function mouse(type, x, y, extra = {}) { await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1, buttons: type === 'mouseReleased' ? 0 : 1, ...extra }); }
async function hover(x, y) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 }); }
async function click(x, y) { await hover(x, y); await mouse('mousePressed', x, y); await mouse('mouseReleased', x, y); }
async function drag(x0, y0, x1, y1) {
  await hover(x0, y0); await mouse('mousePressed', x0, y0);
  for (let i = 1; i <= 8; i++) await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x0 + (x1 - x0) * i / 8, y: y0 + (y1 - y0) * i / 8, button: 'left', buttons: 1 });
  await mouse('mouseReleased', x1, y1);
}
async function key(k, code, vk) {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk, text: k.length === 1 ? k : undefined });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk });
}
const rect = (sel) => js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, l: r.left, t: r.top, w: r.width, h: r.height }; })()`);

async function openImage(name) {
  await go('/app', 800);
  await js(`fetch('/app/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: ${JSON.stringify(join(WORK, name))} }) }).then((r) => r.json())`);
  for (let i = 0; i < 240; i++) {
    const s = await js(`fetch('/app/status').then((r) => r.json())`);
    if (s.phase === 'ready') break;
    if (s.phase === 'failed') throw new Error(s.error);
    await sleep(500);
  }
  await go('/', 3500);
}

// a realistic locate log (lines as the tools print them)
const L1 = ['positioning 2026-09-27-2040_2-Moon__lapl4_ap5501.tif', 'locating 2026-09-27-2040_2-Moon__lapl4_ap5501.tif',
  'quality OK (provisional limits) · limb 6.5 px (4.31 km) · grain 0.2 % · clipped 0.00 %', 'limb: centre 2311 1768 px, radius 1583 px',
  'downloading the IAU nomenclature (≈ 24 MB, once)', '  downloaded 24.3 of 24.3 MB',
  'downloading reference tile E300N3150 (≈ 22 MB, once)', '  downloaded 22.1 of 22.1 MB',
  'downloading reference tile E300N0450 (≈ 22 MB, once)', '  downloaded 9.4 of 22.1 MB'];
const L2 = ['positioning 2026-09-27-2040_2-Moon__lapl4_ap5501.tif', 'locating 2026-09-27-2040_2-Moon__lapl4_ap5501.tif',
  'quality OK (provisional limits) · limb 6.5 px (4.31 km) · grain 0.2 % · clipped 0.00 %', 'limb: centre 2311 1768 px, radius 1583 px',
  'orientation: north 184.2°, not mirrored', '  reference: LOLA relief lit from the subsolar point +1.2° -38.5°'];
const sim = (lines, secs) => `(() => { working('Finding where this is on the Moon'); t0 = Date.now() - ${secs * 1000}; st.since = Date.now() - 4000;
  const lines = ${JSON.stringify(lines)}; $('#log').textContent = lines.join('\\n'); const b = st.i; readLines(lines); const i = st.i; st.i = b; toStage(i); st.since = Date.now() - 5000; tick(); renderStages(); })()`;

try {
  await connect();
  await send('Page.enable'); await send('Runtime.enable');
  await size(1440, 900);
  await go(`/?t=${process.env.LUNARATLAS_TOKEN}`, 300);       // the launcher wants its token: the app was started with this one

  // ---------------- home
  await go('/app', 2500);
  await shot('01-home', 'Home: hero (icon, name, tagline), drop zone with drawn crescent + grid, earlier photos with thumbnail, capture time, solve status, Open button');
  await key('Tab', 'Tab', 9); await sleep(300);
  await shot('02-home-drop-focus', 'Drop zone with keyboard focus (amber focus ring)');
  await js(`document.activeElement.blur(); document.querySelector('#drop').classList.add('over')`); await sleep(300);
  await shot('03-home-drag-over', 'Drag-over state: solid amber border, amber tint, "Release to open this photo"');
  await js(`document.querySelector('#drop').classList.remove('over')`);
  const row = await rect('#recent li:nth-child(3)'); await hover(row.x, row.y); await sleep(300);
  await shot('04-home-row-hover', 'Earlier photos: row hover (whole row is clickable; explicit Open button kept)');
  await hover(5, 5);
  await js(`choose(new File([new Uint8Array(35013686)], 'moon-closeup.tif'))`); await sleep(400);
  await shot('05-home-photo-chosen', 'A photo chosen without a time stamp in its name: asks when it was taken');

  // ---------------- progress (states driven with a realistic log; the page code is the real one)
  await js(sim(L1, 38)); await sleep(700);
  await shot('06-progress-downloading', 'Progress, first run: named stages; "Downloading Moon maps" shows real MB (per file and in total)');
  await js(sim(L2, 14)); await sleep(700);
  await shot('07-progress-searching', 'Progress, later runs: the download stage is skipped ("already on this computer")');
  await js(`document.querySelector('details.log').open = true; document.querySelector('#log').scrollTop = 0`); await sleep(300);
  await shot('08-progress-details-open', 'Details (the raw log) expanded: monospace, Copy button');
  await js(`document.querySelector('details.log').open = false; fail('not annotated: too blurry: the limb is 16.6 px wide, 10.7 km (limit 16.0 px); too noisy: 2.1 % grain in flat maria (limit 1.5 %)', true)`); await sleep(500);
  await shot('09-progress-quality-refused', 'Quality refused: plain-language reasons (raw measurement below each), "Name it anyway"');
  await js(sim(L2, 3)); await js(`fail('close-up not found: the best position had 4 terrain matches')`); await sleep(500);
  await shot('10-progress-error', 'Failure: plain-language title and advice; raw text stays in Details');

  // ---------------- viewer
  await openImage('2026-09-27-2040_2-Moon__lapl4_ap5501.tif');
  await hover(760, 470); await sleep(500);
  await shot('11-viewer', 'Viewer: brand icon in the top bar, tool rail in groups, Layers panel with amber switches and right-aligned counts, split status bar (cursor lat/lon + km/px | zoom, Fit, 1:1, Export)');
  await js(`document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', bubbles: true }))`); await sleep(800);
  await shot('12-viewer-grid', 'Lat/lon grid in cyan; degree labels only where they collide with no name and no other label');
  const t = await rect('#tools button[data-tool="measure"]'); await hover(t.x, t.y); await sleep(400);
  await shot('13-viewer-tool-tooltip', 'Tool rail tooltip: tool name + shortcut; active tool = amber fill + side marker');
  await hover(760, 470);
  // zoom in around a busy area
  await js(`(() => { const P = window.__atlas.placed, inside = (p) => p.f.x > 0.25 * ATLAS.width && p.f.x < 0.75 * ATLAS.width && p.f.y > 0.25 * ATLAS.height && p.f.y < 0.75 * ATLAS.height;
    const c = P.filter((p) => p.f.c === 'crater' && inside(p)).sort((a, b) => b.f.d - a.f.d)[0] || P[0];
    const v = window.__atlas.view; v.x = c.f.x; v.y = c.f.y; v.s = v.s * 2.2; window.__atlas.render(); })()`); await sleep(1200);
  await js(`window.__atlas.render()`); await sleep(400);
  await shot('14-viewer-zoomed-labels', 'Zoomed in: names placed by priority (type, then size), colliding lower-priority names hidden; they fade in as you zoom');
  const lab = await js(`(() => { const p = window.__atlas.placed.find((p) => p.f.c === 'crater' && p.x > 400 && p.x < 1000 && p.y > 250 && p.y < 650); return p && { x: p.x, y: p.y }; })()`);
  if (lab) { await click(lab.x, lab.y); await sleep(700); await shot('15-viewer-feature-card', 'A name selected: amber crater outline, info card'); }
  await key('Escape', 'Escape', 27); await sleep(300);
  // an arrow with its popover
  await key('a', 'KeyA', 65); await sleep(200);
  await drag(640, 560, 760, 430); await sleep(700);
  await js(`document.activeElement && document.activeElement.blur()`); await sleep(200);
  await shot('16-viewer-arrow-popover', 'Annotation popover: anchored beside the arrow with a pointer, never over it; suggested names as chips');
  await js(`document.querySelector('#aOk').click()`); await sleep(200);
  await key('v', 'KeyV', 86);
  // the fixes: a dashed arrow keeps a solid head, a moved name keeps its line, lettered craters follow the craters
  await js(`(() => { const s = window.__atlas.edits.shapes.at(-1); s.dash = true; window.__atlas.render(); })()`); await sleep(300);
  const mv = await js(`(() => { const p = window.__atlas.placed.find((p) => p.f.c === 'crater' && p.x > 300 && p.x < 1000 && p.y > 200 && p.y < 700 && Math.hypot(p.x - 700, p.y - 495) > 120); return p && { x: p.x, y: p.y }; })()`);
  if (mv) { await drag(mv.x, mv.y, mv.x + 110, mv.y + 80); await hover(1100, 820); await sleep(500); }
  await shot('25-viewer-moved-name-dashed-arrow', 'A moved name keeps a thin dashed line to its feature; a dashed arrow keeps a solid head');
  const cr = await rect('#l-crater + span'); await click(cr.x, cr.y); await hover(1100, 820); await sleep(600);
  await shot('26-viewer-craters-off', 'Craters off: the "Lettered craters" switch is greyed out and keeps its own setting');
  await click(cr.x, cr.y); await sleep(300);
  await js(`document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', bubbles: true }))`); await sleep(1200);
  const ex = await rect('#exportBtn'); await click(ex.x, ex.y); await sleep(1800);
  await shot('17-export-dialog', 'Export dialog: tokens, selected cards = amber border on lighter navy, live preview thumbnail of the output');
  const opt = await rect('.opt:nth-child(2) span'); await hover(opt.x, opt.y); await sleep(300);
  await shot('18-export-dialog-hover', 'Export dialog: hover on an unselected card');
  await js(`document.querySelector('[name=reg][value=view]').click()`); await sleep(1200);
  await shot('19-export-dialog-view-region', 'Export dialog: "Current view" chosen, the preview follows');

  // the photo that was named anyway: the quality chip
  await openImage('2026-09-27-2030_3-Moon__lapl4_ap3078.tif');
  await hover(760, 470); await sleep(400);
  await shot('20-viewer-quality-chip', 'A photo named despite the quality check: amber warning chip in the status bar instead of raw text');
  const g = await rect('#gate'); await click(g.x, g.y); await sleep(500);
  console.log('quality popover hidden after click:', await js(`document.querySelector('#gatePop').hidden`));
  await shot('21-viewer-quality-popover', 'Quality chip opened: friendly explanation, the raw measurement underneath');
  await key('Escape', 'Escape', 27);

  // ---------------- narrow window
  await size(960, 680); await go('/', 3000); await hover(480, 340); await sleep(400);
  await shot('22-viewer-narrow', 'Viewer at 960 × 680');
  await go('/app', 2000);
  await shot('23-home-narrow', 'Home at 960 × 680');
  await size(420, 860); await go('/app', 2000);
  await shot('24-home-phone-width', 'Home at 420 px wide (drop zone stacks)');
  writeFileSync(join(OUT, 'shots.json'), JSON.stringify(shots, null, 1));
} catch (e) {
  console.error('FAILED', e);
  process.exitCode = 1;
} finally {
  try { await send('Browser.close'); } catch (e) { /* gone */ }
  chrome.kill();
}
