"""Functional tests of the individual pieces that the pipeline tests only pass through: the geometry helpers,
the label placement rules, the viewer's server-side functions and the settings registry, checked directly
against what they must produce.

test_functional_geometry.py, _render.py and _cli.py cover these modules function by function. This file covers
the ones that had no direct test at all — north_up_matrix, the graticule, the link id, the dashed pattern, the
sky level, the view mapper, the export-option mapping, find_feature, sun_elevation_light and optics_text — and
adds the properties that must hold across a whole range of inputs rather than for one example each.
"""
import json
import os
import unittest
from datetime import datetime, timezone

import _support as S
import cv2
import numpy as np

import atlas_ephem as ae
import atlas_geo as ag
import atlas_render as ar
import atlas_view as av
import lunaratlas as ma


class NorthUp(unittest.TestCase):
    """north_up_matrix: the IAU view, lunar north up and east to the right, never mirrored for a normal image."""

    def test_north_goes_up_and_east_goes_right_for_every_rotation(self):
        for theta in (0, 1, 37, 90, 179, 180, -60, -179, 270):
            geo = S.truth_geometry(theta=theta)
            M, rot, mirror = ag.north_up_matrix(geo)
            n = M @ (geo.A @ np.array([0.0, 1.0]))
            e = M @ (geo.A @ np.array([1.0, 0.0]))
            n, e = n / np.hypot(*n), e / np.hypot(*e)
            with self.subTest(theta=theta):
                self.assertAlmostEqual(float(n[0]), 0.0, places=9, msg='lunar north is straight up')
                self.assertLess(n[1], 0.0, 'and it points up the screen, where y decreases')
                self.assertGreater(float(e[0]), 0.0, 'east is to the right')
                self.assertLess(abs(e[1]), 1e-9)
                self.assertFalse(mirror, 'a normal image is never mirrored')
                self.assertLessEqual(abs(rot), 180.0, 'the rotation is the short way round')

    def test_a_mirrored_image_is_reported_and_turned_the_right_way(self):
        geo = S.truth_geometry(mirror=True, theta=200.0)
        M, rot, mirror = ag.north_up_matrix(geo)
        self.assertTrue(mirror, 'a mirrored image is reported as such')
        self.assertLess(float(np.linalg.det(M)), 0.0, 'and the matrix flips one axis to undo it')
        n = M @ (geo.A @ np.array([0.0, 1.0]))
        e = M @ (geo.A @ np.array([1.0, 0.0]))
        n, e = n / np.hypot(*n), e / np.hypot(*e)
        self.assertAlmostEqual(float(n[0]), 0.0, places=9)
        self.assertGreater(float(e[0]), 0.0, 'north up and east right even for a mirrored image')

    def test_the_rotation_turns_the_image_by_exactly_that_much(self):
        for theta in (0, 37, 90, 180, -60):
            geo = S.truth_geometry(theta=theta)
            M, rot, _ = ag.north_up_matrix(geo)
            # M is the rotation the caller must apply, so turning the image by rot must bring north up again
            n = M @ (geo.A @ np.array([0.0, 1.0]))
            n = n / np.hypot(*n)
            with self.subTest(theta=theta):
                self.assertAlmostEqual(float(n[0]), 0.0, places=9)
                self.assertLess(n[1], 0.0)
                self.assertAlmostEqual(rot, -float(theta), places=6, msg='the rotation undoes the image rotation')


class Graticule(unittest.TestCase):
    """atlas_view.graticule: 10° lines for the page's grid, split where they leave the visible hemisphere."""

    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.lines = av.graticule(cls.geo)

    def test_it_draws_parallel_and_meridian_lines_every_ten_degrees(self):
        lats = sorted({l['value'] for l in self.lines if l['kind'] == 'lat'})
        lons = sorted({l['value'] for l in self.lines if l['kind'] == 'lon'})
        self.assertEqual(lats, list(range(-80, 90, 10)))
        self.assertEqual(lons, list(range(-180, 180, 10)))
        self.assertGreater(len(self.lines), 40)

    def test_every_piece_has_points_finite_and_worth_drawing(self):
        for l in self.lines:
            with self.subTest(kind=l['kind'], value=l['value']):
                pts = np.array(l['pts'], float)
                self.assertGreaterEqual(len(pts), 2, 'a line with less than two points is not drawn')
                self.assertTrue(np.isfinite(pts).all(), 'no NaN reaches the page')

    def test_the_points_of_a_piece_are_close_together(self):
        # a piece follows one line of latitude or longitude, so consecutive points are a fraction of a degree
        for l in self.lines[:24]:
            pts = np.array(l['pts'], float)
            steps = np.hypot(*(pts[1:] - pts[:-1]).T)
            self.assertLess(steps.max(), 60.0, f'the {l["kind"]} {l["value"]} line jumps across the disk')

    def test_a_mirrored_or_rotated_image_gets_a_graticule_too(self):
        for kw in (dict(mirror=True, theta=200.0), dict(theta=90.0), dict(lat0=20.0, lon0=-40.0)):
            lines = av.graticule(S.truth_geometry(**kw))
            self.assertGreater(len(lines), 30, kw)
            self.assertTrue(all(len(l['pts']) >= 2 for l in lines), kw)


class SmallHelpers(unittest.TestCase):
    """The little functions the viewer's JavaScript ports: they must agree, value by value."""

    def test_link_id_takes_only_the_numeric_id_of_a_gazetteer_url(self):
        for url, want in (('https://planetarynames.wr.usgs.gov/Feature/1234', '1234'),
                          ('http://planetarynames.wr.usgs.gov/Feature/1234/', '1234'),
                          ('1234', '1234'), ('', ''), (None, ''),
                          ('https://example.com/Feature/abc', ''), ('a/12b', ''),
                          ('https://example.com/Feature/007', '007')):
            with self.subTest(url):
                self.assertEqual(av.link_id(url), want)

    def test_the_dashed_pattern_alternates_on_and_off(self):
        pieces = ar._dashed(np.array([[0.0, 0.0], [100.0, 0.0]]), 10, 10)
        self.assertGreaterEqual(len(pieces), 4)
        for p in pieces:
            self.assertAlmostEqual(float(np.hypot(*(p[-1] - p[0]))), 10.0, delta=1.0)
        ends = [float(p[-1][0]) for p in pieces]          # the gaps really are gaps
        starts = [float(p[0][0]) for p in pieces[1:]]
        for a, b in zip(ends, starts):
            self.assertGreater(b - a, 5.0, 'there is a gap between the pieces')

    def test_a_line_shorter_than_one_dash_is_drawn_as_it_is(self):
        self.assertEqual(len(ar._dashed(np.array([[0.0, 0.0], [5.0, 0.0]]), 10, 10)), 1)
        self.assertEqual(len(ar._dashed(np.array([[0.0, 0.0], [0.0, 0.0]]), 10, 10)), 0)

    def test_the_dashes_keep_their_length_along_a_diagonal(self):
        # the dash length is measured along the line, not along x, so a diagonal is not squashed
        pieces = ar._dashed(np.array([[0.0, 0.0], [100.0, 100.0]]), 12, 8)
        self.assertGreaterEqual(len(pieces), 6)
        for p in pieces[:-1]:                          # the last one is the remainder, shorter by nature
            self.assertAlmostEqual(float(np.hypot(*(p[-1] - p[0]))), 12.0, delta=0.5)
        self.assertLess(float(np.hypot(*(pieces[-1][-1] - pieces[-1][0]))), 12.0)

    def test_the_sky_level_is_the_brightness_outside_the_limb(self):
        yy, xx = np.mgrid[0:200, 0:200]
        r = np.hypot(xx - 100, yy - 100) / 80.0
        gray = np.where(r < 0.95, 20000.0, 3000.0)
        self.assertAlmostEqual(ar.sky_level(gray, r), 3000.0, delta=1.0)
        self.assertAlmostEqual(ar.sky_level(gray + 1000, r), 4000.0, delta=1.0, msg='the pedestal is measured, not assumed')
        self.assertEqual(ar.sky_level(np.full((200, 200), 7.0), np.zeros((200, 200))), 0.0,
                         'with no sky in view there is no pedestal to find')

    def test_the_sky_level_ignores_a_handful_of_pixels(self):
        r = np.zeros((200, 200))                          # fewer than 1% of the frame is not a sky
        r[0, 0] = 5.0
        self.assertEqual(ar.sky_level(np.full((200, 200), 9.0), r), 0.0)

    def test_the_view_mapper_maps_the_view_box_onto_the_output(self):
        # pixel centres: source pixel (x0, y0) is output pixel 0, and the box's far corner is W-1
        view = (100, 50, 0.5, 400, 300)
        to_out, scale = ar.view_mapper(view)
        self.assertAlmostEqual(scale, 0.5, places=9)
        np.testing.assert_allclose(to_out(100, 50), (-0.25, -0.25), atol=1e-9)
        np.testing.assert_allclose(to_out(100 + 400, 50 + 300), (199.75, 149.75), atol=1e-9)
        # and it is a plain scale, so it works everywhere in between
        np.testing.assert_allclose(to_out(300, 200), (99.75, 74.75), atol=1e-9)


class ExportOptions(S.TempDir, unittest.TestCase):
    """atlas_view.export_command: the dialog's JSON becomes command-line arguments, and nothing reaches a shell."""

    IMG = '/x/moon.tif'

    def args(self, **o):
        """The arguments after the interpreter and lunaratlas.py."""
        return av.export_command(self.IMG, o)[0][2:]

    def out(self, **o):
        return av.export_command(self.IMG, o)[1]

    def test_nothing_is_given_means_a_plain_tiff_next_to_the_image(self):
        self.assertEqual(self.args(), ['export', self.IMG, '--format', 'tiff', '--layers', 'none',
                                       '-o', '/x/moon_atlas.tif'])
        self.assertEqual(self.args(format='png')[-1], '/x/moon_atlas.png')
        self.assertEqual(self.args(format='jpg')[-1], '/x/moon_atlas.jpg')

    def test_the_scale_becomes_a_real_option(self):
        a = self.args(scale='half')
        self.assertEqual(a[a.index('--scale') + 1], '0.5')
        b = self.args(scale='max', max_size=2000)
        self.assertEqual(b[b.index('--max-size') + 1], '2000')
        self.assertNotIn('--scale', self.args(), 'no scale means 1:1, not a flag')
        self.assertNotIn('--max-size', self.args(scale='half'), 'the two are not sent together')

    def test_the_current_view_becomes_a_region(self):
        a = self.args(region='view', box=[10, 20, 300, 400])
        self.assertEqual(a[a.index('--region') + 1], '10,20,300,400')
        self.assertTrue(self.out(region='view', box=[10, 20, 300, 400]).endswith('_region_10_20.tif'))

    def test_a_named_feature_becomes_an_around(self):
        a = self.args(region='feature', name='Tycho', size=[500, 400])
        self.assertIn('--around=Tycho', a)
        self.assertEqual(a[a.index('--size') + 1], '500x400')
        self.assertTrue(self.out(region='feature', name='Tycho').endswith('_atlas_Tycho.tif'))

    def test_a_name_with_punctuation_in_it_is_made_safe_for_a_file_name(self):
        out = self.out(region='feature', name="Chang'e 3 / Yutu")
        self.assertTrue(out.endswith('_Chang_e_3_Yutu.tif'), out)
        self.assertNotIn('/', os.path.basename(out))

    def test_names_off_means_layers_none(self):
        a = self.args(names=False)
        self.assertEqual(a[a.index('--layers') + 1], 'none')
        self.assertEqual(self.args(layers=[])[self.args(layers=[]).index('--layers') + 1], 'none')
        b = self.args(layers=['area', 'crater', 'bogus'])
        self.assertEqual(b[b.index('--layers') + 1], 'area,crater', 'an unknown layer is dropped')
        # nothing said about layers, and no switch: the export's own default (all of them) is left alone
        self.assertEqual(self.args()[self.args().index('--layers') + 1], 'none', 'the viewer sends its own choice')
        self.assertNotIn('--layers', self.args(layers=['area', 'crater', 'lettered', 'relief', 'landing']))

    def test_each_switch_becomes_its_own_no_flag(self):
        for flag, key in (('--no-rims', 'rims'), ('--no-grid', 'grid'),
                          ('--no-drawings', 'drawings'), ('--no-info', 'info')):
            with self.subTest(flag):
                self.assertIn(flag, self.args(**{key: False}))
                self.assertNotIn(flag, self.args(**{key: True}))

    def test_numbers_are_forced_into_the_range_the_cli_accepts(self):
        a = self.args(min_px=1e9, font_scale=0.001)
        self.assertEqual(a[a.index('--min-size') + 1], '400', 'clamped to the largest the export allows')
        self.assertEqual(a[a.index('--font-scale') + 1], '0.3', 'and to the smallest')
        b = self.args(min_px=-5, font_scale=1e9)
        self.assertEqual(b[b.index('--min-size') + 1], '4')
        self.assertEqual(b[b.index('--font-scale') + 1], '5')

    def test_a_number_that_is_not_a_number_falls_back_to_the_range(self):
        # NaN and infinity are refused by the export itself; here they are clamped, which is also safe
        for o, flag, want in ((dict(min_px=float('nan')), '--min-size', '4'),
                              (dict(font_scale=float('inf')), '--font-scale', '5')):
            with self.subTest(str(o)):
                a = self.args(**o)
                self.assertEqual(a[a.index(flag) + 1], want)

    def test_a_box_that_is_not_four_numbers_is_ignored_not_passed_on(self):
        # a box the viewer could not produce is dropped, so the export falls back to the whole image
        for box in ([1, 2], 'wide', None):
            with self.subTest(repr(box)):
                a = self.args(region='view', box=box)
                self.assertNotIn('--region', a, 'no usable box means the whole image')
                self.assertTrue(a[-1].endswith('_atlas.tif'))

    def test_a_box_with_a_number_that_is_not_a_number_is_refused(self):
        with self.assertRaises((TypeError, ValueError, OverflowError)):
            av.export_command(self.IMG, dict(region='view', box=[1, 2, 3, 'x']))

    def test_a_size_that_is_not_a_number_is_refused(self):
        with self.assertRaises((TypeError, ValueError, OverflowError)):
            av.export_command(self.IMG, dict(scale='max', max_size=1e400))

    def test_only_a_font_the_viewer_offers_is_passed_on(self):
        self.assertEqual(self.args(font='Source Sans 3')[self.args(font='Source Sans 3').index('--font') + 1], 'Source Sans 3')
        self.assertNotIn('--font', self.args(font='Comic Sans'))

    def test_night_and_force(self):
        self.assertNotIn('--night', self.args())
        self.assertEqual(self.args(night='dim')[self.args(night='dim').index('--night') + 1], 'dim')
        self.assertNotIn('--night', self.args(night='never'), 'an unknown value is the default')
        self.assertIn('--force', self.args(force=True))
        self.assertNotIn('--force', self.args(force=False))

    def test_options_that_are_not_an_object_are_refused(self):
        for o in (None, 'text', [1, 2], 5, True):
            with self.subTest(repr(o)):
                with self.assertRaises(TypeError):
                    av.export_command(self.IMG, o)

    def test_no_value_is_ever_put_in_a_shell(self):
        args, out = av.export_command(self.IMG, dict(region='feature', name='a; rm -rf ~ $(whoami)'))
        self.assertIsInstance(args, list, 'the command is a list of arguments, never a string for a shell')
        self.assertIn('--around=a; rm -rf ~ $(whoami)', args, 'the name stays one argument, exactly as typed, tied to its option')
        self.assertEqual(sum('rm -rf' in a for a in args), 1, 'and it is one argument, not several')
        self.assertNotIn(';', out, 'the output name has the punctuation taken out')
        self.assertTrue(out.endswith('_atlas_a_rm_-rf_whoami.tif'), out)


class CommandLineHelpers(S.TempDir, unittest.TestCase):
    """lunaratlas.find_feature, sun_elevation_light and optics_text, checked directly."""

    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.feats = S.projected_features(cls.geo)

    def test_find_feature_matches_exactly_then_by_prefix(self):
        self.assertEqual(ma.find_feature(self.feats, 'Tycho')['name'], 'Tycho')
        self.assertEqual(ma.find_feature(self.feats, '  tycho  ')['name'], 'Tycho', 'case and spaces are forgiven')
        self.assertEqual(ma.find_feature(self.feats, 'Coper')['name'], 'Copernicus', 'a prefix finds the feature')
        for bad in ('No Such Crater', 'zzz'):
            with self.subTest(bad):
                with self.assertRaises(SystemExit) as cm:
                    ma.find_feature(self.feats, bad)
                self.assertIn('no feature named', str(cm.exception))

    def test_an_empty_name_matches_the_first_feature_rather_than_refusing(self):
        # the viewer never sends an empty name; if one arrives it finds the first feature instead of failing
        self.assertEqual(ma.find_feature(self.feats, '')['name'], self.feats[0]['name'])
        self.assertEqual(ma.find_feature(self.feats, '   ')['name'], self.feats[0]['name'])

    def test_an_exact_match_wins_over_a_prefix(self):
        names = [dict(name='Copernicus A', lat=0, lon=0), dict(name='Copernicus', lat=1, lon=1)]
        self.assertEqual(ma.find_feature(names, 'Copernicus')['name'], 'Copernicus')

    def test_sun_elevation_needs_a_capture_time_and_gives_ones_and_zeros(self):
        self.assertIsNone(ma.sun_elevation_light('/tmp/no-time-here.tif', self.feats),
                          'without a time in the name there is no way to know')
        named = os.path.join(self.tmp, '2026-09-23-2138_1-Moon.tif')
        cv2.imwrite(named, np.zeros((20, 20), np.uint8))
        light = ma.sun_elevation_light(named, self.feats)
        self.assertEqual(set(np.unique(light)), {0.0, 1.0}, 'a feature is lit or it is not')
        self.assertEqual(light.shape, (len(self.feats),))
        self.assertGreater(light.sum(), 0, 'some of the Moon is lit at any time')
        self.assertLess(light.sum(), len(self.feats), 'and some of it is not')

    def test_the_wide_feature_at_the_terminator_counts_as_lit(self):
        # the Sun's elevation is taken at the feature's rim, so a big feature straddling the terminator stays lit
        named = os.path.join(self.tmp, '2026-09-23-2138_1-Moon.tif')
        cv2.imwrite(named, np.zeros((20, 20), np.uint8))
        e = ae.ephemeris(datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc))
        past = e['sub_sun_lon'] - 90.5                     # just over 90° away: past the terminator
        small = ma.sun_elevation_light(named, [dict(lat=0.0, lon=past, diam=1.0)])
        big = ma.sun_elevation_light(named, [dict(lat=0.0, lon=past, diam=900.0)])
        self.assertEqual(float(small[0]), 0.0, 'a point past the terminator is not lit')
        self.assertEqual(float(big[0]), 1.0, 'but a crater 900 km across still reaches over it')

    def test_a_feature_with_no_diameter_is_treated_as_a_point(self):
        named = os.path.join(self.tmp, '2026-09-23-2138_1-Moon.tif')
        cv2.imwrite(named, np.zeros((20, 20), np.uint8))
        e = ae.ephemeris(datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc))
        past = e['sub_sun_lon'] - 90.5
        for diam in (0.0, -1.0, None):
            with self.subTest(diam):
                r = ma.sun_elevation_light(named, [dict(lat=0.0, lon=past, diam=diam)])
                self.assertEqual(float(r[0]), 0.0, 'a negative diameter is no diameter')

    def test_optics_text_reads_the_folder_and_survives_a_damaged_file(self):
        img = os.path.join(self.tmp, 'moon.tif')
        cv2.imwrite(img, np.zeros((20, 20), np.uint8))
        self.assertIsNone(ma.optics_text(img), 'no optics file, no line')
        p = os.path.join(self.tmp, 'lunaratlas_optics.json')
        with open(p, 'w') as fh:
            fh.write('not json')
        self.assertIsNone(ma.optics_text(img), 'a damaged file is not a reason to stop')
        with open(p, 'w') as fh:
            json.dump(dict(no_text=True), fh)
        self.assertIsNone(ma.optics_text(img), 'a file without a text line gives nothing')
        with open(p, 'w') as fh:
            json.dump(dict(text='250 PDS · 2× ES · IMX678'), fh)
        self.assertEqual(ma.optics_text(img), '250 PDS · 2× ES · IMX678')
        with open(p, 'w') as fh:
            fh.write('[1, 2]')
        self.assertIsNone(ma.optics_text(img), 'a JSON array is not an optics file')


if __name__ == '__main__':
    unittest.main()

