"""What differs per platform and per way of running, checked on any one machine.

A CI runner only takes its own platform's branch; these tests take every branch (macOS, Windows, Linux; checkout and
packaged app; app window and browser) by standing in for sys.platform, the environment and pywebview, so a slip in
the Windows folder is caught on a Mac and the other way round.
"""
import argparse
import importlib.util
import os
import shutil
import sys
import threading
import time
import unittest
from unittest import mock

import _support as S

import atlas_app
import atlas_paths
import atlas_view

LAUNCHER = os.path.join(S.ROOT, 'packaging', 'launcher.py')


class Folders(unittest.TestCase):
    """Where the reference data, the cache and the log go, as the packaging README promises."""

    def user_dir(self, platform, kind, env=None, home='/home/ann'):
        with mock.patch.object(sys, 'platform', platform), mock.patch.dict(os.environ, env or {}, clear=False), \
                mock.patch('os.path.expanduser', lambda p: p.replace('~', home, 1)):
            for k in ('LOCALAPPDATA', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
                if k not in (env or {}):
                    os.environ.pop(k, None)
            return atlas_paths.user_dir(kind)

    def test_macos(self):
        self.assertEqual(self.user_dir('darwin', 'data', home='/Users/ann'),
                         os.path.join('/Users/ann', 'Library', 'Application Support', 'LunarAtlas'))
        self.assertEqual(self.user_dir('darwin', 'cache', home='/Users/ann'),
                         os.path.join('/Users/ann', 'Library', 'Caches', 'LunarAtlas'))

    def test_windows(self):
        env = {'LOCALAPPDATA': r'C:\Users\ann\AppData\Local'}
        self.assertEqual(self.user_dir('win32', 'data', env), os.path.join(env['LOCALAPPDATA'], 'LunarAtlas', 'Data'))
        self.assertEqual(self.user_dir('win32', 'cache', env), os.path.join(env['LOCALAPPDATA'], 'LunarAtlas', 'Cache'))
        self.assertEqual(self.user_dir('win32', 'data', home=r'C:\Users\ann'),
                         os.path.join(r'C:\Users\ann', 'AppData', 'Local', 'LunarAtlas', 'Data'),
                         'without LOCALAPPDATA: the usual place under the profile')

    def test_linux_follows_xdg(self):
        self.assertEqual(self.user_dir('linux', 'data'), os.path.join('/home/ann', '.local', 'share', 'lunaratlas'))
        self.assertEqual(self.user_dir('linux', 'cache'), os.path.join('/home/ann', '.cache', 'lunaratlas'))
        env = {'XDG_DATA_HOME': '/data/ann', 'XDG_CACHE_HOME': '/scratch/ann'}
        self.assertEqual(self.user_dir('linux', 'data', env), os.path.join('/data/ann', 'lunaratlas'))
        self.assertEqual(self.user_dir('linux', 'cache', env), os.path.join('/scratch/ann', 'lunaratlas'))

    def test_the_work_folder_is_in_pictures_when_there_is_one(self):
        with S.tempfile.TemporaryDirectory() as home, mock.patch('os.path.expanduser', lambda p: p.replace('~', home, 1)):
            self.assertEqual(atlas_app.work_folder(), os.path.join(home, 'LunarAtlas'))
            os.makedirs(os.path.join(home, 'Pictures'))
            self.assertEqual(atlas_app.work_folder(), os.path.join(home, 'Pictures', 'LunarAtlas'))


class SelfCommand(S.TempDir):
    """How the app runs locate and export in a process of their own."""

    def test_from_a_checkout_python_runs_lunaratlas_py(self):
        cmd = atlas_paths.self_command('locate', 'x.tif')
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(os.path.basename(cmd[1]), 'lunaratlas.py')
        self.assertTrue(os.path.exists(cmd[1]))
        self.assertEqual(cmd[2:], ['locate', 'x.tif'])

    def packaged(self, platform, with_cli):
        exe = os.path.join(self.tmp, 'LunarAtlas.exe' if platform == 'win32' else 'LunarAtlas')
        cli = os.path.join(self.tmp, 'lunaratlas-cli' + ('.exe' if platform == 'win32' else ''))
        if with_cli:
            open(cli, 'w').close()
        with mock.patch.object(atlas_paths, 'FROZEN', True), mock.patch.object(sys, 'executable', exe), \
                mock.patch.object(sys, 'platform', platform):
            return atlas_paths.self_command('export', 'x.tif'), exe, cli

    def test_the_packaged_app_runs_its_console_twin(self):
        for platform in ('darwin', 'win32', 'linux'):
            with self.subTest(platform):
                cmd, _, cli = self.packaged(platform, True)
                self.assertEqual(cmd, [cli, 'export', 'x.tif'])

    def test_without_the_twin_the_app_runs_itself(self):
        cmd, exe, _ = self.packaged('linux', False)
        self.assertEqual(cmd, [exe, 'export', 'x.tif'])


class Reveal(unittest.TestCase):
    """"Show in Finder / Explorer / the file manager"."""

    def reveal(self, platform, path):
        with mock.patch.object(sys, 'platform', platform), mock.patch.object(atlas_view.subprocess, 'Popen') as p:
            atlas_view.reveal(path)
        return p.call_args[0][0]

    def test_each_platform_opens_its_own_file_manager(self):
        self.assertEqual(self.reveal('darwin', '/a/b.png'), ['open', '-R', '/a/b.png'])
        self.assertEqual(self.reveal('win32', '/a/b.png'), ['explorer', '/select,' + os.path.normpath('/a/b.png')])
        self.assertEqual(self.reveal('linux', '/a/b.png'), ['xdg-open', os.path.dirname(os.path.abspath('/a/b.png'))])

    def test_no_file_manager_is_not_an_error(self):
        with mock.patch.object(sys, 'platform', 'linux'), \
                mock.patch.object(atlas_view.subprocess, 'Popen', side_effect=FileNotFoundError('xdg-open')):
            atlas_view.reveal('/a/b.png')          # a headless box: the export still succeeded


class PackagedEntryPoint(S.TempDir):
    """packaging/launcher.py: a double-click opens the launcher, a subcommand runs that command."""

    def launcher(self):
        spec = importlib.util.spec_from_file_location('lunaratlas_launcher', LAUNCHER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def run_main(self, argv, tty=True):
        mod = self.launcher()
        out = mock.Mock(isatty=lambda: tty)
        with mock.patch.object(sys, 'argv', ['LunarAtlas', *argv]), mock.patch('lunaratlas.main') as main, \
                mock.patch.object(sys, 'stdout', out), mock.patch.object(sys, 'stderr', out), \
                mock.patch.object(atlas_paths, 'user_dir', lambda kind: os.path.join(self.tmp, kind)):
            mod.main()
            logged = sys.stdout
        return main.call_args[0][0], logged

    def test_a_subcommand_runs_that_command(self):
        args, _ = self.run_main(['locate', 'moon.tif'])
        self.assertEqual(args, ['locate', 'moon.tif'])

    def test_batch_runs_that_command(self):
        """batch was added to the CLI after the launcher's own command list; regression for it being missed again."""
        args, _ = self.run_main(['batch', 'folder'])
        self.assertEqual(args, ['batch', 'folder'])

    def test_every_cli_subcommand_is_routed_directly(self):
        """lunaratlas.COMMANDS (what the launcher treats as a command, not as arguments to `app`) matches every
        sub-parser lunaratlas.main() actually builds, so a new subcommand cannot be missed here again."""
        import lunaratlas
        p = argparse.ArgumentParser()
        real_add_subparsers = argparse.ArgumentParser.add_subparsers
        names = []

        def spy(self, *a, **k):
            sub = real_add_subparsers(self, *a, **k)
            real_add_parser = sub.add_parser

            def add_parser(name, *a, **k):
                names.append(name)
                return real_add_parser(name, *a, **k)
            sub.add_parser = add_parser
            return sub
        with mock.patch.object(argparse.ArgumentParser, 'add_subparsers', spy):
            with self.assertRaises(SystemExit):        # required=True: no subcommand given
                lunaratlas.main([])
        self.assertEqual(set(names), set(lunaratlas.COMMANDS))

    def test_a_double_click_opens_the_launcher_that_stops_by_itself(self):
        args, _ = self.run_main([])
        self.assertEqual(args, ['app', '--idle-exit', '180'])

    def test_finders_process_serial_number_is_ignored(self):
        args, _ = self.run_main(['-psn_0_12345'])
        self.assertEqual(args, ['app', '--idle-exit', '180'])

    def test_without_a_terminal_the_output_goes_to_the_log(self):
        _, logged = self.run_main([], tty=False)
        try:
            self.assertEqual(logged.name, os.path.join(self.tmp, 'data', 'lunaratlas.log'))
        finally:
            logged.close()

    def test_downloads_use_the_bundled_certificates(self):
        try:
            import certifi
        except ImportError:
            self.skipTest('certifi not installed')
        with mock.patch.dict(os.environ):
            os.environ.pop('SSL_CERT_FILE', None)
            self.launcher().certificates()
            self.assertEqual(os.environ['SSL_CERT_FILE'], certifi.where())


NOTICES = os.path.join(S.ROOT, 'packaging', 'notices.py')


class PackagingNotices(S.TempDir):
    """packaging/notices.py: third-party licence texts collected for a build, and the GPL-codec guard (C-12)."""

    def notices(self):
        spec = importlib.util.spec_from_file_location('lunaratlas_notices', NOTICES)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_collects_a_licence_for_every_wanted_distribution_that_is_installed(self):
        n = self.notices()
        out = os.path.join(self.tmp, 'THIRD-PARTY-NOTICES.txt')
        n.collect(out)
        with open(out, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('Python', text)                    # always included, whether or not it is installed as a dist
        for name in ('numpy', 'certifi'):                 # both are always installed for the test suite to run
            try:
                import importlib.metadata as im
                version = im.distribution(name).version
            except im.PackageNotFoundError:
                continue
            self.assertIn(f'{name} {version}', text)

    def test_finds_forbidden_gpl_codec_libraries(self):
        n = self.notices()
        for name in ('libx264.164.dylib', 'x265.dll', 'libpostproc.so.58'):
            open(os.path.join(self.tmp, name), 'w').close()
        open(os.path.join(self.tmp, 'libavcodec.dylib'), 'w').close()      # not itself forbidden
        hits = n.find_forbidden(self.tmp)
        self.assertEqual(len(hits), 3)
        with self.assertRaises(SystemExit):
            n.check_forbidden(self.tmp)

    def test_a_clean_folder_passes(self):
        n = self.notices()
        open(os.path.join(self.tmp, 'libavcodec.dylib'), 'w').close()
        n.check_forbidden(self.tmp)                       # must not raise


BUILD = os.path.join(S.ROOT, 'packaging', 'build.py')


class PackagingSeal(S.TempDir):
    """packaging/build.py: the .app is sealed again after the build wrote files into it (C-28).

    PyInstaller ad-hoc signs the bundle; writing THIRD-PARTY-NOTICES.txt into Contents/Resources afterwards
    adds a file the seal does not cover. A quarantined app whose seal does not validate is refused outright
    ("LunarAtlas is damaged"), with no "Open Anyway" to allow it, so this must hold for unsigned builds too.
    """

    def build(self):
        spec = importlib.util.spec_from_file_location('lunaratlas_build', BUILD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_an_unsigned_build_is_still_sealed_ad_hoc_and_verified(self):
        b = self.build()
        with mock.patch.object(b, 'run') as run:
            b.seal_macos('/tmp/LunarAtlas.app', None)
        calls = [c.args for c in run.call_args_list]
        self.assertEqual(calls[0], ('codesign', '--force', '--sign', '-', '/tmp/LunarAtlas.app'))
        self.assertIn('--verify', calls[-1])              # a broken seal must fail the build, not ship
        self.assertIn('--strict', calls[-1])
        for c in calls:                                   # neither needs, nor may have, an identity
            self.assertNotIn('--timestamp', c)
            self.assertNotIn('--options', c)

    def test_a_signed_build_seals_the_app_last_and_verifies(self):
        b = self.build()
        with mock.patch.object(b, 'run') as run, \
             mock.patch.object(b, 'signables', return_value=['/tmp/LunarAtlas.app/Contents/MacOS/python']):
            b.seal_macos('/tmp/LunarAtlas.app', 'Developer ID Application: Someone')
        calls = [c.args for c in run.call_args_list]
        self.assertEqual(calls[0][-1], '/tmp/LunarAtlas.app/Contents/MacOS/python')   # innermost first
        self.assertEqual(calls[1][-1], '/tmp/LunarAtlas.app')                         # the bundle last
        for c in calls[:-1]:
            self.assertIn('--timestamp', c)
        self.assertIn('--verify', calls[-1])


class PackagingWindowsSigning(S.TempDir):
    """packaging/build.py: Authenticode signing is optional, timestamped, and never prints the password.

    Unsigned is a supported outcome (SmartScreen then warns about the publisher), so no certificate must not
    fail the build; but a certificate that is given must actually be used, and must be timestamped, or the
    signature stops being trusted the day it expires.
    """

    def build(self):
        spec = importlib.util.spec_from_file_location('lunaratlas_build_win', BUILD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_no_certificate_leaves_the_build_unsigned_without_failing(self):
        b = self.build()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(b, 'run') as run:
            b.sign_windows(['LunarAtlas.exe'])
        run.assert_not_called()

    def test_a_certificate_signs_every_file_and_timestamps_it(self):
        b = self.build()
        with mock.patch.dict(os.environ, {'WINDOWS_SIGN_SHA1': 'AABB'}, clear=True), \
             mock.patch.object(b, 'run') as run, mock.patch.object(b, 'signtool', return_value='signtool.exe'):
            b.sign_windows(['A.exe', 'B.exe'])
        calls = [c.args for c in run.call_args_list]
        self.assertEqual([c[-1] for c in calls[:2]], ['A.exe', 'B.exe'])
        for c in calls[:2]:
            self.assertIn('/tr', c)                       # timestamped, or it expires with the certificate
            self.assertIn('/sha1', c)
        self.assertEqual(calls[-1][1], 'verify')          # a signature that did not take must fail the build

    def test_the_password_is_never_printed(self):
        b = self.build()
        env = {'WINDOWS_SIGN_PFX': 'c.pfx', 'WINDOWS_SIGN_PASSWORD': 'hunter2'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(b.subprocess, 'run'), mock.patch.object(b, 'signtool', return_value='signtool.exe'), \
             mock.patch('builtins.print') as printed:
            b.sign_windows(['A.exe'])
        shown = ' '.join(str(a) for c in printed.call_args_list for a in c.args)
        self.assertNotIn('hunter2', shown)                # build logs are public
        self.assertIn('***', shown)


class Startup(S.TempDir):
    """atlas_app.run: an app window when pywebview is there, else the browser; a second start hands over."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(atlas_app, 'state_file', lambda: os.path.join(self.tmp + '-state', 'running.json'))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp + '-state', True)

    def fake_webview(self):
        wv = mock.Mock()
        wv.create_window.return_value = mock.Mock()
        return wv

    def test_the_app_window_and_closing_it_stops_everything(self):
        wv, logs = self.fake_webview(), []
        with mock.patch.object(atlas_app, 'webview_module', return_value=wv):
            atlas_app.run(port=S.free_port(), folder=self.tmp, log=logs.append)
        url = wv.create_window.call_args[0][1]
        self.assertRegex(url, r'^http://localhost:\d+/app\?t=[\w-]{20,}$', 'the window opens the token link')
        wv.start.assert_called_once()
        self.assertIn('window closed: stopping', logs)
        port = int(url.split(':')[2].split('/')[0])
        self.assertFalse(atlas_app.already_running(port), 'the server stopped with the window')
        self.assertIsNone(atlas_app.read_state(), 'and took its state file with it')

    def test_no_pywebview_means_the_browser(self):
        logs = []
        with mock.patch.object(atlas_app, 'webview_module', return_value=None), \
                mock.patch.object(atlas_app, 'run_server') as rs:
            atlas_app.run(port=S.free_port(), folder=self.tmp, log=logs.append, window=True)
        self.assertTrue(any('pywebview is not installed' in l for l in logs), logs)
        self.assertEqual(rs.call_args.kwargs['path'], '/app')

    def test_a_second_start_hands_over_to_the_first(self):
        app = atlas_app.App(self.tmp, S.quiet)
        srv = atlas_view.start_server(S.free_port(), S.quiet, app=app)
        app.server = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        logs = []
        atlas_app.write_state(srv)
        with mock.patch.object(atlas_app.webbrowser, 'open') as wb:
            atlas_app.run(port=srv.server_port, log=logs.append)
        self.assertTrue(logs and logs[0].startswith('already running'), logs)
        # the token no longer reaches the browser's own command line (claude-findings.md C-07): a private redirect
        # file is opened instead, and only its content carries the real, token-bearing address
        wb.assert_called_once()
        handoff_url = wb.call_args[0][0]
        self.assertTrue(handoff_url.startswith('file://'), handoff_url)
        self.assertNotIn(srv.token, handoff_url, "the token must not be in the browser's argv")
        with open(handoff_url[len('file://'):], encoding='utf-8') as fh:
            page = fh.read()
        self.assertIn(f'http://localhost:{srv.server_port}/app?t={srv.token}', page)
        if os.name == 'posix':
            self.assertEqual(oct(os.stat(handoff_url[len('file://'):]).st_mode)[-3:], '600', 'private: this user only')

    def test_the_browser_launcher_stops_when_no_page_is_left(self):
        app = atlas_app.App(self.tmp, S.quiet)
        srv = atlas_view.start_server(S.free_port(), S.quiet, app=app)
        app.server = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        app.seen = time.monotonic() - 10
        logs = []
        atlas_app.idle_exit(app, srv, 0.05, logs.append)
        t0 = time.time()
        while time.time() - t0 < 5 and atlas_app.already_running(srv.server_port, srv.token):
            time.sleep(0.05)
        self.assertFalse(atlas_app.already_running(srv.server_port, srv.token))
        self.assertTrue(any('stopping' in l for l in logs), logs)


class ExclusiveListeningSockets(unittest.TestCase):
    """bugs-overview BUG-12: SO_REUSEADDR (inherited as allow_reuse_address=True) has weaker semantics on
    Windows than on POSIX and can let a second process bind a port the first one is still actively listening
    on. Windows verification pending -- a mocked fake socket proves the option ordering and POSIX's own
    behaviour is unaffected, but the actual OS-level consequence has not been reproduced on this Mac."""

    class FakeSocket:
        def __init__(self):
            self.calls = []

        def setsockopt(self, *a):
            self.calls.append(('setsockopt', a))

        def bind(self, addr):
            self.calls.append(('bind', addr))

        def getsockname(self):
            return ('127.0.0.1', 12345)

    def server_bind(self, platform):
        srv = atlas_view.Server.__new__(atlas_view.Server)
        srv.socket = self.FakeSocket()
        srv.server_address = ('127.0.0.1', 12345)
        srv.allow_reuse_address = True            # as HTTPServer sets it
        with mock.patch.object(sys, 'platform', platform), \
                mock.patch.object(atlas_view.socket, 'SO_EXCLUSIVEADDRUSE', 99, create=True):
            srv.server_bind()
        return srv

    def test_windows_sets_exclusive_before_bind_and_disables_reuse(self):
        srv = self.server_bind('win32')
        self.assertFalse(srv.allow_reuse_address, 'the stdlib must not also set SO_REUSEADDR')
        names = [c[0] for c in srv.socket.calls]
        self.assertEqual(names[0], 'setsockopt', 'the exclusive option is set before bind()')
        self.assertIn('bind', names)
        self.assertLess(names.index('setsockopt'), names.index('bind'))
        opt_call = next(c for c in srv.socket.calls if c[0] == 'setsockopt')
        self.assertEqual(opt_call[1], (atlas_view.socket.SOL_SOCKET, 99, 1))

    def test_posix_is_unaffected(self):
        srv = self.server_bind('darwin')
        self.assertTrue(srv.allow_reuse_address, 'POSIX behaviour (SO_REUSEADDR) is unchanged')
        # TCPServer.server_bind() itself sets SO_REUSEADDR here (allow_reuse_address stayed True); this
        # override's own Windows-only branch did not run and did not add a second setsockopt call
        opts = [c[1] for c in srv.socket.calls if c[0] == 'setsockopt']
        self.assertEqual(opts, [(atlas_view.socket.SOL_SOCKET, atlas_view.socket.SO_REUSEADDR, 1)])


if __name__ == '__main__':
    unittest.main()
