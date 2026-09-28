#!/usr/bin/env python3
"""Local labelling page for the quality gate: good / borderline / reject per image.

  label_server.py SURVEY_DIR [--port 8765]

Serves SURVEY_DIR/gallery and the items of SURVEY_DIR/quality.json; every click is saved at once to
SURVEY_DIR/labels.json (written atomically), so the page can be closed and reopened at any time.
"""
import argparse
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
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


class Handler(SimpleHTTPRequestHandler):
    survey = None

    def log_message(self, *a):
        pass

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
        p = self.path.split('?')[0]
        known = p in ('/items.json', '/labels.json') or p.startswith('/gallery/')
        if not known:                        # any other address (a mistyped or pasted link) shows the page
            b = open(os.path.join(HERE, 'label_page.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b)
        elif p == '/items.json':
            self.send_json(items(self.survey))
        elif p == '/labels.json':
            with LOCK:
                self.send_json(self.read_labels())
        elif p.startswith('/gallery/') and '..' not in p:
            self.path = p
            SimpleHTTPRequestHandler.do_GET(self)
        else:
            self.send_error(404)

    def translate_path(self, path):
        return os.path.join(self.survey, path.lstrip('/'))

    def do_POST(self):
        if self.path != '/labels.json':
            return self.send_error(404)
        n = int(self.headers.get('Content-Length', 0))
        try:
            upd = json.loads(self.rfile.read(n))
            assert isinstance(upd, dict)
        except (ValueError, AssertionError):
            return self.send_error(400)
        with LOCK:
            cur = self.read_labels()
            for k, v in upd.items():
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = v
            tmp = self.labels_path() + '.part'
            with open(tmp, 'w') as fh:
                json.dump(cur, fh, indent=1)
            os.replace(tmp, self.labels_path())
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
