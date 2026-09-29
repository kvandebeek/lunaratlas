"""`lunaratlas.py view IMAGE`: the local viewer and editor.

A small HTTP server on 127.0.0.1 serves the page (viewer/), the image as a JPEG tile pyramid (cached per image in
the user's cache folder (atlas_paths), rebuilt when the image changes), the feature list in the image's geometry, the fonts
of lunaratlas/fonts, the user's edits (kept in IMAGE.atlas.json under "edits") and a real export that runs
`lunaratlas.py export` in a separate process and reports its progress.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
import socketserver
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlencode

import cv2
import numpy as np

from atlas_geo import R_MOON, image_signature, load_geo, sidecar_path, write_json_atomic
from atlas_names import load_features
from atlas_paths import CACHE as CACHE_ROOT, FONTS as BUNDLED_FONTS, private_dir, self_command
from atlas_render import BUNDLED, FONT_DIR, Fonts, clean_label_override, clean_shapes, light_levels, rim_polygon

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'viewer')
CACHE = os.path.join(CACHE_ROOT, 'tiles')
TILE = 512
VIEWER_FONTS = BUNDLED                          # shipped with the app: the viewer never waits for a download
EDITS_SCHEMA = 'lunaratlas.edits/1'
MAX_JSON = 16 << 20                             # the biggest request body the page can send (the edits: 5000 shapes)


# ---------------------------------------------------------------- tiles
def tile_dir(image):
    key = hashlib.sha1(os.path.abspath(image).encode()).hexdigest()[:16]
    return os.path.join(CACHE, key)


def tile_version(image):
    """Part of every tile URL. The page caches tiles for a day by URL, so each image, and each change to it, needs URLs
    of its own: with bare /tiles/L/C_R.jpg the app window showed tiles of the photo opened before."""
    sig = image_signature(image)
    return hashlib.sha1(f"{os.path.abspath(image)}|{sig['size_bytes']}|{sig['mtime']}".encode()).hexdigest()[:12]


def as_loader(raw, image):
    """A function that gives the pixels: raw may be a function already, the array, or None (read the file)."""
    if raw is None:
        return lambda: read_image(image)
    return raw if callable(raw) else (lambda: raw)


def tiles_complete(d, levels):
    """Every tile the manifest lists is there (a cleaned cache folder or a copied one can lose some)."""
    try:
        return all(os.path.getsize(os.path.join(d, str(i), f'{c}_{r}.jpg')) > 0
                   for i, L in enumerate(levels) for r in range(L['rows']) for c in range(L['cols']))
    except (OSError, KeyError, TypeError):
        return False


def read_image(image):
    raw = cv2.imread(image, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f'cannot read {image}')
    return raw


def build_tiles(image, load_raw, log):
    """JPEG pyramid (level 0 = full resolution, each next level half size) in the cache; reused while the image's
    size and modification time are unchanged and every tile is still there. load_raw() reads the pixels, and is
    called only when the pyramid has to be built: opening an image again does not decode it."""
    d = tile_dir(image)
    meta_p = os.path.join(d, 'meta.json')
    sig = image_signature(image)
    try:
        with open(meta_p) as fh:
            meta = json.load(fh)
        if meta.get('signature') == sig and meta.get('tile') == TILE and tiles_complete(d, meta.get('levels')):
            log(f'tiles from the cache ({len(meta["levels"])} levels)')
            return meta['levels']
        log('the tile cache is out of date or incomplete: building it again')
    except (OSError, ValueError, TypeError):
        pass
    if os.path.isdir(d):
        shutil.rmtree(d)
    try:
        private_dir(CACHE_ROOT)
        private_dir(CACHE)
        private_dir(d)
    except OSError as e:
        raise SystemExit(f'cannot write the tile cache {d}: {e.strerror or e} '
                         '(set HOME to a writable folder, or delete the cache folder)') from None
    raw = as_loader(load_raw, image)()
    g = raw if raw.ndim == 3 else cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    del raw
    g = g[..., :3]
    if g.dtype != np.uint8:               # display stretch only (exports keep the original tonality)
        white = float(np.percentile(g[::7, ::7], 99.95))
        g = cv2.convertScaleAbs(g, alpha=250.0 / max(white, 1))
    levels, lvl = [], 0
    t0 = time.perf_counter()
    with ThreadPoolExecutor(8) as ex:
        while True:
            h, w = g.shape[:2]
            cols, rows = math.ceil(w / TILE), math.ceil(h / TILE)
            ld = os.path.join(d, str(lvl))
            try:
                os.makedirs(ld, exist_ok=True)
            except OSError as e:
                raise SystemExit(f'cannot write the tile cache {ld}: {e.strerror or e}') from None
            jobs = [(r, c) for r in range(rows) for c in range(cols)]
            done = list(ex.map(lambda rc: cv2.imwrite(os.path.join(ld, f'{rc[1]}_{rc[0]}.jpg'),
                                                      g[rc[0] * TILE:(rc[0] + 1) * TILE, rc[1] * TILE:(rc[1] + 1) * TILE],
                                                      [cv2.IMWRITE_JPEG_QUALITY, 86]), jobs))
            if not all(done):                                        # a full disk: no manifest for a pyramid with holes
                raise SystemExit(f'cannot write the tile cache {ld}: {done.count(False)} tiles could not be written '
                                 '(is the disk full?)')
            levels.append(dict(w=w, h=h, cols=cols, rows=rows))
            if max(w, h) <= TILE:
                break
            g = cv2.resize(g, ((w + 1) // 2, (h + 1) // 2), interpolation=cv2.INTER_AREA)
            lvl += 1
    write_json_atomic(meta_p, dict(signature=sig, tile=TILE, levels=levels, image=os.path.abspath(image)))
    log(f'tiles built: {len(levels)} levels, {sum(l["cols"] * l["rows"] for l in levels)} tiles, {time.perf_counter() - t0:.1f} s')
    return levels


# ---------------------------------------------------------------- page data
def link_id(link):
    k = (link or '').rstrip('/').rsplit('/', 1)[-1]
    return k if k.isdigit() else ''


def graticule(geo):
    """10° lat/lon lines in image px, split where they leave the visible hemisphere."""
    lines = []

    def add(lat, lon, kind, value):
        x, y, z = geo.to_image(lat, lon)
        seg = []
        for a, b, c in zip(x, y, z):
            if c > 0.02:
                seg.append([round(float(a), 1), round(float(b), 1)])
            elif seg:
                if len(seg) > 1:
                    lines.append(dict(kind=kind, value=value, pts=seg))
                seg = []
        if len(seg) > 1:
            lines.append(dict(kind=kind, value=value, pts=seg))
    t = np.arange(-180, 180.01, 0.5)
    for lat in range(-80, 81, 10):
        add(np.full_like(t, lat), t, 'lat', lat)
    t = np.arange(-89.5, 89.51, 0.5)
    for lon in range(-180, 180, 10):
        add(t, np.full_like(t, lon), 'lon', lon)
    return lines


LIGHT_VERSION = 1


def night_side(image, load_raw, geo, side, feats, xy, log):
    load_raw = as_loader(load_raw, image)
    """Per feature how lit it is, kept beside the tiles: it needs the pixels (or the Sun's elevation for a close-up), and
    opening the image again with the same positioning must not decode a 200 MP picture to learn it again."""
    closeup = bool((side.get('quality') or {}).get('closeup'))
    sig = image_signature(image)
    key = hashlib.sha1(json.dumps([LIGHT_VERSION, sig, geo.as_dict(), closeup, (side.get('quality') or {}).get('capture_utc'),
                                   len(feats)], sort_keys=True, default=str).encode()).hexdigest()
    p = os.path.join(tile_dir(image), 'light.json')
    try:
        with open(p) as fh:
            c = json.load(fh)
        if c.get('key') == key and len(c.get('light', ())) == len(feats):
            return np.array(c['light'], float)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if closeup:
        from lunaratlas import sun_elevation_light         # a close-up has no sky: the Sun's elevation decides
        light = sun_elevation_light(image, feats)
    else:
        light = light_levels(load_raw(), geo, feats, xy)
    light = np.asarray(light, float)
    try:
        write_json_atomic(p, dict(key=key, light=[float(v) for v in light]))
    except SystemExit:
        log('could not keep the night side beside the tiles')
    return light


def page_data(image, load_raw, geo, side, levels, log):
    load_raw = as_loader(load_raw, image)
    H, W = side.get('height'), side.get('width')
    if not (isinstance(H, int) and isinstance(W, int)):
        H, W = load_raw().shape[:2]
    feats = load_features(log, sites=True)
    lat = np.array([f['lat'] for f in feats]); lon = np.array([f['lon'] for f in feats])
    x, y, z = geo.to_image(lat, lon)
    light = night_side(image, load_raw, geo, side, feats, np.stack([x, y], 1), log)
    rows = []
    for f, a, b, c, li in zip(feats, x, y, z, light):
        if c < 0.05 or not (-0.05 * W < a < 1.05 * W and -0.05 * H < b < 1.05 * H):
            continue
        r = dict(n=f['name'], c=f['cls'], t=f['type'].split(',')[0], la=round(f['lat'], 3), lo=round(f['lon'], 3),
                 d=round(f['diam'], 2), x=round(float(a), 1), y=round(float(b), 1), z=round(float(c), 3),
                 lit=round(float(min(li, 1.5)), 2), o=f['origin'], k=link_id(f['link']))
        if f['cls'] in ('crater', 'lettered', 'apollo') and f['diam'] > 0:
            pts, _ = rim_polygon(geo, f['lat'], f['lon'], f['diam'], 24)
            (ex, ey), (ew, eh), ang = cv2.fitEllipse(pts.astype(np.float32))
            r['e'] = [round(ex, 1), round(ey, 1), round(ew / 2, 1), round(eh / 2, 1), round(ang, 1)]
        rows.append(r)
    log(f'{len(rows)} features on the visible side')
    from atlas_ephem import capture_time as taken_at, sky_text
    when = taken_at(image)
    return dict(image=os.path.basename(image), sky=sky_text(when) if when else None, width=W, height=H, tile=TILE, levels=levels, tiles_v=tile_version(image),
                geometry=geo.as_dict(), radius_px=geo.radius_px, km_per_px=geo.km_per_px, R_moon=R_MOON,
                quality=side.get('quality', {}), gate=(side.get('quality_gate') or {}).get('line'),
                features=rows, grid=graticule(geo), fonts=[f for f in VIEWER_FONTS if font_files(f)])


# ---------------------------------------------------------------- fonts
def font_files(family):
    """[(url, weight range, style)] for a family in lunaratlas/fonts or data/fonts (moved into place by Fonts when needed)."""
    try:
        files = Fonts(family, log=lambda *a: None).files
    except SystemExit:
        return []
    out = []
    for f in files:
        root = BUNDLED_FONTS if os.path.abspath(f['path']).startswith(os.path.abspath(BUNDLED_FONTS) + os.sep) else FONT_DIR
        rel = os.path.relpath(f['path'], root)
        w = '100 900' if f['variable'] else str(f['weight'])
        out.append(('/fonts/' + rel.replace(os.sep, '/'), w, 'italic' if f['italic'] else 'normal'))
    return out


def fonts_css():
    rules = []
    for fam in VIEWER_FONTS:
        for url, w, style in font_files(fam):
            rules.append(f"@font-face {{ font-family: '{fam}'; src: url('{url}') format('truetype'); "
                         f"font-weight: {w}; font-style: {style}; font-display: swap; }}")
    return '\n'.join(rules)


_CSS: list[bytes] = []


def fonts_css_cached():
    if not _CSS:
        _CSS.append(fonts_css().encode())
    return _CSS[0]


# ---------------------------------------------------------------- edits
def read_edits(image):
    try:
        with open(sidecar_path(image)) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    e = d.get('edits') if isinstance(d, dict) else None
    return e if isinstance(e, dict) else {}


def clean_edits(e):
    """Only the fields the viewer and the export know, with the right types (the sidecar is shared).
    Drawings and label overrides that could not be drawn are dropped rather than saved."""
    e = e if isinstance(e, dict) else {}
    out = dict(schema=EDITS_SCHEMA)
    shapes = e.get('shapes')
    out['shapes'] = clean_shapes(shapes)
    hidden = e.get('hidden') if isinstance(e.get('hidden'), list) else []
    out['hidden'] = sorted({n for n in hidden if isinstance(n, str)})
    labs = e.get('labels') if isinstance(e.get('labels'), dict) else {}
    out['labels'] = {str(n): c for n, v in labs.items() if (c := clean_label_override(v))}
    st = e.get('style') if isinstance(e.get('style'), dict) else {}
    out['style'] = {k: st[k] for k in ('font', 'minPx', 'fs', 'night', 'layers', 'grid', 'rims') if k in st}
    if not isinstance(out['style'].get('font', ''), str):
        del out['style']['font']
    return out


def write_edits(image, e, lock):
    """The sidecar with the viewer's edits. A sidecar that has gone or turned to something else is never a
    traceback: the edits are dropped with a message the page shows, and the geometry is left alone."""
    p = sidecar_path(image)
    with lock:
        try:
            with open(p) as fh:
                d = json.load(fh)
        except (OSError, ValueError) as ex:
            raise ValueError(f'cannot read {os.path.basename(p)} ({ex.__class__.__name__}): '
                             'locate the image again before editing it') from None
        if not isinstance(d, dict):
            raise ValueError(f'{os.path.basename(p)} is not a JSON object: locate the image again before editing it')
        d['edits'] = clean_edits(e)
        d['edits']['saved'] = time.strftime('%Y-%m-%d %H:%M:%S')
        write_json_atomic(p, d, indent=1)
    return d['edits']


# ---------------------------------------------------------------- export jobs
class ExportJob:
    """A lunaratlas.py subcommand in its own process; its output lines are kept for the page."""

    def __init__(self, cmd, output):
        self.cmd, self.output = cmd, output
        self.lines, self.state, self.error = [], 'running', None
        # UTF-8 both ways: a Windows pipe would otherwise be cp1252, which has no ≈ or – for the log lines
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8',
                                                                                  PYTHONUNBUFFERED='1'),
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.rstrip()
            if line and 'WARN' not in line:
                self.lines.append(line)
        code = self.proc.wait()
        if code == 0 and os.path.exists(self.output):
            self.state = 'done'
        else:
            self.state = 'failed'
            self.error = self.lines[-1] if self.lines else f'exit code {code}'

    def status(self):
        size = os.path.getsize(self.output) if self.state == 'done' else None
        return dict(state=self.state, lines=self.lines[-40:], output=self.output, error=self.error, size_bytes=size)


EXT = {'tiff': '.tif', 'png': '.png', 'jpg': '.jpg'}


def export_command(image, o):
    """lunaratlas.py export arguments from the dialog's JSON; every value is validated, nothing reaches a shell."""
    if not isinstance(o, dict):
        raise TypeError('expected a JSON object with the export options')
    fmt = o.get('format') if o.get('format') in EXT else 'tiff'
    args = self_command('export', image, '--format', fmt)
    tag = ''
    if o.get('region') == 'view' and isinstance(o.get('box'), list) and len(o['box']) == 4:
        x, y, w, h = (int(round(float(v))) for v in o['box'])
        args += ['--region', f'{x},{y},{max(1, w)},{max(1, h)}']
        tag = f'_region_{x}_{y}'
    elif o.get('region') == 'feature' and isinstance(o.get('name'), str) and o['name'].strip():
        w, h = (int(round(float(v))) for v in o.get('size', [3000, 2000]))
        args += [f"--around={o['name']}", '--size', f'{max(1, w)}x{max(1, h)}']
        tag = '_' + re.sub(r'[^\w.-]+', '_', o['name']).strip('_')
    if o.get('north_up'):
        if o.get('region') == 'view':
            raise ValueError('north up needs the whole image or a feature, not the current view')
        args.append('--north-up')
    if o.get('scale') == 'half':
        args += ['--scale', '0.5']
    elif o.get('scale') == 'max':
        args += ['--max-size', str(max(1, int(float(o.get('max_size', 4096)))))]
    layers = [l for l in o.get('layers', []) if l in ('area', 'crater', 'lettered', 'relief', 'landing')]
    if not o.get('names', True) or not layers:
        args += ['--layers', 'none']
    elif len(layers) < 5:
        args += ['--layers', ','.join(layers)]
    for flag, key in (('--no-rims', 'rims'), ('--no-grid', 'grid'), ('--no-drawings', 'drawings'), ('--no-info', 'info')):
        if not o.get(key, True):
            args.append(flag)
    if o.get('night') in ('dim', 'show'):
        args += ['--night', o['night']]
    for flag, key, lo, hi in (('--min-size', 'min_px', 4, 400), ('--font-scale', 'font_scale', 0.3, 5)):
        if o.get(key) is not None:
            args += [flag, str(min(hi, max(lo, float(o[key]))))]
    if isinstance(o.get('font'), str) and o['font'] in VIEWER_FONTS:
        args += ['--font', o['font']]
    if o.get('force'):
        args.append('--force')
    out = f"{os.path.splitext(image)[0]}_atlas{tag}{EXT[fmt]}"
    return args + ['--overwrite', '-o', out], out                 # the page's own name: a re-export replaces the last one


# ---------------------------------------------------------------- server
def reveal(path):
    """Show a finished file in the desktop file manager: Finder, Explorer or whatever xdg-open picks."""
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', '/select,' + os.path.normpath(path)])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(os.path.abspath(path))])
    except OSError:
        pass                                  # no file manager (a headless box): the export still succeeded


class Session:
    """One open image: its page data, tiles, edits and export job."""

    def __init__(self, image, geo, side, raw=None, log=print):
        """raw: the pixels, or a function that reads them, or None (read from the file when needed). They are needed only
        for a first open of an image: a repeat open uses the cached tiles and night side and never decodes it."""
        self.image = image
        load_raw = as_loader(raw, image)
        levels = build_tiles(image, load_raw, log)
        self.data = page_data(image, load_raw, geo, side, levels, log)
        self._json: dict[bool, bytes] = {}
        self.tiles = tile_dir(image)
        self.lock = threading.Lock()
        self.rev = 0                                # the newest revision of the edits the page has sent
        self.job: ExportJob | None = None

    def data_json(self, launcher):
        """The page's data as JSON (fetched by the page: a script include from another site would run it there);
        launcher says the page has the launcher to go back to."""
        if launcher not in self._json:
            self._json[launcher] = json.dumps(dict(self.data, launcher=launcher), ensure_ascii=False,
                                              separators=(',', ':')).encode()
        return self._json[launcher]


class Server(ThreadingHTTPServer):
    """The viewer's server: session is the open image (None before the launcher opens one), app the launcher."""
    session: 'Session | None' = None
    app: Any = None
    log: Any = print
    token = ''                                  # this run's secret: every request but the ping must show it

    @property
    def cookie_name(self):
        return f'la_{self.server_port}'         # cookies ignore ports: two instances on one host must not share one

    def url(self, path='/', secret=False):
        """The address of a page; with secret, the one-time form that hands the browser the token."""
        return f'http://localhost:{self.server_port}{path}' + (f'?t={self.token}' if secret else '')

    def prove(self, nonce):
        """What only this server can answer to a nonce (the second start's check that it talks to its own app)."""
        return hmac.new(self.token.encode(), nonce.encode(), 'sha256').hexdigest()

    def server_bind(self):
        """As HTTPServer's, without its socket.getfqdn('127.0.0.1'): a reverse lookup that can wait half a minute
        for an mDNS timeout before the page is served."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = 'localhost', self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    """The viewer's routes for server.session; anything else goes to server.app (the launcher page) when there is one."""

    server_version, sys_version = 'LunarAtlas', ''      # no interpreter version in every response

    def version_string(self):
        return self.server_version
    timeout = 120                              # a client that stalls mid-request does not keep a thread for ever
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")

    @property
    def srv(self) -> Server:
        return cast(Server, self.server)

    def log_message(self, *a):
        pass

    def end_headers(self):
        """On every response, error pages included: no framing (clickjacking), no other origin's pages reading it, no
        content sniffing, and a policy that only lets the page's own scripts run."""
        self.send_header('Content-Security-Policy', self.CSP)
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def reply(self, body, ctype, code=200, cache=False):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.reply(json.dumps(obj).encode(), 'application/json', code)

    def file(self, path, ctype, cache=False):
        try:
            with open(path, 'rb') as fh:
                self.reply(fh.read(), ctype, cache=cache)
        except OSError:
            self.send_error(404)

    def local(self):
        """Only this machine's pages: a Host that is not localhost (DNS rebinding), a request another site's page
        makes (Origin, or Sec-Fetch-Site: a <script> or <img> include sends no Origin) is refused."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in ('localhost', '127.0.0.1', '[::1]'):
            return False
        if self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            return False
        origin = self.headers.get('Origin')
        return origin is None or re.fullmatch(r'http://(localhost|127\.0\.0\.1|\[::1\]):%d' % self.srv.server_port,
                                              origin) is not None

    def authed(self):
        """The request carries this run's token: in the cookie the page got at its first visit (HttpOnly, SameSite=Strict:
        a script cannot read it and another site's request does not carry it), or in X-LA-Token for a client that is
        not a browser. Another user's or process's request on this port has neither."""
        tok = self.srv.token
        if not tok:
            return True
        try:
            jar = SimpleCookie(self.headers.get('Cookie') or '')
        except Exception:                      # noqa: BLE001  (a cookie header that does not parse is no cookie)
            jar = SimpleCookie()
        for have in (jar[self.srv.cookie_name].value if self.srv.cookie_name in jar else '', self.headers.get('X-LA-Token') or ''):
            if have and hmac.compare_digest(have.encode(), tok.encode()):
                return True
        return False

    def enter(self, path, query):
        """The link with the token (?t=…) sets the cookie and goes on to the same page without it. False: not that."""
        q = parse_qs(query, keep_blank_values=True)
        t = (q.pop('t', None) or [''])[0]
        if not (t and self.srv.token and hmac.compare_digest(t.encode(), self.srv.token.encode())):
            return False
        self.send_response(303)
        self.send_header('Location', path + ('?' + urlencode(q, doseq=True) if q else ''))
        self.send_header('Set-Cookie', f'{self.srv.cookie_name}={self.srv.token}; Path=/; HttpOnly; SameSite=Strict')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return True

    def page(self):
        with open(os.path.join(PAGE, 'index.html'), 'rb') as fh:
            return fh.read()

    def do_GET(self):
        if not self.local():
            return self.send_error(403)
        p, _, query = self.path.partition('?')
        if p == '/app/ping' and 'nonce=' in query:        # asked by a second start, which has no cookie: proves, reveals nothing
            return self.reply(b'lunaratlas:' + self.srv.prove((parse_qs(query).get('nonce') or [''])[0]).encode(), 'text/plain')
        if self.enter(p, query):
            return
        if not self.authed():
            return self.send_error(403)
        app, s = self.srv.app, self.srv.session
        if app is not None and app.get(self, p):
            return
        if self.static(p):                     # the look (theme, fonts, icon): the launcher's pages use it too
            return
        if s is None:
            return self.send_error(404)
        if p in ('/', '/index.html'):
            return self.reply(self.page(), 'text/html; charset=utf-8')
        if p in ('/selftest', '/selftest.js') and not os.environ.get('LUNARATLAS_SELFTEST'):
            return self.send_error(404)             # a test affordance: only when the tests switch it on
        if p == '/selftest':                   # tests/viewer_selftest.js on top of the real page
            return self.reply(self.page().replace(b'</body>', b'<script src="/selftest.js"></script>\n</body>'),
                              'text/html; charset=utf-8')
        if p == '/selftest.js':
            return self.file(os.path.join(HERE, 'tests', 'viewer_selftest.js'), 'text/javascript')
        if p == '/data.json':
            return self.reply(s.data_json(self.srv.app is not None), 'application/json')
        if p == '/edits':
            return self.json(read_edits(s.image))
        if p == '/export/status':
            return self.json(s.job.status() if s.job else dict(state='none'))
        m = re.fullmatch(r'/tiles/(\d+)/(\d+)_(\d+)\.jpg', p)
        if m:
            return self.file(os.path.join(s.tiles, m[1], f'{m[2]}_{m[3]}.jpg'), 'image/jpeg', cache=True)
        self.send_error(404)

    def static(self, p):
        if p in ('/favicon.svg', '/lunaratlas.svg'):
            self.file(os.path.join(PAGE, 'lunaratlas.svg'), 'image/svg+xml', cache=True)
        elif p in ('/viewer.js', '/boot.js', '/app.js', '/viewer.css', '/theme.css', '/friendly.js', '/exif.js'):
            self.file(os.path.join(PAGE, p[1:]), 'text/javascript' if p.endswith('.js') else 'text/css')
        elif p == '/fonts.css':
            self.reply(fonts_css_cached(), 'text/css')
        else:
            m = re.fullmatch(r'/fonts/([\w\[\],.\- ]+(?:/[\w\[\],.\- ]+)?\.(?:ttf|otf))', unquote(p))
            if not m or '..' in m[1]:
                return False
            b = os.path.join(BUNDLED_FONTS, m[1])
            self.file(b if os.path.isfile(b) else os.path.join(FONT_DIR, m[1]), 'font/ttf', cache=True)
        return True

    def length(self, limit):
        """The request's Content-Length: 0 when it names none. A bad, negative or too large one raises ValueError
        (a negative one would make rfile.read wait for the client to hang up)."""
        n = int(self.headers.get('Content-Length') or 0)
        if n < 0 or n > limit:
            raise ValueError(f'Content-Length {n} is not between 0 and {limit}')
        return n

    def body(self):
        n = self.length(MAX_JSON)
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except RecursionError:                 # JSON nested thousands deep
            raise ValueError('nested too deeply') from None

    def do_HEAD(self):
        self.refuse()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD

    def refuse(self):
        """GET and POST only. Nothing else names a file on the disk, and a CORS preflight gets no yes."""
        if not self.local():
            return self.send_error(403)
        self.send_response(405)
        self.send_header('Allow', 'GET, POST')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        if not self.local() or not self.authed():
            return self.send_error(403)
        p = self.path.split('?')[0]
        app, s = self.srv.app, self.srv.session
        if app is not None and app.post(self, p):
            return
        if s is None:
            return self.send_error(404)
        try:
            o = self.body()
        except ValueError as e:
            return self.json(dict(error=str(e)), 413 if 'Content-Length' in str(e) else 400)
        if p in ('/edits', '/export') and not isinstance(o, dict):
            return self.json(dict(error='expected a JSON object'), 400)
        if p == '/edits':
            rev = o.pop('rev', None)                # the page numbers its saves: a late one never overwrites a newer one
            if isinstance(rev, (int, float)) and not isinstance(rev, bool):
                with s.lock:
                    stale = rev < s.rev
                    s.rev = max(s.rev, rev)
                if stale:
                    return self.json(dict(stale=True), 409)
            try:
                return self.json(write_edits(s.image, o, s.lock))
            except (OSError, ValueError) as e:
                return self.json(dict(error=str(e)), 500)
        if p == '/export':
            if s.job and s.job.state == 'running':
                return self.json(dict(error='an export is already running'), 409)
            try:
                cmd, out = export_command(s.image, o)
            except (TypeError, ValueError, OverflowError) as e:
                return self.json(dict(error=f'bad export options: {e}'), 400)
            s.job = ExportJob(cmd, out)
            self.srv.log('export: ' + ' '.join(cmd[2:]))
            return self.json(dict(started=True, output=out))
        if p == '/reveal':
            if s.job and s.job.state == 'done':
                reveal(s.job.output)
            return self.json(dict(ok=True))
        self.send_error(404)


def start_server(port, log=print, session=None, app=None, token=None):
    """The HTTP server on the first free port from port on (not yet serving)."""
    for p in range(port, port + 20):
        try:
            srv = Server(('127.0.0.1', p), Handler)
            break
        except OSError:
            continue
    else:
        raise SystemExit(f'no free port in {port}–{port + 19}')
    srv.session, srv.app, srv.log = session, app, log
    srv.token = token or os.environ.get('LUNARATLAS_TOKEN') or secrets.token_urlsafe(32)
    return srv


def run_server(srv, open_browser=True, log=print, path='/', what='viewer'):
    """Serve until Ctrl-C. The address with the token goes to the browser this opens; it is printed only when nothing
    is opened (then it is the way in: this terminal is the user's own), never into a log file."""
    log(f'{what}: {srv.url(path, secret=not open_browser)}  (Ctrl-C to stop)')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(srv.url(path, secret=True))).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log(f'{what} stopped')
    finally:
        srv.server_close()


def serve(image, geo, side, raw=None, port=8766, open_browser=True, log=print):
    session = Session(image, geo, side, raw, log)
    del raw
    run_server(start_server(port, log, session=session), open_browser, log)
