#!/usr/bin/env python3
"""Locate every image of a read-only test folder; geometry + quality go to OUT/located.json.

  survey_locate.py SRC_DIR OUT_DIR [--workers N]
"""
import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from atlas_geo import locate  # noqa: E402

EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff')


def one(path):
    t0 = time.perf_counter()
    lines = []
    try:
        geo, q = locate(path, log=lambda *a: lines.append(' '.join(map(str, a))))
        return dict(file=os.path.basename(path), ok=True, geometry=geo.as_dict(), quality=q,
                    km_per_px=geo.km_per_px, radius_px=geo.radius_px, mirrored=bool(geo.mirrored),
                    north=geo.north_angle, log=lines, seconds=time.perf_counter() - t0)
    except SystemExit as e:
        return dict(file=os.path.basename(path), ok=False, error=str(e), log=lines, seconds=time.perf_counter() - t0)
    except Exception as e:                      # noqa: BLE001 - a survey records every failure
        return dict(file=os.path.basename(path), ok=False, error=f'{e.__class__.__name__}: {e}',
                    trace=traceback.format_exc(), log=lines, seconds=time.perf_counter() - t0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('src'); p.add_argument('out'); p.add_argument('--workers', type=int, default=5)
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    files = sorted(os.path.join(a.src, f) for f in os.listdir(a.src) if f.lower().endswith(EXT))
    res = []
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, f): f for f in files}
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            res.append(r)
            print(f"{i:3d}/{len(files)} {r['file'][:40]:40s} "
                  + (f"ok {r['quality']['matches']:4d} m {r['quality']['rms_px']:5.2f} px {r['km_per_px']:.3f} km/px"
                     if r['ok'] else f"FAIL {r['error'][:70]}") + f"  {r['seconds']:.1f} s", flush=True)
    res.sort(key=lambda r: r['file'])
    with open(os.path.join(a.out, 'located.json'), 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()
