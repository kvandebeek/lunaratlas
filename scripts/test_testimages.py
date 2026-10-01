"""Batch-test LunarAtlas's close-up locate over /Users/kristofvandebeek/Documents/TestImages.

Every file in every folder (Originals and every edited variant), in random order across folders, so a quick,
broad first pass turns up whatever needs fixing sooner rather than finishing one folder at a time. Live progress
to stdout, a JSON line per file to RESULTS_JSONL (resumable: rerunning skips what's already there). The
comparison against each file's Originals counterpart (by filename) is computed by report_testimages.py from the
whole results file, not here, since Originals is not guaranteed to be done before its variants in random order.

Run: python3 scripts/test_testimages.py [--redo] [--only FOLDER] [--seed N]
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'lunaratlas'))
import atlas_geo as ag  # noqa: E402

ROOT = '/Users/kristofvandebeek/Documents/TestImages'
LUNARATLAS = os.path.join(REPO, 'lunaratlas', 'lunaratlas.py')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'testimages_results')
RESULTS_JSONL = os.path.join(OUT_DIR, 'results.jsonl')
REPORT_MD = os.path.join(OUT_DIR, 'report.md')
THUMB_DIR = os.path.join(OUT_DIR, 'thumbs')
TIMEOUT_S = 240
EXTS = ('.tif', '.tiff', '.png', '.jpg', '.jpeg')

REFUSED_PATTERNS = (
    'close-up not found', 'no limb in view', 'image too poor', 'not annotated',
    'a close-up needs the capture time', 'too few terrain matches', 'no optics setup gives',
)


def list_images(folder):
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and name.lower().endswith(EXTS):
            out.append(name)
    return out


def folders():
    subs = sorted(d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)) and d != 'Originals')
    return ['Originals'] + subs


def read_sidecar(path):
    """(matches, rms_px, lat, lon, closeup) from the sidecar export just wrote (or reused), or None."""
    side = path + '.atlas.json'                      # canonical per-extension sidecar (bugs-overview BUG-05)
    try:
        with open(side) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    q = d.get('quality')
    if not isinstance(q, dict) or 'matches' not in q or 'rms_px' not in q:
        return None
    latlon = q.get('centre_latlon')
    if latlon:
        lat, lon = latlon
    else:
        try:
            geo = ag.Geometry.from_dict(d['geometry'])
            lat, lon, _ = geo.to_latlon(d['width'] / 2, d['height'] / 2)
            lat, lon = float(lat), float(lon)
        except (KeyError, ValueError, TypeError):
            lat = lon = None
    return dict(matches=q['matches'], rms_px=q['rms_px'], lat=lat, lon=lon, closeup=bool(q.get('closeup')))


def run_export(path, folder, name):
    """(status, info dict) for one file: locate + draw labels, saving a small annotated jpg for visual review.
    status: solved / refused / crash / timeout. Reads the result from the sidecar export writes/reuses, not the
    log text, since a file already positioned by an earlier run skips straight to rendering."""
    t0 = time.perf_counter()
    os.makedirs(os.path.join(THUMB_DIR, folder), exist_ok=True)
    thumb = os.path.join(THUMB_DIR, folder, os.path.splitext(name)[0] + '_atlas.jpg')
    args = [sys.executable, LUNARATLAS, 'export', path, '-o', thumb, '--format', 'jpg', '--max-size', '1600',
            '--overwrite']
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return 'timeout', dict(seconds=round(time.perf_counter() - t0, 1))
    secs = round(time.perf_counter() - t0, 1)
    out = p.stdout + p.stderr
    has_tb = 'Traceback (most recent call last)' in p.stderr
    wrote = os.path.exists(thumb)
    if p.returncode == 0 and wrote:
        info = read_sidecar(path)
        if info is not None:
            info['seconds'] = secs
            info['thumb'] = thumb
            return 'solved', info
    if has_tb:
        tb = p.stderr[p.stderr.index('Traceback (most recent call last)'):]
        return 'crash', dict(seconds=secs, traceback=tb[-4000:], exit_code=p.returncode)
    last = next((l for l in reversed(out.splitlines()) if l.strip()), '')
    clean = p.returncode != 0 and any(pat in out for pat in REFUSED_PATTERNS)
    return ('refused' if clean else 'crash'), dict(seconds=secs, message=last[-300:], exit_code=p.returncode,
                                                    full_tail='\n'.join(out.splitlines()[-15:]))


def great_circle_deg(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    d = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1, math.sqrt(d))))


def already_done(jsonl_path):
    done = {}
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done[(r['folder'], r['name'])] = r
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--redo', action='store_true', help='ignore results.jsonl and redo everything')
    ap.add_argument('--only', help='only this folder')
    ap.add_argument('--seed', type=int, default=None, help='shuffle seed (default: a fresh random one, printed)')
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    done = {} if a.redo else already_done(RESULTS_JSONL)
    # best-effort live "off truth" hint only, for whichever Originals this run has already touched; the
    # authoritative comparison (order-independent) is report_testimages.py, from the finished results file
    truth = {r['name']: r for (f, n), r in done.items() if f == 'Originals' and r['status'] == 'solved'}

    fs = [a.only] if a.only else folders()
    tasks = [(folder, name) for folder in fs for name in list_images(os.path.join(ROOT, folder))
             if a.redo or (folder, name) not in done]
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2 ** 31)
    random.Random(seed).shuffle(tasks)
    print(f'{len(tasks)} files to do (shuffle seed {seed}, so a rerun with --seed {seed} repeats this order)')

    total = len(tasks) + len(done if not a.redo else [])
    done_count = total - len(tasks)
    t_all = time.perf_counter()
    jsonl = open(RESULTS_JSONL, 'a' if not a.redo else 'w')
    try:
        for folder, name in tasks:
            done_count += 1
            print(f'[{done_count}/{total}] {folder}/{name} ... IN PROGRESS', flush=True)
            status, info = run_export(os.path.join(ROOT, folder, name), folder, name)
            rec = dict(folder=folder, name=name, status=status, **info)
            tag = {'solved': 'OK', 'refused': 'REFUSED (expected for hard edits)', 'crash': 'CRASH ❗',
                   'timeout': 'TIMEOUT ❗'}[status]
            extra = ''
            if status == 'solved':
                extra = f" matches={rec['matches']} rms={rec['rms_px']}px"
                if folder != 'Originals' and name in truth:
                    t = truth[name]
                    off = great_circle_deg(rec.get('lat'), rec.get('lon'), t.get('lat'), t.get('lon'))
                    if off is not None:
                        extra += f" off-truth={off:.2f}°"
                        if off > 1.0:
                            tag = 'WRONG LOCATION ❗❗ NEEDS VERIFY'
            print(f'  -> {tag}{extra}  ({rec.get("seconds", "?")}s)', flush=True)
            jsonl.write(json.dumps(rec) + '\n')
            jsonl.flush()
            if folder == 'Originals' and status == 'solved':
                truth[name] = rec
    finally:
        jsonl.close()
    print(f'\ndone: {done_count}/{total} in {time.perf_counter() - t_all:.0f}s. Run report_testimages.py for the summary.')


if __name__ == '__main__':
    main()
