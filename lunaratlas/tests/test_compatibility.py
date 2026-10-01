"""Compatibility tests: image formats in and out, the viewer's JavaScript against the Python it ports, older and
foreign sidecars, platforms (Windows, Linux, macOS) and the settings documentation.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import _support as S
import cv2
import numpy as np

import atlas_ephem as ae
import atlas_geo as ag
import atlas_render as ar
import atlas_view as av
from atlas_paths import cv_imread, cv_imwrite
import tool_settings as ts

VIEWER_JS = os.path.join(S.PKG, 'viewer', 'viewer.js')
NODE = shutil.which('node')

# (file name, dtype, channels, extra cv2.imwrite parameters): what capture, stacking and editing
# software and web downloads produce
FORMATS = [('mono16.tif', np.uint16, 1, ()), ('mono8.png', np.uint8, 1, ()), ('mono16.png', np.uint16, 1, ()),
           ('rgb16.tif', np.uint16, 3, ()), ('rgb8.jpg', np.uint8, 3, (cv2.IMWRITE_JPEG_QUALITY, 95)),
           ('rgba8.png', np.uint8, 4, ()), ('rgba16.tif', np.uint16, 4, ()), ('float01.tif', np.float32, 1, ()),
           ('float_rgb.tif', np.float32, 3, ()), ('lzw16.tif', np.uint16, 1, (cv2.IMWRITE_TIFF_COMPRESSION, 5))]


@S.needs_all
class InputFormats(S.TempDir, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img01, cls.geo = S.synthetic_moon()

    def write(self, name, dtype, channels, params):
        p = os.path.join(self.tmp, name)
        S.write_image(p, self.img01, dtype, channels, params)
        S.locate_as(p, self.geo)
        return p

    def test_every_format_exports(self):
        for name, dtype, ch, params in FORMATS:
            with self.subTest(name):
                p = self.write(name, dtype, ch, params)
                raw = cv_imread(p, cv2.IMREAD_UNCHANGED)
                self.assertEqual(raw.dtype, dtype)
                for fmt in ('tiff', 'jpg'):
                    out = os.path.join(self.tmp, f'{name}.out.{fmt}')
                    code, log = S.run_main('export', p, '-o', out, '--no-grid', '--layers', 'none')   # tonality, not name shades
                    self.assertIsNone(code, log)
                    im = cv_imread(out, cv2.IMREAD_UNCHANGED)
                    self.assertEqual(im.shape, (1000, 1100, 3))
                    self.assertEqual(im.dtype, np.uint8 if fmt == 'jpg' else np.uint16)
                    # the tonality is kept: the disk centre is as bright in the output as in the input
                    y, x = (int(v) for v in (self.geo.t[1] + 30, self.geo.t[0] - 40))
                    src = self.img01[y, x] * 0.97 if ch >= 3 else self.img01[y, x]
                    top = 255 if fmt == 'jpg' else 65535
                    self.assertAlmostEqual(float(im[y, x, 0]) / top, float(src), delta=0.03, msg=f'{name} -> {fmt}')

    def test_float_data_scaled_to_16_bit(self):
        p = os.path.join(self.tmp, 'float_full.tif')
        cv_imwrite(p, (self.img01 * 65535).astype(np.float32))             # already 0-65535
        S.locate_as(p, self.geo)
        out = os.path.join(self.tmp, 'ff.tif')
        code, log = S.run_main('export', p, '-o', out, '--layers', 'none', '--no-grid', '--no-info')
        self.assertIsNone(code, log)
        self.assertIn('0–65535 scale', log)
        got = cv_imread(out, cv2.IMREAD_UNCHANGED)[..., 0].astype(float)
        self.assertLess(np.abs(got - self.img01 * 65535).max(), 1.01)

    def test_quality_gate_on_every_format(self):
        import lunaratlas as ma
        for name, dtype, ch, params in FORMATS:
            with self.subTest(name):
                ok, reasons, line, q = ma.quality_gate(self.write(name, dtype, ch, params))
                self.assertTrue(ok, f'{name}: {line}')
                self.assertTrue(q['has_limb'], name)
                self.assertEqual(q['channels'], min(ch, 3) if ch > 1 else 1)

    def test_tiles_from_every_format(self):
        for name, dtype, ch, params in FORMATS:
            with self.subTest(name):
                p = self.write(name, dtype, ch, params)
                raw = cv_imread(p, cv2.IMREAD_UNCHANGED)
                with mock.patch.object(av, 'CACHE', os.path.join(self.tmp, 'cache')):
                    levels = av.build_tiles(p, raw, S.quiet)
                    t = cv_imread(os.path.join(av.tile_dir(p), '0', '1_1.jpg'))
                self.assertEqual(len(levels), 3)
                self.assertEqual(t.shape, (488, 512, 3))
                self.assertGreater(t.mean(), 20)                              # stretched for display, not black

    def test_locate_an_8_bit_colour_jpeg(self):
        p = os.path.join(self.tmp, 'downloaded.jpg')
        S.write_image(p, self.img01, np.uint8, 3, (cv2.IMWRITE_JPEG_QUALITY, 90))
        geo, q = ag.locate(p, log=S.quiet)
        med, worst = S.pixel_error(self.geo, geo, 1100, 1000)
        self.assertLess(worst, 1.0)
        self.assertEqual(bool(geo.mirrored), False)


@unittest.skipUnless(NODE, 'node not installed')
class ViewerJavaScript(unittest.TestCase):
    """viewer.js carries a port of atlas_geo.Geometry: both must put every pixel at the same lat/lon."""

    def run_js(self, geo, pixels, latlon, pairs):
        with open(VIEWER_JS, encoding='utf-8') as fh:
            js = fh.read()
        start = js.index('// ------------------------------------------------------------ geometry')
        end = js.index('// ------------------------------------------------------------ edits')
        script = ("const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
                  'const G = input.geometry, RM = input.R_moon;\n' + js[start:end] +
                  "\nconst u = (la, lo) => [Math.cos(la * rad) * Math.cos(lo * rad), Math.cos(la * rad) * Math.sin(lo * rad), Math.sin(la * rad)];"
                  '\nconst inv = input.pixels.map(([x, y]) => { const r = toLatLon(x, y); return r ? [r.lat, r.lon] : null; });'
                  '\nconst fwd = input.latlon.map(([la, lo]) => toImage(u(la, lo)));'
                  '\nconst km = input.pairs.map(([a, b]) => gcKm(u(...a), u(...b)));'
                  '\nconsole.log(JSON.stringify({ inv, fwd, km }));\n')
        r = subprocess.run([NODE, '-e', script], input=json.dumps(dict(geometry=geo.as_dict(), R_moon=ag.R_MOON,
                           pixels=pixels, latlon=latlon, pairs=pairs)), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def check(self, geo):
        rng = np.random.default_rng(0)
        pixels = rng.uniform(0, 1100, (400, 2)).tolist() + [[float(geo.t[0]), float(geo.t[1])], [0.0, 0.0]]
        latlon = np.stack([rng.uniform(-80, 80, 300), rng.uniform(-90, 90, 300)], 1).tolist()
        pairs = [[[0, 0], [0, 1]], [[10, -20], [-30, 40]], [[45, 45], [45, 45]]]
        out = self.run_js(geo, pixels, latlon, pairs)
        P = np.array(pixels)
        la, lo, ok = geo.to_latlon(P[:, 0], P[:, 1])
        for i, v in enumerate(out['inv']):
            self.assertEqual(v is not None, bool(ok[i]), P[i])
            if v is not None:
                self.assertAlmostEqual(v[0], float(la[i]), delta=1e-7)
                self.assertAlmostEqual(v[1], float(lo[i]), delta=1e-7)
        L = np.array(latlon)
        x, y, z = geo.to_image(L[:, 0], L[:, 1])
        np.testing.assert_allclose(np.array(out['fwd']), np.stack([x, y, z], 1), atol=1e-7)
        for (a, b), km in zip(pairs, out['km']):
            p, q = ag.unit(*a), ag.unit(*b)
            self.assertAlmostEqual(km, float(np.arccos(np.clip(p @ q, -1, 1))) * ag.R_MOON, delta=1e-6)

    def test_plain_geometry(self):
        self.check(S.truth_geometry())

    def test_mirrored_geometry(self):
        self.check(S.truth_geometry(mirror=True, theta=123.0, lat0=-6.0, lon0=7.5))

    def test_with_a_correction_field(self):
        g = S.truth_geometry()
        coef = np.random.default_rng(1).normal(0, 0.5, (15, 2))
        self.check(ag.Geometry(g.lat0, g.lon0, g.A, g.t, coef, 4, 0.85))

    def test_javascript_parses(self):
        for f in (VIEWER_JS, os.path.join(S.HERE, 'viewer_selftest.js')):
            r = subprocess.run([NODE, '--check', f], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f + '\n' + r.stderr)


class ViewerMatchesExport(unittest.TestCase):
    """The viewer lays out and styles names like the export: the same classes, layers, sizes and colour."""

    @classmethod
    def setUpClass(cls):
        with open(VIEWER_JS, encoding='utf-8') as fh:
            cls.js = fh.read()
        with open(os.path.join(S.PKG, 'atlas_render.py'), encoding='utf-8') as fh:
            cls.py = fh.read()
        with open(os.path.join(S.PKG, 'viewer', 'index.html'), encoding='utf-8') as fh:
            cls.html = fh.read()
        with open(os.path.join(S.PKG, 'viewer', 'viewer.css'), encoding='utf-8') as fh:
            cls.css = fh.read()

    def js_object(self, name):
        body = re.search(r'const %s = \{([^}]*)\}' % name, self.js)[1]
        return dict(re.findall(r"(\w+): '?([\w.]+)'?", body))

    def test_layers(self):
        js = json.loads(re.search(r"const LAYERS5 = (\[[^\]]*\])", self.js)[1].replace("'", '"'))
        html = re.findall(r'data-layer="(\w+)"', self.html)
        self.assertEqual(tuple(js), ar.LAYERS)
        self.assertEqual(tuple(js), ts.LAYER_NAMES)
        self.assertEqual(html[:5], js)
        self.assertEqual({k: v for k, v in self.js_object('LAYER').items()}, ar.LAYER_OF)

    def test_rank(self):
        rank = {k: int(v) for k, v in self.js_object('RANK').items()}
        py = eval(re.search(r"rank = (\{[^}]*\})", self.py)[1])
        self.assertEqual(rank, py)

    def test_label_colour(self):
        hexc = '#%02x%02x%02x' % ar.LABEL_RGB
        self.assertIn(f"const LABEL = '{hexc}'", self.js)
        self.assertIn(f'--label: {hexc};', self.css)

    def test_size_rules(self):
        pairs = [('np.clip(Dpx * 0.05, 15, 34), 300', 'size = clamp(D * 0.05, 15, 34); w = 300'),
                 ('np.clip(12 + 3.5 * k, 13, 26), 560', 'size = clamp(12 + 3.5 * k, 13, 26); w = 560'),
                 ('np.clip(10 + 2.0 * k, 11, 16), 420', 'size = clamp(10 + 2 * k, 11, 16); w = 420'),
                 ('np.clip(11 + 2.5 * k, 12, 20), 430', 'size = clamp(11 + 2.5 * k, 12, 20); w = 430'),
                 ('Dpx < min_px * 0.3', 'D < minPx * 0.3'), ('Dpx < min_px * 1.5', 'D < minPx * 1.5'),
                 ('geo.km_per_px / scale > 3.0', 'kmPerScreenPx > 3'), ('light[i] < 0.12', 'f.lit < 0.12'),
                 ('track, txt = np.clip(Dpx * 0.05, 15, 34), 300, C[\'area\'], 0.22', 'track = 0.22'),
                 ('math.log2(max(Dpx, 1e-3) / min_px + 1)', 'Math.log2(Math.max(D, 1e-3) / minPx + 1)'),
                 ('R * 0.995', 'R * 0.995'), ('g = 4 * font_scale', 'g = 4 * fs'), ('g = 7 * font_scale', 'g = 7 * fs')]
        for py, js in pairs:
            self.assertIn(py.split(", C['area']")[0] if 'track, txt' in py else py, self.py, 'atlas_render.layout changed')
            self.assertIn(js, self.js, f'viewer.js layout() no longer matches atlas_render.layout: {js}')

    def test_viewer_fonts(self):
        self.assertEqual(av.VIEWER_FONTS[0], ar.DEFAULT_FONT)
        help_text = ts.BY_KEY['LUNARATLAS_FONT']['help']
        for fam in av.VIEWER_FONTS:
            self.assertIn(fam, help_text)

    def test_export_dialog_options_reach_the_cli(self):
        for key in ('format', 'scale', 'max_size', 'names', 'layers', 'rims', 'grid', 'drawings', 'info', 'night',
                    'min_px', 'font_scale', 'font'):
            self.assertRegex(self.js, r'\b%s:' % key, key)
        for flag in re.findall(r"'(--[\w-]+)'", open(os.path.join(S.PKG, 'atlas_view.py'), encoding='utf-8').read()):
            if flag.startswith('--no-'):
                flag = '--' + flag[5:]
            self.assertIn(flag, open(os.path.join(S.PKG, 'lunaratlas.py'), encoding='utf-8').read(), flag)


class Sidecars(S.TempDir, unittest.TestCase):
    def image(self):
        p = os.path.join(self.tmp, 'a.tif')
        cv_imwrite(p, np.zeros((10, 10), np.uint8))
        return p

    def test_older_geometry_without_optional_fields(self):
        p = self.image()
        S.locate_as(p, S.truth_geometry())
        d = S.sidecar(p)
        for k in ('coef', 'deg', 'rmax', 'dist'):
            d['geometry'].pop(k)
        ag.write_json_atomic(ag.sidecar_path(p), d)
        g, _ = ag.load_geo(p)
        self.assertEqual((g.deg, g.rmax, g.dist, g.coef), (0, 0.9, ag.DIST, None))

    def test_unknown_fields_survive_locate_and_edits(self):
        p = self.image()
        S.locate_as(p, S.truth_geometry())
        d = S.sidecar(p)
        d['lunar_mosaic'] = dict(panels=12)
        ag.write_json_atomic(ag.sidecar_path(p), d)
        import threading
        av.write_edits(p, dict(hidden=['x']), threading.Lock())
        S.locate_as(p, S.truth_geometry(theta=10.0))                           # located again
        d = S.sidecar(p)
        self.assertEqual(d['lunar_mosaic'], dict(panels=12))
        self.assertEqual(d['edits']['hidden'], ['x'])                           # the viewer's edits are kept

    def test_other_schema(self):
        p = self.image()
        S.locate_as(p, S.truth_geometry())
        d = S.sidecar(p)
        d['schema'] = 'lunaratlas.geo/2'
        ag.write_json_atomic(ag.sidecar_path(p), d)
        g, d = ag.load_geo(p)
        self.assertIsNone(g)
        self.assertIn("unsupported schema 'lunaratlas.geo/2'", d['problem'])

    def test_sidecar_is_ascii_so_any_locale_reads_it(self):
        # Windows opens text in the ANSI code page unless told otherwise; load_geo does not pass an encoding
        p = os.path.join(self.tmp, 'Mare Crisium – Ångström é.tif')
        cv_imwrite(p, np.zeros((10, 10), np.uint8))
        S.locate_as(p, S.truth_geometry())
        import threading
        av.write_edits(p, dict(shapes=[dict(kind='text', x=1, y=1, label='Grimaldi · Riccioli — 月')]), threading.Lock())
        with open(ag.sidecar_path(p), 'rb') as fh:
            raw = fh.read()
        raw.decode('ascii')
        self.assertIn('月', S.sidecar(p)['edits']['shapes'][0]['label'])

    def test_path_forms(self):
        # the full name, extension included, so same-stem images (moon.tif / moon.jpg) never share a sidecar
        # (bugs-overview BUG-05)
        self.assertEqual(ag.sidecar_path('/x/y/m.v2.final.TIF'), '/x/y/m.v2.final.TIF.atlas.json')
        self.assertEqual(ag.sidecar_path('noext'), 'noext.atlas.json')
        self.assertEqual(av.tile_dir('/a/b.tif'), av.tile_dir('/a/b.tif'))         # stable between runs
        self.assertNotEqual(av.tile_dir('/a/b.tif'), av.tile_dir('/a/c.tif'))


class Platforms(unittest.TestCase):
    def test_capture_time_in_windows_paths(self):
        t = ae.capture_time(r'C:\Users\me\Moon\2026-09-23-2138_1-Moon.tif')
        self.assertEqual((t.hour, t.minute, t.second), (21, 38, 6))

    def test_both_capture_time_parsers_agree(self):
        for name in ('2026-09-23-2138_1-Moon_Filter 4.tif', 'x_2026-01-02-0304_5_y.png', '2026-12-31-2359_9.tif',
                     'Moon_220923.tif', '2026-09-23-2138-Moon.tif', 'IMG_0001.JPG'):
            t = ae.capture_time(name)
            text = ar.capture_time(name)
            self.assertEqual(t is None, text is None, name)
            if t:
                self.assertEqual(text, t.strftime('%Y-%m-%d %H:%M UTC'), name)

    def test_reveal_never_uses_a_shell(self):
        with mock.patch.object(av.subprocess, 'Popen') as po:
            av.reveal('/tmp/a; rm -rf ~.tif')
        args, kw = po.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn('shell', kw)

    def test_tile_cache_location(self):
        import atlas_paths
        self.assertEqual(av.CACHE, os.path.join(atlas_paths.user_dir('cache'), 'tiles'))
        if sys.platform == 'darwin':
            self.assertTrue(av.CACHE.endswith(os.path.join('Library', 'Caches', 'LunarAtlas', 'tiles')))


def _without_cpu_scaled_defaults(text):
    """MOSAIC_WORKERS and MOSAIC_CLASSIFIER_WORKERS default to a count derived from os.cpu_count(), so the
    committed .env.example (generated on one machine) and a freshly generated one agree on every setting except
    these two, which differ by core count alone."""
    return re.sub(r'^# (MOSAIC_WORKERS|MOSAIC_CLASSIFIER_WORKERS)=\d+$', r'# \1=N', text, flags=re.MULTILINE)


class SettingsDocumentation(unittest.TestCase):
    def test_env_example_is_generated_from_the_registry(self):
        with open(os.path.join(S.ROOT, '.env.example'), encoding='utf-8') as fh:
            committed = fh.read()
        self.assertEqual(_without_cpu_scaled_defaults(committed), _without_cpu_scaled_defaults(ts.example()),
                         'run `python3 tool_settings.py --example`')

    def test_readme_counts(self):
        with open(os.path.join(S.PKG, 'README.md'), encoding='utf-8') as fh:
            readme = fh.read()
        n = int(re.search(r'All (\d+) settings are declared', readme)[1])
        self.assertEqual(n, len(ts.BY_KEY))

    def test_every_setting_read_by_lunaratlas_is_declared(self):
        used = set()
        for f in os.listdir(S.PKG):
            if f.endswith('.py'):
                with open(os.path.join(S.PKG, f), encoding='utf-8') as fh:
                    used |= set(re.findall(r"\bts\.(?:get|pairs)\('(\w+)'", fh.read()))
        self.assertTrue(used)
        self.assertEqual(used - set(ts.BY_KEY), set())

    def test_feature_count_in_readme(self):
        if not S.HAVE_FEATURES:
            self.skipTest('IAU nomenclature not in lunaratlas/data')
        from atlas_names import load_features
        with open(os.path.join(S.PKG, 'README.md'), encoding='utf-8') as fh:
            n = int(re.search(r'IAU nomenclature \((\d+) features\)', fh.read())[1])
        self.assertEqual(n, len(load_features(S.quiet, sites=False)))


if __name__ == '__main__':
    unittest.main()
