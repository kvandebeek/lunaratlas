"""The local server, downloads, temporary files and someone else's sidecar, as an attacker would meet them:
another site's page in the same browser, DNS rebinding, a local process, a hostile download or a shared sidecar."""
import http.client
import io
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock
from urllib.parse import urlparse

import _support as S
from atlas_geo import download, https_open, sha256_file, sidecar_path, write_atomic
from atlas_paths import publish, temp_beside


def raw(url, method='GET', path='/', headers=None, body=None):
    """One request with exactly these headers (a browser's, or an attacker's): (status, headers, body)."""
    u = urlparse(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=20)
    hdr = dict({'Host': f'localhost:{u.port}'}, **(headers or {}))
    c.request(method, path, body, hdr)
    r = c.getresponse()
    data = r.read()
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, data)
    c.close()
    return out


@S.needs_all
class ViewerIsLocalOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='lunaratlas_sec_')
        cls.home = os.path.join(cls.tmp, 'home')
        os.makedirs(cls.home)
        cls.img, cls.geo = S.moon_image(cls.tmp)
        cls.v = S.Viewer(cls.img, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls.v.close()
        shutil.rmtree(cls.tmp, True)

    def req(self, method='GET', path='/', headers=None, body=None, auth=True):
        """raw() to the viewer as its own page would: with the cookie the token link gave it."""
        h = dict(headers or {})
        if auth:
            h.setdefault('Cookie', self.v.cookie)
        return raw(self.v.url, method, path, h, body)

    def test_head_is_not_a_file_probe(self):
        for path in ('/etc/hosts', os.path.expanduser('~/.zshrc'), '/does-not-exist', '/'):
            for host in (None, 'evil.example'):
                with self.subTest(path=path, host=host):
                    code, hdr, body = self.req('HEAD', path, {'Host': host} if host else None)
                    self.assertIn(code, (403, 405))
                    self.assertNotIn('last-modified', hdr)
                    self.assertEqual(body, b'')

    def test_nothing_answers_without_the_token(self):
        for method, path, body in (('GET', '/data.json', None), ('GET', '/edits', None), ('GET', '/tiles/0/0_0.jpg', None),
                                   ('GET', '/', None), ('GET', '/viewer.js', None), ('POST', '/edits', b'{}'),
                                   ('POST', '/export', b'{}'), ('POST', '/reveal', b'{}')):
            for hdr in ({}, {'Cookie': f'{self.v.cookie[:-3]}xyz'}, {'Cookie': 'la_0=' + self.v.token}, {'X-LA-Token': 'nope'}):
                with self.subTest(path=path, hdr=hdr):
                    code, _, data = self.req(method, path, hdr, body, auth=False)
                    self.assertEqual(code, 403)
                    self.assertNotIn(b'moon.tif', data)

    def test_the_token_link_hands_the_browser_a_cookie_and_goes_on_without_it(self):
        code, hdr, _ = self.req('GET', f'/?t={self.v.token}&group=x', auth=False)
        self.assertEqual(code, 303)
        self.assertEqual(hdr['location'], '/?group=x', 'the token is gone from the address, the rest stays')
        cookie = hdr['set-cookie']
        for part in ('HttpOnly', 'SameSite=Strict', f'{self.v.cookie}'):
            self.assertIn(part, cookie)
        code, _, body = self.req('GET', '/', {'Cookie': cookie.split(';')[0]}, auth=False)
        self.assertEqual(code, 200)
        self.assertIn(b'boot.js', body)
        self.assertEqual(self.req('GET', '/?t=wrong', auth=False)[0], 403)

    def test_the_header_form_of_the_token_is_for_clients_that_are_not_browsers(self):
        self.assertEqual(self.req('GET', '/edits', {'X-LA-Token': self.v.token}, auth=False)[0], 200)

    def test_the_ping_proves_who_it_is_without_showing_the_token(self):
        import hashlib
        import hmac
        code, _, body = self.req('GET', '/app/ping?nonce=abc', auth=False)
        self.assertEqual(code, 200)
        want = hmac.new(self.v.token.encode(), b'abc', hashlib.sha256).hexdigest().encode()
        self.assertEqual(body, b'lunaratlas:' + want)
        self.assertNotIn(self.v.token.encode(), body)
        self.assertEqual(self.req('GET', '/app/ping', auth=False)[0], 403, 'a bare ping needs the token like the rest')

    def test_the_token_is_not_in_the_log_of_a_browser_start(self):
        self.assertNotIn('LUNARATLAS_TOKEN', ''.join(self.v.lines))

    def test_a_late_save_never_overwrites_a_newer_one(self):
        def save(rev, label):
            return self.req('POST', '/edits', {'Content-Type': 'application/json'},
                            json.dumps(dict(rev=rev, shapes=[dict(kind='text', x=5, y=6, label=label)])).encode())
        big = 10 ** 15
        self.assertEqual(save(big + 2, 'newer')[0], 200)
        code, _, body = save(big + 1, 'older')                          # an old request that arrives late
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(body)['rev'], big + 2, 'the refusal says the current revision')
        self.assertEqual(json.loads(self.req('GET', '/edits')[2])['shapes'][0]['label'], 'newer')
        self.assertEqual(save(big + 3, 'newest')[0], 200)
        latest = json.loads(self.req('GET', '/edits')[2])
        self.assertEqual(latest['shapes'][0]['label'], 'newest')
        self.assertEqual(latest['rev'], big + 3, 'the live response carries the current revision')
        with open(sidecar_path(self.img), encoding='utf-8') as fh:
            self.assertNotIn('rev', json.load(fh)['edits'], 'the number is not stored in the sidecar file')
        self.assertEqual(self.req('POST', '/edits', {'Content-Type': 'application/json'}, b'{}')[0], 200, 'a save without one is as before')

    def test_a_non_finite_revision_is_ignored_rather_than_locking_out_every_later_save(self):
        """rev: Infinity (JSON, not standard but accepted by Python's parser) or a huge number must not become the
        server's high-water mark forever: that would make every future save 409 for the rest of the run."""
        def save(body):
            return self.req('POST', '/edits', {'Content-Type': 'application/json'}, body)
        start = json.loads(self.req('GET', '/edits')[2])['rev']         # other tests in this class share the server
        self.assertEqual(save(b'{"rev": Infinity, "shapes": []}')[0], 200)
        self.assertEqual(save(json.dumps(dict(rev=10 ** 30, shapes=[])).encode())[0], 200)
        code, _, _ = save(json.dumps(dict(rev=start + 1, shapes=[dict(kind='text', x=1, y=1, label='still works')])).encode())
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.req('GET', '/edits')[2])['shapes'][0]['label'], 'still works')

    def test_the_banner_names_no_interpreter(self):
        _, hdr, _ = self.req('GET', '/')
        self.assertEqual(hdr.get('server'), 'LunarAtlas')

    def test_only_get_and_post(self):
        for method in ('PUT', 'DELETE', 'PATCH', 'OPTIONS'):
            self.assertEqual(self.req(method, '/edits')[0], 405, method)

    def test_a_script_or_image_include_from_another_site_is_refused(self):
        for path in ('/data.json', '/data.js', '/tiles/0/0_0.jpg', '/edits', '/', '/viewer.js'):
            for site in ('cross-site', 'same-site'):
                code, _, body = self.req('GET', path, {'Sec-Fetch-Site': site, 'Referer': 'https://evil.example/'})
                self.assertEqual(code, 403, f'{path} {site}')
                self.assertNotIn(b'moon.tif', body)
        for site in ('same-origin', 'none'):                      # the page itself, and a link opened by the user
            self.assertEqual(self.req('GET', '/data.json', {'Sec-Fetch-Site': site})[0], 200)

    def test_other_hosts_and_origins_are_refused(self):
        self.assertEqual(self.req('GET', '/data.json', {'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.req('POST', '/edits', {'Origin': 'https://evil.example'}, b'{}')[0], 403)
        self.assertEqual(self.req('POST', '/edits', {'Origin': 'null'}, b'{}')[0], 403)

    def test_the_data_is_json_and_does_not_name_the_account(self):
        code, hdr, body = self.req('GET', '/data.json')
        self.assertEqual(code, 200)
        self.assertTrue(hdr['content-type'].startswith('application/json'))
        self.assertFalse(body.lstrip().startswith(b'window.'), 'no executable script another page could include')
        self.assertNotIn(os.path.expanduser('~').encode(), body)
        self.assertNotIn(self.tmp.encode(), body)
        self.assertEqual(self.req('GET', '/data.js')[0], 404)

    def test_every_response_says_not_to_frame_or_sniff_it(self):
        for path in ('/', '/data.json', '/viewer.js', '/viewer.css', '/nothing-here', '/tiles/0/0_0.jpg'):
            code, hdr, _ = self.req('GET', path)
            self.assertEqual(hdr.get('x-frame-options'), 'DENY', path)
            self.assertEqual(hdr.get('x-content-type-options'), 'nosniff', path)
            self.assertEqual(hdr.get('cross-origin-resource-policy'), 'same-origin', path)
            csp = hdr.get('content-security-policy', '')
            self.assertIn("frame-ancestors 'none'", csp, path)
            self.assertIn("script-src 'self'", csp, path)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", csp, path)

    def test_the_pages_have_no_inline_script_to_run_under_that_policy(self):
        import re
        for path in ('/', '/app'):
            _, _, body = self.req('GET', path)
            for m in re.finditer(rb'<script([^>]*)>', body):
                self.assertIn(b'src=', m[1], f'{path}: an inline script')
            self.assertNotRegex(body, rb'\son(click|load|error|change|input)\s*=')

    def test_bodies_are_bounded(self):
        for length in ('-1', 'abc', str(64 << 20)):
            with self.subTest(length=length):
                s = socket.create_connection((urlparse(self.v.url).hostname, urlparse(self.v.url).port), timeout=10)
                s.sendall((f'POST /edits HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n'
                           f'Cookie: {self.v.cookie}\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n').encode())
                data = s.recv(4096)
                s.close()
                self.assertRegex(data, rb'^HTTP/1\.[01] (400|413)', 'answered at once, not left waiting for a body')

    def test_deeply_nested_json_is_a_400_not_a_crash(self):
        deep = b'[' * 200000 + b']' * 200000
        code, _, _ = self.req('POST', '/edits', {'Content-Type': 'application/json'}, deep)
        self.assertEqual(code, 400)
        self.assertEqual(self.req('GET', '/edits')[0], 200, 'the server is still there')

    def test_the_export_option_cannot_be_read_as_an_argument(self):
        from atlas_view import export_command
        cmd, _ = export_command(self.img, dict(region='feature', name='--output=/tmp/x'))
        self.assertIn('--around=--output=/tmp/x', cmd)
        self.assertNotIn('--output=/tmp/x', cmd)

    def test_drawings_are_capped(self):
        from atlas_view import clean_edits
        big = [dict(kind='outline', pts=[[i, i] for i in range(10000)]) for _ in range(30)]
        e = clean_edits(dict(shapes=big))
        self.assertLessEqual(sum(len(s['pts']) for s in e['shapes']), 200_000)
        self.assertGreater(len(e['shapes']), 0)


class SecondStart(S.TempDir):
    """A second start finds the first through a private file and proves it is talking to it."""

    def setUp(self):
        super().setUp()
        import atlas_app
        from unittest import mock
        self.state = os.path.join(self.tmp, 'state', 'running.json')
        p = mock.patch.object(atlas_app, 'state_file', lambda: self.state)
        p.start()
        self.addCleanup(p.stop)
        self.app = atlas_app.App(self.tmp, S.quiet)
        from atlas_view import start_server
        self.srv = start_server(S.free_port(), S.quiet, app=self.app)
        self.app.server = self.srv
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def test_the_state_file_is_the_users_own(self):
        import atlas_app
        atlas_app.write_state(self.srv)
        st = atlas_app.read_state()
        self.assertEqual((st['port'], st['token']), (self.srv.server_port, self.srv.token))
        if os.name == 'posix':
            self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(self.state)).st_mode & 0o077, 0)
        atlas_app.clear_state(self.srv)
        self.assertIsNone(atlas_app.read_state())

    def test_only_the_app_that_has_the_token_is_taken_for_the_app(self):
        import atlas_app
        self.assertTrue(atlas_app.already_running(self.srv.server_port, self.srv.token))
        self.assertFalse(atlas_app.already_running(self.srv.server_port, 'a-squatter-does-not-know-it'))
        squatter = socket.socket()                                    # something else on a port: never mistaken for it
        squatter.bind(('127.0.0.1', 0))
        squatter.listen()
        self.addCleanup(squatter.close)
        self.assertFalse(atlas_app.already_running(squatter.getsockname()[1], self.srv.token))
        self.assertFalse(atlas_app.already_running(self.srv.server_port), 'no state file: nothing to go by')

    def test_a_stale_state_file_does_not_stop_a_start(self):
        import atlas_app
        atlas_app.write_state(self.srv)
        self.srv.shutdown()
        self.srv.server_close()
        self.assertFalse(atlas_app.already_running(atlas_app.read_state()['port']))

    def test_the_focus_call_needs_the_token(self):
        import atlas_app
        self.assertFalse(atlas_app.focus(self.srv.server_port, 'wrong'))
        self.assertEqual(raw(f'http://127.0.0.1:{self.srv.server_port}', 'POST', '/app/focus', {'Content-Type': 'application/json'}, b'{}')[0], 403)


class LabellingServer(unittest.TestCase):
    """The experiments' labelling page: no CSRF, no script from a file name."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='lunaratlas_label_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, 'gallery'))
        with open(os.path.join(self.tmp, 'gallery', 'a_thumb.jpg'), 'wb') as fh:
            fh.write(b'\xff\xd8jpeg')
        with open(os.path.join(self.tmp, 'quality.json'), 'w') as fh:
            json.dump([dict(key='a', file='/x/<img src=x onerror=alert(1)>.jpg', width=10, height=10)], fh)
        import importlib.util
        spec = importlib.util.spec_from_file_location('label_server', os.path.join(S.PKG, 'experiments', 'quality', 'label_server.py'))
        assert spec and spec.loader
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod.Handler.survey = self.tmp
        self.srv = self.mod.ThreadingHTTPServer(('127.0.0.1', 0), self.mod.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f'http://127.0.0.1:{self.srv.server_port}'

    def test_a_text_plain_post_from_another_site_writes_nothing(self):
        for hdr in ({'Content-Type': 'text/plain'}, {'Content-Type': 'application/json', 'Origin': 'https://evil.example'},
                    {'Content-Type': 'application/json', 'Host': 'evil.example'}):
            code, _, _ = raw(self.url, 'POST', '/labels.json', hdr, b'{"a": {"verdict": "good"}}')
            self.assertIn(code, (403, 415), hdr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'labels.json')))

    def test_its_own_page_can_still_label(self):
        code, _, _ = raw(self.url, 'POST', '/labels.json', {'Content-Type': 'application/json', 'Origin': self.url},
                         b'{"a": {"verdict": "good"}}')
        self.assertEqual(code, 200)
        self.assertEqual(json.load(open(os.path.join(self.tmp, 'labels.json')))['a']['verdict'], 'good')
        self.assertEqual(raw(self.url, 'GET', '/gallery/a_thumb.jpg')[0], 200)
        self.assertEqual(raw(self.url, 'GET', '/gallery/../quality.json')[0], 404)

    def test_head_and_cross_site_reads_are_refused(self):
        self.assertEqual(raw(self.url, 'HEAD', '/gallery/a_thumb.jpg')[0], 405)
        self.assertEqual(raw(self.url, 'GET', '/items.json', {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_the_page_escapes_file_names(self):
        page = open(os.path.join(S.PKG, 'experiments', 'quality', 'label_page.js'), encoding='utf-8').read()
        html = open(os.path.join(S.PKG, 'experiments', 'quality', 'label_page.html'), encoding='utf-8').read()
        self.assertIn('esc(t.name)', page)
        self.assertNotIn('${t.name}', page)
        self.assertNotIn('<script>', html)


class Downloads(S.TempDir):
    """A download is https only, the expected bytes, and not larger than expected."""

    def test_only_https(self):
        for url in ('http://example.com/x', 'ftp://example.com/x', 'file:///etc/hosts'):
            with self.subTest(url), self.assertRaises(urllib.error.URLError):
                https_open(url)
        with self.assertRaises(urllib.error.URLError):
            download('http://127.0.0.1:9/f', os.path.join(self.tmp, 'f'), lambda p: True)
        with self.assertRaises(urllib.error.URLError):
            https_open('https://evil.example/f')             # https, but not a host it downloads from
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_redirect_off_tls_or_off_the_allowed_hosts_is_refused(self):
        # claude-findings.md C-29: a redirect used to be checked for https only, so an allowed host redirecting to
        # a different one (an S3 bucket, a CDN frontier) would have its target fetched and accepted unpinned
        from atlas_geo import DOWNLOAD_HOSTS, _HttpsOnly
        h = _HttpsOnly()
        allowed = next(iter(DOWNLOAD_HOSTS))
        req = urllib.request.Request(f'https://{allowed}/a')
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(req, io.BytesIO(), 302, 'Found', {}, f'http://{allowed}/b')            # off https
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(req, io.BytesIO(), 302, 'Found', {}, 'https://evil.example/b')  # https, wrong host
        self.assertIsNotNone(h.redirect_request(req, io.BytesIO(), 302, 'Found', {}, f'https://{allowed}/b'))

    def test_the_checksum_and_the_size_are_enforced(self):
        payload = b'lunar' * 1000
        good = __import__('hashlib').sha256(payload).hexdigest()

        class Fake:
            def __init__(self, data): self.data, self.headers = io.BytesIO(data), {'Content-Length': str(len(data))}
            def read(self, n=-1): return self.data.read(n)
            def __enter__(self): return self
            def __exit__(self, *a): return False
        import atlas_geo
        old = atlas_geo.https_open
        atlas_geo.https_open = lambda url, timeout=60: Fake(payload)
        self.addCleanup(setattr, atlas_geo, 'https_open', old)
        dest = os.path.join(self.tmp, 'f.bin')
        download('https://x/f', dest, lambda p: True, sha256=good, max_bytes=10_000)
        self.assertEqual(open(dest, 'rb').read(), payload)
        os.remove(dest)
        with self.assertRaises(SystemExit) as cm:
            download('https://x/f', dest, lambda p: True, sha256='0' * 64)
        self.assertIn('checksum', str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            download('https://x/f', dest, lambda p: True, max_bytes=100)
        self.assertIn('larger', str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [], 'nothing left behind, and nothing accepted')

    def test_the_pins_are_the_files_this_machine_has(self):
        import atlas_closeup
        import atlas_geo
        for tile, digest in atlas_geo.REF_SHA256.items():
            f = os.path.join(S.DATA, 'wac_emp_643', f'WAC_EMP_643NM_{tile}_064P.TIF')
            if os.path.exists(f):
                self.assertEqual(sha256_file(f), digest, tile)
        self.assertEqual(set(atlas_geo.REF_SHA256), set(atlas_geo.REF_TILES))
        self.assertEqual(set(atlas_closeup.LOLA_SHA256), {16, 64})

    def test_the_gazetteer_archive_gives_up_only_its_table(self):
        import atlas_names
        z = os.path.join(self.tmp, 'gaz.zip')
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr('MOON_nomenclature_center_pts.dbf', b'table')
            zf.writestr('evil.py', b'print(1)')
            zf.writestr('../escape.txt', b'x')
        dest = os.path.join(self.tmp, 'iau')
        os.makedirs(dest)
        old = (atlas_names.GAZ_DIR, atlas_names.GAZ_DBF, atlas_names.download)
        atlas_names.GAZ_DIR, atlas_names.GAZ_DBF = dest, os.path.join(dest, 'MOON_nomenclature_center_pts.dbf')
        atlas_names.download = lambda url, d, valid, **k: shutil.copy(z, d)
        self.addCleanup(lambda: (setattr(atlas_names, 'GAZ_DIR', old[0]), setattr(atlas_names, 'GAZ_DBF', old[1]),
                                 setattr(atlas_names, 'download', old[2])))
        atlas_names._download(S.quiet)
        self.assertEqual(sorted(os.listdir(dest)), ['MOON_nomenclature_center_pts.dbf', 'MOON_nomenclature_center_pts.zip'])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'escape.txt')))


class TemporaryFiles(S.TempDir):
    def test_a_planted_symlink_is_not_written_through(self):
        if os.name != 'posix':
            self.skipTest('symlinks need POSIX')
        victim = os.path.join(self.tmp, 'victim.txt')
        with open(victim, 'w') as fh:
            fh.write('precious')
        dest = os.path.join(self.tmp, 'out.tif')
        for guess in (dest + '.part', os.path.join(self.tmp, 'out.part.tif')):
            os.symlink(victim, guess)
        write_atomic(dest, lambda tmp: open(tmp, 'w').write('new'))
        self.assertEqual(open(victim).read(), 'precious')
        self.assertEqual(open(dest).read(), 'new')

    def test_names_are_unpredictable_and_the_result_has_an_ordinary_mode(self):
        a, b = temp_beside(os.path.join(self.tmp, 'x.png')), temp_beside(os.path.join(self.tmp, 'x.png'))
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith('.png'), 'the extension stays: cv2.imwrite picks the encoder from it')
        dest = os.path.join(self.tmp, 'x.png')
        publish(a, dest)
        if os.name == 'posix':
            self.assertNotEqual(os.stat(dest).st_mode & 0o044, 0, 'readable as a file made in the ordinary way is')
        os.remove(b)

    def test_the_photos_cache_is_private(self):
        if os.name != 'posix':
            self.skipTest('modes need POSIX')
        from atlas_paths import private_dir
        d = os.path.join(self.tmp, 'a', 'b')
        private_dir(d)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)


class HandoffFile(unittest.TestCase):
    """atlas_view.handoff_url: the run's whole-lifetime token must never become a browser process's command-line
    argument (readable by any other local user through /proc on Linux), only the content of a private file."""

    def test_the_token_is_only_in_the_files_content_never_in_the_returned_url(self):
        from atlas_view import handoff_url
        target = 'http://localhost:12345/app?t=SUPER-SECRET-TOKEN&group=x'
        url = handoff_url(target)
        self.assertTrue(url.startswith('file://'), url)
        self.assertNotIn('SUPER-SECRET-TOKEN', url)
        path = url[len('file://'):]
        with open(path, encoding='utf-8') as fh:
            page = fh.read()
        self.assertIn('SUPER-SECRET-TOKEN', page)
        # the URL is HTML-escaped for the attribute it sits in (an unescaped & would end the attribute early)
        self.assertIn('http://localhost:12345/app?t=SUPER-SECRET-TOKEN&amp;group=x', page)
        if os.name == 'posix':
            self.assertEqual(oct(os.stat(path).st_mode)[-3:], '600', 'readable by no one else')

    def test_is_reused_not_left_behind_on_every_open(self):
        from atlas_view import handoff_url
        first = handoff_url('http://localhost:1/a')
        second = handoff_url('http://localhost:1/b')
        self.assertEqual(first, second, 'one file, its content replaced each time, not one per open')


class SomeoneElsesSidecar(S.TempDir):
    def test_a_font_it_names_is_not_downloaded(self):
        from atlas_render import Fonts
        called = []
        import atlas_render
        old = atlas_render.https_open
        atlas_render.https_open = lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError('network'))
        self.addCleanup(setattr, atlas_render, 'https_open', old)
        with self.assertRaises(SystemExit) as cm:
            Fonts('Some Font Nobody Has Xyzzy', S.quiet, download=False)
        self.assertIn('not downloaded', str(cm.exception))
        self.assertEqual(called, [])
        self.assertTrue(Fonts('Roboto', S.quiet, download=False).files, 'the bundled families work offline')

    def test_a_font_listing_cannot_name_other_files_or_hosts(self):
        import atlas_render
        listing = [dict(name='../../evil.ttf', download_url=atlas_render.GOOGLE_FONTS_RAW + 'x'),
                   dict(name='ok.ttf', download_url='http://evil.example/ok.ttf'),
                   dict(name='fine.ttf', download_url=atlas_render.GOOGLE_FONTS_RAW + 'main/ofl/x/fine.ttf')]
        self.assertEqual([e['name'] for e in atlas_render.Fonts._listed(listing + ['junk', dict(name=5)])], ['fine.ttf'])

    def test_an_unusable_google_listing_fails_before_font_rendering(self):
        """GitHub can list a directory, and malformed responses must not create Fonts(files=[])."""
        import atlas_render
        listings = (
            [],
            [dict(name='static', type='dir')],
            [dict(name='not-a-font.txt', download_url=atlas_render.GOOGLE_FONTS_RAW + 'main/ofl/x/not-a-font.txt')],
            dict(message='unexpected object'),
            'unexpected scalar',
        )
        for listing in listings:
            with self.subTest(listing=listing), mock.patch.object(atlas_render, 'FONT_DIR', self.tmp), \
                    mock.patch.object(atlas_render, 'https_open', side_effect=lambda *a, **k: io.BytesIO(json.dumps(listing).encode())):
                with self.assertRaisesRegex(SystemExit, 'no usable .ttf files'):
                    atlas_render.Fonts('Listing Has No Fonts', S.quiet)
        self.assertEqual(atlas_render.Fonts._listed(dict(message='unexpected object')), [])
        self.assertEqual(atlas_render.Fonts._listed('unexpected scalar'), [])


@S.needs_all
class ExplicitOutputName(S.TempDir):
    """-o names a file of the user's choosing: an existing one is not replaced unless they say so."""

    def test_an_existing_target_needs_overwrite_but_the_default_name_is_replaced(self):
        img, _ = S.moon_image(self.tmp)
        out = os.path.join(self.tmp, 'mine.jpg')
        with open(out, 'w') as fh:
            fh.write('precious')
        code, _ = S.run_main('export', img, '-o', out, '--max-size', '200')
        self.assertIn('already exists', str(code))
        self.assertIn('--overwrite', str(code))
        self.assertEqual(open(out).read(), 'precious')
        code, _ = S.run_main('export', img, '-o', out, '--max-size', '200', '--overwrite')
        self.assertIsNone(code)
        self.assertGreater(os.path.getsize(out), 100)
        for _ in range(2):                                            # the default name: re-exporting replaces it
            self.assertIsNone(S.run_main('export', img, '--max-size', '200', '--format', 'jpg')[0])

    def test_a_dangling_symlink_is_not_written_through(self):
        if os.name != 'posix':
            self.skipTest('symlinks need POSIX')
        img, _ = S.moon_image(self.tmp)
        victim = os.path.join(self.tmp, 'victim.txt')
        link = os.path.join(self.tmp, 'link.jpg')
        os.symlink(victim, link)
        code, _ = S.run_main('export', img, '-o', link, '--max-size', '200')
        self.assertIn('already exists', str(code))
        self.assertFalse(os.path.exists(victim))

    def test_the_page_re_exports_over_its_own_name(self):
        from atlas_view import export_command
        cmd, out = export_command(os.path.join(self.tmp, 'moon.tif'), {})
        self.assertEqual(cmd[-3:], ['--overwrite', '-o', out])


class ReleaseInputs(unittest.TestCase):
    """What goes into a release is pinned: the actions, the wheels, the way the app is signed."""
    ROOT = S.ROOT

    def workflows(self):
        d = os.path.join(self.ROOT, '.github', 'workflows')
        return {n: open(os.path.join(d, n), encoding='utf-8').read() for n in sorted(os.listdir(d)) if n.endswith('.yml')}

    def test_every_action_is_pinned_to_a_commit(self):
        import re
        for name, text in self.workflows().items():
            uses = re.findall(r'^\s*-?\s*uses:\s*(\S+)', text, re.M)
            self.assertTrue(uses, name)
            for u in uses:
                self.assertRegex(u, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$', f'{name}: {u} is a movable tag')

    def test_the_token_can_only_read_except_in_the_release_job(self):
        import re
        for name, text in self.workflows().items():
            head = text.split('\njobs:')[0]
            self.assertRegex(head, r'(?m)^permissions:\n  contents: read', f'{name}: no top-level read-only permissions')
            self.assertNotRegex(head, r'contents: write', name)
        build = self.workflows()['build-app.yml']
        writers = re.findall(r'(?m)^  (\w+):\n(?:    .*\n)*?    permissions:\n      contents: write', build)
        self.assertEqual(writers, ['release'])

    def test_installs_check_hashes(self):
        for name, text in self.workflows().items():
            for line in text.splitlines():
                if 'pip install' in line:
                    self.assertIn('--require-hashes', line, f'{name}: {line.strip()}')
                    self.assertRegex(line, r'-r [\w./-]*requirements[\w./-]*\.lock', line)

    def test_the_lock_files_pin_every_package_with_hashes(self):
        import re
        for lock in ('requirements.lock', 'requirements-ci.lock', os.path.join('packaging', 'requirements-build.lock')):
            text = open(os.path.join(self.ROOT, lock), encoding='utf-8').read()
            entries = re.findall(r'(?m)^([A-Za-z0-9_.-]+)==([\w.]+)', text)
            self.assertGreater(len(entries), 2, lock)
            for name, _ in entries:
                block = re.search(rf'(?ms)^{re.escape(name)}==.*?(?=^\S|\Z)', text)
                self.assertIsNotNone(block and re.search(r'--hash=sha256:[0-9a-f]{64}', block[0]), f'{lock}: {name} has no hash')
        runtime = open(os.path.join(self.ROOT, 'requirements.lock'), encoding='utf-8').read()
        for pkg in ('numpy', 'opencv-python-headless', 'pillow'):
            self.assertRegex(runtime, rf'(?m)^{pkg}==', pkg)
        self.assertRegex(open(os.path.join(self.ROOT, 'packaging', 'requirements-build.lock')).read(), r'(?m)^pyinstaller==')

    def test_the_release_lists_checksums(self):
        self.assertIn('SHA256SUMS.txt', self.workflows()['build-app.yml'])

    def test_macos_signing_goes_inside_out_and_not_deep(self):
        import importlib.util
        src = os.path.join(self.ROOT, 'packaging', 'build.py')
        spec = importlib.util.spec_from_file_location('build_app', src)
        assert spec and spec.loader
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        tmp = tempfile.mkdtemp(prefix='lunaratlas_app_')
        self.addCleanup(shutil.rmtree, tmp, True)
        app = os.path.join(tmp, 'X.app')
        for d in ('Contents/MacOS', 'Contents/Frameworks/Y.framework/Versions/A', 'Contents/Resources/lib'):
            os.makedirs(os.path.join(app, d))
        macho = b'\xcf\xfa\xed\xfe' + b'0' * 8
        for f in ('Contents/MacOS/X', 'Contents/Frameworks/Y.framework/Versions/A/Y', 'Contents/Resources/lib/z.so'):
            open(os.path.join(app, f), 'wb').write(macho)
        for f in ('Contents/Info.plist', 'Contents/Resources/data.json'):
            open(os.path.join(app, f), 'wb').write(b'<plist>')
        # os.path.relpath uses the native separator; this checks the macOS bundle-signing order algorithm, not
        # path formatting, so compare with '/' regardless of the host running the test
        order = [os.path.relpath(p, app).replace(os.sep, '/') for p in build.signables(app)]
        self.assertEqual(sorted(order), sorted(['Contents/MacOS/X', 'Contents/Frameworks/Y.framework/Versions/A/Y',
                                                'Contents/Frameworks/Y.framework', 'Contents/Resources/lib/z.so']))
        self.assertLess(order.index('Contents/Frameworks/Y.framework/Versions/A/Y'), order.index('Contents/Frameworks/Y.framework'),
                        'a framework is sealed after what is inside it')
        self.assertNotIn('--deep', open(src, encoding='utf-8').read().replace("(codesign --deep", ''))

    def test_the_certificates_of_the_packaged_app_are_not_overridable(self):
        text = open(os.path.join(self.ROOT, 'packaging', 'launcher.py'), encoding='utf-8').read()
        self.assertNotIn("os.environ.setdefault('SSL_CERT_FILE'", text)
        self.assertIn("os.environ['SSL_CERT_FILE'] = certifi.where()", text)


if __name__ == '__main__':
    unittest.main()
