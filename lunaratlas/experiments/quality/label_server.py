#!/usr/bin/env python3
"""Local labelling page for the quality gate: good / borderline / reject per image.

  label_server.py SURVEY_DIR [--port 8765]

Serves SURVEY_DIR/gallery and the items of SURVEY_DIR/quality.json; every click is saved at once to
SURVEY_DIR/labels.json (written atomically), so the page can be closed and reopened at any time.
"""
import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from atlas_paths import publish, temp_beside          # noqa: E402
LOCK = threading.Lock()


def items(survey):
    Q = json.load(open(os.path.join(survey, 'quality.json')))
    seen, out = set(), []
    for q in Q:
        if 'error' in q:
            continue
        sig = (q['width'], q['height'], q.get('edge_width_px'), q.get('mare_noise'))
        if sig in seen:                      # the duplicate pair (-2 / -3) of the test set
            continue
        seen.add(sig)
        own = 'testsamples' not in q['file']
        keys = ('located', 'matches', 'rms_px', 'km_per_px', 'limb_used', 'saturated_share', 'edge_width_px',
                'edge_width_km', 'overshoot', 'undershoot', 'limb_sky_noise', 'mare_noise', 'jpeg_blocking',
                'posterisation', 'octave_ratio', 'width', 'height', 'channels', 'locate_error')
        out.append(dict({k: q.get(k) for k in keys}, key=q['key'], name=os.path.basename(q['file']), own=own,
                        limb=q.get('has_limb_crop', False)))
    out.sort(key=lambda d: (not d['own'], d['key']))      # your images first, the rest in a fixed mixed order
    return out


class Handler(BaseHTTPRequestHandler):
    survey = None
    timeout = 60
    MAX_BODY = 4 << 20

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        super().end_headers()

    def local(self):
        """Only this machine's own page: a Host that is not localhost (DNS rebinding), or a request another site's page
        makes (Origin, Sec-Fetch-Site) is refused, as in the viewer (atlas_view.Handler.local)."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in ('localhost', '127.0.0.1', '[::1]'):
            return False
        if self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            return False
        origin = self.headers.get('Origin')
        return origin is None or re.fullmatch(r'http://(localhost|127\.0\.0\.1|\[::1\]):%d' % self.server.server_port, origin) is not None

    def do_HEAD(self):
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def labels_path(self):
        return os.path.join(self.survey, 'labels.json')

    def read_labels(self):
        try:
            with open(self.labels_path()) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def do_GET(self):
        if not self.local():
            return self.send_error(403)
        p = self.path.split('?')[0]
        known = p in ('/items.json', '/labels.json', '/label_page.js') or p.startswith('/gallery/')
        if not known:                        # any other address (a mistyped or pasted link) shows the page
            b = open(os.path.join(HERE, 'label_page.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b)
        elif p == '/label_page.js':
            b = open(os.path.join(HERE, 'label_page.js'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif p == '/items.json':
            self.send_json(items(self.survey))
        elif p == '/labels.json':
            with LOCK:
                self.send_json(self.read_labels())
        elif re.fullmatch(r'/gallery/[\w.\-]+\.jpg', p):
            try:
                with open(os.path.join(self.survey, p[1:]), 'rb') as fh:
                    b = fh.read()
            except OSError:
                return self.send_error(404)
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.local():
            return self.send_error(403)
        if self.path != '/labels.json':
            return self.send_error(404)
        if (self.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
            return self.send_error(415)              # a text/plain form post from another site needs no CORS preflight
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if not 0 <= n <= self.MAX_BODY:
                return self.send_error(413)
            upd = json.loads(self.rfile.read(n))
            assert isinstance(upd, dict)
        except (ValueError, AssertionError, RecursionError):
            return self.send_error(400)
        with LOCK:
            cur = self.read_labels()
            for k, v in upd.items():
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = v
            tmp = temp_beside(self.labels_path())
            with open(tmp, 'w') as fh:
                json.dump(cur, fh, indent=1)
            publish(tmp, self.labels_path())
        self.send_json(dict(saved=len(cur)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('survey'); ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    Handler.survey = os.path.abspath(a.survey)
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'labelling page: http://localhost:{a.port}/', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
