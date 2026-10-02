const $ = (s) => document.querySelector(s);
const show = (id, on = true) => { $(id).hidden = !on; };
const post = (url, obj) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj || {}) })
  .then(async (r) => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; });
const STAMP = /\d{4}-\d{2}-\d{2}-\d{4}_\d/;
const FR = window.LA_FRIENDLY;
let file = null, path = null, t0 = 0, timer = null, xhr = null, lastForce = false;

function mb(n) { return n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : (n / 1e6).toFixed(1) + ' MB'; }

// ------------------------------------------------------------ the photo being worked on
// The server's own thumbnail, the moment there is a path to ask for: it reads TIFF, which no browser does, and it is
// already cached from the earlier-photos list.  Before the upload has answered there is no path yet, so a small
// JPEG or PNG is shown from the browser's own copy instead; a big one would cost the renderer hundreds of megabytes
// to decode for a 56 px square, and browsers cannot decode a TIFF at all.
const PREVIEW_MAX = 20 << 20;
let thumbURL = null, thumbSrc = '', thumbBad = '';
function showPhoto() {
  const box = $('#wthumb'), img = $('#wimg');
  const local = !path && file && /\.(jpe?g|png)$/i.test(file.name) && file.size <= PREVIEW_MAX;
  const src = path ? '/app/thumb?path=' + encodeURIComponent(path)
    : local ? (thumbURL = thumbURL || URL.createObjectURL(file)) : '';
  if (thumbURL && !local) { URL.revokeObjectURL(thumbURL); thumbURL = null; }
  $('#wname').textContent = file ? file.name : path ? path.split(/[\\/]/).pop() : '';
  if (!src || src === thumbBad) { box.hidden = true; return; }   // nothing to show, or this one could not be made
  if (src !== thumbSrc) {
    thumbSrc = src;
    img.alt = '';                                                 // the name beside it says which photo this is
    img.onerror = () => { thumbBad = src; box.hidden = true; };   // a photo that cannot be shown leaves no empty frame
    img.src = src;
  }
  box.hidden = false;
}

// ------------------------------------------------------------ stages
// the bar is split over the stages; "Downloading Moon maps" only gets room once a download starts (first run)
const STAGES = [
  { id: 'load', name: 'Loading the photo' },
  { id: 'date', name: 'Reading date and libration' },
  { id: 'maps', name: 'Downloading Moon maps', idle: 'first run only' },
  { id: 'search', name: 'Searching the Moon' },
  { id: 'refine', name: 'Refining the fit' },
  { id: 'done', name: 'Opening the viewer' },
];
const W_PLAIN = { load: .08, date: .07, maps: 0, search: .55, refine: .22, done: .08 };
const W_MAPS = { load: .08, date: .07, maps: .40, search: .25, refine: .12, done: .08 };
let st = null;
function resetStages() {
  st = { i: 0, within: 0, shown: 0, maps: false, dl: { files: 0, doneMB: 0, cur: 0, curTotal: 0, closeup: false }, stepText: '', failed: false };
  $('#stages').innerHTML = STAGES.map((s) => `<li data-id="${s.id}"><span class="dot"></span><span>${s.name}</span><span class="note"></span></li>`).join('');
  $('#bar i').style.transition = 'none'; $('#bar i').style.width = '0'; void $('#bar').offsetWidth; $('#bar i').style.transition = '';
  $('#bar').classList.remove('failed');
  renderStages();
}
function stageOf(l) {                     // which stage a log line proves we have reached (-1: none)
  if (/^\s*download(ing|ed)\b/.test(l)) return 2;
  if (/preparing the viewer/.test(l)) return 5;
  if (/rms|candidate scales|close-up located|^result:|optics recognised|^saved /.test(l)) return 4;
  if (/search:|^orientation|candidate \d|reference:|disk \d+ px|searching the image/.test(l)) return 3;
  if (/^capture |^limb:|^quality/.test(l)) return 1;
  return 0;
}
function readLines(lines) {
  let i = st.i, dl = { files: 0, doneMB: 0, cur: 0, curTotal: 0, closeup: false }, step = '';
  for (const raw of lines) {
    const l = String(raw).trim();
    i = Math.max(i, stageOf(l));
    if (/^downloading\b/.test(l)) { dl.files++; dl.doneMB += dl.curTotal; dl.cur = 0; dl.curTotal = 0; }
    const m = /^downloaded ([\d.]+) of ([\d.]+) MB/.exec(l);
    if (m) { dl.cur = +m[1]; dl.curTotal = +m[2]; }
    if (/as a close-up|LOLA elevation model, 64/.test(l)) dl.closeup = true;
    const f = FR.line(l); if (f) step = f;
    const s = /search: (\d+)\/(\d+) views/.exec(l);
    if (s) st.searchFrac = +s[1] / +s[2];
  }
  if (dl.files) st.maps = true;
  st.dl = dl; st.i = i; st.stepText = step;
}
function frac() {                          // 0..1 for the bar: finished stages + a share of the active one
  const W = st.maps ? W_MAPS : W_PLAIN;
  let f = 0;
  for (let k = 0; k < st.i; k++) f += W[STAGES[k].id];
  const id = STAGES[st.i].id, w = W[id];
  let within;
  const secs = (Date.now() - (st.since || Date.now())) / 1000;
  if (id === 'maps') {
    const d = st.dl, done = d.doneMB + d.cur, plan = Math.max(d.closeup ? 675 : 145, done + (d.curTotal - d.cur));
    within = Math.min(.97, done / plan);
  } else if (id === 'search' && st.searchFrac != null) within = Math.min(.97, st.searchFrac);
  else if (id === 'load' && st.upload != null) within = st.upload * .9;
  else within = 1 - Math.exp(-secs / (id === 'search' ? 18 : 6));     // an easing guess, never reaching the end
  return f + w * Math.min(.95, within);
}
function renderStages() {
  STAGES.forEach((s, k) => {
    const li = $(`#stages li[data-id="${s.id}"]`);
    const skip = s.id === 'maps' && !st.maps && st.i > 2;
    li.className = st.failed && k === st.i ? 'failed' : skip ? 'skip' : k < st.i ? 'done' : k === st.i ? 'active' : '';
    let note = '';
    if (s.id === 'maps') {
      const d = st.dl;
      if (skip) note = 'already on this computer';
      else if (st.maps) note = `${(d.doneMB + d.cur).toFixed(0)} MB${d.curTotal ? ` · file ${d.files}: ${d.cur.toFixed(0)} of ${d.curTotal.toFixed(0)} MB` : ''}`;
      else if (k > st.i) note = s.idle;
    }
    if (s.id === 'search' && k === st.i && st.searchFrac != null) note = Math.round(st.searchFrac * 100) + ' %';
    if (s.id === 'load' && k === st.i && st.upload != null) note = `copying ${Math.round(st.upload * 100)} %`;
    li.querySelector('.note').textContent = note;
    if (k === st.i && !st.failed) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  const f = Math.max(st.shown, st.i === STAGES.length - 1 && st.ready ? 1 : frac());    // never backwards
  st.shown = f;
  $('#bar i').style.width = (f * 100).toFixed(1) + '%';
  $('#bar').setAttribute('aria-valuenow', Math.round(f * 100));
  $('#wstep').textContent = st.stepText;
}
function toStage(i) { if (i > st.i) { st.i = i; st.since = Date.now(); st.searchFrac = i === 3 ? null : st.searchFrac; } }

// ------------------------------------------------------------ flow
function choose(f) {
  if (!f) return;
  if (!/\.(tiff?|png|jpe?g)$/i.test(f.name)) { alert('Please choose a TIFF, PNG or JPEG image.'); return; }
  file = f;
  $('#fname').textContent = f.name;
  $('#fsize').textContent = mb(f.size);
  show('#timebox', !STAMP.test(f.name));
  show('#whenfrom', false);
  if (!STAMP.test(f.name)) prefillTime(f);
  show('#pick', false); show('#details'); show('#work', false); show('#recentbox', false);
  $('#go').focus();
}

// the camera's EXIF time in the box, said where it came from; never over a time the user typed
async function prefillTime(f) {
  const t = await window.LA_EXIF.captureTime(f);
  if (!t || file !== f || $('#when').value) return;
  $('#when').value = t.when;
  $('#whenfrom').textContent = t.zone
    ? `From the camera (recorded at UTC${t.zone}), shown in your time zone. Change it if it is wrong.`
    : 'From the camera’s clock. Check it: cameras are often set to the wrong time zone, or never set at all.';
  show('#whenfrom');
}

function reset() {
  file = null; path = null; clearInterval(timer);
  thumbURL && URL.revokeObjectURL(thumbURL);
  thumbURL = null; thumbSrc = ''; thumbBad = '';
  showPhoto();
  $('#file').value = ''; $('#when').value = ''; show('#whenfrom', false);
  show('#pick'); show('#details', false); show('#work', false);
  loadRecent();
  $('#drop').focus();
}

function working(title) {
  show('#pick', false); show('#details', false); show('#work'); show('#recentbox', false);
  $('#wtitle').textContent = title;
  show('#werr', false); show('#force', false); show('#again', false); show('#stop');
  $('#stop').disabled = false;
  $('#log').textContent = '';
  resetStages(); st.since = Date.now();
  showPhoto();                       // the photo this run is about, from the file or from the path we have
  t0 = Date.now();
}

function fail(msg, refused) {
  clearInterval(timer);
  st.failed = true; renderStages();
  $('#bar').classList.add('failed');
  const e = FR.error(msg, refused);
  $('#wtitle').textContent = e.title;
  $('#werr').innerHTML = '';
  const p = document.createElement('p'); p.textContent = e.text;
  $('#werr').append(p);
  if (e.reasons.length) {
    const ul = document.createElement('ul');
    for (const r of e.reasons) {
      const li = document.createElement('li');
      li.innerHTML = '<b></b> <span></span><small></small>';
      li.querySelector('b').textContent = r.title + '.';
      li.querySelector('span').textContent = r.text;
      li.querySelector('small').textContent = r.raw;
      ul.append(li);
    }
    $('#werr').append(ul);
  }
  show('#werr'); show('#stop', false); show('#again'); show('#force', !!refused);
  $('#wstep').textContent = '';
  $('#wtime').textContent = '';
  (refused ? $('#force') : $('#again')).focus();
}

function upload() {
  // the file itself is the request body: no form encoding, fine for mosaics of hundreds of MB
  working('Finding where this is on the Moon');
  st.upload = 0; renderStages();
  let when = '';
  if (!$('#timebox').hidden && $('#when').value) when = new Date($('#when').value).toISOString().slice(0, 16);
  const x = xhr = new XMLHttpRequest();
  x.open('POST', '/app/upload?name=' + encodeURIComponent(file.name) + '&time=' + encodeURIComponent(when));
  x.upload.onprogress = (e) => { if (e.lengthComputable) { st.upload = e.loaded / e.total; renderStages(); } };
  x.onload = () => {
    xhr = null;
    let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { /* shown below */ }
    if (x.status !== 200) return fail(j.error || 'the copy failed');
    path = j.path; st.upload = null;
    begin(j.located ? '/app/open' : '/app/locate', {});
  };
  x.onabort = () => { xhr = null; reset(); };
  x.onerror = () => { xhr = null; fail('the copy failed: is LunarAtlas still running?'); };
  x.send(file);
  tick();
}

function start(url, extra) {                 // from the list of earlier photos
  working(url === '/app/open' ? 'Opening' : 'Finding where this is on the Moon');
  begin(url, extra);
}
function begin(url, extra) {
  lastForce = !!(extra && extra.force);
  if (url === '/app/open') { toStage(5); $('#wtitle').textContent = 'Opening'; }
  showPhoto();                       // the upload has answered: the server's own thumbnail takes over from the file's
  renderStages();
  post(url, Object.assign({ path }, extra)).then(poll).catch((e) => fail(e.message));
}

function tick() {
  const secs = Math.round((Date.now() - t0) / 1000);
  $('#wtime').textContent = secs >= 3 ? `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}` : '';
}

function poll() {
  clearInterval(timer);
  timer = setInterval(async () => {
    let s;
    try { s = await (await fetch('/app/status')).json(); } catch (e) { return fail('LunarAtlas stopped running.'); }
    $('#log').textContent = s.lines.join('\n');
    $('#log').scrollTop = 1e9;
    tick();
    const before = st.i;
    readLines(s.lines);
    const i = st.i; st.i = before; toStage(i);
    if (s.phase === 'opening') { toStage(5); $('#wtitle').textContent = 'Opening the viewer'; $('#stop').disabled = true; }
    if (s.phase === 'idle') { clearInterval(timer); reset(); return; }         // cancelled
    renderStages();
    if (s.phase === 'ready') { clearInterval(timer); st.ready = true; renderStages(); location.href = '/'; }
    if (s.phase === 'failed') fail(s.error || 'unknown error', s.refused);
  }, 600);
}

async function stop() {
  $('#stop').disabled = true;
  if (xhr) { xhr.abort(); return; }
  try { const r = await post('/app/cancel'); if (!r.ok) $('#stop').disabled = false; }
  catch (e) { $('#stop').disabled = false; }
  $('#wstep').textContent = 'Stopping…';
}

// ------------------------------------------------------------ earlier photos
function when(t) {
  if (!t) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})( UTC)?/.exec(t);
  if (!m) return t;
  const d = m[6] ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5])) : new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]);
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
const TAG = { solved: ['ok', 'Solved'], low: ['warn', 'Low quality'], unsolved: ['off', 'Not solved'] };
async function loadRecent() {
  let r;
  try { r = await (await fetch('/app/recent')).json(); } catch (e) { return; }
  const f = r.folder, home = /^(\/Users\/[^/]+|\/home\/[^/]+|[A-Z]:\\Users\\[^\\]+)/.exec(f);
  let short = home ? '~' + f.slice(home[0].length) : f;
  if (short.length > 44) short = short.slice(0, 14) + '…' + short.slice(-28);      // the middle goes, both ends stay
  $('#folder').textContent = short; $('#folder').title = f + ' (show in the file manager)';
  const ul = $('#recent'); ul.textContent = '';
  for (const im of r.images) {
    const li = document.createElement('li');
    const th = document.createElement('div'); th.className = 'thumb';
    const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
    img.src = '/app/thumb?path=' + encodeURIComponent(im.path); img.onerror = () => img.remove();
    th.append(img);
    const meta = document.createElement('div'); meta.className = 'meta';
    const nm = document.createElement('div'); nm.className = 'name'; nm.title = im.name;
    const cut = Math.max(0, im.name.length - 12);         // the end (stamp tail, extension) always shows: middle truncation
    const a = document.createElement('span'); a.className = 'a'; a.textContent = im.name.slice(0, cut);
    const b = document.createElement('span'); b.className = 'b'; b.textContent = im.name.slice(cut);
    nm.append(a, b);
    const sub = document.createElement('div'); sub.className = 'sub';
    const tg = document.createElement('span'); const [cls, label] = TAG[im.status] || TAG.unsolved;
    tg.className = 'tag ' + cls; tg.textContent = label;
    if (im.status === 'low' && im.reasons.length) tg.title = im.reasons.map((x) => FR.quality(x).title).join(', ');
    const tm = document.createElement('span'); tm.textContent = when(im.taken) || 'time unknown';
    sub.append(tm, tg);
    meta.append(nm, sub);
    const btn = document.createElement('button'); btn.className = 'btn';
    const open = im.status === 'solved' || (im.status === 'low' && im.forced);
    btn.textContent = open ? 'Open' : im.status === 'low' ? 'Open anyway' : 'Find names';
    btn.setAttribute('aria-label', `${btn.textContent}: ${im.name}`);
    const go = () => {
      path = im.path;
      if (open) start('/app/open', {});
      else start('/app/locate', im.status === 'low' ? { force: true } : {});
    };
    btn.onclick = (e) => { e.stopPropagation(); go(); };
    li.onclick = go;
    li.append(th, meta, btn); ul.append(li);
  }
  show('#recentbox', ul.children.length > 0 && !$('#pick').hidden);
}

// ------------------------------------------------------------ wiring
$('#drop').onclick = () => $('#file').click();
$('#drop').onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#file').click(); } };
$('#file').onchange = (e) => choose(e.target.files[0]);
let depth = 0;
document.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; if (!$('#pick').hidden) $('#drop').classList.add('over'); });
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('dragleave', (e) => { e.preventDefault(); if (--depth <= 0) { depth = 0; $('#drop').classList.remove('over'); } });
document.addEventListener('drop', (e) => { e.preventDefault(); depth = 0; $('#drop').classList.remove('over'); if (!$('#pick').hidden) choose(e.dataTransfer.files[0]); });
$('#go').onclick = upload;
$('#cancel').onclick = reset;
$('#when').oninput = () => show('#whenfrom', false);      // the user's own time: the camera note no longer applies
$('#again').onclick = reset;
$('#stop').onclick = stop;
$('#force').onclick = () => { working('Finding where this is on the Moon'); begin('/app/locate', { force: true }); };
$('#copy').onclick = async () => {
  try { await navigator.clipboard.writeText($('#log').textContent); $('#copy').textContent = 'Copied'; }
  catch (e) { const r = document.createRange(); r.selectNodeContents($('#log')); getSelection().removeAllRanges(); getSelection().addRange(r); $('#copy').textContent = 'Selected'; }
  setTimeout(() => { $('#copy').textContent = 'Copy'; }, 1500);
};
$('#folder').onclick = (e) => { e.preventDefault(); post('/app/folder'); };
$('#quit').onclick = () => post('/app/quit').finally(() => {
  document.querySelector('main').innerHTML = '<header class="hero"><img src="/lunaratlas.svg" alt=""><div><h1>LunarAtlas has stopped</h1><p>You can close this tab.</p></div></header>';
});

// back from the viewer while something runs: pick the progress up again
fetch('/app/status').then((r) => r.json()).then((s) => {
  if (s.phase === 'locating' || s.phase === 'opening') { path = s.path; working('Finding where this is on the Moon'); poll(); }
}).catch(() => {});
loadRecent();
// the launcher stops a while after its last page is gone (browser mode): this page says it is still here
setInterval(() => fetch('/app/ping').catch(() => {}), 20000);

// for tests/ui/journeys.mjs: a top-level `let` is not a window property anywhere, but Chrome's CDP
// (Runtime.evaluate) still sees the page's own lexical scope, unlike Firefox's WebDriver/Marionette sandbox.
// There a bare `path = x` from a test silently makes a new global instead of setting the page's own `path`
// (so showPhoto() never saw it), hence the setters as well as the getter.
window.__app = { get st() { return st; }, set path(v) { path = v; }, set file(v) { file = v; } };
