"""Summarise scripts/testimages_results/results.jsonl into a report (and print the highlights)."""
import collections
import json
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, 'testimages_results')
JSONL = os.path.join(RESULTS_DIR, 'results.jsonl')
REPORT = os.path.join(RESULTS_DIR, 'report.md')
GALLERY = os.path.join(RESULTS_DIR, 'gallery.html')


def load():
    rows = []
    with open(JSONL) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def great_circle_deg(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    d = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1, math.sqrt(d))))


def main():
    rows = load()
    truth = {r['name']: r for r in rows if r['folder'] == 'Originals' and r['status'] == 'solved'}
    for r in rows:
        r['deg_from_truth'] = None
        if r['folder'] != 'Originals' and r['status'] == 'solved' and r['name'] in truth:
            t = truth[r['name']]
            r['deg_from_truth'] = great_circle_deg(r.get('lat'), r.get('lon'), t.get('lat'), t.get('lon'))
    missing_truth = {r['name'] for r in rows if r['folder'] != 'Originals'} - set(truth)

    by_folder = collections.defaultdict(list)
    for r in rows:
        by_folder[r['folder']].append(r)

    lines = ['# LunarAtlas close-up locate — TestImages batch report', '']
    lines.append(f'{len(rows)} files tested across {len(by_folder)} folders.')
    lines.append('')
    lines.append('| folder | files | solved | refused | crash | timeout | wrong location (>1°) | median rms (px) |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|---:|')
    crashes, wrongs, timeouts = [], [], []
    for folder, rs in [('Originals', by_folder.get('Originals', []))] + \
            sorted((f, rs) for f, rs in by_folder.items() if f != 'Originals'):
        c = collections.Counter(r['status'] for r in rs)
        wrong = [r for r in rs if r.get('deg_from_truth') is not None and r['deg_from_truth'] > 1.0]
        rmss = [r['rms_px'] for r in rs if r['status'] == 'solved']
        med_rms = f'{statistics.median(rmss):.2f}' if rmss else '—'
        lines.append(f"| {folder} | {len(rs)} | {c['solved']} | {c['refused']} | {c['crash']} | {c.get('timeout', 0)} "
                      f"| {len(wrong)} | {med_rms} |")
        crashes += [(folder, r) for r in rs if r['status'] == 'crash']
        wrongs += [(folder, r) for r in rs if r in wrong]
        timeouts += [(folder, r) for r in rs if r['status'] == 'timeout']

    lines.append('')
    if wrongs:
        lines.append('## Wrong location (solved, but >1° from the Originals ground truth) — most serious')
        lines.append('')
        for folder, r in wrongs:
            lines.append(f"- **{folder}/{r['name']}**: {r['deg_from_truth']:.2f}° off, "
                          f"{r['matches']} matches, {r['rms_px']} px rms")
        lines.append('')
    else:
        lines.append('## Wrong location: none found.')
        lines.append('')

    if crashes:
        lines.append('## Crashes (unhandled exceptions — always a bug)')
        lines.append('')
        for folder, r in crashes:
            lines.append(f"### {folder}/{r['name']}")
            lines.append('```')
            lines.append(r.get('traceback', r.get('full_tail', ''))[-2000:])
            lines.append('```')
        lines.append('')
    else:
        lines.append('## Crashes: none.')
        lines.append('')

    if timeouts:
        lines.append(f'## Timeouts ({len(timeouts)})')
        for folder, r in timeouts:
            lines.append(f"- {folder}/{r['name']}")
        lines.append('')

    lines.append('## Refused, by folder (expected for the deliberately hard edits)')
    lines.append('')
    for folder, rs in sorted(by_folder.items()):
        refused = [r for r in rs if r['status'] == 'refused']
        if refused:
            lines.append(f"- **{folder}**: {len(refused)}/{len(rs)} refused, e.g. "
                          f"\"{refused[0].get('message', '')}\"")
    lines.append('')

    # Originals should basically always solve; flag any that didn't
    orig_bad = [r for r in by_folder.get('Originals', []) if r['status'] != 'solved']
    if orig_bad:
        lines.append('## Originals that did NOT solve (should basically never happen)')
        for r in orig_bad:
            lines.append(f"- {r['name']}: {r['status']} — {r.get('message', r.get('traceback', ''))[:200]}")
        lines.append('')

    if missing_truth:
        lines.append(f'## No ground truth yet for {len(missing_truth)} name(s)')
        lines.append('(their Originals counterpart has not been tested, or did not solve — run this report again '
                      'once the full batch is done for a complete wrong-location check)')
        lines.append('')

    with open(REPORT, 'w') as fh:
        fh.write('\n'.join(lines))
    write_gallery(by_folder)
    print('\n'.join(lines[:40]))
    print(f'\n... full report at {REPORT}')
    print(f'... visual gallery at {GALLERY}')


def write_gallery(by_folder):
    css = """
    body{font-family:-apple-system,sans-serif;background:#111;color:#eee;margin:0;padding:16px}
    h2{border-bottom:1px solid #444;padding-bottom:6px;margin-top:36px}
    .grid{display:flex;flex-wrap:wrap;gap:10px}
    .card{width:260px;background:#1b1b1b;border-radius:8px;overflow:hidden;border:2px solid #333}
    .card.solved{border-color:#2a6}
    .card.refused{border-color:#888}
    .card.crash,.card.timeout{border-color:#d33}
    .card.wrong{border-color:#f0a500;box-shadow:0 0 8px #f0a50088}
    .card img{width:100%;display:block;background:#000}
    .card .meta{padding:6px 8px;font-size:12px;line-height:1.4}
    .name{font-weight:600;font-size:12.5px;word-break:break-all}
    .tag{display:inline-block;border-radius:4px;padding:1px 6px;font-size:11px;margin-bottom:4px}
    .tag.solved{background:#164d2c}
    .tag.refused{background:#444}
    .tag.crash,.tag.timeout{background:#5c1414}
    .tag.wrong{background:#6b4a00}
    """
    parts = [f'<!doctype html><html><head><meta charset="utf-8"><title>LunarAtlas TestImages gallery</title>'
             f'<style>{css}</style></head><body><h1>LunarAtlas close-up locate — TestImages gallery</h1>']
    for folder in ['Originals'] + sorted(f for f in by_folder if f != 'Originals'):
        rs = by_folder.get(folder, [])
        parts.append(f'<h2>{folder} ({len(rs)})</h2><div class="grid">')
        for r in rs:
            wrong = r.get('deg_from_truth') is not None and r['deg_from_truth'] > 1.0
            cls = 'wrong' if wrong else r['status']
            thumb = r.get('thumb')
            rel = os.path.relpath(thumb, RESULTS_DIR) if thumb and os.path.exists(thumb) else None
            img = f'<img src="{rel}" loading="lazy">' if rel else '<div style="height:150px"></div>'
            bits = []
            if r['status'] == 'solved':
                bits.append(f"{r['matches']} matches, {r['rms_px']} px rms")
                if r.get('deg_from_truth') is not None:
                    bits.append(f"{r['deg_from_truth']:.2f}° from truth")
            else:
                bits.append(r.get('message', r.get('traceback', ''))[:120])
            parts.append(f'<div class="card {cls}"><a href="{rel or "#"}">{img}</a><div class="meta">'
                          f'<span class="tag {cls}">{"WRONG" if wrong else r["status"].upper()}</span>'
                          f'<div class="name">{r["name"]}</div><div>{"<br>".join(bits)}</div></div></div>')
        parts.append('</div>')
    parts.append('</body></html>')
    with open(GALLERY, 'w') as fh:
        fh.write('\n'.join(parts))


if __name__ == '__main__':
    main()
