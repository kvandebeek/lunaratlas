const REASONS = [['blurry','b'],['noisy','n'],['over-sharpened','s'],['overexposed','o'],['JPEG / compression','j'],
                 ['too small','t'],['colour / processing','c'],['not the Moon','m']];
let items = [], labels = {}, i = 0;
const $ = id => document.getElementById(id);
const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const load = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };

async function save(key) {
  $('saved').textContent = 'saving…';
  try {
    const r = await fetch('/labels.json', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({[key]: labels[key] || null})});
    if (!r.ok) throw new Error(r.status);
    $('saved').textContent = 'saved';
  } catch (e) { $('saved').textContent = 'NOT saved — is label_server.py still running?'; }
  store('labels_backup', JSON.stringify(labels));
}
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));   // file names are not to be trusted
function fmt(v, d = 2) { return v == null ? '–' : (typeof v === 'number' ? (+v.toFixed(d)).toString() : v); }
function visible() { return $('onlyOpen').checked ? items.filter(t => !labels[t.key]?.verdict) : items; }
function render() {
  const t = items[i]; if (!t) return;
  const lab = labels[t.key] || {};
  $('thumb').src = `/gallery/${t.key}_thumb.jpg`;
  const z = $('zoom').checked ? 1 : 1 / (window.devicePixelRatio || 1);
  for (const [id, show] of [['detail', true], ['limb', t.limb]]) {
    const im = $(id);
    im.onload = () => { im.style.width = (im.naturalWidth * z) + 'px'; };
    if (show) im.src = `/gallery/${t.key}_${id}.jpg`;
  }
  $('limbFig').style.display = t.limb ? '' : 'none';
  $('meta').innerHTML = (t.own ? '<span class="own">Your image</span> · ' : '') +
    `${t.width} × ${t.height} px · ${t.located ? `located (${t.matches} matches)` : 'not located'}<br>${esc(t.name)}`;
  $('measure').innerHTML = !$('showM').checked ? '' : `<table class="m">
    <tr><td>limb edge width</td><td>${fmt(t.edge_width_px)} px · ${fmt(t.edge_width_km)} km</td></tr>
    <tr><td>overshoot / undershoot</td><td>${fmt(t.overshoot)} / ${fmt(t.undershoot)}</td></tr>
    <tr><td>saturated</td><td>${fmt(100 * (t.saturated_share || 0))} %</td></tr>
    <tr><td>mare noise</td><td>${fmt(t.mare_noise, 4)}</td></tr>
    <tr><td>JPEG blocking</td><td>${fmt(t.jpeg_blocking)}</td></tr>
    <tr><td>octave ratios (fine → coarse)</td><td>${(t.octave_ratio || []).map(v => fmt(v)).join(' · ')}</td></tr>
    <tr><td>scale</td><td>${fmt(t.km_per_px, 3)} km/px</td></tr></table>`;
  document.querySelectorAll('#verdict button').forEach(b => b.classList.toggle('on', lab.verdict === b.dataset.v));
  document.querySelectorAll('#chips button').forEach(b => b.classList.toggle('on', (lab.reasons || []).includes(b.dataset.r)));
  $('note').value = lab.note || '';
  $('pos').textContent = `${i + 1} of ${items.length}`;
  const n = items.filter(t => labels[t.key]?.verdict).length;
  $('count').textContent = `${n} of ${items.length} labelled`;
  $('bar').style.width = (100 * n / items.length) + '%';
  $('done').style.display = n === items.length ? 'block' : 'none';
  document.querySelectorAll('.strip div').forEach((d, k) => {
    d.classList.toggle('cur', k === i);
    d.querySelector('span').className = labels[items[k].key]?.verdict || '';
  });
  store('label_pos', i);
}
function setLabel(patch) {
  const t = items[i];
  labels[t.key] = Object.assign({name: t.name}, labels[t.key] || {}, patch, {t: new Date().toISOString()});
  save(t.key); render();
}
function go(d) {
  const v = visible(); if (!v.length) return;
  let k = v.indexOf(items[i]);
  if (k < 0) k = d > 0 ? -1 : v.length;
  const nxt = v[Math.max(0, Math.min(v.length - 1, k + d))];
  i = items.indexOf(nxt); render(); window.scrollTo({top: 0});
}
document.querySelectorAll('#verdict button').forEach(b => b.onclick = () => {
  setLabel({verdict: b.dataset.v});
  if (b.dataset.v === 'good') setTimeout(() => go(1), 180);
});
$('chips').innerHTML = REASONS.map(([r, k]) => `<button data-r="${r}">${r}<kbd>${k}</kbd></button>`).join('');
document.querySelectorAll('#chips button').forEach(b => b.onclick = () => {
  const cur = new Set(labels[items[i].key]?.reasons || []);
  cur.has(b.dataset.r) ? cur.delete(b.dataset.r) : cur.add(b.dataset.r);
  setLabel({reasons: [...cur]});
});
let noteTimer;
$('note').oninput = () => { clearTimeout(noteTimer); noteTimer = setTimeout(() => setLabel({note: $('note').value}), 500); };
$('prev').onclick = () => go(-1); $('next').onclick = () => go(1);
['zoom', 'showM'].forEach(id => $(id).onchange = () => { store(id, $(id).checked ? '1' : ''); render(); });
$('onlyOpen').onchange = render;
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowRight') go(1); else if (e.key === 'ArrowLeft') go(-1);
  else if (e.key === '1') document.querySelector('[data-v=good]').click();
  else if (e.key === '2') document.querySelector('[data-v=borderline]').click();
  else if (e.key === '3') document.querySelector('[data-v=reject]').click();
  else { const r = REASONS.find(([, k]) => k === e.key.toLowerCase()); if (r) document.querySelector(`[data-r="${r[0]}"]`).click(); }
});
(async () => {
  items = await (await fetch('/items.json')).json();
  try { labels = await (await fetch('/labels.json')).json(); } catch (e) { labels = JSON.parse(load('labels_backup') || '{}'); }
  $('zoom').checked = load('zoom') === '1'; $('showM').checked = load('showM') === '1';
  $('strip').innerHTML = items.map((t, k) => `<div data-k="${k}" title="${esc(t.name)}"><img loading="lazy" src="/gallery/${t.key}_thumb.jpg"><span></span></div>`).join('');
  document.querySelectorAll('.strip div').forEach(d => d.onclick = () => { i = +d.dataset.k; render(); window.scrollTo({top: 0}); });
  i = Math.min(+(load('label_pos') || 0), items.length - 1);
  render();
})();
