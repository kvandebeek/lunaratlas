"""The close-up search, coarse to fine: the same places found as by the full search, in a third of the time or less."""
import json
import os
import time
import unittest
from datetime import datetime, timezone

import cv2
import numpy as np

import _support as S
import atlas_closeup as ac
import atlas_geo as ag
from atlas_ephem import ephemeris

W, H = 1600, 1200
SETUP = dict(extender='native', magnification=1.0, camera='IMX678', pixel_um=2.0)


class Distinct(unittest.TestCase):
    def test_neighbouring_angles_are_one_place(self):
        cands = [dict(score=0.9, tl=(100, 100), mirror=False, angle=10), dict(score=0.8, tl=(104, 98), mirror=False, angle=14),
                 dict(score=0.7, tl=(104, 98), mirror=True, angle=14), dict(score=0.6, tl=(400, 300), mirror=False, angle=90)]
        out = ac.distinct(cands, 10, 20)
        self.assertEqual([c['score'] for c in out], [0.9, 0.7, 0.6], 'the mirror image at the same spot is another candidate')
        self.assertEqual(len(ac.distinct(cands, 2, 20)), 2)

    def test_a_view_too_small_to_search_is_none(self):
        self.assertIsNone(ac.view_template(np.zeros((30, 40), np.float32), 1.0, 4.8, 0, False))
        tpl, meta = ac.view_template(np.random.default_rng(1).random((600, 800)).astype(np.float32), 1.0, 2.4, 30, True)
        self.assertEqual(tpl.shape[0], tpl.shape[1])
        self.assertTrue(meta['mirror'] and meta['angle'] == 30)
        self.assertEqual(float(tpl[0, 0]), 0.0, 'cut to a disk')


class Sky:
    """The capture time, the sky at it and a synthetic close-up rendered from LOLA relief lit by that Sun."""

    def __init__(self):
        self.when = datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc)
        self.e = ephemeris(self.when)
        self.km = ac.arcsec_per_px(SETUP) * self.e['distance_km'] * ac.KM_PER_ARCSEC_PER_KM
        self.relief16, self.relief64, self.ref = ac.Relief(16), ac.Relief(64), S.reference()
        self.sun = (self.e['sub_sun_lat'], self.e['sub_sun_lon'])

    def case(self, ang, mirror, lat, dlon, blur):
        e, R = self.e, ag.R_MOON / self.km
        c, s = np.cos(np.radians(ang)), np.sin(np.radians(ang))
        A = R * np.array([[c, s], [s, -c]])
        if mirror:
            A = A @ np.diag([-1.0, 1.0])
        sx, sy, _ = ag.latlon_to_sky(np.array(lat), np.array(e['sub_sun_lon'] + dlon), e['sub_obs_lat'], e['sub_obs_lon'])
        truth = ag.Geometry(e['sub_obs_lat'], e['sub_obs_lon'], A, np.array([W / 2, H / 2]) - A @ [float(sx), float(sy)])
        img, _ = ac.render_shaded(truth, W, H, self.relief64, self.ref, self.sun)
        img = cv2.GaussianBlur(img, (0, 0), blur) / max(float(img.max()), 1e-6)
        img = img + np.random.default_rng(1).normal(0, 0.004, img.shape)
        return truth, np.clip(img * 50000 + 800, 0, 65535).astype(np.uint16).astype(np.float32)


def rank(cands, geo_w, truth):
    """1-based position of the candidate that is the true place (its centre within a degree), 0 if none is."""
    tla, tlo, _ = truth.to_latlon(W / 2, H / 2)
    for i, cc in enumerate(cands):
        la, lo, _ = ac.solve_hit(cc, geo_w).to_latlon(W / 2, H / 2)
        if abs(float(la) - float(tla)) < 1 and abs(float(lo) - float(tlo)) < 1:
            return i + 1
    return 0


class FakeGeo:
    """Stands in for a search hit's geometry: verify() reads its matches and rms straight from it."""
    km_per_px, north_angle, mirrored = 0.5, 0.0, False

    def __init__(self, n, rms):
        self.n, self.rms = n, rms

    def to_latlon(self, x, y):
        return 10.0, -20.0, True


class Choice(S.TempDir):
    """Which fit locate_closeup keeps, and what it does when the folder's optics find nothing (no Moon data needed)."""

    def locate(self, hits_for, optics_file=None):
        from unittest import mock
        path = os.path.join(self.tmp, '2026-05-27-2010_5-Moon1__lapl3_ap1.tif')
        if optics_file:
            with open(os.path.join(self.tmp, ac.OPTICS_FILE), 'w') as fh:
                json.dump(optics_file, fh)
        lines = []
        search = lambda gray, kms, *a: ([dict(km=kms[0], score=0.5, angle=0, mirror=False, hit=h) for h in hits_for(kms)], None)
        with mock.patch.object(ac, 'load_gray', lambda p: (np.zeros((100, 200), np.float32),)), \
             mock.patch.object(ac, 'Relief', lambda *a: None), mock.patch.object(ac, 'Reference', lambda *a: None), \
             mock.patch.object(ac, 'blind_search', search), \
             mock.patch.object(ac, 'solve_hit', lambda c, gw: FakeGeo(*c['hit'])), \
             mock.patch.object(ac, 'verify', lambda gray, g, *a, **k: (g.n, g, g.rms)), \
             mock.patch.object(ac, 'ask_optics', lambda folder, log: ac.load_optics(folder)):
            geo, q = ac.locate_closeup(path, lambda *a: lines.append(' '.join(map(str, a))))
        return geo, q, '\n'.join(lines)

    def test_a_poor_fit_with_more_matches_does_not_hide_a_good_one(self):
        geo, q, _ = self.locate(lambda kms: [(40, 20.0), (30, 1.0)])
        self.assertEqual((q['matches'], q['rms_px']), (30, 1.0))

    def test_nothing_that_fits_is_refused_with_the_reason(self):
        with self.assertRaises(SystemExit) as e:
            self.locate(lambda kms: [(40, 20.0), (5, 1.0)])
        self.assertIn('40 terrain matches but 20.0 px rms', str(e.exception))

    def test_a_frame_not_at_the_folders_scale_is_searched_at_every_setup(self):
        folder_optics = dict(SETUP, text='the folder setup')
        geo, q, log = self.locate(lambda kms: [(5, 1.0)] if len(kms) == 3 else [(200, 0.8)], folder_optics)
        self.assertEqual(q['matches'], 200)
        self.assertIn('trying every setup', log)
        self.assertEqual(ac.load_optics(self.tmp), folder_optics, "the folder's optics file is left as it was")


@S.slow
@S.needs_all
class CoarseToFine(unittest.TestCase):
    """A synthetic close-up (the relief lit by the real Sun, blurred, noisy) at angles between the search's steps."""

    @S.disabled_for_speed
    def test_the_place_is_found_first_at_angles_between_the_steps_and_faster_than_the_full_search(self):
        sky = Sky()
        args = (sky.e['sub_obs_lat'], sky.e['sub_obs_lon'], sky.sun, sky.relief16, sky.ref, S.quiet)
        kms = [sky.km * f for f in (0.9, 1.0, 1.1)]
        t_fast = t_full = 0.0
        for ang, mirror, lat, dlon, blur in ((102, False, 30, -50, 0.8), (25, True, 10, -40, 2.5)):
            with self.subTest(angle=ang, mirror=mirror, blur=blur):
                truth, gray = sky.case(ang, mirror, lat, dlon, blur)
                t0 = time.perf_counter()
                fast, gw = ac.blind_search(gray, kms, *args)
                t_fast += time.perf_counter() - t0
                self.assertEqual(rank(fast, gw, truth), 1, 'the true place is the best candidate')
                self.assertGreater(fast[0]['score'], 0.5, 'and the angle is refined to a strong match')
                t0 = time.perf_counter()
                full, gw2 = ac.blind_search_full(gray, kms, *args)
                t_full += time.perf_counter() - t0
                self.assertEqual(rank(full, gw2, truth), 1)
                self.assertGreaterEqual(fast[0]['score'], full[0]['score'] - 0.02, 'never a worse match than the 4° steps')
        self.assertLess(t_fast, t_full * 0.7, f'coarse to fine {t_fast:.0f} s, full {t_full:.0f} s')


@S.slow
@unittest.skipUnless(S.HAVE_RELIEF64, 'LOLA 64 px/deg relief not in lunaratlas/data')
@S.needs_all
class RenamedCloseUp(S.TempDir):
    """A close-up whose file name has lost its capture time is located with --time, and the time is kept."""

    @S.disabled_for_speed
    def test_locate_with_time_then_info_knows_it(self):
        import json
        import os
        truth, gray = Sky().case(25, False, 10, -40, 0.8)
        name = os.path.join(self.tmp, 'renamed.tif')
        cv2.imwrite(name, np.clip(gray, 0, 65535).astype(np.uint16))
        with open(os.path.join(self.tmp, ac.OPTICS_FILE), 'w') as fh:
            json.dump(dict(SETUP, telescope=ac.TELESCOPE[0], focal_mm=ac.TELESCOPE[1], text='test optics'), fh)
        home = os.path.join(self.tmp, 'home')
        os.makedirs(home)
        r = S.run_cli('locate', name, home=home, timeout=S.budget(600))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--time YYYY-MM-DDTHH:MM', r.stderr, 'the message says how to give the time')
        r = S.run_cli('locate', name, '--time', 'yesterday', home=home)
        self.assertIn('YYYY-MM-DDTHH:MM', r.stderr)
        r = S.run_cli('locate', name, '--time', '2026-09-23T21:38', home=home, timeout=S.budget(600))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        geo, d = ag.load_geo(name)
        self.assertTrue(d['quality']['closeup'])
        self.assertEqual(d['quality']['capture_utc'], '2026-09-23 21:38:00')
        tla, tlo, _ = truth.to_latlon(W / 2, H / 2)
        la, lo, _ = geo.to_latlon(W / 2, H / 2)
        self.assertLess(abs(float(la) - float(tla)) + abs(float(lo) - float(tlo)), 0.05)
        r = S.run_cli('info', name, home=home)
        self.assertIn('taken 2026-09-23 21:38 UTC', r.stdout, 'info reads the time from the sidecar')


if __name__ == '__main__':
    unittest.main()
