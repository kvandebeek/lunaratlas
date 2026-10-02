"""`lunaratlas.py view IMAGE`: the local viewer and editor.

A small HTTP server on 127.0.0.1 serves the page (viewer/), the image as a JPEG tile pyramid (cached per image in
the user's cache folder (atlas_paths), rebuilt when the image changes), the feature list in the image's geometry, the fonts
of lunaratlas/fonts, the user's edits (kept in IMAGE.atlas.json under "edits") and a real export that runs
`lunaratlas.py export` in a separate process and reports its progress.
"""
import hashlib
import hmac
import html
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import socket
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

from atlas_geo import (DATA, PPD, R_MOON, Reference, image_signature, load_geo, resolve_sidecar, sidecar_path,
                       sky_to_latlon, unit, write_json_atomic)
from atlas_names import load_features
from atlas_paths import (CACHE as CACHE_ROOT, FONTS as BUNDLED_FONTS, cv_imread, cv_imwrite, file_lock, private_dir,
                         self_command, temp_beside, user_dir)
from atlas_render import BUNDLED, FONT_DIR, Fonts, clean_label_override, clean_shapes, light_levels, rim_polygons

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'viewer')
CACHE = os.path.join(CACHE_ROOT, 'tiles')
TILE = 512
TILE_RENDER_VERSION = 2   # bump whenever build_tiles()'s own pixel processing changes (bugs-overview BUG-18: an
                          # unchanged image signature alone cannot tell an old, too-dark pyramid apart from a
                          # correct one) -- this invalidates both the on-disk pyramid and every browser-cached
                          # tile URL, independent of the edit/session revision tracked elsewhere
VIEWER_FONTS = BUNDLED                          # shipped with the app: the viewer never waits for a download
EDITS_SCHEMA = 'lunaratlas.edits/1'
MAX_JSON = 16 << 20                             # the biggest request body the page can send (the edits: 5000 shapes)
CACHE_LIMIT = 2 << 30                           # cached tiles + launcher thumbnails; least-recently used entries go first


# ---------------------------------------------------------------- tiles
def tile_dir(image):
    key = hashlib.sha1(os.path.abspath(image).encode()).hexdigest()[:16]
    return os.path.join(CACHE, key)


def cache_size(path):
    """Bytes of a cache entry: the file's own size, or the total below a folder. A thumbnail is a single file, so
    os.walk() alone would count it as zero and the limit would never be enforced. A disappearing entry counts as zero."""
    try:
        if not os.path.isdir(path):
            return os.path.getsize(path)
        return sum(os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(path) for f in files)
    except OSError:
        return 0


def evict_cache(limit=CACHE_LIMIT, keep=()):
    """Remove stale cache entries, then oldest entries until under ``limit``.

    Tile folders record their source image and signature in meta.json.  A
    thumbnail has no source metadata, so its file mtime is its LRU clock.  The
    caller may protect files/folders it is about to serve or build.
    """
    protected = {os.path.abspath(p) for p in keep}
    entries = []
    for root, is_tiles in ((CACHE, True), (os.path.join(CACHE_ROOT, 'thumbs'), False)):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            path = os.path.join(root, name)
            is_protected = os.path.abspath(path) in protected
            stale = False
            if is_tiles and not is_protected:
                try:
                    with open(os.path.join(path, 'meta.json')) as fh:
                        meta = json.load(fh)
                    image = meta.get('image')
                    stale = not isinstance(image, str) or not os.path.exists(image) or meta.get('signature') != image_signature(image)
                except (OSError, ValueError, TypeError):
                    stale = True
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            entries.append([path, cache_size(path), mtime, stale, is_protected])
    total = sum(e[1] for e in entries)
    for path, size, _, stale, is_protected in sorted(entries, key=lambda e: (not e[3], e[2])):
        if is_protected:
            continue
        if not stale and total <= limit:
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            total -= size
        except OSError:
            pass


def tile_version(image):
    """Part of every tile URL. The page caches tiles for a day by URL, so each image, and each change to it, needs URLs
    of its own: with bare /tiles/L/C_R.jpg the app window showed tiles of the photo opened before."""
    sig = image_signature(image)
    return hashlib.sha1(f"{os.path.abspath(image)}|{sig['size_bytes']}|{sig['mtime']}|{TILE_RENDER_VERSION}"
                        .encode()).hexdigest()[:12]


def as_loader(raw, image):
    """A function that gives the pixels: raw may be a function already, the array, or None (read the file)."""
    if raw is None:
        return lambda: read_image(image)
    return raw if callable(raw) else (lambda: raw)


def cached_loader(raw, image):
    """as_loader(raw, image), but calling the result more than once decodes the file at most once. A first open
    needs the full array twice over (build_tiles for the pyramid, night_side for the lighting): without this,
    Session.__init__ paid for two full decodes of the same photo (claude-findings.md C-18). Nothing outlives
    Session.__init__ holding this closure, so the decoded array is freed normally once it returns."""
    load = as_loader(raw, image)
    cache: list = []

    def get():
        if not cache:
            cache.append(load())
        return cache[0]
    return get


def tiles_complete(d, levels):
    """Every tile the manifest lists is there (a cleaned cache folder or a copied one can lose some)."""
    try:
        return all(os.path.getsize(os.path.join(d, str(i), f'{c}_{r}.jpg')) > 0
                   for i, L in enumerate(levels) for r in range(L['rows']) for c in range(L['cols']))
    except (OSError, KeyError, TypeError):
        return False


def read_image(image):
    raw = cv_imread(image, cv2.IMREAD_UNCHANGED)
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
        if (meta.get('signature') == sig and meta.get('tile') == TILE and
                meta.get('render') == TILE_RENDER_VERSION and tiles_complete(d, meta.get('levels'))):
            os.utime(d, None)                       # LRU recency for cache eviction
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
    g = raw if raw.ndim == 2 else raw[..., :3]      # a mono photo (the usual lunar capture) stays 2-D throughout:
    del raw                                        # converting it to 3 channels first only triples the memory and
                                                    # the JPEG size for tiles that would look identical either way
    if g.dtype != np.uint8:               # display stretch only (exports keep the original tonality)
        # bugs-overview BUG-18: `max(white, 1)` meant a valid 0-1 float image with a dim white point (e.g. 0.3)
        # was stretched as if white were 1, leaving it far too dark (alpha 250 instead of ~833); a NaN anywhere
        # in the sample poisoned the whole percentile. The white point is now taken from finite samples only,
        # and used as-is whenever it is positive, whatever its scale (0-1 float, raw 16-bit, or anything else).
        sample = g[::7, ::7]
        finite = sample[np.isfinite(sample)]
        white = float(np.percentile(finite, 99.95)) if finite.size else 0.0
        if not math.isfinite(white) or white <= 0:
            white = 0.0                                    # all-invalid or all-zero/negative: black, no warning
        # convertScaleAbs takes the absolute value, which would turn a negative sample bright; NaN/Inf pixels
        # (not just the sample above) are mapped to black rather than reaching the encoder unsanitized. g owns
        # its own buffer here (raw was already deleted above), so this is the only copy made, not an extra one.
        np.nan_to_num(g, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.clip(g, 0, None, out=g)
        g = cv2.convertScaleAbs(g, alpha=(250.0 / white if white > 0 else 0.0))
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
            done = list(ex.map(lambda rc: cv_imwrite(os.path.join(ld, f'{rc[1]}_{rc[0]}.jpg'),
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
    write_json_atomic(meta_p, dict(signature=sig, tile=TILE, render=TILE_RENDER_VERSION, levels=levels,
                                   image=os.path.abspath(image)))
    evict_cache(keep=(d,))
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


LIGHT_VERSION = 2       # bumped: the cache key now fingerprints the feature list itself, not just its length


def valid_light(light, feats):
    """A finite 1-D array with exactly one value per feats, or None (meaning "unknown": rendering already treats
    None as "do not dim anything", which is also the right default for a feature whose lighting could not be
    determined -- bugs-overview BUG-06/BUG-07). Never raises; never returns an array of the wrong shape for feats."""
    if light is None:
        return None
    try:
        a = np.asarray(light, float)
    except (TypeError, ValueError):
        return None
    if a.ndim != 1 or len(a) != len(feats) or not np.all(np.isfinite(a)):
        return None
    return a


def night_side(image, load_raw, geo, side, feats, xy, log):
    """Per feature how lit it is, kept beside the tiles: it needs the pixels (or the Sun's elevation for a close-up), and
    opening the image again with the same positioning must not decode a 200 MP picture to learn it again."""
    load_raw = as_loader(load_raw, image)
    closeup = bool((side.get('quality') or {}).get('closeup'))
    sig = image_signature(image)
    # the ordered feature identities, not just their count: two catalogues of the same length in a different
    # order (or a different one entirely) must not reuse each other's cached lighting (bugs-overview BUG-07)
    fp = [(f.get('name'), round(f.get('lat', 0.0), 6), round(f.get('lon', 0.0), 6)) for f in feats]
    key = hashlib.sha1(json.dumps([LIGHT_VERSION, sig, geo.as_dict(), closeup, (side.get('quality') or {}).get('capture_utc'),
                                   fp], sort_keys=True, default=str).encode()).hexdigest()
    p = os.path.join(tile_dir(image), 'light.json')
    try:
        with open(p) as fh:
            c = json.load(fh)
        if c.get('key') == key:
            cached = valid_light(c.get('light'), feats)
            if cached is not None:
                return cached
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if closeup:
        from lunaratlas import sun_elevation_light         # a close-up has no sky: the Sun's elevation decides
        light = sun_elevation_light(image, feats)
    else:
        light = light_levels(load_raw(), geo, feats, xy)
    # unknown/malformed lighting (no usable capture time for a close-up, or anything else producing a value that
    # does not fit feats) keeps every label visible as if lit, rather than crashing building light.json or
    # silently misassociating values with the wrong features once rendered (bugs-overview BUG-06/BUG-07)
    light = valid_light(light, feats)
    if light is None:
        return None
    try:
        write_json_atomic(p, dict(key=key, light=[float(v) for v in light]))
    except SystemExit:
        log('could not keep the night side beside the tiles')
    return light


DISK_PX = 640            # the whole Moon the viewer draws behind a close-up: big enough to read maria and the terminator


def moon_disk(geo, sun=None, px=DISK_PX):
    """The whole Moon as this image's geometry sees it, as a grayscale array on black (space): the LROC WAC
    albedo, shaded Lommel-Seeliger by the terminator when the capture time gives a Sun, so a close-up can be
    zoomed out onto a real globe instead of an empty wireframe. None when the albedo map is not cached yet —
    the viewer must never download 44 MB just to draw a background."""
    p = os.path.join(DATA, 'wac_emp_643_nearside.png')
    try:
        ref = cv_imread(p, cv2.IMREAD_GRAYSCALE)
    except Exception:                                        # noqa: BLE001  (a damaged map is just no background)
        ref = None
    if ref is None or ref.shape != Reference.SHAPE:
        return None
    n = int(px)
    half = n / 2 - 1
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    # the sky plane about the sub-observer point: x east, y north, one unit = the Moon's radius
    sx, sy = (xx - (n - 1) / 2) / half, -((yy - (n - 1) / 2) / half)
    lat, lon, ok = sky_to_latlon(sx, sy, geo.lat0, geo.lon0, geo.dist)
    lat = np.where(ok, lat, 0.0)
    lon = np.where(ok, lon, 0.0)
    surf = np.stack([np.cos(np.radians(lat)) * np.cos(np.radians(lon)),
                     np.cos(np.radians(lat)) * np.sin(np.radians(lon)),
                     np.sin(np.radians(lat))], -1)
    e = unit(geo.lat0, geo.lon0)
    mu = np.clip(surf @ e, 0.05, None)                         # emission: clamp so the limb cannot blow up
    if sun is None:                                           # no capture time: a full, evenly lit disk
        mu0 = np.ones_like(mu)
    else:
        mu0 = np.clip(surf @ unit(*sun), 0, None)              # incidence
    shade = mu0 / (mu0 + mu)                                  # Lommel-Seeliger: the flat full disk's classic falloff
    mx = ((lon + 90.0) * PPD).astype(np.float32)
    my = ((60.0 - lat) * PPD).astype(np.float32)
    a = cv2.remap(ref, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    # The near-side map covers only +-60 deg of latitude and +-90 of longitude; a hard cut to a flat grey would
    # draw a visible straight seam and a notch across the north of the disk. Fade the map into neutral highlands
    # over the last few degrees instead, so the limb still reads as a smooth sphere.
    edge = np.minimum(59.5 - np.abs(lat), 89.5 - np.abs(lon))
    w = np.clip(edge / 4.0, 0.0, 1.0)
    maria = 0.28 + 0.72 * (a / 255.0)
    bright = w * maria + (1.0 - w) * 0.55
    img = np.where(ok & (surf @ e > 0), shade * bright, 0.0)    # off the limb is space: black
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def disk_png_bytes(disk, px=DISK_PX):
    """The rendered disk as a PNG, for the page's <img> (grayscale, so it is a small file)."""
    ok, buf = cv2.imencode('.png', disk, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return buf.tobytes() if ok else None


def page_data(image, load_raw, geo, side, levels, log):
    load_raw = as_loader(load_raw, image)
    H, W = side.get('height'), side.get('width')
    if not (isinstance(H, int) and isinstance(W, int)):
        H, W = load_raw().shape[:2]
    feats = load_features(log, sites=True)
    lat = np.array([f['lat'] for f in feats]); lon = np.array([f['lon'] for f in feats])
    x, y, z = geo.to_image(lat, lon)
    light = night_side(image, load_raw, geo, side, feats, np.stack([x, y], 1), log)
    if light is None:          # unknown lighting (bugs-overview BUG-06): every feature is treated as fully lit,
        light = np.ones(len(feats))   # the same "do not dim anything" meaning layout()'s own light=None already has
    visible = [(f, a, b, c, li) for f, a, b, c, li in zip(feats, x, y, z, light)
               if c >= 0.05 and -0.05 * W < a < 1.05 * W and -0.05 * H < b < 1.05 * H]
    rim_i = [i for i, (f, *_rest) in enumerate(visible) if f['cls'] in ('crater', 'lettered', 'apollo') and f['diam'] > 0]
    ellipses = {}
    if rim_i:
        rf = [visible[i][0] for i in rim_i]
        polygons, _ = rim_polygons(geo, [f['lat'] for f in rf], [f['lon'] for f in rf], [f['diam'] for f in rf], 24)
        for i, pts in zip(rim_i, polygons):
            (ex, ey), (ew, eh), ang = cv2.fitEllipse(pts.astype(np.float32))
            ellipses[i] = [round(ex, 1), round(ey, 1), round(ew / 2, 1), round(eh / 2, 1), round(ang, 1)]
    rows = []
    for i, (f, a, b, c, li) in enumerate(visible):
        r = dict(n=f['name'], c=f['cls'], t=f['type'].split(',')[0], la=round(f['lat'], 3), lo=round(f['lon'], 3),
                 d=round(f['diam'], 2), x=round(float(a), 1), y=round(float(b), 1), z=round(float(c), 3),
                 lit=round(float(min(li, 1.5)), 2), o=f['origin'], k=link_id(f['link']))
        if i in ellipses:
            r['e'] = ellipses[i]
        rows.append(r)
    log(f'{len(rows)} features on the visible side')
    from atlas_ephem import capture_time as taken_at, sky_text
    when = taken_at(image)
    return dict(image=os.path.basename(image), sky=sky_text(when) if when else None, width=W, height=H, tile=TILE, levels=levels, tiles_v=tile_version(image),
                geometry=geo.as_dict(), radius_px=geo.radius_px, km_per_px=geo.km_per_px, R_moon=R_MOON,
                quality=side.get('quality', {}), gate=(side.get('quality_gate') or {}).get('line'),
                globe=2 * geo.radius_px > 1.15 * max(W, H),      # a close-up: the Moon is far bigger than the
                features=rows, grid=graticule(geo), fonts=[f for f in VIEWER_FONTS if font_files(f)])
                # frame, so there is a real globe to zoom out onto (see Session.disk)


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
    _, d = resolve_sidecar(image)
    e = d.get('edits') if isinstance(d, dict) and 'problem' not in d else None
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


def edits_rev(d):
    """The sidecar's own last-committed edit revision (0 if it has none), the durable cross-process authority for
    BUG-04/BUG-14: unlike an in-memory Session.rev, this survives a server restart and is visible to every process
    that opens the same sidecar. Kept as a sidecar-level key sibling to 'edits' (not inside it), the same way 'rev'
    was already kept out of the 'edits' object the page sends and receives, so the wire format the page and the
    existing tests rely on is unchanged: '/edits' returns the edits content with 'rev' as its own top-level field,
    never nested in the content old sidecars already parse."""
    r = d.get('edits_rev') if isinstance(d, dict) else None
    return r if isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r) else 0


def write_edits(image, e, lock, rev=None):
    """(committed, edits, committed_rev). The sidecar with the viewer's edits, written only if rev is not behind
    the sidecar's own durable revision -- the read of that revision, the comparison, and the write are one
    operation under one lock (process-local `lock` plus the cross-process file_lock), closing the gap where the
    old code checked and advanced an in-memory revision, released the lock, and only then reacquired it to write
    (bugs-overview BUG-04). rev=None (no usable revision on the request) writes unconditionally without advancing
    the durable counter, matching a page that sends no revision at all.

    A sidecar that has gone or turned to something else is never a traceback: the edits are dropped with a message
    the page shows, and the geometry is left alone. A validated legacy sidecar is migrated to the canonical
    per-extension path on this write (bugs-overview BUG-05); the legacy file itself is left in place."""
    canonical = sidecar_path(image)
    with lock, file_lock(canonical):
        _, d = resolve_sidecar(image)
        if d is None or 'problem' in d:
            reason = d['problem'] if isinstance(d, dict) and 'problem' in d else 'no sidecar'
            raise ValueError(f'cannot read a sidecar for {os.path.basename(image)} ({reason}): '
                             'locate the image again before editing it')
        current = edits_rev(d)
        if rev is not None and rev < current:
            return False, d.get('edits') if isinstance(d.get('edits'), dict) else {}, current
        new_rev = current if rev is None else rev
        d['edits'] = clean_edits(e)
        d['edits']['saved'] = time.strftime('%Y-%m-%d %H:%M:%S')
        d['edits_rev'] = new_rev
        write_json_atomic(canonical, d, indent=1)
        return True, d['edits'], new_rev


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
        with self.proc.stdout:
            for line in self.proc.stdout:
                line = line.rstrip()
                if line and 'WARN' not in line:
                    self.lines.append(line)
        code = self.proc.wait()
        if code == 0 and os.path.exists(self.output):
            self.state = 'done'
        elif code == 0:
            # the command exited cleanly but never wrote its result: a real but confusing case (not a message to
            # surface the last printed line for, which usually reads as a success -- e.g. "saved NAME.atlas.json" --
            # and would make a genuine problem look like nonsense on the page)
            self.state = 'failed'
            name = os.path.basename(self.output[:-len('.atlas.json')]) if self.output.endswith('.atlas.json') \
                else os.path.basename(self.output)
            self.error = f'{name} finished without saving its result'
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
    else:
        # "Full size" chosen explicitly: unlike the environment/.env default, '--max-size' on the command line has
        # no "uncapped" sentinel (0 fails cmd_export's own "--max-size must be at least 1 px" check), so a large
        # value within tool_settings' own LUNARATLAS_MAX_SIZE range (0-100000) is sent instead -- bigger than any
        # real capture, so it never actually caps, but it does override a nonzero environment/.env value that
        # would otherwise silently shrink an export the dialog says is full size (bugs-overview BUG-01)
        args += ['--max-size', '100000']
    # Every one of these is a choice the dialog makes explicitly, with its own default (bugs-overview BUG-01): an
    # export must carry out that choice as given, not fall back onto whatever the environment/.env happens to say
    # for the same-named CLI flag whenever the dialog's own default happens to match the CLI's. Both polarities of
    # every boolean are emitted, '--night' is always emitted from a whitelist (never omitted for 'hide', which is
    # the dialog's own default but not the CLI's), and '--lettered'/'--landing' are derived from the layer list and
    # sent explicitly so the CLI's own --lettered/--landing switches (driven by the environment too) cannot
    # re-discard a layer the dialog's list included.
    layers = [l for l in o.get('layers', []) if l in ('area', 'crater', 'lettered', 'relief', 'landing')]
    if not o.get('names', True) or not layers:
        args += ['--layers', 'none']
    else:
        args += ['--layers', ','.join(layers)]
    args.append('--lettered' if 'lettered' in layers else '--no-lettered')
    args.append('--landing' if 'landing' in layers else '--no-landing')
    for on, off, key in (('--rims', '--no-rims', 'rims'), ('--grid', '--no-grid', 'grid'),
                         ('--drawings', '--no-drawings', 'drawings'), ('--info', '--no-info', 'info')):
        args.append(on if o.get(key, True) else off)
    args += ['--night', o['night'] if o.get('night') in ('hide', 'dim', 'show') else 'hide']
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
        load_raw = cached_loader(raw, image)
        levels = build_tiles(image, load_raw, log)
        evict_cache(keep=(tile_dir(image),))         # also clean stale entries on a repeat open, when no pyramid is rebuilt
        self.data = page_data(image, load_raw, geo, side, levels, log)
        self._json: dict[bool, bytes] = {}
        self.tiles = tile_dir(image)
        # The whole Moon behind a close-up, drawn from the cached LROC albedo and shaded by the terminator.
        # Only for a close-up (the disk larger than the photo): for a full-disk photo the tiles ARE the Moon.
        # Absent when the albedo map is not cached, and never downloaded here.
        self.disk = None
        if self.data.get('globe'):
            from atlas_ephem import capture_time as _taken_at, ephemeris
            _t = _taken_at(image)
            _sun = None
            if _t is not None:
                try:
                    _e = ephemeris(_t)
                    _sun = (_e['sub_sun_lat'], _e['sub_sun_lon'])
                except (ValueError, TypeError, ArithmeticError):
                    _sun = None
            _d = moon_disk(geo, _sun)
            self.disk = disk_png_bytes(_d) if _d is not None else None
        self.lock = threading.Lock()
        _, _side = resolve_sidecar(image)           # seed from the durable sidecar revision, not 0: a server
        self.rev = edits_rev(_side) if isinstance(_side, dict) else 0   # restart must not look older than a
                                                     # pending browser snapshot that the sidecar already has (BUG-14)
        self.job: ExportJob | None = None
        self.sid = self.data['tiles_v']             # identifies this open image (and its version) to the page: a
                                                     # page that still shows a previous session's image must not
                                                     # write into this one's sidecar or read this one's export job

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
    reopened = -1e9                             # when the no-key page last asked for a tab with the key
    request_queue_size = 128                    # the default 5 makes Windows refuse a burst of connections (16 at once did)

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
        for an mDNS timeout before the page is served.

        On Windows, SO_REUSEADDR (inherited from HTTPServer as allow_reuse_address=True) has weaker semantics
        than on POSIX: it can let a second process bind the SAME port while the first is still actively
        listening, instead of only during TIME_WAIT. That defeats start_server()'s probe-the-next-free-port
        loop below -- two servers can end up both bound to what the caller thinks is one port, with cookie and
        image-session confusion between them (bugs-overview BUG-12). SO_EXCLUSIVEADDRUSE is Windows' own
        corrective: no other process, with or without SO_REUSEADDR, may bind this port while this one holds it."""
        if sys.platform == 'win32':
            self.allow_reuse_address = False               # do not ask the stdlib to set SO_REUSEADDR here
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
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

    def this_host(self):
        """Host is localhost/127.0.0.1/[::1] (DNS rebinding guard). Checked on every request, token or not."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        return host in ('localhost', '127.0.0.1', '[::1]')

    def same_site(self):
        """A request another site's page makes (Origin, or Sec-Fetch-Site: a <script> or <img> include sends no
        Origin) is refused. Not applied to the one-time `?t=` entry link in enter(): knowing the unguessable token
        is itself the proof of legitimacy that this check exists to approximate, and that link is only ever reached
        by navigating from a page this app wrote itself (the handoff redirect), which browsers correctly tag
        Sec-Fetch-Site: cross-site since it is a file:// page -- rejecting it here would lock the launcher's own
        "already running" hand-off out of its own server."""
        if self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            return False
        origin = self.headers.get('Origin')
        return origin is None or re.fullmatch(r'http://(localhost|127\.0\.0\.1|\[::1\]):%d' % self.srv.server_port,
                                              origin) is not None

    def local(self):
        return self.this_host() and self.same_site()

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
        """The link with the token (?t=…) sets the cookie and goes on to the same page without it. False: not that.

        It goes on with a page of its own (a meta refresh), not a 303: a redirect chain that a cross-site navigation
        started (the file:// hand-off page, see handoff_url) stays cross-site to its end, so the page it lands on
        would arrive as Sec-Fetch-Site: cross-site without the SameSite=Strict cookie, and be refused (Safari showed
        a 403 until a reload). A navigation this server's own page starts is same-origin and carries the cookie."""
        q = parse_qs(query, keep_blank_values=True)
        t = (q.pop('t', None) or [''])[0]
        if not (t and self.srv.token and hmac.compare_digest(t.encode(), self.srv.token.encode())):
            return False
        target = html.escape('/' + path.lstrip('/') + ('?' + urlencode(q, doseq=True) if q else ''), quote=True)  # never //host
        body = (f'<!doctype html><meta charset="utf-8"><title>LunarAtlas</title>'
                f'<meta http-equiv="refresh" content="0; url={target}">'
                f'<body>Opening LunarAtlas… <a href="{target}">click here</a> if nothing happens.</body>').encode()
        self.send_response(200)
        self.send_header('Set-Cookie', f'{self.srv.cookie_name}={self.srv.token}; Path=/; HttpOnly; SameSite=Strict')
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
        return True

    NO_KEY = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, '
              'initial-scale=1"><title>LunarAtlas</title><style>body{{margin:0;min-height:100vh;display:grid;'
              'place-items:center;background:#0A0F25;color:#FCF8EE;font:16px/1.55 "IBM Plex Sans",system-ui,'
              '-apple-system,"Segoe UI",sans-serif}}main{{max-width:520px;margin:24px 16px;padding:28px;background:#111934;'
              'border:1px solid rgba(255,255,255,.12);border-radius:14px}}h1{{margin:0 0 10px;font-size:22px;'
              'font-weight:600}}p{{margin:0 0 14px;color:#B7BFD8}}button{{height:44px;padding:0 20px;border:0;'
              'border-radius:10px;background:#F5A742;color:#1A1206;font-weight:600;font-size:15px;font-family:inherit;'
              'cursor:pointer}}button:hover{{background:#F8B963}}button:focus-visible{{outline:2px solid #F5A742;'
              'outline-offset:3px}}small{{display:block;margin-top:14px;color:#97A1C2;font-size:13px}}</style>'
              '<main>{body}</main></html>')

    def no_key(self, p):
        """A request without this run's key. A page someone opened by its address (typed, bookmarked, or a tab left
        from an earlier run, whose key is gone) gets a page that says so, with a button that asks LunarAtlas to open
        its own tab with the key; anything else, a plain 403."""
        page = p in ('/', '/index.html', '/app', '/settings') and (
            self.headers.get('Sec-Fetch-Dest') == 'document' or 'text/html' in (self.headers.get('Accept') or ''))
        if not page:
            return self.send_error(403)
        body = ('<h1>This address needs LunarAtlas’s key</h1><p>LunarAtlas only answers the window or tab it opened itself: '
                'every start has a new key, so a typed or bookmarked address, or a tab from an earlier start, cannot get '
                'in. That keeps other programs on this computer out.</p><form method="post" action="/app/reopen">'
                '<button>Open LunarAtlas</button></form><small>Or start LunarAtlas again from its icon.</small>')
        self.reply(self.NO_KEY.format(body=body).encode(), 'text/html; charset=utf-8', 403)

    def reopen(self):
        """The no-key page's button: LunarAtlas opens its own window or tab with the key (at most every few seconds).
        The page that asked never sees the key, so another program pressing it only gets a tab opened on the user's
        screen."""
        if self.headers.get('Content-Length'):
            try:
                self.rfile.read(self.length(4096))
            except ValueError:
                return self.send_error(400)
        now, app = time.monotonic(), self.srv.app
        if now - self.srv.reopened > 5:
            self.srv.reopened = now
            if app is not None and getattr(app, 'window', None) is not None:
                app.window.restore()
                app.window.show()
            else:
                path = '/app' if app is not None else '/'
                threading.Thread(target=webbrowser.open, args=(handoff_url(self.srv.url(path, secret=True)),),
                                 daemon=True).start()
        body = ('<h1>Opening LunarAtlas…</h1><p>A new tab (or the LunarAtlas window) opens with the key. You can close '
                'this one.</p>')
        self.reply(self.NO_KEY.format(body=body).encode(), 'text/html; charset=utf-8')

    def page(self):
        with open(os.path.join(PAGE, 'index.html'), 'rb') as fh:
            return fh.read()

    def do_GET(self):
        if not self.this_host():
            return self.send_error(403)
        p, _, query = self.path.partition('?')
        if p == '/app/ping' and 'nonce=' in query:        # asked by a second start, which has no cookie: proves, reveals nothing
            if not self.same_site():
                return self.send_error(403)
            return self.reply(b'lunaratlas:' + self.srv.prove((parse_qs(query).get('nonce') or [''])[0]).encode(), 'text/plain')
        if self.enter(p, query):      # the one-time ?t= link: see same_site()'s docstring for why this skips it
            return
        if not self.same_site():
            return self.send_error(403)
        if not self.authed():
            return self.no_key(p)
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
        if p in ('/edits', '/export/status') and self.session_gone(s, query):
            return
        if p == '/edits':
            with s.lock:                        # the durable sidecar revision is the cross-process authority;
                _, d = resolve_sidecar(s.image)  # a sibling process's write since this session opened is picked
                s.rev = max(s.rev, edits_rev(d) if isinstance(d, dict) else 0)   # up here, never only in memory
            return self.json(dict(read_edits(s.image), rev=s.rev))
        if p == '/export/status':
            return self.json(s.job.status() if s.job else dict(state='none'))
        if p == '/disk.png':
            if not s.disk:
                return self.send_error(404)
            return self.reply(s.disk, 'image/png', cache=True)
        m = re.fullmatch(r'/tiles/(\d+)/(\d+)_(\d+)\.jpg', p)
        if m:
            return self.file(os.path.join(s.tiles, m[1], f'{m[2]}_{m[3]}.jpg'), 'image/jpeg', cache=True)
        self.send_error(404)

    def session_gone(self, s, query):
        """True (after already answering 409) when the request names a session that is no longer the one open: the
        page still shows an image this server has since replaced or closed, so it must not read or write it. False
        (nothing sent) when the request either names no session (an older page, or a test that talks to the routes
        directly) or names this one."""
        sid = (parse_qs(query).get('sid') or [None])[0]
        if sid and sid != s.sid:
            self.json(dict(error='this image is no longer open here', gone=True), 409)
            return True
        return False

    def static(self, p):
        if p in ('/favicon.svg', '/lunaratlas.svg'):
            self.file(os.path.join(PAGE, 'lunaratlas.svg'), 'image/svg+xml', cache=True)
        elif p in ('/viewer.js', '/boot.js', '/app.js', '/viewer.css', '/theme.css', '/friendly.js', '/exif.js',
                   '/equipment.js', '/settings.js'):
            self.file(os.path.join(PAGE, p[1:]), 'text/javascript' if p.endswith('.js') else 'text/css')
        elif p == '/cameras.json':
            self.file(os.path.join(PAGE, 'cameras.json'), 'application/json', cache=True)
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
        p = self.path.split('?')[0]
        if p == '/app/reopen' and self.local():           # the no-key page's button: no key needed, none shown
            return self.reopen()
        if not self.local() or not self.authed():
            return self.send_error(403)
        app, s = self.srv.app, self.srv.session
        if app is not None and app.post(self, p):
            return
        if s is None:
            return self.send_error(404)
        try:
            if p == '/edits' and self.length(MAX_JSON) <= 0:
                # a missing/empty/chunked body would otherwise read as {} and erase every drawing, hidden name and
                # label move (a real save is always far bigger than this)
                return self.json(dict(error='the request has no body'), 400)
            o = self.body()
        except ValueError as e:
            return self.json(dict(error=str(e)), 413 if 'Content-Length' in str(e) else 400)
        if p in ('/edits', '/export') and not isinstance(o, dict):
            return self.json(dict(error='expected a JSON object'), 400)
        if p in ('/edits', '/export', '/reveal') and isinstance(o, dict):
            sid = o.pop('sid', None)                # which open image the page means: absent (an older page, a
            if sid and sid != s.sid:                # test) is allowed through; naming a session that has since
                return self.json(dict(error='this image is no longer open here', gone=True), 409)   # been replaced
                                                     # or closed is refused, so a page left open on a previous
                                                     # image cannot save into, export, or reveal a different one
        if p == '/edits':
            rev = o.pop('rev', None)                # the page numbers its saves: a late one never overwrites a newer one
            if not (isinstance(rev, (int, float)) and not isinstance(rev, bool) and math.isfinite(rev) and abs(rev) < 1e18):
                rev = None                           # not finite (Infinity/NaN) or absurdly large: ignored rather
                                                     # than accepted, so it can never permanently poison the durable
                                                     # revision and lock every future save out as "stale"
            try:
                # the read of the durable revision, the compare against it, and the write are ONE operation under
                # one lock (write_edits' combined `lock, file_lock`): the old code checked-and-advanced an
                # in-memory revision, released the lock, and only then reacquired it to write, so two overlapping
                # requests could both pass the check (bugs-overview BUG-04)
                ok, edits, committed = write_edits(s.image, o, s.lock, rev)
            except (OSError, ValueError, ArithmeticError, SystemExit) as e:
                # SystemExit: write_json_atomic -> write_atomic raises it on a write failure (full disk, a
                # read-only folder); the plain `except Exception`-shaped tuple here used to let it escape raw
                return self.json(dict(error=str(e)), 500)
            with s.lock:
                s.rev = max(s.rev, committed)
            if not ok:
                return self.json(dict(stale=True, rev=committed), 409)
            return self.json(edits)
        if p == '/export':
            with s.lock:                            # check-and-start under one lock: two clicks (or two tabs) must
                if s.job and s.job.state == 'running':      # not both pass the check and both start a process
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


def handoff_url(url):
    """A file:// URL that redirects a browser to url, for opening it instead of handing url itself to
    webbrowser.open(): that spawns the browser with url as a command-line argument, and on Linux (where the
    packaged app has no app window and always opens this way) another local user can read another process's
    argv from /proc, which would show this run's whole-lifetime access token in plain sight. The redirect file's
    own path is not secret, only its content (what it points to), so it is written private (mode 0600, this
    user only) and reused by every open (see claude-findings.md C-07)."""
    d = user_dir('data')
    private_dir(d)
    p = os.path.join(d, 'open.html')
    target = html.escape(url, quote=True)
    page = (f'<!doctype html><meta charset="utf-8"><title>LunarAtlas</title>'
           f'<meta http-equiv="refresh" content="0; url={target}">'
           f'<body>Opening LunarAtlas… <a href="{target}">click here</a> if nothing happens.</body>').encode()
    tmp = temp_beside(p)
    with open(tmp, 'wb') as fh:
        fh.write(page)
    if os.name == 'posix':
        os.chmod(tmp, 0o600)          # before the rename: never a moment where it is readable by anyone else
    os.replace(tmp, p)
    return 'file://' + os.path.abspath(p)


def run_server(srv, open_browser=True, log=print, path='/', what='viewer'):
    """Serve until Ctrl-C. The address with the token goes to the browser this opens; it is printed only when nothing
    is opened (then it is the way in: this terminal is the user's own), never into a log file."""
    log(f'{what}: {srv.url(path, secret=not open_browser)}  (Ctrl-C to stop)')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(handoff_url(srv.url(path, secret=True)))).start()
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
