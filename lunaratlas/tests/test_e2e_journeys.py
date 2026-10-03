"""End-to-end tests of whole user journeys: the real command line in a subprocess, the viewer's server, and the
real page in a browser, driven the way a session actually arrives.

test_e2e.py covers the single-image path (locate -> info -> find -> export, and the viewer over HTTP). This file
adds the journeys around it: a folder of images, the image changing under the sidecar, the viewer's edits
surviving a restart, an export run from the page and checked in the pixels, the browser driven through journeys
that span several features, and the paths a real session takes when the output folder or the cache is not what
it should be.

Everything runs the real code: `python3 lunaratlas.py` as a subprocess with its own HOME, the real
ThreadingHTTPServer, and headless Chrome on the real page. Nothing downloads, and no test writes outside its own
temporary directory. The browser checks live in tests/viewer_selftest.js and are run one group at a time through
/selftest?group=NAME, so a failure points at one journey instead of the whole page.
"""
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

import _support as S
import cv2
import numpy as np

import atlas_geo as ag
from atlas_paths import cv_imread, cv_imwrite


def wait_for(fn, timeout=60, what='condition'):
    """fn() until it returns something true, or fail naming what never happened."""
    t0 = time.time()
    while time.time() - t0 < S.budget(timeout):
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError(f'{what} did not happen within {timeout} s')


class Journey(S.TempDir, unittest.TestCase):
    """A folder with a HOME of its own, so nothing reaches the real cache or the real .env.

    Subclasses that build their images once in setUpClass set `self.tmp` there; TempDir.setUp would then make a
    new directory and delete it, so those override setUp and only prepare the HOME.
    """

    def make_home(self):
        self.home = os.path.join(self.tmp, 'home')
        os.makedirs(self.home, exist_ok=True)

    def setUp(self):
        super().setUp()
        self.make_home()

    def cli(self, *argv, **kw):
        return S.run_cli(*argv, home=self.home, **kw)

    def leftovers(self):
        """Temporary files an interrupted run must never leave behind."""
        return [f for _, _, fs in os.walk(self.tmp) for f in fs if '.part' in f]


@S.needs_all
class BatchOfImages(Journey):
    """A session folder holds many images; each gets its own sidecar and none disturbs another."""

    NAMES = ['2026-09-25-2110_1-Moon.tif', '2026-09-25-2120_2-Moon.tif', '2026-09-25-2130_3-Moon.tif']

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='lunaratlas_journey_')
        cls.truth = {}
        for i, n in enumerate(cls.NAMES):
            cls.truth[n] = S.write_image(os.path.join(cls.tmp, n), theta=30.0 + i * 7, lat0=3.2 - i, lon0=-4.1 + i * 2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):                              # the images are built once, so only the HOME is per test
        self.make_home()

    @S.disabled_for_speed
    def test_every_image_is_located_and_keeps_its_own_geometry(self):
        for n in self.NAMES:
            with self.subTest(n):
                r = self.cli('locate', os.path.join(self.tmp, n))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                geo, d = ag.load_geo(os.path.join(self.tmp, n))
                self.assertIsNotNone(geo, d)
                self.assertEqual(d['image'], n)
                self.assertAlmostEqual(geo.lat0, self.truth[n].lat0, delta=0.5)
        self.assertEqual(sorted(f for f in os.listdir(self.tmp) if f.endswith('.atlas.json')),
                         sorted(n + '.atlas.json' for n in self.NAMES))
        self.assertEqual(self.leftovers(), [])

    @S.disabled_for_speed
    def test_info_and_find_work_for_each_of_them(self):
        import lunaratlas as ma
        for n in self.NAMES:                    # locate them all first: each keeps its own geometry
            self.assertEqual(self.cli('locate', os.path.join(self.tmp, n)).returncode, 0)
        # the position the gazetteer gives Copernicus, so `find` is checked against the same numbers
        feats = S.projected_features(self.truth[self.NAMES[0]])
        cop = next(f for f in feats if f['name'] == 'Copernicus')
        for n in self.NAMES:
            r = self.cli('info', os.path.join(self.tmp, n))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('1100 x 1000 px', r.stdout)
            r = self.cli('find', os.path.join(self.tmp, n), 'Copernicus')
            self.assertEqual(r.returncode, 0, r.stderr)
            x, y, _ = self.truth[n].to_image(cop['lat'], cop['lon'])
            m = re.search(r'image x (-?\d+) px, y (-?\d+) px', r.stdout)
            self.assertLess(abs(int(m[1]) - float(x)) + abs(int(m[2]) - float(y)), 3, n)
            self.assertIn('named after', r.stdout)

    @S.disabled_for_speed
    def test_the_capture_time_in_the_name_reaches_the_info_block(self):
        import atlas_ephem as ae
        import atlas_render as ar
        n = self.NAMES[0]
        path = os.path.join(self.tmp, n)
        self.assertEqual(self.cli('locate', path).returncode, 0)
        self.assertEqual((ae.capture_time(path).hour, ae.capture_time(path).minute), (21, 10),
                         'the SharpCap name gives the capture time in UTC')
        self.assertEqual(ar.capture_time(path), '2026-09-25 21:10 UTC', 'the text the info block shows')
        r = self.cli('export', path, '-o', os.path.join(self.tmp, 't.png'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('info block', r.stdout, 'the export drew one')
        # the other two names are ten and twenty minutes later
        self.assertEqual(ae.capture_time(os.path.join(self.tmp, self.NAMES[1])).minute, 20)
        self.assertEqual(ae.capture_time(os.path.join(self.tmp, self.NAMES[2])).minute, 30)

    def test_one_damaged_image_does_not_stop_the_others(self):
        good = os.path.join(self.tmp, self.NAMES[0])
        self.assertEqual(self.cli('locate', good).returncode, 0)
        bad = os.path.join(self.tmp, 'broken.tif')
        with open(bad, 'w') as fh:
            fh.write('not an image')
        r = self.cli('locate', bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('cannot read', r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        self.assertFalse(os.path.exists(ag.sidecar_path(bad)))
        r = self.cli('info', good)                   # the located image is untouched
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1100 x 1000 px', r.stdout)

    @S.disabled_for_speed
    def test_an_optics_file_next_to_the_images_does_not_confuse_a_full_disk(self):
        # a close-up session folder carries lunaratlas_optics.json; a full disk must still be located and labelled
        import lunaratlas as ma
        with open(os.path.join(self.tmp, 'lunaratlas_optics.json'), 'w') as fh:
            json.dump(dict(magnification=2.0, pixel_um=2.0, text='250 PDS · 2× ES · IMX678'), fh)
        n = self.NAMES[0]
        path = os.path.join(self.tmp, n)
        r = self.cli('locate', path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('close-up', r.stdout)
        # the optics line is what the info block will draw
        self.assertEqual(ma.optics_text(path), '250 PDS · 2× ES · IMX678')
        out = os.path.join(self.tmp, 'with_optics.png')
        r = self.cli('export', path, '-o', out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('info block', r.stdout)
        plain = os.path.join(self.tmp, 'plain.png')
        self.assertEqual(self.cli('export', path, '--no-info', '-o', plain).returncode, 0)
        # the info block adds pixels in the bottom-left corner, where it is drawn
        a = cv_imread(out, cv2.IMREAD_UNCHANGED)
        b = cv_imread(plain, cv2.IMREAD_UNCHANGED)
        self.assertEqual(a.shape, b.shape)
        corner = (slice(a.shape[0] - 220, a.shape[0]), slice(0, 420))
        self.assertFalse(np.array_equal(a[corner], b[corner]), 'the info block was drawn in the corner')


@S.needs_all
class TheWholeLoop(Journey):
    """locate, export, then the image changes underneath, and the stale sidecar must be caught."""

    def setUp(self):
        super().setUp()
        self.img = os.path.join(self.tmp, '2026-09-23-2138_1-Moon.tif')

    @S.disabled_for_speed
    def test_locate_export_then_the_image_is_replaced(self):
        S.write_image(self.img)
        r = self.cli('locate', self.img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = S.sidecar(self.img)
        self.assertIn('quality OK', r.stdout)

        out = os.path.join(self.tmp, 'first.png')
        r = self.cli('export', self.img, '-o', out)
        self.assertEqual(r.returncode, 0, r.stderr)
        im = cv_imread(out, cv2.IMREAD_UNCHANGED)
        self.assertEqual((im.shape, im.dtype), ((1000, 1100, 3), np.uint16))

        # the user replaces the image (a crop, a rotation) without touching the sidecar
        cv_imwrite(self.img, np.rot90(cv_imread(self.img, cv2.IMREAD_UNCHANGED)))
        r = self.cli('export', self.img, '-o', os.path.join(self.tmp, 'stale.png'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('image changed since it was located', r.stdout)
        self.assertIn('locating again', r.stdout)
        second = S.sidecar(self.img)
        self.assertNotEqual(second['image_signature'], first['image_signature'])
        self.assertEqual((second['width'], second['height']), (1000, 1100), 'the rotated image is 1000 x 1100')
        self.assertNotEqual(cv_imread(out, cv2.IMREAD_UNCHANGED).shape,
                            cv_imread(os.path.join(self.tmp, 'stale.png'), cv2.IMREAD_UNCHANGED).shape)
        self.assertEqual(self.leftovers(), [])

    @S.disabled_for_speed
    def test_the_pair_survives_being_copied_to_an_archive(self):
        # users copy IMAGE + IMAGE.atlas.json into a folder; the copy must export exactly like the original
        S.write_image(self.img)
        self.assertEqual(self.cli('locate', self.img).returncode, 0)
        first = os.path.join(self.tmp, 'first.png')
        self.assertEqual(self.cli('export', self.img, '-o', first).returncode, 0)
        # the copy keeps the file name, because the info block shows it
        archive = os.path.join(self.tmp, '2025-08')
        os.makedirs(archive)
        other = os.path.join(archive, os.path.basename(self.img))
        shutil.copy(self.img, other)
        shutil.copy(ag.sidecar_path(self.img), ag.sidecar_path(other))
        r = self.cli('info', other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1100 x 1000 px', r.stdout)
        second = os.path.join(self.tmp, 'copy.png')
        self.assertEqual(self.cli('export', other, '-o', second).returncode, 0)
        np.testing.assert_array_equal(cv_imread(first, cv2.IMREAD_UNCHANGED),
                                      cv_imread(second, cv2.IMREAD_UNCHANGED))
        # and the original's sidecar was not changed by exporting the copy
        self.assertNotIn('edits', S.sidecar(self.img))

    @S.disabled_for_speed
    def test_a_second_locate_is_quick_and_export_reads_the_sidecar(self):
        S.write_image(self.img)
        self.assertEqual(self.cli('locate', self.img).returncode, 0)
        r = self.cli('export', self.img, '-o', os.path.join(self.tmp, 'reuse.png'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('positioning from', r.stdout, 'export must not locate the image again')
        self.assertNotIn('locating', r.stdout)
        # locate again: the same geometry, and the sidecar is rewritten in place
        before = S.sidecar(self.img)['geometry']
        self.assertEqual(self.cli('locate', self.img).returncode, 0)
        self.assertEqual(S.sidecar(self.img)['geometry'], before)
        self.assertEqual(self.leftovers(), [])

    @S.disabled_for_speed
    def test_export_refuses_to_overwrite_the_image_or_its_sidecar(self):
        S.write_image(self.img)
        self.assertEqual(self.cli('locate', self.img).returncode, 0)
        side = ag.sidecar_path(self.img)
        r = self.cli('export', self.img, '-o', side)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('Traceback', r.stderr)
        self.assertIn(os.path.basename(side), r.stderr)
        # the image itself, reached through a name the encoder accepts, is refused as well
        link = os.path.join(self.tmp, 'as_output.png')
        try:
            os.link(self.img, link)
        except OSError:
            self.skipTest('no hard links here')
        r = self.cli('export', self.img, '-o', link)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('refusing to overwrite', r.stderr)
        self.assertTrue(os.path.exists(self.img))
        self.assertEqual(S.sidecar(self.img)['image'], os.path.basename(self.img))
        self.assertAlmostEqual(S.sidecar(self.img)['derived']['libration_lat'], 3.2, delta=0.2)

    @S.disabled_for_speed
    def test_a_missing_output_folder_is_refused_before_any_work(self):
        S.write_image(self.img)
        self.assertEqual(self.cli('locate', self.img).returncode, 0)
        r = self.cli('export', self.img, '-o', os.path.join(self.tmp, 'nope', 'x.png'))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('does not exist', r.stderr)
        self.assertNotIn('Traceback', r.stderr)


@S.needs_all
class ViewerJourney(Journey):
    """The viewer as a user drives it: draw, save, stop, start again, and the edits are still there."""

    def setUp(self):
        super().setUp()
        self.img, self.geo = S.moon_image(self.tmp, '2026-09-23-2138_1-Moon.tif')
        self.v = S.Viewer(self.img, self.home)
        self.addCleanup(self.v.close)
        self.cx, self.cy = (float(t) for t in self.geo.t)

    def wait_export(self, timeout=180):
        def done():
            s = self.v.request('/export/status')[1]
            return s if s['state'] != 'running' else None
        return wait_for(done, timeout, 'the export')

    def data_js(self, viewer=None):
        code, body, _ = (viewer or self.v).request('/data.json', raw=True)
        self.assertEqual(code, 200)
        return json.loads(body.decode())

    def test_edits_survive_a_restart_of_the_viewer(self):
        e = dict(shapes=[dict(kind='circle', cx=self.cx, cy=self.cy, r=40, label='mine', colour='#ffb45a'),
                         dict(kind='measure', a=dict(x=self.cx - 60, y=self.cy), b=dict(x=self.cx + 60, y=self.cy))],
                 hidden=['Tycho'], labels={'Copernicus': dict(dx=10, dy=-6, colour='#00ff00')},
                 style=dict(font='Inter', minPx=30, fs=1.1, night='dim', grid=True, rims=False))
        code, saved, _ = self.v.request('/edits', e)
        self.assertEqual(code, 200, saved)
        self.assertEqual(len(saved['shapes']), 2)
        self.v.close()

        v2 = S.Viewer(self.img, self.home)
        self.addCleanup(v2.close)
        got = v2.request('/edits')[1]
        self.assertEqual(got['shapes'], saved['shapes'])
        self.assertEqual(got['hidden'], ['Tycho'])
        self.assertEqual(got['labels'], saved['labels'])
        self.assertEqual(got['style']['font'], 'Inter')
        self.assertEqual(self.data_js(v2)['geometry'], self.geo.as_dict())

    def test_the_export_run_from_the_page_really_contains_the_drawings(self):
        self.v.request('/edits', dict(shapes=[dict(kind='circle', cx=self.cx, cy=self.cy, r=60, colour='#ff0000')]))
        code, j, _ = self.v.request('/export', dict(format='png'))
        self.assertEqual(code, 200, j)
        s = self.wait_export()
        self.assertEqual(s['state'], 'done', s)
        self.assertTrue(any('1 of your drawings' in line for line in s['lines']), s['lines'])
        im = cv_imread(s['output'], cv2.IMREAD_UNCHANGED)
        self.assertEqual(im.shape, (1000, 1100, 3))
        # the ring is really on the pixels: red (BGR: the high channel) where it passes, above the centre
        y, x = int(round(self.cy)), int(round(self.cx))
        ring = im[max(0, y - 60):y - 55, x - 3:x + 3].astype(int)
        self.assertGreater(int(ring[..., 2].max()), 20000, 'the drawn circle is missing from the export')
        inside = im[y - 3:y + 3, x - 3:x + 3].astype(int)
        self.assertLess(int(inside[..., 2].max()), 20000, 'the middle of the circle is not filled in')

    def test_hiding_a_name_removes_its_letters_from_the_export(self):
        feats = S.projected_features(self.geo)
        cop = next(f for f in feats if f['name'] == 'Copernicus')
        base = os.path.join(self.tmp, 'base.png')
        self.assertEqual(self.cli('export', self.img, '-o', base).returncode, 0)
        self.v.request('/edits', dict(hidden=['Copernicus']))
        hid = os.path.join(self.tmp, 'hidden.png')
        r = self.cli('export', self.img, '-o', hid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1 hidden in the viewer', r.stdout)
        a = cv_imread(base, cv2.IMREAD_UNCHANGED)
        b = cv_imread(hid, cv2.IMREAD_UNCHANGED)
        self.assertEqual(a.shape, b.shape)
        self.assertFalse(np.array_equal(a, b), 'hiding a name must change the export')
        # the letters themselves are gone where Copernicus was, not merely somewhere else on the disk
        x, y, _ = self.geo.to_image(cop['lat'], cop['lon'])
        x, y = int(x), int(y)
        win = (slice(max(0, y - 45), y + 45), slice(max(0, x - 95), x + 95))
        bright_a = int((a[win] > 40000).sum())
        gone = int(((a[win] > 40000) & (b[win] <= 40000)).sum())      # a name that had no room may move in beside it
        self.assertGreater(bright_a, 200, 'the label was drawn there to begin with')
        self.assertGreater(gone, bright_a * 0.5, f'of {bright_a} bright pixels only {gone} went')

    @S.disabled_for_speed
    def test_the_viewer_refuses_a_poor_image_until_force_is_given(self):
        # an overexposed disk: the quality gate refuses it, but it still locates, so --force can open it
        burnt = os.path.join(self.tmp, 'burnt.tif')
        S.write_image(burnt, img01=np.clip(S.synthetic_moon()[0] * 2.5, 0, 1))
        r = self.cli('view', burnt, '--no-open', '--port', str(S.free_port()), timeout=S.budget(300))
        self.assertNotEqual(r.returncode, 0, 'a refused image must not open a viewer')
        self.assertIn('overexposed', r.stderr + r.stdout)
        self.assertNotIn('Traceback', r.stderr)
        v = S.Viewer(burnt, self.home, extra=('--force',))
        self.addCleanup(v.close)
        self.assertIn('overexposed', self.data_js(v)['gate'], 'the page is told why the image is poor')

    def test_two_viewers_of_the_same_image_share_the_cache_and_agree_on_the_edits(self):
        self.v.request('/edits', dict(shapes=[dict(kind='text', x=self.cx, y=self.cy, label='first')]))
        v2 = S.Viewer(self.img, self.home)
        self.addCleanup(v2.close)
        self.assertNotEqual(v2.url, self.v.url, 'the second viewer takes the next free port')
        self.assertEqual(v2.request('/edits')[1]['shapes'][0]['label'], 'first')
        v2.request('/edits', dict(shapes=[dict(kind='text', x=self.cx, y=self.cy, label='second')]))
        self.assertEqual(self.v.request('/edits')[1]['shapes'][0]['label'], 'second')
        tiles = os.path.join(S.cache_dir(self.home), 'tiles')
        self.assertEqual(len(os.listdir(tiles)), 1, 'one cache folder per image, shared by both viewers')
        self.assertEqual(self.v.request('/data.json')[0], 200)


@S.needs_all
@unittest.skipUnless(S.find_chrome(), 'no Chrome or Chromium (set LUNARATLAS_CHROME to its executable)')
class BrowserJourneys(Journey):
    """Headless Chrome on the real page, one journey at a time.

    The checks live in tests/viewer_selftest.js, which the viewer serves at /selftest: that runs the real
    index.html with the real viewer.js, so nothing here can drift from the page. `?group=NAME` picks one journey,
    so a failure names the journey instead of the whole page. Headless Chrome does not run
    requestAnimationFrame, which is why the script calls render() itself.
    """

    def setUp(self):
        super().setUp()
        self.img, self.geo = S.moon_image(self.tmp)

    def drive(self, group, budget=None, patience=30):
        """Run one journey group and return the PASS lines it wrote into <pre id="selftest">."""
        # Chrome's own --virtual-time-budget, in simulated ms: real work gated behind it (image decode, the
        # gazetteer fetch, label layout) still costs real CPU time, so a loaded CI runner can run out of this
        # budget before that work is done even though the self-test's own polling loop still had time left
        budget = int(40000 * S.PERF) if budget is None else budget
        v = S.Viewer(self.img, self.home)
        self.addCleanup(v.close)
        # in real time through Node (S.run_selftest); --dump-dom's virtual time stalled groups partway on CI runners
        url = f'{v.url}/selftest?group={group}&t={v.token}'
        m, log_text = S.run_selftest(url, self.tmp, patience) if S.NODE else S.dump_selftest(url, self.tmp, budget)
        self.assertIsNotNone(m, f'the {group} self-test wrote no result:\n{log_text[-2000:]}')
        lines = html.unescape(m[1]).splitlines()
        self.assertEqual([l for l in lines if not l.startswith('PASS')], [], '\n'.join(lines) + log_text[-800:])
        return lines

    def test_the_page_places_one_label_per_name_and_all_of_them_on_the_canvas(self):
        lines = self.drive('load')
        self.assertGreaterEqual(len(lines), 8)
        self.assertTrue(any('gazetteer' in l for l in lines), '\n'.join(lines))
        self.assertTrue(any('no name is placed twice' in l for l in lines), '\n'.join(lines))
        self.assertEqual(S.sidecar(self.img).get('edits', {}).get('shapes', []), [],
                         'the load journey must not change the sidecar')

    def test_search_offers_a_name_and_nothing_for_one_that_does_not_exist(self):
        lines = self.drive('search')
        self.assertGreaterEqual(len(lines), 3)
        self.assertTrue(any('Tycho' in l for l in lines), '\n'.join(lines))

    def test_zooming_keeps_the_names_and_a_layer_can_be_turned_off(self):
        lines = self.drive('layers')
        self.assertGreaterEqual(len(lines), 5)
        self.assertTrue(any('layer off' in l for l in lines), '\n'.join(lines))

    def test_alt_picks_several_names_and_delete_hides_them_in_one_undo_step(self):
        lines = self.drive('picks')
        self.assertTrue(any('Delete hides both' in l for l in lines), lines)

    def test_a_click_on_the_switch_itself_toggles_the_layer(self):
        lines = self.drive('switches')
        self.assertTrue(any('turns craters off' in l for l in lines), lines)

    def test_the_crater_card_never_covers_the_layers_panel(self):
        lines = self.drive('card')
        self.assertEqual(len(lines), 5, lines)
        self.assertTrue(any('does not cover' in l for l in lines), lines)

    def test_a_name_made_larger_from_its_card_grows_instead_of_vanishing(self):
        lines = self.drive('sizes')
        self.assertEqual(len(lines), 5, '\n'.join(lines))
        self.assertTrue(any('Extra large' in l for l in lines), '\n'.join(lines))
        self.assertEqual(S.sidecar(self.img).get('edits', {}).get('labels', {}), {},
                         'the sizes journey must leave the sidecar as it found it')

    @S.label_sweep
    def test_no_name_vanishes_at_any_size_zoomed_in_or_out(self):
        lines = self.drive('sizesweep', budget=int(120000 * S.PERF), patience=120)
        self.assertEqual(len(lines), 3, '\n'.join(lines))
        self.assertEqual(S.sidecar(self.img).get('edits', {}).get('labels', {}), {},
                         'the size sweep must leave the sidecar as it found it')

    @S.label_sweep
    def test_no_name_vanishes_at_any_size_on_a_close_up(self):
        """The same on a photo of part of the Moon: the disk four times larger than the frame, no limb in it."""
        self.img, self.geo = S.moon_image(self.tmp, 'closeup.tif', R=1800.0, cx=900.0, cy=300.0)
        lines = self.drive('sizesweep', budget=int(120000 * S.PERF), patience=120)
        self.assertEqual(len(lines), 3, '\n'.join(lines))

    def test_a_measurement_is_drawn_undone_redone_and_reaches_the_sidecar(self):
        lines = self.drive('measure')
        self.assertGreaterEqual(len(lines), 6)
        self.assertTrue(any('redo brings it back' in l for l in lines), '\n'.join(lines))
        self.assertEqual(S.sidecar(self.img).get('edits', {}).get('shapes', []), [],
                         'the measure journey must leave the sidecar as it found it')

    @S.disabled_for_speed
    def test_the_fixes_for_lettered_craters_moved_names_dashed_arrows_and_measurements(self):
        lines = self.drive('fixes')
        self.assertEqual(len(lines), 10, '\n'.join(lines))
        self.assertEqual(S.sidecar(self.img).get('edits', {}).get('shapes', []), [],
                         'the fixes journey must leave the sidecar as it found it')


if __name__ == '__main__':
    unittest.main()
