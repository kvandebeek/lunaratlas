"""Functional tests: label layout and drawing, overlays, the viewer's drawings, the IAU list and the quality gate."""
import json
import math
import os
import shutil
import struct
import unittest
import warnings
from unittest import mock

import _support as S
import cv2
import numpy as np

import atlas_names as an
import atlas_quality as aq
import atlas_render as ar


def boxes_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def label_box(lab):
    return (lab['x'] - lab['w'] / 2, lab['y'] - lab['h'] / 2, lab['x'] + lab['w'] / 2, lab['y'] + lab['h'] / 2)


@S.needs_font
class FontsTest(unittest.TestCase):
    def test_variable_font_weights(self):
        f = ar.Fonts('Roboto', S.quiet)
        self.assertTrue(any(x['variable'] for x in f.files))
        thin, bold = f.get(200, 30), f.get(800, 30)
        self.assertGreater(bold.getlength('Copernicus'), thin.getlength('Copernicus'))
        self.assertIs(f.get(200, 30), thin)                       # cached

    def test_italic(self):
        f = ar.Fonts('Roboto', S.quiet)
        self.assertTrue(f.has_italic)
        self.assertNotEqual(f.get(400, 20, True).getbbox('Rima'), f.get(400, 20, False).getbbox('Rima'))

    def test_static_family_picks_the_nearest_weight(self):
        f = ar.Fonts('Barlow', S.quiet)
        self.assertFalse(any(x['variable'] for x in f.files))
        self.assertIn(os.path.basename(f.get(560, 12).path), ('Barlow-Medium.ttf', 'Barlow-SemiBold.ttf'))
        self.assertEqual(os.path.basename(f.get(300, 12).path), 'Barlow-Light.ttf')

    def test_tracking_widens_text(self):
        font = ar.Fonts('Roboto', S.quiet).get(300, 20)
        w0, h0 = ar._text_size(font, 'MARE', 0)
        w1, h1 = ar._text_size(font, 'MARE', 0.22)
        self.assertAlmostEqual(w1 - sum(font.getlength(c) for c in 'MARE'), 0.22 * 20 * 3, places=6)
        self.assertEqual(h0, h1)


class Primitives(unittest.TestCase):
    def test_hex_rgba(self):
        self.assertEqual(ar.hex_rgba('#ffb45a'), (255, 180, 90, 255))
        self.assertEqual(ar.hex_rgba('00ff00', 7), (0, 255, 0, 7))
        for bad in (None, '', '#zzzzzz', '#abc', 'red'):
            self.assertEqual(ar.hex_rgba(bad), (255, 255, 255, 255))

    def test_view_mapper(self):
        f, s = ar.view_mapper((100, 50, 0.5, 200, 100))
        x, y = f(100, 50)
        self.assertAlmostEqual(float(x), -0.25)                 # pixel centres, as cv2.resize
        self.assertAlmostEqual(float(y), -0.25)
        self.assertEqual(s, 0.5)
        f, s = ar.view_mapper((0, 0, (0.5, 0.25), 10, 10))
        self.assertAlmostEqual(s, math.sqrt(0.125))

    def test_fmt_km(self):
        self.assertEqual(ar.fmt_km(1234.5), '1234 km')          # no thousands separator
        self.assertEqual(ar.fmt_km(12.34), '12.3 km')
        self.assertEqual(ar.fmt_km(1.234), '1.23 km')
        self.assertEqual(ar.fmt_km(0), '0.00 km')

    def test_dashed_pattern(self):
        pts = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]])
        pieces = ar._dashed(pts, 7, 5)
        drawn = sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p in pieces)
        self.assertAlmostEqual(drawn, 150 * 7 / 12, delta=7)
        self.assertTrue(all(float(np.hypot(*np.diff(p, axis=0).T).sum()) <= 7 + 1e-6 for p in pieces))

    def test_rim_polygon_size(self):
        g = S.truth_geometry()
        pts, z = ar.rim_polygon(g, g.lat0, g.lon0, 100.0, 64)
        x, y, _ = g.to_image(g.lat0, g.lon0)
        r = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        # perspective: at the sub-observer point everything is D / (D - 1) larger than on the limb plane
        self.assertAlmostEqual(float(r.mean()), 50 / ar.R_MOON * g.radius_px * g.dist / (g.dist - 1), delta=0.01)
        self.assertTrue((z > 0.99).all())

    def test_geodesic_one_degree_on_the_equator(self):
        g = S.truth_geometry(lat0=0.0, lon0=0.0)
        a = [float(v) for v in g.to_image(0.0, 0.0)[:2]]
        b = [float(v) for v in g.to_image(0.0, 1.0)[:2]]
        pts, km = ar.geodesic_px(g, a, b)
        self.assertAlmostEqual(km, 2 * math.pi * ar.R_MOON / 360, delta=1e-6)
        self.assertEqual(pts.shape, (64, 2))
        np.testing.assert_allclose(pts[0], a, atol=1e-6)
        np.testing.assert_allclose(pts[-1], b, atol=1e-6)

    def test_geodesic_off_disk(self):
        g = S.truth_geometry()
        self.assertEqual(ar.geodesic_px(g, (0, 0), (560, 490)), (None, None))


class CleanShapes(unittest.TestCase):
    def test_every_kind(self):
        ok = [dict(kind='circle', cx=1, cy=2, r=3), dict(kind='ellipse', x0=0, y0=0, x1=5, y1=3),
              dict(kind='rect', x0=0, y0=0, x1=5, y1=3), dict(kind='arrow', x0=0, y0=0, x1=5, y1=3),
              dict(kind='text', x=4, y=5, label='hi'), dict(kind='outline', pts=[[0, 0], [1, 1], [2, 0]], closed=True),
              dict(kind='measure', a=dict(x=1, y=2), b=dict(x=3, y=4))]
        for s in ok:
            c = ar.clean_shape(s)
            self.assertIsNotNone(c, s)
            self.assertEqual(c['kind'], s['kind'])

    def test_only_known_typed_fields(self):
        c = ar.clean_shape(dict(kind='circle', cx=1, cy=2, r=3, colour='#fff', size=10, label='x' * 900, font='Inter',
                                dash=1, evil='<script>', hover=[1, 2]))
        self.assertEqual(set(c), {'kind', 'cx', 'cy', 'r', 'colour', 'size', 'label', 'font', 'dash'})
        self.assertEqual(c['size'], 3.0)                          # clamped
        self.assertEqual(len(c['label']), 500)
        self.assertIs(c['dash'], True)
        self.assertIsInstance(c['cx'], float)

    def test_rejects(self):
        for s in (None, [], 'circle', dict(kind='star', x=1, y=1), dict(kind='circle', cx=1, cy=2),
                  dict(kind='circle', cx=True, cy=2, r=3), dict(kind='circle', cx='1', cy=2, r=3),
                  dict(kind='circle', cx=float('nan'), cy=2, r=3), dict(kind='circle', cx=1, cy=2, r=-1),
                  dict(kind='outline', pts=[[0, 0]]), dict(kind='outline', pts=[[0, 0], [1]]),
                  dict(kind='outline', pts='abc'), dict(kind='measure', a=dict(x=1, y=2)),
                  dict(kind='measure', a=dict(x=1, y=2), b=[3, 4])):
            self.assertIsNone(ar.clean_shape(s), s)

    def test_label_override(self):
        self.assertEqual(ar.clean_label_override(dict(dx=1, dy=-2.5, colour='#aabbcc', size=0.1, junk=1)),
                         dict(dx=1.0, dy=-2.5, colour='#aabbcc', size=0.5))
        self.assertEqual(ar.clean_label_override(dict(dx=1)), None)            # half a move is no move
        self.assertEqual(ar.clean_label_override(dict(dx=1, colour='')), None)
        self.assertIsNone(ar.clean_label_override('x'))


@S.needs_all
class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.feats = S.projected_features(cls.geo)
        cls.fonts = ar.Fonts('Roboto', S.quiet)
        cls.view = (0, 0, 1.0, S.DISK['W'], S.DISK['H'])

    def place(self, **kw):
        return ar.layout(self.feats, self.geo, self.view, self.fonts, **kw)

    def names(self, labels):
        return {self.feats[l['feature']]['name'] for l in labels}

    def test_labels_do_not_overlap_and_stay_on_the_disk(self):
        labels = self.place()
        self.assertGreater(len(labels), 30)
        boxes = [label_box(l) for l in labels]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                self.assertFalse(boxes_overlap(boxes[i], boxes[j]), (labels[i]['text'], labels[j]['text']))
        cx, cy = self.geo.t
        for b in boxes:
            self.assertTrue(0 <= b[0] and b[2] <= S.DISK['W'] and 0 <= b[1] and b[3] <= S.DISK['H'])
            for px in (b[0], b[2]):
                for py in (b[1], b[3]):
                    self.assertLess(math.hypot(px - cx, py - cy), self.geo.radius_px)

    def test_maria_first_in_spaced_capitals(self):
        labels = self.place()
        area = [l for l in labels if self.feats[l['feature']]['cls'] == 'area']
        self.assertTrue(area)
        self.assertTrue(all(l['text'] == l['text'].upper() and l['track'] > 0 for l in area))
        self.assertIn('MARE IMBRIUM', {l['text'] for l in area})
        self.assertEqual(self.feats[labels[0]['feature']]['cls'], 'area')

    def test_one_label_colour(self):
        self.assertEqual({l['colour'][:3] for l in self.place()}, {ar.LABEL_RGB})

    def test_detail_level(self):
        n = [len(self.place(min_px=m)) for m in (12, 24, 48, 96)]
        self.assertEqual(n, sorted(n, reverse=True))
        self.assertGreater(n[0], n[-1])

    def test_font_scale(self):
        a = {l['text']: l['size'] for l in self.place()}
        b = {l['text']: l['size'] for l in self.place(font_scale=1.5)}
        common = set(a) & set(b)
        self.assertTrue(common)
        self.assertTrue(all(b[t] >= a[t] for t in common))

    def test_layers(self):
        only = self.place(layers=('crater',))
        self.assertTrue(only)
        self.assertEqual({self.feats[l['feature']]['cls'] for l in only}, {'crater'})
        self.assertEqual(self.place(layers=()), [])

    def test_hidden_names(self):
        self.assertIn('Copernicus', self.names(self.place()))
        self.assertNotIn('Copernicus', self.names(self.place(hidden=['Copernicus'])))

    def test_moved_and_restyled_label(self):
        base = next(l for l in self.place() if l['text'] == 'Copernicus')
        ov = {'Copernicus': dict(dx=30.0, dy=-12.0, colour='#ff0000', size=1.5)}
        lab = next(l for l in self.place(overrides=ov) if l['text'] == 'Copernicus')
        self.assertEqual(lab['colour'][:3], (255, 0, 0))
        self.assertGreater(lab['size'], base['size'])
        f = self.feats[lab['feature']]
        pts, _ = ar.rim_polygon(self.geo, f['lat'], f['lon'], f['diam'], 40)
        home_y = pts[:, 1].max() + 4 + lab['h'] / 2          # the first spot: centred under the rim
        self.assertAlmostEqual(lab['x'], f['x'] + 30.0, delta=1e-6)
        self.assertAlmostEqual(lab['y'], home_y - 12.0, delta=1e-6)

    def test_a_moved_name_keeps_a_line_to_its_feature(self):
        self.assertFalse(any('leader' in l for l in self.place()), 'names left in place have no line')
        lab = next(l for l in self.place(overrides={'Copernicus': dict(dx=120.0, dy=90.0)}) if l['text'] == 'Copernicus')
        f = self.feats[lab['feature']]
        (fx, fy), (ex, ey) = lab['leader']
        self.assertAlmostEqual(fx, f['x'], delta=1e-6)
        self.assertAlmostEqual(fy, f['y'], delta=1e-6)
        self.assertAlmostEqual(ex, lab['x'] - lab['w'] / 2, delta=1e-6)      # it ends on the name's edge, not across it
        self.assertAlmostEqual(ey, lab['y'] - lab['h'] / 2, delta=1e-6)
        img = np.zeros((1000, 1200, 3), np.uint8)
        ar.draw(img, [lab], self.fonts)
        mx, my = int(round((fx + ex) / 2)), int(round((fy + ey) / 2))
        near = img[my - 3:my + 4, mx - 3:mx + 4].reshape(-1, 3)
        self.assertTrue(any(b < 150 < r for b, _, r in near), 'the line is drawn in amber in the export')

    def test_reserved_boxes_stay_free(self):
        box = (300.0, 250.0, 800.0, 700.0)
        for l in self.place(reserved=[box]):
            self.assertFalse(boxes_overlap(label_box(l), box), l['text'])

    def test_night_side(self):
        light = np.ones(len(self.feats))
        i = next(k for k, f in enumerate(self.feats) if f['name'] == 'Copernicus')
        light[i] = 0.0
        self.assertNotIn('Copernicus', self.names(self.place(light=light, night='hide')))
        dim = next(l for l in self.place(light=light, night='dim') if l['text'] == 'Copernicus')
        self.assertLess(dim['colour'][3], 150)
        self.assertIn('Copernicus', self.names(self.place(light=light, night='show')))

    def test_an_unknown_or_malformed_light_array_is_treated_as_no_dimming(self):
        """BUG-07: layout() only checked `light is not None` before indexing light[i]; a stale cache, or any
        array for a different feature list, could IndexError or silently misassociate values. Anything that is
        not exactly one finite value per feature is now treated the same as light=None."""
        baseline = self.names(self.place(night='hide'))
        for bad in (np.ones(len(self.feats) - 1), np.ones(len(self.feats) + 3),
                   np.array([float('nan')] * len(self.feats)), [1.0, 2.0], 'not an array', 5):
            with self.subTest(repr(bad)[:40]):
                self.assertEqual(self.names(self.place(light=bad, night='hide')), baseline)

    def test_landing_sites_only_when_zoomed_in(self):
        self.assertFalse(any(self.feats[l['feature']]['cls'] == 'landing' for l in self.place()))   # 3.9 km/px
        g = self.geo
        x, y, _ = g.to_image(0.674, 23.473)                        # Apollo 11
        big = g.resized(4.0)
        feats = S.projected_features(big)
        X, Y = (float(x) + 0.5) * 4 - 0.5, (float(y) + 0.5) * 4 - 0.5
        labels = ar.layout(feats, big, (int(X) - 400, int(Y) - 300, 1.0, 800, 600), self.fonts)
        landing = [l for l in labels if feats[l['feature']]['cls'] == 'landing']
        self.assertIn('Apollo 11', {l['text'] for l in landing})
        self.assertTrue(all('marker' in l for l in landing))

    def test_crater_rims(self):
        with_rims = [l for l in self.place() if 'rim' in l]
        self.assertTrue(with_rims)
        self.assertFalse(any('rim' in l for l in self.place(rims=False)))

    def test_bad_override_and_hidden_types_are_ignored(self):
        self.assertEqual(len(self.place(overrides=['x'], hidden={'a': 1})), len(self.place()))
        self.assertEqual(len(self.place(overrides={'Copernicus': 'bad'})), len(self.place()))

    def test_scaled_view(self):
        view = (0, 0, 0.5, S.DISK['W'] // 2, S.DISK['H'] // 2)
        labels = ar.layout(self.feats, self.geo, view, self.fonts)
        self.assertTrue(labels)
        self.assertTrue(all(0 <= l['x'] <= view[3] and 0 <= l['y'] <= view[4] for l in labels))


@S.needs_all
class Drawing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.feats = S.projected_features(cls.geo)
        cls.fonts = ar.Fonts('Roboto', S.quiet)
        cls.labels = ar.layout(cls.feats, cls.geo, (0, 0, 1.0, S.DISK['W'], S.DISK['H']), cls.fonts)

    def test_draw_in_place_uint16_and_uint8(self):
        for dtype, top in ((np.uint16, 65535), (np.uint8, 255)):
            img = np.full((S.DISK['H'], S.DISK['W'], 3), top // 4, dtype)
            out = ar.draw(img, self.labels, self.fonts)
            self.assertIs(out, img)
            self.assertEqual(img.dtype, dtype)
            self.assertGreater(int(img.max()), top // 2)             # light letters
            self.assertLess(int(img.min()), top // 4)                # the soft shadow darkens

    def test_only_near_labels_changes(self):
        img = np.full((S.DISK['H'], S.DISK['W'], 3), 1000, np.uint16)
        lab = [l for l in self.labels if 'rim' not in l][:1]
        ar.draw(img, lab, self.fonts)
        diff = np.argwhere((img != 1000).any(-1))
        x0, y0, x1, y1 = label_box(lab[0])
        self.assertTrue(len(diff))
        self.assertGreaterEqual(diff[:, 1].min(), x0 - 20)
        self.assertLessEqual(diff[:, 1].max(), x1 + 20)
        self.assertGreaterEqual(diff[:, 0].min(), y0 - 20)
        self.assertLessEqual(diff[:, 0].max(), y1 + 20)

    def test_nothing_to_draw(self):
        img = np.full((300, 400, 3), 1234, np.uint16)
        ar.draw(img, [], self.fonts)
        self.assertTrue((img == 1234).all())

    def test_tiles_join_seamlessly(self):
        a = np.full((S.DISK['H'], S.DISK['W'], 3), 3000, np.uint16)
        b = a.copy()
        ar.draw(a, self.labels, self.fonts, tile=2048)
        ar.draw(b, self.labels, self.fonts, tile=256)
        self.assertLessEqual(int(np.abs(a.astype(int) - b.astype(int)).max()), 1)

    def test_lines_fill_and_dash(self):
        img = np.zeros((200, 200, 3), np.uint8)
        sq = np.array([[20, 20], [180, 20], [180, 180], [20, 180]], float)
        ar.draw(img, [], self.fonts, lines=[dict(pts=sq, fill=(0, 0, 255, 255), colour=None, width=0)])
        self.assertEqual(tuple(img[100, 100]), (255, 0, 0))                     # RGBA red -> BGR
        img = np.zeros((200, 200, 3), np.uint8)
        ar.draw(img, [], self.fonts, lines=[dict(pts=np.array([[10, 100], [190, 100]], float), colour=(255, 255, 255, 255),
                                                 width=2, dash=(7, 5))])
        row = img[100, 10:190, 0] > 128
        self.assertTrue(0.45 < row.mean() < 0.75)                               # 7 on, 5 off


@S.needs_all
class Overlays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = S.truth_geometry()
        cls.fonts = ar.Fonts('Roboto', S.quiet)
        cls.view = (0, 0, (1.0, 1.0), S.DISK['W'], S.DISK['H'])

    def test_grid(self):
        lines, labels = ar.grid_overlay(self.geo, self.view, self.fonts)
        self.assertGreater(len(lines), 20)
        texts = {l['text'] for l in labels}
        self.assertIn('0°', texts)
        self.assertTrue({'10° N', '10° S', '10° E', '10° W'} <= texts, texts)

    def test_info_block(self):
        lines, labels, box = ar.info_block(self.geo, self.view, self.fonts, date='2026-09-23 21:38 UTC', optics='250 PDS')
        texts = [l['text'] for l in labels]
        self.assertIn('2026-09-23 21:38 UTC', texts)
        self.assertIn(f'{self.geo.km_per_px:.2f} km/px', texts)
        self.assertIn('N', texts)
        self.assertIn('E', texts)
        bar_km = int(next(t for t in texts if t.endswith(' km')).split()[0])
        bar = lines[1]['pts']
        self.assertAlmostEqual(float(bar[1, 0] - bar[0, 0]), bar_km / self.geo.km_per_px, places=6)
        x0, y0, x1, y1 = box
        self.assertTrue(0 < x0 < x1 < S.DISK['W'] and 0 < y0 < y1 < S.DISK['H'])
        self.assertGreater(y0, S.DISK['H'] / 2)                  # bottom left

    def test_info_block_north_arrow_follows_the_image(self):
        _, labels, _ = ar.info_block(self.geo, self.view, self.fonts)
        n = next(l for l in labels if l['text'] == 'N')
        e = next(l for l in labels if l['text'] == 'E')
        d = self.geo.A @ [0, 1]
        cx = (n['x'] + e['x']) / 2
        self.assertEqual(n['x'] > cx, (self.geo.A @ [0, 1])[0] > (self.geo.A @ [1, 0])[0])
        self.assertTrue(np.isfinite(d).all())

    def test_shapes_overlay(self):
        g = self.geo
        cx, cy = g.t
        shapes = [dict(kind='circle', cx=cx, cy=cy, r=40, colour='#ffb45a', label='ring'),
                  dict(kind='ellipse', x0=cx - 50, y0=cy - 20, x1=cx + 50, y1=cy + 20, dash=True),
                  dict(kind='rect', x0=cx - 60, y0=cy - 60, x1=cx + 60, y1=cy + 60),
                  dict(kind='outline', pts=[[cx, cy], [cx + 30, cy], [cx + 30, cy + 30]], closed=True),
                  dict(kind='arrow', x0=cx, y0=cy, x1=cx + 80, y1=cy - 40, label='look'),
                  dict(kind='text', x=cx + 100, y=cy, label='note'),
                  dict(kind='measure', a=dict(x=cx - 100, y=cy), b=dict(x=cx + 100, y=cy))]
        lines, labels = ar.shapes_overlay(shapes, g, self.view, lambda fam: self.fonts)
        texts = [l['text'] for l in labels]
        self.assertEqual(texts[:3], ['ring', 'look', 'note'])
        km = next(t for t in texts if t.endswith(' km'))
        _, want = ar.geodesic_px(g, (cx - 100, cy), (cx + 100, cy))
        self.assertEqual(km, ar.fmt_km(want))
        self.assertGreaterEqual(len(lines), 9)                   # 5 outlines + arrow shaft and head + measure + 2 ends
        ell = next(l for l in lines if l.get('dash'))
        self.assertEqual(ell['pts'].shape, (96, 2))

    def test_shapes_overlay_skips_what_it_cannot_draw(self):
        g = self.geo
        lines, labels = ar.shapes_overlay([dict(kind='measure', a=dict(x=0, y=0), b=dict(x=1, y=1)),     # off the disk
                                           dict(kind='nope'), 'junk', dict(kind='circle', cx=1, cy=1)],
                                          g, self.view, lambda fam: self.fonts)
        self.assertEqual((lines, labels), ([], []))
        self.assertEqual(ar.shapes_overlay('not a list', g, self.view, lambda fam: self.fonts), ([], []))


@S.needs_relief
class LightLevels(unittest.TestCase):
    def test_night_and_day(self):
        img, geo = S.synthetic_moon(sun=(0.0, 35.0))
        raw = S.encode(img)
        feats = [dict(cls='crater', diam=40.0, lat=0.0, lon=40.0), dict(cls='crater', diam=40.0, lat=0.0, lon=-60.0),
                 dict(cls='area', diam=500.0, lat=10.0, lon=50.0)]
        xy = [tuple(float(v) for v in geo.to_image(f['lat'], f['lon'])[:2]) for f in feats]
        light = ar.light_levels(raw, geo, feats, xy)
        self.assertGreater(light[0], 0.3)
        self.assertLess(light[1], 0.12)                          # the night-side threshold of layout()
        self.assertGreater(light[2], 0.3)


@S.needs_features
class Names(S.TempDir, unittest.TestCase):
    def test_gazetteer(self):
        feats = an.load_features(S.quiet, sites=False)
        self.assertGreater(len(feats), 9000)
        names = {f['name'] for f in feats}
        for n in ('Copernicus', 'Mare Imbrium', 'Rupes Recta', 'Tycho', 'Copernicus A'):
            self.assertIn(n, names)
        for f in feats:
            self.assertTrue(-90 <= f['lat'] <= 90 and -180 <= f['lon'] < 180 and f['diam'] >= 0, f)
            self.assertIn(f['cls'], ('area', 'crater', 'lettered', 'relief', 'site', 'apollo'))
        cop = next(f for f in feats if f['name'] == 'Copernicus')
        self.assertAlmostEqual(cop['lat'], 9.62, delta=0.05)
        self.assertAlmostEqual(cop['lon'], -20.08, delta=0.05)          # east longitudes, -180..180
        self.assertAlmostEqual(cop['diam'], 96, delta=2)

    def test_every_feature_type_has_a_style(self):
        dbf = os.path.join(S.DATA, 'iau', 'MOON_nomenclature_center_pts.dbf')
        if not os.path.exists(dbf):
            self.skipTest('IAU DBF not in lunaratlas/data')
        types = {r['type'] for r in an._read_dbf(dbf)}
        self.assertEqual(types - set(an.CLASS), set(), 'a new IAU feature type falls back to "relief"')

    def test_landing_sites(self):
        feats = an.load_features(S.quiet, sites=True)
        sites = [f for f in feats if f['cls'] == 'landing']
        self.assertEqual(len(sites), len(an.SITES))
        self.assertEqual(len({f['name'] for f in sites}), len(sites))
        a11 = next(f for f in sites if f['name'] == 'Apollo 11')
        self.assertAlmostEqual(a11['lat'], 0.674, places=3)
        self.assertTrue(all(abs(f['lon']) <= 90 for f in sites))            # near side only

    def test_sites_are_not_added_twice(self):
        a = an.load_features(S.quiet, sites=True)
        b = an.load_features(S.quiet, sites=True)
        self.assertEqual(len(a), len(b))


def write_dbf(path, rows, deleted=(), fields=(('name', 40), ('type', 30), ('center_lat', 20), ('center_lon', 20),
                                                ('diameter', 20), ('origin', 60), ('link', 60))):
    """A dBASE III file like the USGS gazetteer's (character fields only)."""
    hl = 32 + 32 * len(fields) + 1
    rl = 1 + sum(n for _, n in fields)
    out = bytearray(struct.pack('<B3BIHH20x', 3, 126, 9, 28, len(rows), hl, rl))
    for name, n in fields:
        out += name.encode().ljust(11, b'\0') + b'C' + b'\0' * 4 + bytes([n, 0]) + b'\0' * 14
    out += b'\r'
    for i, r in enumerate(rows):
        out += b'*' if i in deleted else b' '
        for name, n in fields:
            out += str(r.get(name, '')).encode('utf-8').ljust(n)[:n]
    out += b'\x1a'
    with open(path, 'wb') as fh:
        fh.write(out)


class Dbf(S.TempDir, unittest.TestCase):
    ROWS = [dict(name='Alpha', type='Crater, craters', center_lat='10.5', center_lon='350.0', diameter='12.5', origin='A',
                 link='http://x/Feature/1'),
            dict(name='Gone', type='Crater, craters', center_lat='0', center_lon='0', diameter='1'),
            dict(name='Mare Beta', type='Mare, maria', center_lat='-5', center_lon='20', diameter=''),
            dict(name='', type='Crater, craters', center_lat='0', center_lon='0', diameter='1'),
            dict(name='Lacus Ünï', type='Lacus, lacūs', center_lat='1', center_lon='180', diameter='3')]

    def test_read(self):
        p = os.path.join(self.tmp, 'g.dbf')
        write_dbf(p, self.ROWS, deleted={1})
        rows = an._read_dbf(p)
        self.assertEqual([r['name'] for r in rows], ['Alpha', 'Mare Beta', '', 'Lacus Ünï'])
        self.assertEqual(rows[0]['center_lon'], '350.0')

    def test_truncated(self):
        p = os.path.join(self.tmp, 'g.dbf')
        write_dbf(p, self.ROWS)
        with open(p, 'rb') as fh:
            b = fh.read()
        for n in (10, 40, len(b) - 60):
            with open(p, 'wb') as fh:
                fh.write(b[:n])
            with self.assertRaises(ValueError):
                an._read_dbf(p)

    def test_build_json(self):
        dbf, js = os.path.join(self.tmp, 'g.dbf'), os.path.join(self.tmp, 'features.json')
        write_dbf(dbf, self.ROWS)
        with mock.patch.object(an, 'GAZ_DBF', dbf), mock.patch.object(an, 'GAZ_JSON', js):
            feats = an._build_json(S.quiet)
            self.assertEqual([f['name'] for f in feats], ['Alpha', 'Gone', 'Mare Beta', 'Lacus Ünï'])
            self.assertEqual(feats[0]['lon'], -10.0)                   # 350° east -> -10°
            self.assertEqual(feats[3]['lon'], -180.0)
            self.assertEqual(feats[2]['cls'], 'area')
            self.assertEqual(feats[2]['diam'], 0.0)
            with open(js, encoding='utf-8') as fh:
                self.assertEqual(json.load(fh), feats)
            again = an.load_features(S.quiet, sites=False)            # from the JSON now
            self.assertEqual(again, feats)


class QualityVerdict(unittest.TestCase):
    T = dict(aq.PROVISIONAL, version='test', chroma=20.0, fringe_rel=0.75, min_fine_detail=0.1)
    GOOD = dict(saturated_largest_patch=0.0, saturated_share=0.0, edge_width_px=2.0, edge_width_km=7.0, undershoot=0.0,
                overshoot=0.0, mare_noise=0.01, jpeg_blocking=1.0, chroma=2.0, fringe_px=0.1, fringe_rel=0.05,
                posterisation=0.0, fine_detail=0.5, dtype='uint16')

    def test_good_image(self):
        ok, reasons, line = aq.verdict(self.GOOD, self.T)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertTrue(line.startswith('quality OK'))
        self.assertIn('limb 2.0 px (7.00 km)', line)

    def test_each_limit(self):
        for key, value, word in (('saturated_largest_patch', 0.05, 'overexposed'), ('edge_width_px', 30.0, 'blurry'),
                                 ('undershoot', 0.5, 'over-sharpened'), ('overshoot', 1.5, 'over-sharpened'),
                                 ('mare_noise', 0.5, 'noisy'), ('jpeg_blocking', 3.0, 'JPEG'), ('chroma', 60.0, 'colour'),
                                 ('fringe_rel', 2.0, 'fringes'), ('posterisation', 0.9, 'posterised'),
                                 ('fine_detail', 0.01, 'fine detail')):
            ok, reasons, line = aq.verdict(dict(self.GOOD, **{key: value}), self.T)
            self.assertFalse(ok, key)
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn(word, reasons[0])
            self.assertIn('quality refused', line)

    def test_missing_measures_never_refuse(self):
        for v in (None, float('nan')):
            q = {k: v for k in self.GOOD if k not in ('dtype', 'saturated_share')}
            self.assertTrue(aq.verdict(q, self.T)[0], v)

    def test_unused_limit(self):
        t = dict(self.T, chroma=None)
        self.assertTrue(aq.verdict(dict(self.GOOD, chroma=1e6), t)[0])

    def test_provisional_tag(self):
        self.assertIn('(provisional limits)', aq.verdict(self.GOOD, dict(aq.PROVISIONAL))[2])
        self.assertNotIn('provisional', aq.verdict(self.GOOD, self.T)[2])

    def test_thresholds_file(self):
        t = aq.thresholds()
        self.assertTrue(set(aq.PROVISIONAL) <= set(t))


class QualityMeasures(unittest.TestCase):
    H = W = 1200
    CX = CY = 600.2
    R = 450.0

    def base(self):
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        return ((xx - self.CX) ** 2 + (yy - self.CY) ** 2 < self.R ** 2).astype(np.float32)

    def texture(self, seed=0):
        return cv2.GaussianBlur(np.random.default_rng(seed).normal(0, 1, (self.H, self.W)).astype(np.float32), (0, 0), 3)

    def test_limb_edge_width_of_a_gaussian_blur(self):
        for sigma in (1.5, 3.0, 6.0):
            img = cv2.GaussianBlur(self.base(), (0, 0), sigma) * (0.6 + 0.05 * self.texture()) * 50000 + 800
            with warnings.catch_warnings():
                warnings.simplefilter('error', RuntimeWarning)
                lp = aq.limb_profile(img, self.CX, self.CY, self.R)
            self.assertAlmostEqual(lp['edge_width_px'], 2.5631 * sigma, delta=0.1 * sigma + 0.2)     # 10-90 % of a Gaussian
            self.assertLess(abs(lp['overshoot']), 0.12)
            self.assertLess(abs(lp['undershoot']), 0.06)

    def test_limb_profile_with_a_radius_offset_emits_no_all_nan_warning(self):
        """BUG-16: the fitted circle is only good to a few native pixels (limb_profile's own docstring), so a
        real sign-consistent offset between the fit and the true limb -- not blur -- is what pushes some aligned
        rows' padding to land in the same column for every angle. Confirmed already fixed in this tree: the
        finite-column mask is computed before nanmedian and applied to both the profile and its coordinate (t),
        so no column nanmedian ever sees is all-NaN. This locks that in."""
        for dR in (0.0, 1.0, 3.0):
            img = cv2.GaussianBlur((((np.mgrid[0:self.H, 0:self.W][1].astype(np.float32) - self.CX) ** 2 +
                                     (np.mgrid[0:self.H, 0:self.W][0].astype(np.float32) - self.CY) ** 2) <
                                    (self.R + dR) ** 2).astype(np.float32), (0, 0), 1.0) * 50000 + 800
            with self.subTest(dR=dR), warnings.catch_warnings():
                warnings.simplefilter('error', RuntimeWarning)
                lp = aq.limb_profile(img, self.CX, self.CY, self.R)
            self.assertIsNotNone(lp)
            self.assertTrue(math.isfinite(lp['edge_width_px']))

    def test_oversharpening_halo(self):
        img = cv2.GaussianBlur(self.base(), (0, 0), 2)
        usm = img + 2.0 * (img - cv2.GaussianBlur(img, (0, 0), 4))
        lp = aq.limb_profile(usm * 40000 + 5000, self.CX, self.CY, self.R)
        self.assertGreater(lp['overshoot'], 0.2)
        self.assertGreater(lp['undershoot'], 0.2)

    def test_saturation(self):
        img = self.base() * 30000
        img[500:560, 500:560] = 65535
        m = img > 1000
        s = aq.saturation(img.astype(np.uint16), m)
        self.assertAlmostEqual(s['saturated_largest_patch'], 3600 / m.sum(), places=4)
        self.assertEqual(aq.saturation((self.base() * 100).astype(np.uint16), m)['saturated_share'], 0.0)

    def test_mare_noise_grows_with_noise(self):
        rng = np.random.default_rng(0)
        m = np.ones((self.H, self.W), bool)
        vals = [aq.mare_noise((0.5 + n * rng.normal(0, 1, (self.H, self.W))).astype(np.float32) * 40000, m)
                for n in (0.002, 0.01, 0.05)]
        self.assertEqual(vals, sorted(vals))
        self.assertAlmostEqual(vals[1] / vals[0], 5, delta=1)

    def test_jpeg_blocking(self):
        t8 = np.clip((0.5 + 0.2 * self.texture()) * 255, 0, 255).astype(np.uint8)
        self.assertAlmostEqual(aq.jpeg_blocking(t8), 1.0, delta=0.05)
        worst = cv2.imdecode(cv2.imencode('.jpg', t8, [cv2.IMWRITE_JPEG_QUALITY, 8])[1], 0)
        best = cv2.imdecode(cv2.imencode('.jpg', t8, [cv2.IMWRITE_JPEG_QUALITY, 95])[1], 0)
        self.assertGreater(aq.jpeg_blocking(worst), 3)
        self.assertLess(aq.jpeg_blocking(best), 1.3)

    def test_posterisation(self):
        # posterisation() now returns (score or None, diagnostic or None); 8-bit keeps the original calibrated
        # score and never gets a diagnostic (bugs-overview BUG-09 only concerns above-8-bit data)
        t8 = np.clip((0.5 + 0.2 * self.texture()) * 255, 0, 255).astype(np.uint8)
        m = np.ones(t8.shape, bool)
        self.assertEqual(aq.posterisation(t8.astype(np.float32), m, t8), (0.0, None))
        p = t8 // 4 * 4
        score, diag = aq.posterisation(p.astype(np.float32), m, p)
        self.assertGreater(score, 0.6)
        self.assertIsNone(diag)
        self.assertEqual(aq.posterisation(t8.astype(np.float32), np.zeros_like(m), t8), (None, None))

    def test_posterisation_above_8_bits_is_diagnostic_not_a_rejection(self):
        """BUG-09: a dim 10/12-bit capture stored in 16-bit has real, expected gaps every native quantisation
        step; the old 1-unit-step count misread that as posterisation. An 8-bit image stretched to 16-bit spans
        far more than the old 4096-unit shortcut and used to evade detection entirely. Both now get a diagnostic,
        never a score that verdict() could reject on."""
        rng = np.random.default_rng(3)
        m = np.ones((300, 300), bool)
        # a native 12-bit sensor value (step 16): dim, but not destructively quantised -- the per-packet
        # acceptance case that must not be refused. The ADC itself only ever outputs multiples of the step, so
        # unlike real photon/read noise (which the sensor already baked into which 12-bit code each pixel got),
        # nothing here should land between steps
        dim12 = (rng.integers(100, 800, (300, 300)) // 16 * 16).astype(np.float32)
        score, diag = aq.posterisation(dim12, m, dim12.astype(np.uint16))
        self.assertIsNone(score, 'ambiguous bit depth: never a hard rejection')
        self.assertIsNotNone(diag)
        self.assertAlmostEqual(diag['step'], 16, delta=4)
        # smooth native 16-bit data: no detectable step at all
        smooth = (rng.normal(20000, 1500, (300, 300))).astype(np.float32)
        score, diag = aq.posterisation(smooth, m, smooth.astype(np.uint16))
        self.assertIsNone(score)
        self.assertLessEqual((diag or {}).get('step', 0), 1.5)
        # an 8-bit ramp stretched by 257 into 16-bit: far outside the old 4096-unit range, used to score 0.0
        # (confidently "not posterised") with no way to tell; now a diagnostic, still never a hard rejection
        ramp8 = (rng.integers(0, 256, (300, 300)) * 257).astype(np.float32)
        score, diag = aq.posterisation(ramp8, m, ramp8.astype(np.uint16))
        self.assertIsNone(score)
        self.assertIsNotNone(diag)
        self.assertAlmostEqual(diag['step'], 257, delta=30)

    def test_colour_boost_and_fringe(self):
        g = cv2.GaussianBlur(self.base(), (0, 0), 2) * (0.6 + 0.05 * self.texture())
        grey = np.repeat(g[..., None], 3, -1)
        self.assertLess(aq.colour_measures((grey * 40000).astype(np.uint16), g > 0.3)['chroma'], 1)
        boosted = np.stack([g * 0.5, g, g * 1.6], -1)
        self.assertGreater(aq.colour_measures(np.clip(boosted * 40000, 0, 65535).astype(np.uint16), g > 0.3)['chroma'], 25)
        shifted = grey.copy()
        shifted[..., 2] = cv2.warpAffine(g, np.float32([[1, 0, 3], [0, 1, 0]]), (self.W, self.H))
        fr = aq.colour_measures((shifted * 60000).astype(np.uint16), g > 0.3, (self.CX, self.CY, self.R))['fringe_px']
        self.assertAlmostEqual(fr, 3.0, delta=0.3)
        self.assertEqual(aq.colour_measures(np.zeros((10, 10), np.uint8), np.ones((10, 10), bool)),
                         dict(chroma=0.0, fringe_px=None))

    def test_sample_regions(self):
        self.assertEqual(aq.sample_regions(np.ones((100, 200), bool)), [(0, 0, 200, 100)])
        big = np.zeros((5000, 5000), bool)
        big[500:4500, 500:4500] = True
        regions = aq.sample_regions(big)
        self.assertLessEqual(len(regions), 24)
        for x0, y0, w, h in regions:
            self.assertGreater(big[y0:y0 + h, x0:x0 + w].mean(), 0.9)

    @S.needs_relief
    def test_measure_the_synthetic_moon(self):
        img, geo = S.synthetic_moon()
        q = aq.measure(S.encode(img), (float(geo.t[0]), float(geo.t[1]), geo.radius_px))
        for k in ('width', 'height', 'dtype', 'channels', 'moon_share', 'saturated_share', 'edge_width_px',
                  'edge_width_km', 'mare_noise', 'octave_energy', 'octave_ratio', 'fine_detail', 'jpeg_blocking',
                  'chroma', 'posterisation', 'km_per_px'):
            self.assertIn(k, q)
        self.assertEqual((q['width'], q['height'], q['dtype'], q['channels']), (1100, 1000, 'uint16', 1))
        self.assertLess(q['edge_width_px'], 4)
        self.assertTrue(aq.verdict(q)[0], aq.verdict(q)[2])


class FontFallback(S.TempDir, unittest.TestCase):
    """Fonts without the network: files already there are used; nothing there is a clear error."""

    def test_unknown_family_offline(self):
        with mock.patch.object(ar, 'FONT_DIR', self.tmp):
            with self.assertRaises(SystemExit) as cm:
                ar.Fonts('No Such Family', S.quiet)
        self.assertIn('No Such Family', str(cm.exception))

    @S.needs_font
    def test_damaged_file_next_to_a_good_one(self):
        src = S.ROBOTO
        dst = os.path.join(self.tmp, 'roboto')
        shutil.copytree(src, dst)
        with open(os.path.join(dst, 'Roboto-Broken.ttf'), 'wb') as fh:
            fh.write(b'not a font')
        msgs = []
        with mock.patch.object(ar, 'FONT_DIR', self.tmp), mock.patch.object(ar, 'BUNDLED_FONTS', self.tmp + '-none'):
            f = ar.Fonts('Roboto', msgs.append)
        self.assertFalse(os.path.exists(os.path.join(dst, 'Roboto-Broken.ttf')))
        self.assertTrue(f.files)
        self.assertTrue(any('damaged' in m for m in msgs))
        self.assertTrue(any('using the files already here' in m for m in msgs))


if __name__ == '__main__':
    unittest.main()
