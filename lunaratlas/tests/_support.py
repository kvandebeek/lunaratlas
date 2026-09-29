"""Shared helpers for the lunaratlas tests (stdlib unittest, no extra packages).

    python3 -m unittest discover -s lunaratlas/tests -t lunaratlas/tests            # the whole suite
    python3 -m unittest discover -s lunaratlas/tests -t lunaratlas/tests -p 'test_e2e*'   # one kind
    LUNARATLAS_SLOW_TESTS=1 ...          also the slow tests (close-up search, mirrored and crescent locate)
    LUNARATLAS_PERF_FACTOR=3 ...         a slower machine: every performance budget × 3
    LUNARATLAS_UI_OUT=DIR ...            keep test_ui's screenshots of failed checks in DIR
    LUNARATLAS_BROWSER=firefox ...       test_ui in chrome (default), edge, firefox or safari
    LUNARATLAS_JS_COVERAGE=DIR ...       record what the UI journeys ran of the pages; node tests/ui/js_coverage.mjs DIR

What the tests guarantee about this machine:
  - built-in setting defaults only: the .env of the repository never changes a result (subprocesses get explicit
    options instead);
  - no network: urllib may only reach 127.0.0.1 / localhost, so nothing is ever downloaded;
  - the tile cache is written under a temporary HOME, never into ~/Library/Caches;
  - reference data (LROC albedo, LOLA, IAU list, fonts) is read from lunaratlas/data; a test that needs a file
    that is not there is skipped, never downloaded.

The suite is split by what it is about, so one kind can be run on its own:

    test_e2e.py, test_e2e_journeys.py   the real command line, the viewer's server, the real page in a browser
    test_ui.py                          the pages worked by mouse and keyboard from outside (tests/ui/journeys.mjs)
    test_platforms.py                   every platform's folders, file manager and start-up, on any one machine
    test_functional_*.py                the pieces, each against what it must produce
    test_reliability*.py                what happens when the disk, the sidecar, the network or a client misbehaves
    test_performance.py                 a time and memory budget for every step
    test_stability.py                   the same input always gives the same output; the viewer under load
    test_compatibility.py               formats, platforms, older sidecars, the settings documentation

The test images are synthetic: LOLA relief lit by a chosen Sun, times the LROC albedo, seen in a known geometry, with
blur and noise. Positioning them must give that geometry back.
"""
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(PKG)
for p in (ROOT, PKG):
    if p not in sys.path:
        sys.path.insert(0, p)

import tool_settings as ts  # noqa: E402

ts._raw = {}                  # built-in defaults only (before any module reads a setting at import time)

_real_urlopen = urllib.request.urlopen


def _local_only(url, *a, **k):
    u = url.full_url if isinstance(url, urllib.request.Request) else url
    if urllib.parse.urlsplit(u).hostname not in ('127.0.0.1', 'localhost'):
        raise OSError(f'network access is disabled in the tests: {u}')
    return _real_urlopen(url, *a, **k)


urllib.request.urlopen = _local_only

import cv2  # noqa: E402
import numpy as np  # noqa: E402

try:                          # libtiff notes about the 4-channel test images are not test output
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:
    pass

DATA = os.path.join(PKG, 'data')
CLI = os.path.join(PKG, 'lunaratlas.py')
SLOW = os.environ.get('LUNARATLAS_SLOW_TESTS', '') not in ('', '0')
PERF = float(os.environ.get('LUNARATLAS_PERF_FACTOR', '1') or 1)


def quiet(*a, **k):
    pass


# ---------------------------------------------------------------- what the machine has
def have(*rel):
    return os.path.exists(os.path.join(DATA, *rel))


HAVE_REFERENCE = have('wac_emp_643_nearside.png') or all(
    have('wac_emp_643', f'WAC_EMP_643NM_{t}_064P.TIF') for t in ('E300N3150', 'E300N0450', 'E300S3150', 'E300S0450'))
HAVE_RELIEF16 = have('lola', 'ldem_16.img')
HAVE_RELIEF64 = have('lola', 'ldem_64.img')
HAVE_FEATURES = have('iau', 'features.json') or have('iau', 'MOON_nomenclature_center_pts.dbf')
ROBOTO = os.path.join(PKG, 'fonts', 'roboto')      # bundled with the app, so always here
HAVE_ROBOTO = os.path.isdir(ROBOTO) and any(f.endswith('.ttf') for f in os.listdir(ROBOTO))

needs_reference = unittest.skipUnless(HAVE_REFERENCE, 'LROC WAC reference not in lunaratlas/data')
needs_relief = unittest.skipUnless(HAVE_REFERENCE and HAVE_RELIEF16, 'LOLA 16 px/deg relief not in lunaratlas/data')
needs_features = unittest.skipUnless(HAVE_FEATURES, 'IAU nomenclature not in lunaratlas/data')
needs_font = unittest.skipUnless(HAVE_ROBOTO, 'Roboto not in lunaratlas/fonts')
needs_all = unittest.skipUnless(HAVE_REFERENCE and HAVE_RELIEF16 and HAVE_FEATURES and HAVE_ROBOTO,
                                'reference data (albedo, LOLA 16, IAU list, Roboto) not in lunaratlas/data')
slow = unittest.skipUnless(SLOW, 'slow test: set LUNARATLAS_SLOW_TESTS=1')


def budget(seconds):
    return seconds * PERF


# ---------------------------------------------------------------- synthetic lunar images
_cache = {}


def reference():
    if 'ref' not in _cache:
        from atlas_geo import Reference
        _cache['ref'] = Reference(quiet)
    return _cache['ref']


def relief16():
    if 'rel' not in _cache:
        from atlas_closeup import Relief
        _cache['rel'] = Relief(16)
    return _cache['rel']


# the default test Moon: a gibbous disk, north 37° clockwise from up, libration +3.2° / −4.1°
DISK = dict(W=1100, H=1000, cx=560.0, cy=490.0, R=450.0, theta=37.0, mirror=False, lat0=3.2, lon0=-4.1,
            sun=(0.0, 35.0))


def truth_geometry(**kw):
    from atlas_geo import Geometry, similarity
    d = dict(DISK, **kw)
    A, t = similarity(d['cx'], d['cy'], d['R'], d['theta'], d['mirror'])
    return Geometry(d['lat0'], d['lon0'], A, t)


def synthetic_moon(blur=0.8, noise=150.0, seed=7, **kw):
    """(float image 0..1 in the requested geometry, the Geometry): LOLA relief lit by the Sun times the albedo."""
    from atlas_closeup import render_shaded
    d = dict(DISK, **kw)
    geo = truth_geometry(**kw)
    img, _ = render_shaded(geo, d['W'], d['H'], relief16(), reference(), d['sun'])
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    img = img / max(float(img.max()), 1e-6)
    if noise:
        img = img + np.random.default_rng(seed).normal(0, noise / 65535, img.shape)
    return np.clip(img * 0.85 + 600 / 65535, 0, 1).astype(np.float32), geo


def encode(img01, dtype=np.uint16, channels=1):
    """0..1 float -> the stored pixels: uint8 / uint16 / float32, mono, BGR (slightly warm) or BGRA."""
    x = img01
    if channels >= 3:
        x = np.stack([x * 0.97, x, x * 1.02], -1)
    if channels == 4:
        x = np.concatenate([x, np.ones(x.shape[:2] + (1,), x.dtype)], -1)
    if dtype == np.uint8:
        return np.clip(x * 255 + 0.5, 0, 255).astype(np.uint8)
    if dtype == np.uint16:
        return np.clip(x * 65535 + 0.5, 0, 65535).astype(np.uint16)
    return x.astype(np.float32)


def write_image(path, img01=None, dtype=np.uint16, channels=1, params=(), **kw):
    """Write a synthetic Moon to path; returns its true Geometry."""
    geo = None
    if img01 is None:
        img01, geo = synthetic_moon(**kw)
    px = encode(img01, dtype, channels)
    if channels == 4 and dtype == np.uint8 and path.lower().endswith('.png'):
        px[..., 3] = 255
    if not cv2.imwrite(path, px, list(params)):
        raise OSError(f'cannot write {path}')
    return geo if geo is not None else truth_geometry(**kw)


GATE_OK = dict(ok=True, forced=False, reasons=[], line='quality OK (test fixture)', measures={}, thresholds='test')


def locate_as(image, geo, gate=None, **extra):
    """A sidecar for image holding geo, as `lunaratlas.py locate` would write it (no locating)."""
    from atlas_geo import save_geo
    raw = cv2.imread(image, cv2.IMREAD_UNCHANGED)
    q = dict(matches=500, rms_px=0.2, cv_rms_px=0.2, correction_degree=geo.deg, seconds=1.0,
             orientation_score=0.9, other_mirror_score=0.2, orientation_candidates=1, limb_radius_px=geo.radius_px)
    q.update(extra.pop('quality', {}))
    return save_geo(image, geo, q, raw.shape[1], raw.shape[0], quality_gate=gate or dict(GATE_OK), **extra)


def moon_image(folder, name='moon.tif', **kw):
    """A synthetic Moon with its sidecar in folder: (path, Geometry)."""
    p = os.path.join(folder, name)
    geo = write_image(p, **kw)
    locate_as(p, geo)
    return p, geo


def sidecar(image):
    from atlas_geo import sidecar_path
    with open(sidecar_path(image), encoding='utf-8') as fh:
        return json.load(fh)


def projected_features(geo):
    """The IAU features (plus landing sites) with x, y, z in geo, as lunaratlas.project does."""
    from atlas_names import load_features
    from lunaratlas import project
    return project([dict(f) for f in load_features(quiet, sites=True)], geo)


# ---------------------------------------------------------------- running the CLI
class TempDir(unittest.TestCase):
    """A test case with its own temporary folder, self.tmp (removed afterwards)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='lunaratlas_test_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        super().setUp()


def run_main(*argv):
    """lunaratlas.main() in this process: (exit message or None, stdout)."""
    import lunaratlas
    out, code = io.StringIO(), None
    old = sys.argv
    sys.argv = ['lunaratlas.py', *map(str, argv)]
    try:
        with contextlib.redirect_stdout(out):
            lunaratlas.main()
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = old
    return code, out.getvalue()


def subprocess_env(home):
    """The environment for a CLI subprocess: its own HOME (tile cache), no browser, unbuffered output."""
    env = dict(os.environ, HOME=home, PYTHONUNBUFFERED='1', LUNARATLAS_VIEW_OPEN='0', LUNARATLAS_SELFTEST='1')
    env.pop('PYTHONPATH', None)
    return env


def run_cli(*argv, home, timeout=300, cwd=None):
    return subprocess.run([sys.executable, CLI, *map(str, argv)], capture_output=True, text=True, timeout=timeout,
                          env=subprocess_env(home), cwd=cwd)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Viewer:
    """`lunaratlas.py view IMAGE --no-open` in a subprocess, until close()."""

    def __init__(self, image, home, port=None, extra=()):
        self.proc = subprocess.Popen([sys.executable, CLI, 'view', image, '--no-open', '--port', str(port or free_port()),
                                      *extra], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     env=subprocess_env(home))
        self.lines, self.url, self.token = [], None, ''
        t0 = time.time()
        while time.time() - t0 < 120:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.lines.append(line.rstrip())
            if 'viewer: http://' in line:
                self.url = line.split('viewer: ', 1)[1].split()[0]
                self.url, _, self.token = self.url.partition('?t=')       # --no-open prints the way in: with the token
                self.url = self.url.rstrip('/')
                break
        if self.url is None:
            self.close()
            raise RuntimeError('viewer did not start:\n' + '\n'.join(self.lines))
        import threading
        threading.Thread(target=self._drain, daemon=True).start()

    @property
    def cookie(self):
        """The Cookie header value of a browser that has entered with the token."""
        return f"la_{self.url.rsplit(':', 1)[1]}={self.token}"

    def _drain(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())

    def request(self, path, data=None, method=None, raw=False, timeout=30, auth=True) -> tuple[int, Any, dict]:
        body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
        hdr = {'Content-Type': 'application/json'} if body is not None else {}
        if auth:
            hdr['X-LA-Token'] = self.token
        req = urllib.request.Request(self.url + path, data=body, method=method or ('POST' if body is not None else 'GET'),
                                     headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (b if raw else _json_or_text(b)), dict(r.headers)
        except urllib.error.HTTPError as e:
            b = e.read()
            return e.code, (b if raw else _json_or_text(b)), dict(e.headers)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)


def _json_or_text(b):
    try:
        return json.loads(b)
    except ValueError:
        return b.decode('utf-8', 'replace')


def find_chrome():
    cands = [os.environ.get('LUNARATLAS_CHROME'),
             '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
             '/Applications/Chromium.app/Contents/MacOS/Chromium',
             shutil.which('google-chrome'), shutil.which('google-chrome-stable'), shutil.which('chromium'),
             shutil.which('chromium-browser'), shutil.which('chrome'),
             r'C:\Program Files\Google\Chrome\Application\chrome.exe']
    return next((c for c in cands if c and os.path.exists(c)), None)


def find_edge():
    cands = [os.environ.get('LUNARATLAS_EDGE'),
             '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
             shutil.which('microsoft-edge'), shutil.which('microsoft-edge-stable'), shutil.which('msedge'),
             r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
             r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']
    return next((c for c in cands if c and os.path.exists(c)), None)


def find_webdriver(name, runner_dir=None):
    """A WebDriver server: LUNARATLAS_WEBDRIVER, the folder a GitHub runner names in runner_dir, or on the PATH."""
    exe = name + ('.exe' if sys.platform == 'win32' else '')
    cands = [os.environ.get('LUNARATLAS_WEBDRIVER'),
             os.path.join(os.environ[runner_dir], exe) if runner_dir and os.environ.get(runner_dir) else None,
             shutil.which(name), '/usr/bin/' + name]
    return next((c for c in cands if c and os.path.exists(c)), None)


# the browser test_ui drives: chrome (the default), edge, firefox or safari
BROWSER = (os.environ.get('LUNARATLAS_BROWSER') or 'chrome').strip().lower()


def ui_browser_env():
    """The environment that makes tests/ui/journeys.mjs drive BROWSER, or None when it is not on this machine.
    Chrome and Edge are driven through the DevTools protocol (cdp.mjs), Firefox and Safari through WebDriver."""
    if BROWSER in ('chrome', 'edge'):
        exe = find_chrome() if BROWSER == 'chrome' else find_edge()
        return exe and dict(LUNARATLAS_BROWSER=BROWSER, LUNARATLAS_CHROME=exe)
    if BROWSER == 'firefox':
        driver = find_webdriver('geckodriver', 'GECKOWEBDRIVER')
    elif BROWSER == 'safari':
        driver = sys.platform == 'darwin' and find_webdriver('safaridriver')
    else:
        raise ValueError(f'LUNARATLAS_BROWSER={BROWSER}: chrome, edge, firefox or safari')
    return driver and dict(LUNARATLAS_BROWSER=BROWSER, LUNARATLAS_WEBDRIVER=driver)


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def pixel_error(geo_a, geo_b, w, h, step=50, r_max=0.9):
    """Median and max distance (px) between where geo_a and geo_b put the same lunar points (on the disk)."""
    ys, xs = np.mgrid[step:h - step:step, step:w - step:step].astype(float)
    sx, sy = geo_a.to_sky(xs, ys)
    keep = np.hypot(sx, sy) < r_max
    la, lo, ok = geo_a.to_latlon(xs[keep], ys[keep])
    x, y, _ = geo_b.to_image(la[ok], lo[ok])
    d = np.hypot(x - xs[keep][ok], y - ys[keep][ok])
    return float(np.median(d)), float(d.max())

