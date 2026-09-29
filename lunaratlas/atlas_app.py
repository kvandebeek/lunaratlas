"""`lunaratlas.py app`: the launcher for people who do not use a terminal (also what the packaged app runs).

The browser page (viewer/app.html) takes an image, copies it into the work folder (~/Pictures/LunarAtlas), runs
`lunaratlas.py locate` on it in its own process with the progress on the page, and then opens it in the viewer on the
same server. The work folder keeps the copies with their sidecars and exports, so an image located once opens at once.

A browser hands over a file's bytes, never its path: hence the copy. A capture time the name does not carry (the
SharpCap / WinJUPOS stamp that close-ups need) is asked on the page and written into the copy's name.

The page shows in an app window of its own when pywebview is there (WebKit on macOS, Edge WebView2 on Windows): closing
the window stops everything. Otherwise it opens in the browser, and the launcher stops by itself a few minutes after
the last page was closed (the pages ping it), so nothing is left running unseen.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
import http.client
import webbrowser
from datetime import datetime

import cv2
import numpy as np

from atlas_ephem import SHARPCAP
from atlas_geo import load_geo, sidecar_path
from atlas_paths import CACHE, private_dir, publish, self_command, temp_beside, user_dir
from atlas_view import PAGE, ExportJob, Server, Session, reveal, run_server, start_server

IMAGE_EXT = ('.tif', '.tiff', '.png', '.jpg', '.jpeg')
PING = b'lunaratlas'
MAX_UPLOAD = 4 << 30                           # one photo: mosaics of hundreds of MB are real, 4 GB is not a photo
SPARE = 200 << 20                              # disk space an upload leaves free


def work_folder():
    home = os.path.expanduser('~')
    pics = os.path.join(home, 'Pictures')
    return os.path.join(pics if os.path.isdir(pics) else home, 'LunarAtlas')


def copy_name(name, when):
    """A safe file name for the copy; with when ('YYYY-MM-DDTHH:MM', UTC) and no time in the name, the SharpCap stamp
    in front."""
    base = os.path.basename(name.replace('\\', '/'))
    stem, ext = os.path.splitext(base)
    if ext.lower() not in IMAGE_EXT:
        raise ValueError(f'{base}: not a TIFF, PNG or JPEG image')
    stem = re.sub(r'[^\w.\- ]+', '_', stem).strip(' .') or 'image'
    if when and not SHARPCAP.search(stem):
        t = datetime.strptime(when, '%Y-%m-%dT%H:%M')
        stem = f'{t:%Y-%m-%d-%H%M}_0-{stem}'
    return stem + ext.lower()


class App:
    def __init__(self, folder, log):
        self.folder, self.log = folder, log
        self.phase, self.path, self.error, self.job = 'idle', None, None, None
        self.cancelled = False
        self.lines: list[str] = []
        self.server: Server | None = None
        self.window = None                          # the pywebview window, when there is one
        self.seen = time.monotonic()                # last request from a page (browser mode: the idle exit)

    def say(self, *a):
        line = ' '.join(str(x) for x in a)
        self.lines.append(line)
        self.log(line)

    # ------------------------------------------------------------ routes
    def get(self, h, p):
        self.seen = time.monotonic()
        if p == '/app/ping':
            h.reply(PING, 'text/plain')
        elif p == '/app' or (p in ('/', '/index.html') and h.srv.session is None):
            h.file(os.path.join(PAGE, 'app.html'), 'text/html; charset=utf-8')
        elif p == '/app/status':
            h.json(self.status())
        elif p == '/app/recent':
            h.json(dict(folder=self.folder, images=self.recent()))
        elif p == '/app/thumb':
            self.thumb(h)
        else:
            return False
        return True

    def post(self, h, p):
        if p == '/app/upload':
            self.upload(h)
        elif p in ('/app/locate', '/app/open'):
            try:
                o = h.body()
                path = self.inside(o.get('path'))
            except (ValueError, AttributeError) as e:
                return h.json(dict(error=str(e)), 400) or True
            if self.phase in ('locating', 'opening'):
                return h.json(dict(error='busy with another image'), 409) or True
            self.path, self.error, self.lines = path, None, []
            if p == '/app/locate':
                self.locate(path, bool(o.get('force')))
            else:
                self.open(path)
            h.json(dict(ok=True))
        elif p == '/app/folder':
            os.makedirs(self.folder, exist_ok=True)
            reveal(self.folder)
            h.json(dict(ok=True))
        elif p == '/app/cancel':
            h.json(dict(ok=self.cancel()))
        elif p == '/app/quit':
            h.json(dict(ok=True))
            self.quit()
        elif p == '/app/focus':                        # a second start: bring the window forward instead
            if self.window is not None:
                self.window.restore()
                self.window.show()
            h.json(dict(window=self.window is not None))
        else:
            return False
        return True

    def inside(self, path):
        """path, only when it is an image in the work folder (the page cannot name any other file)."""
        if not isinstance(path, str):
            raise ValueError('no image given')
        p = os.path.realpath(path)
        if os.path.dirname(p) != os.path.realpath(self.folder) or not os.path.isfile(p) \
                or os.path.splitext(p)[1].lower() not in IMAGE_EXT:
            raise ValueError('not an image in the work folder')
        return p

    # ------------------------------------------------------------ steps
    def upload(self, h):
        """The request body is the file itself (no form encoding), written in pieces: mosaics are hundreds of MB."""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(h.path).query)
        try:
            n = h.length(MAX_UPLOAD)
            name = copy_name(q.get('name', [''])[0], q.get('time', [''])[0])
        except ValueError as e:
            return h.json(dict(error=str(e) or 'bad upload'), 413 if 'Content-Length' in str(e) else 400)
        os.makedirs(self.folder, exist_ok=True)
        if shutil.disk_usage(self.folder).free < n + SPARE:
            return h.json(dict(error='not enough free disk space for this image'), 507)
        dest = os.path.join(self.folder, name)
        stem, ext = os.path.splitext(dest)
        k = 2
        while os.path.exists(dest) and os.path.getsize(dest) != n:      # same name, other file: keep both
            dest, k = f'{stem} ({k}){ext}', k + 1
        if os.path.exists(dest):                                        # the same file again: its sidecar is reused
            self.drain(h.rfile, n)
            return h.json(dict(path=dest, located=self.located(dest), name=os.path.basename(dest)))
        try:
            tmp = temp_beside(dest, '.part')
        except OSError as e:
            return h.json(dict(error=f'could not save the image: {e.strerror or e}'), 500)
        try:
            with open(tmp, 'wb') as fh:
                left = n
                while left:
                    chunk = h.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        raise OSError('the upload was cut off')
                    fh.write(chunk)
                    left -= len(chunk)
            publish(tmp, dest)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return h.json(dict(error=f'could not save the image: {e.strerror or e}'), 500)
        self.log(f'saved {dest}')
        h.json(dict(path=dest, located=False, name=os.path.basename(dest)))

    @staticmethod
    def drain(f, n):
        while n > 0:
            chunk = f.read(min(n, 1 << 20))
            if not chunk:
                break
            n -= len(chunk)

    @staticmethod
    def located(path):
        geo, _ = load_geo(path)
        return geo is not None

    def locate(self, path, force):
        self.phase, self.cancelled = 'locating', False
        cmd = self_command('locate', path) + (['--force'] if force else [])
        self.say(f'positioning {os.path.basename(path)}')
        self.job = ExportJob(cmd, sidecar_path(path))

        def wait():
            self.job.proc.wait()
            while self.job.state == 'running':          # the reader thread sets the state after the last line
                threading.Event().wait(0.1)
            self.lines += self.job.lines
            if self.cancelled:
                self.phase, self.error, self.cancelled = 'idle', None, False
                self.say('cancelled')
            elif self.job.state == 'done':
                self.open(path)
            else:
                self.phase, self.error = 'failed', self.job.error
        threading.Thread(target=wait, daemon=True).start()

    def open(self, path):
        self.phase = 'opening'

        def work():
            try:
                geo, side = load_geo(path)
                if geo is None:
                    raise SystemExit('this image is not positioned yet')
                g = side.get('quality_gate')
                if isinstance(g, dict) and not g.get('ok', True) and not g.get('forced'):
                    raise SystemExit('not annotated: ' + '; '.join(g.get('reasons') or ['the quality gate refused it']))
                raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if raw is None:
                    raise SystemExit(f'cannot read {os.path.basename(path)}')
                self.say('preparing the viewer')
                assert self.server is not None
                self.server.session = Session(path, geo, side, raw, self.say)
                self.phase = 'ready'
            except SystemExit as e:
                self.phase, self.error = 'failed', str(e)
            except Exception as e:                       # noqa: BLE001  (shown on the page, the server carries on)
                self.phase, self.error = 'failed', f'{e.__class__.__name__}: {e}'
        threading.Thread(target=work, daemon=True).start()

    def busy(self):
        s = self.server.session if self.server else None
        return self.phase in ('locating', 'opening') or bool(s and s.job and s.job.state == 'running')

    def stop_jobs(self):
        """A locate or export still running dies with the app, not orphaned in the background."""
        s = self.server.session if self.server else None
        for job in (self.job, s.job if s else None):
            if job is not None and job.proc.poll() is None:
                job.proc.terminate()

    def quit(self):
        if self.window is not None:
            self.window.destroy()                      # run() then stops the server
        elif self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def status(self):
        lines = self.lines + (self.job.lines if self.job and self.phase == 'locating' else [])
        refused = bool(self.error and self.error.startswith('not annotated'))
        return dict(phase=self.phase, path=self.path, name=os.path.basename(self.path or ''), error=self.error,
                    refused=refused, lines=lines[-60:])

    def cancel(self):
        """Stop a locate that runs (the page's Cancel): True when there was one. Opening takes seconds and runs on."""
        if self.phase != 'locating' or self.job is None or self.job.proc.poll() is not None:
            return False
        self.cancelled = True
        self.job.proc.terminate()
        return True

    def thumb(self, h):
        """/app/thumb?path=…: a small JPEG of an image in the work folder, kept in the cache folder."""
        from urllib.parse import parse_qs, urlparse
        try:
            path = self.inside(parse_qs(urlparse(h.path).query).get('path', [''])[0])
        except ValueError:
            return h.send_error(404)
        st = os.stat(path)
        key = hashlib.sha1(f'{path}|{st.st_size}|{st.st_mtime}'.encode()).hexdigest()[:20]
        out = os.path.join(CACHE, 'thumbs', key + '.jpg')
        if not os.path.exists(out):
            data = thumbnail(path)
            if data is None:
                return h.send_error(404)
            private_dir(CACHE)
            private_dir(os.path.dirname(out))
            tmp = temp_beside(out)
            with open(tmp, 'wb') as fh:
                fh.write(data)
            publish(tmp, out)
        h.file(out, 'image/jpeg', cache=True)

    def recent(self):
        """The images in the work folder, newest first, with when they were taken and how far they got:
        status 'solved', 'low' (the quality gate refused it; forced: named anyway) or 'unsolved' (not located, or it failed)."""
        out = []
        try:
            names = os.listdir(self.folder)
        except OSError:
            return out
        for n in names:
            p = os.path.join(self.folder, n)
            if os.path.splitext(n)[1].lower() not in IMAGE_EXT or not os.path.isfile(p):
                continue
            geo, side = load_geo(p) if os.path.exists(sidecar_path(p)) else (None, None)
            g = side.get('quality_gate') if isinstance(side, dict) else None
            low = isinstance(g, dict) and not g.get('ok', True)
            reasons = [r for r in (g.get('reasons') or []) if isinstance(r, str)] if low and isinstance(g, dict) else []
            out.append(dict(name=n, path=p, mtime=os.path.getmtime(p), size=os.path.getsize(p), located=geo is not None,
                            status='unsolved' if geo is None else 'low' if low else 'solved', reasons=reasons,
                            forced=bool(low and isinstance(g, dict) and g.get('forced')), taken=taken(p)))
        return sorted(out, key=lambda r: -r['mtime'])[:30]


def taken(path):
    """When the photo was taken: the SharpCap / WinJUPOS stamp in the name ('YYYY-MM-DD HH:MM UTC'), else the camera's
    EXIF time ('YYYY-MM-DD HH:MM', local), else None."""
    m = SHARPCAP.search(os.path.basename(path))
    if m:
        return f'{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]} UTC'
    if os.path.splitext(path)[1].lower() not in ('.jpg', '.jpeg', '.tif', '.tiff'):
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            t = ex.get_ifd(0x8769).get(36867) or ex.get(306)              # DateTimeOriginal, else DateTime
    except Exception:                                                    # no EXIF, a huge or odd file: no time
        return None
    m = re.match(r'(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2})', str(t or ''))
    return f'{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}' if m else None


def thumbnail(path, side=160):
    """JPEG bytes of the image at most side px, stretched from the 0.5 to 99.8 percentile (16-bit and dark photos
    show), or None when it cannot be read."""
    im = None
    for flag in (cv2.IMREAD_REDUCED_COLOR_8, cv2.IMREAD_UNCHANGED):
        im = cv2.imread(path, flag)
        if im is not None:
            break
    if im is None:
        return None
    if im.ndim == 3 and im.shape[2] == 4:
        im = im[..., :3]
    k = side / max(im.shape[:2])
    if k < 1:
        im = cv2.resize(im, (max(1, round(im.shape[1] * k)), max(1, round(im.shape[0] * k))), interpolation=cv2.INTER_AREA)
    im = im.astype(np.float32)
    lo, hi = np.percentile(im, (0.5, 99.8))
    im = np.clip((im - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode('.jpg', im, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes() if ok else None


def state_file():
    return os.path.join(user_dir('data'), 'running.json')


def write_state(srv):
    """Where the running launcher is and its token, in a file only this user reads: a second start of the app finds the
    first one through it (another user or process cannot, so cannot pass for it or take it over)."""
    d = os.path.dirname(state_file())
    private_dir(d)
    tmp = temp_beside(state_file())
    with open(tmp, 'w') as fh:
        json.dump(dict(port=srv.server_port, token=srv.token, pid=os.getpid()), fh)
    if os.name == 'posix':
        os.chmod(tmp, 0o600)
    os.replace(tmp, state_file())


def read_state():
    try:
        with open(state_file()) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and isinstance(d.get('port'), int) and isinstance(d.get('token'), str) else None
    except (OSError, ValueError):
        return None


def clear_state(srv):
    st = read_state()
    if st and st['token'] == srv.token:
        try:
            os.remove(state_file())
        except OSError:
            pass


def already_running(port, token=None):
    """True when the launcher that started with this token answers on port (a second start then hands over to it).
    Whatever else answers on the port (another program, another user's launcher, a squatter) fails the proof and is
    left alone. token: default, the one in the state file."""
    if token is None:
        st = read_state()
        token = st['token'] if st and st['port'] == port else None
    if not token:
        return False
    nonce = secrets.token_hex(8)
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=2)     # not urllib: no proxy lookup for loopback
    try:
        c.request('GET', f'/app/ping?nonce={nonce}', headers={'Host': 'localhost'})
        want = b'lunaratlas:' + hmac.new(token.encode(), nonce.encode(), 'sha256').hexdigest().encode()
        return c.getresponse().read() == want
    except (OSError, http.client.HTTPException):
        return False
    finally:
        c.close()


def focus(port, token):
    """Ask the running launcher to show its window: True when it has one."""
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        c.request('POST', '/app/focus', b'{}', headers={'Host': 'localhost', 'Content-Type': 'application/json',
                                                        'X-LA-Token': token})
        return b'true' in c.getresponse().read()
    except (OSError, http.client.HTTPException):
        return False
    finally:
        c.close()


def webview_module():
    """pywebview when it is installed, else None (the browser is used)."""
    try:
        import webview  # pyright: ignore[reportMissingImports]  (optional: the app window)
    except ImportError:
        return None
    return webview


def idle_exit(app, srv, seconds, log):
    """Browser mode: stop once no page has asked anything for this long and nothing is running."""
    def watch():
        while True:
            time.sleep(min(15.0, seconds))
            if time.monotonic() - app.seen > seconds and not app.busy():
                log(f'no page open for {seconds:.0f} s: stopping')
                srv.shutdown()
                return
    threading.Thread(target=watch, daemon=True).start()


def run(port=8766, open_browser=True, folder=None, log=print, window=None, idle=0.0):
    """window: True = an app window (pywebview), False = the browser, None = a window when pywebview is there.
    idle: in browser mode, seconds without a page after which the launcher stops (0 = never)."""
    st = read_state()
    if st and already_running(st['port'], st['token']):
        log(f"already running: http://localhost:{st['port']}/app")
        if not focus(st['port'], st['token']) and open_browser:
            webbrowser.open(f"http://localhost:{st['port']}/app?t={st['token']}")
        return
    webview = webview_module() if window is not False and open_browser else None
    if window and webview is None:
        log('no app window (pywebview is not installed): using the browser')
    app = App(folder or work_folder(), log)
    srv = start_server(port, log, app=app)
    app.server = srv
    write_state(srv)
    if webview is None:
        if idle:
            idle_exit(app, srv, idle, log)
        try:
            run_server(srv, open_browser, log, path='/app', what='LunarAtlas')
        finally:
            app.stop_jobs()
            clear_state(srv)
        return
    log(f"LunarAtlas: {srv.url('/app')} in its own window")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app.window = webview.create_window('LunarAtlas', srv.url('/app', secret=True), width=1440, height=920, min_size=(900, 620),
                                       background_color='#0A0F25', text_select=True)
    try:
        webview.start(private_mode=False)          # returns when the window is closed
    finally:
        log('window closed: stopping')
        app.window = None
        app.stop_jobs()
        clear_state(srv)
        srv.shutdown()
        srv.server_close()
