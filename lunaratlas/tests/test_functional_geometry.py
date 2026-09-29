"""Functional tests: the geometry model, limb fit, pose fits, sidecar, ephemeris and close-up optics."""
import json
import math
import os
import unittest
from datetime import datetime, timedelta, timezone

import _support as S
import numpy as np

import atlas_closeup as ac
import atlas_ephem as ae
import atlas_geo as ag


class GeometryModel(unittest.TestCase):
    def geo(self, **kw):
        return S.truth_geometry(**kw)

    def test_centre_of_disk_is_the_sub_observer_point(self):
        g = self.geo()
        lat, lon, ok = g.to_latlon(g.t[0], g.t[1])
        self.assertTrue(ok)
        self.assertAlmostEqual(float(lat), g.lat0, places=9)
        self.assertAlmostEqual(float(lon), g.lon0, places=9)

    def test_forward_inverse_round_trip(self):
        g = self.geo()
        lat, lon = np.meshgrid(np.linspace(-70, 70, 29), np.linspace(-75, 75, 31))
        x, y, z = g.to_image(lat, lon)
        vis = z > 0.05
        la, lo, ok = g.to_latlon(x[vis], y[vis])
        self.assertTrue(ok.all())
        np.testing.assert_allclose(la, lat[vis], atol=1e-7)
        np.testing.assert_allclose(lo, lon[vis], atol=1e-7)

    def test_round_trip_with_a_correction_field(self):
        g = self.geo()
        coef = np.zeros((6, 2)); coef[1] = [0.8, -0.5]; coef[3] = [-0.6, 0.4]; coef[5] = [0.3, 0.2]
        g = ag.Geometry(g.lat0, g.lon0, g.A, g.t, coef, 2, 0.9)
        lat, lon = np.meshgrid(np.linspace(-50, 50, 21), np.linspace(-50, 50, 21))
        x, y, _ = g.to_image(lat, lon)
        la, lo, ok = g.to_latlon(x, y)
        self.assertTrue(ok.all())
        # the inverse is a 4-step fixed point: sub-milli-degree for a correction of about a pixel
        np.testing.assert_allclose(la, lat, atol=2e-3)
        np.testing.assert_allclose(lo, lon, atol=2e-3)

    def test_scale_orientation_and_mirroring(self):
        for theta in (0.0, 37.0, 90.0, 181.0, 300.0):
            for mirror in (False, True):
                g = self.geo(theta=theta, mirror=mirror)
                self.assertAlmostEqual(g.radius_px, S.DISK['R'], places=6)
                self.assertAlmostEqual(g.km_per_px, ag.R_MOON / S.DISK['R'], places=9)
                self.assertEqual(bool(g.mirrored), mirror)
                # similarity(theta) turns north theta degrees clockwise; north_angle counts counter-clockwise
                self.assertLess(S.angle_diff(g.north_angle, -theta % 360), 1e-9)

    def test_north_is_up_on_screen_for_theta_zero(self):
        g = self.geo(theta=0.0)
        x0, y0, _ = g.to_image(0.0, g.lon0)
        x1, y1, _ = g.to_image(10.0, g.lon0)
        self.assertLess(y1, y0)                        # image y grows downwards
        xe, _, _ = g.to_image(0.0, g.lon0 + 10)
        self.assertGreater(xe, x0)                     # east to the right, not mirrored

    def test_resized_matches_cv2_resize_pixel_centres(self):
        g = self.geo()
        for sx, sy in ((0.5, 0.5), (0.25, 0.3), (1.0, 1.0)):
            gs = g.resized(sx, sy)
            x, y, _ = g.to_image(10.0, -20.0)
            xs, ys, _ = gs.to_image(10.0, -20.0)
            self.assertAlmostEqual(float(xs), (float(x) + 0.5) * sx - 0.5, places=9)
            self.assertAlmostEqual(float(ys), (float(y) + 0.5) * sy - 0.5, places=9)
            back = gs.resized(1 / sx, 1 / sy)
            np.testing.assert_allclose(back.A, g.A, atol=1e-9)
            np.testing.assert_allclose(back.t, g.t, atol=1e-9)

    def test_dict_round_trip(self):
        coef = np.arange(12, dtype=float).reshape(6, 2) * 0.01
        g = ag.Geometry(1.5, -2.5, [[400, 10], [12, -401]], [600, 500], coef, 2, 0.8, 215.0)
        g2 = ag.Geometry.from_dict(json.loads(json.dumps(g.as_dict())))
        self.assertEqual(g.as_dict(), g2.as_dict())

    def test_without_correction(self):
        g = ag.Geometry(0, 0, [[400, 0], [0, -400]], [500, 500], np.ones((3, 2)), 1, 0.9)
        self.assertIsNone(g.without_correction().coef)
        self.assertEqual(g.without_correction().deg, 0)

    def test_perspective_projection_is_close_to_orthographic(self):
        # at 221 lunar radii a feature at the limb shifts by about 1/221 of the radius
        x, y, z = ag.latlon_to_sky(np.array(0.0), np.array(89.0), 0.0, 0.0)
        self.assertAlmostEqual(float(x), math.sin(math.radians(89)) * 221 / (221 - float(z)), places=12)
        self.assertLess(abs(float(x) - math.sin(math.radians(89))), 0.006)

    def test_similarity_determinant_sign(self):
        A, _ = ag.similarity(0, 0, 100, 10, False)
        self.assertLess(np.linalg.det(A), 0)
        A, _ = ag.similarity(0, 0, 100, 10, True)
        self.assertGreater(np.linalg.det(A), 0)

    def test_north_up_matrix(self):
        for theta in (0, 45, 170, 250):
            for mirror in (False, True):
                g = self.geo(theta=theta, mirror=mirror)
                M, rot, mir = ag.north_up_matrix(g)
                self.assertEqual(mir, mirror)
                B = M @ g.A
                n, e = B @ [0, 1], B @ [1, 0]
                self.assertLess(abs(math.atan2(n[0], -n[1])), 1e-9)       # north straight up
                self.assertGreater(e[0], 0)                                # east to the right
                self.assertLessEqual(abs(rot), 180)


class LimbFit(unittest.TestCase):
    def disk(self, w=800, h=700, cx=400.3, cy=351.7, r=250.0, blur=1.2, phase=None):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        img = ((xx - cx) ** 2 + (yy - cy) ** 2 < r * r).astype(np.float32)
        if phase is not None:           # the terminator: an ellipse through the poles
            u = (xx - cx) / r
            img *= (u > phase * np.sqrt(np.clip(1 - ((yy - cy) / r) ** 2, 0, 1))).astype(np.float32)
        img = S.cv2.GaussianBlur(img * 200 + 10, (0, 0), blur)
        return img

    def test_full_disk(self):
        cx, cy, R, share = ag.fit_limb(self.disk())
        self.assertAlmostEqual(cx, 400.3, delta=0.3)
        self.assertAlmostEqual(cy, 351.7, delta=0.3)
        self.assertAlmostEqual(R, 250.0, delta=0.5)
        self.assertGreater(share, 0.9)

    def test_crescent_limb_is_not_the_terminator(self):
        cx, cy, R, share = ag.fit_limb(self.disk(phase=0.6))
        self.assertAlmostEqual(cx, 400.3, delta=1.0)
        self.assertAlmostEqual(R, 250.0, delta=1.5)
        self.assertLess(share, 0.9)                       # the terminator is part of the contour but off the circle

    def test_disk_cut_by_the_frame(self):
        cx, cy, R, _ = ag.fit_limb(self.disk(w=600, cx=450.0))
        self.assertAlmostEqual(cx, 450.0, delta=1.0)
        self.assertAlmostEqual(R, 250.0, delta=1.5)

    def test_circle_through_three_points(self):
        p = np.array([[[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]]).transpose(0, 1, 2)
        cx, cy, R = ag._circle3(p.reshape(1, 3, 2))
        self.assertAlmostEqual(float(cx[0]), 0.0, places=9)
        self.assertAlmostEqual(float(cy[0]), 0.0, places=9)
        self.assertAlmostEqual(float(R[0]), 1.0, places=9)


class PoseFits(unittest.TestCase):
    def correspondences(self, geo, n=400, seed=3, noise=0.3):
        rng = np.random.default_rng(seed)
        lat = rng.uniform(-60, 60, n); lon = rng.uniform(-70, 70, n)
        x, y, z = geo.to_image(lat, lon)
        k = z > 0.2
        P = np.stack([x[k], y[k]], 1) + rng.normal(0, noise, (k.sum(), 2))
        return P, np.stack([lat[k], lon[k]], 1)

    def test_fit_global_recovers_libration_and_affine(self):
        truth = S.truth_geometry(lat0=4.5, lon0=-6.0)
        P, L = self.correspondences(truth)
        P[:10] += 40                                       # outliers are trimmed
        g, res, keep = ag.fit_global(P, L, S.truth_geometry(lat0=0.0, lon0=0.0))
        self.assertAlmostEqual(g.lat0, 4.5, delta=0.1)
        self.assertAlmostEqual(g.lon0, -6.0, delta=0.1)
        self.assertLess(S.pixel_error(truth, g, 1100, 1000)[1], 1.0)
        self.assertFalse(keep[:10].any())

    def test_fit_correction_finds_a_smooth_field(self):
        truth = S.truth_geometry()
        P, L = self.correspondences(truth, n=1500, noise=0.1)
        sx, sy, _ = ag.latlon_to_sky(L[:, 0], L[:, 1], truth.lat0, truth.lon0)
        P2 = P + np.stack([2.0 * sx * sy, 1.5 * sx ** 2], 1)            # a quadratic distortion of 1-2 px
        g, cv = ag.fit_correction(truth, P2, L)
        self.assertGreaterEqual(g.deg, 2)
        x, y, _ = g.to_image(L[:, 0], L[:, 1])
        self.assertLess(np.sqrt(((P2 - np.stack([x, y], 1)) ** 2).sum(1).mean()), 0.3)
        self.assertLess(cv, 0.3)

    def test_fit_correction_keeps_none_for_pure_noise(self):
        truth = S.truth_geometry()
        P, L = self.correspondences(truth, n=800, noise=0.3)
        g, _ = ag.fit_correction(truth, P, L)
        self.assertEqual(g.deg, 0)

    def test_partial_disk_gets_at_most_a_linear_correction(self):
        truth = S.truth_geometry()
        rng = np.random.default_rng(5)
        lat = rng.uniform(-60, 60, 1500); lon = rng.uniform(30, 75, 1500)       # one limb only: a crescent
        x, y, _ = truth.to_image(lat, lon)
        L = np.stack([lat, lon], 1)
        sx, sy, _ = ag.latlon_to_sky(lat, lon, truth.lat0, truth.lon0)
        P = np.stack([x, y], 1) + np.stack([3 * sx ** 3, 3 * sy ** 2], 1)
        g, _ = ag.fit_correction(truth, P, L)
        self.assertLessEqual(g.deg, 1)

    @S.needs_relief
    def test_estimate_sun_from_the_terminator(self):
        # measured on the synthetic Moon: the estimate lies 8-20° towards a thinner phase (the dim zone near the
        # terminator falls under the 25 % "lit" level); it only has to be on the right side and roughly right
        est = []
        for sun_lon in (-60.0, 35.0, 90.0):
            img, geo = S.synthetic_moon(sun=(0.0, sun_lon), noise=0)
            small, (sx, sy) = ag.resize(img, 0.4)
            lat, lon = ag.estimate_sun(small, geo.resized(sx, sy))
            self.assertEqual(lat, 0.0)
            self.assertEqual(math.copysign(1, lon), math.copysign(1, sun_lon))
            self.assertLess(S.angle_diff(lon, sun_lon), 25.0)
            est.append(lon)
        self.assertEqual(est, sorted(est))


class Reference(unittest.TestCase):
    @S.needs_reference
    def test_render_covers_the_near_side(self):
        ref = S.reference()
        self.assertEqual(ref.levels[0].shape, ag.Reference.SHAPE)
        g = S.truth_geometry()
        img, ok = ref.render(g, 1100, 1000)
        self.assertEqual(img.shape, (1000, 1100))
        self.assertGreater(ok.mean(), 0.35)
        self.assertGreater(img[ok].std(), 5)                  # maria and highlands differ

    @S.needs_reference
    def test_mare_is_darker_than_highlands(self):
        g = S.truth_geometry()
        img, _ = S.reference().render(g, 1100, 1000)
        def at(lat, lon):
            x, y, _ = g.to_image(lat, lon)
            return float(img[int(round(float(y))), int(round(float(x)))])
        self.assertLess(at(28.0, 17.5), at(-25.0, 10.0))       # Mare Serenitatis vs the southern highlands


class Sidecar(S.TempDir, unittest.TestCase):
    def test_save_then_load(self):
        p = os.path.join(self.tmp, 'a.tif')
        S.cv2.imwrite(p, np.zeros((10, 10), np.uint8))
        g = S.truth_geometry()
        path = ag.save_geo(p, g, dict(matches=1), 10, 10, extra_field='kept')
        self.assertEqual(path, os.path.join(self.tmp, 'a.atlas.json'))
        g2, d = ag.load_geo(p)
        self.assertEqual(g2.as_dict(), g.as_dict())
        self.assertEqual(d['schema'], ag.SIDECAR_SCHEMA)
        self.assertEqual(d['extra_field'], 'kept')
        self.assertEqual(d['derived']['mirrored'], False)
        self.assertAlmostEqual(d['derived']['north_angle_deg'], round(g.north_angle, 2))

    def test_save_keeps_other_fields(self):
        p = os.path.join(self.tmp, 'a.tif')
        S.cv2.imwrite(p, np.zeros((10, 10), np.uint8))
        with open(ag.sidecar_path(p), 'w') as fh:
            json.dump(dict(edits=dict(shapes=[1]), note='mine'), fh)
        ag.save_geo(p, S.truth_geometry(), {}, 10, 10)
        d = S.sidecar(p)
        self.assertEqual(d['edits'], dict(shapes=[1]))
        self.assertEqual(d['note'], 'mine')

    def test_a_sidecar_from_before_the_rename_still_loads(self):
        p = os.path.join(self.tmp, 'a.tif')
        S.cv2.imwrite(p, np.zeros((10, 10), np.uint8))
        ag.save_geo(p, S.truth_geometry(), {}, 10, 10)
        d = S.sidecar(p)
        d['schema'] = 'moon_atlas.geo/1'
        with open(ag.sidecar_path(p), 'w') as fh:
            json.dump(d, fh)
        self.assertIsNotNone(ag.load_geo(p)[0])
        d['schema'] = 'something.else/1'
        with open(ag.sidecar_path(p), 'w') as fh:
            json.dump(d, fh)
        self.assertIsNone(ag.load_geo(p)[0])

    def test_missing(self):
        self.assertEqual(ag.load_geo(os.path.join(self.tmp, 'none.tif')), (None, None))

    def test_write_json_atomic(self):
        p = os.path.join(self.tmp, 'x.json')
        ag.write_json_atomic(p, {'ä': 1}, ensure_ascii=False)
        with open(p, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh), {'ä': 1})
        self.assertEqual(os.listdir(self.tmp), ['x.json'])


class Ephemeris(unittest.TestCase):
    """Against the worked examples of J. Meeus, Astronomical Algorithms (2nd ed.), within the truncated series."""
    T_1992 = datetime(1992, 4, 12, tzinfo=timezone.utc) - timedelta(seconds=69)      # 0h TD

    def test_julian_day(self):
        self.assertAlmostEqual(ae.julian_day(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) - 69 / 86400, 2451545.0, places=6)
        self.assertAlmostEqual(ae.julian_day(datetime(1957, 10, 4, 19, 26, 24, tzinfo=timezone.utc)) - 69 / 86400,
                               2436116.31, places=6)          # example 7.a
        naive = ae.julian_day(datetime(2026, 2, 3, 4, 5, 6))
        aware = ae.julian_day(datetime(2026, 2, 3, 5, 5, 6, tzinfo=timezone(timedelta(hours=1))))
        self.assertAlmostEqual(naive, aware, places=9)       # a naive time is UTC

    def test_moon_position_example_47a(self):
        lam, beta, dist, _, _ = ae.moon_ecliptic(2448724.5)
        self.assertAlmostEqual(lam, 133.162655, delta=0.001)
        self.assertAlmostEqual(beta, -3.229126, delta=0.01)
        self.assertAlmostEqual(dist, 368409.7, delta=30)

    def test_sun_example_25a(self):
        lon, dist = ae.sun_ecliptic((2448908.5 - 2451545.0) / 36525)
        self.assertAlmostEqual(lon, 199.90988, delta=0.001)
        self.assertAlmostEqual(dist / 149597870.7, 0.99766, delta=0.00002)

    def test_sidereal_time_example_12a(self):
        self.assertAlmostEqual(ae.gmst(2446895.5), 197.693195, delta=1e-5)

    def test_libration_and_subsolar_point_example_53a(self):
        e = ae.ephemeris(self.T_1992, obs=None)
        self.assertAlmostEqual(e['sub_obs_lon'], -1.206, delta=0.02)      # optical libration l'
        self.assertAlmostEqual(e['sub_obs_lat'], 4.194, delta=0.02)       # b'
        self.assertAlmostEqual(e['sub_sun_lon'], 67.89, delta=0.06)       # l0
        self.assertAlmostEqual(e['sub_sun_lat'], 1.46, delta=0.03)        # b0
        self.assertAlmostEqual(e['colongitude'], (90 - e['sub_sun_lon']) % 360, places=9)

    def test_topocentric_parallax(self):
        geo = ae.ephemeris(self.T_1992, obs=None)
        topo = ae.ephemeris(self.T_1992, obs=(50.9, 4.4, 0.05))
        shift = math.hypot(topo['sub_obs_lat'] - geo['sub_obs_lat'], topo['sub_obs_lon'] - geo['sub_obs_lon'])
        self.assertGreater(shift, 0.05)
        self.assertLess(shift, 1.05)                           # "up to 1° of libration"
        self.assertLess(abs(topo['distance_km'] - geo['distance_km']), 6400)
        self.assertLess(abs(topo['sub_sun_lon'] - geo['sub_sun_lon']), 0.01)       # the Sun does not care

    def test_equatorial_ecliptic_round_trip(self):
        for lam, beta in ((0.0, 0.0), (133.2, -3.2), (270.0, 5.0), (359.0, 1.0)):
            ra, dec = ae.ecl_to_eq(lam, beta, 23.44)
            l2, b2 = ae.eq_to_ecl(ra, dec, 23.44)
            self.assertLess(S.angle_diff(l2, lam), 1e-9)
            self.assertAlmostEqual(b2, beta, places=9)

    def test_full_moon_phase_angle(self):
        # 2026-01-03 10:03 UTC is a full moon; 2026-01-18 19:52 UTC a new moon
        self.assertLess(ae.ephemeris(datetime(2026, 1, 3, 10, 3, tzinfo=timezone.utc), obs=None)['phase_angle'], 6)
        self.assertGreater(ae.ephemeris(datetime(2026, 1, 18, 19, 52, tzinfo=timezone.utc), obs=None)['phase_angle'], 174)


class CaptureTime(S.TempDir, unittest.TestCase):
    def test_sharpcap_name(self):
        t = ae.capture_time('/some/2026-09-23-2138_1-Moon_Filter 4_lapl2_ap5276_Drizzle15.tif')
        self.assertEqual(t, datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc))
        self.assertEqual(ae.capture_time('2026-09-23-2138_9-x.tif').second, 54)

    def test_mosaic_layout_middle_time(self):
        panels = {f'p{i}': dict(path=f'2026-09-25-21{m:02d}_0-Moon.tif') for i, m in enumerate((10, 12, 14, 30, 40))}
        with open(os.path.join(self.tmp, 'mosaic_layout.json'), 'w') as fh:
            json.dump(dict(panels=panels), fh)
        t = ae.capture_time(os.path.join(self.tmp, 'mosaic_finished.tif'))
        self.assertEqual(t, datetime(2026, 9, 25, 21, 14, tzinfo=timezone.utc))

    def test_image_layout_wins_over_folder_layout(self):
        with open(os.path.join(self.tmp, 'mosaic_layout.json'), 'w') as fh:
            json.dump(dict(panels={'a': dict(path='2026-01-01-0000_0-x.tif')}), fh)
        with open(os.path.join(self.tmp, 'm_layout.json'), 'w') as fh:
            json.dump(dict(panels={'b': dict(path='2026-02-02-0200_0-x.tif')}), fh)
        self.assertEqual(ae.capture_time(os.path.join(self.tmp, 'm.tif')).month, 2)

    def test_render_capture_time_text(self):
        from atlas_render import capture_time
        self.assertEqual(capture_time('2026-09-23-2138_1-Moon.tif'), '2026-09-23 21:38 UTC')
        panels = {f'p{i}': dict(path=f'2026-09-25-21{m:02d}_0-Moon.tif') for i, m in enumerate((10, 40))}
        with open(os.path.join(self.tmp, 'mosaic_layout.json'), 'w') as fh:
            json.dump(dict(panels=panels), fh)
        self.assertEqual(capture_time(os.path.join(self.tmp, 'mosaic.tif')), '2026-09-25 21:10–21:40 UTC')


class CloseupOptics(S.TempDir, unittest.TestCase):
    def test_drizzle_factor(self):
        self.assertEqual(ac.drizzle_factor('x_Drizzle15.tif'), 1.5)
        self.assertEqual(ac.drizzle_factor('x_Drizzle30.tif'), 3.0)
        self.assertEqual(ac.drizzle_factor('plain.tif'), 1.0)

    def test_setups_cover_every_extender_and_camera(self):
        self.assertEqual(len(ac.setups()), len(ac.EXTENDERS) * len(ac.CAMERAS))

    def test_plate_scale(self):
        s = dict(pixel_um=2.9, magnification=2.0)
        self.assertAlmostEqual(ac.arcsec_per_px(s), 206.265 * 2.9 / (ac.TELESCOPE[1] * 2.0), places=12)
        self.assertAlmostEqual(ac.arcsec_per_px(s, 1.5), ac.arcsec_per_px(s) / 1.5, places=12)

    def test_km_candidates(self):
        known = dict(extender='x', magnification=2.0, camera='c', pixel_um=2.9)
        c = ac.km_candidates('a_Drizzle15.tif', known, 384400)
        self.assertEqual(len(c), 3)                              # nominal ± 10 %
        base = ac.arcsec_per_px(known, 1.5) * 384400 * ac.KM_PER_ARCSEC_PER_KM
        self.assertAlmostEqual(c[1][0], base, places=9)
        self.assertEqual(len(ac.km_candidates('a.tif', None, 384400)), len(ac.setups()))

    def test_optics_file(self):
        self.assertIsNone(ac.load_optics(self.tmp))
        with open(os.path.join(self.tmp, ac.OPTICS_FILE), 'w') as fh:
            json.dump(dict(magnification=2, pixel_um=2.9, text='t'), fh)
        self.assertEqual(ac.load_optics(self.tmp)['text'], 't')
        self.assertEqual(ac.ask_optics(self.tmp, S.quiet)['text'], 't')

    def test_an_optics_file_from_before_the_rename_is_still_read(self):
        with open(os.path.join(self.tmp, 'moon_atlas_optics.json'), 'w') as fh:
            json.dump(dict(magnification=2, pixel_um=2.9, text='old'), fh)
        self.assertEqual(ac.load_optics(self.tmp)['text'], 'old')
        with open(os.path.join(self.tmp, ac.OPTICS_FILE), 'w') as fh:
            json.dump(dict(magnification=1, pixel_um=2.0, text='new'), fh)
        self.assertEqual(ac.load_optics(self.tmp)['text'], 'new')        # the current name wins

    def test_normalise_removes_brightness(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, (200, 200)).astype(np.float32)
        a, b = ac.normalise(x * 10 + 5, 3), ac.normalise(x * 1000 + 5000, 3)
        np.testing.assert_allclose(a, b, atol=1e-3)

    def test_fit_affine_holds_the_libration(self):
        truth = S.truth_geometry(lat0=2.0, lon0=3.0)
        rng = np.random.default_rng(2)
        L = np.stack([rng.uniform(5, 15, 200), rng.uniform(-10, 0, 200)], 1)
        x, y, _ = truth.to_image(L[:, 0], L[:, 1])
        g, res, keep = ac.fit_affine(np.stack([x, y], 1), L, 2.0, 3.0)
        self.assertEqual((g.lat0, g.lon0), (2.0, 3.0))
        self.assertLess(res.max(), 1e-6)
        self.assertTrue(keep.all())

    @unittest.skipUnless(S.HAVE_RELIEF16, 'LOLA 16 px/deg relief not in lunaratlas/data')
    def test_relief_slopes_and_shading(self):
        rel = S.relief16()
        de, dn = rel.slopes(np.array([[0.0, 10.0]], np.float32), np.array([[0.0, 20.0]], np.float32))
        self.assertTrue(np.isfinite(de).all() and np.isfinite(dn).all())
        self.assertLess(np.abs(de).max(), 2.0)                    # m per m: lunar slopes are gentle at 16 px/deg

    @S.needs_relief
    def test_shaded_render_is_dark_on_the_night_side(self):
        g = S.truth_geometry()
        img, ok = ac.render_shaded(g, 1100, 1000, S.relief16(), S.reference(), (0.0, 35.0))
        x_lit, y_lit, _ = g.to_image(0.0, 60.0)          # 25° from the subsolar point
        x_dark, y_dark, _ = g.to_image(0.0, -70.0)       # 105° from it: night
        lit = img[int(y_lit) - 5:int(y_lit) + 5, int(x_lit) - 5:int(x_lit) + 5].mean()
        dark = img[int(y_dark) - 5:int(y_dark) + 5, int(x_dark) - 5:int(x_dark) + 5].mean()
        self.assertGreater(lit, 0.1)
        self.assertLess(dark, 0.01)


if __name__ == '__main__':
    unittest.main()
