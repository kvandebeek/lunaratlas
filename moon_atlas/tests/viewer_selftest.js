/* Viewer self-test: served only at /selftest; drives the real page with synthetic input and writes results
   into <pre id="selftest">. Run: moon_atlas.py view IMAGE --no-open, then headless Chrome --dump-dom /selftest.

   With no query string it runs the whole set. /selftest?group=NAME runs one group on its own, which is how
   tests/test_e2e_journeys.py drives a single journey and reports its result quickly. Every group leaves the
   sidecar as it found it, so the groups can run in any order. */
(async () => {
  const out = [], ok = (c, m) => out.push((c ? 'PASS ' : 'FAIL ') + m);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const cv = document.getElementById('map'), T = window.__atlas;
  const ev = (type, x, y, extra = {}) => cv.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, pointerId: 1, ...extra }));
  const key = (k, extra = {}) => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...extra }));
  const drag = async (x0, y0, x1, y1) => { ev('pointerdown', x0, y0); for (let i = 1; i <= 6; i++) { ev('pointermove', x0 + (x1 - x0) * i / 6, y0 + (y1 - y0) * i / 6); await wait(20); } ev('pointerup', x1, y1); await wait(60); };
  const click = async (x, y) => { ev('pointerdown', x, y); ev('pointerup', x, y); await wait(60); };
  const type = (id, text) => { const el = document.getElementById(id); el.value = text; el.dispatchEvent(new Event('input', { bubbles: true })); };

  const GROUPS = {
    // what the page has once it has loaded: the whole gazetteer, one label per name, all on the canvas
    async load() {
      ok(!!T, 'the page exposes its state for the tests');
      ok(window.ATLAS.features.length > 1000, `the gazetteer reached the page (${window.ATLAS.features.length} features)`);
      // the names are laid out after the edits have been fetched, so wait for that rather than for a fixed time
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      ok(T.placed.length > 20, `${T.placed.length} names placed`);
      ok(T.placed.some((p) => p.f.c === 'crater'), 'craters are named too');
      ok(T.placed.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)), 'every label has a finite place');
      ok(T.placed.every((p) => p.x >= 0 && p.x <= innerWidth && p.y >= 0 && p.y <= innerHeight), 'every label is on the canvas');
      const names = new Set(T.placed.map((p) => p.f.n));
      ok(names.size === T.placed.length, `no name is placed twice (${names.size} distinct of ${T.placed.length})`);
      ok(T.edits && Array.isArray(T.edits.shapes), 'the edits are loaded');
      ok(T.edits.shapes.length === 0, 'a fresh image starts with no drawings');
    },

    // the search box: a real name is offered, a name that does not exist is not
    async search() {
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      type('q', 'Tycho'); await wait(400);
      const hits = document.getElementById('results').textContent;
      ok(/Tycho/i.test(hits), `the search box offers Tycho ("${hits.trim().slice(0, 40)}")`);
      type('q', 'No Such Crater'); await wait(400);
      ok(!/Tycho/i.test(document.getElementById('results').textContent), 'an unknown name is not offered');
      ok(T.edits && Array.isArray(T.edits.shapes), 'searching does not disturb the drawings');
      ok(T.edits.shapes.length === 0, 'and none were made by searching');
      type('q', ''); await wait(200);
    },

    // zooming and the layers panel: names follow the zoom, a layer off really removes its names, and the
    // choice is kept in the edits for the export
    async layers() {
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      const before = T.placed.length;
      key('+'); key('+'); key('+'); await wait(300); T.render();
      ok(T.view.s > 1, `zoomed in (${T.view.s.toFixed(2)}x)`);
      ok(T.placed.length >= before, `no names are lost when zooming in (${before} then ${T.placed.length})`);
      const box = document.getElementById('l-lettered');
      box.checked = false; box.dispatchEvent(new Event('change', { bubbles: true }));
      await wait(300); T.render();
      ok(!T.placed.some((p) => p.f.c === 'lettered'), 'turning a layer off removes its names');
      key('f'); await wait(300); T.render();
      ok(T.placed.length > 0, 'fitting the whole disk brings the names back');
      ok(T.edits.style && Array.isArray(T.edits.style.layers) && !T.edits.style.layers.includes('lettered'),
         'the layer choice is kept in the edits');
      box.checked = true; box.dispatchEvent(new Event('change', { bubbles: true })); await wait(200);
    },

    // a measurement end to end: drawn, undone, redone, undone, and the sidecar left as it was
    async measure() {
      const n0 = T.edits.shapes.length;
      key('m'); await click(600, 500); await click(900, 540);
      const m = T.edits.shapes.at(-1);
      ok(m && m.kind === 'measure' && m.a && m.b, 'a measurement was made');
      const span = m && m.a && m.b ? Math.hypot(m.b.x - m.a.x, m.b.y - m.a.y) : 0;
      ok(span > 100, `it spans the disk (${span.toFixed(0)} px)`);
      key('v'); await wait(50);
      key('z', { metaKey: true }); await wait(100);
      ok(T.edits.shapes.length === n0, 'undo removes it');
      key('z', { metaKey: true, shiftKey: true }); await wait(100);
      ok(T.edits.shapes.length === n0 + 1, 'redo brings it back');
      key('z', { metaKey: true }); await wait(500);
      const saved = await (await fetch('/edits')).json();
      ok(saved.shapes.length === n0, `the sidecar holds ${saved.shapes.length} drawings after the undo`);
      ok(document.getElementById('n-mine').textContent === String(n0), 'the counter in the page agrees');
    },
  };

  const only = new URLSearchParams(location.search).get('group');
  try {
    await wait(1500);
    if (only) {
      if (GROUPS[only]) await GROUPS[only](); else ok(false, `unknown group ${only}`);
    } else {
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
      // the offset is kept from the label's first spot (home), which is not where it sat if that spot was taken
      const o = T.edits.labels[lab.f.n], wx = lab.x + 40 - lab.home[0], wy = lab.y + 25 - lab.home[1];
      ok(o && Math.abs(o.dx * T.view.s - wx) < 3 && Math.abs(o.dy * T.view.s - wy) < 3, `label ${lab.f.n} moved by 40, 25 screen px (offset from its home ${o && (o.dx * T.view.s).toFixed(1)}, ${o && (o.dy * T.view.s).toFixed(1)}; expected ${wx.toFixed(1)}, ${wy.toFixed(1)})`);
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
    }
  } catch (e) { ok(false, 'exception ' + e.message); }
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = out.join('\n'); document.body.appendChild(pre);
})();
