// Settings: the equipment and the observing site (equipment.json through /app/equipment).
const $ = (s) => document.querySelector(s);
let doc = null, setups = [], dirty = false;
const num = (s) => { const x = parseFloat(String(s).replace(',', '.')); return isFinite(x) ? x : null; };

function changed() { dirty = true; $('#save').disabled = false; say(''); }
function say(text, bad) { $('#msg').textContent = text; $('#msg').classList.toggle('bad', !!bad); }

function input(value, label, onInput, opts = {}) {
  const i = document.createElement('input');
  i.value = value == null ? '' : value;
  i.setAttribute('aria-label', label);
  if (opts.num) i.inputMode = 'decimal';
  if (opts.placeholder) i.placeholder = opts.placeholder;
  i.oninput = () => { onInput(opts.num ? num(i.value) : i.value); changed(); };
  return i;
}
function remove(label, onClick) {
  const b = document.createElement('button'); b.className = 'x'; b.type = 'button'; b.textContent = '×';
  b.setAttribute('aria-label', 'Remove ' + label); b.onclick = () => { onClick(); changed(); render(); };
  return b;
}
function head(cols) {
  const r = document.createElement('div'); r.className = 'row head';
  for (const c of cols) { const s = document.createElement('span'); s.textContent = c; r.append(s); }
  return r;
}

function render() {
  const T = $('#telescopes'); T.textContent = '';
  if (doc.telescopes.length) T.append(head(['Name', 'Focal length, mm', 'Aperture, mm (optional)', '']));
  doc.telescopes.forEach((t, k) => {
    const r = document.createElement('div'); r.className = 'row';
    r.append(input(t.name, 'Telescope name', (v) => { t.name = v; }),
      input(t.focal_mm, 'Focal length in mm', (v) => { t.focal_mm = v; }, { num: true }),
      input(t.aperture_mm, 'Aperture in mm', (v) => { if (v == null) delete t.aperture_mm; else t.aperture_mm = v; }, { num: true, placeholder: '—' }),
      remove(t.name || 'telescope', () => doc.telescopes.splice(k, 1)));
    T.append(r);
  });
  if (!doc.telescopes.length) T.innerHTML = '<p class="empty">No telescope yet.</p>';

  const B = $('#barlows'); B.textContent = '';
  if (doc.barlows.length) B.append(head(['Name', 'Factor', '']));
  doc.barlows.forEach((b, k) => {
    const r = document.createElement('div'); r.className = 'row';
    r.append(input(b.name, 'Barlow name', (v) => { b.name = v; }),
      input(b.factor, 'Barlow factor', (v) => { b.factor = v; }, { num: true }),
      remove(b.name || 'barlow', () => doc.barlows.splice(k, 1)));
    B.append(r);
  });
  if (!doc.barlows.length) B.innerHTML = '<p class="empty">No barlow: only native focus.</p>';

  const C = $('#cameras'); C.textContent = '';
  if (doc.cameras.length) C.append(head(['Name', 'Sensor', 'Pixel, µm', 'Binning', '']));
  doc.cameras.forEach((c, k) => {
    const r = document.createElement('div'); r.className = 'row';
    const bins = document.createElement('div'); bins.className = 'bins';
    for (const n of [1, 2, 3, 4]) {
      const l = document.createElement('label'), cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = (c.binnings || [1]).includes(n);
      cb.onchange = () => {
        const s = new Set(c.binnings || [1]); cb.checked ? s.add(n) : s.delete(n);
        if (!s.size) { cb.checked = true; return; }
        c.binnings = [...s].sort(); changed();
      };
      l.append(cb, `${n}×${n}`); bins.append(l);
    }
    r.append(input(c.name, 'Camera name', (v) => { c.name = v; }),
      input(c.sensor, 'Sensor', (v) => { c.sensor = v; }, { placeholder: '—' }),
      input(c.pixel_um, 'Pixel size in µm', (v) => { c.pixel_um = v; }, { num: true }),
      bins, remove(c.name || 'camera', () => doc.cameras.splice(k, 1)));
    C.append(r);
  });
  if (!doc.cameras.length) C.innerHTML = '<p class="empty">No camera yet.</p>';

  renderSetups();
}
function renderSite() {
  const s = doc.site || {};
  $('#lat').value = s.lat ?? ''; $('#lon').value = s.lon ?? ''; $('#height').value = s.height_m || '';
}

function renderSetups() {
  const tb = $('#setups tbody'); tb.textContent = '';
  const unused = new Set(doc.unused);
  for (const s of setups) {
    const tr = document.createElement('tr'), on = !unused.has(s.id);
    tr.className = on ? '' : 'off';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = on; cb.setAttribute('aria-label', 'Use ' + s.text);
    cb.onchange = () => {
      doc.unused = cb.checked ? doc.unused.filter((x) => x !== s.id) : [...doc.unused, s.id];
      tr.className = cb.checked ? '' : 'off'; changed();
    };
    const td = (t, n) => { const c = document.createElement('td'); c.textContent = t; if (n) c.className = 'n'; return c; };
    const first = document.createElement('td'); first.append(cb);
    const f = s.field_arcmin, shows = document.createElement('td');
    if (f) {
      const tag = document.createElement('span'), full = Math.min(f[0], f[1]) >= 30;     // the Moon is 29.4–33.5′ across
      tag.className = 'tag ' + (full ? 'fd' : 'cu'); tag.textContent = full ? 'full disk' : 'close-up'; shows.append(tag);
    }
    tr.append(first, td(s.telescope), td(s.extender === 'native' ? 'none' : s.extender),
      td(s.camera + (s.binning ? ' · ' + s.binning : '')), td(Math.round(s.focal_mm) + ' mm', 1), td(s.arcsec.toFixed(2) + '″/px', 1),
      td(f ? `${Math.round(f[0])}′ × ${Math.round(f[1])}′` : '—', 1), shows);
    tb.append(tr);
  }
  $('#setups').hidden = !setups.length; $('#nosetups').hidden = !!setups.length;
}

function siteFromInputs() {
  const lat = num($('#lat').value), lon = num($('#lon').value), h = num($('#height').value);
  if ($('#lat').value.trim() === '' && $('#lon').value.trim() === '') return null;
  return { lat, lon, height_m: h || 0 };
}

async function load() {
  const j = await (await fetch('/app/equipment')).json();
  doc = j.equipment; setups = j.setups; dirty = false; $('#save').disabled = true;
  render(); renderSite();
}

async function save() {
  doc.site = siteFromInputs();
  $('#save').disabled = true; say('Saving…');
  try {
    const r = await fetch('/app/equipment', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ equipment: doc }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    doc = j.equipment; setups = j.setups; dirty = false; render(); renderSite(); say('Saved.');
  } catch (e) { $('#save').disabled = false; say('Not saved: ' + e.message, true); }
}

$('#addt').onclick = () => { doc.telescopes.push({ name: '', focal_mm: null }); changed(); render(); $('#telescopes .row:last-child input').focus(); };
$('#addb').onclick = () => { doc.barlows.push({ name: 'Barlow', factor: 2 }); changed(); render(); $('#barlows .row:last-child input').focus(); };
window.LA_EQ.picker($('#camq'), $('#camlist'), (c) => {
  doc.cameras.push(c.custom ? { name: c.name || 'Camera', pixel_um: null, binnings: [1] }
    : { name: c.name, sensor: c.sensor, pixel_um: c.pixel_um, width: c.width, height: c.height, binnings: [1] });
  $('#camq').value = ''; changed(); render();
  if (c.custom) $('#cameras .row:last-child').querySelectorAll('input')[2].focus();     // its pixel size
});
for (const id of ['#lat', '#lon', '#height']) $(id).oninput = changed;
$('#locate').onclick = () => {
  if (!navigator.geolocation) { $('#sitemsg').textContent = 'This browser cannot tell the location.'; return; }
  $('#sitemsg').textContent = 'Asking the browser…';
  navigator.geolocation.getCurrentPosition((p) => {
    $('#lat').value = p.coords.latitude.toFixed(1); $('#lon').value = p.coords.longitude.toFixed(1);
    if (p.coords.altitude != null) $('#height').value = Math.round(p.coords.altitude / 10) * 10;
    $('#sitemsg').textContent = 'Filled in (rounded): Save to keep it.'; changed();
  }, (e) => { $('#sitemsg').textContent = 'No location: ' + (e.message || 'refused') + '. Type it in instead.'; },
  { enableHighAccuracy: false, timeout: 15000, maximumAge: 3600e3 });
};
$('#clearsite').onclick = () => { $('#lat').value = $('#lon').value = $('#height').value = ''; $('#sitemsg').textContent = ''; changed(); };
$('#reset').onclick = async () => {
  if (!confirm('Forget all equipment and the observing site?')) return;
  doc = { telescopes: [], barlows: [], cameras: [], site: null, unused: [], recent: [] };
  render(); renderSite(); await save();
};
$('#save').onclick = save;
window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
// the launcher stops a while after its last page is gone (browser mode): this page counts too
setInterval(() => fetch('/app/ping').catch(() => {}), 20000);
load().catch((e) => say('Could not read the equipment: ' + e.message, true));
