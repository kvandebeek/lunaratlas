#!/usr/bin/env python3
"""Quality measures + gallery crops for every image of a test folder (read-only).

  survey_quality.py OUT_DIR SRC [SRC ...]      SRC: a folder or an image file

Writes OUT_DIR/quality.json and OUT_DIR/gallery/<id>_{thumb,detail,limb}.jpg. Uses OUT_DIR/located.json
(from survey_locate.py) for km/px when an image was located.
"""
import hashlib
import json
import math
import os
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from atlas_geo import fit_limb, resize, unresize  # noqa: E402
from atlas_quality import luminance, measure, moon_mask  # noqa: E402

EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff')
CROP = 480


def to8(img):
    if img.dtype == np.uint8:
        return img
    return cv2.convertScaleAbs(img, alpha=255.0 / max(float(img.max()), 1.0))


def crops(raw, g, limb, out, key):
    disp = raw[..., :3] if raw.ndim == 3 else raw
    disp = to8(disp)
    h, w = g.shape
    s = 640 / max(h, w)
    cv2.imwrite(f'{out}/{key}_thumb.jpg', cv2.resize(disp, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    # 1:1 crop where the medium-scale detail is strongest (inside the lit Moon)
    mask, _, _ = moon_mask(g)
    det = np.abs(g - cv2.GaussianBlur(g, (0, 0), 3))
    det = cv2.blur(det * mask, (CROP // 2, CROP // 2))
    if limb is not None:
        cx, cy, R = limb
        yy, xx = np.ogrid[0:h, 0:w]
        det = det * ((xx - cx) ** 2 + (yy - cy) ** 2 < (0.85 * R) ** 2)
    c = min(CROP, h, w)
    y, x = np.unravel_index(np.argmax(det), det.shape)
    x0, y0 = int(np.clip(x - c // 2, 0, w - c)), int(np.clip(y - c // 2, 0, h - c))
    cv2.imwrite(f'{out}/{key}_detail.jpg', disp[y0:y0 + c, x0:x0 + c], [cv2.IMWRITE_JPEG_QUALITY, 95])
    got_limb = False
    if limb is not None:
        cx, cy, R = limb
        # the brightest limb direction
        ang = np.linspace(0, 2 * np.pi, 360, endpoint=False)
        px = np.clip((cx + 0.97 * R * np.cos(ang)).astype(int), 0, w - 1)
        py = np.clip((cy + 0.97 * R * np.sin(ang)).astype(int), 0, h - 1)
        ex = (cx + R * np.cos(ang) >= 0) & (cx + R * np.cos(ang) < w) & (cy + R * np.sin(ang) >= 0) & (cy + R * np.sin(ang) < h)
        v = cv2.GaussianBlur(g, (0, 0), 3)[py, px] * ex
        if v.max() > 0:
            a = ang[int(np.argmax(v))]
            lx, ly = cx + R * math.cos(a), cy + R * math.sin(a)
            cl = min(240, h, w)
            x0, y0 = int(np.clip(lx - cl // 2, 0, w - cl)), int(np.clip(ly - cl // 2, 0, h - cl))
            cv2.imwrite(f'{out}/{key}_limb.jpg', disp[y0:y0 + cl, x0:x0 + cl], [cv2.IMWRITE_JPEG_QUALITY, 95])
            got_limb = True
    return got_limb


def one(path, out, located):
    key = hashlib.md5(os.path.abspath(path).encode()).hexdigest()[:10]
    try:
        raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if raw is None:
            return dict(file=path, key=key, error='unreadable')
        if raw.ndim == 3 and raw.shape[2] == 4:
            raw = raw[..., :3]
        g = luminance(raw)
        H, W = g.shape
        limb, limb_share, limb_err = None, None, None
        try:
            g0, (sx, sy) = resize(g, 1024.0 / max(W, H))
            cx, cy, R, limb_share = fit_limb(g0)
            (cx0, cy0), R0 = unresize((cx, cy), sx, sy), R / math.sqrt(sx * sy)
            limb = (float(cx0), float(cy0), float(R0))
        except SystemExit as e:
            limb_err = str(e)
        loc = located.get(os.path.basename(path))
        km = loc['km_per_px'] if loc and loc.get('ok') else None
        # a limb that holds few contour points is a close-up's frame edge or terminator, not the Moon's edge
        use_limb = limb if (limb is not None and limb_share is not None and limb_share >= 0.25) else None
        if loc and loc.get('ok'):
            use_limb = limb
        q = measure(raw, use_limb, km)
        q.update(file=path, key=key, located=bool(loc and loc.get('ok')),
                 locate_error=None if not loc or loc.get('ok') else loc.get('error'),
                 limb_share=None if limb_share is None else round(float(limb_share), 3), limb_error=limb_err,
                 limb_fit=None if limb is None else [round(v, 1) for v in limb], limb_used=use_limb is not None,
                 matches=loc['quality']['matches'] if loc and loc.get('ok') else None,
                 rms_px=loc['quality']['rms_px'] if loc and loc.get('ok') else None)
        q['has_limb_crop'] = crops(raw, g, use_limb, out, key)
        return q
    except Exception as e:                      # noqa: BLE001
        return dict(file=path, key=key, error=f'{e.__class__.__name__}: {e}', trace=traceback.format_exc())


def main():
    out, srcs = sys.argv[1], sys.argv[2:]
    gal = os.path.join(out, 'gallery')
    os.makedirs(gal, exist_ok=True)
    located = {}
    lp = os.path.join(out, 'located.json')
    if os.path.exists(lp):
        located = {r['file']: r for r in json.load(open(lp))}
    files = []
    for s in srcs:
        if os.path.isdir(s):
            files += sorted(os.path.join(s, f) for f in os.listdir(s) if f.lower().endswith(EXT))
        else:
            files.append(s)
    res = []
    with ProcessPoolExecutor(6) as ex:
        futs = [ex.submit(one, f, gal, located) for f in files]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            res.append(r)
            print(i, os.path.basename(r['file'])[:40], r.get('error') or '', flush=True)
    res.sort(key=lambda r: r['file'])
    with open(os.path.join(out, 'quality.json'), 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()
