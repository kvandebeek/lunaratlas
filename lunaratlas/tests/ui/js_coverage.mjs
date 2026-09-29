// What the UI journeys ran of the pages' JavaScript: V8 block coverage merged over every journey.
//   LUNARATLAS_JS_COVERAGE=DIR python3 -m unittest test_ui     then     node js_coverage.mjs DIR
// Per script: the share of its code that ran, the functions never called, and the lines no journey reached.
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const VIEWER = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'viewer');
const dir = process.argv[2];
const files = { '/viewer.js': 'viewer.js', '/friendly.js': 'friendly.js', '/exif.js': 'exif.js' };
const inline = [];                                     // the pages' own <script> blocks: matched by length
for (const page of ['app.html', 'index.html']) {
  const html = readFileSync(join(VIEWER, page), 'utf8');
  for (const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) inline.push({ name: `${page} <script>`, src: m[1] });
}

const merged = new Map();                              // name -> { src, hit: Uint8Array, fns: Map(key -> {name, start, calls}) }
for (const f of readdirSync(dir).filter((f) => f.endsWith('.json'))) {
  for (const script of JSON.parse(readFileSync(join(dir, f), 'utf8'))) {
    const path = new URL(script.url).pathname;
    const len = script.length;
    let name, src;
    if (files[path]) { name = files[path]; src = readFileSync(join(VIEWER, name), 'utf8'); }
    else { const b = inline.find((i) => i.src.length === len); if (!b) continue; ({ name, src } = b); }
    if (!merged.has(name)) merged.set(name, { src, hit: new Uint8Array(src.length), fns: new Map() });
    const m = merged.get(name);
    // innermost range wins: apply outer ranges first
    const ranges = script.functions.flatMap((fn) => fn.ranges).sort((a, b) => a.startOffset - b.startOffset || b.endOffset - a.endOffset);
    if (src.length !== len) continue;                  // not this file's source (a stale copy, another page)
    const count = new Int32Array(src.length);
    for (const r of ranges) count.fill(r.count, r.startOffset, Math.min(r.endOffset, src.length));
    for (let i = 0; i < src.length; i++) if (count[i] > 0) m.hit[i] = 1;
    for (const fn of script.functions) {
      const r = fn.ranges[0], key = r.startOffset;
      const o = m.fns.get(key) || { name: fn.functionName || '(anonymous)', start: r.startOffset, calls: 0 };
      o.calls += r.count; m.fns.set(key, o);
    }
  }
}

const lineOf = (src, off) => src.slice(0, off).split('\n').length;
let total = 0, covered = 0;
for (const [name, { src, hit, fns }] of [...merged].sort()) {
  let n = 0, c = 0;
  for (let i = 0; i < src.length; i++) if (!/\s/.test(src[i])) { n++; if (hit[i]) c++; }
  total += n; covered += c;
  console.log(`\n${name}: ${(100 * c / n).toFixed(1)} % of the code ran`);
  const never = [...fns.values()].filter((f) => f.calls === 0 && f.name !== '(anonymous)').map((f) => `${f.name} (line ${lineOf(src, f.start)})`);
  if (never.length) console.log('  never called: ' + never.join(', '));
  const lines = src.split('\n'), dead = [];
  let off = 0;
  lines.forEach((l, i) => {
    let any = false, run = false;
    for (let k = 0; k < l.length; k++) if (!/\s/.test(l[k])) { any = true; if (hit[off + k]) run = true; }
    if (any && !run && !/^\s*(\/\/|\/\*|\*|[}\])]+;?$)/.test(l)) dead.push(i + 1);
    off += l.length + 1;
  });
  const spans = [];
  for (const l of dead) { const s = spans.at(-1); if (s && l === s[1] + 1) s[1] = l; else spans.push([l, l]); }
  if (spans.length) console.log(`  lines never reached (${dead.length}): ` + spans.map(([a, b]) => a === b ? a : `${a}-${b}`).join(', '));
}
console.log(`\nall page scripts: ${(100 * covered / total).toFixed(1)} %`);
