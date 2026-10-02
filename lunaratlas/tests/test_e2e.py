"""End-to-end tests: the real command line in a subprocess, the viewer's HTTP server, the browser page itself.

A synthetic Moon of known geometry goes through `locate` (quality gate, limb, orientation, terrain matching), `info`,
`find` and `export`; the viewer serves it, saves edits into the sidecar and runs a real export; headless Chrome runs
tests/viewer_selftest.js on the page. Slow tests (LUNARATLAS_SLOW_TESTS=1) add a blind close-up search and mirrored
and crescent disks.
"""
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone

import _support as S
import cv2
import numpy as np

import atlas_geo as ag
from atlas_paths import cv_imread, cv_imwrite


def check_geometry(test, geo, truth, w, h, px=1.0, deg=0.1):
    test.assertEqual(bool(geo.mirrored), bool(truth.mirrored))
    test.assertLess(S.angle_diff(geo.north_angle, truth.north_angle), deg)
    test.assertAlmostEqual(geo.radius_px / truth.radius_px, 1.0, delta=0.005)
    test.assertAlmostEqual(geo.lat0, truth.lat0, delta=0.5)
    test.assertAlmostEqual(geo.lon0, truth.lon0, delta=0.5)
    med, worst = S.pixel_error(truth, geo, w, h)
    test.assertLess(med, px / 2, f'median {med:.2f} px')
    test.assertLess(worst, px, f'max {worst:.2f} px')


@S.needs_all
class CommandLine(unittest.TestCase):
    """locate -> info -> find -> export, each a separate `python3 lunaratlas.py` process."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='lunaratlas_e2e_')
        cls.home = os.path.join(cls.tmp, 'home')
        os.makedirs(cls.home)
        cls.img = os.path.join(cls.tmp, 'my moon é.tif')              # a space and an accent in the name
        cls.truth = S.write_image(cls.img)
        cls.locate = S.run_cli('locate', cls.img, home=cls.home)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_1_locate_finds_the_true_geometry(self):
        r = self.locate
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('quality OK', r.stdout)
        self.assertIn('saved', r.stdout)
        geo, d = ag.load_geo(self.img)
        self.assertIsNotNone(geo, d)
        check_geometry(self, geo, self.truth, S.DISK['W'], S.DISK['H'], px=0.5, deg=0.1)
        self.assertGreater(d['quality']['matches'], 300)
        self.assertLess(d['quality']['rms_px'], 0.5)
        self.assertTrue(d['quality_gate']['ok'])
        self.assertEqual(d['image'], os.path.basename(self.img))
        self.assertEqual((d['width'], d['height']), (S.DISK['W'], S.DISK['H']))

    def test_2_info(self):
        r = S.run_cli('info', self.img, home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1100 x 1000 px', r.stdout)
        self.assertRegex(r.stdout, r'lunar north is rotated 3[67]\.\d° clockwise from up, not mirrored')
        self.assertRegex(r.stdout, r'terrain matches, 0\.\d+ px rms')

    def test_3_find(self):
        r = S.run_cli('find', self.img, 'Tycho', home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.search(r'image x (-?\d+) px, y (-?\d+) px', r.stdout)
        x, y, _ = self.truth.to_image(-43.3, -11.2)
        self.assertLess(abs(int(m[1]) - float(x)) + abs(int(m[2]) - float(y)), 3)
        self.assertIn('named after', r.stdout)
        r = S.run_cli('find', self.img, 'Nowhere Crater', home=self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no feature named', r.stderr)

    def test_4_export(self):
        r = S.run_cli('export', self.img, home=self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = os.path.join(self.tmp, 'my moon é_atlas.tif')
        im = cv_imread(out, cv2.IMREAD_UNCHANGED)
        self.assertEqual((im.shape, im.dtype), ((1000, 1100, 3), np.uint16))
        for step in ('positioning from', 'view:', 'labels placed', 'labels drawn', 'wrote'):
            self.assertIn(step, r.stdout)              # the viewer's progress bar looks for these
        jpg = os.path.join(self.tmp, 'tycho.jpg')
        r = S.run_cli('export', self.img, '--around', 'Tycho', '--size', '500x400', '-o', jpg, '--quality', '80',
                      home=self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(cv_imread(jpg).shape, (400, 500, 3))

    def test_5_export_errors_are_messages_not_tracebacks(self):
        for args in (('--scale', '2'), ('--format', 'png', '-o', os.path.join(self.tmp, 'x.jpg')),
                     ('--around', 'Hertzsprung'), ('-o', os.path.join(self.tmp, 'missing', 'x.tif'))):
            r = S.run_cli('export', self.img, *args, home=self.home)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertNotIn('Traceback', r.stderr, args)
            self.assertTrue(r.stderr.strip(), args)

    def test_6_help(self):
        r = S.run_cli('export', '-h', home=self.home)
        self.assertEqual(r.returncode, 0)
        for opt in ('--around', '--max-size', '--no-rims', '--layers', '--night', '--force'):
            self.assertIn(opt, r.stdout)

    def test_7_unreadable_image(self):
        bad = os.path.join(self.tmp, 'not an image.tif')
        with open(bad, 'w') as fh:
            fh.write('hello')
        r = S.run_cli('locate', bad, home=self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('cannot read', r.stderr)
        self.assertNotIn('Traceback', r.stderr)


@S.needs_all
class ViewerServer(unittest.TestCase):
    """`lunaratlas.py view` over HTTP, as the page uses it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='lunaratlas_view_')
        cls.home = os.path.join(cls.tmp, 'home')
        os.makedirs(cls.home)
        cls.img, cls.geo = S.moon_image(cls.tmp)
        cls.v = S.Viewer(cls.img, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.assertEqual(self.v.request('/edits', {})[0], 200)            # every test starts without edits

    def test_page_and_assets(self):
        for path, ctype, word in (('/', 'text/html', 'LunarAtlas'), ('/index.html', 'text/html', '<canvas id="map">'),
                                  ('/viewer.js', 'text/javascript', 'window.__atlas'), ('/viewer.css', 'text/css', ':root'),
                                  ('/fonts.css', 'text/css', '@font-face'), ('/selftest', 'text/html', 'selftest.js'),
                                  ('/selftest.js', 'text/javascript', 'PASS')):
            code, body, hdr = self.v.request(path)
            self.assertEqual(code, 200, path)
            self.assertTrue(hdr['Content-Type'].startswith(ctype), path)
            self.assertIn(word, body, path)
            self.assertEqual(hdr['Cache-Control'], 'no-store')

    def test_data_json(self):
        code, body, hdr = self.v.request('/data.json', raw=True)
        self.assertEqual(code, 200)
        self.assertTrue(hdr['Content-Type'].startswith('application/json'))
        d = json.loads(body.decode('utf-8'))
        self.assertNotIn('path', d, 'the page is not told where on the disk the photo is (the account name)')
        self.assertFalse(d['launcher'])
        self.assertEqual((d['width'], d['height']), (1100, 1000))
        self.assertEqual(d['geometry'], self.geo.as_dict())
        self.assertEqual(d['image'], 'moon.tif')
        self.assertGreater(len(d['features']), 1000)
        self.assertIn('quality OK', d['gate'])
        self.assertIn('Roboto', d['fonts'])

    def test_tiles(self):
        code, body, hdr = self.v.request('/data.json', raw=True)
        d = json.loads(body.decode())
        for lvl, L in enumerate(d['levels']):
            for c in range(L['cols']):
                for r in range(L['rows']):
                    code, b, hdr = self.v.request(f'/tiles/{lvl}/{c}_{r}.jpg', raw=True)
                    self.assertEqual(code, 200)
                    self.assertEqual(hdr['Content-Type'], 'image/jpeg')
                    self.assertEqual(hdr['Cache-Control'], 'max-age=86400')
                    t = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
                    self.assertEqual(t.shape[1], min(512, L['w'] - 512 * c))
                    self.assertEqual(t.shape[0], min(512, L['h'] - 512 * r))
        self.assertEqual(self.v.request(f'/tiles/0/{d["levels"][0]["cols"]}_0.jpg')[0], 404)
        tiles = os.path.join(S.cache_dir(self.home), 'tiles')
        self.assertTrue(os.path.isdir(tiles), 'the tile cache is under HOME')
        self.assertEqual(self.v.request(f'/tiles/0/0_0.jpg?v={d["tiles_v"]}')[0], 200)

    def test_tile_urls_are_per_image(self):
        # the page caches tiles for a day by URL: two photos, or one photo changed on disk, must never share them
        # (the app window showed the previous photo's tiles in the next one)
        from atlas_view import tile_version
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, 'a.tif'), os.path.join(d, 'b.tif')
            for p in (a, b):
                with open(p, 'wb') as fh:
                    fh.write(b'same bytes')
                os.utime(p, (1e9, 1e9))
            self.assertNotEqual(tile_version(a), tile_version(b))
            before = tile_version(a)
            self.assertEqual(tile_version(a), before)
            os.utime(a, (2e9, 2e9))
            self.assertNotEqual(tile_version(a), before)

    def test_fonts(self):
        code, css, _ = self.v.request('/fonts.css')
        url = re.search(r"url\('(/fonts/roboto/[^']+)'\)", css)[1]
        code, b, hdr = self.v.request(url.replace('[', '%5B').replace(']', '%5D').replace(',', '%2C'), raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(hdr['Content-Type'], 'font/ttf')
        self.assertGreater(len(b), 10000)

    def test_no_files_outside_the_page(self):
        for path in ('/fonts/../../../../etc/passwd.ttf', '/fonts/..%2F..%2Fquality_thresholds.ttf', '/tiles/../meta.json',
                     '/../lunaratlas.py', '/viewer/../lunaratlas.py', '/moon.atlas.json', '/data/quality_thresholds.json',
                     '/%2e%2e/%2e%2e/etc/passwd'):
            self.assertEqual(self.v.request(path)[0], 404, path)

    def test_edits_round_trip(self):
        cx, cy = (float(v) for v in self.geo.t)
        e = dict(shapes=[dict(kind='circle', cx=cx, cy=cy, r=30, colour='#ffb45a', label='Centre'),
                         dict(kind='measure', a=dict(x=cx - 50, y=cy), b=dict(x=cx + 50, y=cy)),
                         dict(kind='bogus'), dict(kind='circle', cx='x', cy=1, r=1)],
                 hidden=['Tycho'], labels={'Copernicus': dict(dx=5, dy=-3, colour='#ffffff')},
                 style=dict(font='Inter', minPx=30, fs=1.2, night='dim', layers=['crater'], grid=True, rims=False))
        code, saved, _ = self.v.request('/edits', e)
        self.assertEqual(code, 200)
        self.assertEqual(len(saved['shapes']), 2)                          # what cannot be drawn is not saved
        code, got, _ = self.v.request('/edits')
        self.assertIsInstance(got.pop('rev'), int)                # the live revision, not persisted in the sidecar
        self.assertEqual(got, saved)
        d = S.sidecar(self.img)
        self.assertEqual(d['edits'], saved)
        self.assertEqual(ag.Geometry.from_dict(d['geometry']).as_dict(), self.geo.as_dict())   # the geometry is intact

    def test_edits_round_trip_over_a_legacy_sidecar(self):
        """BUG-05 migration, over real HTTP: an image whose only sidecar is the pre-rename shared-stem file is
        still editable, and the save publishes the canonical per-extension sidecar without deleting the old one."""
        import atlas_geo as _ag
        tmp = tempfile.mkdtemp(prefix='lunaratlas_legacy_')
        self.addCleanup(shutil.rmtree, tmp, True)
        img, geo = S.moon_image(tmp)
        canonical, legacy = _ag.sidecar_path(img), os.path.splitext(img)[0] + '.atlas.json'
        os.rename(canonical, legacy)                                  # as a sidecar written before the rename
        self.assertFalse(os.path.exists(canonical))
        v = S.Viewer(img, os.path.join(tmp, 'home'))
        self.addCleanup(v.close)
        code, got, _ = v.request('/edits')
        self.assertEqual(code, 200, got)
        e = dict(shapes=[dict(kind='circle', cx=float(geo.t[0]), cy=float(geo.t[1]), r=20, colour='#ffb45a')],
                 hidden=['Tycho'], labels={}, style={})
        code, saved, _ = v.request('/edits', e)
        self.assertEqual(code, 200, saved)
        self.assertEqual(len(saved['shapes']), 1)
        self.assertTrue(os.path.exists(canonical), 'the save published the canonical sidecar')
        self.assertTrue(os.path.exists(legacy), 'the legacy file is left in place, not deleted')
        with open(canonical, encoding='utf-8') as fh:
            d = json.load(fh)
        self.assertEqual(d['edits']['hidden'], ['Tycho'])
        self.assertEqual(ag.Geometry.from_dict(d['geometry']).as_dict(), geo.as_dict(),
                         'the geometry carried over from the legacy sidecar')

    def _fresh_viewer(self):
        """A session of its own: these tests number revisions explicitly, so they must not share cls.v's sidecar
        with every other test in this class (run in alphabetical order, all against one image)."""
        tmp = tempfile.mkdtemp(prefix='lunaratlas_rev_')
        self.addCleanup(shutil.rmtree, tmp, True)
        img, _ = S.moon_image(tmp)
        v = S.Viewer(img, os.path.join(tmp, 'home'))
        self.addCleanup(v.close)
        return v, img

    def test_overlapping_saves_do_not_race_the_revision_check_and_the_write(self):
        """BUG-04: the old code checked and advanced an in-memory revision under one lock, released it, and
        reacquired a (possibly different) lock to write -- so two overlapping requests could both pass the check.
        Two concrete bodies at two concrete revisions, fired with no ordering guarantee via a thread barrier: the
        higher revision must win, deterministically, and the loser must be told so, never silently dropped or
        silently merged."""
        v, img = self._fresh_viewer()
        gate = threading.Barrier(2, timeout=30)
        out = {}
        def send(key, rev, label):
            gate.wait()
            code, body, _ = v.request('/edits', dict(shapes=[], hidden=[label], labels={}, style={}, rev=rev))
            out[key] = (code, body)
        ts = [threading.Thread(target=send, args=('low', 1000, 'low')),
              threading.Thread(target=send, args=('high', 2000, 'high'))]
        for t in ts: t.start()
        for t in ts: t.join(30)
        self.assertEqual(set(out), {'low', 'high'})
        self.assertEqual(out['high'][0], 200, out['high'])
        d = S.sidecar(img)
        self.assertEqual(d['edits']['hidden'], ['high'], 'the higher revision is the one on disk')
        self.assertEqual(d['edits_rev'], 2000)
        if out['low'][0] != 200:
            self.assertEqual(out['low'][0], 409)
            self.assertEqual(out['low'][1]['rev'], 2000, "the loser is told the revision that beat it")
        else:
            # ran first and committed before 'high' started: also acceptable, but then 'high' must be what is on
            # disk (asserted above) and 'low' must not have clobbered it after the fact
            pass

    def test_a_stale_save_is_rejected_without_touching_the_sidecar(self):
        v, img = self._fresh_viewer()
        code, saved, _ = v.request('/edits', dict(shapes=[], hidden=['first'], labels={}, style={}, rev=500))
        self.assertEqual(code, 200, saved)
        before = S.sidecar(img)
        code, body, _ = v.request('/edits', dict(shapes=[], hidden=['stale'], labels={}, style={}, rev=100))
        self.assertEqual(code, 409, body)
        self.assertEqual(body['rev'], 500)
        after = S.sidecar(img)
        self.assertEqual(after['edits'], before['edits'], 'the rejected write left the sidecar untouched')

    def test_a_retried_save_at_the_same_revision_is_idempotent(self):
        """A response lost in transit (the client never saw the 200) and retried with the same body and the same
        revision must not be treated as a second, different write, and must not be rejected as stale."""
        v, img = self._fresh_viewer()
        body = dict(shapes=[], hidden=['once'], labels={}, style={}, rev=700)
        code1, saved1, _ = v.request('/edits', dict(body))
        code2, saved2, _ = v.request('/edits', dict(body))
        self.assertEqual((code1, code2), (200, 200))
        self.assertEqual(saved1, saved2)
        self.assertEqual(S.sidecar(img)['edits']['hidden'], ['once'])

    def test_bad_requests(self):
        self.assertEqual(self.v.request('/edits', b'{not json')[0], 400)
        self.assertEqual(self.v.request('/edits', [1, 2])[0], 400)
        self.assertEqual(self.v.request('/export', 'a string')[0], 400)
        self.assertEqual(self.v.request('/export', dict(region='view', box=[1, 2, 'x', 4]))[0], 400)
        self.assertEqual(self.v.request('/export', b'{"scale": "max", "max_size": 1e400}')[0], 400)
        self.assertEqual(self.v.request('/nothing', {})[0], 404)
        self.assertEqual(self.v.request('/nothing')[0], 404)
        self.assertEqual(self.v.request('/')[0], 200)                       # still serving

    def test_real_export(self):
        self.v.request('/edits', dict(shapes=[dict(kind='text', x=float(self.geo.t[0]), y=float(self.geo.t[1]),
                                                   label='Hello Moon', colour='#ffffff')]))
        code, j, _ = self.v.request('/export', dict(format='png', scale='half', layers=['area', 'crater'], night='show',
                                                    min_px=30, font_scale=1.1, font='Roboto'))
        self.assertEqual(code, 200, j)
        self.assertTrue(j['started'])
        code, busy, _ = self.v.request('/export', dict(format='png'))
        self.assertEqual(code, 409)                                          # one export at a time
        self.assertIn('already running', busy['error'])
        s = self.wait_export()
        self.assertEqual(s['state'], 'done', s)
        self.assertEqual(s['output'], os.path.join(self.tmp, 'moon_atlas.png'))
        im = cv_imread(s['output'], cv2.IMREAD_UNCHANGED)
        self.assertEqual((im.shape, im.dtype), ((500, 550, 3), np.uint16))
        self.assertEqual(s['size_bytes'], os.path.getsize(s['output']))
        self.assertTrue(any('1 of your drawings' in line for line in s['lines']), s['lines'])

    def test_failed_export_is_reported(self):
        code, j, _ = self.v.request('/export', dict(region='feature', name='Nowhere; rm -rf ~', size=[500, 400]))
        self.assertEqual(code, 200)
        s = self.wait_export()
        self.assertEqual(s['state'], 'failed')
        self.assertIn('no feature named', s['error'])                  # the name is an argument, never a shell command

    def test_export_status_before_any_export(self):
        code, s, _ = self.v.request('/export/status')
        self.assertEqual(code, 200)
        self.assertIn(s['state'], ('none', 'done', 'failed', 'running'))

    def wait_export(self, timeout=120):
        t0 = time.time()
        while time.time() - t0 < S.budget(timeout):
            code, s, _ = self.v.request('/export/status')
            if s['state'] != 'running':
                return s
            time.sleep(0.2)
        self.fail('export did not finish')


@S.needs_all
@unittest.skipUnless(S.find_chrome(), 'no Chrome or Chromium (set LUNARATLAS_CHROME to its executable)')
class BrowserSelfTest(unittest.TestCase):
    """tests/viewer_selftest.js in headless Chrome on the real page: drawing, undo/redo, moving a label, measuring,
    dragging, saving."""

    def test_selftest(self):
        tmp = tempfile.mkdtemp(prefix='lunaratlas_chrome_')
        self.addCleanup(shutil.rmtree, tmp, True)
        home = os.path.join(tmp, 'home')
        os.makedirs(home)
        img, _ = S.moon_image(tmp)
        v = S.Viewer(img, home)
        self.addCleanup(v.close)
        # headless Chrome does not run requestAnimationFrame; the self-test calls render() itself. S.dump_selftest owns
        # the launch (a launch that never writes anything is retried, see there); virtual time in simulated ms:
        # real work behind it (image decode, the gazetteer fetch, label layout) still costs real CPU time, so
        # scale it like every other budget here
        m, log_text = S.dump_selftest(v.url + '/selftest?t=' + v.token, tmp, int(20000 * S.PERF))
        self.assertIsNotNone(m, 'the self-test wrote no result:\n' + log_text[-2000:])
        lines = html.unescape(m[1]).splitlines()
        self.assertGreaterEqual(len(lines), 10, lines)
        failed = [l for l in lines if not l.startswith('PASS')]
        self.assertEqual(failed, [], '\n'.join(lines))
        self.assertEqual(S.sidecar(img)['edits']['shapes'], [])            # the self-test undoes what it did


@S.slow
@unittest.skipUnless(S.HAVE_RELIEF64, 'LOLA 64 px/deg relief not in lunaratlas/data')
@S.needs_all
class CloseUp(unittest.TestCase):
    """A close-up without a limb, found blind from its capture time (SharpCap name) and the folder's optics."""

    @S.disabled_for_speed
    def test_blind_search(self):
        from atlas_closeup import Relief, render_shaded, OPTICS_FILE, TELESCOPE, arcsec_per_px, KM_PER_ARCSEC_PER_KM
        from atlas_ephem import ephemeris
        tmp = tempfile.mkdtemp(prefix='lunaratlas_closeup_')
        self.addCleanup(shutil.rmtree, tmp, True)
        when = datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc)
        name = os.path.join(tmp, '2026-09-23-2138_1-Moon_Filter 4_lapl2_ap5276.tif')
        e = ephemeris(when)
        setup = dict(extender='native', magnification=1.0, camera='IMX678', pixel_um=2.0)
        with open(os.path.join(tmp, OPTICS_FILE), 'w') as fh:
            json.dump(dict(setup, telescope=TELESCOPE[0], focal_mm=TELESCOPE[1], text='test optics'), fh)
        km = arcsec_per_px(setup) * e['distance_km'] * KM_PER_ARCSEC_PER_KM
        W, H, ang = 1600, 1200, 25.0
        R = ag.R_MOON / km
        c, s = np.cos(np.radians(ang)), np.sin(np.radians(ang))
        A = R * np.array([[c, s], [s, -c]])
        # centre on the sunlit terrain west of the terminator's side: the subsolar longitude minus 40°
        lat_c, lon_c = 10.0, e['sub_sun_lon'] - 40.0
        sx, sy, _ = ag.latlon_to_sky(np.array(lat_c), np.array(lon_c), e['sub_obs_lat'], e['sub_obs_lon'])
        t = np.array([W / 2, H / 2]) - A @ [float(sx), float(sy)]
        truth = ag.Geometry(e['sub_obs_lat'], e['sub_obs_lon'], A, t)
        img, ok = render_shaded(truth, W, H, Relief(64), S.reference(), (e['sub_sun_lat'], e['sub_sun_lon']))
        self.assertGreater(ok.mean(), 0.99)
        img = cv2.GaussianBlur(img, (0, 0), 0.8) / max(float(img.max()), 1e-6)
        img = img + np.random.default_rng(1).normal(0, 0.004, img.shape)
        cv_imwrite(name, np.clip(img * 50000 + 800, 0, 65535).astype(np.uint16))
        home = os.path.join(tmp, 'home')
        os.makedirs(home)
        r = S.run_cli('locate', name, home=home, timeout=S.budget(600))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('searching the image as a close-up', r.stdout)
        geo, d = ag.load_geo(name)
        self.assertTrue(d['quality']['closeup'])
        self.assertEqual(d['quality']['optics'], 'test optics')
        check_geometry(self, geo, truth, W, H, px=3.0, deg=1.0)


@S.slow
@S.needs_all
class HarderDisks(unittest.TestCase):
    """Mirrored (a star diagonal) and crescent full disks, located in this process."""

    def locate(self, **kw):
        img, truth = S.synthetic_moon(**kw)
        geo, q = ag.locate(img, log=S.quiet)
        return geo, q, truth

    def test_mirrored(self):
        geo, q, truth = self.locate(mirror=True, theta=200.0)
        check_geometry(self, geo, truth, S.DISK['W'], S.DISK['H'], px=0.5)

    @S.disabled_for_speed
    def test_crescent(self):
        geo, q, truth = self.locate(sun=(0.0, 115.0), theta=300.0, lat0=-5.0, lon0=6.0)
        # a crescent holds far fewer patches: a looser but still sub-pixel-to-pixel fit on the lit part
        self.assertEqual(bool(geo.mirrored), False)
        self.assertLess(S.angle_diff(geo.north_angle, truth.north_angle), 1.0)
        self.assertAlmostEqual(geo.radius_px / truth.radius_px, 1.0, delta=0.01)
        self.assertGreater(q['matches'], 40)

    def test_with_capture_time_lit_relief(self):
        from atlas_ephem import ephemeris
        when = datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc)
        e = ephemeris(when)
        img, truth = S.synthetic_moon(sun=(e['sub_sun_lat'], e['sub_sun_lon']), lat0=e['sub_obs_lat'],
                                      lon0=e['sub_obs_lon'])
        geo, q = ag.locate(img, log=S.quiet, when=when)
        check_geometry(self, geo, truth, S.DISK['W'], S.DISK['H'], px=0.5)


if __name__ == '__main__':
    unittest.main()
