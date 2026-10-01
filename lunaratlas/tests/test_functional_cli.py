"""Functional tests: the command-line helpers and commands (in this process), the viewer's server-side pieces and the
settings registry."""
import argparse
import io
import json
import math
import os
import warnings
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from unittest import mock

import _support as S
import cv2
import numpy as np

import atlas_geo as ag
import atlas_render as ar
import atlas_view as av
import lunaratlas as ma
import tool_settings as ts


def ns(image, output=None, format=None, around=None):
    return argparse.Namespace(image=image, output=output, format=format, around=around)


class OutputPlan(S.TempDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.img = os.path.join(self.tmp, 'moon.tif')
        cv2.imwrite(self.img, np.zeros((4, 4), np.uint8))

    def test_default_name_and_format(self):
        self.assertEqual(ma.output_plan(ns(self.img)), ('tiff', os.path.join(self.tmp, 'moon_atlas.tif')))
        self.assertEqual(ma.output_plan(ns(self.img, format='jpg'))[1], os.path.join(self.tmp, 'moon_atlas.jpg'))

    def test_around_tag(self):
        self.assertEqual(ma.output_plan(ns(self.img, around='Luna 17 / Lunokhod 1'))[1],
                         os.path.join(self.tmp, 'moon_atlas_Luna_17_Lunokhod_1.tif'))
        self.assertEqual(ma.output_plan(ns(self.img, around="Chang'e 3 / Yutu"))[1],
                         os.path.join(self.tmp, 'moon_atlas_Chang_e_3_Yutu.tif'))

    def test_extension_decides(self):
        for name, fmt in (('a.TIFF', 'tiff'), ('a.tif', 'tiff'), ('a.png', 'png'), ('a.jpeg', 'jpg'), ('a.JPG', 'jpg')):
            self.assertEqual(ma.output_plan(ns(self.img, os.path.join(self.tmp, name)))[0], fmt)

    def test_refusals(self):
        for kw, word in ((dict(output=os.path.join(self.tmp, 'a.bmp')), 'unknown extension'),
                         (dict(output=os.path.join(self.tmp, 'a.png'), format='jpg'), 'contradicts'),
                         (dict(output=os.path.join(self.tmp, 'nope', 'a.png')), 'does not exist'),
                         (dict(output=self.img), 'refusing to overwrite')):
            with self.assertRaises(SystemExit) as cm:
                ma.output_plan(ns(self.img, **kw))
            self.assertIn(word, str(cm.exception))

    def test_same_stem_siblings_get_disambiguated_default_names(self):
        """bugs-overview BUG-05's output collision: moon.tif and moon.jpg used to both default to
        moon_atlas.tif. An unambiguous image still gets the short familiar name."""
        jpg = os.path.join(self.tmp, 'moon.jpg')
        cv2.imwrite(jpg, np.zeros((4, 4), np.uint8))
        out_tif = ma.output_plan(ns(self.img))[1]
        out_jpg = ma.output_plan(ns(jpg))[1]
        self.assertNotEqual(out_tif, out_jpg)
        self.assertEqual(out_tif, os.path.join(self.tmp, 'moon.tif_atlas.tif'))
        self.assertEqual(out_jpg, os.path.join(self.tmp, 'moon.jpg_atlas.tif'))

    def test_case_variant_extensions_still_collide(self):
        # most filesystems these tests run on are case-insensitive, so a real second file of a different case
        # cannot be created to prove this end to end; the comparison itself (output_plan's own os.listdir scan)
        # is checked directly instead, with a case-differing name handed to it as if listdir had returned it
        with mock.patch.object(os, 'listdir', return_value=['moon.tif', 'MOON.JPG']):
            out = ma.output_plan(ns(self.img))[1]
        self.assertEqual(os.path.basename(out), 'moon.tif_atlas.tif')

    def test_a_default_destination_owned_by_a_different_source_is_refused(self):
        """A default output file whose manifest names a different source image must not be silently replaced
        (e.g. left over from before same-stem disambiguation, or any other collision)."""
        out = ma.output_plan(ns(self.img))[1]
        with open(out, 'wb') as fh:
            fh.write(b'not really an export')
        with open(out + '.export.json', 'w') as fh:
            json.dump(dict(source=os.path.join(self.tmp, 'someone_else.tif')), fh)
        with self.assertRaises(SystemExit) as cm:
            ma.output_plan(ns(self.img))
        self.assertIn('belongs to a different source image', str(cm.exception))

    def test_a_default_destination_owned_by_this_source_is_still_replaced_without_asking(self):
        out = ma.output_plan(ns(self.img))[1]
        with open(out, 'wb') as fh:
            fh.write(b'an old export of this same image')
        with open(out + '.export.json', 'w') as fh:
            json.dump(dict(source=os.path.abspath(self.img)), fh)
        self.assertEqual(ma.output_plan(ns(self.img))[1], out)        # no refusal

    def test_never_the_sidecar(self):
        side = ag.sidecar_path(self.img)
        with open(side, 'w') as fh:
            fh.write('{}')
        link = os.path.join(self.tmp, 'side.png')
        try:
            os.link(side, link)
        except OSError:
            self.skipTest('no hard links here')
        with self.assertRaises(SystemExit):
            ma.output_plan(ns(self.img, link))


class Parsing(unittest.TestCase):
    def test_parse_ints(self):
        self.assertEqual(ma.parse_ints('3000x2000', 2, 's'), [3000, 2000])
        self.assertEqual(ma.parse_ints('3000X2000', 2, 's'), [3000, 2000])
        self.assertEqual(ma.parse_ints('1,2,3,4', 4, 'r'), [1, 2, 3, 4])
        self.assertEqual(ma.parse_ints('-5,2,3,4', 4, 'r'), [-5, 2, 3, 4])
        for bad in ('3000', '3000x', 'axb', '1.5x2', '1,2,3'):
            with self.assertRaises(SystemExit):
                ma.parse_ints(bad, 2 if 'x' in bad or bad == '3000' else 4, 'what')

    def test_parse_layers(self):
        self.assertEqual(ma.parse_layers(None), set(ma.LAYERS))
        self.assertEqual(ma.parse_layers('crater, Area'), {'crater', 'area'})
        self.assertEqual(ma.parse_layers('none'), set())
        with self.assertRaises(SystemExit):
            ma.parse_layers('craters')

    def test_find_feature(self):
        feats = [dict(name='Copernicus'), dict(name='Copernicus A'), dict(name='Mare Imbrium')]
        self.assertIs(ma.find_feature(feats, ' copernicus '), feats[0])
        self.assertIs(ma.find_feature(feats, 'mare imb'), feats[2])
        with self.assertRaises(SystemExit):
            ma.find_feature(feats, 'Tycho')


class RimProjection(unittest.TestCase):
    def test_batched_rims_match_the_scalar_geometry_contract(self):
        geo = S.truth_geometry()
        lat, lon, diam = [0, 31.2, -42.5], [0, 47.7, -80.1], [12, 97, 181]
        many, many_z = ar.rim_polygons(geo, lat, lon, diam, 24)
        for i in range(len(lat)):
            one, one_z = ar.rim_polygon(geo, lat[i], lon[i], diam[i], 24)
            np.testing.assert_allclose(many[i], one, rtol=0, atol=1e-9)
            np.testing.assert_allclose(many_z[i], one_z, rtol=0, atol=1e-12)


class Optics(S.TempDir, unittest.TestCase):
    def test_optics_text(self):
        img = os.path.join(self.tmp, 'a.tif')
        self.assertIsNone(ma.optics_text(img))
        with open(os.path.join(self.tmp, 'lunaratlas_optics.json'), 'w') as fh:
            json.dump(dict(text='250 PDS · native · IMX678'), fh)
        self.assertEqual(ma.optics_text(img), '250 PDS · native · IMX678')
        with open(os.path.join(self.tmp, 'lunaratlas_optics.json'), 'w') as fh:
            fh.write('[1, 2')
        self.assertIsNone(ma.optics_text(img))

    def test_sun_elevation_light(self):
        from atlas_ephem import ephemeris
        name = '2026-09-23-2138_1-Moon.tif'
        e = ephemeris(datetime(2026, 9, 23, 21, 38, 6, tzinfo=timezone.utc))
        la, lo = e['sub_sun_lat'], e['sub_sun_lon']
        feats = [dict(lat=la, lon=lo, diam=0.0), dict(lat=-la, lon=lo + 180, diam=0.0),
                 dict(lat=0.0, lon=lo + 90.5, diam=0.0), dict(lat=0.0, lon=lo + 90.5, diam=100.0)]
        light = ma.sun_elevation_light(name, feats)
        self.assertEqual(list(light), [1.0, 0.0, 0.0, 1.0])          # a big crater's rim is still lit
        self.assertIsNone(ma.sun_elevation_light('no_time.tif', feats))


@S.needs_all
class Commands(S.TempDir, unittest.TestCase):
    """lunaratlas.main() in this process on a synthetic Moon with a ready sidecar."""

    def setUp(self):
        super().setUp()
        self.img, self.geo = S.moon_image(self.tmp)

    def export(self, *args):
        code, out = S.run_main('export', self.img, *args)
        self.assertIsNone(code, out)
        return out

    @S.needs_all
    def test_north_up_export_keeps_a_moved_label_on_its_feature(self):
        """BUG-10, end to end: a label moved in the viewer must still sit next to its own feature (not drift to
        wherever the old offset-only rotation happened to put it) after --north-up. Checked by actually drawing
        the export and finding the label's own pixels near where the independent anchor math says they belong,
        not merely that export_command runs without raising."""
        import atlas_geo as ag, atlas_render as ar
        geo, side = ag.load_geo(self.img)
        feats = S.projected_features(geo)
        named = next(f for f in feats if f['name'] not in ('',) and f['diam'] > 40 and f['z'] > 0.3)
        fonts = ar.Fonts('Roboto', S.quiet)
        home = ar.label_anchor(named, geo, fonts, min_px=10)
        self.assertIsNotNone(home)
        dx, dy = 40.0, -25.0
        d = S.sidecar(self.img)
        d['edits'] = dict(labels={named['name']: dict(dx=dx, dy=dy, colour='#ffffff')})
        ag.write_json_atomic(ag.sidecar_path(self.img), d)
        out = os.path.join(self.tmp, 'turned.png')
        self.export('--north-up', '--format', 'png', '--min-size', '10', '-o', out)
        img = cv2.imread(out, cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(img)
        # independently recompute where the moved label should land: the new geometry/turn this same export used
        raw = cv2.imread(self.img, cv2.IMREAD_UNCHANGED)
        _, new_geo, (M, b) = ag.north_up(raw, geo)
        new_feats = S.projected_features(new_geo)
        nf = next(f for f in new_feats if f['name'] == named['name'])
        home_new = ar.label_anchor(nf, new_geo, fonts, min_px=10)
        self.assertIsNotNone(home_new)
        want = (M @ np.array([home[0] + dx, home[1] + dy]) + b)
        wx, wy = int(round(float(want[0]))), int(round(float(want[1])))
        H, W = img.shape[:2]
        self.assertTrue(0 <= wx < W and 0 <= wy < H, (wx, wy, W, H))
        patch = img[max(0, wy - 25):wy + 25, max(0, wx - 60):wx + 60]
        self.assertGreater(patch.size, 0)
        self.assertTrue((patch > 10).any(), 'something was drawn near the independently computed position')
        # and NOT near where the old offset-only rotation would have put it, unless the two happen to coincide
        legacy_dx, legacy_dy = (M @ np.array([dx, dy]))
        lx, ly = int(round(home_new[0] + legacy_dx)), int(round(home_new[1] + legacy_dy))
        if math.hypot(lx - wx, ly - wy) > 80:           # far enough apart to be a meaningful check
            legacy_patch = img[max(0, ly - 25):ly + 25, max(0, lx - 60):lx + 60]
            self.assertFalse((legacy_patch > 10).any(),
                             'the label is at the correct spot, not the old offset-only-rotation spot')

    def test_info(self):
        code, out = S.run_main('info', self.img)
        self.assertIsNone(code)
        self.assertIn('1100 x 1000 px', out)
        self.assertIn('37.0° clockwise', out)
        self.assertIn('not mirrored', out)
        self.assertIn('latitude +3.20°, longitude -4.10°', out)
        self.assertIn('quality OK', out)

    def test_info_before_locate(self):
        other = os.path.join(self.tmp, 'other.tif')
        cv2.imwrite(other, np.zeros((5, 5), np.uint8))
        code, _ = S.run_main('info', other)
        self.assertIn('not located yet', str(code))

    def test_find(self):
        code, out = S.run_main('find', self.img, 'copernicus')
        self.assertIsNone(code)
        x, y, _ = self.geo.to_image(9.621, -20.079)
        self.assertIn(f'image x {float(x):.0f} px, y {float(y):.0f} px', out)
        self.assertIn('visible', out)
        code, out = S.run_main('find', self.img, 'Hertzsprung')                  # far side
        self.assertIn('on the far side', out)

    def test_export_formats(self):
        for fmt, dtype in (('tiff', np.uint16), ('png', np.uint16), ('jpg', np.uint8)):
            out = os.path.join(self.tmp, f'o.{fmt}')
            self.export('-o', out, '--format', fmt)
            im = cv2.imread(out, cv2.IMREAD_UNCHANGED)
            self.assertEqual(im.shape, (1000, 1100, 3), fmt)
            self.assertEqual(im.dtype, dtype, fmt)

    def test_export_default_name(self):
        log = self.export()
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'moon_atlas.tif')))
        self.assertIn('labels placed', log)
        self.assertIn('wrote', log)

    def test_export_without_anything_is_the_image(self):
        out = os.path.join(self.tmp, 'plain.tif')
        self.export('-o', out, '--layers', 'none', '--no-grid', '--no-info', '--no-drawings', '--no-rims')
        src = cv2.imread(self.img, cv2.IMREAD_UNCHANGED)
        got = cv2.imread(out, cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(got, cv2.cvtColor(src, cv2.COLOR_GRAY2BGR))

    def test_export_draws_names(self):
        out = os.path.join(self.tmp, 'named.tif')
        self.export('-o', out, '--no-grid', '--no-info')
        src = cv2.cvtColor(cv2.imread(self.img, cv2.IMREAD_UNCHANGED), cv2.COLOR_GRAY2BGR)
        changed = (cv2.imread(out, cv2.IMREAD_UNCHANGED) != src).any(-1)
        self.assertGreater(changed.mean(), 0.005)
        self.assertLess(changed.mean(), 0.5)

    def test_export_scale_and_max_size(self):
        out = os.path.join(self.tmp, 'half.png')
        self.export('-o', out, '--scale', '0.5')
        self.assertEqual(cv2.imread(out, cv2.IMREAD_UNCHANGED).shape[:2], (500, 550))
        out = os.path.join(self.tmp, 'small.jpg')
        self.export('-o', out, '--max-size', '300')
        self.assertEqual(cv2.imread(out).shape[:2], (273, 300))

    def test_export_region_and_around(self):
        out = os.path.join(self.tmp, 'r.png')
        self.export('-o', out, '--region', '100,200,300,150')
        self.assertEqual(cv2.imread(out, cv2.IMREAD_UNCHANGED).shape[:2], (150, 300))
        log = self.export('--around', 'Copernicus', '--size', '400x300', '--format', 'png')
        out = os.path.join(self.tmp, 'moon_atlas_Copernicus.png')
        self.assertEqual(cv2.imread(out, cv2.IMREAD_UNCHANGED).shape[:2], (300, 400))
        x, y, _ = self.geo.to_image(9.621, -20.079)
        self.assertIn(f'view: x {int(round(float(x) - 200))} y {int(round(float(y) - 150))}', log)

    def test_export_includes_the_viewers_edits(self):
        cx, cy = self.geo.t
        d = S.sidecar(self.img)
        d['edits'] = dict(shapes=[dict(kind='circle', cx=cx, cy=cy, r=60, colour='#ff0000', size=2)],
                          hidden=['Copernicus'], labels={}, style=dict(font='Roboto'))
        ag.write_json_atomic(ag.sidecar_path(self.img), d)
        a, b = os.path.join(self.tmp, 'with.tif'), os.path.join(self.tmp, 'without.tif')
        log = self.export('-o', a, '--layers', 'none', '--no-grid', '--no-info')
        self.assertIn('1 of your drawings', log)
        self.export('-o', b, '--layers', 'none', '--no-grid', '--no-info', '--no-drawings')
        wa, wb = cv2.imread(a, -1), cv2.imread(b, -1)
        ring = wa[int(cy), int(cx) + 60]
        self.assertGreater(int(ring[2]), int(ring[0]) + 20000)             # red (BGR) on the circle
        self.assertTrue((wa != wb).any())
        self.assertEqual(int((wa != wb).any(-1).sum()) > 300, True)

    def test_export_validation(self):
        for args, word in ((('--scale', '1.5'), 'upscale'), (('--scale', '0'), 'positive'), (('--scale', 'nan'), 'positive'),
                           (('--font-scale', '-1'), 'positive'), (('--min-size', 'inf'), 'positive'),
                           (('--font-scale', '100000'), '0.3'),      # claude-findings.md C-28: the .env bound applies here too
                           (('--max-size', '0'), 'at least 1'), (('--quality', '101'), '0 to 100'),
                           (('--region', '1,2,3'), 'expected 4'), (('--region', '0,0,0,10'), 'at least 1 px'),
                           (('--region', '5000,5000,10,10'), 'outside'), (('--around', 'Nowhere'), 'no feature'),
                           (('--around', 'Hertzsprung'), 'far side'), (('--layers', 'moons'), 'unknown'),
                           (('--around', ' '), 'needs a feature name')):     # BUG-17
            code, out = S.run_main('export', self.img, *args)
            self.assertIn(word, str(code), args)

    def test_a_blank_around_is_rejected_before_anything_is_located_or_downloaded(self):
        """BUG-17: a whitespace-only --around used to export around whatever feature sorted first, after a full
        locate (and a download on a first run). It must fail immediately, before that work starts."""
        img = os.path.join(self.tmp, 'never_located.tif')
        S.cv2.imwrite(img, np.zeros((20, 20), np.uint8))
        code, out = S.run_main('export', img, '--around', '   ')
        self.assertIn('needs a feature name', str(code), out)
        self.assertFalse(os.path.exists(ag.sidecar_path(img)), 'no locate (and so no sidecar) was attempted')

    def test_quality_gate_refusal_and_force(self):
        d = S.sidecar(self.img)
        d['quality_gate'] = dict(ok=False, forced=False, reasons=['too blurry'], line='quality refused: too blurry')
        ag.write_json_atomic(ag.sidecar_path(self.img), d)
        code, _ = S.run_main('export', self.img, '--format', 'png')
        self.assertIn('quality gate refused', str(code))
        code, _ = S.run_main('export', self.img, '--format', 'png', '--force')
        self.assertIsNone(code)
        code, out = S.run_main('find', self.img, 'Tycho')                    # find always works
        self.assertIsNone(code)

    def test_quality_gate_on_the_synthetic_moon(self):
        ok, reasons, line, q = ma.quality_gate(self.img)
        self.assertTrue(ok, line)
        self.assertTrue(q['has_limb'])
        self.assertAlmostEqual(q['limb_radius_px'], S.DISK['R'], delta=3)


class ViewerServerSide(S.TempDir, unittest.TestCase):
    def test_link_id(self):
        self.assertEqual(av.link_id('http://planetarynames.wr.usgs.gov/Feature/1316'), '1316')
        self.assertEqual(av.link_id('http://x/Feature/1316/'), '1316')
        for bad in (None, '', 'http://x/y', 'javascript:alert(1)'):
            self.assertEqual(av.link_id(bad), '')

    def test_clean_edits(self):
        shapes = [dict(kind='circle', cx=1, cy=2, r=3)] * 6000 + [dict(kind='bad')]
        e = av.clean_edits(dict(shapes=shapes, hidden=['b', 'a', 'a', 3, None], labels={'x': dict(dx=1, dy=2), 'y': 'z',
                                'z': dict(colour='')}, style=dict(font=5, minPx=30, evil=1), junk=1))
        self.assertEqual(e['schema'], av.EDITS_SCHEMA)
        self.assertEqual(len(e['shapes']), 5000)
        self.assertEqual(e['hidden'], ['a', 'b'])
        self.assertEqual(e['labels'], {'x': dict(dx=1.0, dy=2.0)})
        self.assertEqual(e['style'], dict(minPx=30))
        self.assertNotIn('junk', e)
        empty = av.clean_edits('nope')
        self.assertEqual((empty['shapes'], empty['hidden'], empty['labels'], empty['style']), ([], [], {}, {}))
        self.assertEqual(av.clean_edits(dict(shapes='x', hidden='abc', labels=[1], style=[]))['hidden'], [])

    def test_edits_round_trip_keeps_the_geometry(self):
        img = os.path.join(self.tmp, 'a.tif')
        cv2.imwrite(img, np.zeros((10, 10), np.uint8))
        S.locate_as(img, S.truth_geometry())
        import threading
        ok, saved, _ = av.write_edits(img, dict(shapes=[dict(kind='text', x=1, y=2, label='hi')], hidden=['Tycho']),
                                      threading.Lock())
        self.assertTrue(ok)
        self.assertIn('saved', saved)
        self.assertEqual(av.read_edits(img)['hidden'], ['Tycho'])
        geo, d = ag.load_geo(img)
        self.assertIsNotNone(geo)
        self.assertEqual(d['edits']['shapes'][0]['label'], 'hi')

    def test_read_edits_of_a_damaged_sidecar(self):
        img = os.path.join(self.tmp, 'a.tif')
        self.assertEqual(av.read_edits(img), {})
        with open(ag.sidecar_path(img), 'w') as fh:
            fh.write('{"edits": [1]')
        self.assertEqual(av.read_edits(img), {})
        with open(ag.sidecar_path(img), 'w') as fh:
            json.dump(dict(edits=[1]), fh)
        self.assertEqual(av.read_edits(img), {})

    def test_export_command(self):
        img = os.path.join(self.tmp, 'moon.tif')
        cmd, out = av.export_command(img, {})
        self.assertEqual(cmd[:6], [sys.executable, os.path.join(av.HERE, 'lunaratlas.py'), 'export', img, '--format', 'tiff'])
        self.assertEqual(cmd[-2:], ['-o', out])
        self.assertEqual(out, os.path.join(self.tmp, 'moon_atlas.tif'))
        cmd, out = av.export_command(img, dict(format='jpg', region='view', box=[10.4, 20.6, 300, 0], scale='max',
                                               max_size='2048', layers=['crater', 'area', 'moons'], rims=False, grid=False,
                                               drawings=False, info=False, night='dim', min_px=1000, font_scale=0.01,
                                               font='Source Sans 3', force=True))
        self.assertIn('--region', cmd)
        self.assertEqual(cmd[cmd.index('--region') + 1], '10,21,300,1')
        self.assertEqual(cmd[cmd.index('--max-size') + 1], '2048')
        self.assertEqual(cmd[cmd.index('--layers') + 1], 'crater,area')
        for flag in ('--no-rims', '--no-grid', '--no-drawings', '--no-info', '--force'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--min-size') + 1], '400')              # clamped to the CLI's range
        self.assertEqual(cmd[cmd.index('--font-scale') + 1], '0.3')
        self.assertEqual(cmd[cmd.index('--night') + 1], 'dim')
        self.assertEqual(cmd[cmd.index('--font') + 1], 'Source Sans 3')
        self.assertTrue(out.endswith('moon_atlas_region_10_21.jpg'))

    def test_export_command_feature_and_defaults(self):
        img = os.path.join(self.tmp, 'moon.tif')
        cmd, out = av.export_command(img, dict(region='feature', name='Rupes Recta', size=[600, 400.4], scale='half',
                                               names=False, font='Comic Sans', night='bogus', format='bmp'))
        self.assertIn('--around=Rupes Recta', cmd)
        self.assertEqual(cmd[cmd.index('--size') + 1], '600x400')
        self.assertEqual(cmd[cmd.index('--scale') + 1], '0.5')
        self.assertEqual(cmd[cmd.index('--layers') + 1], 'none')
        self.assertNotIn('--font', cmd)
        self.assertEqual(cmd[cmd.index('--night') + 1], 'hide', 'an unknown value is the dialog default, always sent')
        self.assertEqual(cmd[cmd.index('--format') + 1], 'tiff')
        self.assertTrue(out.endswith('moon_atlas_Rupes_Recta.tif'))

    def test_export_command_rejects_bad_numbers(self):
        img = os.path.join(self.tmp, 'moon.tif')
        for o, exc in ((dict(region='view', box=[1, 2, 'x', 4]), ValueError), (dict(scale='max', max_size=[1]), TypeError),
                       (dict(scale='max', max_size=float('inf')), OverflowError), (dict(min_px='big'), ValueError),
                       (dict(region='feature', name='A', size=[1]), ValueError)):
            with self.assertRaises(exc, msg=o):
                av.export_command(img, o)

    def test_graticule(self):
        g = S.truth_geometry()
        lines = av.graticule(g)
        self.assertGreater(len(lines), 25)
        for ln in lines:
            self.assertGreaterEqual(len(ln['pts']), 2)
            self.assertIn(ln['kind'], ('lat', 'lon'))
            la, lo, ok = g.to_latlon(*np.array(ln['pts'][len(ln['pts']) // 2]))
            self.assertTrue(ok)
            if ln['kind'] == 'lat':
                self.assertAlmostEqual(float(la), ln['value'], delta=0.15)       # points are rounded to 0.1 px

    def test_a_dim_float_image_reaches_the_full_display_range(self):
        """bugs-overview BUG-18: `max(white, 1)` meant a valid 0-1 float image with a white point below 1
        (e.g. 0.3) was stretched as if white were 1 -- the display tile stayed far too dark."""
        img = os.path.join(self.tmp, 'dim.tif')
        rng = np.random.default_rng(0)
        raw = (rng.random((300, 300)).astype(np.float32) * 0.3)         # white point ~0.3, not 1.0
        cv2.imwrite(img, raw)
        with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, 'cache1')):
            av.build_tiles(img, raw, S.quiet)
            t = cv2.imread(os.path.join(av.tile_dir(img), '0', '0_0.jpg'), cv2.IMREAD_GRAYSCALE)
        self.assertGreater(t.max(), 200, 'the white point is used as-is, not clamped to 1')

    def test_nan_inf_and_negative_float_pixels_do_not_poison_or_brighten(self):
        """Mixed finite/NaN/Inf samples and negative pixels must not crash the percentile, and a negative or
        non-finite pixel must render black, not bright (convertScaleAbs takes the absolute value)."""
        img = os.path.join(self.tmp, 'odd.tif')
        raw = np.zeros((300, 300), np.float32)
        raw[:] = 0.5
        raw[0:50, 0:50] = np.nan
        raw[50:100, 0:50] = np.inf
        raw[100:150, 0:50] = -np.inf
        raw[150:200, 0:50] = -5.0
        cv2.imwrite(img, raw)
        with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, 'cache2')):
            av.build_tiles(img, raw, S.quiet)
            t = cv2.imread(os.path.join(av.tile_dir(img), '0', '0_0.jpg'), cv2.IMREAD_GRAYSCALE)
        self.assertTrue(np.isfinite(t).all())
        tol = 6                                        # lossy JPEG (quality 86): check well inside each block,
                                                        # away from ringing at a sharp 0-vs-0.5 edge
        self.assertLessEqual(t[10:40, 10:40].max(), tol, 'NaN pixels are black')
        self.assertLessEqual(t[60:90, 10:40].max(), tol, 'Inf pixels are black, not bright via abs()')
        self.assertLessEqual(t[110:140, 10:40].max(), tol, '-Inf pixels are black')
        self.assertLessEqual(t[160:190, 10:40].max(), tol, 'a negative pixel is black, not bright via abs()')
        self.assertGreater(t[200:, 200:].max(), 200, 'the valid 0.5 region still reaches the display range')

    def test_an_all_invalid_or_all_zero_float_image_is_black_without_a_warning(self):
        for raw in (np.zeros((50, 50), np.float32), np.full((50, 50), np.nan, np.float32)):
            img = os.path.join(self.tmp, 'blank.tif')
            cv2.imwrite(img, raw)
            with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, f'cache_blank_{raw[0,0]}')), \
                 warnings.catch_warnings():
                warnings.simplefilter('error')
                av.build_tiles(img, raw, S.quiet)
                t = cv2.imread(os.path.join(av.tile_dir(img), '0', '0_0.jpg'), cv2.IMREAD_GRAYSCALE)
            self.assertTrue((t == 0).all())

    def test_an_old_cache_without_a_render_version_is_rebuilt(self):
        """An on-disk pyramid from before this fix (no 'render' key in meta.json) must be rebuilt, not reused,
        so an old too-dark tile is never served from the on-disk cache (bugs-overview BUG-18)."""
        img = os.path.join(self.tmp, 'old.tif')
        raw = (np.random.default_rng(1).random((300, 300)).astype(np.float32) * 0.3)
        cv2.imwrite(img, raw)
        with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, 'cache3')):
            av.build_tiles(img, raw, S.quiet)
            meta_p = os.path.join(av.tile_dir(img), 'meta.json')
            with open(meta_p) as fh:
                meta = json.load(fh)
            del meta['render']                       # as an old cache, written before TILE_RENDER_VERSION existed
            with open(meta_p, 'w') as fh:
                json.dump(meta, fh)
            msgs = []
            self.assertEqual(av.build_tiles(img, raw, msgs.append), av.build_tiles(img, raw, S.quiet))
            self.assertIn('tiles built', msgs[-1], 'an old-version cache is rebuilt, not reused')
            with open(meta_p) as fh:
                self.assertEqual(json.load(fh)['render'], av.TILE_RENDER_VERSION)

    def test_the_browser_tile_url_changes_with_the_render_version(self):
        """The cached tile URL the page uses must also depend on TILE_RENDER_VERSION, not only the image's own
        signature, so a browser that already cached an old, too-dark tile fetches a fresh one."""
        img = os.path.join(self.tmp, 'url.tif')
        cv2.imwrite(img, np.zeros((20, 20), np.uint8))
        with mock.patch.object(av, 'TILE_RENDER_VERSION', av.TILE_RENDER_VERSION + 1):
            bumped = av.tile_version(img)
        self.assertNotEqual(av.tile_version(img), bumped)

    def test_build_tiles(self):
        img = os.path.join(self.tmp, 'big.tif')
        raw = (np.random.default_rng(0).random((1300, 1100)) * 60000).astype(np.uint16)
        cv2.imwrite(img, raw)
        msgs = []
        with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, 'cache')):
            levels = av.build_tiles(img, raw, msgs.append)
            self.assertEqual([(l['w'], l['h'], l['cols'], l['rows']) for l in levels],
                             [(1100, 1300, 3, 3), (550, 650, 2, 2), (275, 325, 1, 1)])
            d = av.tile_dir(img)
            t = cv2.imread(os.path.join(d, '0', '2_2.jpg'))
            self.assertEqual(t.shape, (1300 - 1024, 1100 - 1024, 3))
            self.assertEqual(cv2.imread(os.path.join(d, '1', '0_0.jpg')).shape, (512, 512, 3))
            self.assertEqual(av.build_tiles(img, raw, msgs.append), levels)
            self.assertIn('from the cache', msgs[-1])
            os.utime(img, (1, 1))                                       # the image changed: rebuilt
            av.build_tiles(img, raw, msgs.append)
            self.assertIn('tiles built', msgs[-1])

    @S.needs_font
    def test_fonts_css(self):
        css = av.fonts_css()
        self.assertIn("font-family: 'Roboto'", css)
        self.assertIn('/fonts/roboto/', css)
        files = av.font_files('Roboto')
        self.assertTrue(all(w == '100 900' for _, w, _ in files))

    @S.needs_all
    def test_a_cache_missing_a_tile_is_built_again(self):
        img, geo = S.moon_image(self.tmp, name='cached.tif')
        raw = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        levels = av.build_tiles(img, raw, S.quiet)
        tile = os.path.join(av.tile_dir(img), '0', '0_0.jpg')
        os.remove(tile)
        msgs = []
        self.assertEqual(av.build_tiles(img, raw, msgs.append), levels)
        self.assertTrue(os.path.getsize(tile) > 0, 'the tile is back')
        self.assertTrue(any('incomplete' in m for m in msgs), msgs)
        open(tile, 'w').close()                                     # an empty file is no tile either
        av.build_tiles(img, raw, S.quiet)
        self.assertTrue(os.path.getsize(tile) > 0)

    def test_a_pyramid_with_a_tile_that_could_not_be_written_has_no_manifest(self):
        from unittest import mock
        img, geo = S.moon_image(self.tmp, name='full.tif')
        raw = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        real = cv2.imwrite
        with mock.patch.object(av.cv2, 'imwrite', lambda p, *a: False if p.endswith('1_0.jpg') else real(p, *a)):
            with self.assertRaises(SystemExit) as cm:
                av.build_tiles(img, raw, S.quiet)
        self.assertIn('could not be written', str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(av.tile_dir(img), 'meta.json')), 'no manifest for a pyramid with holes')

    def test_opening_an_image_again_does_not_decode_it(self):
        from unittest import mock
        img, geo = S.moon_image(self.tmp, name='again.tif')
        side = S.sidecar(img)
        first = av.Session(img, geo, side, None, S.quiet)              # the first open reads the file
        reads = []
        real = cv2.imread
        with mock.patch.object(av.cv2, 'imread', lambda p, *a: reads.append(p) or real(p, *a)):
            again = av.Session(img, geo, side, None, S.quiet)
        self.assertEqual(reads, [], 'tiles and night side come from the cache: the pixels are not read')
        self.assertEqual(again.data['features'], first.data['features'])
        self.assertEqual((again.data['width'], again.data['height']), (1100, 1000))
        geo2 = ag.Geometry(geo.lat0 + 1.0, geo.lon0, geo.A, geo.t)     # another positioning: the night side is worked out again
        with mock.patch.object(av.cv2, 'imread', lambda p, *a: reads.append(p) or real(p, *a)):
            av.Session(img, geo2, side, None, S.quiet)
        self.assertEqual(len(reads), 1)

    def test_page_data(self):
        img, geo = S.moon_image(self.tmp)
        raw = cv2.imread(img, -1)
        d = av.page_data(img, raw, geo, S.sidecar(img), [dict(w=1100, h=1000, cols=3, rows=2)], S.quiet)
        self.assertEqual((d['width'], d['height'], d['tile']), (1100, 1000, av.TILE))
        self.assertEqual(d['geometry'], geo.as_dict())
        names = {r['n']: r for r in d['features']}
        self.assertIn('Copernicus', names)
        self.assertNotIn('Hertzsprung', names)                      # far side
        self.assertEqual(len(names['Copernicus']['e']), 5)          # rim ellipse for the viewer
        self.assertTrue(names['Copernicus']['k'].isdigit())                # its planetarynames.wr.usgs.gov id
        for r in d['features']:
            self.assertGreaterEqual(r['z'], 0.05)
            self.assertTrue(-55 <= r['x'] <= 1155 and -50 <= r['y'] <= 1050)
        self.assertIn('Roboto', d['fonts'])
        self.assertTrue(d['grid'])
        json.dumps(d)                                               # it is served as JSON

    def test_export_job(self):
        out = os.path.join(self.tmp, 'o.txt')
        ok = av.ExportJob([sys.executable, '-c', f'print("step one"); print("WARN hidden"); open({out!r}, "w").write("x")'], out)
        ok.proc.wait(30)
        self._wait(ok)
        s = ok.status()
        self.assertEqual(s['state'], 'done')
        self.assertEqual(s['lines'], ['step one'])
        self.assertEqual(s['size_bytes'], 1)
        bad = av.ExportJob([sys.executable, '-c', 'import sys; print("no feature named x"); sys.exit(1)'], out + '2')
        self._wait(bad)
        self.assertEqual(bad.status()['state'], 'failed')
        self.assertEqual(bad.status()['error'], 'no feature named x')
        silent = av.ExportJob([sys.executable, '-c', 'pass'], out + '3')          # exit 0 but nothing written
        self._wait(silent)
        self.assertEqual(silent.status()['state'], 'failed')
        self.assertEqual(silent.status()['error'], 'o.txt3 finished without saving its result')

    def _wait(self, job):
        import time
        t0 = time.time()
        while job.state == 'running' and time.time() - t0 < 30:
            time.sleep(0.02)

    def test_reveal_per_platform(self):
        p = os.path.join(self.tmp, 'out file.tif')
        for platform, want in (('darwin', ['open', '-R', p]), ('win32', ['explorer', '/select,' + os.path.normpath(p)]),
                               ('linux', ['xdg-open', self.tmp])):
            with mock.patch.object(av.sys, 'platform', platform), mock.patch.object(av.subprocess, 'Popen') as po:
                av.reveal(p)
            po.assert_called_once_with(want)
        with mock.patch.object(av.subprocess, 'Popen', side_effect=FileNotFoundError('xdg-open')):
            av.reveal(p)                                               # a headless box: no file manager, no error


class Settings(S.TempDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, ts, '_raw', {})
        self.addCleanup(ts._warned.clear)

    def env_file(self, content, **environ):
        """Settings read from content as the .env file and environ as the environment."""
        with open(os.path.join(self.tmp, '.env'), 'wb') as fh:
            fh.write(content if isinstance(content, bytes) else content.encode('utf-8'))
        ts._raw, ts._warned = None, set()
        clean = {k: v for k, v in os.environ.items() if not k.startswith(ts.PREFIXES)}
        err = io.StringIO()
        with mock.patch.object(ts, 'ROOT', self.tmp), mock.patch.dict(os.environ, dict(clean, **environ), clear=True), \
                redirect_stderr(err):
            ts._read()
        return err.getvalue()

    def test_every_kind(self):
        err = self.env_file('# comment\nLUNARATLAS_FOCAL_MM = 1500  # a comment\nLUNARATLAS_NIGHT="dim"\n'
                            "LUNARATLAS_TELESCOPE='C11'\nLUNARATLAS_RIMS=no\nLUNARATLAS_GRID=On\nLUNARATLAS_MAX_SIZE=4096\n"
                            'LUNARATLAS_LAYERS=crater, area\nLUNARATLAS_CAMERAS=IMX585:2.9, ASI 120:3.75\n')
        self.assertEqual(err, '')
        self.assertEqual(ts.get('LUNARATLAS_FOCAL_MM'), 1500.0)
        self.assertEqual(ts.get('LUNARATLAS_NIGHT'), 'dim')
        self.assertEqual(ts.get('LUNARATLAS_TELESCOPE'), 'C11')
        self.assertIs(ts.get('LUNARATLAS_RIMS'), False)
        self.assertIs(ts.get('LUNARATLAS_GRID'), True)
        self.assertEqual(ts.get('LUNARATLAS_MAX_SIZE'), 4096)
        self.assertEqual(ts.get('LUNARATLAS_LAYERS'), ['crater', 'area'])
        self.assertEqual(ts.get('LUNARATLAS_CAMERAS'), [('IMX585', 2.9), ('ASI 120', 3.75)])
        self.assertEqual(ts.get('LUNARATLAS_JPEG_QUALITY'), 92)                  # not set: the default

    def test_environment_wins_over_the_file(self):
        self.env_file('LUNARATLAS_FOCAL_MM=1500\n', LUNARATLAS_FOCAL_MM='2400')
        self.assertEqual(ts.get('LUNARATLAS_FOCAL_MM'), 2400.0)

    def test_out_of_range_and_typos_fall_back_with_one_warning(self):
        err = self.env_file('LUNARATLAS_FOCAL_MM=10\nLUNARATLAS_NIGHT=never\nLUNARATLAS_FOCUS=1\nLUNARATLAS_JPEG_QUALITY=9.5\n'
                            'LUNARATLAS_CAMERAS=IMX678\nLUNAR_FINISH_HIGHLIGHTS=0.5\nLUNARATLAS_LAYERS=\n')
        self.assertIn('unknown setting LUNARATLAS_FOCUS', err)
        e2 = io.StringIO()
        with redirect_stderr(e2):
            for _ in range(3):
                self.assertEqual(ts.get('LUNARATLAS_FOCAL_MM'), 1200.0)
            self.assertEqual(ts.get('LUNARATLAS_NIGHT'), 'dim')
            self.assertEqual(ts.get('LUNARATLAS_JPEG_QUALITY'), 92)
            self.assertEqual(ts.get('LUNARATLAS_CAMERAS'), [('IMX678', 2.0), ('IMX533', 3.76), ('IMX462', 2.9)])
            self.assertEqual(ts.get('LUNAR_FINISH_HIGHLIGHTS'), 0.3)            # 0.5 is excluded (open interval)
            self.assertEqual(ts.get('LUNARATLAS_LAYERS'), list(ts.LAYER_NAMES))   # empty: the default
        self.assertEqual(e2.getvalue().count('LUNARATLAS_FOCAL_MM'), 1)
        self.assertIn('outside 50 – 30000', e2.getvalue())

    def test_variables_the_tools_read_directly_are_not_reported_as_unknown(self):
        """claude-findings.md C-28: LUNARATLAS_DATA, _TOKEN, _SELFTEST and the rest of ts.NOT_SETTINGS are real,
        used variables (read straight from os.environ, not through this registry), not settings typos — every
        export from the viewer, and every test subprocess, sets one of these."""
        err = self.env_file('', LUNARATLAS_DATA='/x', LUNARATLAS_TOKEN='t', LUNARATLAS_SELFTEST='1')
        self.assertEqual(err, '')
        # still caught when it is instead put in .env, where none of these do anything (they are never read there)
        err = self.env_file('LUNARATLAS_TOKEN=t\n')
        self.assertIn('unknown setting LUNARATLAS_TOKEN', err)

    def test_nan_and_infinity_are_rejected_not_taken_as_in_range(self):
        """claude-findings.md C-15: math.isfinite comparisons with nan/inf are always False, so the plain lo/hi
        checks used to let both straight through as valid."""
        self.env_file('LUNARATLAS_FOCAL_MM=nan\nLUNARATLAS_FONT_SCALE=inf\nLUNARATLAS_CAMERAS=IMX678:nan\n')
        err = io.StringIO()
        with redirect_stderr(err):
            focal, fs, cams = ts.get('LUNARATLAS_FOCAL_MM'), ts.get('LUNARATLAS_FONT_SCALE'), ts.get('LUNARATLAS_CAMERAS')
        for name in ('LUNARATLAS_FOCAL_MM', 'LUNARATLAS_FONT_SCALE', 'LUNARATLAS_CAMERAS'):
            self.assertIn(name, err.getvalue())
        self.assertEqual(focal, 1200.0)
        self.assertEqual(fs, 1.0)
        self.assertEqual(cams, [('IMX678', 2.0), ('IMX533', 3.76), ('IMX462', 2.9)])

    def test_windows_line_endings(self):
        self.env_file(b'LUNARATLAS_FOCAL_MM=1500\r\nLUNARATLAS_NIGHT=dim\r\n')
        self.assertEqual(ts.get('LUNARATLAS_FOCAL_MM'), 1500.0)
        self.assertEqual(ts.get('LUNARATLAS_NIGHT'), 'dim')

    def test_utf8_bom(self):
        # a .env saved as "UTF-8 with BOM" (Windows PowerShell 5 `Out-File -Encoding utf8`, older Notepad) applies
        # every setting, the first one too
        err = self.env_file(b'\xef\xbb\xbfLUNARATLAS_FOCAL_MM=1500\nLUNARATLAS_NIGHT=dim\n')
        self.assertEqual(err, '')
        self.assertEqual(ts.get('LUNARATLAS_FOCAL_MM'), 1500.0)

    def test_hash_starts_a_comment_except_inside_quotes(self):
        """BUG-20: the parser used to strip the comment before the quotes, so a telescope named "C#11 EdgeHD"
        arrived as "C". Quotes are read first now; an unquoted # still starts a comment."""
        for text, want in (('LUNARATLAS_TELESCOPE="C#11 EdgeHD"', 'C#11 EdgeHD'),
                           ("LUNARATLAS_TELESCOPE='C#11 EdgeHD'", 'C#11 EdgeHD'),
                           ('LUNARATLAS_TELESCOPE="C#11 EdgeHD"  # the scope', 'C#11 EdgeHD'),
                           ('LUNARATLAS_TELESCOPE=C11 # the scope', 'C11'),
                           ('LUNARATLAS_TELESCOPE=C#11', 'C'),                   # unquoted: still a comment
                           ('LUNARATLAS_TELESCOPE="C11', 'C11'),                 # unterminated: read as before
                           ('# LUNARATLAS_TELESCOPE=C11', '250 PDS'),   # a commented-out line stays off
                           ('# a comment that mentions key=value', '250 PDS')):
            with self.subTest(text):
                err = self.env_file(text + '\n')
                self.assertEqual(err, '', text)
                self.assertEqual(ts.get('LUNARATLAS_TELESCOPE'), want)

    def test_pairs_tolerates_a_trailing_comma(self):
        """BUG-21: one empty item used to abort the whole setting with an unpacking error, so every camera was
        lost; the list parser already skipped empty items."""
        err = self.env_file('LUNARATLAS_CAMERAS=IMX678:2.0, IMX533:3.76,\n')
        self.assertEqual(err, '')
        self.assertEqual(ts.get('LUNARATLAS_CAMERAS'), [('IMX678', 2.0), ('IMX533', 3.76)])

    def test_pairs_rejects_empty_and_malformed_entries_with_a_reason(self):
        self.env_file('LUNARATLAS_CAMERAS= , ,\nLUNARATLAS_BINNINGS=IMX678\nLUNARATLAS_EXTENDERS=native:x\n')
        err = io.StringIO()
        with redirect_stderr(err):
            cams, bins, ext = (ts.get('LUNARATLAS_CAMERAS'), ts.get('LUNARATLAS_BINNINGS'),
                               ts.get('LUNARATLAS_EXTENDERS'))
        self.assertEqual(cams, [('IMX678', 2.0), ('IMX533', 3.76), ('IMX462', 2.9)])   # all empty: still invalid
        self.assertEqual(bins, [('1×1', 1.0), ('2×2', 2.0)])
        self.assertEqual(ext[0], ('native', 1.0))
        self.assertIn('empty', err.getvalue())
        self.assertIn('expected NAME:VALUE', err.getvalue())
        self.assertIn('is not a number', err.getvalue())

    def test_undeclared_keys(self):
        self.env_file('LUNARATLAS_BASELINE_DIR=/x\n')
        self.assertEqual(ts.get('NOT_DECLARED', 5, int), 5)

    def test_range_text(self):
        self.assertEqual(ts.range_text(ts.BY_KEY['LUNAR_FINISH_KNEE_PERCENTILE']), '0 (excl.) – 99.9 (excl.)')
        self.assertEqual(ts.range_text(ts.BY_KEY['LUNARATLAS_NIGHT']), 'one of hide | dim | show')
        self.assertEqual(ts.range_text(ts.BY_KEY['LUNARATLAS_RIMS']), '1 or 0')
        self.assertEqual(ts.range_text(ts.BY_KEY['LUNARATLAS_TELESCOPE']), '')

    def test_defaults_are_valid(self):
        for key, s in ts.BY_KEY.items():
            if s['kind'] in ('int', 'float'):
                self.assertTrue(ts._in_range(s, s['default']), key)
            if s['kind'] == 'choice':
                self.assertIn(s['default'], s['choices'], key)
            if s['kind'] in ('pairs', 'list'):
                ts._convert(s, s['default'])

    def test_check_command(self):
        r = subprocess.run([sys.executable, os.path.join(S.ROOT, 'tool_settings.py'), '--check'], capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for key in ts.BY_KEY:
            self.assertIn(key, r.stdout)


if __name__ == '__main__':
    unittest.main()
