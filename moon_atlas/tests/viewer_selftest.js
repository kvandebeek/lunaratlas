/* Viewer self-test: served only at /selftest; drives the real page with synthetic input and writes results
   into <pre id="selftest">. Run: moon_atlas.py view IMAGE --no-open, then headless Chrome --dump-dom /selftest. */
(async () => {
  const out = [], ok = (c, m) => out.push((c ? 'PASS ' : 'FAIL ') + m);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const cv = document.getElementById('map'), T = window.__atlas;
  const ev = (type, x, y, extra = {}) => cv.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, pointerId: 1, ...extra }));
  const key = (k, extra = {}) => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...extra }));
  const drag = async (x0, y0, x1, y1) => { ev('pointerdown', x0, y0); for (let i = 1; i <= 6; i++) { ev('pointermove', x0 + (x1 - x0) * i / 6, y0 + (y1 - y0) * i / 6); await wait(20); } ev('pointerup', x1, y1); await wait(60); };
  const click = async (x, y) => { ev('pointerdown', x, y); ev('pointerup', x, y); await wait(60); };
  try {
    await wait(1500);
    const n0 = T.edits.shapes.length;
    key('c'); await drag(700, 480, 760, 480);
    ok(T.edits.shapes.length === n0 + 1 && T.edits.shapes.at(-1).kind === 'circle', `circle drawn (${T.edits.shapes.length} shapes)`);
    document.getElementById('aOk').click(); await wait(50);
    key('z', { metaKey: true }); await wait(50);
    ok(T.edits.shapes.length === n0, `undo removes it (${T.edits.shapes.length})`);
    key('z', { metaKey: true, shiftKey: true }); await wait(50);
    ok(T.edits.shapes.length === n0 + 1, `redo brings it back (${T.edits.shapes.length})`);
    key('z', { metaKey: true }); await wait(50);
    key('v'); await wait(50);
    const lab = T.placed.find((p) => p.f.c === 'crater' && !T.edits.labels[p.f.n]);
    if (lab) {
      await drag(lab.x, lab.y, lab.x + 40, lab.y + 25);
      const o = T.edits.labels[lab.f.n];
      ok(o && Math.abs(o.dx * T.view.s - 40) < 3 && Math.abs(o.dy * T.view.s - 25) < 3, `label ${lab.f.n} moved by 40, 25 screen px (${o && (o.dx * T.view.s).toFixed(1)}, ${o && (o.dy * T.view.s).toFixed(1)})`);
      T.render();
      const again = T.placed.find((p) => p.f === lab.f);
      ok(again && Math.abs(again.x - lab.x - 40) < 3 && Math.abs(again.y - lab.y - 25) < 3,
         `moved label is drawn at the new place (${again ? (again.x - lab.x).toFixed(1) + ', ' + (again.y - lab.y).toFixed(1) : 'not placed'})`);
      key('z', { metaKey: true }); await wait(50);
      ok(!T.edits.labels[lab.f.n], 'undo puts the label back');
    } else ok(false, 'no crater label to drag');
    key('m'); await click(600, 520); await click(900, 540);
    const m = T.edits.shapes.at(-1);
    ok(m && m.kind === 'measure' && m.b, `measurement saved (${T.edits.shapes.length} shapes)`);
    key('v'); await wait(50);
    // drag the measurement's line: it moves
    const mx = (600 + 900) / 2, my = (520 + 540) / 2, ax = m.a.x;
    await drag(mx, my, mx + 30, my);
    ok(Math.abs((m.a.x - ax) * T.view.s - 30) < 3, 'measurement dragged along');
    key('z', { metaKey: true }); await wait(50); key('z', { metaKey: true }); await wait(50);
    ok(T.edits.shapes.length === n0, `two undos remove drag and measurement (${T.edits.shapes.length})`);
    await wait(500);
    const saved = await (await fetch('/edits')).json();
    ok(saved.shapes.length === n0, `sidecar holds ${saved.shapes.length} shapes after saving`);
  } catch (e) { ok(false, 'exception ' + e.message); }
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = out.join('\n'); document.body.appendChild(pre);
})();
