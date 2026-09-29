"""What differs per platform and per way of running, checked on any one machine.

A CI runner only takes its own platform's branch; these tests take every branch (macOS, Windows, Linux; checkout and
packaged app; app window and browser) by standing in for sys.platform, the environment and pywebview, so a slip in
the Windows folder is caught on a Mac and the other way round.
"""
import importlib.util
import os
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


class Startup(S.TempDir):
    """atlas_app.run: an app window when pywebview is there, else the browser; a second start hands over."""

    def fake_webview(self):
        wv = mock.Mock()
        wv.create_window.return_value = mock.Mock()
        return wv

    def test_the_app_window_and_closing_it_stops_everything(self):
        wv, logs = self.fake_webview(), []
        with mock.patch.object(atlas_app, 'webview_module', return_value=wv):
            atlas_app.run(port=S.free_port(), folder=self.tmp, log=logs.append)
        url = wv.create_window.call_args[0][1]
        self.assertRegex(url, r'^http://localhost:\d+/app$')
        wv.start.assert_called_once()
        self.assertIn('window closed: stopping', logs)
        port = int(url.split(':')[2].split('/')[0])
        self.assertFalse(atlas_app.already_running(port), 'the server stopped with the window')

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
        with mock.patch.object(atlas_app.webbrowser, 'open') as wb:
            atlas_app.run(port=srv.server_port, log=logs.append)
        self.assertTrue(logs and logs[0].startswith('already running'), logs)
        wb.assert_called_once_with(f'http://localhost:{srv.server_port}/app')

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
        while time.time() - t0 < 5 and atlas_app.already_running(srv.server_port):
            time.sleep(0.05)
        self.assertFalse(atlas_app.already_running(srv.server_port))
        self.assertTrue(any('stopping' in l for l in logs), logs)


if __name__ == '__main__':
    unittest.main()
