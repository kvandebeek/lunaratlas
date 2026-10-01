"""Close-ups without a visible limb: where on the Moon is this image?

Nothing is assumed about the region (the user often does not know it). What is known or searched:
  scale     from the optics (lunaratlas_optics.json in the folder, asked once, or all 12 setups of the user's
            250 PDS: native / 2× ES / 2.5× TV Powermate / 3× ES × IMX678 / IMX533 / IMX462), the drizzle factor in the
            name, and the Earth–Moon distance at the capture time
  lighting  from the SharpCap UTC time in the name (atlas_ephem): LOLA relief lit by the real Sun, times the LROC
            albedo, so terminator shadows match too
  position, rotation, mirror   blind: the image, reduced to ~2 km/px and turned in 4° steps (mirrored and not), is
            correlated against the whole Earth-facing hemisphere; the best candidates are verified by terrain matching
            at a finer scale, the winner refined by the same fit as full-disk images.
"""
import json
import math
import os
import re
import time

import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tool_settings as ts  # noqa: E402
from atlas_ephem import capture_time, ephemeris  # noqa: E402
from atlas_geo import (DATA, R_MOON, Geometry, Reference, download, fit_correction, fit_global, load_gray, match_patches,
                       resize, sky_to_latlon, unit)

OPTICS_FILE = 'lunaratlas_optics.json'
OLD_OPTICS_FILES = ('moon_atlas_optics.json',)   # the same file, written before the rename; still read
MAX_CLOSEUP_RMS_PX = 6.0   # a genuine close-up fit is 1-3 px; past this the "matches" are a self-consistent wrong guess
# the user's equipment; LUNARATLAS_TELESCOPE, _FOCAL_MM, _EXTENDERS ("name:factor, …") and _CAMERAS ("name:µm, …") in .env
TELESCOPE = (ts.get('LUNARATLAS_TELESCOPE', '250 PDS'), ts.get('LUNARATLAS_FOCAL_MM', 1200.0, float))
EXTENDERS = tuple(ts.pairs('LUNARATLAS_EXTENDERS', [('native', 1.0), ('2× ES Focal Extender', 2.0),
                                                     ('2.5× TV Powermate', 2.5), ('3× ES Focal Extender', 3.0)]))
CAMERAS = tuple(ts.pairs('LUNARATLAS_CAMERAS', [('IMX678', 2.0), ('IMX533', 3.76), ('IMX462', 2.9)]))
BINNINGS = tuple(ts.pairs('LUNARATLAS_BINNINGS', [('1×1', 1.0), ('2×2', 2.0)]))
KM_PER_ARCSEC_PER_KM = math.pi / 180 / 3600      # km on the Moon per arcsec per km of distance
MAX_SCALE_STEP = 1.10     # unknown optics: no scale is more than ~5 % from a searched one (10 % off loses the place)


# ---------------------------------------------------------------- optics
def drizzle_factor(name):
    m = re.search(r'Drizzle(\d)(\d)', os.path.basename(name))
    return int(m[1]) + int(m[2]) / 10 if m else 1.0


def setups():
    """Every extender × camera × binning; pixel_um is the binned pixel."""
    return [dict(extender=e, magnification=f, camera=c, pixel_um=p * b, binning=bn if b != 1 else None)
            for e, f in EXTENDERS for c, p in CAMERAS for bn, b in BINNINGS]


def arcsec_per_px(s, drizzle=1.0):
    return 206.265 * s['pixel_um'] / (TELESCOPE[1] * s['magnification']) / drizzle


def optics_text(s):
    cam = s['camera'] + (f" {s['binning']} binned" if s.get('binning') else '')
    return f"{TELESCOPE[0]} · {s['extender']} · {cam} ({TELESCOPE[1] * s['magnification']:.0f} mm, {arcsec_per_px(s):.3f}″/px)"


def load_optics(folder):
    for name in (OPTICS_FILE,) + OLD_OPTICS_FILES:
        try:
            with open(os.path.join(folder, name)) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        return d if isinstance(d, dict) and 'magnification' in d and 'pixel_um' in d else None
    return None


def ask_optics(folder, log=print):
    """The folder's optics: from lunaratlas_optics.json, else asked once (when a terminal is attached) and saved.
    None = unknown: every setup is tried."""
    o = load_optics(folder)
    if o:
        return o
    import sys
    if not sys.stdin.isatty():
        log(f'optics unknown (no lunaratlas_optics.json, no terminal to ask): trying all {len(setups())} setups')
        return None
    print(f'\nWhich setup took the images in {folder}?')
    for i, (c, p) in enumerate(CAMERAS, 1):
        print(f'  {i}  {c} ({p} µm)')
    ci = input(f'camera [1-{len(CAMERAS)}, empty = not sure]: ').strip()
    for i, (e, f) in enumerate(EXTENDERS, 1):
        print(f'  {i}  {e}')
    ei = input(f'focal length [1-{len(EXTENDERS)}, empty = not sure]: ').strip()
    if not (ci.isdigit() and 1 <= int(ci) <= len(CAMERAS) and ei.isdigit() and 1 <= int(ei) <= len(EXTENDERS)):
        log(f'optics not given: trying all {len(setups())} setups')
        return None
    bn, b = BINNINGS[0]
    if len(BINNINGS) > 1:
        for i, (n, _) in enumerate(BINNINGS, 1):
            print(f'  {i}  {n}')
        bi = input(f'binning [1-{len(BINNINGS)}, empty = {bn}]: ').strip()
        if bi.isdigit() and 1 <= int(bi) <= len(BINNINGS):
            bn, b = BINNINGS[int(bi) - 1]
    c, p = CAMERAS[int(ci) - 1]
    e, f = EXTENDERS[int(ei) - 1]
    s = dict(telescope=TELESCOPE[0], focal_mm=TELESCOPE[1] * f, extender=e, magnification=f, camera=c, pixel_um=p * b,
             binning=bn if b != 1 else None)
    s['text'] = optics_text(s)
    with open(os.path.join(folder, OPTICS_FILE), 'w') as fh:
        json.dump(s, fh, indent=1)
    log(f'saved {OPTICS_FILE}: {s["text"]}')
    return s


# ---------------------------------------------------------------- shaded relief
LOLA_SHA256 = {16: 'a511e40d7a3ea3275945b4da2a1df377133264fab0be94b7434b1cf8907254cb',            # fixed archive products
               64: '1c4958699d4cffd7e777d51421b6044bba300aa0bef286a544309efb082cdbd6'}
LOLA_URL = 'https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img'


def lola_path(ppd, log=print):
    """data/lola/ldem_PPD.img, downloaded from the PDS once (16 px/deg ≈ 33 MB; 64 px/deg ≈ 530 MB, close-ups only)."""
    p = os.path.join(DATA, 'lola', f'ldem_{ppd}.img')
    size = 180 * ppd * 360 * ppd * 2
    if os.path.exists(p) and os.path.getsize(p) == size:
        return p
    log(f'downloading the LOLA elevation model, {ppd} px/deg (≈ {size / 1e6:.0f} MB, once)' if not os.path.exists(p)
        else f'LOLA elevation model {ppd} px/deg is damaged: downloading it again')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    download(f'{LOLA_URL}/ldem_{ppd}.img', p, lambda f: os.path.getsize(f) == size, timeout=120, log=log,
             sha256=LOLA_SHA256.get(ppd), max_bytes=size)
    return p


class Relief:
    """LOLA LDEM (16 or 64 px/deg) slopes, sampled in any view: Lommel-Seeliger shading × LROC albedo."""

    def __init__(self, ppd=16, log=print):
        p = lola_path(ppd, log)
        h = np.fromfile(p, '<i2').reshape(180 * ppd, 360 * ppd).astype(np.float32) * 0.5      # m
        self.ppd = ppd
        # slopes (m per m) towards east and north; the map runs lon 0..360 east, lat +90..-90
        km_deg = 2 * math.pi * R_MOON / 360
        gx = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3, borderType=cv2.BORDER_REPLICATE) / 8
        gy = cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3, borderType=cv2.BORDER_REPLICATE) / 8
        self.dn = -gy * ppd / (km_deg * 1000)             # north = up the map
        lat = 90 - (np.arange(h.shape[0]) + 0.5) / ppd
        self.de_raw = gx * ppd / (km_deg * 1000)           # divided by cos(lat) when sampled
        self.coslat = np.cos(np.radians(lat)).astype(np.float32)

    def slopes(self, lat, lon):
        mx = ((np.asarray(lon) % 360) * self.ppd - 0.5).astype(np.float32)
        my = ((90 - np.asarray(lat)) * self.ppd - 0.5).astype(np.float32)
        de = cv2.remap(self.de_raw, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        dn = cv2.remap(self.dn, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return de / np.maximum(np.cos(np.radians(lat)), 0.05), dn


def render_shaded(geo, w, h, relief, ref, sun_latlon, albedo=True):
    """The Moon as it looked: relief lit from the subsolar point, seen from the geometry's sub-observer point."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    lat, lon, ok = geo.to_latlon(xs, ys)
    lat = np.where(ok, lat, 0.0)
    lon = np.where(ok, lon, 0.0)
    de, dn = relief.slopes(lat, lon)
    la, lo = np.radians(lat), np.radians(lon)
    up = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)
    east = np.stack([-np.sin(lo), np.cos(lo), np.zeros_like(lo)], -1)
    north = np.cross(up, east)
    n = up - de[..., None] * east - dn[..., None] * north
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    s = unit(*sun_latlon)
    e = unit(geo.lat0, geo.lon0)
    mu0 = np.clip(n @ s, 0, None)
    mu = np.clip(n @ e, 1e-3, None)
    img = mu0 / (mu0 + mu)
    if albedo:
        a, ok2 = ref.render(geo, w, h)
        # albedo modulates; beyond the albedo map's ±60° the relief alone
        img = img * np.where(ok2, 0.35 + a / 255.0, 0.85)
    return np.where(ok & (np.hypot(*geo.to_sky(xs, ys)) < 0.995), img, 0).astype(np.float32), ok


# ---------------------------------------------------------------- search
def normalise(x, sigma):
    """Local contrast: high-pass, divided by the local RMS (brightness, exposure and phase shading drop out)."""
    x = x.astype(np.float32)
    hp = x - cv2.GaussianBlur(x, (0, 0), sigma)
    return hp / np.sqrt(cv2.GaussianBlur(hp * hp, (0, 0), sigma * 2) + 1e-6)


def view_template(gray, km, work_km, ang, mirror):
    """The close-up as one search view: reduced to work_km per px, turned by ang (mirrored or not), cut to a disk of
    0.9 of its short side. Returns (template, dict of what solve_hit needs to turn a match back into a geometry), or
    None when the image is too small at this scale."""
    small, (sx, sy) = resize(gray, km / work_km)
    side = int(0.9 * min(small.shape))
    if side < 24:
        return None
    sn = normalise(small, 3)
    yy, xx = np.mgrid[0:side, 0:side]
    circle = ((xx - (side - 1) / 2) ** 2 + (yy - (side - 1) / 2) ** 2) < (side / 2) ** 2
    cs = np.array([(small.shape[1] - 1) / 2, (small.shape[0] - 1) / 2])
    a = math.radians(ang)
    R2 = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    if mirror:
        R2 = R2 @ np.diag([-1.0, 1.0])
    ct = np.array([(side - 1) / 2, (side - 1) / 2])
    T = np.hstack([R2, (ct - R2 @ cs)[:, None]])
    tpl = cv2.warpAffine(sn, T, (side, side), flags=cv2.INTER_LINEAR)
    return np.where(circle, tpl, 0).astype(np.float32), dict(km=km, angle=ang, mirror=mirror, R2=R2, cs=cs, ct=ct, sxy=(sx, sy))


def work_reference(lat0, lon0, sun, relief, ref, work_km):
    """The Earth-facing hemisphere as it looked, at work_km per px: (normalised image, geometry of it)."""
    Rw = R_MOON / work_km
    size = int(2 * Rw * 1.02) + 8
    c = (size - 1) / 2
    geo_w = Geometry(lat0, lon0, Rw * np.array([[1.0, 0], [0, -1.0]]), [c, c])
    rimg, ok = render_shaded(geo_w, size, size, relief, ref, sun)
    rn = normalise(rimg, 3)
    rn[~ok] = 0
    return rn, geo_w


def distinct(cands, keep, dist):
    """The best `keep` of cands that are distinct places (neighbouring angles are one candidate)."""
    cands = sorted(cands, key=lambda cc: -cc['score'])
    out = []
    for cc in cands:
        if all(math.hypot(cc['tl'][0] - o['tl'][0], cc['tl'][1] - o['tl'][1]) > dist or cc['mirror'] != o['mirror'] for o in out):
            out.append(cc)
        if len(out) >= keep:
            break
    return out


def per_scale(cands, km_list, keep, dist, least):
    """distinct() within each scale, then every scale's best, every scale's second, … (each rank by score).
    Ranked across scales by raw score, a small view (few pixels) wins with a chance peak over the true place at a
    slightly wrong scale: a 1840 px close-up at 0.22 km/px is 40 px wide at 4.8 km/px, and its best noise peak beat
    the real place at 0.50 km/px (8 % off its true 0.54, still verified by 144 matches)."""
    n = max(least, math.ceil(keep / len(km_list)))
    lists = [distinct([c for c in cands if c['km'] == km], n, dist) for km in km_list]
    return [c for r in range(n) for c in sorted((l[r] for l in lists if len(l) > r), key=lambda c: -c['score'])]


def blind_search_full(gray, km_list, lat0, lon0, sun, relief, ref, log, work_km=2.4, angle_step=4, keep=12):
    """Every view at work_km and angle_step against the whole hemisphere: candidates (score, km_per_px, angle, mirror,
    ref centre px) of the close-up. Thorough and slow (reference for blind_search)."""
    rn, geo_w = work_reference(lat0, lon0, sun, relief, ref, work_km)
    cands = []
    t0 = time.perf_counter()
    n_total = len(km_list) * 2 * (360 // angle_step)
    done = 0
    for km in km_list:
        for mirror in (False, True):
            for ang in range(0, 360, angle_step):
                v = view_template(gray, km, work_km, ang, mirror)
                if v is None:
                    done += 1
                    continue
                tpl, meta = v
                _, mx, _, tl = cv2.minMaxLoc(cv2.matchTemplate(rn, tpl, cv2.TM_CCOEFF_NORMED))
                cands.append(dict(meta, score=float(mx), tl=tl))
                done += 1
            log(f'  search: {done}/{n_total} views ({km:.3f} km/px, {"mirrored" if mirror else "not mirrored"}), '
                f'best so far {max((cc["score"] for cc in cands), default=0):.3f}, {time.perf_counter() - t0:.0f} s')
    return distinct(cands, keep, 20), geo_w


def blind_search(gray, km_list, lat0, lon0, sun, relief, ref, log, work_km=2.4, angle_step=4, keep=12,
                 coarse_km=4.8, coarse_step=4, coarse_keep=30, fine_step=1, pad=24):
    """Coarse to fine. Pass 1: every view against the hemisphere at coarse_km per px (a quarter of the pixels) in
    coarse_step° turns, which keeps coarse_keep distinct places. Pass 2: each of those at work_km, only in a window
    around where it was found, turned by ±coarse_step° in fine_step° steps. About three times faster than
    blind_search_full, and it finds the place at a finer angle than that one's angle_step.
    Candidates as blind_search_full's, at work_km (solve_hit needs that resolution)."""
    t0 = time.perf_counter()
    rc, geo_c = work_reference(lat0, lon0, sun, relief, ref, coarse_km)
    coarse = []
    n_total = len(km_list) * 2 * (360 // coarse_step)
    done = 0
    for km in km_list:
        for mirror in (False, True):
            for ang in range(0, 360, coarse_step):
                done += 1
                v = view_template(gray, km, coarse_km, ang, mirror)
                if v is None:
                    continue
                tpl, meta = v
                _, mx, _, tl = cv2.minMaxLoc(cv2.matchTemplate(rc, tpl, cv2.TM_CCOEFF_NORMED))
                coarse.append(dict(meta, score=float(mx), tl=tl))
            log(f'  search: {done}/{n_total} coarse views ({km:.3f} km/px, {"mirrored" if mirror else "not mirrored"}), '
                f'best so far {max((cc["score"] for cc in coarse), default=0):.3f}, {time.perf_counter() - t0:.0f} s')
    places = per_scale(coarse, km_list, coarse_keep, 10, 3)
    rn, geo_w = work_reference(lat0, lon0, sun, relief, ref, work_km)
    k = coarse_km / work_km
    fine = []
    for i, c in enumerate(places):
        for ang in np.arange(c['angle'] - coarse_step, c['angle'] + coarse_step + 1e-9, fine_step):
            v = view_template(gray, c['km'], work_km, float(ang) % 360, c['mirror'])
            if v is None:
                continue
            tpl, meta = v
            side = tpl.shape[0]
            x0, y0 = max(0, int(round(c['tl'][0] * k)) - pad), max(0, int(round(c['tl'][1] * k)) - pad)
            win = rn[y0:y0 + side + 2 * pad, x0:x0 + side + 2 * pad]
            if win.shape[0] < side or win.shape[1] < side:
                continue
            _, mx, _, (px, py) = cv2.minMaxLoc(cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED))
            fine.append(dict(meta, score=float(mx), tl=(px + x0, py + y0)))
        if (i + 1) % 10 == 0 or i + 1 == len(places):
            log(f'  search: refined {i + 1}/{len(places)} places, best {max((cc["score"] for cc in fine), default=0):.3f}, '
                f'{time.perf_counter() - t0:.0f} s')
    return per_scale(fine, km_list, keep, 20, 2), geo_w


def solve_hit(c, geo_w):
    """Geometry (image px) of a search hit: image px -> reduced px -> turned template px -> work render px -> sky."""
    sx, sy = c['sxy']
    R2 = c['R2']
    G = R2 @ np.diag([sx, sy])                            # image px -> work px (linear part)
    g = R2 @ (0.5 * np.array([sx, sy]) - 0.5 - c['cs']) + c['ct'] + np.array(c['tl'], float)
    Gi = np.linalg.inv(G)
    return Geometry(geo_w.lat0, geo_w.lon0, Gi @ geo_w.A, Gi @ (geo_w.t - g))


def fit_affine(P, L, lat0, lon0, iters=4):
    """Image px <-> lat/lon pairs -> affine sky -> image with the libration held (known from the capture time; a
    close-up covers too little of the sphere to fit it)."""
    from atlas_geo import latlon_to_sky
    keep = np.ones(len(P), bool)
    for _ in range(iters):
        xs, ys, _ = latlon_to_sky(L[keep, 0], L[keep, 1], lat0, lon0)
        sol = np.linalg.lstsq(np.stack([xs, ys, np.ones_like(xs)], 1), P[keep], rcond=None)[0]
        g = Geometry(lat0, lon0, sol[:2].T, sol[2])
        x, y, _ = g.to_image(L[:, 0], L[:, 1])
        res = np.hypot(x - P[:, 0], y - P[:, 1])
        keep = res < max(3 * 1.4826 * np.median(res[keep]), 0.5)
    return g, res, keep


def verify(gray, geo, relief, ref, sun, target_px=1100, fixed=True):
    """Consistent terrain matches of a candidate geometry, on a reduced copy (patches vs the shaded reference)."""
    H, W = gray.shape
    s = min(1.0, target_px / max(H, W))
    gi, (sx, sy) = (gray, (1.0, 1.0)) if s >= 0.999 else resize(gray, s)
    gs = geo.resized(sx, sy)
    rr, ok = render_shaded(gs, gi.shape[1], gi.shape[0], relief, ref, sun)
    P, L, _ = match_patches(gi, rr * 255, ok, gs, 48, 20, 36)
    if len(P) < 8:
        return 0, None, None
    g, res, keep = fit_affine(P, L, geo.lat0, geo.lon0) if fixed else fit_global(P, L, gs)
    return int(keep.sum()), g.resized(1 / sx, 1 / sy), float(np.sqrt((res[keep] ** 2).mean()) / s) if keep.any() else None


def km_candidates(path, optics, dist_km):
    """(km per px, setup) to search, finest first. Known optics: nominal ± 10 % (a focal extender's real factor
    depends on the spacing). Unknown: every setup's scale, near-equal ones (< 5 % apart) merged and gaps wider than
    MAX_SCALE_STEP filled (setup None), since the search loses a place whose scale is ~10 % off."""
    drz = drizzle_factor(path)
    to_km = dist_km * KM_PER_ARCSEC_PER_KM
    if optics:
        base = arcsec_per_px(optics, drz) * to_km
        return [(base * f, optics) for f in (0.9, 1.0, 1.1)]
    out = []
    for km, o in sorted(((arcsec_per_px(o, drz) * to_km, o) for o in setups()), key=lambda t: t[0]):
        if out:
            prev = out[-1][0]
            if km / prev < 1.05:
                continue
            steps = math.ceil(math.log(km / prev) / math.log(MAX_SCALE_STEP))
            out += [(prev * (km / prev) ** (i / steps), None) for i in range(1, steps)]
        out.append((km, o))
    return out


def locate_closeup(path, log=print, optics=None, when=None):
    """Close-up (a path, no limb needed) -> (Geometry, quality dict). when: UTC datetime if not in the name."""
    t0 = time.perf_counter()
    gray = load_gray(path)[0]
    H, W = gray.shape
    when = when or capture_time(path)
    if when is None:
        raise SystemExit('a close-up needs the capture time (SharpCap name YYYY-MM-DD-HHMM_T-…) for its lighting')
    eph = ephemeris(when)
    lat0, lon0 = eph['sub_obs_lat'], eph['sub_obs_lon']
    sun = (eph['sub_sun_lat'], eph['sub_sun_lon'])
    log(f"capture {when:%Y-%m-%d %H:%M} UTC: libration {lat0:+.2f}° {lon0:+.2f}°, colongitude {eph['colongitude']:.1f}°, "
        f"Earth–Moon {eph['distance_km']:.0f} km")
    folder = os.path.dirname(os.path.abspath(path))
    optics = optics if optics is not None else ask_optics(folder, log)
    had_optics = optics is not None
    relief16, relief64, ref = Relief(16, log), Relief(64, log), Reference(log)

    def fits(n, rms):
        return n >= 15 and rms is not None and rms <= MAX_CLOSEUP_RMS_PX

    def search(optics):
        """((matches, geometry, rms, hit, n candidates), None) for the best fit that passes both gates, else
        (None, why)."""
        kms = [km for km, _ in km_candidates(path, optics, eph['distance_km']) if W * km < 2600]
        if not kms:
            return None, 'no optics setup gives a close-up at this image size'
        log(f"{len(kms)} candidate scales {kms[0]:.3f}–{kms[-1]:.3f} km/px "
            + (f"({optics['text']})" if optics else f"(all {len(setups())} setups)"))
        cands, geo_w = blind_search(gray, kms, lat0, lon0, sun, relief16, ref, log)
        best, worst = None, (0, None)
        for i, c in enumerate(cands):
            geo = solve_hit(c, geo_w)
            n, g, rms = verify(gray, geo, relief64, ref, sun)
            la, lo, _ = geo.to_latlon(W / 2, H / 2)
            log(f"  candidate {i + 1}: score {c['score']:.3f}, {c['km']:.3f} km/px, {c['angle']}°"
                f"{', mirrored' if c['mirror'] else ''}, centre {float(la):+.1f}° {float(lo):+.1f}° → {n} terrain matches"
                + (f", {rms:.1f} px rms" if rms is not None else ''))
            if not fits(n, rms):
                worst = max(worst, (n, rms), key=lambda t: t[0])
                continue
            if best is None or n > best[0]:
                best = (n, g, rms, c)
            if n >= 60:
                break
        if best is None:
            n, rms = worst
            return None, (f'close-up not found: the best position had {n} terrain matches'
                          + (f' but {rms:.1f} px rms — too poor a fit to trust' if n >= 15 and rms is not None else ''))
        n, geo, rms, c = best
        # refine at full resolution (or 2400 px): patches against the 64 px/deg relief, affine with libration held
        n2, g2, rms2 = verify(gray, geo, relief64, ref, sun, target_px=min(2400, max(H, W)))
        if n2 >= max(15, n // 2) and fits(n2, rms2):
            geo, n, rms = g2, n2, rms2
        return (n, geo, rms, c, len(cands)), None

    found, why = search(optics)
    if found is None and had_optics:
        # the folder's optics are one night's setup: a frame binned, or with another extender, is at another scale
        log(f"{why} at the scale of {OPTICS_FILE} ({optics['text']}): trying every setup")
        optics = None
        found, why = search(None)
    if found is None:
        raise SystemExit(why)
    n, geo, rms, c, n_cands = found
    la, lo, _ = geo.to_latlon(W / 2, H / 2)
    if optics is None:
        # the fitted scale tells which setup it was: saved for the folder (unless it has its own), so its next images
        # search 3 scales, not all
        arcsec = geo.km_per_px / (eph['distance_km'] * KM_PER_ARCSEC_PER_KM) * drizzle_factor(path)
        best_s = min(setups(), key=lambda o: abs(math.log(arcsec_per_px(o) / arcsec)))
        if abs(math.log(arcsec_per_px(best_s) / arcsec)) < 0.12:
            o = dict(telescope=TELESCOPE[0], focal_mm=TELESCOPE[1] * best_s['magnification'], **best_s,
                     detected_from=os.path.basename(path), measured_arcsec_per_px=round(arcsec, 4))
            o['text'] = optics_text(o)
            if had_optics:
                log(f"optics recognised from the scale ({arcsec:.3f}″/px): {o['text']} · {OPTICS_FILE} left as it is")
                optics = o
            else:
                try:
                    with open(os.path.join(folder, OPTICS_FILE), 'w') as fh:
                        json.dump(o, fh, indent=1)
                    log(f"optics recognised from the scale ({arcsec:.3f}″/px): {o['text']} · saved {OPTICS_FILE}")
                    optics = o
                except OSError:
                    pass
    q = dict(matches=int(n), rms_px=round(float(rms), 2), cv_rms_px=None, correction_degree=0, closeup=True,
             search_score=round(c['score'], 3), orientation_candidates=n_cands,
             optics=optics['text'] if optics else None, capture_utc=when.strftime('%Y-%m-%d %H:%M:%S'),
             centre_latlon=[round(float(la), 3), round(float(lo), 3)], seconds=round(time.perf_counter() - t0, 1),
             width=W, height=H, limb_radius_px=None, orientation_score=None, other_mirror_score=None)
    log(f"close-up located: centre {float(la):+.2f}° {float(lo):+.2f}°, {geo.km_per_px:.3f} km/px, north "
        f"{geo.north_angle:.1f}°, {'mirrored' if geo.mirrored else 'not mirrored'}, {n} matches, {rms:.2f} px rms, "
        f"{q['seconds']} s")
    return geo, q
