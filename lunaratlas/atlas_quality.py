"""Image quality measures for the quality gate: is this image good enough to annotate?

All measures work on the pixels alone (plus the limb when one is visible), so they also explain why an
image cannot be located: an overexposed or very blurry frame fails the terrain matching.

  saturation      share of the Moon at full scale (any colour channel)
  limb            median radial profile across the sunlit limb: 10-90 % edge width (px, km), bright
                  overshoot inside and dark undershoot ring outside (over-sharpening), sky noise
  octaves         Laplacian-pyramid energy per octave on the sunlit interior, relative to the octave
                  below: blur empties the finest octaves, noise and over-sharpening overfill them
  mare noise      fine-scale noise in the flattest tiles of the sunlit disk, relative to their brightness
  jpeg blocking   gradient at 8 px block edges / gradient elsewhere (1 = none)
  posterisation   share of empty grey levels inside the Moon's tonal range (stretched 8-bit data)
"""
import json
import math
import os

import cv2
import numpy as np

R_MOON = 1737.4
from atlas_paths import DATA  # noqa: E402
THRESHOLDS_FILE = os.path.join(DATA, 'quality_thresholds.json')
# provisional, lenient limits (only extreme images are refused) until data/quality_thresholds.json is written
# from the user's labels by experiments/quality/calibrate.py
PROVISIONAL = dict(version='provisional', saturated_largest_patch=0.02, edge_width_px=16.0, undershoot=0.2,
                   overshoot=0.9, mare_noise=0.1, jpeg_blocking=1.6, posterisation=0.5, chroma=None, fringe_rel=None)


def thresholds():
    try:
        with open(THRESHOLDS_FILE) as fh:
            t = json.load(fh)
        return dict(PROVISIONAL, **t) if isinstance(t, dict) else dict(PROVISIONAL)
    except (OSError, ValueError):
        return dict(PROVISIONAL)


def verdict(q, t=None):
    """(ok, reasons, one-line summary). A measure that could not be taken never rejects."""
    t = t or thresholds()
    reasons = []

    def over(key):
        v, lim = q.get(key), t.get(key)
        return v is not None and lim is not None and isinstance(v, (int, float)) and math.isfinite(v) and v > lim
    if over('saturated_largest_patch'):
        reasons.append(f"overexposed: {q['saturated_largest_patch'] * 100:.1f} % of the Moon is one clipped area "
                       f"(limit {t['saturated_largest_patch'] * 100:.1f} %)")
    if over('edge_width_px'):
        km = f", {q['edge_width_km']:.1f} km" if q.get('edge_width_km') else ''
        reasons.append(f"too blurry: the limb is {q['edge_width_px']:.1f} px wide{km} (limit {t['edge_width_px']:.1f} px)")
    if over('undershoot') or over('overshoot'):
        reasons.append(f"over-sharpened: halo at the limb (dark ring {q.get('undershoot') or 0:.2f}, bright ring "
                       f"{q.get('overshoot') or 0:.2f} of the limb contrast; limits {t['undershoot']:.2f} / {t['overshoot']:.2f})")
    if over('mare_noise'):
        reasons.append(f"too noisy: {q['mare_noise'] * 100:.1f} % grain in flat maria (limit {t['mare_noise'] * 100:.1f} %)")
    if over('jpeg_blocking'):
        reasons.append(f"heavy JPEG compression: 8 px block edges {q['jpeg_blocking']:.2f}× the normal gradient "
                       f"(limit {t['jpeg_blocking']:.2f}×)")
    if over('chroma'):
        reasons.append(f"colour boosted far beyond the Moon's own: chroma {q['chroma']:.0f} (limit {t['chroma']:.0f})")
    if over('fringe_rel'):
        reasons.append(f"colour fringes: red and blue limb {q['fringe_px']:.1f} px apart, {q['fringe_rel']:.1f}× the limb's "
                       f"width (limit {t['fringe_rel']:.1f}×)")
    if over('posterisation'):
        reasons.append(f"posterised: {q['posterisation'] * 100:.0f} % of the grey levels in the Moon's range are empty")
    lim = t.get('min_fine_detail')
    if lim is not None and q.get('fine_detail') is not None and q['fine_detail'] < lim:
        reasons.append(f"too little fine detail: finest octaves hold {q['fine_detail']:.2f} of the medium-scale energy "
                       f"(limit {lim:.2f}; blurred or upscaled)")
    parts = []
    if q.get('edge_width_px') is not None and math.isfinite(q['edge_width_px']):
        parts.append(f"limb {q['edge_width_px']:.1f} px" + (f" ({q['edge_width_km']:.2f} km)" if q.get('edge_width_km') else ''))
    if q.get('mare_noise') is not None:
        parts.append(f"grain {q['mare_noise'] * 100:.1f} %")
    parts.append(f"clipped {q.get('saturated_share', 0) * 100:.2f} %")
    if q.get('dtype') == 'uint8':
        parts.append(f"JPEG blocks {q.get('jpeg_blocking', 1):.2f}×")
    tag = '' if t.get('version') != 'provisional' else ' (provisional limits)'
    line = ('quality OK' if not reasons else 'quality refused: ' + '; '.join(reasons)) + tag + ' · ' + ' · '.join(parts)
    return not reasons, reasons, line


def luminance(raw):
    g = raw if raw.ndim == 2 else cv2.cvtColor(raw[..., :3], cv2.COLOR_BGR2GRAY)
    return g.astype(np.float32)


def full_scale(raw):
    if raw.dtype == np.uint8:
        return 255.0
    if raw.dtype == np.uint16:
        return 65535.0
    return float(np.nanmax(raw)) or 1.0


def moon_mask(g):
    """Sunlit Moon: blurred brightness well above the sky."""
    sm = cv2.GaussianBlur(g, (0, 0), 2)
    lo, top = np.percentile(sm, [2, 99.5])
    bright = sm > lo + 0.5 * (top - lo)
    hi = np.percentile(sm[bright], 20) if bright.any() else top
    return sm > lo + 0.25 * (hi - lo), float(lo), float(hi)


# ---------------------------------------------------------------- saturation
def saturation(raw, mask):
    fs = full_scale(raw)
    chans = raw[..., :3] if raw.ndim == 3 else raw[..., None]
    sat = (chans >= 0.998 * fs).any(-1) & mask
    n = max(int(mask.sum()), 1)
    frac = float(sat.sum()) / n
    blob = 0.0
    if sat.any():
        k, _, st, _ = cv2.connectedComponentsWithStats(sat.astype(np.uint8), connectivity=8)
        blob = float(st[1:, cv2.CC_STAT_AREA].max()) / n if k > 1 else 0.0
    return dict(saturated_share=round(frac, 5), saturated_largest_patch=round(blob, 5))


# ---------------------------------------------------------------- limb
def limb_profile(g, cx, cy, R, half=32, step=0.25, n_ang=1440):
    """Median profile across the sunlit limb, each profile aligned on its own half-level crossing
    (the circle is fitted on a reduced copy, so it is only good to a few native pixels)."""
    t = np.arange(-half, half + step / 2, step)
    ang = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    xs = (cx + np.outer(np.cos(ang), R + t)).astype(np.float32)
    ys = (cy + np.outer(np.sin(ang), R + t)).astype(np.float32)
    h, w = g.shape
    inside = (xs >= 1) & (xs < w - 2) & (ys >= 1) & (ys < h - 2)
    prof = cv2.remap(g, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    full = inside.all(1)
    inner = np.median(prof[:, t < -half / 2], 1)
    outer = np.median(prof[:, t > half / 2], 1)
    contrast = inner - outer
    if not full.any():
        return None
    top = np.percentile(contrast[full], 90)
    use = full & (contrast > 0.5 * top) & (contrast > 0)
    if use.sum() < 20:
        return None
    aligned = []
    for p, a, b in zip(prof[use], inner[use], outer[use]):
        q = (p - b) / (a - b)
        # outermost crossing of 0.5, walking inwards from the sky
        idx = np.nonzero((q[:-1] >= 0.5) & (q[1:] < 0.5))[0]
        if not len(idx):
            continue
        i = idx[np.argmin(np.abs(t[idx]))]
        f = (q[i] - 0.5) / (q[i] - q[i + 1] + 1e-9)
        x0 = t[i] + f * step
        aligned.append(np.interp(t, t - x0, q, left=np.nan, right=np.nan))
    if len(aligned) < 20:
        return None
    A = np.array(aligned)
    med = np.nanmedian(A, 0)
    good = np.isfinite(med)
    tt, mm = t[good], med[good]

    def cross(level):
        j = np.nonzero((mm[:-1] >= level) & (mm[1:] < level))[0]
        if not len(j):
            return np.nan
        j = j[np.argmin(np.abs(tt[j]))]
        return tt[j] + (mm[j] - level) / (mm[j] - mm[j + 1] + 1e-9) * step

    x90, x10 = cross(0.9), cross(0.1)
    width = float(x10 - x90) if np.isfinite(x10) and np.isfinite(x90) else float('nan')
    plateau = np.median(mm[(tt > -half * 0.6) & (tt < -half * 0.3)]) if ((tt > -half * 0.6) & (tt < -half * 0.3)).any() else 1.0
    near_in = mm[(tt > -8) & (tt < 0)]
    near_out = mm[(tt > 0) & (tt < 10)]
    far_out = mm[tt > half * 0.5]
    sky = np.median(far_out) if len(far_out) else 0.0
    over = float(near_in.max() - plateau) if len(near_in) else 0.0
    under = float(sky - near_out.min()) if len(near_out) else 0.0
    # sky noise along the profiles, in units of limb contrast
    sky_samples = (prof[use][:, t > half * 0.5] - outer[use, None]) / np.maximum(contrast[use, None], 1e-6)
    sky_noise = float(1.4826 * np.median(np.abs(sky_samples)))
    return dict(limb_angles=int(len(A)), edge_width_px=round(width, 2), overshoot=round(over, 3),
                undershoot=round(under, 3), limb_sky_noise=round(sky_noise, 4),
                profile=[round(float(v), 3) for v in np.interp(np.arange(-half, half + 1, 1.0), tt, mm)])


# ---------------------------------------------------------------- octaves and noise
def sample_regions(mask, max_px=16e6, size=1024, n=24):
    """Whole image when small; otherwise up to n evenly spread size × size windows that lie (90 %) inside
    the mask. Keeps a 200 Mpx mosaic at a few seconds and a few hundred MB."""
    h, w = mask.shape
    if h * w <= max_px:
        return [(0, 0, w, h)]
    frac = cv2.resize(mask.astype(np.float32), (max(1, w // size), max(1, h // size)), interpolation=cv2.INTER_AREA)
    cells = [(x * size, y * size, size, size) for y, x in zip(*np.nonzero(frac > 0.9))]
    if not cells:
        return [(0, 0, w, h)]
    step = max(1, len(cells) // n)
    return cells[::step][:n]


def octave_energy(g, mask, levels=6, regions=None):
    """Relative Laplacian-pyramid energy per octave (0 = finest) on the masked region, normalised by
    the local brightness so that phase shading and exposure do not matter."""
    sums, counts = np.zeros(levels), np.zeros(levels)
    for x0, y0, w, h in regions or [(0, 0, g.shape[1], g.shape[0])]:
        gg, mm = g[y0:y0 + h, x0:x0 + w], mask[y0:y0 + h, x0:x0 + w]
        base = cv2.GaussianBlur(gg, (0, 0), 16)
        G = np.where(mm, gg / np.maximum(base, 1e-3), 1.0).astype(np.float32)
        M = mm.astype(np.float32)
        for k in range(levels):
            if min(G.shape) < 16:
                break
            down = cv2.pyrDown(G)
            band = G - cv2.pyrUp(down, dstsize=(G.shape[1], G.shape[0]))
            mk = cv2.erode(M, np.ones((5, 5), np.uint8)) > 0.5
            sums[k] += float((band[mk] ** 2).sum())
            counts[k] += int(mk.sum())
            G = down
            M = cv2.resize(M, (down.shape[1], down.shape[0]), interpolation=cv2.INTER_AREA)
    return [float(s / c) if c > 100 else float('nan') for s, c in zip(sums, counts)]


def mare_noise(g, mask, tile=32, regions=None):
    """Fine-scale noise (RMS of the finest band) in the 10 % flattest interior tiles, relative to their
    brightness."""
    act_all, noise_all = [], []
    for x0, y0, w, h in regions or [(0, 0, g.shape[1], g.shape[0])]:
        gg, mm = g[y0:y0 + h, x0:x0 + w], mask[y0:y0 + h, x0:x0 + w]
        sz = (w // tile, h // tile)
        if min(sz) < 1:
            continue
        cut = (slice(0, sz[1] * tile), slice(0, sz[0] * tile))
        gg, mm = gg[cut], mm[cut]
        fine = gg - cv2.GaussianBlur(gg, (0, 0), 1.0)
        act = np.abs(gg - cv2.GaussianBlur(gg, (0, 0), 4.0))
        area = lambda a: cv2.resize(a.astype(np.float32), sz, interpolation=cv2.INTER_AREA)
        full = area(mm) > 0.999
        b = np.maximum(area(gg), 1e-3)
        act_all.append((area(act) / b)[full])
        noise_all.append((np.sqrt(area(fine * fine)) / b)[full])
    if not act_all:
        return None
    act, noise = np.concatenate(act_all), np.concatenate(noise_all)
    if len(act) < 10:
        return None
    flat = noise[np.argsort(act)[:max(5, len(act) // 10)]]
    return float(np.median(flat))


# ---------------------------------------------------------------- colour
def colour_measures(raw, mask, limb=None):
    """chroma: 90th percentile of Lab chroma on the sunlit disk (natural lunar colour is faint; heavily boosted
    'mineral moon' colour is not). fringe: offset of the red against the blue limb edge in px (chromatic
    dispersion or misaligned channels), measured like the limb profile."""
    if raw.ndim != 3 or raw.shape[2] < 3:
        return dict(chroma=0.0, fringe_px=None)
    x = raw[..., :3]
    step = max(1, int(math.sqrt(x.shape[0] * x.shape[1] / 4e6)))          # ≈ 4 Mpx is plenty for a percentile
    xs = x[::step, ::step].astype(np.float32) / full_scale(raw)
    lab = cv2.cvtColor(xs, cv2.COLOR_BGR2Lab)
    m = mask[::step, ::step] & (lab[..., 0] > 15)
    chroma = float(np.percentile(np.hypot(lab[..., 1], lab[..., 2])[m], 90)) if m.sum() > 500 else 0.0
    fringe = limb_fringe(x, limb) if limb is not None else None
    return dict(chroma=round(chroma, 2), fringe_px=fringe)


def limb_fringe(x, limb, half=32, step=0.25, n_ang=720):
    """Red-versus-blue shift at the sunlit limb in px: per angle, the half-level crossing of each channel; the
    radial differences are fitted as one shift vector d (dispersion moves a whole channel), |d| is returned."""
    cx, cy, R = limb
    t = np.arange(-half, half + step / 2, step)
    ang = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    xs = (cx + np.outer(np.cos(ang), R + t)).astype(np.float32)
    ys = (cy + np.outer(np.sin(ang), R + t)).astype(np.float32)
    h, w = x.shape[:2]
    full = ((xs >= 1) & (xs < w - 2) & (ys >= 1) & (ys < h - 2)).all(1)
    cross = []
    for c in (2, 0):                                  # red, blue (BGR)
        prof = cv2.remap(x[..., c].astype(np.float32), xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        a, b = np.median(prof[:, t < -half / 2], 1), np.median(prof[:, t > half / 2], 1)
        q = (prof - b[:, None]) / np.maximum(a - b, 1e-6)[:, None]
        pos = np.full(n_ang, np.nan)
        for k in np.nonzero(full & (a - b > 0))[0]:
            j = np.nonzero((q[k, :-1] >= 0.5) & (q[k, 1:] < 0.5))[0]
            if len(j):
                j = j[np.argmin(np.abs(t[j]))]
                pos[k] = t[j] + (q[k, j] - 0.5) / (q[k, j] - q[k, j + 1] + 1e-9) * step
        cross.append((pos, a - b))
    (pr, cr), (pb, cb) = cross
    top = np.nanpercentile(np.where(full, np.minimum(cr, cb), np.nan), 90) if full.any() else 0
    ok = np.isfinite(pr) & np.isfinite(pb) & (np.minimum(cr, cb) > 0.5 * top)
    if ok.sum() < 20:
        return None
    d = pr[ok] - pb[ok]
    A = np.stack([np.cos(ang[ok]), np.sin(ang[ok])], 1)
    for _ in range(3):                                # robust: drop crater-rim outliers
        v = np.linalg.lstsq(A, d, rcond=None)[0]
        r = d - A @ v
        keep = np.abs(r) < max(3 * 1.4826 * np.median(np.abs(r)), 0.25)
        A, d = A[keep], d[keep]
    # a shift covers only part of the limb (a phase): the fit is still the displacement along the lit arc
    return round(float(np.hypot(*v)), 2)


# ---------------------------------------------------------------- compression and tonality
def jpeg_blocking(g8, mask=None):
    """Gradient across 8 px block edges / gradient elsewhere, inside mask (the Moon: a smooth dark sky
    gradient shows blocks that do not matter for annotation)."""
    g = g8.astype(np.float32)
    dh = np.abs(np.diff(g, axis=1))
    dv = np.abs(np.diff(g, axis=0))
    mh = np.ones(dh.shape, bool) if mask is None else mask[:, 1:] & mask[:, :-1]
    mv = np.ones(dv.shape, bool) if mask is None else mask[1:] & mask[:-1]
    cols = (np.arange(dh.shape[1]) % 8 == 7)[None, :]
    rows = (np.arange(dv.shape[0]) % 8 == 7)[:, None]
    if (mh & cols).sum() < 200 or (mv & rows).sum() < 200:
        return 1.0
    act = (dh[mh & ~cols].mean() + dv[mv & ~rows].mean()) / 2
    edge = (dh[mh & cols].mean() + dv[mv & rows].mean()) / 2
    return float(edge / max(act, 1e-6))


def posterisation(g, mask, raw):
    v = g[mask]
    if v.size < 1000:
        return None
    if v.size > 4_000_000:
        v = v[np.random.default_rng(0).integers(0, v.size, 4_000_000)]
    lo, hi = np.percentile(v, [1, 99])
    if raw.dtype == np.uint8:
        levels = np.arange(math.floor(lo), math.ceil(hi) + 1)
        if len(levels) < 8:
            return 1.0
        hist = np.bincount(np.clip(np.round(v).astype(int), 0, 255), minlength=256)[levels.astype(int)]
        return float((hist == 0).mean())
    q = np.round(v).astype(np.int64)
    q = q[(q >= lo) & (q <= hi)]
    return float(1 - len(np.unique(q)) / max(hi - lo + 1, 1)) if hi - lo < 4096 else 0.0


# ---------------------------------------------------------------- all together
def measure(raw, limb=None, km_per_px=None):
    """raw: the image as read by cv2.IMREAD_UNCHANGED. limb: (cx, cy, R) in native px or None."""
    g = luminance(raw)
    mask, lo, hi = moon_mask(g)
    q = dict(width=int(g.shape[1]), height=int(g.shape[0]), dtype=str(raw.dtype),
             channels=1 if raw.ndim == 2 else int(raw.shape[2]), moon_share=round(float(mask.mean()), 4))
    q.update(saturation(raw, mask))
    if limb is not None:
        cx, cy, R = limb
        q.update(limb_radius_px=round(R, 1))
        km_per_px = km_per_px or R_MOON / R
        lp = limb_profile(g, cx, cy, R)
        if lp:
            q.update(lp)
            q['edge_width_km'] = round(lp['edge_width_px'] * km_per_px, 3) if math.isfinite(lp['edge_width_px']) else None
    if km_per_px:
        q['km_per_px'] = round(km_per_px, 4)
    interior = cv2.erode(mask.astype(np.uint8), np.ones((33, 33), np.uint8)).astype(bool)
    if limb is not None:
        cx, cy, R = limb
        yy, xx = np.ogrid[0:g.shape[0], 0:g.shape[1]]
        interior &= (xx - cx) ** 2 + (yy - cy) ** 2 < (0.95 * R) ** 2
    regions = sample_regions(interior)
    e = octave_energy(g, interior, regions=regions)
    q['octave_energy'] = [round(v, 8) for v in e]
    q['octave_ratio'] = [round(e[k] / e[k + 1], 3) if e[k + 1] > 0 else None for k in range(len(e) - 1)]
    q['mare_noise'] = mare_noise(g, interior, regions=regions)
    q['fine_detail'] = round(e[1] / e[3], 4) if len(e) > 3 and e[3] > 0 and math.isfinite(e[1]) else None
    # JPEG is 8-bit only; its 8 px grid is measured on whole blocks of the sampled windows
    if raw.dtype == np.uint8:
        vals = [jpeg_blocking(g[y0:y0 + h, x0:x0 + w], mask[y0:y0 + h, x0:x0 + w]) for x0, y0, w, h in
                (sample_regions(mask) if len(regions) > 1 else regions)]
        q['jpeg_blocking'] = round(float(np.median(vals)), 3)
    else:
        q['jpeg_blocking'] = 1.0
    q.update(colour_measures(raw, mask, limb))
    if q.get('fringe_px') is not None and q.get('edge_width_px'):
        # a colour shift larger than the limb's own blur is a visible fringe; one inside a soft limb is not
        q['fringe_rel'] = round(q['fringe_px'] / max(q['edge_width_px'], 1.0), 3)
    q['posterisation'] = posterisation(g, mask, raw)
    return q
