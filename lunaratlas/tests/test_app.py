"""The browser launcher (`lunaratlas.py app`): upload, capture time in the copy's name, locate, open, refusals."""
import http.client
import json
import os
import shutil
import subprocess
import threading
import time
import unittest

import _support as S
from atlas_geo import sidecar_path
from atlas_app import App, already_running, copy_name, taken, thumbnail
from atlas_view import start_server


class CopyName(unittest.TestCase):
    def test_the_capture_time_goes_in_front_only_when_the_name_has_none(self):
        self.assertEqual(copy_name('moon.TIF', '2026-09-20T21:30'), '2026-09-20-2130_0-moon.tif')
        self.assertEqual(copy_name('2025-01-02-0304_5-x.png', '2026-09-20T21:30'), '2025-01-02-0304_5-x.png')
        self.assertEqual(copy_name('moon.jpg', ''), 'moon.jpg')

    def test_no_folders_and_no_other_file_types(self):
        self.assertEqual(copy_name('../../etc/moon.png', ''), 'moon.png')
        self.assertEqual(copy_name('C:\\Users\\x\\Moon shot.jpeg', ''), 'Moon shot.jpeg')
        self.assertEqual(copy_name('a<b>|c.tif', ''), 'a_b_c.tif')
        for bad in ('run.sh', 'moon', 'moon.tif.exe'):
            with self.subTest(bad), self.assertRaises(ValueError):
                copy_name(bad, '')


class RecentPhotos(S.TempDir):
    def test_capture_time_from_the_name_else_exif_else_none(self):
        from PIL import Image
        self.assertEqual(taken('/x/2026-09-27-2040_2-Moon.tif'), '2026-09-27 20:40 UTC')
        p = os.path.join(self.tmp, 'camera.jpg')
        im = Image.new('L', (40, 30), 128)
        ex = im.getexif()
        ex[306] = '2025:03:04 21:15:09'
        im.save(p, exif=ex)
        self.assertEqual(taken(p), '2025-03-04 21:15')
        Image.new('L', (40, 30)).save(os.path.join(self.tmp, 'plain.png'))
        self.assertIsNone(taken(os.path.join(self.tmp, 'plain.png')))
        with open(os.path.join(self.tmp, 'broken.jpg'), 'wb') as fh:
            fh.write(b'not a jpeg')
        self.assertIsNone(taken(os.path.join(self.tmp, 'broken.jpg')))

    def test_thumbnail_of_a_dark_16_bit_image(self):
        import cv2
        import numpy as np
        p = os.path.join(self.tmp, 'dark.tif')
        img = np.zeros((900, 1200), np.uint16)
        cv2.circle(img, (600, 450), 400, 900, -1)                    # a faint 16-bit disk
        cv2.imwrite(p, img)
        t = cv2.imdecode(np.frombuffer(thumbnail(p), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertLessEqual(max(t.shape), 160)
        self.assertGreater(int(t.max()), 200, 'stretched: a dark photo still shows')
        with open(os.path.join(self.tmp, 'junk.png'), 'wb') as fh:
            fh.write(b'junk')
        self.assertIsNone(thumbnail(os.path.join(self.tmp, 'junk.png')))

    def test_recent_lists_every_photo_with_its_status(self):
        import json as j
        folder = os.path.join(self.tmp, 'work')
        os.makedirs(folder)
        from PIL import Image
        for n in ('a.png', 'b.png'):
            Image.new('L', (20, 20)).save(os.path.join(folder, n))
        with open(os.path.join(folder, 'notes.txt'), 'w') as fh:
            fh.write('x')
        with open(sidecar_path(os.path.join(folder, 'b.png')), 'w') as fh:
            j.dump({'geometry': 'damaged'}, fh)                     # a sidecar that does not position it
        rows = {r['name']: r for r in App(folder, S.quiet).recent()}
        self.assertEqual(set(rows), {'a.png', 'b.png'})
        self.assertEqual({r['status'] for r in rows.values()}, {'unsolved'})
        self.assertFalse(rows['a.png']['located'])

    def test_cancel_with_nothing_running(self):
        self.assertFalse(App(self.tmp, S.quiet).cancel())


def big_endian_tiff(original, offset):
    """A minimal 'MM' TIFF: IFD0 points to an Exif IFD with DateTimeOriginal and OffsetTimeOriginal (no pixels)."""
    import struct
    a, b = original.encode() + b'\0', offset.encode() + b'\0'
    exif = 8 + 2 + 12 + 4                                            # after IFD0 (one entry)
    data = exif + 2 + 2 * 12 + 4
    return (b'MM\0*' + struct.pack('>I', 8)
            + struct.pack('>HHHII', 1, 0x8769, 4, 1, exif) + struct.pack('>I', 0)
            + struct.pack('>H', 2) + struct.pack('>HHII', 0x9003, 2, len(a), data)
            + struct.pack('>HHII', 0x9011, 2, len(b), data + len(a)) + struct.pack('>I', 0) + a + b)


FRIENDLY_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'friendly.js')
EXIF_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'exif.js')
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'node not installed')
class CameraTimeInThePage(S.TempDir):
    """exif.js fills the time box before the upload: the camera time, converted when the camera recorded its UTC offset."""

    def read(self, *names, tz='Europe/Brussels'):
        script = ("globalThis.window = {}; require(process.argv[1]); const fs = require('fs');\n"
                  "(async () => { const out = [];\n"
                  "  for (const p of process.argv.slice(2)) out.push(await window.LA_EXIF.captureTime(new Blob([fs.readFileSync(p)])));\n"
                  "  console.log(JSON.stringify(out)); })();\n")
        r = subprocess.run([NODE, '-e', script, os.path.abspath(EXIF_JS)] + [os.path.join(self.tmp, n) for n in names],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ, TZ=tz))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def save(self, name, original=None, offset=None, changed=None):
        from PIL import Image
        im = Image.new('L', (40, 30), 128)
        ex = im.getexif()
        if changed:
            ex[306] = changed
        if original or offset:
            sub = ex.get_ifd(0x8769)
            if original:
                sub[0x9003] = original
            if offset:
                sub[0x9011] = offset
        im.save(os.path.join(self.tmp, name), exif=ex)

    def test_camera_time_with_and_without_its_zone(self):
        self.save('zone.jpg', original='2025:03:04 21:15:09', offset='+09:00', changed='2025:05:01 10:00:00')
        self.save('clock.jpg', original='2025:07:14 23:50:00')
        self.save('changed.tif', changed='2024:12:31 22:05:00')
        with open(os.path.join(self.tmp, 'west.tif'), 'wb') as fh:       # Pillow writes no Exif IFD into a TIFF
            fh.write(big_endian_tiff('2025:07:15 01:30:00', '-04:00'))
        zone, clock, changed, west = self.read('zone.jpg', 'clock.jpg', 'changed.tif', 'west.tif')
        self.assertEqual(zone, {'when': '2025-03-04T13:15', 'zone': '+09:00'})      # 12:15 UTC, winter time in Brussels
        self.assertEqual(clock, {'when': '2025-07-14T23:50', 'zone': None})         # no zone: the clock as it reads
        self.assertEqual(changed, {'when': '2024-12-31T22:05', 'zone': None})       # no DateTimeOriginal: DateTime
        self.assertEqual(west, {'when': '2025-07-15T07:30', 'zone': '-04:00'})      # 05:30 UTC, summer time

    def test_no_time_no_fill(self):
        from PIL import Image
        Image.new('L', (40, 30)).save(os.path.join(self.tmp, 'plain.png'))
        Image.new('L', (40, 30)).save(os.path.join(self.tmp, 'plain.jpg'))
        self.save('zeros.jpg', original='0000:00:00 00:00:00')
        with open(os.path.join(self.tmp, 'broken.jpg'), 'wb') as fh:
            fh.write(b'\xff\xd8\xff\xe1\x00\x20Exif\x00\x00II*\x00\xff\xff\xff\x7f')
        with open(os.path.join(self.tmp, 'empty.tif'), 'wb') as fh:
            fh.write(b'')
        self.assertEqual(self.read('plain.png', 'plain.jpg', 'zeros.jpg', 'broken.jpg', 'empty.tif'), [None] * 5)



@unittest.skipUnless(NODE, 'node not installed')
class ProgressSentences(unittest.TestCase):
    """friendly.js turns log lines into the sentence under the progress bar."""

    def test_the_tilt_comes_from_the_time_only_for_a_close_up(self):
        lines = ['capture 2026-09-27 20:41 UTC: libration -4.43° -4.07°, colongitude 81.2°, distance 369000 km',
                 '  disk 2048 px: 252 matches, 0.81 px rms (full res), libration -4.30° -4.08°']
        script = ("globalThis.window = {}; require(process.argv[1]);\n"
                  "console.log(JSON.stringify(process.argv.slice(2).map(window.LA_FRIENDLY.line)));\n")
        r = subprocess.run([NODE, '-e', script, os.path.abspath(FRIENDLY_JS)] + lines, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        closeup, fit = json.loads(r.stdout)
        self.assertIn('capture time', closeup)
        self.assertNotIn('capture time', fit)                  # the limb fit finds the tilt itself
        self.assertIn('Refining', fit)

class SamePhotoAgain(S.TempDir):
    """An upload with the name and size of a copy already in the work folder reuses that copy and its sidecar."""

    def setUp(self):
        super().setUp()
        self.app = App(os.path.join(self.tmp, 'work'), S.quiet)
        self.srv = start_server(S.free_port(), S.quiet, app=self.app)
        self.app.server = self.srv
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def upload(self, data, name='moon.tif'):
        c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
        c.request('POST', f'/app/upload?name={name}&time=', data, {'Host': 'localhost', 'X-LA-Token': self.srv.token})
        r = json.loads(c.getresponse().read())
        c.close()
        with open(r['path'], 'rb') as fh:
            return r, fh.read()

    @staticmethod
    def uncompressed(seed):
        import cv2
        import numpy as np
        img = (np.random.default_rng(seed).random((300, 400)) * 65535).astype(np.uint16)
        return cv2.imencode('.tif', img, [cv2.IMWRITE_TIFF_COMPRESSION, 1])[1].tobytes()

    def test_the_same_file_again_is_not_copied_twice(self):
        a = self.uncompressed(1)
        first, _ = self.upload(a)
        again, kept = self.upload(a)
        self.assertEqual(again['path'], first['path'])
        self.assertEqual(kept, a)

    @unittest.expectedFailure
    def test_another_photo_with_the_same_name_and_size_is_kept(self):
        # known issue: the size alone decides "the same file", and uncompressed captures of one camera all have the
        # same size; a second moon.tif (no time given) opens the first photo and its positioning instead
        # (atlas_app.App.upload: compare the bytes, or a hash, before reusing the copy)
        a, b = self.uncompressed(1), self.uncompressed(2)
        self.assertEqual(len(a), len(b))
        self.upload(a)
        second, kept = self.upload(b)
        self.assertEqual(kept, b, f'{os.path.basename(second["path"])} holds the earlier photo')


@unittest.skipUnless(S.HAVE_REFERENCE, 'needs the reference data in lunaratlas/data')
class Launcher(S.TempDir):
    def setUp(self):
        super().setUp()
        self.src, _ = S.moon_image(self.tmp, name='source.tif')
        os.remove(sidecar_path(self.src))                     # the launcher locates it for real
        self.folder = os.path.join(self.tmp, 'work')
        self.app = App(self.folder, S.quiet)
        self.srv = start_server(S.free_port(), S.quiet, app=self.app)
        self.app.server = self.srv
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, body=b'', headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=60)
        c.request(method, path, body, dict({'Host': 'localhost', 'X-LA-Token': self.srv.token}, **(headers or {})))
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def upload(self, name, when=''):
        with open(self.src, 'rb') as fh:
            return self.call('POST', f'/app/upload?name={name}&time={when}', fh.read())

    def wait(self, limit=240):
        t0 = time.time()
        while time.time() - t0 < limit:
            st = self.call('GET', '/app/status')[1]
            if st['phase'] in ('ready', 'failed'):
                return st
            time.sleep(0.3)
        self.fail('the launcher did not finish')

    def test_from_upload_to_the_viewer(self):
        self.assertEqual(self.call('GET', '/')[0], 200)                         # the launcher page, no image yet
        self.assertTrue(already_running(self.srv.server_port, self.srv.token))
        self.assertFalse(already_running(self.srv.server_port, 'not-the-token'), 'a different token is a different app')
        code, r = self.upload('moon.tif', '2026-09-20T21:30')
        self.assertEqual(code, 200, r)
        self.assertEqual(os.path.basename(r['path']), '2026-09-20-2130_0-moon.tif')
        self.assertFalse(r['located'])
        self.assertEqual(self.call('POST', '/app/locate', json.dumps(dict(path=r['path'])).encode())[0], 200)
        st = self.wait()
        self.assertEqual(st['phase'], 'ready', st)
        self.assertTrue(any('capture time' in l for l in st['lines']), 'the time from the page lit the relief')
        self.assertEqual(self.call('GET', '/data.json')[0], 200)                  # the viewer now serves the image
        self.assertIn(b'Other image', self.call('GET', '/')[1])
        self.assertTrue(self.call('GET', '/data.json')[1]['launcher'], 'the viewer page has the way back')
        again = self.upload('moon.tif', '2026-09-20T21:30')[1]                   # the same photo: nothing to redo
        self.assertEqual(again['path'], r['path'])
        self.assertTrue(again['located'])
        rows = self.call('GET', '/app/recent')[1]['images']
        self.assertEqual([i['name'] for i in rows], ['2026-09-20-2130_0-moon.tif'])
        self.assertEqual(rows[0]['status'], 'solved')
        self.assertEqual(rows[0]['taken'], '2026-09-20 21:30 UTC')
        code, jpg = self.call('GET', '/app/thumb?path=' + r['path'].replace(' ', '%20'))
        self.assertEqual(code, 200)
        self.assertTrue(jpg.startswith(b'\xff\xd8'), 'a JPEG thumbnail')
        self.assertEqual(self.call('GET', '/app/thumb?path=/etc/passwd')[0], 404)
        for p in ('/theme.css', '/friendly.js', '/exif.js', '/lunaratlas.svg', '/fonts.css'):
            self.assertEqual(self.call('GET', p)[0], 200, p)

    def test_cancel_stops_a_locate(self):
        r = self.upload('moon.tif')[1]
        self.assertEqual(self.call('POST', '/app/locate', json.dumps(dict(path=r['path'])).encode())[0], 200)
        self.assertTrue(self.call('POST', '/app/cancel', b'{}')[1]['ok'])
        t0 = time.time()
        while time.time() - t0 < 30 and self.call('GET', '/app/status')[1]['phase'] == 'locating':
            time.sleep(0.2)
        st = self.call('GET', '/app/status')[1]
        self.assertEqual(st['phase'], 'idle', st)
        self.assertFalse(self.call('POST', '/app/cancel', b'{}')[1]['ok'], 'nothing left to cancel')

    def test_only_images_in_the_work_folder(self):
        self.assertEqual(self.call('POST', '/app/upload?name=x.sh', b'#!/bin/sh')[0], 400)
        for p in (self.src, '/etc/passwd', os.path.join(self.folder, '..', 'source.tif'), 7):
            with self.subTest(p):
                self.assertEqual(self.call('POST', '/app/open', json.dumps(dict(path=p)).encode())[0], 400)
        self.assertEqual(self.call('POST', '/app/quit', b'{}', {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.call('GET', '/app/status', headers={'Host': 'evil.example'})[0], 403)

    def test_a_failed_locate_is_reported_on_the_page(self):
        with open(os.path.join(self.tmp, 'blank.png'), 'wb') as fh:
            import cv2
            import numpy as np
            fh.write(cv2.imencode('.png', np.zeros((300, 400), np.uint8))[1].tobytes())
        self.src = os.path.join(self.tmp, 'blank.png')
        r = self.upload('blank.png')[1]
        self.call('POST', '/app/locate', json.dumps(dict(path=r['path'])).encode())
        st = self.wait()
        self.assertEqual(st['phase'], 'failed')
        self.assertTrue(st['error'])
        self.assertEqual(self.call('GET', '/app/ping')[0], 200, 'the launcher carries on')


if __name__ == '__main__':
    unittest.main()
