"""The pages as a user works them: real mouse and keyboard input in a browser (tests/ui/journeys.mjs).

Headless Chrome by default; LUNARATLAS_BROWSER=edge, firefox or safari drives that one instead (Chrome and Edge
through the DevTools protocol, cdp.mjs; Firefox and Safari through WebDriver, webdriver.mjs). The journeys a browser
cannot run are skipped with "not in this browser" (NOT_IN below).

Where test_e2e_journeys.py runs checks inside the page (viewer_selftest.js, synthetic events), these go through
Chrome's input pipeline from outside: a click lands on whatever is on top at that spot, so a covered, hidden or
disabled control fails the way it would fail a user. Each journey then checks what reached the server and the disk.

The server runs in this process (the launcher, which also serves the viewer), with "show in the file manager"
recorded instead of opening Finder or Explorer. A failing journey leaves a screenshot per failed check in
LUNARATLAS_UI_OUT (default: a folder in the test's temporary directory, printed with the failure).
"""
import glob
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import _support as S
import cv2
import numpy as np

import atlas_app
import atlas_view
from atlas_app import App
from atlas_geo import sidecar_path
from atlas_view import start_server

NODE = shutil.which('node')
JOURNEYS = os.path.join(S.HERE, 'ui', 'journeys.mjs')
BROWSER_ENV = S.ui_browser_env()
# journeys a browser cannot run, and why; a skip with any other reason is a missing browser or missing data
NOT_IN = dict.fromkeys(('firefox', 'safari'), {
    'launch': 'WebDriver cannot set the time zone the capture time is typed in',
    'exif': 'WebDriver cannot set the time zone the camera time is shown in',
})


@unittest.skipUnless(NODE, 'node not installed')
@unittest.skipUnless(BROWSER_ENV, f'{S.BROWSER} not found (LUNARATLAS_CHROME, LUNARATLAS_EDGE or LUNARATLAS_WEBDRIVER)')
@S.needs_all
class UI(S.TempDir):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, 'work')
        os.makedirs(self.folder)
        self.revealed = []
        for mod in (atlas_app, atlas_view):
            p = mock.patch.object(mod, 'reveal', self.revealed.append)
            p.start()
            self.addCleanup(p.stop)
        self.app = App(self.folder, S.quiet)
        self.srv = start_server(S.free_port(), S.quiet, app=self.app)
        self.app.server = self.srv
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.app.stop_jobs)
        self.base = f'http://localhost:{self.srv.server_port}'
        self.out = os.environ.get('LUNARATLAS_UI_OUT') or os.path.join(self.tmp, 'ui')

    def call(self, method, path, body=b''):
        c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=30)
        c.request(method, path, body, {'Host': 'localhost', 'X-LA-Token': self.srv.token})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data) if data[:1] in (b'{', b'[') else data

    def open_image(self, gate=None):
        """A synthetic Moon, positioned, opened in the viewer as the launcher opens it."""
        img, _ = S.moon_image(self.folder)
        if gate:
            d = S.sidecar(img)
            d['quality_gate'] = gate
            with open(sidecar_path(img), 'w', encoding='utf-8') as fh:
                json.dump(d, fh)
        self.assertEqual(self.call('POST', '/app/open', json.dumps(dict(path=img)).encode())[0], 200)
        t0 = time.time()
        while time.time() - t0 < 60:
            st = self.call('GET', '/app/status')[1]
            if st['phase'] in ('ready', 'failed'):
                break
            time.sleep(0.2)
        self.assertEqual(st['phase'], 'ready', st)
        return img

    def journey(self, name, timeout=600, **args):
        why = NOT_IN.get(S.BROWSER, {}).get(name)
        if why:
            self.skipTest(f'not in this browser: {why}')
        env = {k: v for k, v in os.environ.items() if k not in ('LUNARATLAS_CHROME', 'LUNARATLAS_WEBDRIVER')}
        env.update(BROWSER_ENV)
        env['LUNARATLAS_UI_TOKEN'] = self.srv.token
        r = subprocess.run([NODE, JOURNEYS, name, self.base, self.out, json.dumps(args)], capture_output=True,
                           text=True, timeout=timeout, env=env)
        lines = r.stdout.splitlines()
        report = '\n'.join(lines) + ('\n' + r.stderr[-2000:] if r.stderr.strip() else '')
        self.assertTrue(any(l.startswith('DONE') for l in lines), f'the {name} journey did not finish:\n{report}')
        self.assertEqual([l for l in lines if l.startswith(('FAIL', 'SHOT'))], [], f'journey {name}:\n{report}')
        self.assertEqual(r.returncode, 0, report)
        return [l[5:] for l in lines if l.startswith('PASS ')]

    def edits(self, img):
        return S.sidecar(img).get('edits', {})

    # ---------------------------------------------------------------- the viewer
    def test_every_tool_button_its_tooltip_and_its_key(self):
        self.open_image()
        self.assertGreaterEqual(len(self.journey('tools')), 25)

    def test_drawing_with_every_tool_and_its_editor(self):
        img = self.open_image()
        self.journey('draw')
        shapes = self.edits(img)['shapes']
        self.assertEqual([s['kind'] for s in shapes], ['circle', 'ellipse', 'rect', 'arrow', 'outline', 'text'])
        self.assertTrue(all(s.get('label') for s in shapes), 'every drawing kept its label in the sidecar')

    def test_moving_deleting_and_undoing_a_drawing(self):
        img = self.open_image()
        self.journey('edit')
        self.assertEqual([s['label'] for s in self.edits(img)['shapes']], ['ab'])

    def test_measuring_a_distance(self):
        img = self.open_image()
        self.journey('measure')
        self.assertEqual(self.edits(img)['shapes'], [])

    def test_zoom_pan_fit_and_the_status_bar(self):
        self.open_image()
        self.journey('navigate')

    def test_the_search_box_by_keyboard_and_mouse(self):
        self.open_image()
        self.journey('search')

    def test_a_names_card_restyles_moves_and_hides_it(self):
        img = self.open_image()
        self.journey('card')
        e = self.edits(img)
        self.assertEqual(e['hidden'], [], 'the hide was undone')
        self.assertTrue(any(o.get('size') == 1.3 and 'dx' not in o for o in e['labels'].values()), e['labels'])

    def test_the_layers_panel(self):
        img = self.open_image()
        self.journey('layers')
        st = self.edits(img)['style']
        self.assertEqual(st['night'], 'hide')
        self.assertEqual(sorted(st['layers']), ['area', 'crater', 'landing', 'lettered', 'relief'])

    def test_picking_several_names(self):
        img = self.open_image()
        self.journey('picks')
        self.assertEqual(len(self.edits(img)['hidden']), 1)

    def test_export_from_the_dialog_to_the_file(self):
        img = self.open_image()
        self.journey('export')
        stem = os.path.splitext(img)[0]
        png = cv2.imread(stem + '_atlas.png', cv2.IMREAD_UNCHANGED)
        src = cv2.imread(img, cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(png, os.listdir(self.folder))
        self.assertEqual(png.dtype, np.uint16, '16-bit PNG')
        self.assertEqual(png.shape[:2], (round(src.shape[0] / 2), round(src.shape[1] / 2)), 'the 1:2 scale')
        jpgs = glob.glob(stem + '_atlas_region_*.jpg')
        self.assertEqual(len(jpgs), 1, os.listdir(self.folder))
        self.assertLessEqual(max(cv2.imread(jpgs[0]).shape[:2]), 512)
        # P11's export manifest (OUTPUT.export.json) sits beside the real export and must not be counted as one;
        # '*.tif*' also matched it (a '.tif.export.json' name), which this test never anticipated
        tifs = [f for f in glob.glob(stem + '_atlas_*.tif*') if not f.endswith('.export.json')]
        self.assertEqual(len(tifs), 1, os.listdir(self.folder))
        self.assertEqual([os.path.realpath(r) for r in self.revealed], [os.path.realpath(stem + '_atlas.png')],
                         'Show in Finder showed the PNG')

    def test_a_reload_keeps_every_edit(self):
        self.open_image()
        self.journey('persist')

    def test_an_edit_made_an_instant_before_leaving_is_kept(self):
        img = self.open_image()
        self.journey('leave')
        self.assertEqual([s.get('label') for s in self.edits(img)['shapes']], ['Last words', 'Reloaded'])

    def test_an_export_does_not_start_when_the_drawings_cannot_be_saved(self):
        img = self.open_image()
        self.journey('savefail')
        self.assertEqual([s.get('label') for s in self.edits(img)['shapes']], ['Unsaved'], 'saved once the connection was back')

    def test_the_preview_renders_once_per_change(self):
        self.open_image()
        self.journey('preview')

    def test_the_quality_warning_of_a_photo_named_anyway(self):
        self.open_image(gate=dict(ok=False, forced=True, reasons=['too blurry'],
                                  line='quality refused: too blurry · edge 9.1 px'))
        self.journey('gate')

    def test_reshaping_drawings_by_their_squares(self):
        img = self.open_image()
        self.journey('handles')
        self.assertEqual([s['kind'] for s in self.edits(img)['shapes']],
                         ['circle', 'rect', 'arrow', 'outline', 'measure', 'rect'])

    def test_an_export_that_fails(self):
        self.open_image()
        with mock.patch.object(atlas_view, 'self_command',
                               lambda *a: [sys.executable, '-c', 'import sys; print("cannot write"); sys.exit(3)']):
            self.journey('exportfail')
        self.assertEqual(self.revealed, [])

    # ---------------------------------------------------------------- the launcher
    def source(self, name='moon.tif'):
        src, _ = S.moon_image(self.tmp, name=name)
        os.remove(sidecar_path(src))
        return src

    def test_progress_rendering_against_a_scripted_status_sequence(self):
        """bugs-overview BUG-22: the real launch journey's own progress sampling used to race a fast synthetic
        locate (the page can update the bar and navigate away in the same task). This drives the exact
        render path with a controlled, deterministic status sequence instead -- no real locate, no timing."""
        img, _ = S.moon_image(self.folder)      # a real photo in the work folder: the header shows its thumbnail
        self.journey('progressStages', image=img)

    def test_from_choosing_a_file_to_the_viewer_and_back(self):
        src = self.source()
        self.journey('launch', image=src)
        copy = os.path.join(self.folder, '2026-09-20-1930_0-moon.tif')      # 21:30 in Brussels, in UTC
        self.assertTrue(os.path.exists(copy), os.listdir(self.folder))
        self.assertTrue(os.path.exists(sidecar_path(copy)), 'the copy was located')

    def test_drop_keyboard_and_refused_files(self):
        src = self.source()
        stamped = self.source('2026-09-20-2130_0-stamped.tif')
        text = os.path.join(self.tmp, 'notes.txt')
        with open(text, 'w') as fh:
            fh.write('not a photo')
        self.journey('drop', image=src, stamped=stamped, text=text)
        self.assertEqual(os.listdir(self.folder), [], 'nothing is copied before "Find the names"')

    def test_cancelling_a_locate(self):
        # the synthetic Moon is found in seconds: a stand-in locate that searches for a minute gives Cancel its time
        slow = ("import sys, time\nprint('capture 2026-09-20 19:30 UTC', flush=True)\nprint('limb: r 700 px', flush=True)\n"
                "for i in range(120):\n    print(f'search: {i + 1}/120 views', flush=True); time.sleep(0.5)\n")
        started = []

        def fake(*args):
            started.append(args)
            return [sys.executable, '-c', slow]
        with mock.patch.object(atlas_app, 'self_command', fake):
            self.journey('cancel', image=self.source())
        self.assertEqual(started[0][0], 'locate')
        self.assertEqual(self.call('GET', '/app/status')[1]['phase'], 'idle')
        self.assertIsNotNone(self.app.job.proc.poll(), 'the locate process was stopped')

    def test_a_photo_without_the_moon(self):
        blank = os.path.join(self.tmp, 'blank.png')
        cv2.imwrite(blank, np.zeros((300, 400), np.uint8))
        self.journey('fail', blank=blank)

    def camera_jpeg(self, name, when=None, zone=None):
        from PIL import Image
        src = self.source(os.path.splitext(name)[0] + '.tif')
        im = cv2.imread(src, cv2.IMREAD_UNCHANGED)
        im8 = cv2.convertScaleAbs(im, alpha=255 / max(1, int(im.max())))
        out = os.path.join(self.tmp, name)
        pil = Image.fromarray(im8)
        exif = Image.Exif()
        if when:
            ex = exif.get_ifd(0x8769)
            ex[0x9003] = when
            if zone:
                ex[0x9011] = zone
        pil.save(out, exif=exif.tobytes())
        return out

    def test_the_camera_time_is_read_from_the_photo(self):
        self.journey('exif', utc=self.camera_jpeg('utc.jpg', '2026:09:20 21:30:00', '+00:00'),
                     clock=self.camera_jpeg('clock.jpg', '2026:09:20 21:30:00'), plain=self.camera_jpeg('plain.jpg'))

    def test_a_photo_refused_by_the_quality_check(self):
        name = '2026-09-20-1930_0-moon.tif'
        img, _ = S.moon_image(self.folder, name=name)
        d = S.sidecar(img)
        d['quality_gate'] = dict(ok=False, forced=False, reasons=['too blurry'], line='quality refused: too blurry')
        with open(sidecar_path(img), 'w', encoding='utf-8') as fh:
            json.dump(d, fh)
        again = os.path.join(self.tmp, name)
        shutil.copy(img, again)
        with open(os.path.join(self.folder, 'broken.tif'), 'wb') as fh:
            fh.write(b'II*\x00 not really a TIFF')
        self.journey('refused', image=again)
        self.assertTrue(S.sidecar(img)['quality_gate'].get('ok') or S.sidecar(img)['quality_gate'].get('forced'),
                        'named anyway')

    def test_the_folder_link_and_quit(self):
        self.journey('quit')
        self.assertEqual([os.path.realpath(r) for r in self.revealed], [os.path.realpath(self.folder)],
                         'the folder link shows the work folder')
        time.sleep(0.5)
        with self.assertRaises(OSError):
            self.call('GET', '/app/ping')


if __name__ == '__main__':
    unittest.main()
