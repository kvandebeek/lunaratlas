"""Shared helpers for the lunaratlas tests (stdlib unittest, no extra packages).

    python3 lunaratlas/tests/run_tests.py                         # the whole suite, with percent complete
    python3 lunaratlas/tests/run_tests.py --pattern 'test_e2e*'   # one kind
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
import atexit
import contextlib
import io
import json
import os
import re
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

# Every in-process test (as opposed to a CLI subprocess, which already gets its own HOME through subprocess_env())
# must never touch the developer's real cache and data folders (~/Library/Caches/LunarAtlas and its Windows/Linux
# equivalents): atlas_paths.user_dir() reads HOME/LOCALAPPDATA/XDG_*_HOME live, so redirecting them here, before any
# atlas_* module is first imported anywhere in the test process, keeps every Session, App, tile pyramid, thumbnail
# and (see atlas_view.handoff_url) hand-off file inside a folder this test run owns and removes with everything
# else in it. This must run before `import tool_settings`, which is the first of this project's own modules any
# test file imports.
if not os.environ.get('_LUNARATLAS_TEST_HOME'):                # set once, even if _support is imported repeatedly
    _test_home = tempfile.mkdtemp(prefix='lunaratlas_test_home_')
    os.environ['_LUNARATLAS_TEST_HOME'] = _test_home
    os.environ['HOME'] = _test_home
    os.environ['LOCALAPPDATA'] = os.path.join(_test_home, 'AppData', 'Local')
    os.environ['XDG_CACHE_HOME'] = os.path.join(_test_home, '.cache')
    os.environ['XDG_DATA_HOME'] = os.path.join(_test_home, '.local', 'share')
    atexit.register(shutil.rmtree, _test_home, True)

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
NODE = shutil.which("node")                       # the self-test runs through it when present (run_selftest)


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
disabled_for_speed = unittest.skip('disabled by request: exceeds runtime target')


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
    # cv2.imwrite(path, ...) opens the path itself, and on Windows that goes through OpenCV's own ANSI-codepage
    # path handling, not Python's: a non-ASCII name (accented, "my moon é.tif") is mojibake'd into a different
    # file, so the test never finds what it just wrote. Encode in memory and let Python's own open() (Unicode-
    # correct on every platform) write the bytes instead.
    ok, buf = cv2.imencode(os.path.splitext(path)[1], px, list(params))
    if not ok:
        raise OSError(f'cannot encode {path}')
    with open(path, 'wb') as fh:
        fh.write(buf.tobytes())
    return geo if geo is not None else truth_geometry(**kw)


GATE_OK = dict(ok=True, forced=False, reasons=[], line='quality OK (test fixture)', measures={}, thresholds='test')


def locate_as(image, geo, gate=None, **extra):
    """A sidecar for image holding geo, as `lunaratlas.py locate` would write it (no locating)."""
    from atlas_geo import save_geo
    from atlas_paths import cv_imread
    raw = cv_imread(image, cv2.IMREAD_UNCHANGED)
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


def cache_dir(home):
    """Where a CLI subprocess given `home` as HOME (see subprocess_env) keeps its tile cache, mirroring
    atlas_paths.user_dir('cache') for the platform this test runs on."""
    if sys.platform == 'darwin':
        return os.path.join(home, 'Library', 'Caches', 'LunarAtlas')
    if sys.platform == 'win32':
        return os.path.join(home, 'AppData', 'Local', 'LunarAtlas', 'Cache')
    return os.path.join(home, '.cache', 'lunaratlas')


def subprocess_env(home):
    """The environment for a CLI subprocess: its own HOME (tile cache), no browser, unbuffered output.
    atlas_paths.user_dir() reads XDG_CACHE_HOME/XDG_DATA_HOME on Linux and LOCALAPPDATA on Windows ahead of HOME,
    so without overriding those too the subprocess's cache would land under the test process's own HOME instead
    of this test's home, and a test asserting the cache lives under `home` would fail on those platforms only.
    PYTHONIOENCODING: a console on a non-UTF-8 locale (Windows with a legacy ANSI code page) would otherwise have
    the child write its own default encoding, which the parent's encoding='utf-8' (see run_cli/Viewer) could not
    decode back correctly."""
    env = dict(os.environ, HOME=home, PYTHONUNBUFFERED='1', LUNARATLAS_VIEW_OPEN='0', LUNARATLAS_SELFTEST='1',
               PYTHONIOENCODING='utf-8',
               LOCALAPPDATA=os.path.join(home, 'AppData', 'Local'),
               XDG_CACHE_HOME=os.path.join(home, '.cache'),
               XDG_DATA_HOME=os.path.join(home, '.local', 'share'))
    env.pop('PYTHONPATH', None)
    return env


def run_cli(*argv, home, timeout=300, cwd=None):
    return subprocess.run([sys.executable, CLI, *map(str, argv)], capture_output=True, text=True, encoding='utf-8',
                          timeout=timeout, env=subprocess_env(home), cwd=cwd)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Viewer:
    """`lunaratlas.py view IMAGE --no-open` in a subprocess, until close()."""

    def __init__(self, image, home, port=None, extra=()):
        self.proc = subprocess.Popen([sys.executable, CLI, 'view', image, '--no-open', '--port', str(port or free_port()),
                                      *extra], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding='utf-8', env=subprocess_env(home))
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
                # 'localhost' resolves to ::1 first on Windows; the server only binds 127.0.0.1, so every request
                # would wait out a ~2s IPv6-connect-refused timeout before falling back (measured: 600 requests in
                # test_sustained_requests this way cost ~20 minutes instead of a few seconds)
                self.url = self.url.rstrip('/').replace('://localhost:', '://127.0.0.1:')
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


def _kill_chrome(proc, profile):
    """Chrome and every helper it started: they keep running (and holding the profile) after the parent dies."""
    if proc.poll() is None:
        try:
            proc.kill()
        except PermissionError:      # a snap-confined Chromium (Ubuntu) refuses the signal; the sweep below still runs
            pass
    if os.name == 'posix':
        subprocess.run(['pkill', '-9', '-f', profile], capture_output=True)
    else:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)


def run_selftest(url, tmp, patience_s):
    """The self-test page run in real time through the DevTools protocol (ui/selftest.mjs): (match, log), like
    dump_selftest, which it replaces where Node is available. A launch that fails to start is tried again."""
    node = shutil.which('node')
    log = ''
    for n in (1, 2, 3):
        d = os.path.join(tmp, f'selftest-{n}')
        os.makedirs(d, exist_ok=True)
        try:
            r = subprocess.run([node, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui', 'selftest.mjs'),
                                find_chrome(), url, d, str(int(patience_s * 1000))],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=patience_s * PERF * 2 + 60)
        except subprocess.TimeoutExpired:
            log += f'[run {n}: timed out]\n'
            continue
        m = re.search(r'<pre id="selftest">(.*?)</pre>', r.stdout, re.S)
        if m:
            return m, log + r.stderr
        log += f'[run {n}: {r.stderr.strip()[:300]}]\n'
        if 'Chrome did not start' not in r.stderr:
            break                                         # the page ran and gave no result: a real failure, not a launch
    return None, log


def dump_selftest(url, tmp, virtual_time_ms, attempts=5):
    """Open `url` (a /selftest page) in headless Chrome with --dump-dom; return (match, log): the regex match of the
    page's <pre id="selftest">...</pre> (None if there was none) and Chrome's own stderr, with a note per launch
    that had to be given up on.

    A launch that works writes its dump within a few seconds on a quiet machine (1.4-2.9 s measured on Windows);
    one that is stuck never writes anything at all, however long it is given -- measured on a Windows 10 PC with
    the same command line: 7 of 10 launches hung (and, with this retry in place and 3 launches, about 40% of
    single launches still did: 8 of 10 runs passed). The same silent-launch signature appears in GitHub's Ubuntu
    and macOS runner logs (GCM / D-Bus / updater noise) and once locally; the cause is Chrome's own startup, not
    this harness or the page. Neither --disable-background-networking nor --host-resolver-rules is the cause or
    the cure (same matrix: hangs with, without, or with either alone). So do not wait out a long budget for
    something that does not come: each launch gets a patience, then is killed and started again on a fresh
    profile. The patience grows with every launch (+50% each), so a healthy but slow runner that needs longer than
    the first one is still not cut off by the later ones -- and the final launch no longer gets 120 s x PERF, which
    is pure waste when stuck. Only silence is retried: a launch that wrote a dump without the result in it is
    returned as the real failure it is. Every abandoned launch, and any slow success, is printed to stderr, so the
    rate of this shows in CI logs instead of hiding behind a pass."""
    base = 10 + 5 * PERF                             # seconds; a good launch needs ~2 on a quiet machine
    notes = []
    for n in range(1, attempts + 1):
        last = n == attempts
        wait_for_it = base * (1 + 0.5 * (n - 1))
        profile = os.path.join(tmp, f'chrome-profile-{n}')
        dom, err = os.path.join(tmp, f'dom-{n}.html'), os.path.join(tmp, f'chrome-{n}.log')
        with open(dom, 'w') as out, open(err, 'w') as log:             # Chrome's helpers keep a pipe open: use files
            # kept from earlier attempts at this: harmless, and they silence a GCM retry loop in the log, but they
            # do NOT stop the hang. EXCLUDE is required: the wildcard MAP matches a literal IP too, so without it
            # our own server (always opened by IP literal) is blackholed as well.
            proc = subprocess.Popen([find_chrome(), '--headless=new', '--disable-gpu', '--use-mock-keychain',
                                     '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                                     '--host-resolver-rules=MAP * 127.0.0.1:1,EXCLUDE 127.0.0.1',
                                     f'--user-data-dir={profile}', '--window-size=1400,900',
                                     '--enable-logging=stderr', '--v=0',                  # the page's console.log lines: where a stuck run stopped
                                     f'--virtual-time-budget={virtual_time_ms}', '--dump-dom', url],
                                    stdout=out, stderr=log)
        try:
            t0, text = time.time(), ''
            while time.time() - t0 < wait_for_it:
                time.sleep(0.2)
                exited = proc.poll() is not None      # BEFORE reading: an exited process's dump is complete when read
                if os.path.exists(dom):
                    with open(dom, encoding='utf-8', errors='replace') as fh:
                        text = fh.read()
                m = re.search(r'<pre id="selftest">(.*?)</pre>', text, re.S)
                if m:
                    took = time.time() - t0
                    if n > 1 or took >= 5:                                # the fast common case stays quiet
                        print(f'[launch {n} of {attempts}: dump after {took:.1f}s]', file=sys.stderr, flush=True)
                    with open(err, errors='replace') as fh:
                        return m, ''.join(notes) + fh.read()
                if exited:
                    break                                                # exited: nothing more is coming
            with open(err, errors='replace') as fh:
                log = fh.read()
            if text.strip() or last:                                      # real failure, or out of attempts
                return None, ''.join(notes) + log
            why = f'exited ({proc.returncode}) without output' if proc.poll() is not None else f'wrote nothing in {wait_for_it:.0f}s'
            progress = ' | '.join(re.findall(r'CONSOLE[^\]]*\]\s*"?(.*?)"?,\s*source:', log)[-8:])    # the page's last words
            notes.append(f'[launch {n} of {attempts}: {why}, retrying with a fresh profile; page progress: {progress!r}; its log: {log[-300:]!r}]\n')
            print(notes[-1].rstrip(), file=sys.stderr, flush=True)       # visible in the run, not only on failure
        finally:
            _kill_chrome(proc, profile)
    return None, ''.join(notes)


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
