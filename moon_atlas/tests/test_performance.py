"""Performance tests: every step has a time and memory budget, so a change that quietly gets slower is caught.

    python3 -m unittest discover -s moon_atlas/tests -t moon_atlas/tests -p 'test_performance*'
    MOON_ATLAS_PERF_FACTOR=3 ...      a slower machine: every budget × 3

Budgets are wall-clock and deliberately generous (roughly 3-10x the measured cost on the development machine,
Apple silicon, Python 3.14): they exist to catch a step that becomes an order of magnitude slower, a quadratic
that sneaks in, or memory that is never released, not to police microseconds. Nothing here downloads: the
reference data must already be in moon_atlas/data, and the budget measurements reuse the suite's shared
reference and relief, so they are paid once per process.
"""
import gc
import os

import shutil
import tempfile
import time
import tracemalloc
import unittest

import _support as S
import cv2
import numpy as np

import atlas_closeup as ac
import atlas_geo as ag
import atlas_quality as aq
import atlas_render as ar
import atlas_view as av


class ReferenceData(S.TempDir, unittest.TestCase):
    """The one-time costs: reading the albedo mosaic and the LOLA elevation, and rendering the reference."""

    @classmethod
    def setUpClass(cls):
        cls.ref = S.reference()                 # the suite's shared copy: the first read is not timed again here

    def test_the_shared_reference_is_loaded(self):
        self.assertEqual(self.ref.levels[0].shape, ag.Reference.SHAPE)
        self.assertGreater(len(self.ref.levels), 1, 'the pyramid must be built for a big image')

    def test_rendering_the_reference_for_a_typical_image(self):
        g = S.truth_geometry()
        t = time.perf_counter()
        img, ok = self.ref.render(g, 1100, 1000)
        self.assertLess(time.perf_counter() - t, S.budget(5), 'the 1 MP reference render')
        self.assertEqual(img.shape, (1000, 1100))
        self.assertGreater(ok.mean(), 0.35)

    def test_the_reference_render_is_linear_in_the_pixels(self):
        # a 4x bigger frame may not cost far more than 4x: no per-pixel Python, no accidental re-read of the file
        g = S.truth_geometry()
        t = time.perf_counter(); self.ref.render(g, 1100, 1000); small = time.perf_counter() - t
        t = time.perf_counter(); self.ref.render(g, 2200, 2000); big = time.perf_counter() - t
        self.assertLess(big, S.budget(8))
        self.assertLess(big, max(small, 1e-3) * 12, f'4x the pixels cost {big / max(small, 1e-3):.1f}x the time')

    @unittest.skipUnless(S.HAVE_RELIEF64, 'LOLA 64 px/deg relief not in moon_atlas/data')
    def test_the_64_px_deg_relief_is_built_in_bounded_time(self):
        # Relief(64) is the biggest thing the program builds: the whole 64 px/deg slope map. It is built once per
        # close-up search, so its cost has to stay a matter of seconds, and it must not be built at all for the
        # far cheaper 16 px/deg one (REMAINING_WORK.md, "Memory").
        t = time.perf_counter()
        r = ac.Relief(64)
        self.assertLess(time.perf_counter() - t, S.budget(60), 'building the 64 px/deg slopes')
        self.assertEqual(r.ppd, 64)
        self.assertEqual(r.de_raw.shape[0], 180 * 64)
        small = ac.Relief(16)
        self.assertLess(small.de_raw.nbytes, r.de_raw.nbytes / 10, '16 px/deg must be far smaller than 64')

    @unittest.skipUnless(S.HAVE_RELIEF64, 'LOLA 64 px/deg relief not in moon_atlas/data')
    def test_the_relief_footprint_matches_the_lola_file(self):
        # the slopes are two float32 maps the size of the elevation model: nothing hidden on top of that
        r = ac.Relief(64)
        per_map = 180 * 64 * 360 * 64 * 4
        self.assertEqual(r.de_raw.nbytes, per_map)
        self.assertEqual(r.dn.nbytes, per_map)
        self.assertLess(r.de_raw.nbytes + r.dn.nbytes, 3.5e9, 'about 3.4 GB for both slope maps')

    def test_the_16_px_deg_relief_is_a_fixed_size(self):
        # two float32 maps over 180x360 degrees at 16 px/deg: 4 x 16 x (180*16) x (360*16) bytes
        r = ac.Relief(16)
        per_map = 4 * (180 * 16) * (360 * 16)
        self.assertEqual(r.de_raw.nbytes, per_map)
        self.assertEqual(r.dn.nbytes, per_map)
        self.assertLess(per_map * 2, 200e6, 'the relief the suite keeps between tests')


class LimbAndQuality(unittest.TestCase):
    """The two whole-image passes that run before anything is positioned."""

    def frame(self, W, H):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        img = ((xx - W / 2) ** 2 + (yy - H / 2) ** 2 < (0.44 * min(W, H)) ** 2).astype(np.float32) * 200
        img = cv2.GaussianBlur(img, (0, 0), 2.0)
        return img + np.random.default_rng(1).normal(0, 3, img.shape).astype(np.float32)

    def test_limb_fit_on_a_12_megapixel_frame(self):
        t = time.perf_counter()
        cx, cy, R, share = ag.fit_limb(self.frame(4000, 3000))
        self.assertLess(time.perf_counter() - t, S.budget(10), 'the RANSAC limb fit')
        self.assertGreater(share, 0.9)
        self.assertAlmostEqual(R, 0.44 * 3000, delta=0.02 * 3000)

    def test_the_quality_measures_on_a_12_megapixel_frame(self):
        raw = np.random.default_rng(0).integers(0, 40000, (3000, 4000), dtype=np.uint16)
        t = time.perf_counter()
        q = aq.measure(raw, (2000.0, 1500.0, 1320.0))
        self.assertLess(time.perf_counter() - t, S.budget(20), 'the quality measures')
        self.assertEqual((q['width'], q['height']), (4000, 3000))
        self.assertIn('saturated_share', q)

    def test_measuring_twice_costs_the_same_as_once(self):
        raw = np.random.default_rng(0).integers(0, 40000, (1500, 1500), dtype=np.uint16)
        t = time.perf_counter(); aq.measure(raw); first = time.perf_counter() - t
        t = time.perf_counter(); aq.measure(raw); second = time.perf_counter() - t
        self.assertLess(second, max(first, 1e-3) * 4, 'a warm run must not be much slower than a cold one')


@S.needs_font
class LabelLayout(unittest.TestCase):
    """Placing every name is the step that grows with the gazetteer: it must stay vectorised."""

    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.feats = S.projected_features(cls.geo)
        cls.fonts = ar.Fonts('Roboto', S.quiet)
        cls.view = (0, 0, 1.0, S.DISK['W'], S.DISK['H'])

    def test_layout_of_the_whole_gazetteer(self):
        t = time.perf_counter()
        labels = ar.layout(self.feats, self.geo, self.view, self.fonts)
        self.assertLess(time.perf_counter() - t, S.budget(10))
        self.assertGreater(len(labels), 30)

    def test_layout_cost_does_not_explode_with_the_number_of_candidates(self):
        # every spot a label could take is tried in turn; a 10x gazetteer must not cost 100x
        many = []
        for i in range(10):
            for f in self.feats:
                g = dict(f)
                g['name'] = f"{f['name']} {i}"
                many.append(g)
        t = time.perf_counter(); ar.layout(self.feats, self.geo, self.view, self.fonts); one = time.perf_counter() - t
        t = time.perf_counter(); ar.layout(many, self.geo, self.view, self.fonts); ten = time.perf_counter() - t
        self.assertLess(ten, S.budget(30))
        self.assertLess(ten, max(one, 1e-3) * 30, f'10x the features cost {ten / max(one, 1e-3):.1f}x the time')

    def test_the_font_face_cache_is_bounded_and_reused(self):
        fonts = ar.Fonts('Roboto', S.quiet)
        t = time.perf_counter()
        for size in range(8, 60):
            fonts.get(400, size)
        first = time.perf_counter() - t
        self.assertLess(first, S.budget(5))
        t = time.perf_counter()
        for _ in range(20):
            for size in range(8, 60):
                fonts.get(400, size)
        self.assertLess(time.perf_counter() - t, first * 20, 'cached faces must be reused, not re-opened')
        self.assertLessEqual(len(fonts.cache), 200)

    def test_the_grid_overlay(self):
        t = time.perf_counter()
        lines, labels = ar.grid_overlay(self.geo, self.view, self.fonts)
        self.assertLess(time.perf_counter() - t, S.budget(5))
        self.assertGreater(len(lines), 20)

    def test_drawing_a_busy_image(self):
        labels = ar.layout(self.feats, self.geo, self.view, self.fonts)
        img = np.full((2000, 2000, 3), 3000, np.uint16)
        t = time.perf_counter()
        ar.draw(img, labels, self.fonts)
        self.assertLess(time.perf_counter() - t, S.budget(20), f'drawing {len(labels)} labels on 4 MP')

    def test_drawing_is_about_the_labels_and_not_the_frame(self):
        labels = ar.layout(self.feats, self.geo, self.view, self.fonts)
        few = [l for l in labels if 'rim' not in l][:5]
        a = np.full((1000, 1000, 3), 3000, np.uint16)
        b = np.full((2000, 2000, 3), 3000, np.uint16)
        t = time.perf_counter(); ar.draw(a, few, self.fonts); small = time.perf_counter() - t
        t = time.perf_counter(); ar.draw(b, few, self.fonts); big = time.perf_counter() - t
        self.assertLess(big, S.budget(10))
        self.assertLess(big, max(small, 5e-3) * 8, 'four times the pixels, mostly empty, must stay cheap')

    def test_drawing_nothing_is_free(self):
        img = np.full((2000, 2000, 3), 3000, np.uint16)
        t = time.perf_counter()
        ar.draw(img, [], self.fonts)
        self.assertLess(time.perf_counter() - t, S.budget(2), 'an empty image must not be walked pixel by pixel')


@S.needs_all
class ViewerOverhead(S.TempDir, unittest.TestCase):
    """The viewer's own work: tiles, the page payload and the font stylesheet."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, 'home')
        os.makedirs(self.home)
        self._old_cache = av.CACHE
        av.CACHE = os.path.join(self.home, 'caches')
        self.addCleanup(setattr, av, 'CACHE', self._old_cache)

    def image(self, W=2048, H=1536, name='m.tif'):
        p = os.path.join(self.tmp, name)
        cv2.imwrite(p, S.encode(np.random.default_rng(0).random((H, W), dtype=np.float32) * 0.5 + 0.2))
        return p, cv2.imread(p, cv2.IMREAD_UNCHANGED)

    def test_building_the_tile_pyramid(self):
        img, raw = self.image()
        t = time.perf_counter()
        levels = av.build_tiles(img, raw, S.quiet)
        first = time.perf_counter() - t
        self.assertLess(first, S.budget(20))
        self.assertGreaterEqual(len(levels), 3)
        t = time.perf_counter()
        again = av.build_tiles(img, raw, S.quiet)
        second = time.perf_counter() - t
        self.assertEqual(len(again), len(levels), 'the same image gives the same pyramid')
        self.assertLess(second, S.budget(2), 'a cached pyramid must be read, not rebuilt')
        self.assertLess(second, max(first, 1e-3) * 5, f'reusing the cache took {second / max(first, 1e-3):.1f}x the build')

    def test_the_page_payload_for_the_whole_gazetteer(self):
        img, geo = S.moon_image(self.tmp)
        raw = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        levels = av.build_tiles(img, raw, S.quiet)
        side = S.sidecar(img)
        t = time.perf_counter()
        data = av.page_data(img, raw, geo, side, levels, S.quiet)
        self.assertLess(time.perf_counter() - t, S.budget(20))
        self.assertGreater(len(data['features']), 1000)
        self.assertEqual((data['width'], data['height']), (S.DISK['W'], S.DISK['H']))

    def test_the_font_stylesheet_is_not_rebuilt_per_request(self):
        t = time.perf_counter()
        css = av.fonts_css()
        self.assertLess(time.perf_counter() - t, S.budget(10))
        self.assertIn('@font-face', css)

    def test_tiles_on_disk_stay_a_sensible_size(self):
        img, _ = self.image(4096, 3072)
        raw = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        levels = av.build_tiles(img, raw, S.quiet)
        n = sum(l['cols'] * l['rows'] for l in levels)
        d = av.tile_dir(img)
        size = sum(os.path.getsize(os.path.join(base, f)) for base, _, fs in os.walk(d) for f in fs)
        self.assertGreater(n, 10)
        # a full pyramid of a 12 MP image is a fraction of the source, not several times it
        self.assertLess(size, os.path.getsize(img) * 2, f'{size / 1e6:.1f} MB of tiles')


@S.needs_all
class CommandLineTiming(S.TempDir, unittest.TestCase):
    """The whole commands, as a user waits for them (the README quotes 10-20 s for a locate)."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, 'home')
        os.makedirs(self.home)
        self.img, _ = S.moon_image(self.tmp)

    def test_export_of_a_one_megapixel_image(self):
        for fmt, ext in (('tiff', '.tif'), ('png', '.png'), ('jpg', '.jpg')):
            with self.subTest(fmt):
                t = time.perf_counter()
                r = S.run_cli('export', self.img, '--format', fmt, '-o', os.path.join(self.tmp, 'o' + ext), home=self.home)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertLess(time.perf_counter() - t, S.budget(60))

    def test_export_with_every_layer_on(self):
        t = time.perf_counter()
        r = S.run_cli('export', self.img, '--layers', 'area,crater,lettered,relief,landing', '--font-scale', '1.3',
                      '-o', os.path.join(self.tmp, 'all.png'), home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.perf_counter() - t, S.budget(60))

    def test_info_and_find_are_quick(self):
        for args in (('info', self.img), ('find', self.img, 'Copernicus')):
            with self.subTest(args[0]):
                t = time.perf_counter()
                r = S.run_cli(*args, home=self.home)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertLess(time.perf_counter() - t, S.budget(30), f'{args[0]} must not re-locate the image')

    def test_a_full_export_of_a_four_megapixel_image(self):
        big = os.path.join(self.tmp, 'big.tif')
        cv2.imwrite(big, S.encode(np.random.default_rng(0).random((2000, 2000), dtype=np.float32) * 0.5 + 0.2))
        S.locate_as(big, S.truth_geometry(W=2000, H=2000, cx=1000.0, cy=1000.0, R=800.0))
        t = time.perf_counter()
        r = S.run_cli('export', big, '-o', os.path.join(self.tmp, 'big.png'), home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.perf_counter() - t, S.budget(120))


@S.needs_all
class ViewerLatency(S.TempDir, unittest.TestCase):
    """Every viewer request the page makes on load, and the pages it can show, must answer quickly."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='moon_atlas_perf_')
        cls.home = os.path.join(cls.tmp, 'home')
        os.makedirs(cls.home)
        cls.img, cls.geo = S.moon_image(cls.tmp)
        cls.v = S.Viewer(cls.img, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        shutil.rmtree(cls.tmp, True)

    def best_of(self, path, each=3):
        best = None
        for _ in range(each):
            t = time.perf_counter()
            code = self.v.request(path, raw=True)[0]
            dt = time.perf_counter() - t
            self.assertEqual(code, 200, path)
            best = dt if best is None else min(best, dt)
        return best

    def test_the_first_load_of_the_page(self):
        t = time.perf_counter()
        for p in ('/', '/viewer.js', '/viewer.css', '/fonts.css', '/data.js', '/edits', '/export/status'):
            self.assertEqual(self.v.request(p, raw=True)[0], 200, p)
        self.assertLess(time.perf_counter() - t, S.budget(30), 'everything the page needs before it draws')

    def test_the_page_assets_answer_quickly(self):
        for p, budget in (('/', 2), ('/viewer.js', 2), ('/viewer.css', 2), ('/fonts.css', 2), ('/data.js', 3),
                          ('/edits', 1), ('/export/status', 1)):
            with self.subTest(p):
                self.assertLess(self.best_of(p), S.budget(budget), f'{p} is too slow')

    def test_tiles_answer_quickly(self):
        import json
        body = self.v.request('/data.js', raw=True)[1].decode()
        d = json.loads(body[len('window.ATLAS = '):].rstrip().rstrip(';'))
        paths = [f'/tiles/{lv}/{c}_{r}.jpg' for lv, L in enumerate(d['levels'])
                 for c in range(L['cols']) for r in range(L['rows'])]
        self.assertGreater(len(paths), 5)
        for p in paths:
            self.assertLess(self.best_of(p, each=2), S.budget(3), f'{p} is too slow')

    def test_a_long_session_of_mixed_requests_stays_fast(self):
        # no per-request leak: the last hundred requests are no slower than the first hundred
        paths = ['/', '/data.js', '/edits', '/export/status', '/tiles/0/0_0.jpg', '/viewer.js']
        first = sum(self.best_of(p, each=2) for p in paths)
        for i in range(200):
            self.v.request(paths[i % len(paths)], raw=True)
        last = sum(self.best_of(p, each=2) for p in paths)
        self.assertLess(last, max(first, 1e-3) * 6, f'{first * 1e3:.0f} ms then {last * 1e3:.0f} ms: the server is slowing down')


@S.needs_font
class Memory(S.TempDir, unittest.TestCase):
    """Nothing that runs per image may keep growing: a batch of exports must not climb."""

    def test_repeated_layout_and_drawing_frees_its_memory(self):
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        fonts = ar.Fonts('Roboto', S.quiet)
        view = (0, 0, 1.0, S.DISK['W'], S.DISK['H'])
        ar.layout(feats, geo, view, fonts)                        # warm the caches the first pass fills
        gc.collect()
        tracemalloc.start()
        base = tracemalloc.take_snapshot()
        for _ in range(15):
            ar.draw(np.full((600, 700, 3), 3000, np.uint16), ar.layout(feats, geo, view, fonts), fonts)
        gc.collect()
        grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(base, 'filename'))
        tracemalloc.stop()
        self.assertLess(grown, 4_000_000, f'{grown / 1e6:.1f} MB retained after 15 more layout+draw rounds')

    def test_the_ephemeris_keeps_no_growth_over_a_year(self):
        from datetime import datetime, timedelta, timezone
        import atlas_ephem as ae
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            ae.ephemeris(start + timedelta(days=i))
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for i in range(200):
            ae.ephemeris(start + timedelta(days=i * 3))
        gc.collect()
        grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(before, 'filename'))
        tracemalloc.stop()
        self.assertLess(grown, 500_000, f'{grown} bytes retained by 200 ephemeris calls')

    @S.needs_all
    def test_a_full_export_does_not_retain_the_image(self):
        img, _ = S.moon_image(self.tmp)
        code, log = S.run_main('export', img, '-o', os.path.join(self.tmp, 'o.png'))
        self.assertIsNone(code, log)
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(3):
            S.run_main('export', img, '-o', os.path.join(self.tmp, 'o.png'))
        gc.collect()
        grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(before, 'filename'))
        tracemalloc.stop()
        self.assertLess(grown, 8_000_000, f'{grown / 1e6:.1f} MB retained after 3 more exports')

    def test_the_gazetteer_is_not_re_read_per_image(self):
        import atlas_names as an
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(50):
            an.load_features(S.quiet)
        grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(before, 'filename'))
        tracemalloc.stop()
        self.assertLess(grown, 500_000, f'{grown} bytes retained by 50 gazetteer reads')


@S.needs_all
class CostOfADecision(unittest.TestCase):
    """Cheap answers must stay cheap: the parts a user hits before committing to a long run."""

    def test_the_quality_gate_is_worth_its_cost(self):
        # locate spends most of its time in terrain matching; refusing a bad image early must stay cheap
        import moon_atlas as ma
        tmp = tempfile.mkdtemp(prefix='moon_atlas_perf_')
        self.addCleanup(shutil.rmtree, tmp, True)
        img, _ = S.synthetic_moon(blur=14.0)
        p = os.path.join(tmp, 'soft.tif')
        cv2.imwrite(p, S.encode(img))
        t = time.perf_counter()
        ok, reasons, line, q = ma.quality_gate(p)
        self.assertFalse(ok, line)
        self.assertLess(time.perf_counter() - t, S.budget(15), 'the quality gate alone must stay quick')

    def test_projection_of_every_feature_is_vectorised(self):
        import moon_atlas as ma
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        t = time.perf_counter()
        for _ in range(20):
            ma.project([dict(f) for f in feats], geo)
        self.assertLess((time.perf_counter() - t) / 20, S.budget(1), 'per-feature Python loops would show here')

    def test_building_a_geometry_is_cheap(self):
        geo = S.truth_geometry()
        t = time.perf_counter()
        for _ in range(2000):
            geo.to_image(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
        self.assertLess((time.perf_counter() - t) / 2000, S.budget(0.05), 'to_image is on the hot path of every export')


if __name__ == '__main__':
    unittest.main()
