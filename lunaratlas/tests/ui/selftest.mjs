// Runs the page's own self-test (/selftest) in real time through the DevTools protocol and prints its result as
//   <pre id="selftest">…</pre>
// the way `chrome --dump-dom` does. --dump-dom needs --virtual-time-budget, which pauses and jumps the page's clock
// around work it cannot see; on CI runners that stalled the page partway through a group (the page's own log
// stopped after a few checks and nothing was written), while the same Chrome drives every journey in real time.
// usage: node selftest.mjs CHROME URL DIR PATIENCE_MS
import { Browser } from './cdp.mjs';

const [chrome, url, dir, patience] = process.argv.slice(2);
const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
let b;
try {
  b = await Browser.launch(chrome, dir, { width: 1400, height: 900 });
  await b.send('Page.navigate', { url });           // not goto(): the result is what is waited for, not the load event
  await b.until(`!!document.getElementById('selftest')`, Number(patience) || 60000, 'the self-test result');
  process.stdout.write('<pre id="selftest">' + esc(await b.js(`document.getElementById('selftest').textContent`)) + '</pre>');
} catch (e) {
  console.error(String(e.message || e).slice(0, 400));
  process.exitCode = 1;
} finally {
  if (b) await b.close();
}
