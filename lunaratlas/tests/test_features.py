"""North-up export, the sky at the capture time, batch, find with several names, --fit and --time."""
import csv
import io
import json
import math
import os
import shutil
import unittest
from datetime import datetime, timezone
from unittest import mock

import cv2
import numpy as np

import _support as S
import atlas_ephem as ae
import atlas_geo as ag
import atlas_render as ar
import lunaratlas as la


class Sky(unittest.TestCase):
    def eph(self, phase, sun_lon, obs_lon=0.0):
        return dict(phase_angle=phase, sub_sun_lon=sun_lon, sub_obs_lon=obs_lon)

    def test_the_phase_names_and_the_lit_share(self):
        for phase, sun, want, share in ((0, 0, 'full moon', 1.0), (180, 180, 'new moon', 0.0),
                                        (90, 90, 'first quarter', 0.5), (90, -90, 'last quarter', 0.5),
                                        (60, 60, 'waxing gibbous', 0.75), (120, -120, 'waning crescent', 0.25),
                                        (120, 120, 'waxing crescent', 0.25), (60, -60, 'waning gibbous', 0.75)):
            p = ae.phase_summary(self.eph(phase, sun))
            self.assertEqual(p['name'], want, (phase, sun))
            self.assertAlmostEqual(p['illumination'], share, places=2)

    def test_the_moon_of_a_real_night(self):
        # full moon on 2026-09-26 (about 16:00 UTC): nearly all lit; a week earlier a waxing half
        full = ae.phase_summary(ae.ephemeris(datetime(2026, 9, 26, 16, 0, tzinfo=timezone.utc)))
        self.assertGreater(full['illumination'], 0.97)
        wax = ae.phase_summary(ae.ephemeris(datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)))
        self.assertTrue(wax['waxing'])
        self.assertTrue(0.3 < wax['illumination'] < 0.7, wax)
        wane = ae.phase_summary(ae.ephemeris(datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)))
        self.assertFalse(wane['waxing'])

    def test_the_text_lines(self):
        t = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        self.assertRegex(ae.phase_text(t), r'^[a-z ]+, \d+ % lit$')
        self.assertRegex(ae.sky_text(t), r'% lit · Sun overhead at \d+\.\d° [NS] \d+\.\d° [EW] · colongitude \d+°$')

    def test_a_time_typed_by_a_person(self):
        want = datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc)
        for text in ('2026-09-20T21:30', '2026-09-20 21:30', ' 2026-09-20T21:30Z ', '2026-09-20T21:30:00'):
            self.assertEqual(ae.parse_when(text), want, text)
        for bad in ('', 'yesterday', '2026-13-01T00:00', '21:30'):
            with self.assertRaises(ValueError, msg=bad) as cm:
                ae.parse_when(bad)
            self.assertIn('YYYY-MM-DDTHH:MM', str(cm.exception))


class TimeFromTheSidecar(S.TempDir):
    def test_a_name_without_a_time_gets_the_one_given_with_locate(self):
        img = os.path.join(self.tmp, 'closeup.tif')
        cv2.imwrite(img, np.zeros((8, 8), np.uint8))
        self.assertIsNone(ae.capture_time(img))
        with open(ag.sidecar_path(img), 'w') as fh:
            json.dump(dict(quality=dict(capture_utc='2026-09-20 21:30:00')), fh)
        self.assertEqual(ae.capture_time(img), datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc))
        self.assertEqual(ar.capture_time(img), '2026-09-20 21:30 UTC', 'the info block shows it too')

    def test_the_name_wins_over_the_sidecar(self):
        img = os.path.join(self.tmp, '2026-01-02-0304_0-x.tif')
        with open(ag.sidecar_path(img), 'w') as fh:
            json.dump(dict(quality=dict(capture_utc='2020-01-01 00:00:00')), fh)
        self.assertEqual(ae.capture_time(img).year, 2026)

    def test_damaged_sidecars_give_no_time_not_a_traceback(self):
        img = os.path.join(self.tmp, 'closeup.tif')
        for text in ('', '[]', '{"quality": 5}', '{"quality": {"capture_utc": "soon"}}', 'not json'):
            with open(ag.sidecar_path(img), 'w') as fh:
                fh.write(text)
            self.assertIsNone(ae.capture_time(img), text)

    def test_time_on_the_command_line(self):
        class A:
            image = os.path.join('x', 'closeup.tif')
            time = '2026-09-20T21:30'
        self.assertEqual(la.when_of(A), datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc))
        A.time = None
        self.assertIsNone(la.when_of(A))
        A.time = 'soon'
        with self.assertRaises(SystemExit) as cm:
            la.when_of(A)
        self.assertIn('YYYY-MM-DDTHH:MM', str(cm.exception))
        A.time, A.image = '2026-09-20T21:30', '2026-09-20-2130_0-moon.tif'
        with self.assertRaises(SystemExit) as cm:
            la.when_of(A)
        self.assertIn('already carries', str(cm.exception))


class FindMatches(unittest.TestCase):
    FEATS = [dict(name=n, cls='crater', type='Crater', lat=0, lon=0, diam=1.0, origin='', link='', x=1, y=2, z=1)
             for n in ('Copernicus', 'Copernicus A', 'Copernicus B', 'Tycho', 'Mare Imbrium', 'Mare Tranquillitatis')]

    def test_exact_before_prefix_and_the_others_listed(self):
        hit, others, near = la.find_matches(self.FEATS, 'copernicus')
        self.assertEqual((hit['name'], near), ('Copernicus', []))
        self.assertEqual([o['name'] for o in others], ['Copernicus A', 'Copernicus B'], 'what else starts with it')
        hit, others, _ = la.find_matches(self.FEATS, 'Copernicus ')
        self.assertEqual(hit['name'], 'Copernicus')
        hit, others, _ = la.find_matches(self.FEATS, 'mare t')
        self.assertEqual(hit['name'], 'Mare Tranquillitatis')

    def test_a_prefix_names_the_other_fits(self):
        hit, others, _ = la.find_matches([f for f in self.FEATS if f['name'] != 'Copernicus'], 'Copernic')
        self.assertEqual(hit['name'], 'Copernicus A')
        self.assertEqual([o['name'] for o in others], ['Copernicus B'])

    def test_a_misspelling_gets_suggestions(self):
        hit, others, near = la.find_matches(self.FEATS, 'Tycoh')
        self.assertIsNone(hit)
        self.assertIn('Tycho', near)
        with self.assertRaises(SystemExit) as cm:
            la.find_feature(self.FEATS, 'Tycoh')
        self.assertIn('no feature named "Tycoh"', str(cm.exception))
        self.assertIn('did you mean Tycho', str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            la.find_feature(self.FEATS, 'zzzzqq')
        self.assertNotIn('did you mean', str(cm.exception))

    def test_a_part_of_a_name_is_found_too(self):
        hit, _, near = la.find_matches(self.FEATS, 'imbrium')
        self.assertIsNone(hit)
        self.assertEqual(near, ['Mare Imbrium'])

    def test_a_blank_name_matches_nothing(self):
        """BUG-17: strip('').startswith('') used to match the first feature in the list for an empty or
        whitespace-only query, so `find IMAGE ""` reported an unrelated feature and `export --around " "` could
        export around whatever feature happened to sort first."""
        for q in ('', ' ', '\t', '   \n  '):
            with self.subTest(repr(q)):
                hit, others, near = la.find_matches(self.FEATS, q)
                self.assertIsNone(hit)
                self.assertEqual(others, [])
                self.assertEqual(near, [])
                with self.assertRaises(SystemExit):
                    la.find_feature(self.FEATS, q)


class Turning(S.TempDir):
    """north_up: the picture, its geometry and the drawings turn together."""

    def dotted(self, theta, mirror):
        geo = S.truth_geometry(W=400, H=300, cx=200.0, cy=150.0, R=120.0, theta=theta, mirror=mirror)
        raw = np.zeros((300, 400), np.uint16)
        for (x, y, v) in ((60, 40, 20000), (300, 80, 40000), (120, 250, 60000)):
            cv2.circle(raw, (x, y), 6, v, -1)
        return raw, geo

    def test_north_ends_up_and_east_to_the_right_for_any_orientation(self):
        for theta in (0, 33, 90, 170, 259, 345):
            for mirror in (False, True):
                with self.subTest(theta=theta, mirror=mirror):
                    raw, geo = self.dotted(theta, mirror)
                    turned, g2, (M, b) = ag.north_up(raw, geo)
                    self.assertFalse(g2.mirrored)
                    self.assertLess(min(g2.north_angle, 360 - g2.north_angle), 1e-6)
                    n0 = g2.to_image(10.0, g2.lon0)          # a point north of the centre is higher up...
                    c0 = g2.to_image(0.0, g2.lon0)
                    self.assertLess(float(n0[1]), float(c0[1]))
                    e0 = g2.to_image(0.0, g2.lon0 + 10.0)     # ...and one to the east is further right
                    self.assertGreater(float(e0[0]), float(c0[0]))

    def test_every_pixel_and_every_feature_moves_the_same_way(self):
        raw, geo = self.dotted(33, True)
        turned, g2, (M, b) = ag.north_up(raw, geo)
        for (x, y) in ((60, 40), (300, 80), (120, 250)):
            nx, ny = M @ [x, y] + b
            self.assertGreater(int(turned[int(round(ny)), int(round(nx))]), 15000, 'the dot is where the map says')
        for lat, lon in ((10, -20), (-5, 15), (30, 5)):
            x, y, _ = geo.to_image(lat, lon)
            x2, y2, _ = g2.to_image(lat, lon)
            np.testing.assert_allclose(M @ [x, y] + b, [x2, y2], atol=1e-6)

    def test_the_correction_polynomial_turns_with_it(self):
        raw, geo = self.dotted(70, False)
        geo = ag.Geometry(geo.lat0, geo.lon0, geo.A, geo.t, np.array([[0.0, 0.0], [2.0, -1.0], [0.5, 0.25]]), 1, dist=geo.dist)
        _, g2, (M, b) = ag.north_up(raw, geo)
        for lat, lon in ((10, -20), (-5, 15), (30, 5), (0, 0)):
            x, y, _ = geo.to_image(lat, lon)
            x2, y2, _ = g2.to_image(lat, lon)
            np.testing.assert_allclose(M @ [x, y] + b, [x2, y2], atol=1e-6)

    def test_a_right_angle_needs_no_black_corners(self):
        raw, geo = self.dotted(90, False)
        turned, _, _ = ag.north_up(raw, geo)
        self.assertIn(turned.shape[:2], ((300, 400), (400, 300)), 'the same picture, on its side or not: no extra canvas')
        self.assertEqual(int((turned > 0).sum()), int((raw > 0).sum()), 'and nothing lost at the edges')

    def test_the_drawings_turn_and_the_ellipse_becomes_an_outline(self):
        M, b = np.array([[0.0, 1.0], [-1.0, 0.0]]), np.array([10.0, 20.0])
        edits = dict(shapes=[dict(kind='circle', cx=1, cy=2, r=3), dict(kind='rect', x0=0, y0=0, x1=4, y1=2),
                             dict(kind='ellipse', x0=0, y0=0, x1=4, y1=2, label='e', colour='#fff'),
                             dict(kind='arrow', x0=0, y0=0, x1=1, y1=0), dict(kind='text', x=5, y=6, label='t'),
                             dict(kind='outline', pts=[[0, 0], [1, 0], [1, 1]], closed=True),
                             dict(kind='measure', a=dict(x=0, y=0), b=dict(x=2, y=0))],
                     labels={'Tycho': dict(dx=3, dy=4, colour='#f00'), 'Bad': 'x'}, hidden=['A'], style=dict(fs=1))
        out = ar.transform_edits(edits, M, b)
        by = {s['kind']: s for s in out['shapes']}
        self.assertEqual((by['circle']['cx'], by['circle']['cy'], by['circle']['r']), (12.0, 19.0, 3))
        self.assertEqual((by['text']['x'], by['text']['y']), (16.0, 15.0))
        self.assertEqual((by['arrow']['x0'], by['arrow']['y0'], by['arrow']['x1'], by['arrow']['y1']), (10.0, 20.0, 10.0, 19.0))
        self.assertEqual((by['measure']['b']['x'], by['measure']['b']['y']), (10.0, 18.0))
        outlines = [s for s in out['shapes'] if s['kind'] == 'outline']
        self.assertEqual(len(outlines), 3)
        rect = next(s for s in outlines if len(s['pts']) == 4)
        self.assertEqual(rect['pts'], [[10.0, 20.0], [10.0, 16.0], [12.0, 16.0], [12.0, 20.0]])
        self.assertTrue(all(s.get('closed') for s in outlines))
        ell = next(s for s in outlines if s.get('label') == 'e')
        self.assertEqual((len(ell['pts']), ell['colour']), (96, '#fff'), 'the ellipse keeps its label and colour')
        self.assertEqual(out['labels'], {'Tycho': dict(dx=4.0, dy=-3.0, colour='#f00')}, 'offsets turn, with no shift')
        self.assertEqual((out['hidden'], out['style']), (['A'], dict(fs=1)))
        self.assertEqual(edits['shapes'][0], dict(kind='circle', cx=1, cy=2, r=3), 'the original is not touched')

    @S.needs_all
    def test_a_moved_label_s_absolute_position_survives_a_turn(self):
        """BUG-10: a moved label is stored as home + offset. The old code rotated the offset alone; the home
        itself generally moves to a DIFFERENT place after a turn (it depends on the feature's new on-image
        position, the new text layout, etc.), not merely a rotation of the old home. With real anchors, the
        stored offset is derived from an independently computed full-point transform of the absolute position,
        not merely trusted from the implementation under test."""
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        f = next(x for x in feats if x['name'] == 'Tycho')
        fonts = ar.Fonts('Roboto', S.quiet)
        home_old = ar.label_anchor(f, geo, fonts, min_px=10)
        self.assertIsNotNone(home_old)
        dx, dy = 15.0, -9.0                 # an arbitrary move away from the automatic spot
        edits = dict(labels={'Tycho': dict(dx=dx, dy=dy, colour='#fff')})
        for angle in (0.0, 73.0, 180.0):
            with self.subTest(angle=angle):
                raw = np.zeros((int(S.DISK['H']), int(S.DISK['W']), 3), np.uint8)
                geo2 = ag.Geometry(geo.lat0, geo.lon0,
                                   np.array([[math.cos(math.radians(angle)), -math.sin(math.radians(angle))],
                                             [math.sin(math.radians(angle)), math.cos(math.radians(angle))]]) @ geo.A,
                                   geo.t)
                _, new_geo, (M, b) = ag.north_up(raw, geo2)
                new_feats = S.projected_features(new_geo)
                nf = next(x for x in new_feats if x['name'] == 'Tycho')
                home_new = ar.label_anchor(nf, new_geo, fonts, min_px=10)
                self.assertIsNotNone(home_new)
                out = ar.transform_edits(edits, M, b, anchors={'Tycho': (home_old, home_new)})
                got_dx, got_dy = out['labels']['Tycho']['dx'], out['labels']['Tycho']['dy']
                # independently recomputed: the absolute point the user actually placed, carried through the
                # same M @ point + b every drawing uses, then re-expressed relative to the NEW home
                old_point = np.array([home_old[0] + dx, home_old[1] + dy])
                want_point = M @ old_point + b
                want_dx, want_dy = want_point[0] - home_new[0], want_point[1] - home_new[1]
                self.assertAlmostEqual(got_dx, want_dx, places=4)
                self.assertAlmostEqual(got_dy, want_dy, places=4)
                # the absolute screen position (not just the offset) must match the full-point transform
                got_point = np.array([home_new[0] + got_dx, home_new[1] + got_dy])
                np.testing.assert_allclose(got_point, want_point, atol=1e-4)

    @S.needs_all
    def test_without_anchors_falls_back_to_rotating_the_offset_alone(self):
        """The documented legacy guarantee for data this packet cannot reconstruct exactly: old {dx,dy} data with
        no geometry/font context available still renders, as a plain rotation of the stored offset."""
        M, b = np.array([[0.0, 1.0], [-1.0, 0.0]]), np.array([5.0, 7.0])
        edits = dict(labels={'Tycho': dict(dx=3.0, dy=4.0, colour='#f00')})
        out = ar.transform_edits(edits, M, b)
        self.assertEqual(out['labels']['Tycho']['dx'], 4.0)
        self.assertEqual(out['labels']['Tycho']['dy'], -3.0)


@S.needs_all
class Commands(S.TempDir):
    def setUp(self):
        super().setUp()
        self.img, self.geo = S.moon_image(self.tmp, name='2026-09-20-2130_0-moon.tif', theta=27.0)

    def export(self, *args, img=None):
        code, out = S.run_main('export', img or self.img, *args)
        self.assertIsNone(code, out)
        return out

    def test_north_up_export_is_a_bigger_canvas_with_north_up_and_the_info_says_so(self):
        out = os.path.join(self.tmp, 'n.tif')
        log = self.export('--north-up', '-o', out, '--no-rims')
        self.assertIn('turned so that north is up', log)
        im = cv2.imread(out, cv2.IMREAD_UNCHANGED)
        self.assertEqual(im.dtype, np.uint16)
        self.assertGreater(im.shape[1], 1100 * 0.99)
        self.assertGreater(im.shape[0] * im.shape[1], 1100 * 1000, 'a turn by 27° needs room for the corners')
        self.assertEqual(int(im[0, 0].max()), 0, 'the corner is black')
        straight = os.path.join(self.tmp, 's.tif')
        self.export('-o', straight, '--no-rims')
        self.assertEqual(cv2.imread(straight, cv2.IMREAD_UNCHANGED).shape, (1000, 1100, 3))

    def test_north_up_with_a_region_is_refused_with_the_reason(self):
        code, _ = S.run_main('export', self.img, '--north-up', '--region', '0,0,100,100')
        self.assertIn('--region', str(code))
        self.assertIn('as it was taken', str(code))

    def test_north_up_around_a_feature_and_with_drawings(self):
        with open(ag.sidecar_path(self.img)) as fh:
            d = json.load(fh)
        x, y, _ = self.geo.to_image(9.621, -20.079)
        d['edits'] = dict(shapes=[dict(kind='circle', cx=float(x), cy=float(y), r=40, colour='#ff0000', size=3)],
                          labels={'Copernicus': dict(dx=30, dy=30)})
        with open(ag.sidecar_path(self.img), 'w') as fh:
            json.dump(d, fh)
        out = os.path.join(self.tmp, 'c.png')
        log = self.export('--north-up', '--around', 'Copernicus', '--size', '500x400', '--format', 'png', '-o', out)
        self.assertIn('1 of your drawings', log)
        im = cv2.imread(out, cv2.IMREAD_UNCHANGED)
        self.assertEqual(im.shape[:2], (400, 500))
        red = (im[..., 2] > 40000) & (im[..., 1] < 20000) & (im[..., 0] < 20000)
        ys, xs = np.nonzero(red)
        self.assertGreater(len(xs), 100, 'the circle was drawn')
        self.assertLess(abs(xs.mean() - 250), 12)                    # and it is round Copernicus, in the middle of the view
        self.assertLess(abs(ys.mean() - 200), 12)

    def test_fit_sizes_the_view_from_the_feature(self):
        f = la.find_feature(la.project(la.load_features(S.quiet, sites=True), self.geo), 'Copernicus')
        dpx = f['diam'] / ag.R_MOON * self.geo.radius_px
        log = self.export('--around', 'Copernicus', '--fit', '--size', '600x400', '-o', os.path.join(self.tmp, 'f.tif'))
        want = max(600, round(2.2 * dpx))
        self.assertRegex(log, rf'{min(want, 1100)} x ')
        big = self.export('--around', 'Copernicus', '--size', '600x400', '-o', os.path.join(self.tmp, 'g.tif'))
        self.assertIn('600 x 400 px source', big)

    def test_fit_on_a_landing_site_falls_back_to_the_size(self):
        log = self.export('--around', 'Apollo 11', '--fit', '--size', '500x300', '-o', os.path.join(self.tmp, 'a.tif'))
        self.assertIn('has no diameter', log)

    def test_info_tells_the_sky_of_the_capture_time(self):
        code, out = S.run_main('info', self.img)
        self.assertIsNone(code)
        self.assertRegex(out, r'taken 2026-09-20 21:30 UTC: [a-z ]+, \d+ % of the disk lit')
        self.assertRegex(out, r'Sun overhead at [\d.]+° [NS] [\d.]+° [EW], colongitude [\d.]+°, Earth–Moon [\d,]+ km')

    def test_the_info_block_names_the_phase(self):
        out = os.path.join(self.tmp, 'i.png')
        log = self.export('--format', 'png', '-o', out, '--info')
        self.assertIn('info block', log)
        t = ae.capture_time(self.img)
        from atlas_render import Fonts, info_block
        _, labels, _ = info_block(self.geo, (0, 0, (1.0, 1.0), 1100, 1000), Fonts('Roboto', S.quiet), sky=ae.phase_text(t))
        self.assertTrue(any('% lit' in str(l.get('text', l)) for l in labels), [str(l)[:80] for l in labels])

    def test_find_with_several_names_and_as_data(self):
        code, out = S.run_main('find', self.img, 'Tycho', 'Copernicus', '--json')
        self.assertIsNone(code)
        rows = json.loads(out)
        self.assertEqual([r['name'] for r in rows], ['Tycho', 'Copernicus'])
        self.assertEqual(set(rows[0]), {'asked', 'name', 'type', 'lat', 'lon', 'diameter_km', 'x', 'y', 'diameter_px',
                                        'visibility', 'named_after', 'also'})
        code, out = S.run_main('find', self.img, 'Tycho', 'Copernicus', '--csv')
        table = list(csv.reader(io.StringIO(out)))
        self.assertEqual(table[0][:3], ['asked', 'name', 'type'])
        self.assertEqual([r[1] for r in table[1:]], ['Tycho', 'Copernicus'])

    def test_find_reports_every_name_it_could_not_find_and_still_answers_the_rest(self):
        code, out = S.run_main('find', self.img, 'Tycho', 'Tychoo', 'Nowhere Crater')
        self.assertIn('Tycho (', out)
        self.assertIn('no feature named "Tychoo"', str(code))
        self.assertIn('did you mean Tycho', str(code))
        self.assertIn('no feature named "Nowhere Crater"', str(code))

    def test_find_lists_what_else_fits(self):
        code, out = S.run_main('find', self.img, 'Copernicus')
        self.assertIn('also matches: Copernicus', out)


@S.needs_all
class Batch(S.TempDir):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, 'session')
        os.makedirs(os.path.join(self.folder, 'sub'))
        first, geo = S.moon_image(self.folder, name='a_moon.tif')
        for name in ('b_moon.tif', os.path.join('sub', 'c_moon.tif')):
            copy = os.path.join(self.folder, name)
            shutil.copy(first, copy)
            S.locate_as(copy, geo)
        with open(os.path.join(self.folder, 'broken.tif'), 'w') as fh:
            fh.write('this is not an image')
        with open(os.path.join(self.folder, 'notes.txt'), 'w') as fh:
            fh.write('not a photo')
        shutil.copy(first, os.path.join(self.folder, 'a_moon_atlas.tif'))            # an earlier export: not a photo either

    def batch(self, *args):
        return S.run_main('batch', self.folder, '--format', 'jpg', '--max-size', '300', '--no-rims', *args)

    def test_the_photos_are_found_in_order_without_exports_and_hidden_files(self):
        open(os.path.join(self.folder, '.hidden.tif'), 'w').close()
        names = [os.path.basename(p) for p in la.batch_images(self.folder)]
        self.assertEqual(names, ['a_moon.tif', 'b_moon.tif', 'broken.tif'])
        self.assertEqual([os.path.basename(p) for p in la.batch_images(self.folder, recursive=True)],
                         ['a_moon.tif', 'b_moon.tif', 'broken.tif', 'c_moon.tif'])

    def test_a_damaged_photo_does_not_stop_the_others_and_the_table_says_what_happened(self):
        code, out = self.batch()
        self.assertEqual(code, 1, 'one photo failed: the exit status says so')
        for n in ('a_moon_atlas.jpg', 'b_moon_atlas.jpg'):
            self.assertTrue(os.path.exists(os.path.join(self.folder, n)), n)
        self.assertRegex(out, r'a_moon\.tif +exported +[\d.]+ +a_moon_atlas\.jpg')
        self.assertRegex(out, r'b_moon\.tif +exported')
        self.assertRegex(out, r'broken\.tif +failed +[\d.]+ +cannot read')
        self.assertIn('2 exported, 1 failed of 3', out)
        self.assertNotIn('notes.txt', out)
        self.assertFalse(os.path.exists(os.path.join(self.folder, 'a_moon_atlas_atlas.jpg')), 'an export is not exported again')

    def test_each_photo_gets_an_options_object_of_its_own(self):
        # cmd_export fills in a.font from the photo's own edits: one photo's font must not become the next one's
        from unittest import mock
        seen = []
        with mock.patch.object(la, 'cmd_export', lambda a: seen.append(a)):
            self.batch()
        self.assertEqual([os.path.basename(a.image) for a in seen], ['a_moon.tif', 'b_moon.tif', 'broken.tif'])
        self.assertIsNot(seen[0], seen[1])
        self.assertTrue(all(a.output is None for a in seen))

    def test_skip_existing_leaves_finished_photos_alone(self):
        self.batch()
        code, out = self.batch('--skip-existing')
        self.assertRegex(out, r'a_moon\.tif +skipped')
        self.assertRegex(out, r'b_moon\.tif +skipped')
        self.assertIn('2 skipped, 1 failed of 3', out)

    def test_recursive_and_locate_only(self):
        code, out = self.batch('-r', '--locate-only')
        self.assertRegex(out, r'c_moon\.tif +located')
        self.assertFalse(os.path.exists(os.path.join(self.folder, 'sub', 'c_moon_atlas.jpg')), 'nothing exported')

    def test_a_folder_without_photos_or_not_a_folder(self):
        empty = os.path.join(self.tmp, 'empty')
        os.makedirs(empty)
        code, _ = S.run_main('batch', empty)
        self.assertIn('no images', str(code))
        code, _ = S.run_main('batch', os.path.join(self.tmp, 'nothing'))
        self.assertIn('is not a folder', str(code))

    def test_the_export_options_of_export_work_here_too(self):
        code, out = S.run_main('batch', self.folder, '--format', 'png', '--max-size', '250', '--around', 'Copernicus', '--size', '400x300')
        out_file = os.path.join(self.folder, 'a_moon_atlas_Copernicus.png')
        self.assertTrue(os.path.exists(out_file), out)
        self.assertLessEqual(max(cv2.imread(out_file).shape[:2]), 250)

    def test_skip_existing_regenerates_after_a_saved_drawing(self):
        """bugs-overview BUG-11: --skip-existing only compared mtimes, so a drawing saved in the viewer after
        the last export left a stale export in place, reported as skipped."""
        self.batch()
        img = os.path.join(self.folder, 'a_moon.tif')
        d = S.sidecar(img)
        d['edits'] = dict(shapes=[dict(kind='text', x=10, y=10, label='hi')])
        ag.write_json_atomic(ag.sidecar_path(img), d)
        os.utime(os.path.join(self.folder, 'a_moon_atlas.jpg'), None)   # touch the export to a time AFTER the edit
        code, out = self.batch('--skip-existing')
        self.assertRegex(out, r'a_moon\.tif +exported')

    def test_skip_existing_regenerates_after_a_changed_option(self):
        self.batch()
        code, out = self.batch('--skip-existing', '--night', 'show')    # a different effective option than before
        self.assertRegex(out, r'a_moon\.tif +exported')

    def test_skip_existing_does_not_mark_a_failed_export_current(self):
        """A failed export must leave no fresh manifest to be skipped over next time (bugs-overview BUG-11)."""
        img = os.path.join(self.folder, 'a_moon.tif')
        out = os.path.join(self.folder, 'a_moon_atlas.jpg')
        with mock.patch.object(cv2, 'imencode', return_value=(False, None)):   # the encoder refused it: write_atomic's
            code1, out1 = S.run_main('export', img, '-o', out, '--format', 'jpg')   # own OSError -> SystemExit
        self.assertIsNotNone(code1)
        self.assertFalse(os.path.exists(out + '.export.json'))
        code2, out2 = self.batch('--skip-existing')
        self.assertRegex(out2, r'a_moon\.tif +exported')

    def test_locate_only_skip_existing_consults_positioning_not_an_export_file(self):
        """bugs-overview BUG-11 item 5: a --locate-only --skip-existing run must check whether the IMAGE is
        already positioned, never an unrelated export file's mtime (there is none in locate-only mode)."""
        code, out = self.batch('-r', '--locate-only')
        self.assertRegex(out, r'a_moon\.tif +located')
        code, out = self.batch('-r', '--locate-only', '--skip-existing')
        self.assertRegex(out, r'a_moon\.tif +skipped')
        # an export file existing (from a previous, non-locate-only run) must not fool this check either way
        self.batch()
        code, out = self.batch('-r', '--locate-only', '--skip-existing')
        self.assertRegex(out, r'a_moon\.tif +skipped')


@S.needs_relief
class RecentExcludesExports(S.TempDir):
    """bugs-overview BUG-13: App.recent() used to list every image file, including LunarAtlas's own
    IMAGE_atlas….ext exports, as an unsolved photo -- sharing atlas_paths.is_export_name with batch_images()."""

    def test_an_export_file_does_not_appear_in_recent(self):
        from atlas_app import App
        img, _ = S.moon_image(self.tmp)
        code, out = S.run_main('export', img, '-o', os.path.join(self.tmp, 'moon_atlas.tif'))
        self.assertIsNone(code, out)
        rows = {r['name']: r for r in App(self.tmp, S.quiet).recent()}
        self.assertIn('moon.tif', rows)
        self.assertNotIn('moon_atlas.tif', rows)


if __name__ == '__main__':
    unittest.main()
