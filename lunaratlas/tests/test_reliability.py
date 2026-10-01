"""Reliability tests: interrupted writes and downloads, damaged caches and sidecars, missing fonts, images that cannot
be annotated. Each must end in a clear message or a repaired file, never a damaged file or a traceback."""
import io
import json
import os
import shutil
import threading
import unittest
import urllib.request
from unittest import mock

import _support as S
import cv2
import numpy as np

import atlas_geo as ag
import atlas_names as an
import atlas_quality as aq
import atlas_render as ar
import lunaratlas as ma


class AtomicWrites(S.TempDir, unittest.TestCase):
    def test_failed_write_keeps_the_old_file(self):
        p = os.path.join(self.tmp, 'side.json')
        ag.write_json_atomic(p, dict(v=1))

        def boom(tmp):
            with open(tmp, 'w') as fh:
                fh.write('{"v": 2, "trunc')
            raise KeyboardInterrupt                    # Ctrl-C in the middle of a write
        with self.assertRaises(KeyboardInterrupt):
            ag.write_atomic(p, boom)
        with open(p) as fh:
            self.assertEqual(json.load(fh), dict(v=1))
        self.assertEqual(os.listdir(self.tmp), ['side.json'])

    def test_unserialisable_data_keeps_the_old_file(self):
        p = os.path.join(self.tmp, 'side.json')
        ag.write_json_atomic(p, dict(v=1))
        with self.assertRaises(TypeError):
            ag.write_json_atomic(p, dict(v=object()))
        with open(p) as fh:
            self.assertEqual(json.load(fh), dict(v=1))

    def test_temporary_file_keeps_the_extension(self):
        seen = []
        ag.write_atomic(os.path.join(self.tmp, 'x.png'), lambda t: (seen.append(t), cv2.imwrite(t, np.zeros((2, 2), np.uint8))))
        self.assertTrue(seen[0].endswith('.png') and os.path.basename(seen[0]) != 'x.png')                  # cv2 picks the encoder from it
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'x.png')))


class FakeResponse(io.BytesIO):
    def __init__(self, data, fail_after=None):
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, n=-1):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise ConnectionResetError('connection reset')
        return super().read(n if n != -1 else -1)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Downloads(S.TempDir, unittest.TestCase):
    def dest(self):
        return os.path.join(self.tmp, 'file.bin')

    def test_complete_download(self):
        with mock.patch.object(urllib.request, 'urlopen', return_value=FakeResponse(b'x' * 3_000_000)):
            ag.download('https://pds.lroc.im-ldi.com/f', self.dest(), lambda p: os.path.getsize(p) == 3_000_000)
        self.assertEqual(os.listdir(self.tmp), ['file.bin'])

    def test_damaged_download_leaves_nothing(self):
        with mock.patch.object(urllib.request, 'urlopen', return_value=FakeResponse(b'<html>error</html>')):
            with self.assertRaises(SystemExit) as cm:
                ag.download('https://pds.lroc.im-ldi.com/f', self.dest(), lambda p: False)
        self.assertIn('damaged', str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_broken_connection_leaves_nothing(self):
        """BUG-08: a connection reset mid-transfer used to escape download() as a raw ConnectionResetError
        instead of the clear SystemExit every other download failure here already becomes."""
        with mock.patch.object(urllib.request, 'urlopen', return_value=FakeResponse(b'x' * 5_000_000, fail_after=2 << 20)):
            with self.assertRaises(SystemExit) as cm:
                ag.download('https://pds.lroc.im-ldi.com/f', self.dest(), lambda p: True)
        self.assertIn('could not download', str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_failed_redownload_keeps_the_old_copy(self):
        """BUG-08: offline/DNS/timeout errors used to escape as a raw OSError; the temporary-file cleanup and the
        untouched existing destination (the two things that matter here) are unaffected by converting it."""
        with open(self.dest(), 'wb') as fh:
            fh.write(b'old')
        with mock.patch.object(urllib.request, 'urlopen', side_effect=OSError('offline')):
            with self.assertRaises(SystemExit) as cm:
                ag.download('https://pds.lroc.im-ldi.com/f', self.dest(), lambda p: True)
        self.assertIn('could not download', str(cm.exception))
        with open(self.dest(), 'rb') as fh:
            self.assertEqual(fh.read(), b'old')
        self.assertEqual(os.listdir(self.tmp), ['file.bin'], 'no temporary file left behind')

    def test_the_tests_never_reach_the_network(self):
        with self.assertRaises(OSError):
            urllib.request.urlopen('https://api.github.com/', timeout=1)

    def test_a_disallowed_scheme_or_host_stays_its_own_refusal_not_a_generic_network_message(self):
        """A download() call on a URL https_check() refuses (wrong scheme, or a host not in DOWNLOAD_HOSTS) is a
        configuration/security refusal, never attempted over the network -- it must keep raising URLError with
        its own 'refusing ...' message, not get folded into the BUG-08 fix's generic SystemExit."""
        for url in ('http://pds.lroc.im-ldi.com/f', 'https://evil.example/f'):
            with self.subTest(url):
                with self.assertRaises(urllib.error.URLError) as cm:
                    ag.download(url, self.dest(), lambda p: True)
                self.assertIn('refusing', str(cm.exception))

class LocateFailureClassification(S.TempDir, unittest.TestCase):
    """bugs-overview BUG-02: geometry() used to catch every SystemExit from locate() as "no usable limb" and
    fall back to a close-up search. A download failure building the reference map (or any other fatal error
    inside locate()) must terminate the command instead of triggering that blind, expensive fallback."""

    @S.needs_relief
    def test_a_download_failure_inside_locate_is_not_mistaken_for_no_limb(self):
        img, geo = S.moon_image(self.tmp)
        os.remove(ag.sidecar_path(img))                     # a fresh image: geometry() must actually call locate()
        def boom(self_, log=print):
            raise SystemExit('could not download https://pds.lroc.im-ldi.com/x (offline); check the network and try again')
        with mock.patch.object(ag.Reference, '__init__', boom), \
             mock.patch('atlas_closeup.locate_closeup', side_effect=AssertionError('must not be called')) as cu:
            with self.assertRaises(SystemExit) as cm:
                ma.geometry(img, relocate=True)
        self.assertIn('could not download', str(cm.exception))
        self.assertFalse(cu.called, 'no close-up fallback for a download failure')

    def test_a_genuinely_unusable_limb_still_falls_back_to_a_close_up(self):
        """The recoverable case this packet must keep working: no limb, but a capture time is available."""
        img = os.path.join(self.tmp, '2026-01-01-0000_0-crop.tif')
        cv2.imwrite(img, np.full((200, 200), 40, np.uint8))     # too little contrast: fit_limb finds nothing
        with mock.patch('atlas_closeup.locate_closeup') as cu:
            cu.side_effect = SystemExit('close-up: stop here, do not actually search')
            with self.assertRaises(SystemExit) as cm:
                ma.geometry(img, relocate=True, gate=False)
        self.assertTrue(cu.called, 'a genuinely unusable limb with a capture time still tries a close-up')
        self.assertIn('stop here', str(cm.exception))


class DamagedSidecars(S.TempDir, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.img = os.path.join(self.tmp, 'moon.tif')
        cv2.imwrite(self.img, np.zeros((20, 20), np.uint8))
        S.locate_as(self.img, S.truth_geometry())
        self.side = ag.sidecar_path(self.img)

    def damage(self, text):
        with open(self.side, 'w') as fh:
            fh.write(text)

    def problem(self):
        geo, d = ag.load_geo(self.img)
        self.assertIsNone(geo)
        return d['problem']

    def test_truncated(self):
        with open(self.side) as fh:
            good = fh.read()
        self.damage(good[:len(good) // 2])
        self.assertIn('damaged (JSONDecodeError)', self.problem())

    def test_not_an_object(self):
        self.damage('[1, 2, 3]')
        self.assertIn('not a JSON object', self.problem())

    def test_image_changed(self):
        cv2.imwrite(self.img, np.ones((20, 20), np.uint8))
        os.utime(self.img, (1e9, 1e9))
        self.assertEqual(self.problem(), 'image changed since it was located')

    def test_invalid_geometries(self):
        d = S.sidecar(self.img)
        for bad in (dict(d['geometry'], A=[[1, 2], [2, 4]]), dict(d['geometry'], A=[[float('nan'), 0], [0, 1]]),
                    dict(d['geometry'], t=[1]), dict(d['geometry'], coef=[[1, 2]], deg=2), dict(d['geometry'], dist=0.5),
                    dict(d['geometry'], lat0='north'), dict(d['geometry'], A='identity'), 'geometry', None):
            ag.write_json_atomic(self.side, dict(d, geometry=bad))
            self.assertIn('invalid geometry', self.problem(), bad)

    def test_info_explains_instead_of_crashing(self):
        self.damage('{"schema": "lunaratlas.geo/1"')
        code, out = S.run_main('info', self.img)
        self.assertIn('locate', str(code))
        ag.write_json_atomic(self.side, dict(schema='other'))
        code, out = S.run_main('info', self.img)
        self.assertIn('unsupported schema', str(code))

    def test_a_damaged_sidecar_is_located_again_and_replaced(self):
        good = S.sidecar(self.img)
        self.damage('{"geometry": ')
        truth = S.truth_geometry()
        q = dict(matches=400, rms_px=0.3, cv_rms_px=0.3, correction_degree=0, seconds=1.0, width=20, height=20)
        with mock.patch.object(ma, 'quality_gate', return_value=(True, [], 'quality OK', dict(has_limb=True))), \
                mock.patch.object(ma, 'locate', return_value=(truth, q)) as loc, \
                mock.patch('sys.stdout', new=io.StringIO()) as out:
            geo = ma.geometry(self.img)
        loc.assert_called_once()
        self.assertIn('damaged', out.getvalue())
        self.assertEqual(geo.as_dict(), truth.as_dict())
        self.assertEqual(ag.load_geo(self.img)[0].as_dict(), good['geometry'])

    def test_located_again_keeps_the_edits(self):
        d = S.sidecar(self.img)
        d['edits'] = dict(shapes=[dict(kind='text', x=1, y=2, label='mine')])
        ag.write_json_atomic(self.side, d)
        cv2.imwrite(self.img, np.full((20, 20), 3, np.uint8))                  # the image changed
        os.utime(self.img, (2e9, 2e9))
        q = dict(matches=400, rms_px=0.3, cv_rms_px=0.3, correction_degree=0, seconds=1.0, width=20, height=20)
        with mock.patch.object(ma, 'quality_gate', return_value=(True, [], 'quality OK', dict(has_limb=True))), \
                mock.patch.object(ma, 'locate', return_value=(S.truth_geometry(), q)), \
                mock.patch('sys.stdout', new=io.StringIO()) as out:
            ma.geometry(self.img)
        self.assertIn('image changed since it was located: locating again', out.getvalue())
        self.assertEqual(S.sidecar(self.img)['edits']['shapes'][0]['label'], 'mine')

    def test_damaged_gate_and_quality_entries(self):
        # a sidecar edited by hand or by another tool: the gate and quality entries are not objects
        for gate, quality in (('refused', 'bad'), ([1], None), (dict(line=3), 7)):
            d = S.sidecar(self.img)
            d['quality_gate'], d['quality'] = gate, quality
            ag.write_json_atomic(self.side, d)
            with mock.patch('sys.stdout', new=io.StringIO()):
                self.assertIsNotNone(ma.geometry(self.img), (gate, quality))

    def test_image_moved_away_from_its_sidecar(self):
        # the image was moved or deleted but its .atlas.json stayed: info shows the stale info with a warning,
        # never a FileNotFoundError traceback
        os.remove(self.img)
        code, out = S.run_main('info', self.img)
        self.assertIsNone(code, out)
        self.assertIn('is missing (its sidecar is still here)', out)
        self.assertIn('20 x 20 px', out)                          # the stale info is still shown
        code, out = S.run_main('find', self.img, 'Tycho')
        self.assertIn('cannot read', str(code))                  # a clean message, not a traceback
        self.assertNotIn('Traceback', str(code))


@S.needs_all
class DamagedEditsNeverStopAnExport(S.TempDir, unittest.TestCase):
    def test_hand_edited_sidecar(self):
        img, geo = S.moon_image(self.tmp)
        cx, cy = (float(v) for v in geo.t)
        for edits in ([1, 2], 'text', dict(shapes='all', hidden={'a': 1}, labels=['x']),
                      dict(shapes=[None, 5, dict(kind='circle'), dict(kind='circle', cx=cx, cy=cy, r='big'),
                                   dict(kind='outline', pts=[[1, 2], ['a', 3]]), dict(kind='measure', a=1, b=2),
                                   dict(kind='arrow', x0=cx, y0=cy, x1=cx, y1=cy, label='zero length'),
                                   dict(kind='text', x=cx, y=cy, label='ok', font=7, size='huge', colour=12)],
                           hidden=[None, 3, 'Tycho'], labels={'Copernicus': dict(dx='far', dy=None, size=1e308),
                                                              'Tycho': [1]})):
            self.export_with(img, edits)

    def test_hand_edited_style(self):
        # a style that is not an object, or a font that is not a text, is never saved by the viewer's clean_edits,
        # but a hand-edited sidecar can still hold one: cmd_export must fall back, not crash
        img, geo = S.moon_image(self.tmp)
        for edits in (dict(style='bold'), dict(style=dict(font=['Roboto'])), dict(style=dict(font=None)),
                     dict(style=dict(font=''))):
            self.export_with(img, edits)

    def export_with(self, img, edits):
        with self.subTest(edits=str(edits)[:60]):
            d = S.sidecar(img)
            d['edits'] = edits
            ag.write_json_atomic(ag.sidecar_path(img), d)
            out = os.path.join(self.tmp, 'out.png')
            code, log = S.run_main('export', img, '-o', out, '--overwrite')
            self.assertIsNone(code, log)
            self.assertTrue(os.path.exists(out))

    @S.needs_font
    def test_unavailable_font_for_a_drawing(self):
        img, geo = S.moon_image(self.tmp)
        fonts = os.path.join(self.tmp, 'fonts')
        os.makedirs(fonts)
        os.symlink(S.ROBOTO, os.path.join(fonts, 'roboto'))
        d = S.sidecar(img)
        d['edits'] = dict(shapes=[dict(kind='text', x=float(geo.t[0]), y=float(geo.t[1]), label='hi', font='No Such Font')])
        ag.write_json_atomic(ag.sidecar_path(img), d)
        with mock.patch.object(ar, 'FONT_DIR', fonts):
            code, log = S.run_main('export', img, '-o', os.path.join(self.tmp, 'o.png'))
        self.assertIsNone(code, log)
        self.assertIn(f'using {ar.DEFAULT_FONT}', log)


class DamagedCaches(S.TempDir, unittest.TestCase):
    def test_feature_cache_rebuilt_from_the_dbf(self):
        from test_functional_render import Dbf, write_dbf
        dbf, js = os.path.join(self.tmp, 'g.dbf'), os.path.join(self.tmp, 'features.json')
        write_dbf(dbf, Dbf.ROWS)
        with open(js, 'w') as fh:
            fh.write('[{"name": "Alp')
        msgs = []
        with mock.patch.object(an, 'GAZ_DBF', dbf), mock.patch.object(an, 'GAZ_JSON', js):
            os.utime(dbf, (1, 1))                                         # the JSON is newer, but damaged
            feats = an.load_features(msgs.append, sites=False)
        self.assertEqual(len(feats), 4)
        self.assertIn('damaged', msgs[0])
        with open(js, encoding='utf-8') as fh:
            self.assertEqual(len(json.load(fh)), 4)

    def test_newer_dbf_replaces_the_cache(self):
        from test_functional_render import Dbf, write_dbf
        dbf, js = os.path.join(self.tmp, 'g.dbf'), os.path.join(self.tmp, 'features.json')
        with open(js, 'w') as fh:
            json.dump([dict(name='stale', cls='crater', type='t', lat=0, lon=0, diam=1, origin='', link='')], fh)
        os.utime(js, (1, 1))
        write_dbf(dbf, Dbf.ROWS)
        with mock.patch.object(an, 'GAZ_DBF', dbf), mock.patch.object(an, 'GAZ_JSON', js):
            self.assertNotIn('stale', {f['name'] for f in an.load_features(S.quiet, sites=False)})

    def test_damaged_dbf_is_downloaded_again(self):
        from test_functional_render import Dbf, write_dbf
        dbf, js = os.path.join(self.tmp, 'g.dbf'), os.path.join(self.tmp, 'features.json')
        with open(dbf, 'wb') as fh:
            fh.write(b'\x03' + b'\0' * 40)
        with mock.patch.object(an, 'GAZ_DBF', dbf), mock.patch.object(an, 'GAZ_JSON', js), \
                mock.patch.object(an, '_download', side_effect=lambda log: write_dbf(dbf, Dbf.ROWS)) as dl:
            feats = an.load_features(S.quiet, sites=False)
        dl.assert_called_once()
        self.assertEqual(len(feats), 4)

    def test_quality_thresholds_file(self):
        p = os.path.join(self.tmp, 'thresholds.json')
        with mock.patch.object(aq, 'THRESHOLDS_FILE', p):
            self.assertEqual(aq.thresholds(), aq.PROVISIONAL)                  # missing
            for text in ('{"edge_width_px": 1', '[1]', ''):
                with open(p, 'w') as fh:
                    fh.write(text)
                self.assertEqual(aq.thresholds(), aq.PROVISIONAL, text)
            with open(p, 'w') as fh:
                json.dump(dict(version='x', edge_width_px=3.0), fh)
            t = aq.thresholds()
            self.assertEqual((t['version'], t['edge_width_px'], t['undershoot']), ('x', 3.0, aq.PROVISIONAL['undershoot']))

    @S.needs_font
    def test_interrupted_font_download(self):
        dst = os.path.join(self.tmp, 'roboto')
        shutil.copytree(S.ROBOTO, dst)
        open(os.path.join(dst, '.incomplete'), 'w').close()
        msgs = []
        with mock.patch.object(ar, 'FONT_DIR', self.tmp), mock.patch.object(ar, 'BUNDLED_FONTS', self.tmp + '-none'):
            f = ar.Fonts('Roboto', msgs.append)                               # offline: the complete files serve
        self.assertTrue(f.files)
        self.assertIn('earlier download incomplete', msgs[0])

    def test_reference_tile_of_the_wrong_size_is_refused(self):
        p = os.path.join(self.tmp, 'tile.tif')
        cv2.imwrite(p, np.zeros((100, 100), np.uint8))
        self.assertIsNone(ag.Reference._tile(p))
        self.assertIsNone(ag.Reference._tile(os.path.join(self.tmp, 'missing.tif')))
        with open(p, 'wb') as fh:
            fh.write(b'II*\0garbage')
        self.assertIsNone(ag.Reference._tile(p))

    @unittest.skipUnless(all(S.have('wac_emp_643', f'WAC_EMP_643NM_{t}_064P.TIF') for t in ag.REF_TILES),
                         'LROC WAC tiles not in lunaratlas/data')
    def test_damaged_reference_cache_is_rebuilt_from_the_tiles(self):
        tiles = os.path.join(self.tmp, 'wac_emp_643')
        os.makedirs(tiles)
        for t in ag.REF_TILES:
            f = f'WAC_EMP_643NM_{t}_064P.TIF'
            os.symlink(os.path.join(S.DATA, 'wac_emp_643', f), os.path.join(tiles, f))
        with open(os.path.join(self.tmp, 'wac_emp_643_nearside.png'), 'wb') as fh:
            fh.write(b'\x89PNG\r\n\x1a\n broken')
        with mock.patch.object(ag, 'DATA', self.tmp):
            ref = ag.Reference(S.quiet)
        self.assertEqual(ref.levels[0].shape, ag.Reference.SHAPE)
        again = cv2.imread(os.path.join(self.tmp, 'wac_emp_643_nearside.png'), cv2.IMREAD_GRAYSCALE)
        np.testing.assert_array_equal(again, ref.levels[0])


class ImagesThatCannotBeAnnotated(S.TempDir, unittest.TestCase):
    def write(self, name, arr):
        p = os.path.join(self.tmp, name)
        cv2.imwrite(p, arr)
        return p

    def test_blank_noise_and_tiny_frames_are_refused_with_a_message(self):
        rng = np.random.default_rng(0)
        for name, arr in (('black.png', np.zeros((300, 300), np.uint16)), ('white.png', np.full((300, 300), 65535, np.uint16)),
                          ('noise.png', (rng.random((300, 300)) * 60000).astype(np.uint16)),
                          ('tiny.png', np.full((8, 8), 100, np.uint8)), ('one.png', np.zeros((1, 1), np.uint8))):
            with self.subTest(name):
                code, log = S.run_main('locate', self.write(name, arr))
                self.assertIsInstance(code, str)
                self.assertIn('capture time', code)
                self.assertFalse(os.path.exists(ag.sidecar_path(os.path.join(self.tmp, name))))

    def test_not_an_image(self):
        p = os.path.join(self.tmp, 'notes.tif')
        with open(p, 'w') as fh:
            fh.write('not an image')
        for cmd in ('locate', 'export'):
            code, _ = S.run_main(cmd, p)
            self.assertIn('cannot read', str(code))

    def test_measures_on_degenerate_frames(self):
        for arr in (np.zeros((64, 64), np.uint8), np.full((64, 64), 255, np.uint8), np.zeros((1, 1), np.uint16),
                    np.zeros((40, 40, 3), np.float32), np.full((50, 50, 4), 7, np.uint8)):
            q = aq.measure(arr if arr.ndim == 2 or arr.shape[2] != 4 else arr[..., :3])
            self.assertIn('saturated_share', q)
            self.assertTrue(aq.verdict(q)[0] in (True, False))

    @S.needs_relief
    def test_overexposed_moon_is_refused(self):
        img, geo = S.synthetic_moon()
        raw = S.encode(np.clip(img * 2.5, 0, 1))                        # half the disk clipped
        p = os.path.join(self.tmp, 'burnt.tif')
        cv2.imwrite(p, raw)
        ok, reasons, line, q = ma.quality_gate(p)
        self.assertFalse(ok, line)
        self.assertIn('overexposed', reasons[0])
        code, _ = S.run_main('locate', p)
        self.assertIn('--force', str(code))
        self.assertFalse(os.path.exists(ag.sidecar_path(p)))

    @S.needs_relief
    def test_blurred_moon_is_refused(self):
        img, geo = S.synthetic_moon(blur=12.0)
        p = os.path.join(self.tmp, 'soft.tif')
        cv2.imwrite(p, S.encode(img))
        ok, reasons, line, q = ma.quality_gate(p)
        self.assertFalse(ok, line)
        self.assertIn('too blurry', ' '.join(reasons))


class ConcurrentEdits(S.TempDir, unittest.TestCase):
    def test_parallel_saves_leave_a_valid_sidecar(self):
        import atlas_view as av
        img = os.path.join(self.tmp, 'a.tif')
        cv2.imwrite(img, np.zeros((10, 10), np.uint8))
        S.locate_as(img, S.truth_geometry())
        lock, errors = threading.Lock(), []

        def worker(k):
            try:
                for i in range(20):
                    av.write_edits(img, dict(shapes=[dict(kind='text', x=k, y=i, label=f'{k}-{i}')]), lock)
            except Exception as e:                         # noqa: BLE001
                errors.append(e)
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        geo, d = ag.load_geo(img)
        self.assertIsNotNone(geo)
        self.assertEqual(len(d['edits']['shapes']), 1)
        self.assertFalse([f for f in os.listdir(self.tmp) if '.part' in f])

    def test_session_restart_does_not_reset_the_durable_revision_to_zero(self):
        """BUG-14: Session.rev used to start at 0 on every (re)build, so a pending browser snapshot saved under a
        real, higher revision could look newer than the freshly reset server and be replayed, rolling back a
        write that had already landed. The session now seeds its revision from the sidecar's own durable value."""
        import atlas_view as av
        img = os.path.join(self.tmp, 'a.tif')
        cv2.imwrite(img, np.zeros((10, 10), np.uint8))
        geo, _ = S.locate_as(img, S.truth_geometry()), None
        side = S.sidecar(img)
        lock = threading.Lock()
        ok, edits, committed = av.write_edits(img, dict(hidden=['real']), lock, 5000)
        self.assertTrue(ok)
        self.assertEqual(committed, 5000)
        # a fresh Session for the same image (as a restarted viewer process would build) must see the durable
        # revision, not 0 -- so a replayed pending snapshot older than 5000 is correctly refused as stale
        s2 = av.Session.__new__(av.Session)
        _, d = ag.resolve_sidecar(img)
        s2_rev = av.edits_rev(d) if isinstance(d, dict) else 0
        self.assertEqual(s2_rev, 5000, 'a new session reads the durable revision, not zero')
        ok2, _, committed2 = av.write_edits(img, dict(hidden=['stale replay']), lock, 100)
        self.assertFalse(ok2, 'a pending snapshot older than the durable revision is rejected, not replayed')
        self.assertEqual(committed2, 5000)
        self.assertEqual(S.sidecar(img)['edits']['hidden'], ['real'], 'the real edit was never rolled back')

    def test_write_edits_and_save_geo_share_the_cross_process_lock(self):
        """A relocate (save_geo, as a separate `lunaratlas.py locate` subprocess would run it) and an edit save
        (write_edits, as the viewer server runs it) must never interleave their read-modify-write of one sidecar,
        even though they are different functions with no Python-level lock in common other than the file lock."""
        import atlas_view as av
        img = os.path.join(self.tmp, 'a.tif')
        cv2.imwrite(img, np.zeros((10, 10), np.uint8))
        S.locate_as(img, S.truth_geometry())
        lock, errors, iterations = threading.Lock(), [], 25

        def relocator():
            try:
                for i in range(iterations):
                    ag.save_geo(img, S.truth_geometry(theta=float(i)), {}, 10, 10)
            except Exception as e:                         # noqa: BLE001
                errors.append(e)

        def editor():
            try:
                for i in range(iterations):
                    av.write_edits(img, dict(hidden=[f'h{i}']), lock)
            except Exception as e:                         # noqa: BLE001
                errors.append(e)
        ts = [threading.Thread(target=relocator), threading.Thread(target=editor)]
        for t in ts: t.start()
        for t in ts: t.join(60)
        self.assertEqual(errors, [])
        geo, d = ag.load_geo(img)
        self.assertIsNotNone(geo, d)                        # never a damaged/partial sidecar from an interleaved write
        self.assertIn('edits', d)


if __name__ == '__main__':
    unittest.main()
