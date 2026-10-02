/* Viewer self-test: served only at /selftest; drives the real page with synthetic input and writes results
   into <pre id="selftest">. Run: lunaratlas.py view IMAGE --no-open, then headless Chrome --dump-dom /selftest.

   With no query string it runs the whole set. /selftest?group=NAME runs one group on its own, which is how
   tests/test_e2e_journeys.py drives a single journey and reports its result quickly. Every group leaves the
   sidecar as it found it, so the groups can run in any order. */
(async () => {
  const out = [], ok = (c, m) => out.push((c ? 'PASS ' : 'FAIL ') + m);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  for (let i = 0; i < 200 && !window.__atlas; i++) await wait(50);      // boot.js fetches the data, then starts the page
  const cv = document.getElementById('map'), T = window.__atlas;
  const ev = (type, x, y, extra = {}) => cv.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, pointerId: 1, ...extra }));
  const key = (k, extra = {}) => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...extra }));
  const drag = async (x0, y0, x1, y1) => { ev('pointerdown', x0, y0); for (let i = 1; i <= 6; i++) { ev('pointermove', x0 + (x1 - x0) * i / 6, y0 + (y1 - y0) * i / 6); await wait(20); } ev('pointerup', x1, y1); await wait(60); };
  const click = async (x, y) => { ev('pointerdown', x, y); ev('pointerup', x, y); await wait(60); };
  const type = (id, text) => { const el = document.getElementById(id); el.value = text; el.dispatchEvent(new Event('input', { bubbles: true })); };

  // where the page stood, for a failure message: slow machines have failed here with nothing placed
  const diag = () => `fonts ${document.fonts.status}, edits ${T.edits ? 'loaded' : 'missing'}, ${T.placed.length} placed, zoom ${T.view.s.toFixed(2)}, window ${innerWidth}x${innerHeight}`;

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
      // the page re-fits once its fonts have loaded; zoom only after that, or the late fit undoes the zoom
      await Promise.race([document.fonts.ready, wait(5000)]); await wait(500);
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

    // Alt/⌥ picks several names (click toggles one, a drag takes a box); Delete hides them all as one undo step
    async picks() {
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      key('v'); T.render();
      const alt = { altKey: true };
      const altClick = async (x, y) => { ev('pointerdown', x, y, alt); ev('pointerup', x, y, alt); await wait(60); T.render(); };
      const [a, b] = [T.placed[0], T.placed.find((p) => Math.hypot(p.x - T.placed[0].x, p.y - T.placed[0].y) > 60)];
      ok(!!a && !!b, 'two names apart to pick');
      await altClick(a.x, a.y); await altClick(b.x, b.y);
      ok(T.picks.size === 2 && T.picks.has(a.f.n) && T.picks.has(b.f.n), `Alt-click: two names picked (${[...T.picks.keys()].join(', ')})`);
      await altClick(a.x, a.y);
      ok(T.picks.size === 1 && !T.picks.has(a.f.n), 'a second Alt-click takes a name out again');
      await altClick(a.x, a.y);
      const bar = document.getElementById('picks');
      ok(!bar.hidden && /2 selected/.test(bar.textContent), `the bar says "${bar.textContent.trim().split('\n')[0]}"`);
      const h0 = T.hidden.size;
      key('Delete'); await wait(60); T.render();
      ok(T.hidden.size === h0 + 2 && T.hidden.has(a.f.n) && T.hidden.has(b.f.n), 'Delete hides both');
      ok(T.picks.size === 0 && getComputedStyle(bar).display === 'none', 'and clears the selection, the bar gone from the screen');
      ok(!T.placed.some((p) => p.f.n === a.f.n || p.f.n === b.f.n), 'hidden names are no longer drawn');
      key('z', { metaKey: true }); await wait(60); T.render();
      ok(T.hidden.size === h0, 'one undo brings both back');
      ev('pointerdown', 5, 5, alt);
      for (let i = 1; i <= 6; i++) { ev('pointermove', 5 + (innerWidth - 10) * i / 6, 5 + (innerHeight - 10) * i / 6, alt); await wait(20); }
      ev('pointerup', innerWidth - 5, innerHeight - 5, alt); await wait(60); T.render();
      ok(T.placed.length > 0 && T.placed.every((p) => T.picks.has(p.f.n)), `an Alt-drag over everything picks every placed name (${T.picks.size} picked, ${T.placed.length} placed)`);
      key('Escape'); await wait(60);
      ok(T.picks.size === 0 && bar.hidden, 'Escape clears the selection');
      ok(T.hidden.size === h0, 'and hides nothing');
    },

    // the switch itself turns a layer off and on, not only its label
    async switches() {
      // not just T.placed.length === 0: if names are placed incrementally, the first few on screen may all be
      // non-craters, and the very next line needs a crater specifically to be among them
      for (let i = 0; i < 60 && !T.placed.some((p) => p.f.c === 'crater'); i++) await wait(200);
      const inp = document.getElementById('l-crater'), pill = inp.nextElementSibling;
      // the state is in the message because this has failed on CI (macOS) with the later checks, which assert the
      // same crater condition, passing -- and nothing said whether the switch was off or no crater was placed yet
      const nCrater = T.placed.filter((p) => p.f.c === 'crater').length;
      ok(inp.checked && nCrater > 0, `craters are on and named (switch ${inp.checked ? 'on' : 'off'}, ${nCrater} crater names of ${T.placed.length} placed; ${diag()})`);
      pill.click(); await wait(60); T.render();
      ok(!inp.checked, 'a click on the switch turns craters off');
      ok(!T.placed.some((p) => p.f.c === 'crater'), 'and their names go');
      pill.click(); await wait(60); T.render();
      ok(inp.checked && T.placed.some((p) => p.f.c === 'crater'), 'a second click turns them on again');
    },

    // the crater card never covers the layers panel: in a short window the panel folds while the card is open,
    // and unfolds when it closes; a panel the user folded stays folded
    async card() {
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      key('v'); T.render();
      const lay = document.getElementById('layers'), card = document.getElementById('info');
      const p = T.placed.find((q) => q.x < innerWidth - 420 && q.x > 120 && q.y > 100 && q.y < innerHeight - 100);
      ok(!!p, 'a name away from the panels to click');
      const covers = () => { const a = lay.getBoundingClientRect(), b = card.getBoundingClientRect();
        return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom; };
      await click(p.x, p.y);
      ok(!card.hidden, `a click on ${p.f.n} opens its card`);
      ok(!covers(), `the card does not cover the layers panel (panel ${lay.classList.contains('collapsed') ? 'folded' : 'open'})`);
      document.getElementById('infoClose').click(); await wait(60);
      ok(card.hidden && !lay.classList.contains('collapsed'), 'closing the card brings the layers panel back');
      document.getElementById('layersHead').click(); await wait(60);
      await click(p.x, p.y);
      document.getElementById('infoClose').click(); await wait(60);
      ok(lay.classList.contains('collapsed'), 'a panel the user folded stays folded');
      document.getElementById('layersHead').click(); await wait(60);
    },

    // the fixes from BUGS_AND_DESIGN_CHOICES.md: lettered craters follow the craters, a moved name keeps its line,
    // a dashed arrow keeps a solid head, a click on a saved measurement with the Measure tool picks it up
    async fixes() {
      for (let i = 0; i < 60 && T.placed.length === 0; i++) await wait(200);
      const strokes = [], P = CanvasRenderingContext2D.prototype, stroke0 = P.stroke;
      P.stroke = function () { strokes.push({ dash: this.getLineDash().join(','), style: String(this.strokeStyle) }); return stroke0.apply(this, arguments); };
      try {
        const cr = document.getElementById('l-crater'), le = document.getElementById('l-lettered');
        cr.checked = false; cr.dispatchEvent(new Event('change', { bubbles: true })); await wait(60); T.render();
        ok(le.disabled && le.closest('.row').classList.contains('off'), 'craters off: the lettered switch is greyed out');
        ok(le.checked && !T.placed.some((p) => p.f.c === 'lettered'), 'its own setting is kept, but no lettered names are drawn');
        cr.checked = true; cr.dispatchEvent(new Event('change', { bubbles: true })); await wait(60); T.render();
        ok(!le.disabled && !le.closest('.row').classList.contains('off'), 'craters on: the lettered switch works again');

        key('v'); await wait(50); T.render();
        const lab = T.placed.find((p) => p.f.c === 'crater' && !T.edits.labels[p.f.n] && p.x > 150 && p.x < innerWidth - 450 && p.y > 150 && p.y < innerHeight - 150);
        ok(!!lab, 'a crater name to move');
        if (lab) {
          await drag(lab.x, lab.y, lab.x + 60, lab.y + 50);
          strokes.length = 0; T.render();
          ok(strokes.some((s) => s.dash === '4,3'), 'after letting go, the moved name keeps its dashed line to the feature');
          key('z', { metaKey: true }); await wait(50);
        }

        const arrow = { kind: 'arrow', x0: 0, y0: 0, x1: 0, y1: 0, colour: '#123456', size: 1, dash: true };
        const [ix, iy] = [T.view.x, T.view.y]; Object.assign(arrow, { x0: ix - 50, y0: iy, x1: ix + 50, y1: iy });
        T.edits.shapes.push(arrow); strokes.length = 0; T.render();
        const mine = strokes.filter((s) => s.style === '#123456');
        ok(mine.some((s) => s.dash !== '') && mine.some((s) => s.dash === ''), `a dashed arrow: dashed shaft, solid head (${mine.map((s) => s.dash || 'solid').join(' / ')})`);
        T.edits.shapes.pop(); T.render();

        const n0 = T.edits.shapes.length;
        key('m'); await click(600, 500); await click(900, 540);
        ok(T.edits.shapes.length === n0 + 1, 'a measurement was made');
        await click(750, 520);
        const pan = document.querySelector('#tools button[data-tool="pan"]');
        ok(pan.getAttribute('aria-pressed') === 'true', 'a click on it with the Measure tool switches to Pan and select');
        ok(T.edits.shapes.length === n0 + 1, 'and starts no new measurement');
        key('Escape'); await wait(50);
        key('z', { metaKey: true }); await wait(500);
        ok(T.edits.shapes.length === n0, 'undo removes the measurement again');
      } finally { P.stroke = stroke0; }
    },
  };

  const only = new URLSearchParams(location.search).get('group');
  try {
    // names are laid out after the edits have been fetched, so wait for that rather than for a fixed time (a
    // loaded CI machine can still be laying labels out well past a blind 1.5s, unlike GROUPS.load()'s own wait)
    await Promise.race([document.fonts.ready, wait(5000)]);
    // the page draws from a requestAnimationFrame; where no frame ever comes (or one throws), nothing is placed
    // however long this waits, so say whether frames come and ask for a drawing directly
    let frames = 0, drawError = '';
    const tick = () => { frames++; requestAnimationFrame(tick); }; requestAnimationFrame(tick);
    for (let i = 0; i < 60 && T.placed.length === 0; i++) {
      await wait(200);
      if (i % 5 === 4 && T.placed.length === 0) { try { T.render(); } catch (e) { drawError = String(e && e.stack || e).slice(0, 300); } }
    }
    if (T.placed.length === 0) ok(false, `no name was placed at the start (${diag()}, ${frames} animation frames, render ${drawError ? 'threw ' + drawError : 'did not throw'})`);
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
    } else ok(false, `no crater label to drag (${diag()})`);
    key('m'); await click(600, 520); await click(900, 540);
    const m = T.edits.shapes.at(-1);
    ok(m && m.kind === 'measure' && m.b, `measurement saved (${T.edits.shapes.length} shapes)`);
    key('v'); await wait(50);
    // drag the measurement's line: it moves
    // grab the line where no name or crater sits on it: a label there takes the drag instead (the fonts differ
    // by platform, so the names fall on different spots)
    const at = (t) => [600 + 300 * t, 520 + 20 * t];
    const free = [0.5, 0.4, 0.6, 0.3, 0.7, 0.35, 0.65, 0.45, 0.55, 0.25, 0.75].find((t) => !T.hitFeature(...at(t)));
    const [mx, my] = at(free ?? 0.5), ax = m.a.x;
    await drag(mx, my, mx + 30, my);
    ok(Math.abs((m.a.x - ax) * T.view.s - 30) < 3,
       `measurement dragged along (moved ${((m.a.x - ax) * T.view.s).toFixed(1)} of 30 px, grabbed at ${mx.toFixed(0)},${my.toFixed(0)}, ${free === undefined ? 'no free spot on the line' : 'a free spot'})`);
    key('z', { metaKey: true }); await wait(50); key('z', { metaKey: true }); await wait(50);
    ok(T.edits.shapes.length === n0, `two undos remove drag and measurement (${T.edits.shapes.length})`);
    await wait(500);
    const saved = await (await fetch('/edits')).json();
    ok(saved.shapes.length === n0, `sidecar holds ${saved.shapes.length} shapes after saving`);
    }
  } catch (e) { ok(false, 'exception ' + e.message); }
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = out.join('\n'); document.body.appendChild(pre);
})();
