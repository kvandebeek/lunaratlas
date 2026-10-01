/* Starts the viewer: fetches the page's data (/data.json, so that no other site can include it as a script), then runs
   viewer.js on it. */
(async () => {
  try {
    const r = await fetch('/data.json');
    if (!r.ok) throw new Error(r.statusText);
    window.ATLAS = await r.json();
  } catch (e) {
    document.body.textContent = 'LunarAtlas has no image open (' + e.message + '). Reload this page, or start it again.';
    return;
  }
  if (window.ATLAS.launcher) {             // opened from the launcher: a way back to it, and the sign that this page is still open
    document.getElementById('otherImage').hidden = false;
    setInterval(() => fetch('/app/ping').catch(() => {}), 20000);
  }
  const s = document.createElement('script');
  s.src = '/viewer.js';
  document.head.appendChild(s);
})();
