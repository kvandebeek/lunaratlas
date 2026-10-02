// Real user journeys through the LunarAtlas pages: mouse and keyboard through the browser's input pipeline.
//   node journeys.mjs JOURNEY BASE_URL OUT_DIR [ARGS_JSON]
//   Chrome or Edge: LUNARATLAS_CHROME (cdp.mjs); Firefox or Safari: LUNARATLAS_WEBDRIVER and LUNARATLAS_BROWSER (webdriver.mjs)
// Prints PASS/FAIL lines and DONE; exit status 1 on any failure. Run from tests/test_ui.py, which starts the server
// with a synthetic Moon and checks the files on disk afterwards.
import { runJourney, sleep, CMD } from './cdp.mjs';
import { WebDriverBrowser } from './webdriver.mjs';

const [name, BASE, OUT, ARGS] = process.argv.slice(2);
const args = ARGS ? JSON.parse(ARGS) : {};

// ---------------------------------------------------------------- viewer helpers
const ready = 'window.__atlas && __atlas.placed.length > 20';
const edits = (b) => b.js(`fetch('/edits').then((r) => r.json())`);
async function serverHas(b, pred, what, ms = 5000) {          // the sidecar on the server, after the page's save
  const t0 = Date.now(); let e;
  while (Date.now() - t0 < ms) { e = await edits(b); try { if (pred(e)) return e; } catch { /* not yet */ } await sleep(150); }
  throw new Error(`the server never had ${what}: ${JSON.stringify(e).slice(0, 300)}`);
}
// screen position of an image point, and of the disk centre
const scr = (b, x, y) => b.js(`(() => { const v = __atlas.view; return [(${x} - v.x) * v.s + innerWidth / 2, (${y} - v.y) * v.s + innerHeight / 2]; })()`);
const centre = (b) => b.js(`(() => { const v = __atlas.view, t = ATLAS.geometry.t; return [(t[0] - v.x) * v.s + innerWidth / 2, (t[1] - v.y) * v.s + innerHeight / 2, ATLAS.radius_px * v.s]; })()`);
const onCanvas = (b, x, y) => b.js(`document.elementFromPoint(${x}, ${y}) === document.getElementById('map')`);
const toast = (b) => b.text('#toast');
// this export's own "Written"/"failed" message: the dialog's button comes back and the toast names this format
async function exported(b, ext) {
  await b.until(`!document.getElementById('xGo').disabled && /(Written: .*\\.${ext}\\b|failed)/.test(document.getElementById('toast').textContent)`, 180000, `the ${ext} export`);
  return toast(b);
}
// a spot on the dark backdrop beside the export dialog, where a user clicks to dismiss it
const besideDialog = (b) => b.js(`(() => { const r = document.querySelector('#export .dialog').getBoundingClientRect();
  const x = r.left > 60 ? r.left / 2 : (r.right + innerWidth) / 2, y = r.top + 20;
  return document.elementFromPoint(x, y) === document.getElementById('export') ? [x, y] : null; })()`);
async function toastSays(b, re, ms = 4000) {
  await b.until(`/${re.source}/.test(document.getElementById('toast').textContent) && document.getElementById('toast').classList.contains('show')`, ms, `a toast matching ${re}`);
  return toast(b);
}
// a placed name of this class away from the panels, as a user would pick one to click
const labelAway = (b, cls = 'crater') => b.js(`(() => {
  __atlas.render();
  const busy = [...document.querySelectorAll('.panel, .popover')].filter((e) => !e.hidden).map((e) => e.getBoundingClientRect());
  const p = __atlas.placed.find((q) => q.f.c === '${cls}' && q.x > 140 && q.x < innerWidth - 420 && q.y > 120 && q.y < innerHeight - 140
    && document.elementFromPoint(q.x, q.y) === document.getElementById('map')
    && !busy.some((r) => q.x > r.left - 20 && q.x < r.right + 20 && q.y > r.top - 20 && q.y < r.bottom + 20));
  return p ? { x: p.x, y: p.y, n: p.f.n } : null; })()`);
const zoom = (b) => b.js('__atlas.view.s');
async function openViewer(b) { await b.goto(BASE + '/', ready); await sleep(400); }

const J = {
  // ---------------------------------------------------------------- the tool bar
  async tools(b, ok) {
    await openViewer(b);
    const tools = ['pan', 'measure', 'circle', 'ellipse', 'rect', 'outline', 'text', 'arrow'];
    for (const t of tools) {
      await b.hover(`#tools button[data-tool="${t}"]`);
      const tip = await b.js(`(() => { const t = document.getElementById('tip'); return getComputedStyle(t).display !== 'none' ? t.textContent : ''; })()`);
      await ok(tip.length > 2, `hovering the ${t} button shows its tooltip ("${tip}")`);
      await b.click(`#tools button[data-tool="${t}"]`);
      const pressed = await b.js(`[...document.querySelectorAll('#tools button[data-tool]')].filter((x) => x.getAttribute('aria-pressed') === 'true').map((x) => x.dataset.tool)`);
      await ok(pressed.length === 1 && pressed[0] === t, `clicking ${t} makes it the one pressed tool (${pressed})`);
    }
    const keys = { v: 'pan', m: 'measure', c: 'circle', e: 'ellipse', r: 'rect', o: 'outline', t: 'text', a: 'arrow' };
    await b.clickAt(700, 450); await b.press('Escape');
    for (const [k, t] of Object.entries(keys)) {
      await b.press(k);
      const on = await b.js(`document.querySelector('#tools button[aria-pressed="true"]').dataset.tool`);
      await ok(on === t, `the ${k.toUpperCase()} key picks ${t} (${on})`);
    }
    await b.press('v');
    const cross = await b.js(`document.getElementById('map').classList.contains('crosshair')`);
    await ok(!cross, 'the pan tool has no crosshair cursor');
    await b.click('#undoBtn');
    await ok(/Nothing to undo/.test(await toastSays(b, /Nothing to undo/)), 'Undo with nothing done says so');
    await b.click('#redoBtn');
    await ok(/Nothing to redo/.test(await toastSays(b, /Nothing to redo/)), 'Redo with nothing undone says so');
    const label = await b.js(`document.getElementById('undoBtn').getAttribute('aria-label')`);
    await ok(/Undo \((⌘Z|Ctrl\+Z)\)/.test(label), `Undo names its shortcut for this platform (${label})`);
  },

  // ---------------------------------------------------------------- every drawing tool, with its editor
  async draw(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    const spots = { circle: [-0.45, -0.35], ellipse: [0.15, -0.4], rect: [-0.45, 0.2], arrow: [0.2, 0.25] };
    let n = 0;
    for (const [tool, [fx, fy]] of Object.entries(spots)) {
      await b.press(tool === 'rect' ? 'r' : tool[0]);
      const x = cx + fx * R, y = cy + fy * R;
      await ok(await onCanvas(b, x, y), `${tool}: the spot to draw is on the canvas, not under a panel`);
      await b.drag(x, y, x + 0.18 * R, y + 0.12 * R);
      n++;
      await b.until(`!document.getElementById('annot').hidden`, 3000, `the ${tool} editor`);
      const head = await b.text('#annot h4');
      await ok(head.toLowerCase().startsWith(tool === 'rect' ? 'rectangle' : tool), `drawing a ${tool} opens its editor ("${head}")`);
      await ok(await b.js(`document.activeElement.id === 'aLabel'`), `${tool}: the label box has the focus`);
      const chip = await b.text('#annot .chip');
      await ok(chip.length > 0, `${tool}: nearby names are offered (${chip})`);
      await b.click('#annot .chip');
      await ok(await b.js(`document.getElementById('aLabel').value`) === chip, `${tool}: a click on a name fills the label`);
      await b.click('#annot .colours button:nth-child(3)');
      const colour = await b.js(`document.querySelector('#annot .colours button:nth-child(3)').dataset.c`);
      await b.choose('#aSize', '1.35');
      await b.click('#aDash');
      await b.click('#aOk');
      await ok(await b.js(`document.getElementById('annot').hidden`), `${tool}: Done closes the editor`);
      const e = await serverHas(b, (e) => e.shapes.length === n && e.shapes[n - 1].dash, `the ${tool}`);
      const s = e.shapes[n - 1];
      await ok(s.kind === tool && s.label === chip && s.colour === colour && s.size === 1.35 && s.dash === true,
        `${tool}: kind, label, colour, size and dashes reach the sidecar (${JSON.stringify(s).slice(0, 160)})`);
    }
    // an outline: click corners, double-click the last one to close it, type a label, Enter
    await b.press('o');
    const pts = [[-0.2, 0.55], [0.05, 0.45], [0.2, 0.6]];
    for (const [fx, fy] of pts) await b.clickAt(cx + fx * R, cy + fy * R);
    await b.clickAt(cx + 0.0 * R, cy + 0.7 * R, { count: 2 });
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the outline editor');
    await b.type('My outline');
    await b.press('Enter');
    let e = await serverHas(b, (e) => e.shapes.length === n + 1 && e.shapes[n].label === 'My outline', 'the outline');
    await ok(e.shapes[n].kind === 'outline' && e.shapes[n].closed && e.shapes[n].pts.length === 4,
      `a double-click closes a 4-point outline, typed label and Enter keep it (${e.shapes[n].pts.length} points)`);
    n++;
    // text: click, type, Done; and a text left empty is not kept
    await b.press('t');
    await b.clickAt(cx - 0.1 * R, cy + 0.05 * R);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the text editor');
    await b.type('Hello Moon');
    await b.click('#aOk');
    e = await serverHas(b, (e) => e.shapes.length === n + 1, 'the text');
    await ok(e.shapes[n].kind === 'text' && e.shapes[n].label === 'Hello Moon', 'a typed text is kept');
    n++;
    await b.clickAt(cx + 0.1 * R, cy - 0.1 * R);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'a second text editor');
    await b.click('#aOk');
    await sleep(500);
    e = await edits(b);
    await ok(e.shapes.length === n, `an empty text is dropped (${e.shapes.length} shapes)`);
    await ok(await b.text('#n-mine') === String(n), `the My drawings counter says ${n}`);
    // a tiny drag is a click, not a shape
    await b.press('c');
    await b.drag(cx, cy, cx + 2, cy + 1, { steps: 2 });
    await sleep(400);
    await ok((await edits(b)).shapes.length === n, 'a 2-pixel drag with the circle tool draws nothing');
    await b.press('Escape');
  },

  // ---------------------------------------------------------------- select, move, delete, undo a drawing
  async edit(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.press('c');
    await b.drag(cx - 0.3 * R, cy, cx - 0.1 * R, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the circle editor');
    await b.click('#aOk');
    let e = await serverHas(b, (e) => e.shapes.length === 1, 'the circle');
    const c0 = e.shapes[0];
    await b.press('v');
    const [ex, ey] = await scr(b, c0.cx, c0.cy + c0.r);           // on the outline, away from the resize handle
    await b.clickAt(ex, ey);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor after a click on the circle');
    await ok(/Circle/.test(await b.text('#annot h4')), 'a click on the outline opens the circle again');
    const s = await zoom(b);
    await b.drag(ex, ey, ex + 60, ey + 30);
    e = await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx - 60 / s) < 3, 'the moved circle');
    await ok(Math.abs(e.shapes[0].cy - c0.cy - 30 / s) < 3, 'dragging the outline moves the circle by the mouse distance');
    await b.click('#undoBtn');
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx) < 0.5, 'the circle back in place');
    await ok(true, 'the Undo button puts it back');
    await b.click('#redoBtn');
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx - 60 / s) < 3, 'the move redone');
    await ok(true, 'the Redo button moves it again');
    await b.press('z', [CMD]);
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx) < 0.5, 'the move undone by the keyboard');
    await ok(true, `${CMD === 'meta' ? '⌘' : 'Ctrl'}+Z undoes`);
    await b.press('z', [CMD, 'shift']);
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx - 60 / s) < 3, 'the move redone by the keyboard');
    await ok(true, 'Shift+' + (CMD === 'meta' ? '⌘' : 'Ctrl') + '+Z redoes');
    await b.press('z', [CMD]);
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx) < 0.5, 'the circle back');
    await b.press('y', [CMD]);
    await serverHas(b, (e) => Math.abs(e.shapes[0].cx - c0.cx - 60 / s) < 3, 'the move redone by Ctrl+Y');
    await ok(true, (CMD === 'meta' ? '⌘' : 'Ctrl') + '+Y redoes too');
    // Delete key with the editor open
    const [ex2, ey2] = await scr(b, e.shapes[0].cx + e.shapes[0].r, e.shapes[0].cy);
    await b.clickAt(ex2, ey2);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.click('#annot h4');                                     // off the label box, so Delete is not typing
    await b.press('Delete');
    await serverHas(b, (e) => e.shapes.length === 0, 'no shapes after Delete');
    await ok(true, 'the Delete key removes the open drawing');
    await b.press('z', [CMD]);
    await serverHas(b, (e) => e.shapes.length === 1, 'the drawing back');
    await ok(true, 'and undo brings it back');
    // the editor's Delete button
    await b.clickAt(ex2, ey2);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.click('#aDel');
    await serverHas(b, (e) => e.shapes.length === 0, 'no shapes after the Delete button');
    await ok(await b.js(`document.getElementById('annot').hidden`), 'the Delete button removes it and closes the editor');
    // typing in the label box: Delete and Ctrl+Z edit the text, not the drawings
    await b.press('r');
    await b.drag(cx - 0.2 * R, cy - 0.2 * R, cx, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the rectangle editor');
    await b.type('abc'); await b.press('Backspace'); await b.press('Delete');
    await sleep(400);
    e = await edits(b);
    await ok(e.shapes.length === 1 && e.shapes[0].label === 'ab', `keys in the label box edit the label, not the drawings ("${e.shapes[0] && e.shapes[0].label}")`);
    await b.click('#annot h4');                       // Escape is not handled while the label box has the focus
    await b.press('Escape');
    await ok(await b.js(`document.getElementById('annot').hidden`), 'Escape closes the editor');
    // My drawings off: the shapes are not drawn and cannot be grabbed
    await b.click('#l-mine + span');
    const [rx, ry] = await scr(b, e.shapes[0].x0, (e.shapes[0].y0 + e.shapes[0].y1) / 2);
    await b.clickAt(rx, ry);
    await ok(await b.js(`document.getElementById('annot').hidden`), 'with My drawings off a click on a drawing does not open it');
    await b.click('#l-mine + span');
  },

  // ---------------------------------------------------------------- measuring
  async measure(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.click('#tools button[data-tool="measure"]');
    await b.clickAt(cx - 0.4 * R, cy - 0.1 * R);
    await b.move(cx, cy); await sleep(100);
    await b.clickAt(cx + 0.4 * R, cy + 0.1 * R);
    const t = await toastSays(b, /km/);
    await ok(/saved/.test(t), `the second click saves the measurement ("${t}")`);
    const e = await serverHas(b, (e) => e.shapes.length === 1 && e.shapes[0].kind === 'measure', 'the measurement');
    const km = +/([\d.,]+)\s*km/.exec(t)[1].replace(',', '');
    const expect = 0.8 * 1737.4 * 1.03;                               // ≈ chord across 0.8 R, the arc a little longer
    await ok(km > 0.6 * expect && km < 1.6 * expect, `the distance is plausible (${km} km for 0.8 of the radius)`);
    // off the disk
    let off = null;
    for (const [x, y] of [[cx - 1.25 * R, cy], [cx + 1.25 * R, cy], [cx, cy - 1.2 * R], [cx, cy + 1.2 * R]]) if (x > 90 && y > 80 && x < 1350 && y < 830 && await onCanvas(b, x, y)) { off = [x, y]; break; }
    if (off) {
      await b.clickAt(...off);
      await ok(/Measure on the lunar disk/.test(await toastSays(b, /Measure on/)), 'a click off the disk is refused with a hint');
    }
    // back to pan: a click on the line opens it, with the distance
    await b.press('v');
    const [mx, my] = await scr(b, (e.shapes[0].a.x + e.shapes[0].b.x) / 2, (e.shapes[0].a.y + e.shapes[0].b.y) / 2);
    await b.clickAt(mx, my);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the measurement editor');
    await ok(/Measurement/.test(await b.text('#annot h4')) && /km/.test(await b.text('#annot .hint')), 'a click on the line opens it with its distance');
    await b.click('#aDel');
    await serverHas(b, (e) => e.shapes.length === 0, 'the measurement deleted');
    await ok(true, 'and it can be deleted');
  },

  // ---------------------------------------------------------------- zoom, pan, fit, 1:1, the status bar
  async navigate(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    const s0 = await zoom(b), pct0 = await b.text('#zoomPct'), km0 = await b.text('#slabel');
    await ok(/%/.test(pct0) && /km/.test(km0), `the status bar shows the zoom and a scale bar (${pct0}, ${km0})`);
    await b.move(cx + 0.1 * R, cy - 0.1 * R); await sleep(100);
    const over = await b.text('#readout');
    await ok(/° [NS]/.test(over) && /° [EW]/.test(over), `over the disk the read-out gives latitude and longitude (${over.replace(/\s+/g, ' ').trim()})`);
    await b.wheel(cx, cy, -400);
    const s1 = await zoom(b);
    await ok(s1 > s0 * 1.5, `the mouse wheel zooms in (${s0.toFixed(3)} → ${s1.toFixed(3)})`);
    await ok(await b.text('#zoomPct') !== pct0, 'and the zoom read-out follows');
    await b.wheel(cx, cy, 400);
    await ok(Math.abs(await zoom(b) - s0) / s0 < 0.05, 'the wheel back zooms out again');
    await b.clickAt(cx, cy, { count: 2 });
    const zIn = await zoom(b) / s0;
    await ok(Math.abs(zIn - 2) < 0.05, `a double-click zooms in 2× (measured ×${zIn.toFixed(3)})`);
    await b.clickAt(cx, cy, { mods: ['shift'], count: 2 });
    await sleep(100);
    const zOut = await zoom(b) / s0;
    await ok(Math.abs(zOut - 1) < 0.05, `Shift+double-click zooms out 2× (back to ×${zOut.toFixed(3)} of the start)`);
    const v0 = await b.js('[__atlas.view.x, __atlas.view.y]');
    await b.drag(cx - 100, cy + 50, cx + 100, cy - 50);
    const v1 = await b.js('[__atlas.view.x, __atlas.view.y]');
    const s = await zoom(b);
    await ok(Math.abs((v0[0] - v1[0]) * s - 200) < 4 && Math.abs((v1[1] - v0[1]) * s - 100) < 4, 'dragging pans the image with the mouse');
    await b.click('#oneBtn');
    await b.until(`Math.abs(__atlas.view.s - 1) < 0.01`, 3000, '1:1');
    await sleep(800);                                  // the flight ends; a fit during it would be overridden
    await ok(await b.text('#zoomPct') === '100 %', 'the 1:1 button shows actual pixels (100 %)');
    await b.click('#fitBtn');
    await ok(Math.abs(await zoom(b) - s0) / s0 < 0.01, 'the Fit button shows the whole disk again');
    await b.clickAt(cx + 0.9 * R, cy + 0.9 * R); await b.press('Escape');
    await b.press('='); await b.press('=');
    await ok(Math.abs(await zoom(b) / s0 - 2.25) < 0.05, 'the = key zooms in (1.5× a press)');
    await b.press('-');
    await ok(Math.abs(await zoom(b) / s0 - 1.5) < 0.05, 'the - key zooms out');
    await b.press('1');
    await b.until(`Math.abs(__atlas.view.s - 1) < 0.01`, 3000, '1:1 by key');
    await sleep(800);
    await ok(true, 'the 1 key shows actual pixels');
    await b.press('f');
    await ok(Math.abs(await zoom(b) - s0) / s0 < 0.01, 'the F key fits the disk');
    for (let i = 0; i < 12; i++) await b.wheel(cx, cy, -600);
    await ok(await zoom(b) <= 8.0001, `zooming in stops at 800 % (${(await zoom(b) * 100).toFixed(0)} %)`);
    for (let i = 0; i < 16; i++) await b.wheel(cx, cy, 600);
    await ok(await zoom(b) > 0, 'zooming out stops at a minimum');
    await b.press('f');
    // #slabel is written by render(), which redraw() defers to the next animation frame: it lags the zoom state
    // (which zoom(b) reads directly) by a frame, and a loaded runner can be several frames late
    try { await b.until(`document.getElementById('slabel').textContent === ${JSON.stringify(km0)}`, 3000, 'the scale bar'); } catch { /* the check below reports what it saw */ }
    const kmNow = await b.text('#slabel');
    await ok(kmNow === km0, `the scale bar is back to where it started (${kmNow}, expected ${km0})`);
  },

  // ---------------------------------------------------------------- the search box
  async search(b, ok) {
    await openViewer(b);
    await b.click('#q');
    await b.type('tyc');
    await b.until(`document.getElementById('results').classList.contains('open')`, 2000, 'the results');
    const first = await b.text('#results li[data-i="0"] .nm');
    await ok(first === 'Tycho', `typing "tyc" offers Tycho first ("${first}")`);
    await b.press('ArrowDown'); await b.press('ArrowUp');
    await ok(await b.js(`document.querySelector('#results li.on').dataset.i`) === '0', 'the arrow keys move through the list');
    await b.press('Enter');
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await ok(await b.text('#info h2') === 'Tycho', 'Enter opens Tycho\'s card');
    await b.until(`Math.abs(__atlas.view.x - ATLAS.features.find((f) => f.n === 'Tycho').x) < 2`, 3000, 'the flight to Tycho');
    await ok(true, 'and the view flies to Tycho');
    await ok(await b.js(`document.getElementById('q').value`) === 'Tycho', 'the box shows the chosen name');
    await b.press('Escape');
    await ok(await b.js(`document.getElementById('info').hidden`), 'Escape closes the card');
    await b.press('/');
    await ok(await b.js(`document.activeElement.id === 'q'`), 'the / key jumps to the search box');
    await b.type('zzqq');
    await b.until(`/No visible feature/.test(document.getElementById('results').textContent)`, 2000, 'the empty result');
    await ok(true, 'a name that does not exist says so');
    await b.press('Escape');
    await ok(await b.js(`!document.getElementById('results').classList.contains('open') && document.activeElement.id !== 'q'`), 'Escape closes the list and leaves the box');
    await b.click('#q');
    await b.js(`document.getElementById('q').select()`);
    await b.type('coperni');
    await b.until(`document.getElementById('results').classList.contains('open')`, 2000, 'the results');
    await b.click('#results li[data-i="0"]');
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await ok(await b.text('#info h2') === 'Copernicus', 'a click on a result opens its card');
    await b.click('#q');
    await b.js(`document.getElementById('q').select()`);
    await b.type('mare imbrium');
    await b.until(`document.getElementById('results').classList.contains('open')`, 2000, 'the results');
    await ok(/Mare Imbrium/.test(await b.text('#results')), 'names of several words are found');
    await b.click('#q'); await b.js(`document.getElementById('q').select()`); await b.type('ANGSTROM');
    await b.until(`document.getElementById('results').classList.contains('open')`, 2000, 'the results');
    await ok(await b.text('#results li[data-i="0"] .nm') === 'Angström', 'accents and case do not matter (ANGSTROM finds Angström)');
  },

  // ---------------------------------------------------------------- a name's card: restyle, move, hide
  async card(b, ok) {
    await openViewer(b);
    let p = await labelAway(b);
    await ok(!!p, 'a crater name away from the panels to click');
    await b.clickAt(p.x, p.y);
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await ok(await b.text('#info h2') === p.n, `a click on ${p.n} opens its card`);
    await ok(/Diameter/.test(await b.text('#info')) && /° [NS]/.test(await b.text('#info')), 'the card gives its diameter and position');
    await b.click('#info .colours button:nth-child(3)');
    const col = await b.js(`document.querySelector('#info .colours button:nth-child(3)').dataset.c`);
    await serverHas(b, (e) => e.labels[p.n] && e.labels[p.n].colour === col, 'the label colour');
    await ok(await b.js(`document.querySelector('#info .colours button:nth-child(3)').classList.contains('on')`), 'a colour click restyles the name and marks the colour');
    await b.choose('#lSize', '1.3');
    await serverHas(b, (e) => e.labels[p.n].size === 1.3, 'the label size');
    await ok(true, 'the size menu makes the name larger');
    p = await b.js(`(() => { __atlas.render(); const q = __atlas.placed.find((q) => q.f.n === ${JSON.stringify(p.n)}); return { x: q.x, y: q.y, n: q.f.n }; })()`);
    await b.drag(p.x, p.y, p.x + 50, p.y + 35);
    await serverHas(b, (e) => e.labels[p.n].dx != null, 'the moved label');
    const at = await b.js(`(() => { __atlas.render(); const q = __atlas.placed.find((q) => q.f.n === ${JSON.stringify(p.n)}); return [q.x, q.y]; })()`);
    await ok(Math.abs(at[0] - p.x - 50) < 3 && Math.abs(at[1] - p.y - 35) < 3, `dragging the name moves it with the mouse (${(at[0] - p.x).toFixed(0)}, ${(at[1] - p.y).toFixed(0)})`);
    await b.until(`!!document.getElementById('lReset')`, 2000, 'the reset link');
    await b.click('#lReset');
    await serverHas(b, (e) => e.labels[p.n] && e.labels[p.n].dx == null, 'the label back home');
    await ok(true, '"back to its place" returns it, keeping its colour and size');
    const s0 = await zoom(b);
    await b.click('#infoZoom');
    await sleep(900);
    await ok(await zoom(b) > s0, 'Zoom to flies in on it');
    await b.click('#infoHide');
    await serverHas(b, (e) => e.hidden.includes(p.n), 'the hidden name');
    await ok(await b.js(`document.getElementById('info').hidden && !__atlas.placed.some((q) => q.f.n === ${JSON.stringify(p.n)})`), 'Hide label removes the name and closes the card');
    await ok(/hidden/.test(await toast(b)), 'and says how to undo it');
    await b.click('#undoBtn');
    await serverHas(b, (e) => !e.hidden.includes(p.n), 'the name back');
    await ok(true, 'Undo shows it again');
    await b.press('f');
    const q = await labelAway(b);
    await b.clickAt(q.x, q.y);
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await b.click('#infoClose');
    await ok(await b.js(`document.getElementById('info').hidden`), 'the close button closes the card');
    const [cx, cy, R] = await centre(b);
    let empty = null;
    for (let i = 0; i < 40 && !empty; i++) {
      const x = cx + (Math.random() - 0.5) * R, y = cy + (Math.random() - 0.5) * R;
      if (await b.js(`(() => { __atlas.render(); return !__atlas.placed.some((q) => Math.abs(q.x - ${x}) < 90 && Math.abs(q.y - ${y}) < 40) && !__atlas.hitFeature(${x}, ${y}) && document.elementFromPoint(${x}, ${y}).id === 'map'; })()`)) empty = [x, y];
    }
    if (empty) {
      await b.clickAt(q.x, q.y);
      await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
      await b.clickAt(...empty);
      await ok(await b.js(`document.getElementById('info').hidden`), 'a click on empty ground closes the card');
    }
  },

  // ---------------------------------------------------------------- the layers panel
  async layers(b, ok) {
    await openViewer(b);
    const CLS = { area: ['area'], crater: ['crater'], lettered: ['lettered', 'apollo'], relief: ['relief', 'site'], landing: ['landing'] };
    await b.wheel(700, 450, -500);                                 // closer in, so every kind of name shows
    for (const [layer, cls] of Object.entries(CLS)) {
      const had = await b.js(`(__atlas.render(), __atlas.placed.filter((q) => ${JSON.stringify(cls)}.includes(q.f.c)).length)`);
      await b.click(`#l-${layer} + span`);
      await ok(!(await b.js(`document.getElementById('l-${layer}').checked`)), `a click on the ${layer} switch turns it off`);
      const left = await b.js(`(__atlas.render(), __atlas.placed.filter((q) => ${JSON.stringify(cls)}.includes(q.f.c)).length)`);
      await ok(left === 0, `and its names go (${had} → ${left})`);
      await serverHas(b, (e) => !e.style.layers.includes(layer), `${layer} off in the saved style`);
      await b.click(`label[for="l-${layer}"]`);
      await ok(await b.js(`document.getElementById('l-${layer}').checked`), `a click on the ${layer} label turns it back on`);
    }
    await b.press('f');
    await b.click('#l-grid + span');
    await serverHas(b, (e) => e.style.grid === true, 'the grid on');
    await ok(true, 'the grid switch turns the grid on and it is saved');
    await b.clickAt(700, 450); await b.press('Escape');
    await b.press('g');
    await serverHas(b, (e) => e.style.grid === false, 'the grid off');
    await ok(!(await b.js(`document.getElementById('l-grid').checked`)), 'the G key turns it off again, switch and all');
    await b.click('#l-rims + span');
    await serverHas(b, (e) => e.style.rims === true, 'the rims on');
    await ok(true, 'the crater outline switch is saved');
    await b.click('#l-rims + span');
    // a clicked switch keeps the keyboard focus, and the viewer ignores its shortcuts while a form field has it
    await b.clickAt(700, 450); await b.press('Escape');
    await b.press('l');
    await ok(await b.js(`(__atlas.render(), __atlas.placed.length === 0)`), 'the L key turns all names off');
    await b.press('l');
    await ok(await b.js(`(__atlas.render(), __atlas.placed.length > 20)`), 'and on again');
    await ok(await b.js(`document.querySelector('#night button.on').dataset.v`) === 'hide', 'night-side names are hidden by default');
    for (const v of ['show', 'dim', 'hide']) {
      await b.click(`#night button[data-v="${v}"]`);
      await serverHas(b, (e) => e.style.night === v, `night ${v}`);
      await ok(await b.js(`document.querySelector('#night button.on').dataset.v`) === v, `night side: ${v} is chosen and saved`);
    }
    const n0 = await b.js('(__atlas.render(), __atlas.placed.length)');
    await b.click('#minPx');                                        // a click on the track moves the thumb there
    const v0 = +(await b.js(`document.getElementById('minPx').value`));
    for (let i = 0; i < 20; i++) await b.press('ArrowRight');
    const v1 = +(await b.js(`document.getElementById('minPx').value`));
    await ok(v1 === Math.min(70, v0 + 20), `the Detail slider moves with the arrow keys (${v0} → ${v1})`);
    await ok(new RegExp(`${v1} px`).test(await b.text('#minPxV')), `its read-out says ${await b.text('#minPxV')}`);
    await serverHas(b, (e) => e.style.minPx === v1, 'the detail setting');
    await ok(await b.js('(__atlas.render(), __atlas.placed.length)') < n0, 'less detail shows fewer names');
    await b.press('Home');
    await b.click('#fs');
    for (let i = 0; i < 3; i++) await b.press('ArrowRight');
    const fs = +(await b.js(`document.getElementById('fs').value`));
    await serverHas(b, (e) => Math.abs(e.style.fs - fs) < 1e-6, 'the label size');
    await ok(await b.text('#fsV') === Math.round(fs * 100) + ' %', `the Label size slider is saved (${await b.text('#fsV')})`);
    const fonts = await b.js(`[...document.querySelectorAll('#fontSel option')].map((o) => o.value)`);
    await ok(fonts.length >= 2, `there is a choice of fonts (${fonts.join(', ')})`);
    if (fonts.length >= 2) {
      await b.choose('#fontSel', fonts[1]);
      await serverHas(b, (e) => e.style.font === fonts[1], 'the font');
      await ok(true, `choosing ${fonts[1]} is saved`);
    }
    await b.click('#layersHead');
    await ok(await b.js(`document.getElementById('layers').classList.contains('collapsed')`), 'a click on the Layers heading folds the panel');
    await ok(await b.js(`document.getElementById('layersHead').getAttribute('aria-expanded')`) === 'false', 'and says so to screen readers');
    await b.press('Enter');
    await ok(!(await b.js(`document.getElementById('layers').classList.contains('collapsed')`)), 'Enter on the focused heading unfolds it');
  },

  // ---------------------------------------------------------------- several names at once
  async picks(b, ok) {
    await openViewer(b);
    const two = await b.js(`(() => { __atlas.render(); const ok = (q) => q.x > 120 && q.x < innerWidth - 420 && q.y > 100 && q.y < innerHeight - 140 && document.elementFromPoint(q.x, q.y).id === 'map';
      const a = __atlas.placed.find(ok), c = a && __atlas.placed.find((q) => ok(q) && Math.hypot(q.x - a.x, q.y - a.y) > 80);
      return a && c ? [{ x: a.x, y: a.y, n: a.f.n }, { x: c.x, y: c.y, n: c.f.n }] : null; })()`);
    await ok(!!two, 'two names apart to pick');
    const [a, c] = two;
    await b.clickAt(a.x, a.y, { mods: ['alt'] });
    await b.clickAt(c.x, c.y, { mods: ['alt'] });
    await b.until(`!document.getElementById('picks').hidden`, 2000, 'the selection bar');
    await ok(/2 selected/.test(await b.text('#picks')), `Alt-click on ${a.n} and ${c.n}: "2 selected"`);
    await b.clickAt(a.x, a.y, { mods: ['alt'] });
    await ok(/1 selected/.test(await b.text('#picks')), 'Alt-click again takes one out');
    await b.clickAt(a.x, a.y, { mods: ['alt'] });
    await b.click('#pHide');
    await serverHas(b, (e) => e.hidden.includes(a.n) && e.hidden.includes(c.n), 'both hidden');
    await ok(await b.js(`document.getElementById('picks').hidden`), 'the Hide button hides both names and the bar goes');
    await b.click('#undoBtn');
    await serverHas(b, (e) => !e.hidden.includes(a.n) && !e.hidden.includes(c.n), 'both back');
    await ok(true, 'one Undo brings both back');
    await b.drag(160, 110, 960, 760, { mods: ['alt'], steps: 10 });
    const n = await b.js('__atlas.picks.size');
    await ok(n > 2, `an Alt-drag picks every name in the box (${n})`);
    await b.click('#pClear');
    await ok(await b.js(`document.getElementById('picks').hidden && __atlas.picks.size === 0`), 'Clear empties the selection');
    const e = await edits(b);
    await ok(e.hidden.length === 0, 'and hides nothing');
    await b.clickAt(a.x, a.y, { mods: ['alt'] });
    await b.press('Backspace');
    await serverHas(b, (e) => e.hidden.includes(a.n), 'hidden by Backspace');
    await ok(true, 'Backspace hides the picked names too');
  },

  // ---------------------------------------------------------------- export, from the dialog to the file
  async export(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.press('c'); await b.drag(cx, cy, cx + 0.2 * R, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.type('Export me'); await b.click('#aOk');
    await b.press('v');
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await ok(true, 'the Export button opens the dialog');
    await ok(/My drawings and measurements \(1\)/.test(await b.text('#export')), 'it counts my drawing');
    await ok(await b.js(`document.querySelector('[name=reg][value=feature]').disabled`), '"Around feature" is off with no name selected');
    await b.until(`(() => { const c = document.getElementById('xPrev'); if (!c.width) return false; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let s = 0; for (let i = 0; i < d.length; i += 16) s += d[i]; return s > 1000; })()`, 5000, 'a preview with the Moon in it');
    await ok(true, 'the preview shows the image');
    const [W, H] = await b.js('[ATLAS.width, ATLAS.height]');
    await ok((await b.text('#outSize')).startsWith(`${W} × ${H} px`), `whole image at 1:1: ${await b.text('#outSize')}`);
    await b.click('[name=fmt][value=png]');
    await b.click('[name=sc][value=half]');
    const want = `${Math.round(W / 2)} × ${Math.round(H / 2)} px · 16-bit PNG`;
    await b.until(`document.getElementById('outSize').textContent === ${JSON.stringify(want)}`, 2000, want);
    await ok(true, `PNG at 1:2 says ${want}`);
    await b.click('#xGrid');
    await ok(!(await b.js(`document.getElementById('xGrid').checked`)), 'the grid box can be unticked');
    await b.click('#xGo');
    await ok(await b.js(`document.getElementById('xGo').disabled && !document.getElementById('xProg').hidden`), 'Export starts: button off, progress shown');
    await b.press('Escape');
    await ok(!(await b.js(`document.getElementById('export').hidden`)), 'Escape does not close the dialog while it runs');
    const done = await exported(b, 'png');
    await ok(/Written: .*\.png/.test(done), `the export finishes ("${done}")`);
    await ok(await b.visible('#xReveal'), 'and offers to show the file');
    await b.click('#xReveal');
    await sleep(300);
    await b.press('Escape');
    await ok(await b.js(`document.getElementById('export').hidden`), 'Escape closes the dialog afterwards');
    // the current view as JPEG, closed by a click beside the dialog
    await b.wheel(cx, cy, -300);
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await b.click('[name=reg][value=view]');
    await b.click('[name=fmt][value=jpg]');
    await b.click('[name=sc][value=max]');
    await b.click('#maxSide');
    await b.js(`document.getElementById('maxSide').select()`);
    await b.type('512');
    await b.until(`/^\\d+ × \\d+ px · JPEG$/.test(document.getElementById('outSize').textContent)`, 2000, 'the JPEG size');
    const sz = (await b.text('#outSize')).match(/(\d+) × (\d+)/).slice(1).map(Number);
    await ok(Math.max(...sz) <= 512, `longest side 512: ${await b.text('#outSize')}`);
    await b.click('#xGo');
    const d2 = await exported(b, 'jpg');
    await ok(/Written: .*\.jpg/.test(d2), `the view exports as JPEG ("${d2}")`);
    const spot = await besideDialog(b);
    await ok(!!spot, 'there is backdrop beside the dialog to click');
    if (spot) await b.clickAt(...spot);
    await ok(await b.js(`document.getElementById('export').hidden`), 'a click beside the dialog closes it');
    // around a feature
    await b.press('f');
    const p = await labelAway(b);
    await b.clickAt(p.x, p.y);
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await ok(!(await b.js(`document.querySelector('[name=reg][value=feature]').disabled`)), `with ${p.n} selected "Around feature" is offered`);
    await b.click('[name=reg][value=feature]');
    await b.click('[name=fmt][value=tiff]');
    await b.click('#xNorth');
    await ok(await b.js(`document.querySelector('[name=reg][value=view]').disabled`), 'North up switches "Current view" off (its box counts pixels of the picture as it was taken)');
    await ok(/turned/.test(await b.text('#outSize')), 'and the size line says the canvas grows');
    await b.click('#xGo');
    const d3 = await exported(b, 'tiff?');
    await ok(/Written: .*\.tiff?/.test(d3), `a close-up around ${p.n} exports as TIFF ("${d3}")`);
    await b.click('#xCancel');
    await ok(await b.js(`document.getElementById('export').hidden`), 'Close closes the dialog');
  },

  // ---------------------------------------------------------------- leaving at once, and a save that fails
  async leave(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.press('c'); await b.drag(cx, cy, cx + 0.2 * R, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.type('Last words'); await b.click('#aOk');
    await b.click('#otherImage');                                // before the 300 ms timer of the save has run
    await b.until(`location.pathname === '/app'`, 5000, 'the launcher');
    await ok(true, 'the link to the launcher goes back');
    const e = await b.js(`fetch('/edits').then((r) => r.json())`);
    await ok(e.shapes.length === 1 && e.shapes[0].label === 'Last words', `the edit made an instant before leaving is saved (${JSON.stringify(e.shapes).slice(0, 80)})`);
    // a reload straight after an edit
    await openViewer(b);
    await b.press('t'); await b.clickAt(cx - 0.3 * R, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the text editor');
    await b.type('Reloaded'); await b.click('#aOk');
    await b.goto(BASE + '/', ready);
    await sleep(500);
    const nm = await b.text('#n-mine');
    await ok(nm === '2', `a reload straight after an edit keeps it too (${nm} drawings, saved: ${JSON.stringify((await b.js(`fetch('/edits').then((r) => r.json())`)).shapes.map((q) => q.label))})`);
  },

  async savefail(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.press('c'); await b.drag(cx, cy, cx + 0.2 * R, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.type('Unsaved'); await b.click('#aOk');
    // an IIFE, not two ;-separated statements: WebDriver's js() wraps the expression in `return (...)`, which a
    // statement sequence cannot sit inside
    await b.js(`(() => { window.__realFetch = window.fetch; window.fetch = (u, o) => String(u).includes('/edits') && o && o.method === 'POST' ? Promise.reject(new Error('down')) : window.__realFetch(u, o); })()`);
    await b.press('v');
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await b.click('#xGo');
    await b.until(`/could not be saved/.test(document.getElementById('toast').textContent)`, 5000, 'the warning');
    await ok(true, 'an export whose drawings cannot be saved says so');
    await ok(!(await b.js(`document.getElementById('xGo').disabled`)), 'and Export can be tried again');
    const st = await b.js(`window.__realFetch('/export/status').then((r) => r.json())`);
    await ok(st.state === 'none', `no export was started (${st.state})`);
    await b.js(`window.fetch = window.__realFetch`);
    await b.click('#xGo');
    const done = await exported(b, 'tif');
    await ok(/Written/.test(done), `with the connection back the export runs (${done})`);
  },

  async preview(b, ok) {
    await openViewer(b);
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await sleep(1200);
    await b.js(`(() => { const c = document.getElementById('xPrev'); let n = 0, w = c.width; Object.defineProperty(c, 'width', { get: () => w, set: (v) => { n++; w = v; } }); window.__prevRenders = () => n; })()`);
    await b.click('#xGrid');
    await sleep(1000);
    await ok(await b.js('__prevRenders()') === 1, `one option change renders the preview once (${await b.js('__prevRenders()')})`);
  },

  // ---------------------------------------------------------------- a reload keeps everything
  async persist(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    await b.press('e'); await b.drag(cx - 0.3 * R, cy - 0.2 * R, cx, cy);
    await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor');
    await b.type('Kept'); await b.click('#aOk');
    await b.press('v');
    const p = await labelAway(b);
    await b.clickAt(p.x, p.y);
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card');
    await b.click('#infoHide');
    await b.click('#l-grid + span');
    await b.click('#night button[data-v="show"]');
    await serverHas(b, (e) => e.shapes.length === 1 && e.hidden.includes(p.n) && e.style.grid && e.style.night === 'show', 'all the edits');
    await b.goto(BASE + '/', ready);
    await sleep(600);
    await ok(await b.text('#n-mine') === '1', 'after a reload my drawing is back');
    await ok(await b.js(`document.getElementById('l-grid').checked`), 'the grid is still on');
    await ok(await b.js(`document.querySelector('#night button.on').dataset.v`) === 'show', 'the night setting is kept');
    await ok(await b.js(`(__atlas.render(), !__atlas.placed.some((q) => q.f.n === ${JSON.stringify(p.n)}))`), `${p.n} is still hidden`);
    await ok(/edits loaded/.test(await b.text('#saveState')), 'the status bar says the edits were loaded');
    await b.click('#q'); await b.type(p.n.slice(0, 6));
    await b.until(`document.getElementById('results').classList.contains('open')`, 2000, 'the results');
    await ok(/hidden/.test(await b.text('#results')), 'the search marks a hidden name as hidden');
    await b.press('Escape');
    await b.goto(BASE + `/#q=${encodeURIComponent('Copernicus')}`, ready);
    await b.until(`!document.getElementById('info').hidden`, 3000, 'the card from the link');
    await ok(await b.text('#info h2') === 'Copernicus', 'a link with #q=Copernicus opens on Copernicus');
  },

  // ---------------------------------------------------------------- the quality chip of a forced photo
  async gate(b, ok) {
    await openViewer(b);
    await ok(await b.visible('#gate'), 'a photo named despite the quality check shows a warning chip');
    await b.click('#gate');
    await ok(await b.visible('#gatePop'), 'a click on it explains why');
    await ok(/Photo quality/.test(await b.text('#gatePop')) && (await b.js(`document.querySelectorAll('#gatePop li').length`)) > 0, 'with the reasons listed');
    await ok(await b.js(`document.activeElement === document.querySelector('#gatePop .close')`), 'the focus goes to its close button');
    await b.press('Escape');
    await ok(!(await b.visible('#gatePop')) && await b.js(`document.activeElement.id === 'gate'`), 'Escape closes it and gives the focus back to the chip');
    await b.click('#gate');
    await b.click('#gatePop .close');
    await ok(!(await b.visible('#gatePop')), 'the close button closes it');
    await b.click('#gate');
    await b.clickAt(700, 400);
    await ok(!(await b.visible('#gatePop')), 'a click elsewhere closes it');
  },

  // ---------------------------------------------------------------- reshaping drawings by their squares
  async handles(b, ok) {
    await openViewer(b);
    const [cx, cy, R] = await centre(b);
    const s = await zoom(b);
    // the drawing tool stays on after a shape is drawn, and its squares only answer the pan tool: a user has to
    // pick the hand first (V does not reach the page while the label box has the focus)
    const editorOpen = async () => { await b.until(`!document.getElementById('annot').hidden`, 3000, 'the editor'); await b.click('#tools button[data-tool="pan"]'); };
    // circle: its square sets the radius; the editor's font menu
    await b.press('c'); await b.drag(cx - 0.45 * R, cy - 0.3 * R, cx - 0.3 * R, cy - 0.3 * R); await editorOpen();
    let e = await serverHas(b, (e) => e.shapes.length === 1, 'the circle');
    const c = e.shapes[0];
    let [hx, hy] = await scr(b, c.cx + c.r, c.cy);
    await b.drag(hx, hy, hx + 40, hy);
    e = await serverHas(b, (e) => Math.abs(e.shapes[0].r - c.r - 40 / s) < 3, 'the larger circle');
    await ok(true, 'dragging the circle\'s square makes it larger');
    await ok(!(await b.js(`document.getElementById('annot').hidden`)), 'and the editor stays open');
    const fonts = await b.js(`[...document.querySelectorAll('#aFont option')].map((o) => o.value).filter(Boolean)`);
    if (fonts.length > 1) {
      await b.choose('#aFont', fonts[1]);
      await serverHas(b, (e) => e.shapes[0].font === fonts[1], 'the drawing font');
      await ok(true, `the editor's font menu sets ${fonts[1]} for this label`);
    }
    await b.click('#aOk');
    // rectangle: a corner
    await b.press('r'); await b.drag(cx + 0.1 * R, cy - 0.45 * R, cx + 0.3 * R, cy - 0.3 * R); await editorOpen();
    e = await serverHas(b, (e) => e.shapes.length === 2, 'the rectangle');
    const r = e.shapes[1];
    [hx, hy] = await scr(b, r.x1, r.y1);
    await b.drag(hx, hy, hx + 30, hy + 20);
    await serverHas(b, (e) => Math.abs(e.shapes[1].x1 - r.x1 - 30 / s) < 3 && Math.abs(e.shapes[1].y1 - r.y1 - 20 / s) < 3, 'the moved corner');
    await ok(true, 'dragging a rectangle\'s corner reshapes it');
    await b.click('#aOk');
    // arrow: its tail
    await b.press('a'); await b.drag(cx - 0.35 * R, cy + 0.3 * R, cx - 0.15 * R, cy + 0.35 * R); await editorOpen();
    e = await serverHas(b, (e) => e.shapes.length === 3, 'the arrow');
    const a = e.shapes[2];
    [hx, hy] = await scr(b, a.x0, a.y0);
    await b.drag(hx, hy, hx - 25, hy - 25);
    await serverHas(b, (e) => Math.abs(e.shapes[2].x0 - a.x0 + 25 / s) < 3, 'the moved tail');
    await ok(true, 'dragging an arrow\'s tail moves only that end');
    await b.click('#aOk');
    // outline: a corner point
    await b.press('o');
    for (const [fx, fy] of [[0.1, 0.25], [0.3, 0.2], [0.35, 0.4]]) await b.clickAt(cx + fx * R, cy + fy * R);
    await b.clickAt(cx + 0.15 * R, cy + 0.45 * R, { count: 2 });
    await editorOpen();
    e = await serverHas(b, (e) => e.shapes.length === 4, 'the outline');
    const o = e.shapes[3];
    [hx, hy] = await scr(b, o.pts[0][0], o.pts[0][1]);
    await b.drag(hx, hy, hx - 20, hy + 15);
    await serverHas(b, (e) => Math.abs(e.shapes[3].pts[0][0] - o.pts[0][0] + 20 / s) < 3, 'the moved point');
    await ok(true, 'dragging an outline\'s point moves that point');
    await b.click('#aOk');
    // measurement: an end point, then one undo takes the reshaping back
    await b.press('m'); await b.clickAt(cx - 0.3 * R, cy - 0.05 * R); await b.clickAt(cx + 0.05 * R, cy + 0.05 * R);
    e = await serverHas(b, (e) => e.shapes.length === 5, 'the measurement');
    const m = e.shapes[4];
    await b.press('v');
    const [mx, my] = await scr(b, (m.a.x + m.b.x) / 2, (m.a.y + m.b.y) / 2);
    await b.clickAt(mx, my); await editorOpen();
    [hx, hy] = await scr(b, m.b.x, m.b.y);
    await b.drag(hx, hy, hx + 35, hy);
    await serverHas(b, (e) => Math.abs(e.shapes[4].b.x - m.b.x - 35 / s) < 3, 'the moved end');
    await ok(/km/.test(await b.text('#annot .hint')), 'dragging a measurement\'s end changes it; the editor gives the new distance');
    await b.click('#undoBtn');
    await serverHas(b, (e) => Math.abs(e.shapes[4].b.x - m.b.x) < 0.5, 'the end back');
    await ok(true, 'one Undo takes the reshaping back');
    await b.press('Escape');
    // a shape larger than the window: its editor still fits on the screen
    await b.press('r');
    await ok(await onCanvas(b, 120, 95), 'a corner of the window free to start a large rectangle');
    await b.drag(120, 95, 1085, 830, { steps: 12 }); await editorOpen();
    const box = await b.js(`(() => { const r = document.getElementById('annot').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()`);
    await ok(box[0] >= 0 && box[1] >= 0 && box[2] <= 1400 && box[3] <= 900, `the editor of a window-sized shape stays on the screen (${box.map(Math.round)})`);
    await b.click('#aOk');
    await serverHas(b, (e) => e.shapes.length === 6, 'the large rectangle');         // saved 300 ms after the edit
  },

  // ---------------------------------------------------------------- an export that fails says so
  async exportfail(b, ok) {
    await openViewer(b);
    await b.click('#exportBtn');
    await b.until(`!document.getElementById('export').hidden`, 2000, 'the export dialog');
    await b.click('#xGo');
    const t = await exported(b, 'tiff?');
    await ok(/Export failed/.test(t), `a failed export says so ("${t}")`);
    await ok(await b.js(`document.querySelector('#export .progress .bar > div').classList.contains('failed')`), 'and marks the bar as failed');
    await ok(!(await b.visible('#xReveal')), 'there is nothing to show in the file manager');
    await ok(!(await b.js(`document.getElementById('xGo').disabled`)), 'Export can be pressed again');
    await b.click('#xCancel');
  },

  // ---------------------------------------------------------------- the launcher: from a file to the viewer
  async launch(b, ok) {
    await b.setTimezone('Europe/Brussels');                        // 21:30 there = 19:30 UTC
    await b.goto(BASE + '/app');
    await b.until(`document.getElementById('folder').textContent.length > 0`, 5000, 'the work folder');
    await ok(true, `the launcher shows where it keeps photos (${await b.text('#folder')})`);
    await ok(!(await b.visible('#recentbox')), 'a new work folder lists no earlier photos');
    await b.chooseFile('#drop', [args.image]);
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details');
    await ok(await b.text('#fname') === args.image.split(/[\\/]/).pop(), `a click on the drop zone and a chosen file show its name (${await b.text('#fname')})`);
    await ok(/MB/.test(await b.text('#fsize')), `and its size (${await b.text('#fsize')})`);
    await ok(await b.visible('#when'), 'a name without a capture time asks for one');
    // Record the stage/bar high-water mark INSIDE the page's own render path, not by sampling the DOM from
    // outside on a timer: the page can update the bar and navigate away in the very same task (app.js's poll()
    // renders the final state and sets location.href in one synchronous run), so an external 250 ms poll can
    // land entirely between two renders and never observe an in-between state -- a real race, confirmed by
    // reproducing it with the fitted-circle timing of a fast synthetic locate, not merely theorized (BUG-22).
    // sessionStorage survives the same-origin navigation to the viewer, so the figure is read back below
    // instead of raced for.
    await b.js(`(function () {
      const orig = window.renderStages;
      window.renderStages = function () {
        orig();
        try {
          const done = document.querySelectorAll('#stages li.done').length;
          const bar = +document.getElementById('bar').getAttribute('aria-valuenow') || 0;
          const prev = JSON.parse(sessionStorage.getItem('la_test_progress') || '{"done":0,"bar":0}');
          sessionStorage.setItem('la_test_progress',
            JSON.stringify({ done: Math.max(prev.done, done), bar: Math.max(prev.bar, bar) }));
        } catch (e) { /* no storage: the journey still passes on the other assertions */ }
      };
    })()`);
    await b.choose('#when', '2026-09-20T21:30');
    await b.click('#go');
    await ok(await b.visible('#work'), '"Find the names" shows the progress');
    const t0 = Date.now();
    while (Date.now() - t0 < 240000) {
      const st = await b.js(`location.pathname === '/' ? 'viewer' : (document.getElementById('werr').hidden ? '' : document.getElementById('werr').textContent)`).catch(() => 'navigating');
      if (st === 'viewer') break;
      if (st) { await ok(false, 'the locate failed: ' + st); return; }
      await sleep(250);
    }
    const progress = await b.js(`JSON.parse(sessionStorage.getItem('la_test_progress') || '{"done":0,"bar":0}')`).catch(() => ({ done: 0, bar: 0 }));
    await ok(progress.done >= 2 && progress.bar > 10,
            `the stages tick off and the bar moves (${progress.done} stages done, bar at ${progress.bar} %)`);
    await b.until(ready, 30000, 'the viewer');
    await ok(true, 'when it is found, the viewer opens by itself with the names');
    await ok(await b.visible('#otherImage'), 'the viewer has a way back to the launcher');
    await b.click('#otherImage');
    await b.until(`location.pathname === '/app' && document.querySelectorAll('#recent li').length > 0`, 10000, 'the launcher with the photo listed');
    await ok(/Solved/.test(await b.text('#recent')), 'the photo is listed as solved');
    await ok(/20 Sept?|Sep 20|2026/.test(await b.text('#recent .sub')), `with the time it was taken (${await b.text('#recent .sub')})`);
    await b.until(`(() => { const i = document.querySelector('#recent img'); return i && i.complete && i.naturalWidth > 0; })()`, 5000, 'the thumbnail');
    await ok(true, 'and its thumbnail');
    await b.click('#recent li .btn');
    await b.until(ready, 30000, 'the viewer again');
    await ok(true, 'its Open button opens it again straight away');
  },

  async drop(b, ok) {
    await b.goto(BASE + '/app');
    const r = await b.target('#drop');
    await b.dropFile(r.x, r.y, [args.image]);
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details after a drop');
    await ok(await b.text('#fname') === args.image.split(/[\\/]/).pop(), 'dropping a photo on the page picks it');
    await b.click('#cancel');
    await ok(await b.visible('#drop') && !(await b.visible('#details')), '"Choose another" goes back to the drop zone');
    await ok(await b.js(`document.activeElement.id === 'drop'`), 'with the focus on it');
    b.chooser = null;
    await b.press('Enter');
    await ok(await b.answerChooser([args.stamped]), 'Enter on the drop zone opens the file chooser (keyboard only)');
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details');
    await ok(!(await b.visible('#when')), 'a name with a SharpCap time stamp does not ask for the time');
    await b.click('#cancel');
    await b.chooseFile('#drop', [args.text]);
    await sleep(300);
    await ok(b.dialogs.some((d) => /TIFF, PNG or JPEG/.test(d)), `a text file is refused with a message ("${b.dialogs.at(-1)}")`);
    await ok(await b.visible('#drop'), 'and the drop zone stays');
  },

  // ---------------------------------------------------------------- deterministic progress rendering
  // (bugs-overview BUG-22): a controlled status sequence fed straight into app.js's own render path, with no
  // server, no real locate, and no timing involved at all -- the "launch" journey above still exercises the
  // real end-to-end locate (upload, positioning, navigation, sidecar, names, recent row, thumbnail), but no
  // longer needs to also prove progress rendering by sampling the DOM against a race it cannot win.
  async progressStages(b, ok) {
    await b.goto(BASE + '/app');
    await b.until(`document.getElementById('folder').textContent.length > 0`, 5000, 'the work folder');
    const snaps = await b.js(`(function () {
      working('Finding where this is on the Moon');
      const snap = () => ({
        done: document.querySelectorAll('#stages li.done').length,
        active: (document.querySelector('#stages li.active') || {}).dataset ? document.querySelector('#stages li.active').dataset.id : null,
        bar: +document.getElementById('bar').getAttribute('aria-valuenow') || 0,
      });
      const out = [];
      const sequence = [
        ['loading', []],
        ['date', ['capture 2026-09-20 19:30 UTC']],
        ['searching', ['searching the image as a close-up', 'search: 3/10 views']],
        ['refining', ['result: 42 matches, 1.20 px rms']],
      ];
      for (const [label, lines] of sequence) {
        readLines(lines);
        toStage(window.__app.st.i);
        renderStages();
        out.push([label, snap()]);
      }
      toStage(5); renderStages();                            // 'opening'
      out.push(['opening', snap()]);
      return out;
    })()`);
    const byLabel = Object.fromEntries(snaps);
    await ok(byLabel.loading.done === 0 && byLabel.loading.active === 'load',
            `loading: the first stage is active, nothing done yet (${JSON.stringify(byLabel.loading)})`);
    await ok(byLabel.date.done >= 1, `date: the loading stage is marked done (${JSON.stringify(byLabel.date)})`);
    // "Downloading Moon maps" shows as skipped, not done, when nothing was ever downloaded (st.maps stays
    // false): done counts load+date (2) once searching is the active stage, not 3
    await ok(byLabel.searching.done >= 2 && byLabel.searching.active === 'search' && byLabel.searching.bar > 10,
            `searching: the stage and the bar both advance from a scripted log line (${JSON.stringify(byLabel.searching)})`);
    await ok(byLabel.refining.done >= 3 && byLabel.refining.active === 'refine',
            `refining: the fit stage is reached (${JSON.stringify(byLabel.refining)})`);
    await ok(byLabel.opening.done >= 4 && byLabel.opening.active === 'done',
            `opening: every earlier stage is done, "Opening the viewer" is now active (${JSON.stringify(byLabel.opening)})`);
    const failed = await b.js(`(function () {
      fail('a synthetic failure for this journey only');
      return { failed: document.getElementById('bar').classList.contains('failed'),
              title: document.getElementById('wtitle').textContent,
              stopHidden: document.getElementById('stop').hidden };
    })()`);
    await ok(failed.failed, `a scripted failure marks the bar failed, deterministically (${JSON.stringify(failed)})`);
    await ok(failed.title.length > 3, 'and shows a title');
    // the photo being worked on: nothing without a file or a path, the server's own thumbnail and the file's name
    // once there is a path, the browser's own copy of a small JPEG before the upload answers, and no empty frame
    // left behind by one that cannot be shown
    await b.js(`(() => { __app.path = null; __app.file = null; showPhoto(); })()`);
    await ok(await b.js(`document.getElementById('wthumb').hidden`), 'no thumbnail box without a file or a path');
    await b.js(`(() => { __app.path = ${JSON.stringify(args.image)}; showPhoto(); })()`);
    await b.until(`(() => { const i = document.getElementById('wimg'); return !document.getElementById('wthumb').hidden && i.complete && i.naturalWidth > 0; })()`,
                  10000, 'the thumbnail of the photo being worked on');
    const named = await b.js(`document.getElementById('wname').textContent`);
    await ok(named === args.image.split(/[\\/]/).pop(), `and the name of that photo beside it ("${named}")`);
    await b.js(`(function () {                     // a small JPEG, as chosen from disk before the upload answers
      const c = document.createElement('canvas'); c.width = c.height = 8;
      return new Promise((r) => c.toBlob((blob) => { __app.file = new File([blob], 'chosen.jpg'); __app.path = null; showPhoto(); r(1); }, 'image/jpeg'));
    })()`);
    await b.until(`(() => { const i = document.getElementById('wimg'); return i.src.startsWith('blob:') && i.complete && i.naturalWidth > 0; })()`,
                  5000, 'the chosen file previewed from the browser itself');
    await ok(await b.text('#wname') === 'chosen.jpg', 'a photo still uploading is named from the file the user chose');
    await b.js(`(function () {                     // what a TIFF gets: no browser decodes one, so no box at all
      __app.file = new File([new Uint8Array(64)], 'mosaic.tif'); __app.path = null; showPhoto();
    })()`);
    await ok(await b.js(`document.getElementById('wthumb').hidden`), 'a TIFF gets no local preview: the browser cannot decode one');
    await b.js(`(() => { __app.path = '/not/an/image/in/the/work/folder.tif'; showPhoto(); })()`);
    await b.until(`document.getElementById('wthumb').hidden`, 10000, 'the empty frame gone');
    await ok(true, 'a thumbnail the server cannot make leaves no empty frame, and the name stays');
    await ok(await b.js(`document.getElementById('wname').textContent.length > 0`), 'the name of a photo that cannot be shown is still there');
    await b.js(`fail('a synthetic failure')`);
    await ok((await b.text('#wname')).length > 0, 'a failure keeps the name of the photo it is about');
  },

  async cancel(b, ok) {
    await b.goto(BASE + '/app');
    await b.chooseFile('#drop', [args.image]);
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details');
    await b.click('#go');
    const t0 = Date.now();                         // Cancel while it searches: the synthetic Moon is found in seconds
    while (Date.now() - t0 < 60000 && !(await b.js(`!!document.querySelector('#stages li[data-id="search"].active') && !document.getElementById('stop').disabled`))) await sleep(30);
    await ok(await b.js(`!document.getElementById('stop').disabled`), 'Cancel can be pressed while it searches');
    await b.click('#stop');
    await b.until(`!document.getElementById('pick').hidden`, 30000, 'the drop zone after Cancel');
    await ok(true, 'Cancel stops the locate and goes back to the drop zone');
    const st = await b.js(`fetch('/app/status').then((r) => r.json())`);
    await ok(st.phase === 'idle', `the launcher is idle again (${st.phase})`);
  },

  async fail(b, ok) {
    await b.goto(BASE + '/app');
    await b.chooseFile('#drop', [args.blank]);
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details');
    await b.click('#go');
    await b.until(`!document.getElementById('werr').hidden`, 120000, 'the error');
    const title = await b.text('#wtitle');
    await ok(title.length > 3 && !/Working|Finding/.test(title), `a photo without the Moon ends in a plain-language error ("${title}")`);
    await ok(await b.visible('#again') && !(await b.visible('#stop')), 'with "Choose another photo" instead of Cancel');
    await ok(await b.js(`document.getElementById('bar').classList.contains('failed')`), 'and the bar marked as failed');
    await ok(await b.visible('#log') && (await b.text('#log')).length > 20, 'Details shows the log, open from the start');
    await b.grantClipboard(BASE);
    await b.click('#copy');
    const said = await b.text('#copy');
    await ok(said === 'Copied' || said === 'Selected', `Copy copies (or selects) the log ("${said}")`);
    await b.click('#again');
    await ok(await b.visible('#drop'), '"Choose another photo" starts over');
    await b.until(`!document.getElementById('recentbox').hidden`, 5000, 'the failed photo in the list');
    await ok(/Not solved/.test(await b.text('#recent')) && /Find names/.test(await b.text('#recent .btn')), 'the failed photo is listed as not solved, to try again');
  },

  // ---------------------------------------------------------------- the camera's time from the photo
  async exif(b, ok) {
    await b.setTimezone('Europe/Brussels');
    await b.goto(BASE + '/app');
    await b.chooseFile('#drop', [args.utc]);
    await b.until(`document.getElementById('when').value !== ''`, 3000, 'the camera time');
    await ok(await b.js(`document.getElementById('when').value`) === '2026-09-20T23:30', `a camera time recorded in UTC is shown in local time (${await b.js(`document.getElementById('when').value`)})`);
    await ok(/UTC\+00:00/.test(await b.text('#whenfrom')) && await b.visible('#whenfrom'), `and says where it came from ("${await b.text('#whenfrom')}")`);
    await b.choose('#when', '2026-09-21T01:00');
    await ok(!(await b.visible('#whenfrom')), 'a time the user changes drops the camera note');
    await b.click('#cancel');
    await b.chooseFile('#drop', [args.clock]);
    await b.until(`document.getElementById('when').value !== ''`, 3000, 'the camera time');
    await ok(await b.js(`document.getElementById('when').value`) === '2026-09-20T21:30', 'a camera clock without a zone is taken as it is');
    await ok(/clock/.test(await b.text('#whenfrom')), 'with a warning to check it');
    await b.click('#cancel');
    await b.chooseFile('#drop', [args.plain]);
    await sleep(500);
    await ok(await b.js(`document.getElementById('when').value`) === '' && !(await b.visible('#whenfrom')), 'a photo without a time leaves the box empty');
  },

  // ---------------------------------------------------------------- a photo refused by the quality check
  async refused(b, ok) {
    await b.goto(BASE + '/app');
    await b.until(`document.querySelectorAll('#recent li').length === 2`, 5000, 'the two earlier photos');
    const rows = await b.js(`[...document.querySelectorAll('#recent li')].map((li) => li.textContent)`);
    await ok(rows.some((t) => /Low quality/.test(t) && /Open anyway/.test(t)), 'a refused photo is listed as low quality, to open anyway');
    await ok(rows.some((t) => /Not solved/.test(t) && /time unknown/.test(t) && /Find names/.test(t)), 'an unreadable one as not solved, time unknown');
    await b.until(`[...document.querySelectorAll('#recent img')].length === 1`, 5000, 'the broken thumbnail dropped');
    await ok(true, 'a thumbnail that cannot be made is left out, not shown broken');
    await b.chooseFile('#drop', [args.image]);
    await b.until(`!document.getElementById('details').hidden`, 3000, 'the details');
    await b.click('#go');
    await b.until(`!document.getElementById('werr').hidden`, 60000, 'the refusal');
    await ok(await b.js(`document.querySelectorAll('#werr li').length`) > 0, `the same photo again is refused, with the reasons (${(await b.text('#werr')).slice(0, 80)})`);
    await ok(await b.visible('#force') && await b.js(`document.activeElement.id === 'force'`), '"Name it anyway" is offered and has the focus');
    await b.click('#force');
    await b.until(ready, 120000, 'the viewer after "Name it anyway"');
    await ok(true, '"Name it anyway" names it and opens the viewer');
    await b.click('#otherImage');
    await b.until(`location.pathname === '/app' && document.querySelectorAll('#recent li').length === 2`, 10000, 'the launcher');
    await b.until(`[...document.querySelectorAll('#recent img')].length === 1`, 5000, 'the broken thumbnail dropped again');
    await b.click('#recent li:not(:has(img)) .btn');
    await b.until(`!document.getElementById('werr').hidden`, 60000, 'the error for the unreadable photo');
    await ok(true, '"Find names" on the unreadable photo runs and reports the error');
    await b.click('#again');
    await b.until(`document.querySelectorAll('#recent li').length === 2`, 5000, 'the list');
    // reset() rebuilt the list with fresh <img>s, the unreadable photo's included: until its thumbnail request
    // fails and onerror drops it, li:has(img) matches that row too (and it is the newer file, so listed first).
    // Clicking it runs a locate that fails instead of opening a viewer. Same wait as after #otherImage above.
    await b.until(`[...document.querySelectorAll('#recent img')].length === 1`, 5000, 'the broken thumbnail dropped again');
    await b.click('#recent li:has(img) .meta');
    await b.until(ready, 30000, 'the viewer from the list row');
    await ok(true, 'a click on the row itself opens the photo');
  },

  async quit(b, ok) {
    await b.goto(BASE + '/app');
    await b.click('#folder');
    await sleep(300);
    await ok(true, 'the folder link can be clicked');
    await b.click('#quit');
    await b.until(`/has stopped/.test(document.querySelector('main').textContent)`, 5000, 'the stopped page');
    await ok(true, 'Quit stops LunarAtlas and says the tab can be closed');
  },
};

if (!J[name]) { console.log(`FAIL unknown journey ${name}`); process.exit(1); }
// Chrome and Edge through their own protocol (LUNARATLAS_CHROME); Firefox and Safari through their WebDriver
const driver = process.env.LUNARATLAS_WEBDRIVER;
const launch = driver && ((out) => WebDriverBrowser.launch(driver, process.env.LUNARATLAS_BROWSER, out));
const fails = await runJourney(name, J[name], { chrome: process.env.LUNARATLAS_CHROME, launch, out: OUT, base: BASE });
process.exit(fails ? 1 : 0);
