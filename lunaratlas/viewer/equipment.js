// The equipment, shared by the launcher (the short form at the first close-up, "Taken with") and Settings:
// the camera catalogue and its search, the plate scale, and the short form itself.
(function () {
  let catalogue = null;

  // every catalogue entry as {name, sensor, pixel_um, width, height, group}
  async function cameras() {
    if (catalogue) return catalogue;
    let j = { sensors: {}, planetary: [], dslr: [] };
    try { j = await (await fetch('/cameras.json')).json(); } catch (e) { /* by hand only */ }
    const out = [];
    for (const [brand, model, sensor] of j.planetary) {
      const s = j.sensors[sensor]; if (!s) continue;
      out.push({ name: `${brand} ${model}`, sensor, pixel_um: s[0], width: s[1], height: s[2], group: 'Planetary cameras' });
    }
    for (const [sensor, s] of Object.entries(j.sensors)) {
      out.push({ name: `Sony ${sensor}`.replace('Sony AR', 'onsemi AR'), sensor, pixel_um: s[0], width: s[1], height: s[2],
        group: 'Sensors', any: true });
    }
    for (const [brand, model, um, w, h] of j.dslr) out.push({ name: `${brand} ${model}`, pixel_um: um, width: w, height: h, group: 'DSLR and mirrorless' });
    return (catalogue = out);
  }

  // the entries matching every word of q (in the name or sensor), at most n, catalogue order (grouped)
  function search(list, q, n = 12) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return list.filter((c) => words.every((w) => (c.name + ' ' + (c.sensor || '')).toLowerCase().includes(w))).slice(0, n);
  }

  const arcsec = (focal, factor, um, bin) => 206.265 * um * (bin || 1) / (focal * (factor || 1));

  // a camera search box: typing shows the matches under it, picking one calls onPick(entry); the last item lets the
  // user type a name and pixel size instead (onPick with custom: true)
  async function picker(input, list, onPick) {
    const all = await cameras();
    let hits = [], at = -1;
    function close() { list.hidden = true; list.textContent = ''; input.setAttribute('aria-expanded', 'false'); }
    function choose(c) { close(); onPick(c); }
    function render() {
      list.textContent = ''; at = -1;
      hits = search(all, input.value);
      let group = '';
      for (const c of hits) {
        if (c.group !== group) {
          group = c.group;
          const g = document.createElement('li'); g.className = 'grp'; g.textContent = group; g.setAttribute('role', 'presentation');
          list.append(g);
        }
        const li = document.createElement('li'); li.setAttribute('role', 'option'); li.className = 'opt';
        li.innerHTML = '<span></span><small></small>';
        li.firstChild.textContent = c.name + (c.any ? ' (any camera)' : '');
        li.lastChild.textContent = `${c.sensor ? c.sensor + ' · ' : ''}${c.pixel_um} µm`;
        li.onmousedown = (e) => { e.preventDefault(); choose(c); };
        list.append(li);
      }
      const own = document.createElement('li'); own.setAttribute('role', 'option'); own.className = 'opt own';
      own.textContent = input.value.trim() ? `Not listed: “${input.value.trim()}” with its pixel size…` : 'Not listed: enter a name and pixel size…';
      own.onmousedown = (e) => { e.preventDefault(); choose({ custom: true, name: input.value.trim() }); };
      list.append(own);
      list.hidden = false; input.setAttribute('aria-expanded', 'true');
    }
    function mark(k) {
      const opts = [...list.querySelectorAll('li[role=option]')];
      if (!opts.length) return;
      at = (k + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle('hl', i === at));
      opts[at].scrollIntoView({ block: 'nearest' });
    }
    input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('aria-expanded', 'false');
    input.addEventListener('input', render);
    input.addEventListener('focus', () => { if (input.value) render(); });
    input.addEventListener('blur', close);
    input.addEventListener('keydown', (e) => {
      if (list.hidden && e.key === 'ArrowDown') { render(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); mark(at + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); mark(at - 1); }
      else if (e.key === 'Enter' && !list.hidden) {
        e.preventDefault();
        const opts = [...list.querySelectorAll('li[role=option]')];
        const k = at >= 0 ? at : 0;
        if (k < hits.length) choose(hits[k]); else if (opts[k]) choose({ custom: true, name: input.value.trim() });
      } else if (e.key === 'Escape' && !list.hidden) { e.stopPropagation(); close(); }
    });
  }

  // ------------------------------------------------------------ the short form (launcher only)
  // open({onSetup(id), onAnyScale(), cancel()}): what took this photo; saved to the equipment, then onSetup
  function form(opts) {
    const $ = (s) => document.querySelector(s);
    const dlg = $('#eqform');
    let cam = null, factor = 1, bin = 1;
    const num = (s) => { const x = parseFloat(String(s).replace(',', '.')); return isFinite(x) ? x : NaN; };
    function chips(box, current, set) {
      box.querySelectorAll('button[data-v]').forEach((b) => {
        b.setAttribute('aria-pressed', String(b.dataset.v === String(current)));
        b.onclick = () => set(b.dataset.v);
      });
    }
    function update() {
      const f = num($('#eqfocal').value);
      chips($('#eqbarlows'), $('#eqother').hidden ? factor : 'other', (v) => {
        if (v === 'other') { $('#eqother').hidden = false; $('#eqfactor').focus(); factor = num($('#eqfactor').value) || NaN; }
        else { $('#eqother').hidden = true; factor = +v; }
        update();
      });
      chips($('#eqbins'), bin, (v) => { bin = +v; update(); });
      const um = cam ? (cam.custom ? num($('#equm').value) : cam.pixel_um) : NaN;
      const fac = $('#eqother').hidden ? factor : num($('#eqfactor').value);
      const ok = $('#eqname').value.trim() && f >= 50 && f <= 30000 && fac >= 0.2 && fac <= 10 && um >= 0.5 && um <= 30
        && (!cam || !cam.custom || $('#eqcam').value.trim());
      $('#eqgo').disabled = !ok;
      $('#eqscale').textContent = ok
        ? `${Math.round(f * fac)} mm${fac !== 1 ? ` (${f} mm × ${fac})` : ''} with ${um} µm pixels${bin > 1 ? `, ${bin}×${bin} binned` : ''}: `
          + `${arcsec(f, fac, um, bin).toFixed(2)}″ per pixel`
        : 'Fill in the telescope and choose a camera: the scale of your photo shows here.';
    }
    function showCam() {
      $('#eqcamdesc').textContent = cam && !cam.custom ? `${cam.sensor ? cam.sensor + ' · ' : ''}${cam.pixel_um} µm`
        + (cam.width ? ` · ${cam.width} × ${cam.height}` : '') : '';
      $('#eqown').hidden = !(cam && cam.custom);
      update();
    }
    if (!dlg.dataset.wired) {
      dlg.dataset.wired = '1';
      picker($('#eqcam'), $('#eqcamlist'), (c) => {
        cam = c;
        if (!c.custom) $('#eqcam').value = c.name; else { $('#equm').focus(); }
        showCam();
      });
      $('#eqcam').addEventListener('input', () => { if (cam && !cam.custom) { cam = null; showCam(); } });
      for (const id of ['#eqname', '#eqfocal', '#eqfactor', '#equm', '#eqcam']) $(id).addEventListener('input', update);
      $('#eqform form').onsubmit = async (e) => {
        e.preventDefault();
        const fac = $('#eqother').hidden ? factor : num($('#eqfactor').value);
        const camera = cam.custom ? { name: $('#eqcam').value.trim(), pixel_um: num($('#equm').value) }
          : { name: cam.name, sensor: cam.sensor, pixel_um: cam.pixel_um, width: cam.width, height: cam.height };
        const body = { telescope: { name: $('#eqname').value.trim(), focal_mm: num($('#eqfocal').value) },
          barlow: fac !== 1 ? { name: 'Barlow', factor: fac } : null, camera, binning: bin };
        $('#eqgo').disabled = true; $('#eqerr').hidden = true;
        try {
          const r = await fetch('/app/equipment/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          const j = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(j.error || r.statusText);
          dlg.close(); dlg._opts.onSetup(j.setup);
        } catch (err) { $('#eqerr').textContent = 'Could not save this: ' + err.message; $('#eqerr').hidden = false; update(); }
      };
      $('#eqany').onclick = () => { dlg.close(); dlg._opts.onAnyScale(); };
      dlg.addEventListener('cancel', (e) => { e.preventDefault(); dlg.close(); dlg._opts.cancel(); });
    }
    dlg._opts = opts;
    $('#eqerr').hidden = true; $('#eqother').hidden = true;
    $('#eqphoto').textContent = opts.name || '';
    $('#eqtitle').textContent = opts.title || 'A close-up: what took it?';
    showCam();
    dlg.showModal();
    ($('#eqname').value ? $('#eqcam') : $('#eqname')).focus();
  }

  window.LA_EQ = { cameras, search, picker, arcsec, form };
})();
