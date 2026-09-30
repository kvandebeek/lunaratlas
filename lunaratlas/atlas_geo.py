"""Where every pixel of a lunar image lies on the Moon.

Geometry: selenographic (lat, lon) -> unit sphere -> perspective view from the sub-observer
point (lat0, lon0) -> 2x2 affine + offset into image pixels -> smooth polynomial correction
(stitching / refraction residue). Found automatically by matching the image against the LROC
WAC 643 nm normalized-albedo map rendered in the same geometry.
"""
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
from atlas_paths import DATA, publish, temp_beside  # noqa: E402  (lunaratlas/data, or the app's data folder)
R_MOON = 1737.4           # km
DIST = 221.0              # Earth-Moon distance in lunar radii (perspective; 205-234 over the orbit)
PPD = 64                  # reference map pixels per degree
SIDECAR_SCHEMA = 'lunaratlas.geo/1'
OLD_SCHEMAS = ('moon_atlas.geo/1',)       # the same format, written before the rename; still read
REF_TILES = {'E300N3150': (0, 0), 'E300N0450': (0, 90), 'E300S3150': (60, 0), 'E300S0450': (60, 90)}
REF_URL = 'https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/BROWSE/WAC_EMP'
DOWNLOAD_HOSTS = {'pds.lroc.im-ldi.com', 'pds-geosciences.wustl.edu', 'asc-planetarynames-data.s3.us-west-2.amazonaws.com',
                  'api.github.com', 'raw.githubusercontent.com'}                       # the only hosts anything is fetched from
REF_SHA256 = {'E300N3150': '422615a7d4e7707f8be828a3a5b05797d5fbdaf93a374405f2e308aff2c16651',      # fixed archive products:
              'E300N0450': 'aef55c19918daa8b96bcf045b75f589222b0940e0634500decc028776e1d8bbb',
              'E300S3150': '6536e4fa9c3388b095b79bdc030f996df47998e6a870c9aa1a4056f6b103e016',      # anything else is refused
              'E300S0450': '1be84f5edd067d8d8d9ecf34a2ab2bdeb405a61652bc8ac26bbb3aa5073f8ad4'}


# ---------------------------------------------------------------- sphere and projection
def frame(lat0, lon0):
    """Sky-plane axes (east u, north v, towards the observer e) in the Moon body frame."""
    a, b = math.radians(lat0), math.radians(lon0)
    e = np.array([math.cos(a) * math.cos(b), math.cos(a) * math.sin(b), math.sin(a)])
    u = np.array([-math.sin(b), math.cos(b), 0.0])
    return u, np.cross(e, u), e


def unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)


def latlon_to_sky(lat, lon, lat0, lon0, D=DIST):
    """Perspective projection onto the plane through the Moon centre (lunar radii).
    Returns x (east), y (north) and z = cos(emission) (visible if > 1/D)."""
    p = unit(lat, lon)
    u, v, e = frame(lat0, lon0)
    z = p @ e
    k = D / (D - z)
    return (p @ u) * k, (p @ v) * k, z


def sky_to_latlon(xs, ys, lat0, lon0, D=DIST):
    """Ray from the observer through the sky-plane point, first hit on the unit sphere."""
    u, v, e = frame(lat0, lon0)
    O = D * e
    d = xs[..., None] * u + ys[..., None] * v - O
    dd = (d * d).sum(-1)
    od = d @ O
    disc = od * od - dd * (D * D - 1.0)
    ok = disc >= 0
    s = (-od - np.sqrt(np.clip(disc, 0, None))) / dd
    p = O + s[..., None] * d
    lat = np.degrees(np.arcsin(np.clip(p[..., 2], -1, 1)))
    lon = np.degrees(np.arctan2(p[..., 1], p[..., 0]))
    return lat, lon, ok


def poly_terms(sx, sy, deg):
    return np.stack([sx ** i * sy ** j for i in range(deg + 1) for j in range(deg + 1 - i)], -1)


class Geometry:
    """image px <-> selenographic lat/lon.

    image = A @ sky + t + correction(sky)   (image y grows downwards; A absorbs scale,
    rotation, mirroring and slight anisotropy; the correction is clamped at radius rmax so it
    never extrapolates beyond the matched area)."""

    def __init__(self, lat0, lon0, A, t, coef=None, deg=0, rmax=0.9, dist=DIST):
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.A, self.t = np.asarray(A, float), np.asarray(t, float)
        self.deg, self.rmax, self.dist = int(deg), float(rmax), float(dist)
        self.coef = None if coef is None else np.asarray(coef, float)
        self.Ai = np.linalg.inv(self.A)

    # -- basics
    @property
    def radius_px(self):
        return math.sqrt(abs(np.linalg.det(self.A)))

    @property
    def km_per_px(self):
        return R_MOON / self.radius_px

    @property
    def mirrored(self):
        return np.linalg.det(self.A) > 0          # image y points down: an unmirrored view has det < 0

    @property
    def north_angle(self):
        """Direction of lunar north on screen, degrees counter-clockwise from 'up'."""
        n = self.A @ np.array([0.0, 1.0])
        return math.degrees(math.atan2(-n[0], -n[1])) % 360

    def resized(self, sx, sy=None):
        """The same geometry for the image after cv2.resize by (sx, sy): pixel centres map as
        p' = (p + 0.5) * s - 0.5, so a resize is a scale plus a sub-pixel shift."""
        sy = sx if sy is None else sy
        S = np.diag([sx, sy])
        return Geometry(self.lat0, self.lon0, S @ self.A, S @ self.t + 0.5 * np.array([sx, sy]) - 0.5,
                        None if self.coef is None else self.coef * [sx, sy], self.deg, self.rmax, self.dist)

    def without_correction(self):
        return Geometry(self.lat0, self.lon0, self.A, self.t, None, 0, self.rmax, self.dist)

    # -- correction
    def _corr(self, sx, sy):
        if self.coef is None:
            return 0.0, 0.0
        r = np.hypot(sx, sy)
        k = np.where(r > self.rmax, self.rmax / np.maximum(r, 1e-9), 1.0)
        c = poly_terms(sx * k, sy * k, self.deg) @ self.coef
        return c[..., 0], c[..., 1]

    # -- forward / inverse
    def to_image(self, lat, lon):
        sx, sy, z = latlon_to_sky(np.asarray(lat, float), np.asarray(lon, float), self.lat0, self.lon0, self.dist)
        x = self.A[0, 0] * sx + self.A[0, 1] * sy + self.t[0]
        y = self.A[1, 0] * sx + self.A[1, 1] * sy + self.t[1]
        cx, cy = self._corr(sx, sy)
        return x + cx, y + cy, z

    def to_sky(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        xm, ym = x, y
        for _ in range(4 if self.coef is not None else 1):     # fixed point: the correction is small and smooth
            dx, dy = xm - self.t[0], ym - self.t[1]
            sx = self.Ai[0, 0] * dx + self.Ai[0, 1] * dy
            sy = self.Ai[1, 0] * dx + self.Ai[1, 1] * dy
            cx, cy = self._corr(sx, sy)
            xm, ym = x - cx, y - cy
        return sx, sy

    def to_latlon(self, x, y):
        sx, sy = self.to_sky(x, y)
        return sky_to_latlon(sx, sy, self.lat0, self.lon0, self.dist)

    # -- persistence
    def as_dict(self):
        return dict(lat0=self.lat0, lon0=self.lon0, A=self.A.tolist(), t=self.t.tolist(), deg=self.deg,
                    rmax=self.rmax, dist=self.dist, coef=None if self.coef is None else self.coef.tolist())

    @staticmethod
    def from_dict(d):
        """Raises ValueError for anything that is not a usable geometry."""
        try:
            g = Geometry(d['lat0'], d['lon0'], d['A'], d['t'], d.get('coef'), d.get('deg', 0),
                         d.get('rmax', 0.9), d.get('dist', DIST))
        except (KeyError, TypeError, ValueError, np.linalg.LinAlgError) as e:
            raise ValueError(f'invalid geometry: {e!r}') from None
        nterms = (g.deg + 1) * (g.deg + 2) // 2
        if g.A.shape != (2, 2) or g.t.shape != (2,) or not (np.isfinite(g.A).all() and np.isfinite(g.t).all()):
            raise ValueError('invalid geometry: A must be 2 x 2 and t of length 2, all finite')
        if g.coef is not None and (g.coef.shape != (nterms, 2) or not np.isfinite(g.coef).all()):
            raise ValueError(f'invalid geometry: correction must be {nterms} x 2 for degree {g.deg}')
        if not (math.isfinite(g.lat0) and math.isfinite(g.lon0) and g.dist > 1 and g.rmax > 0 and g.radius_px > 0):
            raise ValueError('invalid geometry: libration, distance or radius out of range')
        return g


def similarity(cx, cy, R, theta_deg, mirror):
    """Sky (x east, y north) -> image with north rotated by theta; optional mirror."""
    th = math.radians(theta_deg)
    rot = np.array([[math.cos(th), math.sin(th)], [math.sin(th), -math.cos(th)]])
    if mirror:
        rot = rot @ np.diag([-1.0, 1.0])
    return R * rot, np.array([cx, cy], float)


# ---------------------------------------------------------------- reference map
def https_check(url):
    """Raise unless url is https and its host is one this program downloads from. The one place this check is
    made, used both for a request's own URL and for every redirect it is sent to (claude-findings.md C-29: a
    redirect used to be checked for scheme only, so an allowed host redirecting off itself, e.g. to an S3 bucket
    or a CDN frontier, would have its target fetched and accepted unpinned)."""
    u = urlsplit(url)
    if u.scheme.lower() != 'https':
        raise urllib.error.URLError(f'refusing {u.scheme or "a URL without a scheme"}: only https')
    if (u.hostname or '').lower() not in DOWNLOAD_HOSTS:
        raise urllib.error.URLError(f'refusing {u.hostname}: not a host LunarAtlas downloads from')


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """A download that starts on https from an allowed host never continues anywhere else: a redirect off TLS, or
    to a host not in DOWNLOAD_HOSTS, is refused."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


urllib.request.install_opener(urllib.request.build_opener(_HttpsOnly))       # for every urlopen of this program


def https_open(url, timeout=60):
    """urlopen for an https URL from a host this program downloads from, and only such a URL on any redirect."""
    https_check(url)
    return urllib.request.urlopen(url, timeout=timeout)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, valid, timeout=60, log=None, sha256=None, max_bytes=None):
    """url (https only) -> dest through a temporary file: dest only ever appears complete and accepted by valid(path).
    sha256: the digest the file must have (a fixed product); max_bytes: more than that is refused as it arrives.
    With log, a line 'downloaded A of B MB' about every second (the app's progress bar reads it)."""
    tmp = temp_beside(dest, '.part')
    try:
        with https_open(url, timeout) as r, open(tmp, 'wb') as fh:
            hdr = getattr(r, 'headers', None)
            total, got, shown = int((hdr.get('Content-Length') if hdr else 0) or 0), 0, 0.0
            if max_bytes and total > max_bytes:
                raise SystemExit(f'download of {url} is larger than expected ({total / 1e6:.0f} MB); not taken')
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if max_bytes and got > max_bytes:
                    raise SystemExit(f'download of {url} is larger than expected; not taken')
                if log and total and (time.monotonic() - shown > 1 or got == total):
                    shown = time.monotonic()
                    log(f'  downloaded {got / 1e6:.1f} of {total / 1e6:.1f} MB')
        if sha256 and sha256_file(tmp) != sha256:
            raise SystemExit(f'download of {url} is not the file this version expects (checksum differs); not taken')
        if not valid(tmp):
            raise SystemExit(f'download of {url} is damaged; try again')
        publish(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_atomic(path, write):
    """write(tmp_path) then rename over path, so an interrupted write never leaves a damaged file.
    A write that cannot happen at all (a read-only folder, a full disk) is a clear message, not a traceback."""
    tmp = None
    try:
        try:
            tmp = temp_beside(path)              # keeps the extension: cv2.imwrite picks the encoder from it
            write(tmp)
            publish(tmp, path)
        except OSError as e:
            raise SystemExit(f'cannot write {path}: {e.strerror or e}') from None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass                             # a temporary file that cannot be removed is left behind, not fatal


class Reference:
    """LROC WAC 643 nm normalized albedo, near side: lon -90..90, lat 60..-60 at 64 px/deg."""
    SHAPE = (120 * PPD, 180 * PPD)

    def __init__(self, log=print):
        cache = os.path.join(DATA, 'wac_emp_643_nearside.png')
        ref = cv2.imread(cache, cv2.IMREAD_GRAYSCALE) if os.path.exists(cache) else None
        if ref is None or ref.shape != self.SHAPE:
            ref = self._assemble(log)

            def write(p):
                if not cv2.imwrite(p, ref):
                    raise OSError(f'cannot write {p}')
            write_atomic(cache, write)
        self.levels = [ref]
        while self.levels[-1].shape[1] > 1500:
            self.levels.append(cv2.pyrDown(self.levels[-1]))

    @staticmethod
    def _tile(path):
        im = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if os.path.exists(path) else None
        return im if im is not None and im.shape == (60 * PPD, 90 * PPD) else None

    @classmethod
    def _assemble(cls, log):
        d = os.path.join(DATA, 'wac_emp_643')
        os.makedirs(d, exist_ok=True)
        ref = np.zeros(cls.SHAPE, np.uint8)
        for t, (r, c) in REF_TILES.items():
            f = os.path.join(d, f'WAC_EMP_643NM_{t}_064P.TIF')
            im = cls._tile(f)
            if im is None:
                log(f'downloading reference tile {t} (≈ 22 MB, once)' if not os.path.exists(f) else
                    f'reference tile {t} is damaged: downloading it again')
                download(f'{REF_URL}/WAC_EMP_643NM_{t}_064P.TIF', f, lambda p: cls._tile(p) is not None, log=log,
                         sha256=REF_SHA256[t], max_bytes=30_000_000)
                im = cls._tile(f)
            ref[r * PPD:(r + 60) * PPD, c * PPD:(c + 90) * PPD] = im
        return ref

    def render(self, geo, w, h):
        """Reference resampled into the image geometry (pyramid level just finer than the target)."""
        ref_km = 2 * math.pi * R_MOON / 360 / PPD
        i = 0
        while i + 1 < len(self.levels) and ref_km * 2 ** (i + 1) < 0.7 * geo.km_per_px:
            i += 1
        lvl, ppd = self.levels[i], PPD / 2 ** i
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
        lat, lon, ok = geo.to_latlon(xs, ys)
        ok &= (np.abs(lat) < 59.5) & (np.abs(lon) < 89.5)
        mx = ((lon + 90.0) * ppd).astype(np.float32)
        my = ((60.0 - lat) * ppd).astype(np.float32)
        out = cv2.remap(lvl, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return out.astype(np.float32), ok


# ---------------------------------------------------------------- image I/O
def resize(img, s):
    """INTER_AREA resize by about s; returns the image and the exact (sx, sy) of the rounded size."""
    h, w = img.shape[:2]
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA), (size[0] / w, size[1] / h)


def unresize(p, sx, sy):
    """Pixel positions in an image resized by (sx, sy) -> positions in the original."""
    p = np.asarray(p, float)
    return (p + 0.5) / [sx, sy] - 0.5



def load_gray(path):
    """Any 8/16-bit mono or colour image -> float32 luminance, plus the raw array."""
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f'cannot read image: {path}')
    g = raw
    if g.ndim == 3:
        g = cv2.cvtColor(g[..., :3], cv2.COLOR_BGR2GRAY)
    return g.astype(np.float32), raw


# ---------------------------------------------------------------- limb
def _circle3(p):
    (x1, y1), (x2, y2), (x3, y3) = p[:, 0].T, p[:, 1].T, p[:, 2].T
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    d = np.where(np.abs(d) < 1e-9, np.nan, d)
    s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return cx, cy, np.hypot(x1 - cx, y1 - cy)


def fit_limb(gray, tol=1.5):
    """Circle through the sunlit limb. RANSAC: many contour points ON the circle and almost none
    OUTSIDE it (the terminator always lies inside the true limb, so it cannot win)."""
    g = cv2.GaussianBlur(gray, (0, 0), 1.5)
    lo, top = np.percentile(g, [2, 99.5])
    if not top > lo + 1e-3 * max(abs(top), 1.0):
        raise SystemExit('no Moon found in the image (it has no contrast)')
    # sunlit level from the pixels well above the sky, not from a fixed share of the frame:
    # a thin crescent in faint sky would otherwise take its "bright" level from the sky
    hi = np.percentile(g[g > lo + 0.5 * (top - lo)], 20)
    m = (g > lo + 0.4 * (hi - lo)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        raise SystemExit('no Moon found in the image')
    m = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = max(cnts, key=len)[:, 0, :].astype(np.float64)
    h, w = gray.shape
    pts = pts[(pts[:, 0] > 2) & (pts[:, 0] < w - 3) & (pts[:, 1] > 2) & (pts[:, 1] < h - 3)]
    if len(pts) < 20:
        raise SystemExit('could not find the limb (is the whole Moon, or a large part of its edge, in the image?)')
    rng = np.random.default_rng(1)
    cx, cy, R = _circle3(pts[rng.integers(0, len(pts), (3000, 3))])
    good = np.isfinite(R) & (R > 0.03 * max(h, w)) & (R < 1.5 * max(h, w))      # a small Moon in a wide frame too
    cx, cy, R = cx[good], cy[good], R[good]
    best, bs = None, -1e9
    for c0 in range(0, len(R), 500):
        sl = slice(c0, c0 + 500)
        d = np.hypot(pts[None, :, 0] - cx[sl, None], pts[None, :, 1] - cy[sl, None]) - R[sl, None]
        score = (np.abs(d) < tol).sum(1) - 4 * (d > 3 * tol).sum(1)
        i = int(np.argmax(score))
        if score[i] > bs:
            bs, best = score[i], (cx[sl][i], cy[sl][i], R[sl][i])
    if best is None:
        raise SystemExit('could not find the limb (is the whole Moon, or a large part of its edge, in the image?)')
    cx, cy, R = best
    for _ in range(5):
        d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - R
        k = np.abs(d) < tol * 2
        x, y = pts[k, 0], pts[k, 1]
        sol = np.linalg.lstsq(np.stack([x, y, np.ones_like(x)], 1), x * x + y * y, rcond=None)[0]
        cx, cy = sol[0] / 2, sol[1] / 2
        R = math.sqrt(sol[2] + cx * cx + cy * cy)
    d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - R
    return cx, cy, R, float((np.abs(d) < 2 * tol).mean())


# ---------------------------------------------------------------- matching
def _highpass(im, s):
    im = im.astype(np.float32)
    return im - cv2.GaussianBlur(im, (0, 0), s)


def _ncc(x, y):
    x = x - x.mean(); y = y - y.mean()
    return float((x * y).sum() / math.sqrt((x * x).sum() * (y * y).sum() + 1e-12))


def coarse_pose(img_small, disk_mask, ref, cx, cy, R, verify=None, n_peaks=10):
    """North angle + mirror by brute force, then (angle, libration) by coordinate descent, on
    local-contrast images of the sunlit part (maria dominate; the phase shading is removed).

    On a crescent the brute-force score has several peaks of similar height and the highest is often
    wrong (measured on a set of downloaded crescent photos: the right pose was the 1st to 6th peak). With verify(pose)
    -> number of consistent terrain matches, the peaks are refined and verified in score order; the
    first with a clear result wins, otherwise the one with the most matches."""
    h, w = img_small.shape
    sm = cv2.GaussianBlur(img_small, (0, 0), R / 60)
    lit = sm > np.percentile(sm[disk_mask], 95) * 0.3
    mask = disk_mask & cv2.erode(lit.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

    def local_contrast(x, m):
        x = np.where(m, x, 0).astype(np.float32)
        wsum = cv2.GaussianBlur(m.astype(np.float32), (0, 0), R / 6) + 1e-6
        return x / (cv2.GaussianBlur(x, (0, 0), R / 6) / wsum + 1e-6)

    a = local_contrast(sm, mask)

    def score(th, mirror, lat0, lon0):
        A, t = similarity(cx, cy, R, th, mirror)
        rr, ok = ref.render(Geometry(lat0, lon0, A, t), w, h)
        m = ok & mask
        if m.sum() < 500:
            return -1.0
        return _ncc(a[m], local_contrast(cv2.GaussianBlur(rr, (0, 0), R / 60), m)[m])

    angles = range(0, 360, 3)
    grid = {mi: [score(th, mi, 0, 0) for th in angles] for mi in (False, True)}
    peaks = sorted(((s[i], angles[i], mi) for mi, s in grid.items() for i in range(len(s))
                    if s[i] >= s[i - 1] and s[i] >= s[(i + 1) % len(s)]), reverse=True)

    def refine(th, mi):
        lat0 = lon0 = 0.0
        for step in (2.0, 1.0, 0.5, 0.25):
            for _ in range(6):
                best = (score(th, mi, lat0, lon0), th, lat0, lon0)
                for d in (-step, step):
                    for c in ((th + d, lat0, lon0), (th, lat0 + d, lon0), (th, lat0, lon0 + d)):
                        if abs(c[1]) <= 10 and abs(c[2]) <= 10:
                            sc = score(c[0], mi, c[1], c[2])
                            if sc > best[0]:
                                best = (sc, *c)
                if best[1:] == (th, lat0, lon0):
                    break
                _, th, lat0, lon0 = best
        return dict(score=score(th, mi, lat0, lon0), theta=th % 360, mirror=mi, lat0=lat0, lon0=lon0)

    tried = []
    for _, th, mi in peaks[:n_peaks if verify else 1]:
        o = refine(th, mi)
        o['verified'] = verify(o) if verify else None
        tried.append(o)
        if verify is None or o['verified'] >= 40:
            break
    o = max(tried, key=lambda c: (c['verified'] or 0, c['score']))
    o['other_mirror'] = max(grid[not o['mirror']])
    o['tried'] = len(tried)
    return o


def usable_centres(img, ok, geo, patch, search, step, target=300):
    """Patch centres on the sunlit, reference-covered disk (r < 0.88), on a grid whose step shrinks
    (down to patch / 2) until about `target` centres fit: a crescent holds a tenth of a full disk's
    patches on the full-disk grid (measured: 11 at a 4096 px disk), too few to fit the pose."""
    h, w = img.shape
    half, S = patch // 2, search
    k = 2 * (half + S) + 1
    okw = cv2.erode(ok.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    sm = cv2.blur(img.astype(np.float32), (patch, patch))
    lo, hi = np.percentile(sm[ok], [5, 99]) if ok.any() else (0.0, 1.0)
    lit = sm > lo + 0.1 * (hi - lo)

    def grid(st):
        ys, xs = np.mgrid[half + S:h - half - S:st, half + S:w - half - S:st]
        ys, xs = ys.ravel(), xs.ravel()
        sx, sy = geo.to_sky(xs.astype(float), ys.astype(float))
        keep = (np.hypot(sx, sy) <= 0.88) & okw[ys, xs]
        return xs[keep], ys[keep], lit[ys[keep], xs[keep]]

    # the sunlit test only sets the step: dim terrain near the terminator still matches (on the 25 Sep mosaic
    # 47 of 611 matches lie where this test calls it unlit)
    xs, ys, sun = grid(step)
    fine = max(8, half)
    if sun.sum() < target and step > fine:
        n_fine = grid(fine)[2].sum()
        st = int(np.clip(math.sqrt(n_fine / target) * fine, fine, step))
        if st < step:
            xs, ys, _ = grid(st)
    return xs, ys


def match_patches(img, rr, ok, geo, patch, search, step):
    """NCC patch matching image -> rendered reference: image xy <-> lat/lon pairs."""
    a, b = _highpass(img, patch / 4), _highpass(rr, patch / 4)
    half, S = patch // 2, search
    pts, lls, scores = [], [], []
    for xc, yc in zip(*usable_centres(img, ok, geo, patch, search, step)):
        xc, yc = int(xc), int(yc)
        tpl = a[yc - half:yc + half, xc - half:xc + half]
        if tpl.std() < 1e-3:
            continue
        res = cv2.matchTemplate(b[yc - half - S:yc + half + S, xc - half - S:xc + half + S], tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, (px, py) = cv2.minMaxLoc(res)
        if mx < 0.45 or px in (0, res.shape[1] - 1) or py in (0, res.shape[0] - 1):
            continue
        r2 = res.copy(); r2[max(0, py - 3):py + 4, max(0, px - 3):px + 4] = -1
        if r2.max() > mx - 0.08:                      # ambiguous: repeated texture
            continue
        dx = 0.5 * (res[py, px - 1] - res[py, px + 1]) / (res[py, px - 1] - 2 * mx + res[py, px + 1])
        dy = 0.5 * (res[py - 1, px] - res[py + 1, px]) / (res[py - 1, px] - 2 * mx + res[py + 1, px])
        lat, lon, _ = geo.to_latlon(xc + px + dx - S, yc + py + dy - S)
        pts.append((xc, yc)); lls.append((float(lat), float(lon))); scores.append(mx)
    return np.array(pts, float).reshape(-1, 2), np.array(lls, float).reshape(-1, 2), np.array(scores)


def estimate_sun(img_small, geo):
    """Subsolar point (lat 0, lon) that best explains which part of the disk is sunlit, for a given pose."""
    h, w = img_small.shape
    ys, xs = np.mgrid[0:h:2, 0:w:2].astype(np.float64)
    lat, lon, ok = geo.to_latlon(xs, ys)
    sx, sy = geo.to_sky(xs, ys)
    k = ok & (np.hypot(sx, sy) < 0.95)
    if k.sum() < 200:
        return None
    g = img_small[::2, ::2][k]
    lo, hi = np.percentile(img_small, 2), np.percentile(g, 99)
    lit = g > lo + 0.25 * (hi - lo)
    p = unit(lat[k], lon[k])
    best = None
    for step, span, c in ((4.0, 180.0, 0.0), (0.5, 4.0, None)):
        c = c if c is not None else best[1]
        for sl in np.arange(c - span, c + span + 1e-9, step):
            pred = p @ unit(0.0, sl) > 0
            sc = float((pred == lit).mean())
            if best is None or sc > best[0]:
                best = (sc, float(sl))
    return (0.0, ((best[1] + 180) % 360) - 180)


def fit_global(pts, lls, init):
    """Libration by Gauss-Newton with the affine solved linearly inside; robust 3-sigma trimming."""
    keep = np.ones(len(pts), bool)

    def solve(lat0, lon0, k):
        xs, ys, _ = latlon_to_sky(lls[k, 0], lls[k, 1], lat0, lon0)
        sol = np.linalg.lstsq(np.stack([xs, ys, np.ones_like(xs)], 1), pts[k], rcond=None)[0]
        A, t = sol[:2].T, sol[2]
        return A, t, pts[k] - (np.stack([xs, ys], 1) @ A.T + t)

    p = np.array([init.lat0, init.lon0])
    for _ in range(4):
        for _ in range(30):
            A, t, r = solve(p[0], p[1], keep)
            f0 = r.ravel()
            J = np.stack([(solve(*(p + dp), keep)[2].ravel() - f0) / 1e-3 for dp in (np.array([1e-3, 0]), np.array([0, 1e-3]))], 1)
            step = np.linalg.lstsq(J, -f0, rcond=None)[0]
            p = p + step
            if np.abs(step).max() < 1e-5:
                break
        A, t, _ = solve(p[0], p[1], keep)
        g = Geometry(p[0], p[1], A, t)
        x, y, _ = g.to_image(lls[:, 0], lls[:, 1])
        res = np.hypot(x - pts[:, 0], y - pts[:, 1])
        keep = res < max(3 * 1.4826 * np.median(res[keep]), 0.5)
    return g, res, keep


def fit_correction(geo, pts, lls, max_deg=4):
    """Smooth residual field; degree chosen by 5-fold cross-validation (0 = none)."""
    x, y, _ = geo.to_image(lls[:, 0], lls[:, 1])
    r = pts - np.stack([x, y], 1)
    sx, sy, _ = latlon_to_sky(lls[:, 0], lls[:, 1], geo.lat0, geo.lon0, geo.dist)
    # a partial disk (a crescent) gets at most a linear correction, chosen on angular-sector folds: nothing can check
    # it on the unlit side, where a cubic or quartic fitted on the crescent alone ran up to 1000 px wrong. A full disk
    # is interpolated everywhere, so interleaved folds measure what matters there
    sector = (np.floor((np.arctan2(sy, sx) + np.pi) / (2 * np.pi) * 16).astype(int)) % 16
    partial = (np.bincount(sector, minlength=16) >= 3).mean() < 0.75
    if partial:
        max_deg = min(max_deg, 1)
    fold = sector % 5 if partial else np.arange(len(pts)) % 5
    best = (math.sqrt((r ** 2).sum(1).mean()), 0)
    for deg in range(1, max_deg + 1):
        M = poly_terms(sx, sy, deg)
        if len(pts) < 4 * M.shape[1]:
            break
        err = []
        for f in range(5):
            tr, te = fold != f, fold == f
            c = np.linalg.lstsq(M[tr], r[tr], rcond=None)[0]
            err.append(((r[te] - M[te] @ c) ** 2).sum(1))
        cv = math.sqrt(np.concatenate(err).mean())
        if cv < best[0] * 0.97:
            best = (cv, deg)
    deg = best[1]
    rmax = float(np.percentile(np.hypot(sx, sy), 99)) if len(sx) else 0.9
    if deg == 0:
        return Geometry(geo.lat0, geo.lon0, geo.A, geo.t, None, 0, rmax), best[0]
    c = np.linalg.lstsq(poly_terms(sx, sy, deg), r, rcond=None)[0]
    return Geometry(geo.lat0, geo.lon0, geo.A, geo.t, c, deg, rmax), best[0]


# ---------------------------------------------------------------- pipeline
def locate(path, log=print, when=None):
    """Full-disk or partial-phase image (a path, or a grey array) -> (Geometry, quality dict). when (UTC datetime):
    the terrain is then matched against LOLA relief lit by the real Sun (times the albedo), which also covers the
    polar regions beyond the albedo map's ±60° and the terminator shadows of crescents."""
    t0 = time.perf_counter()
    reliefs, sun_fixed = {}, None
    try:
        from atlas_closeup import Relief, lola_path, render_shaded
        if when is not None:
            from atlas_ephem import ephemeris
            e = ephemeris(when)
            sun_fixed = (e['sub_sun_lat'], e['sub_sun_lon'])
        have_relief = bool(lola_path(16, log))
    except (ImportError, OSError, SystemExit) as ex:            # offline: the albedo map alone, as before
        if not isinstance(ex, ImportError):
            log(f'no LOLA relief ({ex}): matching against the albedo map only')
        have_relief = False

    def shaded(g, w, h, sun, ppd):
        if ppd not in reliefs:
            reliefs[ppd] = Relief(ppd if os.path.exists(os.path.join(DATA, 'lola', f'ldem_{ppd}.img')) else 16, log)
        rr, ok = render_shaded(g, w, h, reliefs[ppd], ref, sun)
        return rr * 255, ok
    gray = np.asarray(path, np.float32) if isinstance(path, np.ndarray) else load_gray(path)[0]
    H, W = gray.shape
    ref = Reference(log)
    g0, (s0x, s0y) = resize(gray, 1024.0 / max(W, H))
    s0 = math.sqrt(s0x * s0y)
    cx, cy, R, limb_share = fit_limb(g0)
    (cx0, cy0), R0 = unresize((cx, cy), s0x, s0y), R / s0
    log(f'limb: centre {cx0:.0f} {cy0:.0f} px, radius {R0:.0f} px')

    g1, (s1x, s1y) = resize(g0, 384.0 / (2 * R))
    (c1x, c1y), R1 = ((cx + 0.5) * s1x - 0.5, (cy + 0.5) * s1y - 0.5), R * math.sqrt(s1x * s1y)
    yy, xx = np.mgrid[0:g1.shape[0], 0:g1.shape[1]]
    disk = np.hypot(xx - c1x, yy - c1y) < 0.9 * R1

    native = 2 * R0
    diams = [d for d in (1024, 2048) if d < 0.8 * native] + [min(4096, native)]
    plan = {1024: (64, 24, 40), 2048: (64, 12, 72)}
    scaled = {}

    def stage(diam, geo, search=None, sun=None):
        # small disks (< 1024 px) need small patches, or a thin crescent holds none (measured: 384 px disk ≤ 0.25 px error)
        # patches scale with the disk below 3072 px (fixed 96 px patches found 67 matches on a 1100 px disk, 970 at
        # 1000 px with 32 px patches); larger disks keep the measured plan
        p = int(np.clip(round(diam / 32 / 8) * 8, 32, 96))
        patch, srch, step = plan.get(diam, (p, 8, max(24, p * 3 // 4)) if diam < 3072 else (96, 8, 128 if diam >= 4000 else 96))
        s = diam / native
        if diam not in scaled:
            scaled[diam] = (gray, (1.0, 1.0)) if s >= 0.999 else resize(gray, s)
        gi, (sx, sy) = scaled[diam]
        gs = geo.resized(sx, sy)
        if sun is not None:                  # LOLA relief lit by the Sun (times the albedo): shadows match too
            rr, ok = shaded(gs, gi.shape[1], gi.shape[0], sun, 16 if diam <= 1024 else 64)
        else:
            rr, ok = ref.render(gs, gi.shape[1], gi.shape[0])
        P, L, _ = match_patches(gi, rr, ok, gs, patch, search or srch, step)
        return P, L, gs, sx, sy

    def verify(o):
        A, t = similarity(cx0, cy0, R0, o['theta'], o['mirror'])
        g = Geometry(o['lat0'], o['lon0'], A, t)
        srch = max(8, plan.get(diams[0], (0, 24))[1])
        P, L, gs, _, _ = stage(diams[0], g, search=srch)
        n = int(fit_global(P, L, gs)[2].sum()) if len(P) >= 6 else 0
        o['sun'] = sun_fixed
        if have_relief:
            # the same pose against the lit relief: the Sun from the capture time, or from where this pose puts
            # the image's sunlit area (the terminator); a crescent is mostly shadow, which the albedo map lacks
            sun = sun_fixed or estimate_sun(g1, Geometry(o['lat0'], o['lon0'], *similarity(c1x, c1y, R1, o['theta'], o['mirror'])))
            P2, L2, gs2, _, _ = stage(diams[0], g, search=srch, sun=sun) if sun else ([], [], None, 0, 0)
            n2 = int(fit_global(P2, L2, gs2)[2].sum()) if len(P2) >= 6 else 0
            if n2 > n:
                n, o['sun'] = n2, sun
        return n

    o = coarse_pose(g1, disk, ref, c1x, c1y, R1, verify=verify)
    log(f'orientation: north {o["theta"]:.1f}°, {"mirrored" if o["mirror"] else "not mirrored"} '
        f'(match {o["score"]:.2f} vs {o["other_mirror"]:.2f} mirrored the other way; '
        f'{o["verified"]} terrain matches, pose {o["tried"]} of the candidates)')
    A, t = similarity(cx0, cy0, R0, o['theta'], o['mirror'])
    geo = Geometry(o['lat0'], o['lon0'], A, t)

    best = None
    sun = o.get('sun')
    if sun is not None:
        log(f"  reference: LOLA relief lit from the subsolar point {sun[0]:+.1f}° {sun[1]:+.1f}°"
            f" ({'capture time' if sun_fixed else 'from the terminator'})")
    for diam in diams:
        s = diam / native
        P, L, gs, sx, sy = stage(diam, geo, sun=sun)
        gfit, res, keep = fit_global(P, L, gs) if len(P) >= 6 else (None, None, np.zeros(len(P), bool))
        n = int(keep.sum())
        # a finer stage with far fewer matches than the one before is less reliable than that one: on a crescent the
        # full-resolution terrain is mostly terminator shadow, which the albedo reference does not show
        if n < 12 or (best and n < 0.5 * best[0]):
            if best is None:
                raise SystemExit(f'too few terrain matches ({n}) — is this a lunar image with enough of the disk?')
            log(f'  disk {diam:.0f} px: only {n} matches; keeping the {best[1]:.0f} px result')
            break
        geo = gfit.resized(1 / sx, 1 / sy)
        rms = math.sqrt((res[keep] ** 2).mean()) / s
        log(f'  disk {diam:.0f} px: {n} matches, {rms:.2f} px rms (full res), '
            f'libration {geo.lat0:+.2f}° {geo.lon0:+.2f}°')
        best = (n, diam, geo, unresize(P[keep], sx, sy), L[keep])
    _, _, geo, P, L = best
    geo, cv_rms = fit_correction(geo, P, L)
    x, y, _ = geo.to_image(L[:, 0], L[:, 1])
    rms = float(math.sqrt(((P - np.stack([x, y], 1)) ** 2).sum(1).mean()))
    q = dict(matches=int(len(P)), rms_px=round(rms, 2), cv_rms_px=round(cv_rms, 2), correction_degree=geo.deg,
             orientation_score=round(o['score'], 3), other_mirror_score=round(o['other_mirror'], 3),
             orientation_candidates=o['tried'],
             limb_radius_px=round(R / s0, 1), seconds=round(time.perf_counter() - t0, 1), width=W, height=H)
    log(f'result: {q["matches"]} matches, {rms:.2f} px rms ({rms * geo.km_per_px:.2f} km), '
        f'correction degree {geo.deg}, {q["seconds"]} s')
    return geo, q


def north_up_matrix(geo):
    """2 × 2 map of image px that turns lunar north (at the disk centre) straight up and east to the right: the IAU
    view, never mirrored. Returns (M, rotation in degrees counter-clockwise on screen, whether it mirrors)."""
    n = geo.A @ np.array([0.0, 1.0])                        # north on the image (y down)
    rot = (-math.pi / 2 - math.atan2(n[1], n[0]) + math.pi) % (2 * math.pi) - math.pi     # the short way round
    R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    mirror = bool((R @ geo.A @ np.array([1.0, 0.0]))[0] < 0)
    M = (np.diag([-1.0, 1.0]) if mirror else np.eye(2)) @ R
    return M, math.degrees(rot), mirror


def north_up(raw, geo):
    """(the image turned so lunar north is up and east right, never mirrored; its geometry; the map of the old pixel
    positions onto the new ones as (M, b): new = M @ old + b). The canvas grows to hold the turned picture: the corners
    of a turn by other than a right angle are black."""
    M, _, _ = north_up_matrix(geo)
    h, w = raw.shape[:2]
    corners = np.array([[-0.5, -0.5], [w - 0.5, -0.5], [w - 0.5, h - 0.5], [-0.5, h - 0.5]]) @ M.T
    lo, hi = corners.min(0), corners.max(0)
    b = -0.5 - lo
    nw, nh = int(math.ceil(hi[0] - lo[0] - 1e-6)), int(math.ceil(hi[1] - lo[1] - 1e-6))
    turned = cv2.warpAffine(raw, np.hstack([M, b[:, None]]), (nw, nh), flags=cv2.INTER_LANCZOS4,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    new = Geometry(geo.lat0, geo.lon0, M @ geo.A, M @ geo.t + b, None if geo.coef is None else geo.coef @ M.T,
                   geo.deg, geo.rmax, geo.dist)
    return turned, new, (M, b)


# ---------------------------------------------------------------- sidecar
def sidecar_path(image):
    return os.path.splitext(image)[0] + '.atlas.json'


def image_signature(image):
    st = os.stat(image)
    return dict(size_bytes=st.st_size, mtime=round(st.st_mtime, 3))


def save_geo(image, geo, quality, width, height, **extra):
    p = sidecar_path(image)
    d = {}
    if os.path.exists(p):              # keep whatever else was stored next to the geometry
        try:
            with open(p) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
    d.update(schema=SIDECAR_SCHEMA, image=os.path.basename(image), image_signature=image_signature(image),
             width=width, height=height, geometry=geo.as_dict(), quality=quality,
             derived=dict(radius_px=round(geo.radius_px, 1), km_per_px=round(geo.km_per_px, 4),
                          north_angle_deg=round(geo.north_angle, 2), mirrored=bool(geo.mirrored),
                          libration_lat=round(geo.lat0, 3), libration_lon=round(geo.lon0, 3)),
             located=time.strftime('%Y-%m-%d %H:%M:%S'), **extra)
    write_json_atomic(p, d, indent=1)
    return p


def write_json_atomic(path, data, **kw):
    def write(tmp):
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, **kw)
    write_atomic(path, write)


def load_geo(image):
    """(Geometry, sidecar dict). The geometry is None when the sidecar is missing, damaged, of an unknown
    schema or made for a different version of the image; the dict's 'problem' then says which."""
    p = sidecar_path(image)
    if not os.path.exists(p):
        return None, None
    try:
        with open(p) as fh:
            d = json.load(fh)
    except (OSError, ValueError) as e:
        return None, dict(problem=f'{os.path.basename(p)} is damaged ({e.__class__.__name__})')
    if not isinstance(d, dict):
        return None, dict(problem=f'{os.path.basename(p)} is damaged (not a JSON object)')
    if d.get('schema') != SIDECAR_SCHEMA and d.get('schema') not in OLD_SCHEMAS:
        return None, dict(d, problem=f"{os.path.basename(p)} has unsupported schema {d.get('schema')!r}")
    try:
        sig = image_signature(image)
    except OSError:
        return None, dict(d, problem=f'{os.path.basename(image)} is missing (its sidecar is still here)')
    if d.get('image_signature') != sig:
        return None, dict(d, problem='image changed since it was located')
    try:
        return Geometry.from_dict(d['geometry']), d
    except (KeyError, TypeError, ValueError) as e:
        return None, dict(d, problem=f'{os.path.basename(p)}: {e}')
