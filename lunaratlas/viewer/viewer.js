/* LunarAtlas viewer and editor. Data: window.ATLAS (/data.json, fetched by boot.js); edits live in IMAGE.atlas.json (GET/POST /edits). */
(() => {
  'use strict';
  const A = window.ATLAS;
  const G = A.geometry;
  const RM = A.R_moon;
  const $ = (s) => document.querySelector(s);
  const canvas = $('#map');
  let ctx = canvas.getContext('2d');           // swapped for the export preview's canvas while that draws
  let dpr = 1, VW = 0, VH = 0, offscreen = false;
  // colours from theme.css (one set of tokens for the page and the canvas)
  const css = getComputedStyle(document.documentElement), tok = (n, d) => css.getPropertyValue(n).trim() || d;
  const C = { accent: tok('--accent', '#F5A742'), grid: tok('--grid-line', 'rgba(143,216,236,.3)'), gridLabel: tok('--grid-label', 'rgba(143,216,236,.9)'),
              bg0: tok('--bg-0', '#0A0F25'), bg1: tok('--bg-1', '#111934'), text: tok('--text', '#FCF8EE'), text2: tok('--text-2', '#B7BFD8'),
              halo: tok('--halo', 'rgba(5,8,20,.72)') };
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
  const NIGHT_DIM = 0.3;                       // 'dim' names on the night side (atlas_render.NIGHT_DIM)

  // ------------------------------------------------------------ geometry (port of atlas_geo.Geometry)
  const det = G.A[0][0] * G.A[1][1] - G.A[0][1] * G.A[1][0];
  const Ai = [[G.A[1][1] / det, -G.A[0][1] / det], [-G.A[1][0] / det, G.A[0][0] / det]];
  const rad = Math.PI / 180;
  const F = (() => {
    const a = G.lat0 * rad, b = G.lon0 * rad;
    const e = [Math.cos(a) * Math.cos(b), Math.cos(a) * Math.sin(b), Math.sin(a)];
    const u = [-Math.sin(b), Math.cos(b), 0];
    const v = [e[1] * u[2] - e[2] * u[1], e[2] * u[0] - e[0] * u[2], e[0] * u[1] - e[1] * u[0]];
    return { e, u, v };
  })();
  const dot = (p, q) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
  function corr(sx, sy) {
    if (!G.coef) return [0, 0];
    const r = Math.hypot(sx, sy), k = r > G.rmax ? G.rmax / Math.max(r, 1e-9) : 1;
    sx *= k; sy *= k;
    let cx = 0, cy = 0, n = 0;
    for (let i = 0; i <= G.deg; i++) for (let j = 0; j <= G.deg - i; j++) {
      const t = Math.pow(sx, i) * Math.pow(sy, j);
      cx += t * G.coef[n][0]; cy += t * G.coef[n][1]; n++;
    }
    return [cx, cy];
  }
  function toSky(x, y) {
    let xm = x, ym = y, sx = 0, sy = 0;
    for (let it = 0; it < (G.coef ? 4 : 1); it++) {
      const dx = xm - G.t[0], dy = ym - G.t[1];
      sx = Ai[0][0] * dx + Ai[0][1] * dy; sy = Ai[1][0] * dx + Ai[1][1] * dy;
      const c = corr(sx, sy); xm = x - c[0]; ym = y - c[1];
    }
    return [sx, sy];
  }
  function toLatLon(x, y) {
    const [sx, sy] = toSky(x, y), D = G.dist;
    const O = [D * F.e[0], D * F.e[1], D * F.e[2]];
    const d = [0, 1, 2].map((i) => sx * F.u[i] + sy * F.v[i] - O[i]);
    const dd = dot(d, d), od = dot(d, O), disc = od * od - dd * (D * D - 1);
    if (disc < 0) return null;
    const s = (-od - Math.sqrt(disc)) / dd;
    const p = [0, 1, 2].map((i) => O[i] + s * d[i]);
    return { lat: Math.asin(Math.max(-1, Math.min(1, p[2]))) / rad, lon: Math.atan2(p[1], p[0]) / rad, p };
  }
  function toImage(p) {            // unit vector -> image px
    const D = G.dist, z = dot(p, F.e), k = D / (D - z);
    const sx = dot(p, F.u) * k, sy = dot(p, F.v) * k, c = corr(sx, sy);
    return [G.A[0][0] * sx + G.A[0][1] * sy + G.t[0] + c[0], G.A[1][0] * sx + G.A[1][1] * sy + G.t[1] + c[1], z];
  }
  const gcKm = (p, q) => Math.acos(Math.max(-1, Math.min(1, dot(p, q)))) * RM;

  // ------------------------------------------------------------ edits (saved in the sidecar) + undo
  const LAYERS5 = ['area', 'crater', 'lettered', 'relief', 'landing'];
  const shown = (l) => set[l] && (l !== 'lettered' || set.crater);   // lettered craters go with the craters
  let E = { shapes: [], hidden: [], labels: {}, style: {} };
  let hiddenSet = new Set();
  const view = { s: 1, x: A.width / 2, y: A.height / 2 };
  const set = { area: true, crater: true, lettered: true, relief: true, landing: true, rims: false, grid: false, mine: true,
                night: 'dim', minPx: 24, fs: 1, font: 'IBM Plex Sans' };
  const undo = [], redo = [];
  const snap = () => JSON.stringify({ shapes: E.shapes, hidden: [...hiddenSet], labels: E.labels });
  function change(fn) {                       // every edit goes through here: undo point, apply, save
    undo.push(snap()); if (undo.length > 200) undo.shift(); redo.length = 0;
    fn(); save(); redraw();
  }
  function restore(json) { const o = JSON.parse(json); E.shapes = o.shapes; E.labels = o.labels; hiddenSet = new Set(o.hidden); save(); redraw(); }
  function doUndo() { if (!undo.length) { toast('Nothing to undo'); return; } closeEditor(true); redo.push(snap()); restore(undo.pop()); if (selected) select(selected); toast('Undone'); }
  function doRedo() { if (!redo.length) { toast('Nothing to redo'); return; } closeEditor(true); undo.push(snap()); restore(redo.pop()); if (selected) select(selected); toast('Redone'); }
  let saveT = null, dirty = false, inflight = 0, chain = Promise.resolve();
  let rev = Date.now();                       // every save is numbered (later than any earlier page's): the server drops a late one
  function body() {
    E.hidden = [...hiddenSet];
    E.style = { font: set.font, minPx: set.minPx, fs: set.fs, night: set.night, grid: set.grid, rims: set.rims,
                layers: LAYERS5.filter((l) => set[l]) };
    return JSON.stringify({ ...E, rev: ++rev });
  }
  // One save after the other, each with the edits as they are when it starts. Rejects when the edits could not be saved.
  function post() {
    const send = () => {
      dirty = false; inflight++;
      return fetch('/edits', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body() })
        .finally(() => { inflight--; })
        .then((r) => { if (!r.ok && r.status !== 409) throw new Error(r.status); $('#saveState').textContent = 'saved'; })   // 409: a newer one is there
        .catch((e) => { dirty = true; $('#saveState').textContent = 'not saved — is lunaratlas view still running?'; throw e; });
    };
    const p = chain.then(send, send);
    chain = p.catch(() => {});
    return p;
  }
  function save() {
    $('#n-mine').textContent = E.shapes.length;
    $('#saveState').textContent = 'saving…';
    dirty = true;
    clearTimeout(saveT);
    saveT = setTimeout(() => { saveT = null; post().catch(() => {}); }, 300);
  }
  const flush = () => { clearTimeout(saveT); saveT = null; return post(); };
  // Leaving the page (a reload, a closed tab, the link to the launcher) must not lose an edit still waiting for its timer.
  // The request sent while leaving may still be on its way when the page loads again: the edits are also kept here, and
  // the next load takes them up (and saves them again, which is harmless when the server has them already).
  const PENDING = 'lunaratlas.pending.' + A.tiles_v;
  function leave() {
    if (!dirty && !saveT && !inflight) return;                        // a save still on its way may be cut off by the leaving
    clearTimeout(saveT); saveT = null; dirty = false;
    const b = body();
    try { localStorage.setItem(PENDING, b); } catch { /* no storage: the request below is all there is */ }
    try { fetch('/edits', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: b, keepalive: b.length < 60000 }).catch(() => {}); } catch { /* too large to send while leaving */ }
  }
  addEventListener('pagehide', leave);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') leave(); });
  $('#otherImage').addEventListener('click', (e) => { e.preventDefault(); const go = () => { location.href = '/app'; }; flush().then(go, go); });

  // ------------------------------------------------------------ features
  const FE = A.features;
  const RANK = { area: 0, crater: 1, relief: 2, site: 2, landing: 3, lettered: 4, apollo: 5 };
  const LAYER = { area: 'area', crater: 'crater', lettered: 'lettered', apollo: 'lettered', relief: 'relief', site: 'relief', landing: 'landing' };
  for (const f of FE) f.dpx = f.d / RM * A.radius_px;
  const ORDER = FE.slice().sort((a, b) => (RANK[a.c] - RANK[b.c]) || (b.d - a.d));
  const LABEL = '#fff4e2';                  // one colour for every name; maria differ by size and spacing
  const TYPE_NAME = { area: 'Mare / lake / bay', crater: 'Crater', lettered: 'Satellite crater', apollo: 'Apollo site feature', relief: 'Relief', site: 'Statio', landing: 'Landing site' };
  const count = {};
  for (const f of FE) { const l = LAYER[f.c]; count[l] = (count[l] || 0) + 1; }
  for (const k of LAYERS5) $('#n-' + k).textContent = count[k] || 0;
  $('#fileName').textContent = A.image;
  if (A.sky) { const sky = $('#skyLine'); sky.textContent = A.sky.split(' · ')[0]; sky.title = A.sky; }     // phase, Sun, colongitude at the capture time
  $('#q').placeholder = `Search ${FE.length} names`;

  // ------------------------------------------------------------ tiles
  const LV = A.levels, TILE = A.tile, cache = new Map();
  let loadingTiles = 0, tilesIdle = null;
  function tileDone() { if (--loadingTiles <= 0) { loadingTiles = 0; const f = tilesIdle; tilesIdle = null; if (f) f(); } }
  function tile(l, c, r) {
    const k = l + '/' + c + '_' + r;
    let im = cache.get(k);
    if (!im) {
      im = new Image();
      loadingTiles++;
      im.onload = () => { im.ok = true; tileDone(); redraw(); };
      im.onerror = tileDone;
      im.src = '/tiles/' + k + '.jpg?v=' + A.tiles_v;      // per image: the browser keeps tiles for a day
      cache.set(k, im);
      if (cache.size > 900) { const first = cache.keys().next().value; cache.delete(first); }
    }
    return im;
  }
  function drawLevel(l) {
    const f = Math.pow(2, l), step = TILE * f, lv = LV[l];
    const x0 = view.x - VW / 2 / view.s, y0 = view.y - VH / 2 / view.s, x1 = view.x + VW / 2 / view.s, y1 = view.y + VH / 2 / view.s;
    const c0 = Math.max(0, Math.floor(x0 / step)), c1 = Math.min(lv.cols - 1, Math.floor(x1 / step));
    const r0 = Math.max(0, Math.floor(y0 / step)), r1 = Math.min(lv.rows - 1, Math.floor(y1 / step));
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) {
      const im = tile(l, c, r);
      if (!im.ok) continue;
      const [sx, sy] = scr(c * step, r * step);
      ctx.drawImage(im, sx, sy, im.naturalWidth * f * view.s + 0.5, im.naturalHeight * f * view.s + 0.5);
    }
  }
  function drawTiles() {
    const want = Math.max(0, Math.min(LV.length - 1, Math.floor(Math.log2(1 / (view.s * dpr)))));
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    drawLevel(LV.length - 1);
    if (want + 2 < LV.length - 1) drawLevel(want + 2);
    if (want < LV.length - 1) drawLevel(want);
  }
  const scr = (x, y) => [(x - view.x) * view.s + VW / 2, (y - view.y) * view.s + VH / 2];
  const img = (sx, sy) => [(sx - VW / 2) / view.s + view.x, (sy - VH / 2) / view.s + view.y];

  // ------------------------------------------------------------ labels
  const fontStr = (w, size, it, fam) => `${it ? 'italic ' : ''}${w} ${size}px "${fam || set.font}", "IBM Plex Sans", system-ui, sans-serif`;
  function textW(txt, size, track) {
    if (!track) return ctx.measureText(txt).width;
    let w = 0; for (const ch of txt) w += ctx.measureText(ch).width;
    return w + track * size * (txt.length - 1);
  }
  function drawTxt(lab) {
    ctx.font = lab.font;
    let x = lab.x - lab.w / 2; const y = lab.y + lab.h / 2;
    if (!lab.track) { ctx.fillText(lab.text, x, y); return; }
    for (const ch of lab.text) { ctx.fillText(ch, x, y); x += ctx.measureText(ch).width + lab.track * lab.size; }
  }
  function ellBox(e) {
    const t = e[4] * rad, a = e[2] * view.s, b = e[3] * view.s;
    return [Math.hypot(a * Math.cos(t), b * Math.sin(t)), Math.hypot(a * Math.sin(t), b * Math.cos(t))];
  }
  const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  function layout() {
    const cell = 4, gw = Math.ceil(VW / cell) + 2, gh = Math.ceil(VH / cell) + 2, occ = new Uint8Array(gw * gh);
    const block = (x0, y0, x1, y1) => {
      const a0 = Math.max(0, Math.floor(x0 / cell)), a1 = Math.min(gw, Math.ceil(x1 / cell));
      for (let b = Math.max(0, Math.floor(y0 / cell)); b < Math.min(gh, Math.ceil(y1 / cell)); b++) occ.fill(1, b * gw + a0, b * gw + a1);
    };
    for (const el of offscreen ? [] : document.querySelectorAll('.panel, .popover')) {     // keep names clear of the UI
      if (el.hidden) continue;
      const r = el.getBoundingClientRect(); if (!r.width) continue;
      block(r.left - 6, r.top - 6, r.right + 6, r.bottom + 6);
    }
    const mine = new Set();
    if (set.mine) for (const s of E.shapes) if (s.label) {            // your own labels come first
      mine.add(norm(s.label.trim()));
      const [x, y] = shapeAnchor(s), px = Math.round(15 * (s.size || 1) * set.fs);
      ctx.font = fontStr(520, px, false, s.font);
      const w = ctx.measureText(s.label).width / 2 + 6, h = px * 0.6 + 4;
      block(x - w, y - h, x + w, y + h);
    }
    const [dcx, dcy] = scr(G.t[0], G.t[1]), R = A.radius_px * view.s;
    const minPx = set.minPx, fs = set.fs, kmPerScreenPx = A.km_per_px / view.s;
    const out = [];
    for (const f of ORDER) {
      const layer = LAYER[f.c];
      if (!shown(layer) || f.z < 0.1 || hiddenSet.has(f.n) || mine.has(f.key)) continue;
      let alpha = 1;
      if (f.lit < 0.12 && set.night !== 'show') { if (set.night === 'hide') continue; alpha = NIGHT_DIM; }
      const [X, Y] = scr(f.x, f.y);
      if (X < -250 || Y < -250 || X > VW + 250 || Y > VH + 250) continue;
      const ov = E.labels[f.n] || {};
      const D = f.dpx * view.s, k = Math.log2(Math.max(D, 1e-3) / minPx + 1);
      let size, w, it = false, track = 0, txt = f.n;
      if (f.c === 'area') { if (D < minPx * 0.3) continue; size = clamp(D * 0.05, 15, 34); w = 300; track = 0.22; txt = txt.toUpperCase(); }
      else if (f.c === 'crater') { if (D < minPx) continue; size = clamp(12 + 3.5 * k, 13, 26); w = 560; }
      else if (f.c === 'lettered' || f.c === 'apollo') { if (D < minPx) continue; size = clamp(10 + 2 * k, 11, 16); w = 420; }
      else if (f.c === 'landing') { if (kmPerScreenPx > 3) continue; size = 13; w = 520; }
      else { if (D < minPx * 1.5) continue; size = clamp(11 + 2.5 * k, 12, 20); w = 430; it = true; track = 0.02; }
      size = Math.round(size * fs * (ov.size || 1));
      const font = fontStr(w, size, it);
      ctx.font = font;
      const tw = textW(txt, size, track), th = size * 0.72;
      let spots;
      if (f.e && (f.c === 'crater' || f.c === 'lettered' || f.c === 'apollo')) {
        const [ex, ey] = scr(f.e[0], f.e[1]), [hx, hy] = ellBox(f.e), g = 4 * fs;
        spots = [[ex, ey + hy + g + th / 2], [ex, ey - hy - g - th / 2], [ex + hx + g + tw / 2, ey], [ex - hx - g - tw / 2, ey]];
      } else if (f.c === 'landing') {
        const g = 7 * fs; spots = [[X + g + tw / 2, Y], [X - g - tw / 2, Y], [X, Y + g + th / 2], [X, Y - g - th / 2]];
      } else spots = [[X, Y]];
      const home = spots[0], moved = ov.dx != null && ov.dy != null;
      if (moved) spots = [[home[0] + ov.dx * view.s, home[1] + ov.dy * view.s]];
      for (const [sx, sy] of spots) {
        const px = 3 + size * 0.12, py = 2 + size * 0.3;            // descenders and the soft shade belong to the name
        const bx0 = sx - tw / 2 - px, by0 = sy - th / 2 - py, bx1 = sx + tw / 2 + px, by1 = sy + th / 2 + py;
        if (!moved) {
          if (bx0 < 0 || by0 < 0 || bx1 > VW || by1 > VH) continue;
          let off = false;
          for (const [px, py] of [[bx0, by0], [bx1, by0], [bx0, by1], [bx1, by1]]) if (Math.hypot(px - dcx, py - dcy) > R * 0.995) { off = true; break; }
          if (off) continue;
          const a0 = Math.floor(bx0 / cell), b0 = Math.floor(by0 / cell), a1 = Math.floor(bx1 / cell) + 1, b1 = Math.floor(by1 / cell) + 1;
          let busy = false;
          for (let b = b0; b < b1 && !busy; b++) for (let a = a0; a < a1; a++) if (occ[b * gw + a]) { busy = true; break; }
          if (busy) continue;
        }
        block(bx0, by0, bx1, by1);
        out.push({ f, text: txt, font, size, track, x: sx, y: sy, w: tw, h: th, colour: ov.colour || LABEL, alpha, D, home, moved,
                   box: [bx0, by0, bx1, by1] });
        break;
      }
    }
    layout.occ = { occ, gw, gh, cell, block };                         // the grid labels go into the gaps
    return out;
  }

  function drawRim(f, alpha, width, colour) {
    const [ex, ey] = scr(f.e[0], f.e[1]);
    ctx.strokeStyle = colour || rgba(C.accent, 0.45 * alpha); ctx.lineWidth = width || 1;
    ctx.beginPath(); ctx.ellipse(ex, ey, f.e[2] * view.s, f.e[3] * view.s, f.e[4] * rad, 0, 2 * Math.PI); ctx.stroke();
  }
  let placed = [];
  const seen = new Map();                    // name -> when it (re)appeared: new names fade in instead of popping up
  const FADE = 220;
  function fadeOf(l, now) {
    if (offscreen) return 1;
    let t = seen.get(l.f.n);
    if (t == null) { t = now; seen.set(l.f.n, t); }
    return Math.min(1, (now - t) / FADE);
  }
  function drawLabels() {
    placed = layout();
    const now = performance.now();
    if (!offscreen) {                        // forget names that went away, so they fade in again when they return
      const on = new Set(placed.map((l) => l.f.n));
      for (const k of seen.keys()) if (!on.has(k)) seen.delete(k);
    }
    let fading = false;
    for (const l of placed) { l.fade = fadeOf(l, now); if (l.fade < 1) fading = true; }
    ctx.save();
    if (set.rims) for (const l of placed) if (l.f.e && l.D >= 8) drawRim(l.f, l.alpha * l.fade);
    for (const l of placed) if (l.moved && l.f !== (dragLabel && dragLabel.f)) {   // a moved name keeps a thin line to its feature
      const [X, Y] = scr(l.f.x, l.f.y), [x0, y0, x1, y1] = l.box, ex = clamp(X, x0, x1), ey = clamp(Y, y0, y1);
      if (Math.hypot(ex - X, ey - Y) < 6) continue;
      ctx.save(); ctx.globalAlpha = l.alpha * l.fade; ctx.beginPath(); ctx.moveTo(X, Y); ctx.lineTo(ex, ey);
      ctx.strokeStyle = 'rgba(0,0,0,0.45)'; ctx.lineWidth = 3; ctx.stroke();                          // a dark edge, so it reads on bright ground
      ctx.strokeStyle = rgba(C.accent, 0.95); ctx.lineWidth = 1.3; ctx.setLineDash([4, 3]); ctx.stroke(); ctx.restore();
    }
    for (const l of placed) if (l.f.c === 'landing') {
      const [X, Y] = scr(l.f.x, l.f.y);
      ctx.strokeStyle = l.colour; ctx.globalAlpha = l.alpha * l.fade; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(X, Y, 3.2 * set.fs, 0, 2 * Math.PI); ctx.stroke();
    }
    // a soft, wide shade and a tight one: legible on bright terrain without an outline
    for (const [blur, a] of [[7 * set.fs, 0.55], [2.2 * set.fs, 0.8]]) {
      ctx.shadowColor = C.halo.replace(/[\d.]+\)$/, a + ')'); ctx.shadowBlur = blur * dpr;
      for (const l of placed) {
        ctx.fillStyle = l.colour;
        ctx.globalAlpha = (l.f.c === 'lettered' ? 0.85 : 0.96) * l.alpha * l.fade;
        drawTxt(l);
      }
    }
    ctx.restore();
    if (dragLabel && !offscreen) {           // the label being moved: a thin line back to its feature
      const l = placed.find((p) => p.f === dragLabel.f);
      if (l) { const [X, Y] = scr(l.f.x, l.f.y); ctx.save(); ctx.strokeStyle = rgba(C.accent, 0.7); ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(X, Y); ctx.lineTo(l.x, l.y); ctx.stroke(); ctx.restore(); }
    }
    if (fading) redraw();
  }

  // ------------------------------------------------------------ grid
  let gridMarks = [];                       // candidate places for the degree labels, found while drawing the lines
  function drawGrid() {
    gridMarks = [];
    if (!set.grid) return;
    ctx.save();
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
    const best = new Map(), m = offscreen ? 4 : 70;
    for (const ln of A.grid) {
      ctx.beginPath();
      ln.pts.forEach(([x, y], i) => { const [sx, sy] = scr(x, y); i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy); });
      ctx.stroke();
      for (const [x, y] of ln.pts) {       // each line's label near the left (latitude) or bottom (longitude) edge
        const [sx, sy] = scr(x, y);
        if (sx < m || sy < (offscreen ? 4 : 80) || sx > VW - (offscreen ? 4 : 300) || sy > VH - m) continue;
        const k = ln.kind + ln.value;
        let c = best.get(k);
        if (!c) { c = []; c.ln = ln; best.set(k, c); }
        c.push({ d: ln.kind === 'lat' ? sx : VH - m - sy, sx, sy });
      }
    }
    ctx.restore();
    for (const c of best.values()) { c.sort((a, b) => a.d - b.d); gridMarks.push(c); }
  }
  function gridText(ln) {
    const v = ln.value;
    return ln.kind === 'lat' ? (v === 0 ? '0°' : `${Math.abs(v)}° ${v > 0 ? 'N' : 'S'}`) : (v === 0 || v === -180 ? `${Math.abs(v)}°` : `${Math.abs(v)}° ${v > 0 ? 'E' : 'W'}`);
  }
  function drawGridLabels() {              // after the names: into the free space only, never on top of a name or another label
    if (!set.grid || !gridMarks.length) return;
    const g = layout.occ, size = Math.round(11 * set.fs);
    ctx.save();
    ctx.font = fontStr(500, size, false); ctx.fillStyle = C.gridLabel;
    ctx.shadowColor = C.halo; ctx.shadowBlur = 4 * dpr;
    const free = (x0, y0, x1, y1) => {
      if (!g) return true;
      for (let b = Math.max(0, Math.floor(y0 / g.cell)); b < Math.min(g.gh, Math.ceil(y1 / g.cell)); b++)
        for (let a = Math.max(0, Math.floor(x0 / g.cell)); a < Math.min(g.gw, Math.ceil(x1 / g.cell)); a++) if (g.occ[b * g.gw + a]) return false;
      return true;
    };
    gridMarks.sort((a, b) => Math.abs(a.ln.value) - Math.abs(b.ln.value));   // the equator and the central meridian first
    for (const c of gridMarks) {
      const t = gridText(c.ln), w = ctx.measureText(t).width;
      for (const { sx, sy } of c.slice(0, 40)) {      // the best spot, else the next free one along the line
        const x0 = sx + 2, y0 = sy - 4 - size, x1 = sx + 8 + w, y1 = sy - 1;
        if (!free(x0, y0, x1, y1)) continue;
        if (g) g.block(x0 - 3, y0 - 3, x1 + 3, y1 + 3);
        ctx.fillText(t, sx + 4, sy - 4);
        break;
      }
    }
    ctx.restore();
  }

  // ------------------------------------------------------------ measurements (saved like drawings: kind 'measure')
  function geodesic(p, q, n = 48) {
    const om = Math.acos(Math.max(-1, Math.min(1, dot(p, q)))), so = Math.sin(om) || 1, pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, a = Math.sin((1 - t) * om) / so, b = Math.sin(t * om) / so;
      const r = om < 1e-9 ? p : [a * p[0] + b * q[0], a * p[1] + b * q[1], a * p[2] + b * q[2]];
      pts.push(toImage(r));
    }
    return pts;
  }
  function fmtKm(km) { return km >= 100 ? km.toFixed(0) + ' km' : km >= 10 ? km.toFixed(1) + ' km' : km.toFixed(2) + ' km'; }
  function measureKm(m) { const a = toLatLon(m.a.x, m.a.y), b = m.b && toLatLon(m.b.x, m.b.y); return a && b ? { km: gcKm(a.p, b.p), a, b } : null; }
  function drawMeasure(m, live) {
    if (!m.a || !m.b) return;
    const r = measureKm(m); if (!r) return;
    const pts = geodesic(r.a.p, r.b.p);
    ctx.save();
    ctx.strokeStyle = m.colour || C.accent; ctx.lineWidth = 2; ctx.setLineDash(live ? [6, 5] : []);
    ctx.beginPath(); pts.forEach(([x, y], i) => { const [sx, sy] = scr(x, y); i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy); }); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = m.colour || C.accent;
    for (const e of [m.a, m.b]) { const [sx, sy] = scr(e.x, e.y); ctx.beginPath(); ctx.arc(sx, sy, 4, 0, 7); ctx.fill(); }
    const mid = pts[pts.length >> 1], [mx, my] = scr(mid[0], mid[1]);
    const t1 = fmtKm(r.km), t2 = `${Math.hypot(m.b.x - m.a.x, m.b.y - m.a.y).toFixed(0)} px`;
    ctx.font = fontStr(600, 14, false); const w1 = ctx.measureText(t1).width; ctx.font = fontStr(400, 11.5, false); const w2 = ctx.measureText(t2).width;
    const w = Math.max(w1, w2) + 20;
    ctx.fillStyle = rgba(C.bg1, 0.92); roundRect(mx - w / 2, my - 48, w, 40, 8); ctx.fill();
    ctx.fillStyle = C.text; ctx.font = fontStr(600, 14, false); ctx.textAlign = 'center'; ctx.fillText(t1, mx, my - 29);
    ctx.fillStyle = C.text2; ctx.font = fontStr(400, 11.5, false); ctx.fillText(t2, mx, my - 14);
    ctx.restore();
  }
  function roundRect(x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

  // ------------------------------------------------------------ user drawings (image px)
  const SH_COL = ['#f5a742', '#ffffff', '#8fd8ec', '#ff967d', '#c4daff', '#aae4d6'];   // amber (the accent) first
  function shapePath(s, part) {    // part: 'shaft' or 'head' of an arrow, both when left out
    ctx.beginPath();
    if (s.kind === 'circle') { const [x, y] = scr(s.cx, s.cy); ctx.arc(x, y, s.r * view.s, 0, 2 * Math.PI); }
    else if (s.kind === 'ellipse') { const [x, y] = scr((s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2); ctx.ellipse(x, y, Math.abs(s.x1 - s.x0) / 2 * view.s, Math.abs(s.y1 - s.y0) / 2 * view.s, 0, 0, 2 * Math.PI); }
    else if (s.kind === 'rect') { const [x, y] = scr(Math.min(s.x0, s.x1), Math.min(s.y0, s.y1)); ctx.rect(x, y, Math.abs(s.x1 - s.x0) * view.s, Math.abs(s.y1 - s.y0) * view.s); }
    else if (s.kind === 'outline') {
      s.pts.forEach(([px, py], i) => { const [x, y] = scr(px, py); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      if (s.closed) ctx.closePath(); else if (s.hover) { const [x, y] = scr(s.hover[0], s.hover[1]); ctx.lineTo(x, y); }
    }
    else if (s.kind === 'arrow') {
      const [x0, y0] = scr(s.x0, s.y0), [x1, y1] = scr(s.x1, s.y1), a = Math.atan2(y1 - y0, x1 - x0), h = 11 * (s.size || 1);
      if (part !== 'head') { ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); }
      if (part !== 'shaft') { ctx.moveTo(x1 - h * Math.cos(a - 0.45), y1 - h * Math.sin(a - 0.45)); ctx.lineTo(x1, y1); ctx.lineTo(x1 - h * Math.cos(a + 0.45), y1 - h * Math.sin(a + 0.45)); }
    }
  }
  function shapeAnchor(s) {         // where the label goes (screen)
    if (s.kind === 'circle') { const [x, y] = scr(s.cx, s.cy); return [x, y + s.r * view.s + 14]; }
    if (s.kind === 'ellipse' || s.kind === 'rect') { const [x, y] = scr((s.x0 + s.x1) / 2, Math.max(s.y0, s.y1)); return [x, y + 14]; }
    if (s.kind === 'outline') { let mx = 0, my = -1e9; for (const [px, py] of s.pts) { mx += px; my = Math.max(my, py); } const [x, y] = scr(mx / s.pts.length, my); return [x, y + 14]; }
    if (s.kind === 'arrow') { const [x, y] = scr(s.x0, s.y0); return [x, y + 14]; }
    if (s.kind === 'measure') { const [x, y] = scr((s.a.x + s.b.x) / 2, (s.a.y + s.b.y) / 2); return [x, y]; }
    const [x, y] = scr(s.x, s.y); return [x, y];
  }
  function shapeCentre(s) {
    if (s.kind === 'circle') return [s.cx, s.cy];
    if (s.kind === 'outline') { let x = 0, y = 0; for (const p of s.pts) { x += p[0]; y += p[1]; } return [x / s.pts.length, y / s.pts.length]; }
    if (s.kind === 'text') return [s.x, s.y];
    if (s.kind === 'arrow') return [(s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2];
    if (s.kind === 'measure') return [(s.a.x + s.b.x) / 2, (s.a.y + s.b.y) / 2];
    return [(s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2];
  }
  // handles: points you drag to reshape (image px), each with a setter
  function handles(s) {
    if (s.kind === 'circle') return [{ x: s.cx + s.r, y: s.cy, set: (x, y) => { s.r = Math.hypot(x - s.cx, y - s.cy); } }];
    if (s.kind === 'ellipse' || s.kind === 'rect' || s.kind === 'arrow')
      return [{ x: s.x0, y: s.y0, set: (x, y) => { s.x0 = x; s.y0 = y; } }, { x: s.x1, y: s.y1, set: (x, y) => { s.x1 = x; s.y1 = y; } }];
    if (s.kind === 'outline') return s.pts.map((p) => ({ x: p[0], y: p[1], set: (x, y) => { p[0] = x; p[1] = y; } }));
    if (s.kind === 'measure') return [s.a, s.b].map((p) => ({ x: p.x, y: p.y, set: (x, y) => { if (toLatLon(x, y)) { p.x = x; p.y = y; } } }));
    return [];
  }
  function translate(s, dx, dy) {
    if (s.kind === 'circle') { s.cx += dx; s.cy += dy; }
    else if (s.kind === 'outline') for (const p of s.pts) { p[0] += dx; p[1] += dy; }
    else if (s.kind === 'text') { s.x += dx; s.y += dy; }
    else if (s.kind === 'measure') { if (toLatLon(s.a.x + dx, s.a.y + dy) && toLatLon(s.b.x + dx, s.b.y + dy)) for (const p of [s.a, s.b]) { p.x += dx; p.y += dy; } }
    else { s.x0 += dx; s.x1 += dx; s.y0 += dy; s.y1 += dy; }
  }
  function drawShape(s, live) {
    if (s.kind === 'measure') { drawMeasure(s, live); if (s === editing) drawHandles(s); return; }
    ctx.save();
    const size = s.size || 1;
    if (s.kind !== 'text') {
      ctx.strokeStyle = s.colour; ctx.lineWidth = 1.6 * size; ctx.setLineDash(s.dash ? [7, 5] : []);
      if (s.kind === 'arrow' && s.dash) { shapePath(s, 'shaft'); ctx.stroke(); ctx.setLineDash([]); shapePath(s, 'head'); ctx.stroke(); }   // the head stays solid
      else { shapePath(s); ctx.stroke(); }
      if (s === editing) { ctx.setLineDash([3, 4]); ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 1; shapePath(s); ctx.stroke(); }
    }
    if (s.label) {
      const [x, y] = shapeAnchor(s), px = Math.round(15 * size * set.fs);
      ctx.font = fontStr(s.kind === 'text' ? 500 : 520, px, false, s.font); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.shadowColor = C.halo; ctx.shadowBlur = 6.4 * set.fs * dpr; ctx.fillStyle = s.colour;
      ctx.fillText(s.label, x, y);
    } else if (s.kind === 'text' && !live) {
      const [x, y] = scr(s.x, s.y); ctx.fillStyle = s.colour; ctx.beginPath(); ctx.arc(x, y, 3, 0, 7); ctx.fill();
    }
    ctx.restore();
    if (s === editing) drawHandles(s);
  }
  function drawHandles(s) {
    ctx.save(); ctx.fillStyle = C.bg1; ctx.strokeStyle = C.accent; ctx.lineWidth = 1.5;
    for (const h of handles(s)) { const [x, y] = scr(h.x, h.y); ctx.beginPath(); ctx.rect(x - 4.5, y - 4.5, 9, 9); ctx.fill(); ctx.stroke(); }
    ctx.restore();
  }

  // ------------------------------------------------------------ render
  let pending = false;
  function redraw() { if (!pending) { pending = true; requestAnimationFrame(render); } }
  function render() {
    pending = false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg0; ctx.fillRect(0, 0, VW, VH);
    drawTiles();
    drawGrid();
    const [ix0, iy0] = scr(-0.5, -0.5), [ix1, iy1] = scr(A.width - 0.5, A.height - 0.5);
    ctx.save(); ctx.beginPath(); ctx.rect(ix0, iy0, ix1 - ix0, iy1 - iy0); ctx.clip();      // names stop at the photo's edge, as in an export
    drawLabels();
    ctx.restore();
    drawGridLabels();
    if (selected) {
      const f = selected;
      ctx.save(); ctx.shadowColor = C.halo; ctx.shadowBlur = 4 * dpr;
      if (f.e) drawRim(f, 1, 2, C.accent);              // outlines only for the selected crater (unless all are on)
      else { const [x, y] = scr(f.x, f.y); ctx.strokeStyle = C.accent; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.arc(x, y, 9, 0, 7); ctx.stroke(); }
      ctx.restore();
    }
    if (picks.size) {
      ctx.save(); ctx.shadowColor = C.halo; ctx.shadowBlur = 4 * dpr;
      ctx.setLineDash([5, 3]);                // several picked: dashed, the single selection is solid
      for (const f of picks.values()) {
        if (f.e) drawRim(f, 1, 2, PICK);
        else { const [x, y] = scr(f.x, f.y); ctx.strokeStyle = PICK; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.arc(x, y, 9, 0, 7); ctx.stroke(); }
      }
      ctx.restore();
    }
    if (marquee && (Math.abs(marquee.x1 - marquee.x0) > 4 || Math.abs(marquee.y1 - marquee.y0) > 4)) {
      const x = Math.min(marquee.x0, marquee.x1), y = Math.min(marquee.y0, marquee.y1);
      ctx.save(); ctx.setLineDash([5, 4]); ctx.strokeStyle = PICK; ctx.lineWidth = 1.2; ctx.fillStyle = rgba(C.accent, 0.08);
      ctx.fillRect(x, y, Math.abs(marquee.x1 - marquee.x0), Math.abs(marquee.y1 - marquee.y0));
      ctx.strokeRect(x + .5, y + .5, Math.abs(marquee.x1 - marquee.x0), Math.abs(marquee.y1 - marquee.y0));
      ctx.restore();
    }
    if (set.mine) for (const s of E.shapes) drawShape(s);
    if (draft) drawShape(draft, true);
    status();
  }

  // ------------------------------------------------------------ status bar
  let cursor = null;
  function fmtLat(v) { return `${Math.abs(v).toFixed(2)}° ${v >= 0 ? 'N' : 'S'}`; }
  function fmtLon(v) { return `${Math.abs(v).toFixed(2)}° ${v >= 0 ? 'E' : 'W'}`; }
  function status() {
    const pct = view.s * 100;
    $('#zoomPct').textContent = (pct >= 10 ? pct.toFixed(0) : pct.toFixed(1)) + ' %';
    const kmpx = A.km_per_px / view.s, nice = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
    let km = nice[0]; for (const n of nice) if (n / kmpx <= 130) km = n;
    $('#sbar').style.width = (km / kmpx).toFixed(1) + 'px';
    $('#slabel').textContent = km + ' km';
    const r = $('#readout'), kp = `<span><b>${A.km_per_px.toFixed(2)}</b> <span class="k">km/px</span></span>`;
    if (!cursor) { r.innerHTML = `<span class="k">Move over the Moon</span>${kp}`; return; }
    const ll = toLatLon(cursor[0], cursor[1]);
    const pos = `<span class="px"><span class="k">x</span> <b>${cursor[0].toFixed(0)}</b> <span class="k">y</span> <b>${cursor[1].toFixed(0)}</b></span>`;
    r.innerHTML = ll ? `<span><b>${fmtLat(ll.lat)}</b></span><span><b>${fmtLon(ll.lon)}</b></span>${kp}${pos}` : `<span class="k">off the disk</span>${kp}${pos}`;
  }

  // ------------------------------------------------------------ view control
  function fit() {
    const d = 2 * A.radius_px * 1.04;
    if (d > 1.15 * Math.max(A.width, A.height)) {            // a close-up: the photo, not the whole Moon, fills the view
      const s = Math.min((VW - 380) / A.width, (VH - 150) / A.height);
      view.s = s; view.x = A.width / 2; view.y = A.height / 2 + 8 / s; redraw(); return;
    }
    const s = Math.min((VW - 40) / d, (VH - 150) / d, VW / A.width, VH / A.height);
    view.s = s; view.x = G.t[0]; view.y = G.t[1] + 8 / s; redraw();
  }
  const minS = () => Math.min(VW / A.width, VH / A.height) * 0.3, maxS = 4;
  function zoomAt(sx, sy, factor) {
    const [ix, iy] = img(sx, sy);
    view.s = clamp(view.s * factor, minS(), maxS);
    view.x = ix - (sx - VW / 2) / view.s; view.y = iy - (sy - VH / 2) / view.s; redraw();
  }
  let anim = null;
  function flyTo(x, y, s) {
    const from = { ...view }, t0 = performance.now(), dur = 750;
    s = clamp(s, minS(), maxS);
    cancelAnimationFrame(anim);
    const step = (t) => {
      const u = Math.min(1, (t - t0) / dur), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      view.s = Math.exp(Math.log(from.s) + (Math.log(s) - Math.log(from.s)) * e);
      view.x = from.x + (x - from.x) * e; view.y = from.y + (y - from.y) * e;
      render();
      if (u < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }
  function flyToFeature(f) { flyTo(f.x, f.y, clamp(f.dpx > 0 ? 0.28 * Math.min(VW, VH) / f.dpx : 1, minS(), 1.5)); }

  // ------------------------------------------------------------ info card (select, restyle, hide a name)
  let selected = null;
  // a short window: the card (bottom right) would cover the layers panel (top right), so the panel folds while the
  // card is open and unfolds when it closes; folded by the user, it stays folded
  function makeRoom() {
    const lay = $('#layers'), card = $('#info');
    if (card.hidden) { if (lay.dataset.autofold) { delete lay.dataset.autofold; setLayersFolded(false); } return; }
    if (lay.classList.contains('collapsed')) return;
    if (lay.getBoundingClientRect().bottom + 8 > card.getBoundingClientRect().top) { lay.dataset.autofold = '1'; setLayersFolded(true); }
  }
  function select(f) {
    selected = f;
    const el = $('#info');
    if (!f) { el.hidden = true; makeRoom(); redraw(); return; }
    const ov = E.labels[f.n] || {};
    const nameAfter = f.o ? `<div class="origin"><i>Named after</i>${esc(f.o)}</div>` : '';
    const sunlit = f.lit < 0.12 ? 'night side' : f.lit < 0.5 ? 'near the terminator' : 'sunlit';
    const size = f.dpx > 0 ? `<dt>In this image</dt><dd>≈ ${Math.round(f.dpx)} px across · ${sunlit}</dd>` : `<dt>In this image</dt><dd>x ${f.x.toFixed(0)}, y ${f.y.toFixed(0)} px · ${sunlit}</dd>`;
    el.innerHTML = `
      <button class="close" id="infoClose" aria-label="Close"><svg width="16" height="16"><use href="#i-x"/></svg></button>
      <div class="kicker"><h3>${esc(f.c === 'relief' || f.c === 'site' ? f.t : TYPE_NAME[f.c])}</h3></div>
      <h2>${esc(f.n)}</h2>
      <dl>${f.d > 0 ? `<dt>Diameter</dt><dd>${f.d >= 100 ? f.d.toFixed(0) : f.d.toFixed(1)} km</dd>` : ''}
        <dt>Position</dt><dd>${fmtLat(f.la)}, ${fmtLon(f.lo)}</dd>${size}</dl>
      ${nameAfter}
      <div class="labelstyle"><span>Label</span>
        <div class="colours">${[LABEL, ...SH_COL].map((c) => `<button data-c="${c}" style="background:${c}" class="${(ov.colour || LABEL) === c ? 'on' : ''}" aria-label="${c}"></button>`).join('')}</div>
        <select id="lSize"><option value="0.8">Small</option><option value="1">Normal</option><option value="1.3">Large</option><option value="1.7">Extra large</option></select>
      </div>
      <p class="hint">Drag the name to move it${ov.dx != null ? ' · <a href="#" id="lReset">back to its place</a>' : ''}</p>
      <div class="actions">
        <button class="btn" id="infoZoom"><svg width="14" height="14"><use href="#i-target"/></svg>Zoom to</button>
        <button class="btn" id="infoHide"><svg width="14" height="14"><use href="#i-eyeoff"/></svg>Hide label</button>
        ${/^\d+$/.test(f.k || '') ? `<a class="btn" href="https://planetarynames.wr.usgs.gov/Feature/${f.k}" target="_blank" rel="noopener">IAU <svg width="13" height="13"><use href="#i-ext"/></svg></a>` : ''}
      </div>`;
    el.hidden = false;
    makeRoom();
    $('#lSize').value = String(ov.size || 1);
    $('#infoClose').onclick = () => select(null);
    $('#infoZoom').onclick = () => flyToFeature(f);
    $('#infoHide').onclick = () => { change(() => hiddenSet.add(f.n)); toast(`“${f.n}” hidden · ⌘Z undoes`); select(null); };
    el.querySelectorAll('.colours button').forEach((b) => b.onclick = () => { change(() => styleLabel(f, { colour: b.dataset.c === LABEL ? null : b.dataset.c })); select(f); });
    $('#lSize').onchange = (e) => change(() => styleLabel(f, { size: +e.target.value === 1 ? null : +e.target.value }));
    if ($('#lReset')) $('#lReset').onclick = (e) => { e.preventDefault(); change(() => styleLabel(f, { dx: null, dy: null })); select(f); };
    redraw();
  }
  function styleLabel(f, patch) {
    const o = Object.assign({}, E.labels[f.n] || {}, patch);
    for (const k of Object.keys(o)) if (o[k] == null) delete o[k];
    if (Object.keys(o).length) E.labels[f.n] = o; else delete E.labels[f.n];
  }
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ------------------------------------------------------------ several names at once (Alt/⌥ click or drag)
  const PICK = C.accent, ALT = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌥' : 'Alt';
  const picks = new Map();                    // name -> feature
  let marquee = null;                         // screen box of an Alt-drag
  function pickAt(m, click) {
    if (selected && !picks.size) picks.set(selected.n, selected);    // the card's feature starts the selection
    if (click) {
      const f = hitFeature(m.x0, m.y0);
      if (f) { if (picks.has(f.n)) picks.delete(f.n); else picks.set(f.n, f); }
    } else {
      const x0 = Math.min(m.x0, m.x1), x1 = Math.max(m.x0, m.x1), y0 = Math.min(m.y0, m.y1), y1 = Math.max(m.y0, m.y1);
      for (const p of placed) { const [x, y] = scr(p.f.x, p.f.y); if (x >= x0 && x <= x1 && y >= y0 && y <= y1) picks.set(p.f.n, p.f); }
    }
    if (selected) select(null);
    showPicks();
  }
  function clearPicks() { picks.clear(); showPicks(); redraw(); }
  function hidePicks() {
    const n = picks.size; if (!n) return;
    change(() => { for (const name of picks.keys()) hiddenSet.add(name); });
    toast(`${n} label${n > 1 ? 's' : ''} hidden · ⌘Z undoes`);
    clearPicks();
  }
  function showPicks() {
    const el = $('#picks');
    if (!picks.size) { el.hidden = true; return; }
    const n = picks.size;
    el.innerHTML = `<b>${n} selected</b>
      <button class="btn" id="pHide"><svg width="14" height="14"><use href="#i-eyeoff"/></svg>Hide ${n > 1 ? n + ' labels' : 'label'}</button>
      <button class="btn ghost" id="pClear">Clear</button>
      <span class="hint">${ALT}-click adds or removes · ${ALT}-drag selects an area · Delete hides</span>`;
    el.hidden = false;
    $('#pHide').onclick = hidePicks;
    $('#pClear').onclick = clearPicks;
  }

  function hitLabel(sx, sy) {
    for (let i = placed.length - 1; i >= 0; i--) { const b = placed[i].box; if (sx >= b[0] && sx <= b[2] && sy >= b[1] && sy <= b[3]) return placed[i]; }
    return null;
  }
  function hitFeature(sx, sy) {
    const l = hitLabel(sx, sy); if (l) return l.f;
    const [ix, iy] = img(sx, sy);
    let best = null;
    for (const p of placed) {
      const e = p.f.e; if (!e) continue;
      const t = -e[4] * rad, dx = ix - e[0], dy = iy - e[1];
      const u = dx * Math.cos(t) - dy * Math.sin(t), v = dx * Math.sin(t) + dy * Math.cos(t);
      if ((u * u) / (e[2] * e[2]) + (v * v) / (e[3] * e[3]) <= 1 && (!best || p.f.d < best.d)) best = p.f;
    }
    return best;
  }
  function hitHandle(sx, sy) {
    if (!editing) return null;
    for (const h of handles(editing)) { const [x, y] = scr(h.x, h.y); if (Math.abs(sx - x) <= 7 && Math.abs(sy - y) <= 7) return h; }
    return null;
  }
  function segDist(px, py, ax, ay, bx, by) {
    const vx = bx - ax, vy = by - ay, t = clamp(((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy || 1), 0, 1);
    return Math.hypot(px - ax - t * vx, py - ay - t * vy);
  }
  function hitShape(sx, sy) {           // near the outline (not anywhere inside a big circle), or on its label
    const tol = 7;
    for (let i = E.shapes.length - 1; i >= 0; i--) {
      const s = E.shapes[i];
      if (s.label) { const [x, y] = shapeAnchor(s); if (Math.abs(sx - x) < 60 && Math.abs(sy - y) < 10) return s; }
      if (s.kind === 'text') { const [x, y] = scr(s.x, s.y); if (Math.hypot(sx - x, sy - y) < 10) return s; continue; }
      if (s.kind === 'circle') { const [x, y] = scr(s.cx, s.cy); if (Math.abs(Math.hypot(sx - x, sy - y) - s.r * view.s) < tol) return s; continue; }
      if (s.kind === 'ellipse') {
        const [x, y] = scr((s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2), rx = Math.abs(s.x1 - s.x0) / 2 * view.s, ry = Math.abs(s.y1 - s.y0) / 2 * view.s;
        const q = Math.hypot((sx - x) / Math.max(rx, 1), (sy - y) / Math.max(ry, 1));
        if (Math.abs(q - 1) * Math.min(rx, ry) < tol) return s; continue;
      }
      let pts;
      if (s.kind === 'rect') pts = [[s.x0, s.y0], [s.x1, s.y0], [s.x1, s.y1], [s.x0, s.y1], [s.x0, s.y0]];
      else if (s.kind === 'outline') pts = s.closed ? [...s.pts, s.pts[0]] : s.pts;
      else if (s.kind === 'arrow') pts = [[s.x0, s.y0], [s.x1, s.y1]];
      else if (s.kind === 'measure') pts = [[s.a.x, s.a.y], [s.b.x, s.b.y]];
      else continue;
      for (let k = 0; k + 1 < pts.length; k++) {
        const [ax, ay] = scr(pts[k][0], pts[k][1]), [bx, by] = scr(pts[k + 1][0], pts[k + 1][1]);
        if (segDist(sx, sy, ax, ay, bx, by) < tol) return s;
      }
    }
    return null;
  }

  // ------------------------------------------------------------ search
  for (const f of FE) f.key = norm(f.n);
  let results = [], ri = 0;
  function search(q) {
    const ul = $('#results'), n = norm(q.trim());
    if (!n) { ul.classList.remove('open'); return; }
    const starts = [], has = [];
    for (const f of ORDER) { if (f.key.startsWith(n)) starts.push(f); else if (f.key.includes(n)) has.push(f); if (starts.length > 40) break; }
    starts.sort((a, b) => a.n.length - b.n.length || b.d - a.d);
    results = starts.concat(has).slice(0, 9); ri = 0;
    ul.innerHTML = results.length ? results.map((f, i) => `<li data-i="${i}" class="${i === 0 ? 'on' : ''}"><span class="dot"></span><span class="nm">${esc(f.n)}</span><span class="ty">${esc(f.c === 'relief' ? f.t : TYPE_NAME[f.c])}${f.d > 0 ? ' · ' + (f.d >= 100 ? f.d.toFixed(0) : f.d.toFixed(1)) + ' km' : ''}${f.lit < 0.12 ? ' · night' : ''}${hiddenSet.has(f.n) ? ' · hidden' : ''}</span></li>`).join('')
      : `<li class="empty">No visible feature matches “${esc(q)}”</li>`;
    ul.classList.add('open');
  }
  function choose(i) {
    const f = results[i]; if (!f) return;
    $('#results').classList.remove('open'); $('#q').value = f.n; $('#q').blur();
    if (hiddenSet.has(f.n)) change(() => hiddenSet.delete(f.n));
    flyToFeature(f); select(f);
  }
  $('#q').addEventListener('input', (e) => search(e.target.value));
  $('#q').addEventListener('keydown', (e) => {
    const items = [...document.querySelectorAll('#results li[data-i]')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); ri = clamp(ri + (e.key === 'ArrowDown' ? 1 : -1), 0, items.length - 1); items.forEach((li, i) => li.classList.toggle('on', i === ri)); }
    else if (e.key === 'Enter') choose(ri);
    else if (e.key === 'Escape') { $('#results').classList.remove('open'); e.target.blur(); }
  });
  $('#results').addEventListener('mousedown', (e) => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); choose(+li.dataset.i); } });
  $('#q').addEventListener('blur', () => setTimeout(() => $('#results').classList.remove('open'), 120));

  // ------------------------------------------------------------ drawing editor
  let editing = null, draft = null, tool = 'pan', editStart = null;
  function shapeSize(s) {
    if (s.kind === 'circle') return 2 * s.r;
    if (s.kind === 'outline') { const [cx, cy] = shapeCentre(s); return 2 * Math.max(...s.pts.map((p) => Math.hypot(p[0] - cx, p[1] - cy))); }
    if (s.kind === 'text') return 0;
    if (s.kind === 'measure') return Math.hypot(s.b.x - s.a.x, s.b.y - s.a.y);
    return Math.max(Math.abs(s.x1 - s.x0), Math.abs(s.y1 - s.y0));
  }
  function nearNames(s) {
    const [cx, cy] = shapeCentre(s), size = shapeSize(s) || 40 / view.s;
    return FE.filter((f) => f.z > 0.1 && (f.c !== 'area' || f.dpx < 4 * size))
      .map((f) => ({ f, d: Math.hypot(f.x - cx, f.y - cy) + 0.5 * Math.abs((f.dpx || size) - size) }))
      .sort((a, b) => a.d - b.d).slice(0, 7).map((o) => o.f);
  }
  function shapeScreenBox(s) {              // the shape's screen bounds, with its label
    let pts;
    if (s.kind === 'circle') pts = [[s.cx - s.r, s.cy - s.r], [s.cx + s.r, s.cy + s.r]];
    else if (s.kind === 'outline') pts = s.pts;
    else if (s.kind === 'text') pts = [[s.x, s.y]];
    else if (s.kind === 'measure') pts = [[s.a.x, s.a.y], [s.b.x, s.b.y]];
    else pts = [[s.x0, s.y0], [s.x1, s.y1]];
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const [x, y] of pts) { const [a, b] = scr(x, y); x0 = Math.min(x0, a); y0 = Math.min(y0, b); x1 = Math.max(x1, a); y1 = Math.max(y1, b); }
    if (s.label || s.kind === 'text') {
      const [ax, ay] = shapeAnchor(s), half = Math.max(30, (s.label || '').length * 4.5 * (s.size || 1));
      x0 = Math.min(x0, ax - half); x1 = Math.max(x1, ax + half); y0 = Math.min(y0, ay - 12); y1 = Math.max(y1, ay + 12);
    }
    return [x0 - 6, y0 - 6, x1 + 6, y1 + 6];
  }
  function openEditor(s, fresh) {
    if (editing && editing !== s) closeEditor();
    editing = s;
    editStart = fresh ? null : snap();
    const el = $('#annot');
    const names = s.kind === 'measure' ? [] : nearNames(s);
    const fonts = A.fonts && A.fonts.length ? A.fonts : ['IBM Plex Sans'];
    el.innerHTML = `
      <h4>${{ circle: 'Circle', ellipse: 'Ellipse', rect: 'Rectangle', outline: 'Outline', text: 'Text', arrow: 'Arrow', measure: 'Measurement' }[s.kind]}</h4>
      ${s.kind === 'measure' ? `<p class="hint">${fmtKm((measureKm(s) || { km: 0 }).km)} · drag the end points to adjust. Saved with the image and included in exports.</p>` : `
      <div class="field"><span>Label</span><input type="text" id="aLabel" value="${esc(s.label || '')}" placeholder="Pick a name below or type your own">
        <div class="suggest">${names.map((f) => `<button class="chip" data-n="${esc(f.n)}">${esc(f.n)}</button>`).join('')}</div></div>`}
      <div class="field"><span>Colour</span><div class="colours">${SH_COL.map((c) => `<button data-c="${c}" style="background:${c}" class="${c === (s.colour || SH_COL[0]) ? 'on' : ''}" aria-label="${c}"></button>`).join('')}</div></div>
      ${s.kind === 'measure' ? '' : `<div class="field" style="display:flex;gap:10px">
        <label style="flex:1"><span>Size</span>
          <select id="aSize"><option value="0.8">Small</option><option value="1">Medium</option><option value="1.35">Large</option><option value="1.8">Extra large</option></select></label>
        <label style="flex:1.3"><span>Font</span>
          <select id="aFont"><option value="">Same as the names</option>${fonts.map((f) => `<option>${esc(f)}</option>`).join('')}</select></label>
      </div>
      ${s.kind !== 'text' ? `<div class="field"><label class="check"><input type="checkbox" id="aDash" ${s.dash ? 'checked' : ''}> Dashed line</label></div>` : ''}`}
      <p class="hint">Drag the shape to move it${handles(s).length ? ', the squares to reshape it' : ''}.</p>
      <div class="foot"><button class="btn ghost" id="aDel">Delete</button><button class="btn primary" id="aOk">Done</button></div>`;
    el.hidden = false;
    $('#info').hidden = true; selected = null; makeRoom();
    placeEditor();
    const live = () => { save(); redraw(); };
    if ($('#aSize')) { $('#aSize').value = String(s.size || 1); $('#aSize').onchange = (e) => { s.size = +e.target.value; live(); }; }
    if ($('#aFont')) { $('#aFont').value = s.font || ''; $('#aFont').onchange = (e) => { s.font = e.target.value || undefined; document.fonts.load(fontStr(500, 14, false, s.font)).finally(live); }; }
    const lab = $('#aLabel');
    if (lab) {
      lab.focus();
      lab.oninput = () => { s.label = lab.value; live(); };
      lab.onkeydown = (e) => { if (e.key === 'Enter') closeEditor(); };
      el.querySelectorAll('.chip').forEach((b) => b.onclick = () => { lab.value = s.label = b.dataset.n; live(); });
    }
    el.querySelectorAll('.colours button').forEach((b) => b.onclick = () => { s.colour = b.dataset.c; el.querySelectorAll('.colours button').forEach((x) => x.classList.toggle('on', x === b)); live(); });
    if ($('#aDash')) $('#aDash').onchange = (e) => { s.dash = e.target.checked; live(); };
    $('#aDel').onclick = () => { const i = E.shapes.indexOf(s); closeEditor(); change(() => { if (i >= 0) E.shapes.splice(i, 1); }); };
    $('#aOk').onclick = () => closeEditor();
    redraw();
  }
  function placeEditor() {                  // next to the shape, never on it: right, left, below, above, whichever fits
    if (!editing) return;
    const el = $('#annot'), w = el.offsetWidth || 296, h = el.offsetHeight, bx = shapeScreenBox(editing), gap = 14;
    const lay = $('#layers').getBoundingClientRect();
    const L = 70, T = 64, Rr = (lay.width && lay.bottom > bx[1] ? lay.left : VW) - 10, B = VH - 70;
    const cy = clamp((bx[1] + bx[3]) / 2 - h / 2, T, B - h), cx = clamp((bx[0] + bx[2]) / 2 - w / 2, L, Rr - w);
    const cands = [['l', bx[2] + gap, cy], ['r', bx[0] - gap - w, cy], ['t', cx, bx[3] + gap], ['b', cx, bx[1] - gap - h]];
    const overlap = (x, y) => Math.max(0, Math.min(x + w, bx[2]) - Math.max(x, bx[0])) * Math.max(0, Math.min(y + h, bx[3]) - Math.max(y, bx[1]));
    let pick = cands.find(([, x, y]) => x >= L && y >= T && x + w <= Rr && y + h <= B);
    if (!pick) pick = cands.map(([side, x, y]) => [side, clamp(x, L, VW - w - 10), clamp(y, T, B - h)])
      .sort((a, b) => overlap(a[1], a[2]) - overlap(b[1], b[2]))[0];
    const [side, x, y] = pick;
    el.style.left = x + 'px'; el.style.top = y + 'px';
    let nub = el.querySelector('.nub');
    if (!nub) { nub = document.createElement('i'); el.prepend(nub); }
    nub.className = 'nub ' + side;               // points back at the shape
    nub.style.left = nub.style.top = '';
    if (side === 'l' || side === 'r') nub.style.top = clamp((bx[1] + bx[3]) / 2 - y - 6, 14, h - 26) + 'px';
    else nub.style.left = clamp((bx[0] + bx[2]) / 2 - x - 6, 14, w - 26) + 'px';
    nub.hidden = overlap(x, y) > 0;
  }
  function closeEditor(skipUndo) {
    if (editing) {
      if (editing.kind === 'text' && !editing.label) { const i = E.shapes.indexOf(editing); if (i >= 0) E.shapes.splice(i, 1); }
      if (!skipUndo && editStart && editStart !== snap()) { undo.push(editStart); redo.length = 0; }   // one undo step per edit session
    }
    editing = null; editStart = null; $('#annot').hidden = true; save(); redraw();
  }
  function addShape(s) { change(() => E.shapes.push(s)); openEditor(s, true); }

  // ------------------------------------------------------------ pointer input
  let down = null, dragLabel = null, dragShape = null, dragHandle = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    canvas.setPointerCapture(e.pointerId);
    const [ix, iy] = img(e.offsetX, e.offsetY);
    down = { sx: e.offsetX, sy: e.offsetY, ix, iy, vx: view.x, vy: view.y, moved: false };
    const colour = SH_COL[0];
    if (tool === 'measure' && !draft && set.mine) {   // clicking a saved measurement picks it up, as Pan and select would
      const s = hitHandle(e.offsetX, e.offsetY) ? editing : hitShape(e.offsetX, e.offsetY);
      if (s && s.kind === 'measure') setTool('pan');
    }
    if (tool === 'pan' && e.altKey) { marquee = { x0: e.offsetX, y0: e.offsetY, x1: e.offsetX, y1: e.offsetY }; return; }
    if (tool === 'pan') {
      const h = hitHandle(e.offsetX, e.offsetY);
      if (h) { dragHandle = { h, before: snap() }; return; }
      const s = set.mine ? hitShape(e.offsetX, e.offsetY) : null;
      if (s) { dragShape = { s, x: ix, y: iy, before: snap() }; return; }
      const l = hitLabel(e.offsetX, e.offsetY);
      if (l) { dragLabel = { f: l.f, home: l.home, grab: [e.offsetX - l.x, e.offsetY - l.y], before: snap() }; return; }
      if (editing) closeEditor();
      canvas.classList.add('dragging');
    }
    else if (tool === 'circle') draft = { kind: 'circle', cx: ix, cy: iy, r: 0, colour, size: 1 };
    else if (tool === 'ellipse' || tool === 'rect') draft = { kind: tool, x0: ix, y0: iy, x1: ix, y1: iy, colour, size: 1 };
    else if (tool === 'arrow') draft = { kind: 'arrow', x0: ix, y0: iy, x1: ix, y1: iy, colour, size: 1 };
  });
  canvas.addEventListener('pointermove', (e) => {
    const [ix, iy] = img(e.offsetX, e.offsetY);
    cursor = [ix, iy];
    if (down) {
      if (Math.hypot(e.offsetX - down.sx, e.offsetY - down.sy) > 4) down.moved = true;
      if (marquee) { marquee.x1 = e.offsetX; marquee.y1 = e.offsetY; }
      else if (dragHandle) { if (down.moved) { dragHandle.h.set(ix, iy); dragHandle.h.x = ix; dragHandle.h.y = iy; } }
      else if (dragShape) { if (down.moved) { translate(dragShape.s, ix - dragShape.x, iy - dragShape.y); dragShape.x = ix; dragShape.y = iy; } }
      else if (dragLabel) {
        if (down.moved) {
          const x = e.offsetX - dragLabel.grab[0], y = e.offsetY - dragLabel.grab[1];
          styleLabel(dragLabel.f, { dx: (x - dragLabel.home[0]) / view.s, dy: (y - dragLabel.home[1]) / view.s });
        }
      }
      else if (tool === 'pan') { view.x = down.vx - (e.offsetX - down.sx) / view.s; view.y = down.vy - (e.offsetY - down.sy) / view.s; }
      else if (draft && draft.kind === 'circle') draft.r = Math.hypot(ix - draft.cx, iy - draft.cy);
      else if (draft && (draft.kind === 'ellipse' || draft.kind === 'rect' || draft.kind === 'arrow')) { draft.x1 = ix; draft.y1 = iy; }
    } else if (tool === 'pan') {
      const over = hitHandle(e.offsetX, e.offsetY) || (set.mine && hitShape(e.offsetX, e.offsetY)) || hitLabel(e.offsetX, e.offsetY) || hitFeature(e.offsetX, e.offsetY);
      canvas.classList.toggle('pointer', !!over);
    }
    if (draft && draft.kind === 'measure' && draft.a) { if (toLatLon(ix, iy)) draft.b = { x: ix, y: iy }; }
    if (draft && draft.kind === 'outline') draft.hover = [ix, iy];
    redraw();
  });
  canvas.addEventListener('pointerleave', () => { cursor = null; redraw(); });
  canvas.addEventListener('pointerup', (e) => {
    canvas.classList.remove('dragging');
    if (!down) return;
    const [ix, iy] = img(e.offsetX, e.offsetY), click = !down.moved;
    down = null;
    if (marquee) { const m = marquee; marquee = null; pickAt(m, click); redraw(); return; }
    const finishDrag = (d) => { if (!click && d.before !== snap()) { undo.push(d.before); redo.length = 0; save(); } };
    if (dragHandle) { finishDrag(dragHandle); dragHandle = null; editStart = editing ? snap() : null; placeEditor(); redraw(); return; }
    if (dragShape) { const s = dragShape.s; finishDrag(dragShape); dragShape = null; if (click) openEditor(s); else { editStart = editing ? snap() : null; placeEditor(); } redraw(); return; }
    if (dragLabel) { const f = dragLabel.f; finishDrag(dragLabel); dragLabel = null; if (click || selected === f) select(f); redraw(); return; }
    if (tool === 'pan' && click) select(hitFeature(e.offsetX, e.offsetY));
    else if (tool === 'measure' && click) {
      if (!toLatLon(ix, iy)) { toast('Measure on the lunar disk'); return; }
      if (!draft || draft.kind !== 'measure') draft = { kind: 'measure', a: { x: ix, y: iy }, colour: SH_COL[0] };
      else { draft.b = { x: ix, y: iy }; const m = draft; draft = null; change(() => E.shapes.push(m)); toast(`${fmtKm(measureKm(m).km)} · saved; click the line to adjust or delete it (switches to Pan and select)`); }
    } else if (tool === 'text' && click) {
      addShape({ kind: 'text', x: ix, y: iy, colour: SH_COL[1], size: 1, label: '' });
    } else if (tool === 'outline' && click) {
      if (!draft) draft = { kind: 'outline', pts: [[ix, iy]], colour: SH_COL[0], size: 1 };
      else draft.pts.push([ix, iy]);
    } else if (draft && draft.kind && draft.kind !== 'outline' && draft.kind !== 'measure') {
      const s = draft; draft = null;
      const big = s.kind === 'circle' ? s.r * view.s > 4 : Math.hypot((s.x1 - s.x0) * view.s, (s.y1 - s.y0) * view.s) > 6;
      if (big) addShape(s);
    }
    redraw();
  });
  function closeOutline() { if (draft && draft.kind === 'outline' && draft.pts.length >= 3) { draft.closed = true; const s = draft; draft = null; delete s.hover; addShape(s); } }
  canvas.addEventListener('dblclick', (e) => {
    if (tool === 'outline' && draft && draft.pts.length >= 4) { draft.pts.pop(); closeOutline(); return; }
    if (tool === 'pan') zoomAt(e.offsetX, e.offsetY, e.shiftKey ? 0.5 : 2);
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const k = e.ctrlKey ? 0.012 : 0.0022;
    zoomAt(e.offsetX, e.offsetY, Math.exp(-e.deltaY * k));
    placeEditor();
  }, { passive: false });

  // ------------------------------------------------------------ tools + keys
  function setTool(t) {
    tool = t; draft = null;
    document.querySelectorAll('#tools button[data-tool]').forEach((b) => { b.classList.toggle('on', b.dataset.tool === t); b.setAttribute('aria-pressed', String(b.dataset.tool === t)); });
    canvas.classList.toggle('crosshair', t !== 'pan');
    redraw();
  }
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
  document.querySelectorAll('#tools button').forEach((b) => {
    if (!MAC) b.dataset.key = b.dataset.key.replace('⇧⌘', 'Ctrl+Shift+').replace('⌘', 'Ctrl+');
    b.setAttribute('aria-label', `${b.dataset.tip} (${b.dataset.key})`);
    b.setAttribute('aria-keyshortcuts', b.dataset.key.replace('⇧', 'Shift+').replace('⌘', 'Meta+'));
    if (b.dataset.tool) b.onclick = () => setTool(b.dataset.tool);
    const on = () => {
      const tip = $('#tip'), r = b.getBoundingClientRect();
      tip.textContent = b.dataset.tip; const k = document.createElement('kbd'); k.textContent = b.dataset.key; tip.append(k);
      tip.style.display = 'flex'; tip.style.left = r.right + 12 + 'px'; tip.style.top = r.top + r.height / 2 - tip.offsetHeight / 2 + 'px';
    };
    const off = () => { $('#tip').style.display = 'none'; };
    b.addEventListener('mouseenter', on); b.addEventListener('focus', () => { if (b.matches(':focus-visible')) on(); });
    b.addEventListener('mouseleave', off); b.addEventListener('blur', off); b.addEventListener('click', off);
  });
  $('#undoBtn').onclick = doUndo; $('#redoBtn').onclick = doRedo;
  const TOOLKEY = { v: 'pan', m: 'measure', c: 'circle', e: 'ellipse', r: 'rect', o: 'outline', t: 'text', a: 'arrow' };
  window.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === 'z') { if (e.target.matches('input, textarea')) return; e.preventDefault(); e.shiftKey ? doRedo() : doUndo(); return; }
    if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); doRedo(); return; }
    if (e.target.matches('input, select, textarea')) return;
    const k = e.key.toLowerCase();
    if (k === '/') { e.preventDefault(); $('#q').focus(); $('#q').select(); }
    else if (k === 'escape') {
      if (!$('#export').hidden) { if (!jobRunning) $('#export').hidden = true; return; }
      if (draft) draft = null; else if (editing) closeEditor(); else if (picks.size) clearPicks(); else select(null);
      redraw();
    }
    else if (k === 'enter') closeOutline();
    else if (k === 'f') fit();
    else if (k === '1') flyTo(view.x, view.y, 1);
    else if (k === 'g') { set.grid = !set.grid; $('#l-grid').checked = set.grid; save(); redraw(); }
    else if (k === 'l') { const on = !set.crater; for (const l of LAYERS5) { set[l] = on; $('#l-' + l).checked = on; } syncLettered(); save(); redraw(); }
    else if (k === '+' || k === '=') zoomAt(VW / 2, VH / 2, 1.5);
    else if (k === '-') zoomAt(VW / 2, VH / 2, 1 / 1.5);
    else if ((k === 'backspace' || k === 'delete') && !editing && picks.size) hidePicks();
    else if ((k === 'backspace' || k === 'delete') && editing) { const s = editing, i = E.shapes.indexOf(s); closeEditor(); change(() => { if (i >= 0) E.shapes.splice(i, 1); }); }
    else if (TOOLKEY[k] && !mod) setTool(TOOLKEY[k]);
  });

  // ------------------------------------------------------------ layers panel
  function syncLettered() {                 // off with the craters, greyed out, its own setting kept
    const on = set.crater, inp = $('#l-lettered');
    inp.disabled = !on; inp.closest('.row').classList.toggle('off', !on);
  }
  document.querySelectorAll('[data-layer]').forEach((inp) => inp.onchange = () => { set[inp.dataset.layer] = inp.checked; syncLettered(); save(); redraw(); });
  document.querySelectorAll('#night button').forEach((b) => b.onclick = () => {
    set.night = b.dataset.v; document.querySelectorAll('#night button').forEach((x) => x.classList.toggle('on', x === b)); save(); redraw();
  });
  const minPx = $('#minPx'), fsI = $('#fs'), fontSel = $('#fontSel');
  fontSel.innerHTML = (A.fonts && A.fonts.length ? A.fonts : ['IBM Plex Sans']).map((f) => `<option>${esc(f)}</option>`).join('');
  const sliders = (persist) => {
    set.minPx = +minPx.value; set.fs = +fsI.value;
    $('#minPxV').textContent = `craters ≥ ${set.minPx} px`; $('#fsV').textContent = Math.round(set.fs * 100) + ' %';
    if (persist) save();
    redraw();
  };
  minPx.oninput = () => sliders(true); fsI.oninput = () => sliders(true);
  fontSel.onchange = () => { set.font = fontSel.value; document.fonts.load(fontStr(500, 14, false)).finally(() => { save(); redraw(); }); };
  function setLayersFolded(c) { $('#layers').classList.toggle('collapsed', c); $('#layersHead').setAttribute('aria-expanded', String(!c)); redraw(); }
  const toggleLayers = () => { delete $('#layers').dataset.autofold; setLayersFolded(!$('#layers').classList.contains('collapsed')); };
  $('#layersHead').onclick = toggleLayers;
  $('#layersHead').onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleLayers(); } };
  $('#fitBtn').onclick = fit;
  $('#oneBtn').onclick = () => flyTo(view.x, view.y, 1);

  // ------------------------------------------------------------ export (runs lunaratlas.py export)
  let jobRunning = false;
  $('#exportBtn').onclick = openExport;
  function openExport() {
    const el = $('#export');
    const [vx0, vy0] = img(0, 0), [vx1, vy1] = img(VW, VH);
    const vr = [Math.max(0, Math.round(vx0)), Math.max(0, Math.round(vy0)), Math.min(A.width, Math.round(vx1)), Math.min(A.height, Math.round(vy1))];
    el.innerHTML = `<div class="dialog" role="dialog" aria-label="Export">
      <div class="top"><div>
        <h2>Export labelled image</h2>
        <p class="lead">Names, your drawings and measurements are drawn into your image at 1:1 or smaller, never upscaled.</p>
      </div><div class="preview"><canvas id="xPrev" aria-label="Preview of the export"></canvas><span>Preview</span></div></div>
      <fieldset><legend>Region</legend><div class="opts">
        <label class="opt"><input type="radio" name="reg" value="all" checked><span>Whole image<small>${A.width} × ${A.height} px</small></span></label>
        <label class="opt"><input type="radio" name="reg" value="view"><span>Current view<small>${vr[2] - vr[0]} × ${vr[3] - vr[1]} px</small></span></label>
        <label class="opt"><input type="radio" name="reg" value="feature" ${selected ? '' : 'disabled'}><span>Around feature<small>${selected ? esc(selected.n) : 'select one first'}</small></span></label>
      </div></fieldset>
      <fieldset><legend>Scale</legend><div class="opts">
        <label class="opt"><input type="radio" name="sc" value="1" checked><span>1:1<small>captured resolution</small></span></label>
        <label class="opt"><input type="radio" name="sc" value="half"><span>1:2<small>half size</small></span></label>
        <label class="opt"><input type="radio" name="sc" value="max"><span>Longest side<small><input type="number" id="maxSide" value="4096" min="256" step="256" class="num"> px</small></span></label>
      </div></fieldset>
      <fieldset><legend>Format</legend><div class="opts">
        <label class="opt"><input type="radio" name="fmt" value="tiff" checked><span>TIFF<small>16-bit</small></span></label>
        <label class="opt"><input type="radio" name="fmt" value="png"><span>PNG<small>16-bit</small></span></label>
        <label class="opt"><input type="radio" name="fmt" value="jpg"><span>JPEG<small>8-bit, quality 92</small></span></label>
      </div></fieldset>
      <fieldset><legend>Include</legend><div class="checks">
        <label><input type="checkbox" id="xNames" checked> Names (as in Layers)</label>
        <label><input type="checkbox" id="xRims" checked> Crater outlines</label>
        <label><input type="checkbox" id="xGrid" checked> Lat/lon grid</label>
        <label><input type="checkbox" id="xMine" checked> My drawings and measurements (${E.shapes.length})</label>
        <label><input type="checkbox" id="xInfo" checked> Info block (date, scale bar, north)</label>
        <label><input type="checkbox" id="xNorth"> North up, east right <small>(turns the picture; not with the current view)</small></label>
      </div></fieldset>
      <div class="outsize"><span>Output</span><b id="outSize"></b></div>
      <div class="progress" id="xProg" hidden><div class="bar"><div></div></div><pre id="xLog"></pre></div>
      <div class="foot"><button class="btn ghost" id="xCancel">Close</button><button class="btn" id="xReveal" hidden>Show in Finder</button><button class="btn primary" id="xGo"><svg width="15" height="15"><use href="#i-down"/></svg>Export</button></div>
    </div>`;
    el.hidden = false;
    const opts = () => {
      const north = $('#xNorth').checked, viewRadio = el.querySelector('[name=reg][value=view]');
      viewRadio.disabled = north;                  // the view's box counts pixels of the picture as it was taken
      if (north && viewRadio.checked) el.querySelector('[name=reg][value=all]').checked = true;
      const reg = el.querySelector('[name=reg]:checked').value, sc = el.querySelector('[name=sc]:checked').value, fmt = el.querySelector('[name=fmt]:checked').value;
      let w = A.width, h = A.height;
      const o = { format: fmt, scale: sc === '1' ? null : sc, max_size: +$('#maxSide').value || 4096, names: $('#xNames').checked,
                  layers: LAYERS5.filter(shown), rims: $('#xRims').checked, grid: $('#xGrid').checked,
                  drawings: $('#xMine').checked, info: $('#xInfo').checked, night: set.night, min_px: set.minPx, font_scale: set.fs, font: set.font };
      if (north) o.north_up = true;
      if (reg === 'view') { w = vr[2] - vr[0]; h = vr[3] - vr[1]; o.region = 'view'; o.box = [vr[0], vr[1], w, h]; }
      if (reg === 'feature' && selected) { w = Math.min(A.width, Math.max(600, Math.round(selected.dpx * 3))); h = Math.round(w * 2 / 3); o.region = 'feature'; o.name = selected.n; o.size = [w, h]; }
      const s = sc === 'half' ? 0.5 : sc === 'max' ? Math.min(1, o.max_size / Math.max(w, h)) : 1;
      $('#outSize').textContent = `${Math.round(w * s)} × ${Math.round(h * s)} px · ${fmt === 'jpg' ? 'JPEG' : '16-bit ' + fmt.toUpperCase()}${north ? ' · turned: the canvas grows to hold it' : ''}`;
      const box = reg === 'view' ? vr.slice() : reg === 'feature' && selected
        ? [selected.x - w / 2, selected.y - h / 2, selected.x + w / 2, selected.y + h / 2] : [0, 0, A.width, A.height];
      schedulePreview(box, s, o);
      return o;
    };
    el.querySelectorAll('input').forEach((i) => i.addEventListener('input', opts));
    opts();
    $('#xCancel').onclick = () => { if (!jobRunning) el.hidden = true; };
    el.onclick = (e) => { if (e.target === el && !jobRunning) el.hidden = true; };
    $('#xReveal').onclick = () => fetch('/reveal', { method: 'POST', body: '{}' });
    $('#xGo').onclick = async () => {
      try { await flush(); } catch {                // the export reads the drawings from the sidecar: not saved, it would leave them out
        toast('Your drawings could not be saved, so the export was not started. Is LunarAtlas still running?'); return;
      }
      const r = await fetch('/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts()) });
      const j = await r.json();
      if (!r.ok) { toast(j.error || 'Export could not start'); return; }
      jobRunning = true; $('#xGo').disabled = true; $('#xProg').hidden = false; $('#xReveal').hidden = true;
      const bar = el.querySelector('.progress .bar > div'), steps = ['positioning', 'view:', 'labels placed', 'labels drawn', 'wrote'];
      bar.classList.remove('failed');
      const poll = async () => {
        const s = await (await fetch('/export/status')).json();
        $('#xLog').textContent = s.lines.join('\n');
        $('#xLog').scrollTop = 1e9;
        const done = steps.filter((k) => s.lines.some((l) => l.includes(k))).length;
        bar.style.width = (s.state === 'done' ? 100 : Math.min(95, 10 + 85 * done / steps.length)) + '%';
        if (s.state === 'running') { setTimeout(poll, 400); return; }
        jobRunning = false; $('#xGo').disabled = false;
        if (s.state === 'done') { toast(`Written: ${s.output.split('/').pop()} (${(s.size_bytes / 1e6).toFixed(1)} MB)`); $('#xReveal').hidden = false; }
        else { bar.style.width = '100%'; bar.classList.add('failed'); toast('Export failed: ' + (s.error || '')); }
      };
      poll();
    };
  }

  // ------------------------------------------------------------ quality: a chip in the status bar, the explanation on click
  function showGate() {
    const line = A.gate || '', reasons = window.LA_FRIENDLY ? LA_FRIENDLY.gate(line) : [];
    const chip = $('#gate'), pop = $('#gatePop');
    if (!/^quality refused/.test(line)) { chip.hidden = true; return; }
    chip.querySelector('span').textContent = reasons.length === 1 ? reasons[0].title : `Low quality${reasons.length ? ' · ' + reasons.length + ' issues' : ''}`;
    chip.title = 'Why the names may be less accurate on this photo';
    chip.hidden = false;
    chip.setAttribute('aria-expanded', 'false');
    const close = () => { pop.hidden = true; chip.setAttribute('aria-expanded', 'false'); redraw(); };
    chip.onclick = (e) => {
      e.stopPropagation();
      if (!pop.hidden) { close(); return; }
      pop.innerHTML = `<button class="close" aria-label="Close"><svg width="16" height="16"><use href="#i-x"/></svg></button>
        <h4><svg width="14" height="14"><use href="#i-warn"/></svg>Photo quality</h4>
        <p>This photo did not pass the quality check and was named anyway, so names may be placed less accurately. What the check found:</p>
        <ul>${reasons.map((r) => `<li><b>${esc(r.title)}</b><span>${esc(r.text)}</span><small>${esc(r.raw)}</small></li>`).join('')}</ul>
        <div class="raw">${esc(line)}</div>`;
      pop.hidden = false;
      const r = chip.getBoundingClientRect();
      pop.style.left = Math.max(14, Math.min(r.left, VW - pop.offsetWidth - 14)) + 'px';
      chip.setAttribute('aria-expanded', 'true');
      pop.querySelector('.close').onclick = close;
      pop.querySelector('.close').focus();
      redraw();
    };
    document.addEventListener('click', (e) => { if (!pop.hidden && !pop.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pop.hidden) { close(); chip.focus(); } });
  }

  // the export's look in small: the same drawing code on a small canvas, names and lines scaled as in the output
  let prevT = null;
  function schedulePreview(box, outScale, o) {
    clearTimeout(prevT);
    tilesIdle = null;
    prevT = setTimeout(() => {
      renderPreview(box, outScale, o);                                   // once; again only when a tile it wanted has arrived
      tilesIdle = loadingTiles ? () => renderPreview(box, outScale, o) : null;
    }, 30);
  }
  function renderPreview(box, outScale, o) {
    const cv = $('#xPrev'); if (!cv) return;
    const bw = Math.max(1, box[2] - box[0]), bh = Math.max(1, box[3] - box[1]), k = Math.min(176 / bw, 132 / bh), q = 2;
    cv.width = Math.max(1, Math.round(bw * k * q)); cv.height = Math.max(1, Math.round(bh * k * q));
    cv.style.width = cv.width / q + 'px'; cv.style.height = cv.height / q + 'px';
    const keep = { ctx, VW, VH, dpr, placed, view: { ...view }, set: { ...set } };
    try {
      ctx = cv.getContext('2d'); VW = cv.width; VH = cv.height; dpr = 1; offscreen = true;
      view.s = k * q; view.x = (box[0] + box[2]) / 2; view.y = (box[1] + box[3]) / 2;
      const f = view.s / (outScale || 1);                 // preview px per output px
      Object.assign(set, { grid: o.grid, rims: o.rims, mine: o.drawings, minPx: keep.set.minPx * f, fs: keep.set.fs * f });
      if (!o.names) for (const l of LAYERS5) set[l] = false;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, VW, VH);
      drawTiles(); drawGrid(); drawLabels(); drawGridLabels();
      if (set.mine) for (const sh of E.shapes) drawShape(sh);
    } finally {
      ({ ctx, VW, VH, dpr, placed } = keep); offscreen = false;
      Object.assign(view, keep.view); Object.assign(set, keep.set);
    }
  }

  // ------------------------------------------------------------ misc + start
  let tt = null;
  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(tt); tt = setTimeout(() => t.classList.remove('show'), 2800); }
  function resize() {
    dpr = window.devicePixelRatio || 1; VW = window.innerWidth; VH = window.innerHeight;
    canvas.width = Math.round(VW * dpr); canvas.height = Math.round(VH * dpr); redraw();
  }
  window.addEventListener('resize', resize);
  function applyStyle(st) {
    if (!st) return;
    if (st.font && (A.fonts || []).includes(st.font)) { set.font = st.font; fontSel.value = st.font; }
    if (st.minPx) minPx.value = st.minPx;
    if (st.fs) fsI.value = st.fs;
    if (st.night) { set.night = st.night; document.querySelectorAll('#night button').forEach((x) => x.classList.toggle('on', x.dataset.v === st.night)); }
    if (Array.isArray(st.layers)) { for (const l of LAYERS5) { set[l] = st.layers.includes(l); $('#l-' + l).checked = set[l]; } syncLettered(); }
    for (const k of ['grid', 'rims']) if (typeof st[k] === 'boolean') { set[k] = st[k]; $('#l-' + k).checked = st[k]; }
  }
  function applyHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    if (h.has('grid')) { set.grid = true; $('#l-grid').checked = true; }
    if (h.has('q')) {
      const f = FE.find((o) => o.key === norm(h.get('q')));
      if (f) { view.s = clamp(f.dpx > 0 ? 0.28 * Math.min(VW, VH) / f.dpx : 1, minS(), 1.5); view.x = f.x; view.y = f.y; select(f); }
    }
    if (h.has('s')) view.s = +h.get('s');
    if (h.has('x')) view.x = +h.get('x');
    if (h.has('y')) view.y = +h.get('y');
    if (h.has('export')) openExport();
    redraw();
  }
  window.addEventListener('hashchange', applyHash);
  window.__atlas = { get placed() { return placed; }, get edits() { return E; }, get hidden() { return hiddenSet; }, get picks() { return picks; }, view, render };   // for tests/viewer_selftest.js
  resize();
  showGate();
  fetch('/edits').then((r) => r.json()).then((e) => {
    try {
      const p = JSON.parse(localStorage.getItem(PENDING) || 'null');
      localStorage.removeItem(PENDING);
      if (p && Array.isArray(p.shapes)) { e = p; setTimeout(save, 0); }
    } catch { /* no storage */ }
    E = { shapes: Array.isArray(e.shapes) ? e.shapes : [], hidden: [], labels: e.labels || {}, style: e.style || {} };
    hiddenSet = new Set(Array.isArray(e.hidden) ? e.hidden : []);
    applyStyle(E.style); syncLettered();
    $('#n-mine').textContent = E.shapes.length;
    $('#saveState').textContent = E.shapes.length || hiddenSet.size || Object.keys(E.labels).length ? 'edits loaded' : '';
  }).catch(() => toast('Could not load your edits')).finally(() => {
    sliders(false);
    document.fonts.load(fontStr(500, 14, false)).then(() => document.fonts.load(fontStr(400, 14, true))).finally(() => { fit(); applyHash(); });
  });
  fit();
})();
