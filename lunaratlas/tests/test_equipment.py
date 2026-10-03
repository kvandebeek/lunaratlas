"""The equipment and observing site (atlas_equipment, equipment.json): what is kept, what a page may send, the setups
the close-up search gets from it, the launcher's routes, and the stop that lets the page ask what took a close-up."""
import http.client
import json
import os
import stat
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import _support as S

import atlas_ephem as ae
import atlas_equipment as eq
from atlas_app import App
from atlas_view import start_server

TEL = dict(name='250 PDS', focal_mm=1200)
CAM = dict(name='ZWO ASI678MC', sensor='IMX678', pixel_um=2.0, width=3840, height=2160)


class Own(S.TempDir):
    """Each test with an equipment file of its own (none at first)."""

    def setUp(self):
        super().setUp()
        self.file = os.path.join(self.tmp, 'equipment.json')
        p = mock.patch.dict(os.environ, LUNARATLAS_EQUIPMENT=self.file)
        p.start()
        self.addCleanup(p.stop)


class Equipment(Own, unittest.TestCase):
    def test_nothing_is_assumed_without_a_file(self):
        self.assertEqual(eq.load(), eq.empty())
        self.assertEqual(eq.setups(), [])
        self.assertIsNone(eq.site(), 'no site: the ephemeris is geocentric, nobody is put in Belgium')

    def test_setups_are_every_telescope_barlow_camera_and_binning(self):
        d = eq.save(dict(telescopes=[TEL, dict(name='80ED', focal_mm=480)], barlows=[dict(name='ES', factor=2)],
                         cameras=[dict(CAM, binnings=[1, 2])]))
        s = eq.setups(d)
        self.assertEqual(len(s), 2 * 2 * 2)
        self.assertEqual(len({x['id'] for x in s}), len(s), 'every setup has an id of its own')
        x = eq.find('t1/b1/c1/2', d)
        self.assertEqual((x['focal_mm'], x['pixel_um'], x['binning'], x['width']), (2400, 4.0, '2×2', 1920))
        self.assertAlmostEqual(eq.arcsec_per_px(x), 206.265 * 4.0 / 2400)
        self.assertEqual(eq.text(x), '250 PDS · ES 2× · ZWO ASI678MC 2×2 binned (2400 mm, 0.344″/px)')
        self.assertEqual(eq.find('t1/native/c1/1', d)['extender'], 'native')

    def test_ticked_off_setups_are_not_searched(self):
        d = eq.save(dict(telescopes=[TEL], cameras=[CAM], barlows=[dict(name='B', factor=2)], unused=['t1/b1/c1/1']))
        self.assertEqual([s['id'] for s in eq.setups(d)], ['t1/native/c1/1'])
        self.assertEqual(len(eq.setups(d, include_unused=True)), 2)
        self.assertFalse(eq.find('t1/b1/c1/1', d)['used'])

    def test_what_a_page_sends_is_checked(self):
        for bad in (dict(telescopes=[dict(name='x', focal_mm=5)]), dict(telescopes=[dict(name='', focal_mm=1200)]),
                    dict(cameras=[dict(name='c', pixel_um='nan')]), dict(cameras=[dict(name='c', pixel_um=2, binnings=[9])]),
                    dict(barlows=[dict(name='b', factor=True)]), dict(site=dict(lat=95, lon=0)),
                    dict(telescopes='250 PDS'), dict(telescopes=[TEL] * 41), [], None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                eq.clean(bad)
        d = eq.clean(dict(telescopes=[dict(TEL, id='t7'), dict(TEL, id='t7')], unused=['nonsense', 't7/native/c9/1']))
        self.assertEqual([t['id'] for t in d['telescopes']], ['t7', 't1'], 'a repeated id gets a new one')
        self.assertEqual(d['unused'], [], 'only setups that exist are kept')

    def test_a_save_is_read_back_even_when_the_file_looks_unchanged(self):
        """On Windows two saves within one clock tick keep the file's time, and reordering `recent` keeps its size:
        load() handed back the order from before the save (CI, windows-latest)."""
        d, sid = eq.add(TEL, None, CAM)
        d, sid2 = eq.add(TEL, dict(name='Barlow', factor=2), CAM)
        with mock.patch.object(eq, '_key', return_value=('the same file, time and size',)):
            eq.load()
            eq.remember(sid)
            self.assertEqual(eq.load()['recent'], [sid, sid2])

    def test_saved_for_this_user_only_and_read_back(self):
        eq.save(dict(telescopes=[TEL], cameras=[CAM], site=dict(lat=48.2, lon=16.4, height_m=200)))
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o600)
        self.assertEqual(eq.site(), (48.2, 16.4, 0.2))
        self.assertEqual(eq.load()['telescopes'][0]['name'], '250 PDS')
        with open(self.file, 'w') as fh:
            fh.write('{ not json')
        self.assertEqual(eq.load(), eq.empty(), 'a damaged file is no equipment, not a crash')

    def test_the_short_form_adds_once_and_puts_the_setup_first(self):
        d, sid = eq.add(TEL, None, CAM)
        self.assertEqual(sid, 't1/native/c1/1')
        d, sid2 = eq.add(dict(name='250 pds', focal_mm=1200), dict(name='Barlow', factor=2), CAM, 2)
        self.assertEqual(len(d['telescopes']), 1, 'the same telescope is not added twice')
        self.assertEqual(len(d['cameras']), 1)
        self.assertEqual(d['cameras'][0]['binnings'], [1, 2], 'a new binning is added to the camera')
        self.assertEqual(sid2, 't1/b1/c1/2')
        self.assertEqual(d['recent'], [sid2, sid])
        eq.remember(sid)
        self.assertEqual(eq.load()['recent'], [sid, sid2])
        eq.remember('t9/native/c9/1')
        self.assertEqual(eq.load()['recent'], [sid, sid2], 'an unknown setup is not remembered')
        with self.assertRaises(ValueError):
            eq.add(TEL, None, dict(name='c', pixel_um=99))


class Site(Own, unittest.TestCase):
    T = datetime(2026, 9, 23, 21, 38, tzinfo=timezone.utc)

    def test_no_site_is_geocentric_and_a_site_is_read_when_used(self):
        self.assertEqual(ae.ephemeris(self.T), ae.ephemeris(self.T, obs=None))
        eq.save(dict(site=dict(lat=50.9, lon=4.4, height_m=50)))
        self.assertEqual(ae.ephemeris(self.T), ae.ephemeris(self.T, obs=(50.9, 4.4, 0.05)),
                         'a site saved in Settings applies at once, no restart')
        self.assertNotEqual(ae.ephemeris(self.T)['sub_obs_lat'], ae.ephemeris(self.T, obs=None)['sub_obs_lat'])


class Launcher(Own, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, 'work')
        self.app = App(self.folder, S.quiet)
        self.srv = start_server(S.free_port(), S.quiet, app=self.app)
        self.app.server = self.srv
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, obj=None):
        c = http.client.HTTPConnection('127.0.0.1', self.srv.server_port, timeout=60)
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode() if obj is not None else b''
        c.request(method, path, body, {'Host': 'localhost', 'X-LA-Token': self.srv.token})
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def test_the_pages_and_files_are_served(self):
        for p in ('/settings', '/equipment.js', '/settings.js', '/cameras.json'):
            self.assertEqual(self.call('GET', p)[0], 200, p)
        cams = self.call('GET', '/cameras.json')[1]
        for brand, model, sensor in cams['planetary']:
            self.assertIn(sensor, cams['sensors'], f'{brand} {model}')

    def test_the_short_form_and_settings_save_through_the_routes(self):
        self.assertEqual(self.call('GET', '/app/equipment')[1]['setups'], [])
        code, r = self.call('POST', '/app/equipment/add', dict(telescope=TEL, barlow=None, camera=CAM, binning=1))
        self.assertEqual(code, 200, r)
        self.assertEqual(r['setup'], 't1/native/c1/1')
        row = r['setups'][0]
        self.assertEqual(row['field_arcmin'], [22.0, 12.4])
        self.assertIn('0.344″/px', row['text'])
        doc = r['equipment']
        doc['site'] = dict(lat=48.2, lon=16.4)
        code, r = self.call('POST', '/app/equipment', dict(equipment=doc))
        self.assertEqual(code, 200, r)
        self.assertEqual(eq.site(), (48.2, 16.4, 0.0))
        code, r = self.call('POST', '/app/equipment', dict(equipment=dict(telescopes=[dict(name='x', focal_mm=-1)])))
        self.assertEqual(code, 400)
        self.assertIn('focal_mm', r['error'])
        self.assertEqual(len(eq.setups()), 1, 'a refused save changes nothing')
        self.assertEqual(self.call('POST', '/app/equipment/add', b'[1]')[0], 400)

    def test_a_setup_that_is_not_there_is_refused(self):
        os.makedirs(self.folder)
        img, _ = S.moon_image(self.folder, 'm.tif')
        code, r = self.call('POST', '/app/locate', dict(path=img, setup='t9/native/c1/1'))
        self.assertEqual(code, 400)
        self.assertIn('setup', r['error'])

    def test_a_close_up_with_no_equipment_known_stops_and_asks(self):
        import cv2
        import numpy as np
        os.makedirs(self.folder)
        img = os.path.join(self.folder, '2026-09-23-2138_1-Moon_closeup.png')
        rng = np.random.default_rng(3)
        cv2.imwrite(img, (rng.random((300, 400)) * 200 + 30).astype(np.uint8))     # no limb anywhere
        self.assertEqual(self.call('POST', '/app/locate', dict(path=img, force=True))[0], 200)
        t0 = time.time()
        while time.time() - t0 < 120 and self.call('GET', '/app/status')[1]['phase'] == 'locating':
            time.sleep(0.2)
        st = self.call('GET', '/app/status')[1]
        self.assertEqual(st['phase'], 'equipment', st)
        self.assertIsNone(st['error'], 'a question, not a failure')
        self.assertTrue(self.call('POST', '/app/cancel', b'{}')[1]['ok'], 'putting the question away')
        self.assertEqual(self.call('GET', '/app/status')[1]['phase'], 'idle')


class Cli(Own, unittest.TestCase):
    def test_locate_asks_only_when_told_to_and_names_a_missing_setup(self):
        import cv2
        import numpy as np
        img = os.path.join(self.tmp, '2026-09-23-2138_1-Moon_closeup.png')
        cv2.imwrite(img, (np.random.default_rng(3).random((300, 400)) * 200 + 30).astype(np.uint8))
        home = os.path.join(self.tmp, 'home')
        os.makedirs(home)
        r = S.run_cli('locate', img, '--force', '--ask-equipment', home=home, timeout=S.budget(120))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(eq.NEED, r.stdout + r.stderr)
        r = S.run_cli('locate', img, '--force', '--setup', 't1/native/c1/1', home=home, timeout=S.budget(120))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no setup t1/native/c1/1', r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
