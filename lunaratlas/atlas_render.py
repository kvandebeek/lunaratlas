"""Label layout and drawing: IBM Plex Sans (a bundled font, or any Google Font), no outlines, soft shadow behind the letters."""
import json
import math
import os
import re
import urllib.error
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from atlas_geo import DATA, R_MOON, download, resize
from atlas_paths import FONTS as BUNDLED_FONTS

FONT_DIR = os.path.join(DATA, 'fonts')
DEFAULT_FONT = 'IBM Plex Sans'
BUNDLED = ('IBM Plex Sans', 'Source Sans 3', 'Roboto')           # in lunaratlas/fonts: offline, the viewer's choices

LABEL_RGB = (255, 244, 226)                          # one colour for every name (chosen 2026-09-27); maria differ by size
STYLE = dict(
    shadow_sigma=3.2, shadow_opacity=0.75,            # the accepted look: blurred shade, not an outline
    colours=dict(area=LABEL_RGB + (235,), crater=LABEL_RGB + (250,), lettered=LABEL_RGB + (215,),
                 relief=LABEL_RGB + (235,), landing=LABEL_RGB + (245,), rim=(245, 167, 66, 105),
                 leader=(245, 167, 66, 242)),
    grid=(143, 216, 236, 70), grid_label=(143, 216, 236, 200),        # the app's amber and cyan (icon)
)
NIGHT_DIM = 0.3                                       # 'dim': names on the night side, clearly fainter
LAYERS = ('area', 'crater', 'lettered', 'relief', 'landing')          # as in the viewer's Layers panel
LAYER_OF = {'area': 'area', 'crater': 'crater', 'lettered': 'lettered', 'apollo': 'lettered', 'relief': 'relief',
            'site': 'relief', 'landing': 'landing'}
WEIGHTS = {'thin': 100, 'extralight': 200, 'light': 300, 'regular': 400, 'medium': 500,
           'semibold': 600, 'bold': 700, 'extrabold': 800, 'black': 900}


# ---------------------------------------------------------------- fonts
class Fonts:
    """A font family: the bundled ones from lunaratlas/fonts, any other from data/fonts, downloaded from Google Fonts
    (github.com/google/fonts) if needed.
    Handles variable fonts (weight/width/optical-size axes) and static families."""

    def __init__(self, family=DEFAULT_FONT, log=print):
        self.family = family
        self.files = self._ensure(family, log)
        self.cache = {}

    @staticmethod
    def _slug(family):
        return re.sub(r'[^a-z0-9]', '', family.lower())

    @staticmethod
    def _font_ok(path):
        try:
            ImageFont.truetype(path, 12)
            return True
        except OSError:
            return False

    def _ensure(self, family, log):
        b = os.path.join(BUNDLED_FONTS, self._slug(family))
        if os.path.isdir(b):
            files = sorted(f for f in os.listdir(b) if f.lower().endswith(('.ttf', '.otf')) and self._font_ok(os.path.join(b, f)))
            if files:
                return self._describe(b, files)
        d = os.path.join(FONT_DIR, self._slug(family))
        os.makedirs(d, exist_ok=True)
        pending = os.path.join(d, '.incomplete')          # present while a download of the family is under way
        files = [f for f in os.listdir(d) if f.lower().endswith(('.ttf', '.otf'))]
        damaged = [f for f in files if not self._font_ok(os.path.join(d, f))]
        usable = [f for f in files if f not in damaged]            # fallback when the download cannot run
        if damaged or os.path.exists(pending):
            log(f'font {family}: {"damaged files " + ", ".join(damaged) if damaged else "earlier download incomplete"}; downloading again')
            for f in damaged:
                os.remove(os.path.join(d, f))
            files = []
        legacy = [f for f in os.listdir(FONT_DIR) if f.lower().endswith('.ttf') and self._slug(f.split('[')[0].split('-')[0]) == self._slug(family)]
        if not files and legacy and not damaged:         # fonts downloaded during the design mockups
            for f in legacy:
                os.replace(os.path.join(FONT_DIR, f), os.path.join(d, f))
            files = legacy
        if not files:
            listing, err = None, None
            for lic in ('ofl', 'apache', 'ufl'):
                try:
                    with urllib.request.urlopen(f'https://api.github.com/repos/google/fonts/contents/{lic}/{self._slug(family)}', timeout=30) as r:
                        listing = json.load(r); break
                except urllib.error.HTTPError as e:
                    if e.code != 404:                              # e.g. 403 rate limit
                        err = e
                except Exception as e:                             # offline, DNS, timeout
                    err = e
            if not listing and usable:
                log(f'font {family}: cannot download ({err or "not found"}); using the files already here')
                listing, files = [], usable
            elif not listing:
                raise SystemExit(f'cannot reach Google Fonts for "{family}": {err}' if err else
                                 f'font "{family}" not found on Google Fonts')
            want = [e for e in listing if e['name'].lower().endswith('.ttf')]
            if want:
                log(f'downloading font {family} ({len(want)} files, once)')
                open(pending, 'w').close()
                for e in want:
                    download(e['download_url'], os.path.join(d, e['name']), self._font_ok)
                os.remove(pending)
                files = [e['name'] for e in want]
        return self._describe(d, files)

    @staticmethod
    def _describe(d, files):
        out = []
        for f in files:
            base = f.rsplit('.', 1)[0]
            italic = 'italic' in base.lower()
            if '[' in base:
                out.append(dict(path=os.path.join(d, f), italic=italic, variable=True, weight=None))
            else:
                style = base.split('-')[-1].lower().replace('italic', '') or 'regular'
                out.append(dict(path=os.path.join(d, f), italic=italic, variable=False, weight=WEIGHTS.get(style, 400)))
        return out

    @property
    def has_italic(self):
        return any(f['italic'] for f in self.files)

    def get(self, weight, size, italic=False):
        key = (weight, size, italic)
        if key in self.cache:
            return self.cache[key]
        cands = [f for f in self.files if f['italic'] == (italic and self.has_italic)] or self.files
        var = [f for f in cands if f['variable']]
        f = var[0] if var else min(cands, key=lambda c: abs(c['weight'] - weight))
        font = ImageFont.truetype(f['path'], size)
        if f['variable']:
            vals = []
            for a in font.get_variation_axes():
                n = (a['name'].decode() if isinstance(a['name'], bytes) else a['name']).lower()
                v = weight if n.startswith('weight') else size if n.startswith('optical') else a['default']
                vals.append(max(a['minimum'], min(a['maximum'], v)))
            font.set_variation_by_axes(vals)
        self.cache[key] = font
        return font


# ---------------------------------------------------------------- layout
def _text_size(font, s, track):
    if not track:
        return font.getlength(s), font.size * 0.72
    return sum(font.getlength(c) for c in s) + track * font.size * (len(s) - 1), font.size * 0.72


def rim_polygon(geo, lat, lon, diam_km, n=40):
    """Projected outline of a circular feature (a small circle on the sphere)."""
    a = diam_km / 2 / R_MOON
    la, lo = math.radians(lat), math.radians(lon)
    c = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    east = np.array([-math.sin(lo), math.cos(lo), 0.0])
    north = np.cross(c, east)
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    p = math.cos(a) * c + math.sin(a) * (np.cos(t)[:, None] * east + np.sin(t)[:, None] * north)
    x, y, z = geo.to_image(np.degrees(np.arcsin(p[:, 2])), np.degrees(np.arctan2(p[:, 1], p[:, 0])))
    return np.stack([x, y], 1), z


def sky_radius(shape, geo):
    """Distance from the disk centre in lunar radii, per pixel (sky plane)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    sx, sy = geo.to_sky(xx.astype(np.float64), yy.astype(np.float64))
    return np.hypot(sx, sy)


def sky_level(gray, r):
    """Median brightness outside the limb (the additive sky pedestal), or 0 when too little sky is in view."""
    outside = r > 1.03
    return float(np.median(gray[outside])) if outside.sum() > 0.01 * gray.size else 0.0


def lit_level(gray_small, geo_small, feats_xy, radii_px):
    """Brightest nearby pixel above the sky / sunlit level above the sky, per feature (0 = night side,
    1 = fully lit). gray_small and geo_small are the small copy and its geometry; xy and radii in its px."""
    g = cv2.GaussianBlur(gray_small, (0, 0), 1.0)
    r = sky_radius(g.shape, geo_small)
    sky = sky_level(g, r)
    on = g[r < 0.95]                     # the sunlit level from the disk, not from sky noise around a small Moon
    ref = on if on.size > 100 else g.ravel()
    upper = ref[ref > np.percentile(ref, 50)]
    lit = max(np.percentile(upper if upper.size else ref, 90) - sky, 1e-6)
    out = np.zeros(len(feats_xy))
    h, w = g.shape
    for i, ((x, y), r) in enumerate(zip(feats_xy, radii_px)):
        X, Y, rr = int(round(x)), int(round(y)), max(1, int(round(r)))
        if 0 <= X < w and 0 <= Y < h:
            out[i] = max(0.0, g[max(0, Y - rr):Y + rr + 1, max(0, X - rr):X + rr + 1].max() - sky) / lit
    return out


def light_levels(raw, geo, feats, xy):
    """lit_level for every feature (xy in image px), measured on a 1024 px copy of the whole image."""
    small, (sx, sy) = resize(raw if raw.ndim == 2 else raw[..., :3], 1024.0 / max(raw.shape[:2]))
    if small.ndim == 3:            # grey after shrinking: no full-size grey copy (≈ 0.8 GB for a 14792 px mosaic)
        small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    xy = (np.asarray(xy, float).reshape(-1, 2) + 0.5) * [sx, sy] - 0.5
    s = math.sqrt(sx * sy)
    radii = [s * (max(4.0, f['diam'] / R_MOON * geo.radius_px / 2) if f['cls'] in ('crater', 'lettered', 'apollo')
                  else 25.0 / geo.km_per_px) for f in feats]          # areas / ranges: only near the label itself
    return lit_level(small.astype(np.float32), geo.resized(sx, sy), xy, radii)


def hex_rgba(c, alpha=255):
    c = (c or '#ffffff').lstrip('#')
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)
    except ValueError:
        return (255, 255, 255, alpha)


def view_mapper(view):
    x0, y0, scale, W, H = view
    kx, ky = (scale, scale) if np.isscalar(scale) else scale
    return (lambda x, y: ((np.asarray(x, float) - x0 + 0.5) * kx - 0.5, (np.asarray(y, float) - y0 + 0.5) * ky - 0.5)), \
        math.sqrt(kx * ky)


def layout(feats, geo, view, fonts, min_px=24, font_scale=1.0, rims=True, lettered=True, landing=True,
           night='hide', light=None, keep_on_disk=True, layers=LAYERS, hidden=(), overrides=None, reserved=()):
    """Place labels for one output view. view = (x0, y0, scale, w, h), scale a number or (sx, sy): the
    source crop at x0, y0 resized by cv2 to w x h, so output px = (src - x0 + 0.5) * scale - 0.5.
    hidden: feature names not to label. overrides: name -> {dx, dy (source px, from the automatic spot), colour
    ('#rrggbb'), size (factor)} from the viewer's editor; a moved label stays where it was put. reserved: output
    boxes (x0, y0, x1, y1) no automatic label may cover (the user's own texts, the info block).
    Returns a list of label dicts in output px, drawn in order."""
    x0, y0, scale, W, H = view
    to_out, scale = view_mapper(view)
    overrides = overrides if isinstance(overrides, dict) else {}         # the sidecar is shared: types are checked
    hidden = {n for n in hidden if isinstance(n, str)} if isinstance(hidden, (list, tuple, set)) else set()

    C = STYLE['colours']
    R = geo.radius_px * scale
    cx, cy = to_out(geo.t[0], geo.t[1])
    cell = 3
    occ = np.zeros((H // cell + 2, W // cell + 2), bool)
    for bx0, by0, bx1, by1 in reserved:
        occ[max(0, int(by0 // cell)):max(0, int(by1 // cell) + 1), max(0, int(bx0 // cell)):max(0, int(bx1 // cell) + 1)] = True
    rank = {'area': 0, 'crater': 1, 'relief': 2, 'landing': 3, 'site': 2, 'lettered': 4, 'apollo': 5}
    order = sorted(range(len(feats)), key=lambda i: (rank.get(feats[i]['cls'], 4), -feats[i]['diam']))
    out = []
    for i in order:
        f = feats[i]
        cls = f['cls']
        if (cls == 'lettered' and not lettered) or (cls == 'landing' and not landing) or LAYER_OF.get(cls, 'relief') not in layers:
            continue
        if f['z'] < 0.1 or f['name'] in hidden:
            continue
        ov = clean_label_override(overrides.get(f['name'])) or {}
        X, Y = to_out(f['x'], f['y'])
        if not (-200 <= X < W + 200 and -200 <= Y < H + 200):
            continue
        Dpx = f['diam'] / R_MOON * R
        alpha = 1.0
        if light is not None and night != 'show' and light[i] < 0.12:
            if night == 'hide':
                continue
            alpha = NIGHT_DIM
        k = math.log2(max(Dpx, 1e-3) / min_px + 1)
        track, italic, txt = 0.0, False, f['name']
        if cls == 'area':
            if Dpx < min_px * 0.3:
                continue
            size, wt, col, track, txt = np.clip(Dpx * 0.05, 15, 34), 300, C['area'], 0.22, txt.upper()
        elif cls == 'crater':
            if Dpx < min_px:
                continue
            size, wt, col = np.clip(12 + 3.5 * k, 13, 26), 560, C['crater']
        elif cls in ('lettered', 'apollo'):
            if Dpx < min_px:
                continue
            size, wt, col = np.clip(10 + 2.0 * k, 11, 16), 420, C['lettered']
        elif cls == 'landing':
            if geo.km_per_px / scale > 3.0:              # only once zoomed in enough to be meaningful
                continue
            size, wt, col = 13, 520, C['landing']
        else:                                            # relief, statio
            if Dpx < min_px * 1.5:
                continue
            size, wt, col, italic, track = np.clip(11 + 2.5 * k, 12, 20), 430, C['relief'], True, 0.02
        size = max(8, int(round(size * font_scale * float(ov.get('size') or 1))))
        if ov.get('colour'):
            col = hex_rgba(ov['colour'], col[3])
        font = fonts.get(wt, size, italic)
        tw, th = _text_size(font, txt, track)
        poly = None
        if cls in ('crater', 'lettered', 'apollo'):
            pts, _ = rim_polygon(geo, f['lat'], f['lon'], f['diam'], 40)
            poly = np.stack(to_out(pts[:, 0], pts[:, 1]), 1)
            l, t, r, b = poly[:, 0].min(), poly[:, 1].min(), poly[:, 0].max(), poly[:, 1].max()
            g = 4 * font_scale
            spots = [(X, b + g + th / 2), (X, t - g - th / 2), (r + g + tw / 2, Y), (l - g - tw / 2, Y)]
        elif cls == 'landing':
            g = 7 * font_scale
            spots = [(X + g + tw / 2, Y), (X - g - tw / 2, Y), (X, Y + g + th / 2), (X, Y - g - th / 2)]
        else:
            spots = [(X, Y)]
        moved = 'dx' in ov and 'dy' in ov
        if moved:                                        # the user's placement: first spot + their offset, no search
            spots = [(spots[0][0] + float(ov['dx']) * scale, spots[0][1] + float(ov['dy']) * scale)]
        for sx, sy in spots:
            bx0, by0, bx1, by1 = sx - tw / 2 - 4, sy - th / 2 - 4, sx + tw / 2 + 4, sy + th / 2 + 4
            if not moved and keep_on_disk and max(math.hypot(px - cx, py - cy) for px in (bx0, bx1) for py in (by0, by1)) > R * 0.995:
                continue
            a0, b0, a1, b1 = int(bx0 // cell), int(by0 // cell), int(bx1 // cell) + 1, int(by1 // cell) + 1
            if a0 < 0 or b0 < 0 or a1 >= occ.shape[1] or b1 >= occ.shape[0]:
                continue
            if not moved and occ[b0:b1, a0:a1].any():
                continue
            occ[b0:b1, a0:a1] = True
            lab = dict(text=txt, weight=wt, size=size, italic=italic, track=track, x=sx, y=sy, w=tw, h=th,
                       colour=col[:3] + (int(col[3] * alpha),), feature=i)
            if poly is not None and rims and Dpx >= 8:
                lab['rim'] = poly
            if cls == 'landing':
                lab['marker'] = (X, Y, 3.2 * font_scale)
            if moved:                                    # a moved name keeps a line to its feature, as in the viewer
                ex, ey = min(max(X, sx - tw / 2), sx + tw / 2), min(max(Y, sy - th / 2), sy + th / 2)
                if math.hypot(ex - X, ey - Y) >= 6 * font_scale:
                    lab['leader'] = ((X, Y), (ex, ey))
            out.append(lab)
            break
    return out


# ---------------------------------------------------------------- drawing
def _draw_text(d, lab, font, ox, oy, fill):
    x = lab['x'] - lab['w'] / 2 - ox
    y = lab['y'] + lab['h'] / 2 - oy
    if not lab['track']:
        d.text((x, y), lab['text'], font=font, fill=fill, anchor='ls')
        return
    for c in lab['text']:
        d.text((x, y), c, font=font, fill=fill, anchor='ls')
        x += font.getlength(c) + lab['track'] * font.size


def _dashed(pts, on, off):
    """Split a polyline into dash pieces of `on` px with `off` px gaps."""
    out, cur, pos, drawing = [], [pts[0]], 0.0, True
    for a, b in zip(pts[:-1], pts[1:]):
        seg = float(np.hypot(*(b - a)))
        t = 0.0
        while seg - t > 1e-9:
            left = (on if drawing else off) - pos
            step = min(left, seg - t)
            t += step
            pos += step
            p = a + (b - a) * (t / seg)
            if drawing:
                cur.append(p)
            if pos >= (on if drawing else off) - 1e-9:
                if drawing and len(cur) > 1:
                    out.append(np.array(cur))
                drawing, pos, cur = not drawing, 0.0, [p]
    if drawing and len(cur) > 1:
        out.append(np.array(cur))
    return out


def draw(out_img, labels, fonts, font_scale=1.0, tile=2048, white=None, lines=()):
    """Composite labels into out_img (H x W x 3, uint8 or uint16, BGR) in place, tile by tile. lines: polylines
    drawn under the labels, dicts of pts (N x 2 output px), colour RGBA, width, closed, dash (on, off) and fill RGBA.
    A label may carry its own 'fonts' (a Fonts of another family)."""
    H, W = out_img.shape[:2]
    maxv = 65535.0 if out_img.dtype == np.uint16 else 255.0
    white = white or maxv
    sig = STYLE['shadow_sigma'] * font_scale
    m = int(math.ceil(3 * sig)) + 2
    boxes = np.array([(l['x'] - l['w'] / 2, l['y'] - l['h'] / 2, l['x'] + l['w'] / 2, l['y'] + l['h'] / 2) for l in labels]).reshape(-1, 4)
    rb = [(l['rim'][:, 0].min(), l['rim'][:, 1].min(), l['rim'][:, 0].max(), l['rim'][:, 1].max()) if 'rim' in l
          else (min(l['leader'][0][0], l['leader'][1][0]), min(l['leader'][0][1], l['leader'][1][1]),
                max(l['leader'][0][0], l['leader'][1][0]), max(l['leader'][0][1], l['leader'][1][1])) if 'leader' in l
          else None for l in labels]
    lb = [(ln['pts'][:, 0].min() - ln.get('width', 1), ln['pts'][:, 1].min() - ln.get('width', 1),
           ln['pts'][:, 0].max() + ln.get('width', 1), ln['pts'][:, 1].max() + ln.get('width', 1)) for ln in lines]
    for ty in range(0, H, tile):
        for tx in range(0, W, tile):
            th, tw = min(tile, H - ty), min(tile, W - tx)
            ox, oy = tx - m, ty - m
            lw, lh = tw + 2 * m, th + 2 * m
            hit = [j for j, l in enumerate(labels)
                   if boxes[j, 2] + 40 >= ox and boxes[j, 0] - 40 <= ox + lw and boxes[j, 3] + 40 >= oy and boxes[j, 1] - 40 <= oy + lh
                   or (rb[j] is not None and rb[j][2] >= ox and rb[j][0] <= ox + lw and rb[j][3] >= oy and rb[j][1] <= oy + lh)]
            lhit = [j for j, b in enumerate(lb) if b[2] >= ox and b[0] <= ox + lw and b[3] >= oy and b[1] <= oy + lh]
            if not hit and not lhit:
                continue
            layer = Image.new('RGBA', (lw, lh), (0, 0, 0, 0))
            shade = Image.new('L', (lw, lh), 0)
            d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shade)
            for j in lhit:
                ln = lines[j]
                p = ln['pts'] - [ox, oy]
                if ln.get('fill'):
                    d.polygon([tuple(map(float, q)) for q in p], fill=ln['fill'])
                if ln.get('colour') and ln.get('width', 1) > 0:
                    if ln.get('closed'):
                        p = np.vstack([p, p[:1]])
                    width = max(1, int(round(ln.get('width', 1))))
                    for piece in (_dashed(p, *ln['dash']) if ln.get('dash') else [p]):
                        d.line([tuple(map(float, q)) for q in piece], fill=ln['colour'], width=width, joint='curve')
            for j in hit:
                l = labels[j]
                if 'leader' in l:                        # dark edge, then dashed amber, so it reads on bright ground
                    p = np.array(l['leader'], float) - [ox, oy]
                    a8 = l['colour'][3] / 255
                    d.line([tuple(map(float, q)) for q in p], fill=(0, 0, 0, int(115 * a8)), width=max(1, int(round(3 * font_scale))))
                    for piece in _dashed(p, 4 * font_scale, 3 * font_scale):
                        d.line([tuple(map(float, q)) for q in piece], fill=STYLE['colours']['leader'][:3] + (int(STYLE['colours']['leader'][3] * a8),),
                               width=max(1, int(round(1.3 * font_scale))))
                if 'rim' in l:
                    p = [(float(a - ox), float(b - oy)) for a, b in l['rim']]
                    d.line(p + p[:1], fill=STYLE['colours']['rim'][:3] + (int(STYLE['colours']['rim'][3] * l['colour'][3] / 255),),
                           width=max(1, int(round(font_scale))))
                if 'marker' in l:
                    mx, my, r = l['marker']
                    d.ellipse((mx - r - ox, my - r - oy, mx + r - ox, my + r - oy), outline=l['colour'], width=max(1, int(round(1.4 * font_scale))))
                font = l.get('fonts', fonts).get(l['weight'], l['size'], l['italic'])
                _draw_text(ds, l, font, ox, oy, int(255 * l['colour'][3] / 255))
            for j in hit:
                l = labels[j]
                _draw_text(d, l, l.get('fonts', fonts).get(l['weight'], l['size'], l['italic']), ox, oy, l['colour'])
            sh = cv2.GaussianBlur(np.asarray(shade, np.float32) / 255.0, (0, 0), sig) * STYLE['shadow_opacity']
            la = np.asarray(layer, np.float32)
            a = la[..., 3:4] / 255.0
            col = la[..., 2::-1] / 255.0 * white                       # RGBA -> BGR, scaled to the image white
            sl = (slice(m, m + th), slice(m, m + tw))
            base = out_img[ty:ty + th, tx:tx + tw].astype(np.float32)
            base = base * (1 - sh[sl][..., None])
            base = base * (1 - a[sl]) + col[sl] * a[sl]
            out_img[ty:ty + th, tx:tx + tw] = np.clip(base, 0, maxv).astype(out_img.dtype)
    return out_img


# ---------------------------------------------------------------- overlays: grid, the user's drawings, info block
def text_label(fonts, text, x, y, size, colour, weight=500, italic=False, track=0.0, anchor='centre'):
    """A free text in output px, drawn like the names (soft shadow, no outline). anchor 'left' puts x at its start."""
    font = fonts.get(weight, size, italic)
    tw, th = _text_size(font, text, track)
    cx = x + tw / 2 if anchor == 'left' else x
    return dict(text=text, weight=weight, size=size, italic=italic, track=track, x=cx, y=y, w=tw, h=th,
                colour=colour, fonts=fonts)


def box_of(lab, pad=4):
    return (lab['x'] - lab['w'] / 2 - pad, lab['y'] - lab['h'] / 2 - pad, lab['x'] + lab['w'] / 2 + pad, lab['y'] + lab['h'] / 2 + pad)


def grid_overlay(geo, view, fonts, font_scale=1.0, step=10):
    """Lat/lon lines every `step` degrees on the visible hemisphere. Parallels are labelled where they cross the
    central meridian, meridians where they cross the equator (near the limb the lines converge and labels would pile
    up). Returns (lines, labels)."""
    to_out, _ = view_mapper(view)
    W, H = view[3], view[4]
    lines, labels = [], []
    col = STYLE['grid']
    size = max(8, int(round(11 * font_scale)))
    m = 30 * font_scale

    def visible_runs(lat, lon):
        x, y, z = geo.to_image(lat, lon)
        X, Y = to_out(x, y)
        vis = z > 0.02
        for r in np.split(np.arange(len(z)), np.nonzero(np.diff(vis.astype(int)))[0] + 1):
            if len(r) > 1 and vis[r[0]]:
                pts = np.stack([X[r], Y[r]], 1)
                if ((pts[:, 0] > -50) & (pts[:, 0] < W + 50) & (pts[:, 1] > -50) & (pts[:, 1] < H + 50)).any():
                    lines.append(dict(pts=pts, colour=col, width=max(1.0, font_scale)))

    def label_at(lat, lon, txt):
        x, y, z = geo.to_image(np.array([lat], float), np.array([lon], float))
        if z[0] < 0.25:                                     # too foreshortened to read next to the limb
            return
        X, Y = to_out(x, y)
        X, Y = float(X[0]), float(Y[0])
        if m < X < W - m and m < Y < H - m:
            labels.append(text_label(fonts, txt, X + 4 * font_scale, Y - 8 * font_scale, size, STYLE['grid_label'], anchor='left'))
    t = np.arange(-180, 180.01, 0.5)
    lon_c = float(np.clip(round(geo.lon0 / step) * step, -80, 80)) if abs(geo.lon0) < 90 else 0.0
    for lat in range(-90 + step, 90, step):
        visible_runs(np.full_like(t, lat), t)
        label_at(lat, lon_c, '0°' if lat == 0 else f"{abs(lat)}° {'N' if lat > 0 else 'S'}")
    t = np.arange(-89.5, 89.51, 0.5)
    for lon in range(-180, 180, step):
        visible_runs(t, np.full_like(t, lon))
        if lon != lon_c:
            label_at(0.0, lon, f'{abs(lon)}°' if lon in (0, -180) else f"{abs(lon)}° {'E' if lon > 0 else 'W'}")
    return lines, labels


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def geodesic_px(geo, a, b, n=64):
    """Image px along the great circle between image points a and b (both on the disk), and its length in km."""
    la, lo, ok1 = geo.to_latlon(a[0], a[1])
    lb, lob, ok2 = geo.to_latlon(b[0], b[1])
    if not (ok1 and ok2):
        return None, None
    p, q = _unit(la, lo), _unit(lb, lob)
    om = math.acos(max(-1.0, min(1.0, float(p @ q))))
    km = om * R_MOON
    if om < 1e-9:
        return np.array([a, b], float), 0.0
    t = np.linspace(0, 1, n)[:, None]
    r = (np.sin((1 - t) * om) * p + np.sin(t * om) * q) / math.sin(om)
    x, y, _ = geo.to_image(np.degrees(np.arcsin(r[:, 2])), np.degrees(np.arctan2(r[:, 1], r[:, 0])))
    return np.stack([x, y], 1), km


def fmt_km(km):
    return f'{km:.0f} km' if km >= 100 else f'{km:.1f} km' if km >= 10 else f'{km:.2f} km'


SHAPE_GEOMETRY = dict(circle=('cx', 'cy', 'r'), ellipse=('x0', 'y0', 'x1', 'y1'), rect=('x0', 'y0', 'x1', 'y1'),
                      arrow=('x0', 'y0', 'x1', 'y1'), text=('x', 'y'), outline=(), measure=())


def _num(v):
    """A finite JSON number, else None (bools are not numbers here)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _point(p):
    """{x, y} -> dict, or None."""
    if not isinstance(p, dict):
        return None
    x, y = _num(p.get('x')), _num(p.get('y'))
    return None if x is None or y is None else dict(x=x, y=y)


def clean_shape(s):
    """One of the viewer's drawings with only the fields it and the export know, correctly typed, or None when it
    cannot be drawn (unknown kind, missing or non-finite geometry). Used when saving and again when exporting."""
    if not isinstance(s, dict) or s.get('kind') not in SHAPE_GEOMETRY:
        return None
    kind = s['kind']
    out = dict(kind=kind)
    for k in SHAPE_GEOMETRY[kind]:
        out[k] = _num(s.get(k))
        if out[k] is None:
            return None
    if kind == 'circle' and out['r'] < 0:
        return None
    if kind == 'outline':
        pts = s.get('pts')
        if not isinstance(pts, list) or len(pts) < 2:
            return None
        clean = []
        for p in pts[:10000]:
            if not isinstance(p, list) or len(p) != 2 or None in (xy := [_num(v) for v in p]):
                return None
            clean.append(xy)
        out['pts'] = clean
        if s.get('closed'):
            out['closed'] = True
    if kind == 'measure':
        out['a'], out['b'] = _point(s.get('a')), _point(s.get('b'))
        if out['a'] is None or out['b'] is None:
            return None
    if isinstance(s.get('colour'), str):
        out['colour'] = s['colour'][:32]
    if (size := _num(s.get('size'))) is not None:
        out['size'] = min(3.0, max(0.5, size))
    if isinstance(s.get('label'), str):
        out['label'] = s['label'][:500]
    if isinstance(s.get('font'), str) and s['font']:
        out['font'] = s['font'][:100]
    if s.get('dash'):
        out['dash'] = True
    return out


def clean_label_override(v):
    """A name's placement / style override from the viewer ({dx, dy, colour, size}), correctly typed, or None."""
    if not isinstance(v, dict):
        return None
    out = {}
    dx, dy = _num(v.get('dx')), _num(v.get('dy'))
    if dx is not None and dy is not None:
        out['dx'], out['dy'] = dx, dy
    if isinstance(v.get('colour'), str) and v['colour']:
        out['colour'] = v['colour'][:32]
    if (size := _num(v.get('size'))) is not None:
        out['size'] = min(3.0, max(0.5, size))
    return out or None


def shapes_overlay(shapes, geo, view, fonts_for, font_scale=1.0):
    """The viewer's drawings (image px, as saved in the sidecar's edits) in output px. fonts_for(family) -> Fonts.
    Kinds: circle, ellipse, rect, outline, arrow, text, measure. Returns (lines, labels)."""
    to_out, scale = view_mapper(view)
    lines, labels = [], []
    for s in shapes if isinstance(shapes, list) else ():
        s = clean_shape(s)
        if s is None:
            continue                                     # a damaged or unknown shape in the sidecar is skipped
        kind = s['kind']
        col = hex_rgba(s.get('colour'), 255)
        size = s.get('size', 1.0)
        width = max(1.0, 1.6 * size * font_scale)
        dash = (7 * font_scale, 5 * font_scale) if s.get('dash') else None
        pts = None
        try:
            if kind == 'circle':
                t = np.linspace(0, 2 * math.pi, 96, endpoint=False)
                pts = np.stack(to_out(s['cx'] + s['r'] * np.cos(t), s['cy'] + s['r'] * np.sin(t)), 1)
            elif kind == 'ellipse':
                t = np.linspace(0, 2 * math.pi, 96, endpoint=False)
                cx, cy = (s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2
                rx, ry = abs(s['x1'] - s['x0']) / 2, abs(s['y1'] - s['y0']) / 2
                pts = np.stack(to_out(cx + rx * np.cos(t), cy + ry * np.sin(t)), 1)
            elif kind == 'rect':
                xs, ys = [s['x0'], s['x1'], s['x1'], s['x0']], [s['y0'], s['y0'], s['y1'], s['y1']]
                pts = np.stack(to_out(np.array(xs, float), np.array(ys, float)), 1)
            elif kind == 'outline':
                p = np.asarray(s['pts'], float)
                pts = np.stack(to_out(p[:, 0], p[:, 1]), 1)
            elif kind == 'arrow':
                a = np.array(to_out(s['x0'], s['y0']), float)
                b = np.array(to_out(s['x1'], s['y1']), float)
                ang, h = math.atan2(b[1] - a[1], b[0] - a[0]), 11 * size * font_scale
                head = [b - h * np.array([math.cos(ang - 0.45), math.sin(ang - 0.45)]), b,
                        b - h * np.array([math.cos(ang + 0.45), math.sin(ang + 0.45)])]
                lines.append(dict(pts=np.array([a, b]), colour=col, width=width, dash=dash))
                lines.append(dict(pts=np.array(head), colour=col, width=width))
            elif kind == 'measure':
                g, km = geodesic_px(geo, (s['a']['x'], s['a']['y']), (s['b']['x'], s['b']['y']))
                if g is None:
                    continue
                P = np.stack(to_out(g[:, 0], g[:, 1]), 1)
                mcol = hex_rgba(s.get('colour') or '#f5a742', 255)
                lines.append(dict(pts=P, colour=mcol, width=max(1.0, 2 * font_scale)))
                for e in (P[0], P[-1]):
                    t = np.linspace(0, 2 * math.pi, 16, endpoint=False)
                    r = 3.5 * font_scale
                    lines.append(dict(pts=np.stack([e[0] + r * np.cos(t), e[1] + r * np.sin(t)], 1), colour=mcol,
                                      width=1, closed=True, fill=mcol))
                mid = P[len(P) // 2]
                labels.append(text_label(fonts_for(s.get('font')), fmt_km(km), mid[0], mid[1] - 16 * font_scale,
                                         max(8, int(round(14 * font_scale))), (255, 255, 255, 250), weight=600))
                continue
        except (KeyError, TypeError, ValueError):
            continue                                     # a damaged shape in the sidecar is skipped, never fatal
        if pts is not None:
            lines.append(dict(pts=pts, colour=col, width=width, dash=dash, closed=kind != 'outline' or bool(s.get('closed'))))
        if s.get('label'):
            if kind == 'text':
                ax, ay = to_out(s['x'], s['y'])
            elif kind == 'arrow':
                ax, ay = to_out(s['x0'], s['y0'])
                ay += 14 * font_scale
            elif pts is not None:
                ax, ay = pts[:, 0].mean(), pts[:, 1].max() + 14 * font_scale
            else:
                continue
            labels.append(text_label(fonts_for(s.get('font')), s['label'], float(ax), float(ay),
                                     max(8, int(round(15 * size * font_scale))), col, weight=500 if kind == 'text' else 520))
    return lines, labels


def capture_time(image):
    """SharpCap / WinJUPOS name 'YYYY-MM-DD-HHMM_T-…' (UTC; T = tenths of a minute) of the image, or for a
    mosaic the span of its panels (from IMAGE's _layout.json). Returns a text or None."""
    pat = re.compile(r'(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})_(\d)')

    def stamp(name):
        m = pat.search(os.path.basename(name))
        return None if not m else (f'{m[1]}-{m[2]}-{m[3]}', f'{m[4]}:{m[5]}')
    s = stamp(image)
    if s:
        return f'{s[0]} {s[1]} UTC'
    lay = os.path.splitext(image)[0] + '_layout.json'
    alt = os.path.join(os.path.dirname(image), 'mosaic_layout.json')
    for p in (lay, alt):
        if os.path.exists(p):
            try:
                with open(p) as fh:
                    panels = json.load(fh).get('panels', {})
                st = sorted(filter(None, (stamp(v.get('path', k)) for k, v in panels.items())))
                if st:
                    day = st[0][0]
                    return f'{day} {st[0][1]}–{st[-1][1]} UTC' if st[0] != st[-1] else f'{day} {st[0][1]} UTC'
            except (OSError, ValueError, AttributeError):
                pass
    return None


def info_block(geo, view, fonts, font_scale=1.0, date=None, optics=None, title=None):
    """Bottom-left panel: title, capture time, optics, image scale with a scale bar, and N / E arrows.
    Returns (lines, labels, box in output px)."""
    to_out, scale = view_mapper(view)
    W, H = view[3], view[4]
    fs = font_scale
    pad, gap = 12 * fs, 6 * fs
    km_px = geo.km_per_px / scale
    rows = [t for t in (title, date, optics, f'{km_px:.2f} km/px') if t]
    size, big = max(8, int(round(13 * fs))), max(9, int(round(15 * fs)))
    nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
    bar_km = max([n for n in nice if n / km_px <= 170 * fs] or [nice[0]])
    bar = bar_km / km_px
    arrow = 30 * fs
    width = max(max(fonts.get(500, big if i == 0 and title else size).getlength(t) for i, t in enumerate(rows)), bar + 50 * fs) \
        + 2 * pad + 2 * arrow + 30 * fs
    height = max(pad * 2 + len(rows) * (size + gap) + (big - size if title else 0) + 26 * fs, 2 * arrow + 2 * pad + 24 * fs)
    x0, y1 = 24 * fs, H - 24 * fs
    y0 = y1 - height
    lines = [dict(pts=np.array([[x0, y0], [x0 + width, y0], [x0 + width, y1], [x0, y1]], float),
                  fill=(12, 14, 18, 150), colour=None, width=0)]
    labels, y = [], y0 + pad
    for i, t in enumerate(rows):
        sz = big if i == 0 and title else size
        y += sz * 0.72 / 2 + gap / 2
        labels.append(text_label(fonts, t, x0 + pad, y, sz, (240, 240, 240, 245), weight=600 if i == 0 and title else 450,
                                 anchor='left'))
        y += sz * 0.72 / 2 + gap
    by = y1 - pad - 6 * fs
    bx = x0 + pad
    white = (240, 240, 240, 245)
    lines.append(dict(pts=np.array([[bx, by], [bx + bar, by]]), colour=white, width=max(1, 2 * fs)))
    for xx in (bx, bx + bar):
        lines.append(dict(pts=np.array([[xx, by - 5 * fs], [xx, by + 5 * fs]]), colour=white, width=max(1, 1.5 * fs)))
    labels.append(text_label(fonts, f'{bar_km} km', bx + bar + 8 * fs, by, size, white, anchor='left'))
    # compass at the view centre's direction: north and east from the sky-plane axes through the affine
    cx, cy = x0 + width - pad - arrow - 10 * fs, y0 + height / 2
    for vec, name in ((np.array([0.0, 1.0]), 'N'), (np.array([1.0, 0.0]), 'E')):
        d = geo.A @ vec
        d = d / max(np.hypot(*d), 1e-9)
        tip = np.array([cx, cy]) + d * arrow
        base = np.array([cx, cy])
        lines.append(dict(pts=np.array([base, tip]), colour=white, width=max(1, 1.6 * fs)))
        a = math.atan2(d[1], d[0])
        h = 6 * fs
        lines.append(dict(pts=np.array([tip - h * np.array([math.cos(a - 0.5), math.sin(a - 0.5)]), tip,
                                        tip - h * np.array([math.cos(a + 0.5), math.sin(a + 0.5)])]), colour=white,
                          width=max(1, 1.6 * fs)))
        lp = tip + d * 10 * fs
        labels.append(text_label(fonts, name, float(lp[0]), float(lp[1]), size, white, weight=600))
    return lines, labels, (x0, y0, x0 + width, y1)
