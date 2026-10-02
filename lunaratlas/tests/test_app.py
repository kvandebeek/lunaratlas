"""The browser launcher (`lunaratlas.py app`): upload, capture time in the copy's name, locate, open, refusals."""
import errno
import http.client
import json
import os
import shutil
import subprocess
import threading
import time
import unittest
from unittest import mock

import _support as S
import cv2
import numpy as np
from atlas_geo import sidecar_path
from atlas_app import App, already_running, copy_name, taken, thumbnail
import atlas_view as av
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


@S.needs_features
class NightSideForACloseupWithNoCaptureTime(S.TempDir):
    """BUG-06: a close-up with no usable capture time made sun_elevation_light() return None; night_side() then
    built a 0-D NumPy array from it and page_data() iterated it with zip(), raising instead of opening the page."""

    def test_page_data_does_not_crash_and_shows_names_as_lit(self):
        W, H = 1100, 1000                                  # the geometry S.truth_geometry() actually describes
        img = os.path.join(self.tmp, 'crop.tif')            # no SharpCap stamp in the name: no capture time
        cv2.imwrite(img, np.zeros((H, W), np.uint16))
        geo = S.truth_geometry()
        side = dict(quality=dict(closeup=True), width=W, height=H)   # no capture_utc either
        data = av.page_data(img, lambda: np.zeros((H, W), np.uint16), geo, side,
                            levels=[dict(w=W, h=H)], log=lambda *a: None)
        self.assertGreater(len(data['features']), 0)
        self.assertTrue(all(f.get('lit', 1.0) >= 1.0 for f in data['features']),
                        'unknown lighting shows every name as lit, not hidden or dimmed')

    def test_night_side_itself_returns_none_rather_than_a_malformed_array(self):
        W, H = 1100, 1000
        img = os.path.join(self.tmp, 'crop2.tif')
        cv2.imwrite(img, np.zeros((H, W), np.uint16))
        geo = S.truth_geometry()
        feats = S.projected_features(geo)
        side = dict(quality=dict(closeup=True))
        xy = np.zeros((len(feats), 2))
        light = av.night_side(img, lambda: np.zeros((H, W), np.uint16), geo, side, feats, xy, lambda *a: None)
        self.assertIsNone(light)


class RecentPhotos(S.TempDir):
    def test_capture_time_from_the_name_else_exif_else_none(self):
        from PIL import Image
        self.assertEqual(taken('/x/2026-09-27-2040_2-Moon.tif'), '2026-09-27 20:40 UTC')
        self.assertIsNone(taken('/x/2026-02-30-2561_0-moon.tif'), 'an impossible SharpCap-looking stamp is not a date')
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

    def test_cache_cleanup_drops_orphans_and_oldest_entries_but_keeps_active_one(self):
        root = os.path.join(self.tmp, 'cache')
        tiles = os.path.join(root, 'tiles')
        thumbs = os.path.join(root, 'thumbs')
        os.makedirs(tiles); os.makedirs(thumbs)
        alive = os.path.join(self.tmp, 'alive.png')
        cv2.imwrite(alive, np.zeros((10, 10), np.uint8))
        def tile(name, image, payload):
            d = os.path.join(tiles, name); os.makedirs(d)
            with open(os.path.join(d, 'meta.json'), 'w') as fh:
                json.dump(dict(image=image, signature=av.image_signature(image) if os.path.exists(image) else {}), fh)
            with open(os.path.join(d, 'payload'), 'wb') as fh: fh.write(payload)
            return d
        keep = tile('keep', alive, b'k' * 50)
        orphan = tile('orphan', os.path.join(self.tmp, 'gone.png'), b'o' * 50)
        old_thumb = os.path.join(thumbs, 'old.jpg')
        with open(old_thumb, 'wb') as fh: fh.write(b'x' * 50)
        os.utime(old_thumb, (1, 1))
        with mock.patch.object(av, 'CACHE_ROOT', root), mock.patch.object(av, 'CACHE', tiles):
            av.evict_cache(limit=80, keep=(keep,))
        self.assertTrue(os.path.isdir(keep), 'the currently open pyramid is never evicted')
        self.assertFalse(os.path.exists(orphan), 'a deleted source leaves no permanent pyramid')
        self.assertFalse(os.path.exists(old_thumb), 'the oldest cache entry is evicted over the cap')

    def test_cache_size_counts_a_file_as_well_as_a_folder(self):
        """BUG-15: cache_size() only walked, and os.walk() of a plain file yields nothing, so every launcher
        thumbnail counted as zero bytes and the 2 GiB cap was never reached."""
        f = os.path.join(self.tmp, 'thumb.jpg')
        with open(f, 'wb') as fh: fh.write(b'x' * 1024)
        d = os.path.join(self.tmp, 'pyramid'); os.makedirs(os.path.join(d, 'inner'))
        with open(os.path.join(d, 'a'), 'wb') as fh: fh.write(b'y' * 10)
        with open(os.path.join(d, 'inner', 'b'), 'wb') as fh: fh.write(b'z' * 5)
        self.assertEqual(av.cache_size(f), 1024)
        self.assertEqual(av.cache_size(d), 15)
        self.assertEqual(av.cache_size(os.path.join(self.tmp, 'gone')), 0)

    def test_thumbnails_alone_are_evicted_down_to_the_cap(self):
        """A cache holding nothing but thumbnails used to measure zero and grow without limit."""
        root = os.path.join(self.tmp, 'cache2')
        tiles, thumbs = os.path.join(root, 'tiles'), os.path.join(root, 'thumbs')
        os.makedirs(tiles); os.makedirs(thumbs)
        names = []
        for i, age in enumerate((1, 2, 3)):
            t = os.path.join(thumbs, f'{i}.jpg')
            with open(t, 'wb') as fh: fh.write(b'x' * 100)
            os.utime(t, (age, age))
            names.append(t)
        with mock.patch.object(av, 'CACHE_ROOT', root), mock.patch.object(av, 'CACHE', tiles):
            av.evict_cache(limit=150)
        self.assertFalse(os.path.exists(names[0]), 'the oldest thumbnail goes first')
        self.assertFalse(os.path.exists(names[1]))
        self.assertTrue(os.path.exists(names[2]), 'eviction stops as soon as the cache is under the cap')

    def test_mixed_cache_evicts_only_what_the_thumbnails_push_over(self):
        """Tiles alone fit under the cap; tiles plus thumbnails do not. Only the oldest thumbnails go, the
        retained entries account for the remaining bytes, and a second pass removes nothing more."""
        root = os.path.join(self.tmp, 'cache3')
        tiles, thumbs = os.path.join(root, 'tiles'), os.path.join(root, 'thumbs')
        os.makedirs(tiles); os.makedirs(thumbs)
        alive = os.path.join(self.tmp, 'alive2.png')
        cv2.imwrite(alive, np.zeros((10, 10), np.uint8))
        pyramid = os.path.join(tiles, 'live'); os.makedirs(pyramid)
        with open(os.path.join(pyramid, 'meta.json'), 'w') as fh:
            json.dump(dict(image=alive, signature=av.image_signature(alive)), fh)
        with open(os.path.join(pyramid, 'payload'), 'wb') as fh: fh.write(b'p' * 200)
        tile_bytes = av.cache_size(pyramid)
        kept = []
        for i, age in enumerate((10, 20, 30)):
            t = os.path.join(thumbs, f'{i}.jpg')
            with open(t, 'wb') as fh: fh.write(b'x' * 100)
            os.utime(t, (age, age))
            kept.append(t)
        limit = tile_bytes + 100
        with mock.patch.object(av, 'CACHE_ROOT', root), mock.patch.object(av, 'CACHE', tiles):
            av.evict_cache(limit=limit)
            self.assertTrue(os.path.isdir(pyramid), 'a live pyramid under the cap is not touched')
            self.assertEqual([os.path.exists(t) for t in kept], [False, False, True])
            remaining = av.cache_size(pyramid) + sum(av.cache_size(t) for t in kept if os.path.exists(t))
            self.assertEqual(remaining, limit)
            av.evict_cache(limit=limit)
            self.assertTrue(os.path.isdir(pyramid))
            self.assertTrue(os.path.exists(kept[2]), 'already under the cap: a second pass evicts nothing')


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

    def error(self, msg, refused=False):
        script = ("globalThis.window = {}; require(process.argv[1]);\n"
                  "console.log(JSON.stringify(window.LA_FRIENDLY.error(process.argv[2], process.argv[3] === '1')));\n")
        r = subprocess.run([NODE, '-e', script, os.path.abspath(FRIENDLY_JS), msg, '1' if refused else '0'],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_every_kind_of_failure_gets_its_own_title(self):
        """A regression for a duplicated `return` that made every one of these but the first two say
        'The Moon could not be found in this photo', including a full disk and being offline."""
        cases = [
            ('not annotated: too blurry', True, 'quality check'),
            ('close-up needs its capture time: …', False, 'looks like a close-up'),
            ('no optics setup fits this image size', False, 'could not be worked out'),
            ('no Moon found in this photo', False, 'could not be found in this photo'),
            ('cannot reach data.lroc.asu.edu: timed out', False, 'could not be downloaded'),
            ('could not save the image: No space left on device', False, 'did not work'),
            ('LunarAtlas stopped running.', False, 'did not work'),
            ('the copy failed: is LunarAtlas still running?', False, 'did not work'),
        ]
        for msg, refused, expect in cases:
            with self.subTest(msg=msg):
                e = self.error(msg, refused)
                self.assertIn(expect, e['title'])
                if expect == 'did not work':                 # the generic fallback shows the real message
                    self.assertIn(msg[1:], e['text'])         # only the first letter's case differs


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

    def test_another_photo_with_the_same_name_and_size_is_kept(self):
        # uncompressed captures of one camera all have one size: the bytes decide, not the name and the size
        a, b = self.uncompressed(1), self.uncompressed(2)
        self.assertEqual(len(a), len(b))
        first, kept1 = self.upload(a)
        with open(sidecar_path(first['path']), 'w') as fh:
            fh.write('{"the": "first photo\'s positioning"}')
        second, kept2 = self.upload(b)
        self.assertNotEqual(second['path'], first['path'], 'a copy of its own')
        self.assertTrue(os.path.basename(second['path']).endswith(' (2).tif'), second['path'])
        self.assertEqual((kept1, kept2), (a, b), 'each copy holds its own pixels')
        self.assertFalse(second['located'], 'and starts without the other photo\'s positioning')
        self.assertEqual(open(sidecar_path(first['path'])).read(), '{"the": "first photo\'s positioning"}', 'the first is untouched')
        third, _ = self.upload(b)                                     # the second photo again: its own copy again
        self.assertEqual(third['path'], second['path'])
        self.assertEqual(self.upload(a)[0]['path'], first['path'])
        c = self.uncompressed(3)
        self.assertTrue(os.path.basename(self.upload(c)[0]['path']).endswith(' (3).tif'))

    def test_an_upload_leaves_no_temporary_file_behind(self):
        a = self.uncompressed(1)
        self.upload(a)
        self.upload(a)
        self.upload(self.uncompressed(2))
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, 'work'))), ['moon (2).tif', 'moon.tif'])

    def test_two_different_photos_racing_for_one_name_both_survive(self):
        """BUG-03: the no-hard-links fallback checked that the name was free and then renamed over it, so two
        uploads could pass the check together and the later one destroyed the earlier photo. Both uploads are
        released from a barrier, so the race is real and not a timing sleep."""
        a, b = self.uncompressed(1), self.uncompressed(2)
        self.assertEqual(len(a), len(b), 'equal length, so neither wins on size')
        gate = threading.Barrier(2, timeout=30)
        out = {}
        def send(key, payload):
            gate.wait()
            out[key] = self.upload(payload)
        threads = [threading.Thread(target=send, args=kv) for kv in (('a', a), ('b', b))]
        for t in threads: t.start()
        for t in threads: t.join(60)
        self.assertEqual(set(out), {'a', 'b'}, 'both uploads answered')
        paths = {k: v[0]['path'] for k, v in out.items()}
        self.assertNotEqual(paths['a'], paths['b'], 'each payload got a name of its own')
        for key, payload in (('a', a), ('b', b)):
            with open(paths[key], 'rb') as fh:
                self.assertEqual(fh.read(), payload, f'{key} was not overwritten by the other upload')
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, 'work'))), ['moon (2).tif', 'moon.tif'])

    def test_a_folder_without_hard_links_fails_the_upload_instead_of_replacing(self):
        """The bounded safe default: no atomic claim is available, so the upload fails cleanly. Nothing already
        in the work folder is touched and no temporary file is left behind."""
        first, _ = self.upload(self.uncompressed(1))
        with open(sidecar_path(first['path']), 'w') as fh:
            fh.write('{"the": "first photo\'s positioning"}')
        before = open(first['path'], 'rb').read()
        def no_links(src, dst, **kw):
            raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))
        with mock.patch.object(os, 'link', no_links):
            c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
            c.request('POST', '/app/upload?name=moon.tif&time=', self.uncompressed(2),
                      {'Host': 'localhost', 'X-LA-Token': self.srv.token})
            r = c.getresponse()
            body = json.loads(r.read())
            c.close()
        self.assertEqual(r.status, 500)
        self.assertIn('hard link', body['error'])
        with open(first['path'], 'rb') as fh:
            self.assertEqual(fh.read(), before, 'the photo already there is untouched')
        self.assertEqual(open(sidecar_path(first['path'])).read(), '{"the": "first photo\'s positioning"}')
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, 'work'))), ['moon.tif', 'moon.tif.atlas.json'],
                         'the photo and its sidecar only: no temporary file and no second copy')

    def test_racing_uploads_without_hard_links_lose_no_photo(self):
        """The actual BUG-03 sequence: no hard links, so the old code checked that `moon.tif` was free and then
        renamed onto it. Both uploads passed the check and the loser's pixels were destroyed. Now neither claims
        the name, both are told so, and no half-published image appears in the work folder."""
        a, b = self.uncompressed(1), self.uncompressed(2)
        gate = threading.Barrier(2, timeout=30)
        out = {}
        def no_links(src, dst, **kw):
            raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))
        def send(key, payload):
            gate.wait()
            c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
            c.request('POST', '/app/upload?name=moon.tif&time=', payload,
                      {'Host': 'localhost', 'X-LA-Token': self.srv.token})
            r = c.getresponse()
            out[key] = (r.status, json.loads(r.read()))
            c.close()
        with mock.patch.object(os, 'link', no_links):
            threads = [threading.Thread(target=send, args=kv) for kv in (('a', a), ('b', b))]
            for t in threads: t.start()
            for t in threads: t.join(60)
        self.assertEqual(set(out), {'a', 'b'})
        for key, (status, body) in out.items():
            self.assertEqual(status, 500, f'{key} was not quietly published over the other')
            self.assertIn('hard link', body['error'])
        self.assertEqual(os.listdir(os.path.join(self.tmp, 'work')), [],
                         'no photo, no partial copy and no temporary file')

    def test_a_permission_error_is_reported_as_itself_and_cleans_up(self):
        def denied(src, dst, **kw):
            raise PermissionError(errno.EACCES, 'Permission denied')
        with mock.patch.object(os, 'link', denied):
            c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
            c.request('POST', '/app/upload?name=moon.tif&time=', self.uncompressed(1),
                      {'Host': 'localhost', 'X-LA-Token': self.srv.token})
            r = c.getresponse()
            body = json.loads(r.read())
            c.close()
        self.assertEqual(r.status, 500)
        self.assertIn('Permission denied', body['error'])
        self.assertNotIn('hard link', body['error'], 'not reported as an unsupported filesystem')
        self.assertEqual(os.listdir(os.path.join(self.tmp, 'work')), [], 'no partial image, no temporary file')

    def test_a_name_taken_by_a_symlink_out_of_the_folder_is_refused_not_followed(self):
        """A symlink planted in the work folder is never written through, by the hard-link claim or anything
        else: the upload is refused and the file it points at keeps its bytes."""
        work = os.path.join(self.tmp, 'work')
        os.makedirs(work, exist_ok=True)
        outside = os.path.join(self.tmp, 'outside.tif')
        with open(outside, 'wb') as fh: fh.write(b'not a photo')
        os.symlink(outside, os.path.join(work, 'moon.tif'))
        c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
        c.request('POST', '/app/upload?name=moon.tif&time=', self.uncompressed(1),
                  {'Host': 'localhost', 'X-LA-Token': self.srv.token})
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        self.assertEqual(r.status, 400)
        self.assertNotIn('path', body)
        with open(outside, 'rb') as fh:
            self.assertEqual(fh.read(), b'not a photo', 'the file the symlink pointed at is untouched')


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

    @S.disabled_for_speed
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

    def open_image(self, name, **kw):
        os.makedirs(self.folder, exist_ok=True)
        img, _ = S.moon_image(self.folder, name, **kw)
        self.assertEqual(self.call('POST', '/app/open', json.dumps(dict(path=img)).encode())[0], 200)
        self.assertEqual(self.wait()['phase'], 'ready')
        return img

    def test_a_page_left_open_on_a_replaced_image_cannot_write_read_or_export_the_new_one(self):
        """claude-findings.md C-01: opening image B must not let a page still showing image A save into B's
        sidecar, read B's edits or export status as if they were A's, or start an export of B while claiming A."""
        a = self.open_image('A.tif')
        sid_a = self.call('GET', '/data.json')[1]['tiles_v']
        b = self.open_image('B.tif', theta=10.0)
        body = json.dumps(dict(rev=1, sid=sid_a, shapes=[dict(kind='text', x=1, y=1, label='from a stale tab')])).encode()
        code, r = self.call('POST', '/edits', body)
        self.assertEqual(code, 409)
        self.assertTrue(r.get('gone'))
        self.assertEqual(S.sidecar(b).get('edits', {}).get('shapes', []), [], "B's edits are untouched")
        self.assertEqual(S.sidecar(a).get('edits', {}).get('shapes', []), [], "A's own sidecar is untouched too")
        self.assertEqual(self.call('GET', f'/edits?sid={sid_a}')[0], 409)
        self.assertEqual(self.call('GET', f'/export/status?sid={sid_a}')[0], 409)
        self.assertEqual(self.call('POST', '/export', json.dumps(dict(sid=sid_a)).encode())[0], 409)
        # a page that never learned a sid (an older page, or a direct API caller) still works as before
        self.assertEqual(self.call('GET', '/edits')[0], 200)

    def test_opening_another_image_is_refused_while_an_export_is_running(self):
        """claude-findings.md C-02: opening another image must not orphan a running export — untracked, not
        stopped on quit, invisible to the browser-mode idle timer."""
        self.open_image('A.tif')
        session = self.app.server.session
        session.job = mock.Mock(state='running')
        self.addCleanup(setattr, session, 'job', None)
        b, _ = S.moon_image(self.folder, 'B.tif', theta=10.0)
        code, r = self.call('POST', '/app/open', json.dumps(dict(path=b)).encode())
        self.assertEqual(code, 409)
        self.assertIn('export', r.get('error', ''))
        self.assertIs(self.app.server.session, session, "the session (and its export job) wasn't replaced")

    def test_two_uploads_racing_for_the_same_name_both_keep_their_own_photo(self):
        """claude-findings.md C-23: the destination name is claimed atomically, so two uploads finishing at the
        same instant cannot have the later one silently replace the earlier photo under one name."""
        bodies = [f'photo {i}'.encode() * 500 for i in range(2)]
        results = []

        def up(body):
            results.append(self.upload_bytes('same.tif', body))
        threads = [threading.Thread(target=up, args=(b,)) for b in bodies]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        paths = {r[1]['path'] for r in results}
        self.assertEqual(len(paths), 2, f'both uploads kept a name of their own: {results}')
        contents = {open(p, 'rb').read() for p in paths}
        self.assertEqual(contents, set(bodies))

    def upload_bytes(self, name, body):
        return self.call('POST', f'/app/upload?name={name}&time=', body)


if __name__ == '__main__':
    unittest.main()
