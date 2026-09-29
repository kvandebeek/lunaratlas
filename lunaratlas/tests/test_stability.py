"""Stability tests: the same input always gives the same output, repeated work does not drift or grow, a year of
ephemeris is continuous, and the viewer keeps serving under sustained and parallel use."""
import gc
import json
import os
import shutil
import tempfile
import threading
import time
import tracemalloc
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import _support as S
import cv2
import numpy as np

import atlas_ephem as ae
import atlas_geo as ag
import atlas_render as ar


class Determinism(S.TempDir, unittest.TestCase):
    def test_limb_fit_is_repeatable(self):
        yy, xx = np.mgrid[0:700, 0:800].astype(np.float32)
        img = cv2.GaussianBlur(((xx - 400) ** 2 + (yy - 350) ** 2 < 250 ** 2).astype(np.float32) * 200, (0, 0), 1.5)
        rng = np.random.default_rng(3)
        img += rng.normal(0, 3, img.shape).astype(np.float32)
        runs = {ag.fit_limb(img) for _ in range(5)}
        self.assertEqual(len(runs), 1)

    @S.needs_relief
    def test_locate_is_repeatable(self):
        img, truth = S.synthetic_moon(W=700, H=650, cx=350.0, cy=320.0, R=290.0)
        a, qa = ag.locate(img, log=S.quiet)
        b, qb = ag.locate(img.copy(), log=S.quiet)
        self.assertEqual(a.as_dict(), b.as_dict())
        self.assertEqual({k: v for k, v in qa.items() if k != 'seconds'}, {k: v for k, v in qb.items() if k != 'seconds'})

    @S.needs_all
    def test_export_is_repeatable(self):
        img, _ = S.moon_image(self.tmp)
        outs = []
        for i in range(2):
            p = os.path.join(self.tmp, f'o{i}.png')
            code, log = S.run_main('export', img, '-o', p)
            self.assertIsNone(code, log)
            outs.append(cv2.imread(p, cv2.IMREAD_UNCHANGED))
        np.testing.assert_array_equal(outs[0], outs[1])

    @S.needs_all
    def test_layout_is_repeatable_and_independent_of_call_history(self):
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        fonts = ar.Fonts('Roboto', S.quiet)
        view = (0, 0, 1.0, 1100, 1000)
        first = ar.layout(feats, geo, view, fonts)
        ar.layout(feats, geo, view, fonts, min_px=8, font_scale=1.6, hidden=['Copernicus'])      # something else between
        again = ar.layout(feats, geo, view, fonts)
        strip = lambda ls: [{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in l.items()} for l in ls]
        self.assertEqual(strip(first), strip(again))

    def test_sidecar_round_trips_are_exact(self):
        g = ag.Geometry(1.234567890123, -4.5, [[400.123, 10.5], [12.25, -401.75]], [600.5, 500.25],
                        np.random.default_rng(0).normal(0, 1, (10, 2)), 3, 0.87)
        for _ in range(50):
            g = ag.Geometry.from_dict(json.loads(json.dumps(g.as_dict())))
        self.assertEqual(g.lat0, 1.234567890123)
        self.assertEqual(g.coef.shape, (10, 2))

    def test_repeated_pixel_lat_lon_trips_do_not_drift(self):
        g = S.truth_geometry()
        x, y = np.array([300.0, 560.0, 800.0]), np.array([400.0, 490.0, 700.0])
        x0, y0 = x.copy(), y.copy()
        for _ in range(200):
            la, lo, ok = g.to_latlon(x, y)
            x, y, _ = g.to_image(la, lo)
        self.assertLess(np.abs(x - x0).max(), 1e-7)
        self.assertLess(np.abs(y - y0).max(), 1e-7)


class Endurance(unittest.TestCase):
    def test_ephemeris_over_a_year_is_continuous_and_in_range(self):
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        prev, lat_rng, lon_rng, dist_rng = None, [], [], []
        for h in range(0, 366 * 24, 2):
            e = ae.ephemeris(t0 + timedelta(hours=h), obs=None)
            lat_rng.append(e['sub_obs_lat']); lon_rng.append(e['sub_obs_lon']); dist_rng.append(e['distance_km'])
            self.assertTrue(-180 <= e['sub_sun_lon'] <= 180 and 0 <= e['colongitude'] < 360 and 0 <= e['phase_angle'] <= 180)
            if prev:
                self.assertLess(abs(e['sub_obs_lat'] - prev['sub_obs_lat']), 0.15)          # libration is slow
                self.assertLess(abs(e['sub_obs_lon'] - prev['sub_obs_lon']), 0.25)
                self.assertLess(S.angle_diff(e['sub_sun_lon'], prev['sub_sun_lon']), 1.1)  # 12.2° per day
                self.assertLess(abs(e['distance_km'] - prev['distance_km']), 800)
            prev = e
        self.assertTrue(6.0 < max(lat_rng) < 7.0 and -7.0 < min(lat_rng) < -6.0)        # libration in latitude ±6.7°
        self.assertTrue(6.5 < max(lon_rng) < 8.2 and -8.2 < min(lon_rng) < -6.5)        # in longitude ±7.9°
        self.assertTrue(356000 < min(dist_rng) < 360000 and 404000 < max(dist_rng) < 407000)

    def test_ephemeris_across_the_turn_of_a_year_and_a_leap_day(self):
        for t in (datetime(2027, 12, 31, 23, 59, tzinfo=timezone.utc), datetime(2028, 2, 29, 12, tzinfo=timezone.utc)):
            a, b = ae.ephemeris(t, obs=None), ae.ephemeris(t + timedelta(minutes=2), obs=None)
            self.assertLess(abs(a['sub_obs_lon'] - b['sub_obs_lon']), 0.01)

    @S.needs_all
    def test_repeated_layout_and_drawing_does_not_grow(self):
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        fonts = ar.Fonts('Roboto', S.quiet)
        view = (0, 0, 1.0, 1100, 1000)
        img = np.zeros((1000, 1100, 3), np.uint16)

        def once():
            ar.draw(img, ar.layout(feats, geo, view, fonts), fonts)
        once()
        gc.collect()
        tracemalloc.start()
        try:
            once()
            gc.collect()
            base = tracemalloc.get_traced_memory()[0]
            for _ in range(15):
                once()
            gc.collect()
            grown = tracemalloc.get_traced_memory()[0] - base
        finally:
            tracemalloc.stop()
        self.assertLess(grown, 2_000_000, f'{grown / 1e6:.1f} MB retained after 15 more exports')
        self.assertLess(len(fonts.cache), 200)                          # a bounded number of (weight, size) faces


@S.needs_all
class ViewerUnderLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='lunaratlas_load_')
        cls.home = os.path.join(cls.tmp, 'home')
        os.makedirs(cls.home)
        cls.img, cls.geo = S.moon_image(cls.tmp)
        cls.v = S.Viewer(cls.img, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        shutil.rmtree(cls.tmp, True)

    def test_sustained_requests(self):
        paths = ['/', '/viewer.js', '/viewer.css', '/fonts.css', '/edits', '/export/status', '/tiles/0/0_0.jpg',
                 '/tiles/1/0_0.jpg', '/tiles/2/0_0.jpg', '/nope']
        t0 = time.time()
        for i in range(600):
            code = self.v.request(paths[i % len(paths)], raw=True)[0]
            self.assertEqual(code, 404 if paths[i % len(paths)] == '/nope' else 200)
        self.assertLess(time.time() - t0, S.budget(60))
        self.assertIsNone(self.v.proc.poll(), 'the viewer stopped')

    def test_parallel_saves_and_reads(self):
        cx, cy = (float(v) for v in self.geo.t)

        def save(k):
            e = dict(shapes=[dict(kind='circle', cx=cx + k, cy=cy, r=10 + k)], hidden=[f'n{k}'])
            code, body, _ = self.v.request('/edits', e)
            return code, body

        with ThreadPoolExecutor(16) as ex:
            saves = list(ex.map(save, range(64)))
            reads = list(ex.map(lambda _: self.v.request('/edits')[0], range(64)))
        self.assertTrue(all(c == 200 for c, _ in saves), [c for c, _ in saves])
        self.assertTrue(all(c == 200 for c in reads))
        final = self.v.request('/edits')[1]
        self.assertEqual(len(final['shapes']), 1)                       # one whole save won, nothing interleaved
        self.assertEqual(final['hidden'], [f"n{int(final['shapes'][0]['r']) - 10}"])
        geo, d = ag.load_geo(self.img)
        self.assertIsNotNone(geo, d)

    def test_big_edit_payload(self):
        cx, cy = (float(v) for v in self.geo.t)
        pts = [[cx + 100 * np.cos(a), cy + 100 * np.sin(a)] for a in np.linspace(0, 6.28, 9000)]
        e = dict(shapes=[dict(kind='outline', pts=pts, closed=True)] + [dict(kind='text', x=cx, y=cy, label='x' * 400)] * 5500)
        code, saved, _ = self.v.request('/edits', e, timeout=60)
        self.assertEqual(code, 200)
        self.assertEqual(len(saved['shapes']), 5000)
        self.assertEqual(len(saved['shapes'][0]['pts']), 9000)
        self.assertEqual(self.v.request('/', raw=True)[0], 200)

    def test_client_that_goes_away(self):
        import socket
        host, port = self.v.url.split('//')[1].split(':')
        for _ in range(20):
            s = socket.create_connection((host, int(port)), timeout=5)
            s.sendall(b'POST /edits HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100000\r\n\r\n{"shapes": [')
            s.close()                                                   # a body that never arrives
        s = socket.create_connection((host, int(port)), timeout=5)
        s.sendall(b'GET /tiles/0/0_0.jpg HTTP/1.1\r\nHost: localhost\r\n\r\n')
        s.close()
        self.assertEqual(self.v.request('/edits')[0], 200)
        self.assertIsNone(self.v.proc.poll())


if __name__ == '__main__':
    unittest.main()
