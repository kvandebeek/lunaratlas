#!/usr/bin/env python3
"""Quality-gate thresholds from the user's labels.

  calibrate.py SURVEY_DIR [--write]

Reads SURVEY_DIR/quality.json and SURVEY_DIR/labels.json (good / borderline / reject). Every measure gets the
lowest limit that refuses NO image labelled good or borderline (plus a 5 % margin); a measure is used only if
that limit still catches at least one rejected image. Prints what each limit catches, which rejects no measure
catches (candidates for a new measure) and, with --write, saves lunaratlas/data/quality_thresholds.json.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from atlas_quality import THRESHOLDS_FILE, verdict  # noqa: E402

# (measure, direction): +1 = too high is bad, -1 = too low is bad; each maps to a limit key of verdict()
# fine_detail is measured but not a limit: it depends on the sampling (oversampled close-ups and unsharpened stacks
# score low without being bad; measured on a 2.5x Powermate stack of 24 May 2026: 0.10)
MEASURES = [('saturated_largest_patch', 1), ('edge_width_px', 1), ('undershoot', 1), ('overshoot', 1),
            ('mare_noise', 1), ('jpeg_blocking', 1), ('posterisation', 1),
            ('chroma', 1), ('fringe_rel', 1)]


def key(m, d):
    return m if d > 0 else 'min_' + m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('survey'); ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    Q = {q['key']: q for q in json.load(open(os.path.join(a.survey, 'quality.json'))) if 'error' not in q}
    labels = json.load(open(os.path.join(a.survey, 'labels.json')))
    rows = [(Q[k], v) for k, v in labels.items() if k in Q and v.get('verdict')]
    good = [q for q, v in rows if v['verdict'] in ('good', 'borderline')]
    bad = [(q, v) for q, v in rows if v['verdict'] == 'reject']
    print(f'{len(rows)} labelled: {len(good)} good or borderline, {len(bad)} reject\n')
    th = dict(version=time.strftime('%Y-%m-%d'), labelled=len(rows))
    caught = set()
    for m, d in MEASURES:
        vals = [q[m] for q in good if isinstance(q.get(m), (int, float))]
        if not vals:
            continue
        lim = max(vals) * 1.05 if d > 0 else min(vals) / 1.05
        hit = [(q, v) for q, v in bad if isinstance(q.get(m), (int, float)) and (q[m] > lim if d > 0 else q[m] < lim)]
        tagged = sum(1 for q, v in hit if v.get('reasons'))
        print(f"{m:26s} limit {'>' if d > 0 else '<'} {lim:.4g}  catches {len(hit):2d} of {len(bad)} rejects"
              + (f"  ({tagged} with a reason: " + ', '.join(sorted({r for _, v in hit for r in v.get('reasons', [])})) + ')'
                 if tagged else ''))
        th[key(m, d)] = round(lim, 5) if hit else None
        caught |= {q['key'] for q, _ in hit}
    missed = [(q, v) for q, v in bad if q['key'] not in caught]
    print(f'\nrefused with these limits: {len(caught)} of {len(bad)} rejects, 0 of {len(good)} good/borderline')
    if missed:
        print('rejects no measure catches (reasons given → the measure to improve):')
        for q, v in missed:
            print(f"  {q['name'] if 'name' in q else os.path.basename(q['file'])[:40]:40s} {', '.join(v.get('reasons', [])) or '-'}"
                  f"  {v.get('note', '')}")
    # sanity: the verdict function with these limits agrees
    disagree = [q for q in good if not verdict(q, th)[0]]
    if disagree:
        print(f'WARNING: {len(disagree)} good/borderline images would still be refused')
    if a.write:
        with open(THRESHOLDS_FILE, 'w') as fh:
            json.dump(th, fh, indent=1)
        print(f'\nwrote {THRESHOLDS_FILE}')


if __name__ == '__main__':
    main()
