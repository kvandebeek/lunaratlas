#!/usr/bin/env python3
"""moon_atlas — IAU names on your own lunar images (a QuickMap for your own data).

  locate IMAGE              work out where every pixel lies on the Moon; saves IMAGE.atlas.json
  export IMAGE [options]    labelled 16-bit TIFF / 16-bit PNG / JPEG at 1:1 or smaller
  info IMAGE                geometry and quality of the positioning
  find IMAGE NAME           where a named feature is in the image
  view IMAGE                browser viewer and editor (labels, search, km measuring, your own drawings, export)

Run `moon_atlas.py export -h` for the export options.
"""
import argparse
import json
import math
import re
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tool_settings as ts  # noqa: E402
from atlas_geo import fit_limb, load_geo, locate, resize, save_geo, sidecar_path, unresize, R_MOON   # noqa: E402
from atlas_names import load_features                                    # noqa: E402
from atlas_quality import luminance, measure, thresholds, verdict                   # noqa: E402
from atlas_render import (DEFAULT_FONT, LAYERS, Fonts, box_of, capture_time, draw, grid_overlay, info_block,  # noqa: E402
                          layout, light_levels, shapes_overlay)

T0 = time.perf_counter()


def log(*a):
    print(f'[{time.perf_counter() - T0:6.1f} s]', *a, flush=True)


def quality_gate(image):
    """Quality measures on the pixels (and the limb, when one is found): (ok, reasons, line, measures)."""
    raw = cv2.imread(image, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f'cannot read {image}')
    if raw.ndim == 3 and raw.shape[2] == 4:
        raw = raw[..., :3]
    g = luminance(raw)
    H, W = g.shape
    limb = None
    try:
        g0, (sx, sy) = resize(g, 1024.0 / max(W, H))
        cx, cy, R, share = fit_limb(g0)
        if share >= 0.25:
            (cx0, cy0), R0 = unresize((cx, cy), sx, sy), R / math.sqrt(sx * sy)
            limb = (float(cx0), float(cy0), float(R0))
    except SystemExit:
        pass
    del g
    q = measure(raw, limb)
    q['has_limb'] = limb is not None
    ok, reasons, line = verdict(q)
    return ok, reasons, line, q


def geometry(image, relocate=False, force=False, gate=True):
    """The image's positioning, located (and saved) when needed. With gate, an image the quality gate refuses is
    not annotated unless force; find and info pass gate=False and only report the verdict."""
    geo, d = (None, None) if relocate else load_geo(image)
    if geo is not None:
        log(f'positioning from {os.path.basename(sidecar_path(image))}')
        g = d.get('quality_gate')
        if g:
            log(g['line'])
            if gate and not g['ok'] and not force and not g.get('forced'):
                raise SystemExit('not annotated: the quality gate refused this image (use --force to annotate anyway)')
        return geo
    if d is not None:
        log(f"{d['problem']}: locating again")
    ok, reasons, line, qm = quality_gate(image)
    log(line)
    if not ok:
        if gate and not force:
            raise SystemExit('not annotated: ' + '; '.join(reasons) + '. Use --force to annotate anyway.')
        log('annotating anyway (--force)' if force else 'quality gate: not applied for this command')
    log(f'locating {os.path.basename(image)}')
    try:
        if not qm.get('has_limb'):
            raise SystemExit('no limb in view')
        from atlas_ephem import capture_time as _when
        geo, q = locate(image, log, when=_when(image))
    except SystemExit as e:
        # no usable limb (or the full-disk fit failed): a close-up, found blind from its time and optics
        from atlas_closeup import locate_closeup
        from atlas_ephem import capture_time
        if capture_time(image) is None:
            hint = f' The quality gate found: {"; ".join(reasons)}.' if reasons else ''
            raise SystemExit(f'{e}; a close-up needs its capture time in the name (SharpCap YYYY-MM-DD-HHMM_T-…).{hint}') from None
        log(f'{e}: searching the image as a close-up')
        try:
            geo, q = locate_closeup(image, log)
        except SystemExit as e2:
            hint = f' The quality gate found: {"; ".join(reasons)}.' if reasons else ''
            raise SystemExit(f'{e2}{hint}') from None
    keep = {k: v for k, v in qm.items() if k != 'profile'}
    p = save_geo(image, geo, q, q.pop('width'), q.pop('height'),
                 quality_gate=dict(ok=ok, forced=bool(force and not ok), reasons=reasons, line=line, measures=keep,
                                   thresholds=thresholds().get('version')))
    log(f'saved {p}')
    return geo


def project(feats, geo):
    lat = np.array([f['lat'] for f in feats]); lon = np.array([f['lon'] for f in feats])
    x, y, z = geo.to_image(lat, lon)
    for f, a, b, c in zip(feats, x, y, z):
        f['x'], f['y'], f['z'] = float(a), float(b), float(c)
    return feats


def optics_text(image):
    """The folder's optics (moon_atlas_optics.json, written by the optics prompt or the close-up search) as one line."""
    for d in (os.path.dirname(os.path.abspath(image)),):
        p = os.path.join(d, 'moon_atlas_optics.json')
        try:
            with open(p) as fh:
                o = json.load(fh)
            return o.get('text') or None
        except (OSError, ValueError, AttributeError):
            continue
    return None


def sun_elevation_light(image, feats):
    """Per feature 1 where the Sun is above its horizon (at the rim: its elevation plus the feature's angular radius),
    else 0, from the capture time in the name; None without a time."""
    from atlas_ephem import capture_time, ephemeris
    t = capture_time(image)
    if t is None:
        return None
    e = ephemeris(t)
    la, lo = np.radians(e['sub_sun_lat']), np.radians(e['sub_sun_lon'])
    s = np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
    lat = np.radians([f['lat'] for f in feats]); lon = np.radians([f['lon'] for f in feats])
    p = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], 1)
    elev = np.degrees(np.arcsin(np.clip(p @ s, -1, 1)))
    rad = np.degrees(np.array([max(f['diam'], 0.0) for f in feats]) / 2 / R_MOON)
    return (elev + rad > 0.0).astype(float)


def find_feature(feats, name):
    n = name.strip().lower()
    hit = [f for f in feats if f['name'].lower() == n] or [f for f in feats if f['name'].lower().startswith(n)]
    if not hit:
        raise SystemExit(f'no feature named "{name}"')
    return hit[0]


# ---------------------------------------------------------------- commands
def cmd_locate(a):
    geometry(a.image, relocate=True, force=a.force)


def cmd_info(a):
    geo, d = load_geo(a.image)
    if d is None:
        raise SystemExit('not located yet: run `moon_atlas.py locate IMAGE`')
    if geo is None:
        if not all(k in d for k in ('image', 'width', 'height', 'located', 'derived', 'quality')):
            raise SystemExit(f"{d['problem']}: run `moon_atlas.py locate IMAGE`")
        print(f"warning: {d['problem']}; run locate again")
    der, q = d['derived'], d['quality']
    print(f"{d['image']}  {d['width']} x {d['height']} px   located {d['located']}")
    print(f"  disk radius {der['radius_px']} px, {der['km_per_px']} km/px at the centre")
    na = der['north_angle_deg']
    turn = f'{360 - na:.1f}° clockwise' if na > 180 else f'{na:.1f}° counter-clockwise'
    print(f"  lunar north is rotated {turn} from up, {'mirrored' if der['mirrored'] else 'not mirrored'}")
    print(f"  libration: latitude {der['libration_lat']:+.2f}°, longitude {der['libration_lon']:+.2f}°")
    if all(k in q for k in ('matches', 'rms_px', 'correction_degree', 'seconds')):
        print(f"  {q['matches']} terrain matches, {q['rms_px']} px rms ({q['rms_px'] * der['km_per_px']:.2f} km), "
              f"correction degree {q['correction_degree']}, located in {q['seconds']} s")
    g = d.get('quality_gate')
    if isinstance(g, dict) and 'line' in g:
        print(f"  {g['line']}" + ('  [annotated anyway: --force]' if g.get('forced') else ''))


def cmd_find(a):
    geo = geometry(a.image, gate=False)
    f = find_feature(project(load_features(log, sites=True), geo), a.name)
    D = f['diam'] / R_MOON * geo.radius_px
    vis = 'visible' if f['z'] > 0.1 else ('at the limb' if f['z'] > 0 else 'on the far side')
    print(f"{f['name']} ({f['type']}): lat {f['lat']:+.3f}°, lon {f['lon']:+.3f}°, {f['diam']:.1f} km")
    print(f"  image x {f['x']:.0f} px, y {f['y']:.0f} px, ≈ {D:.0f} px across, {vis}")
    if f['origin']:
        print(f"  named after: {f['origin']}")


EXTENSIONS = {'tiff': ('.tif', '.tiff'), 'png': ('.png',), 'jpg': ('.jpg', '.jpeg')}


def output_plan(a):
    """(format, output path), checked before any work: the extension decides the encoder, so it must agree
    with --format, and the output may never be the input image or its sidecar."""
    ext = os.path.splitext(a.output)[1].lower() if a.output else ''
    from_ext = next((k for k, v in EXTENSIONS.items() if ext in v), None)
    if a.output and from_ext is None:
        raise SystemExit(f'-o {a.output}: unknown extension "{ext}" (use .tif, .png or .jpg)')
    if a.format and from_ext and a.format != from_ext:
        raise SystemExit(f'--format {a.format} contradicts -o {a.output} (a {from_ext} file name); '
                         f'use a {EXTENSIONS[a.format][0]} name or drop --format')
    fmt = a.format or from_ext or ts.get('MOON_ATLAS_FORMAT')
    tag = '_' + re.sub(r'[^\w.-]+', '_', a.around).strip('_') if a.around else ''    # "Luna 17 / Lunokhod 1" is one name
    out = a.output or f"{os.path.splitext(a.image)[0]}_atlas{tag}{EXTENSIONS[fmt][0]}"
    if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
        raise SystemExit(f'output folder {os.path.dirname(os.path.abspath(out))} does not exist')
    for keep in (a.image, sidecar_path(a.image)):
        if os.path.exists(out) and os.path.exists(keep) and os.path.samefile(out, keep):
            raise SystemExit(f'refusing to overwrite {keep}: choose another -o')
    return fmt, out


def parse_ints(text, n, what):
    try:
        v = [int(p) for p in text.replace('x', ',').replace('X', ',').split(',')]
    except ValueError:
        v = []
    if len(v) != n:
        raise SystemExit(f'{what}: expected {n} whole numbers, got "{text}"')
    return v


def parse_layers(text):
    if text is None:
        return set() if ts.get('MOON_ATLAS_LAYERS') == ['none'] else set(ts.get('MOON_ATLAS_LAYERS'))
    names = {v.strip().lower() for v in text.split(',') if v.strip()}
    if names == {'none'}:
        return set()
    unknown = names - set(LAYERS)
    if unknown:
        raise SystemExit(f"--layers: unknown {', '.join(sorted(unknown))} (use {','.join(LAYERS)} or none)")
    return names


def cmd_export(a):
    for name, v in (('--scale', a.scale), ('--font-scale', a.font_scale), ('--min-size', a.min_size)):
        if v is not None and not (math.isfinite(v) and v > 0):
            raise SystemExit(f'{name} must be a positive number')
    if a.scale is not None and a.scale > 1.0 + 1e-9:
        raise SystemExit('--scale above 1 would upscale beyond the captured resolution; not allowed')
    if a.max_size is not None and a.max_size < 1:
        raise SystemExit('--max-size must be at least 1 px')
    if not 0 <= a.quality <= 100:
        raise SystemExit('--quality must be 0 to 100')
    fmt, out = output_plan(a)
    layers = parse_layers(a.layers)
    if not a.lettered:
        layers.discard('lettered')
    if not a.landing:
        layers.discard('landing')
    if a.around:
        sw, sh = parse_ints(a.size, 2, '--size')
    elif a.region:
        x0, y0, sw, sh = parse_ints(a.region, 4, '--region x,y,w,h')
    if (a.around or a.region) and (sw < 1 or sh < 1):
        raise SystemExit('the view width and height must be at least 1 px')

    raw = cv2.imread(a.image, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f'cannot read {a.image}')
    geo = geometry(a.image, force=a.force)
    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    raw = raw[..., :3]
    if raw.dtype not in (np.uint8, np.uint16):          # float data (0–1, or already 0–65535) -> 16-bit
        kind, f32 = raw.dtype, raw.astype(np.float32)
        top = float(np.nanmax(f32)) if f32.size else 0.0
        raw = (np.clip(np.nan_to_num(f32) * (65535.0 if top <= 1.5 else 1.0), 0, 65535) + 0.5).astype(np.uint16)
        log(f'{kind} input converted to 16-bit ({"0–1" if top <= 1.5 else "0–65535"} scale)')
    H, W = raw.shape[:2]
    feats = project(load_features(log, sites=True), geo)      # all features can be looked up; layers filter labels

    # region in source pixels: the requested rectangle, cut to the image
    if a.around:
        f = find_feature(feats, a.around)
        if f['z'] < 0.1:
            raise SystemExit(f"{f['name']} is {'at the limb' if f['z'] > 0 else 'on the far side'}: nothing to show around it")
        x0, y0 = int(round(f['x'] - sw / 2)), int(round(f['y'] - sh / 2))
    elif not a.region:
        x0, y0, sw, sh = 0, 0, W, H
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + sw), min(H, y0 + sh)
    if xb <= xa or yb <= ya:
        raise SystemExit(f'the view (x {x0} y {y0}, {sw} x {sh} px) lies outside the {W} x {H} px image')
    x0, y0, sw, sh = xa, ya, xb - xa, yb - ya
    scale = a.scale or 1.0
    if a.max_size:
        scale = min(scale, a.max_size / max(sw, sh))
    ow, oh = max(1, round(sw * scale)), max(1, round(sh * scale))
    log(f'view: x {x0} y {y0}, {sw} x {sh} px source -> {ow} x {oh} px output (scale {scale:.3f})')

    light = light_levels(raw, geo, feats, [(f['x'], f['y']) for f in feats])   # night side, from the whole image
    if (load_geo(a.image)[1] or {}).get('quality', {}).get('closeup'):
        # a close-up has no sky to compare brightness with: the Sun's elevation from the capture time decides
        light = sun_elevation_light(a.image, feats)
    vw = (x0, y0, (ow / sw, oh / sh), ow, oh)
    edits = (load_geo(a.image)[1] or {}).get('edits') or {}
    a.font = a.font or (edits.get('style') or {}).get('font') or ts.get('MOON_ATLAS_FONT') or DEFAULT_FONT
    fonts = Fonts(a.font, log)
    families = {a.font: fonts}

    def fonts_for(family):
        family = family or a.font
        if family not in families:
            try:
                families[family] = Fonts(family, log)
            except SystemExit as e:                  # an unavailable font never stops an export
                log(f'{e}; using {a.font}')
                families[family] = fonts
        return families[family]
    over_lines, over_labels, reserved = [], [], []
    if a.drawings and edits.get('shapes'):
        sl, st = shapes_overlay(edits['shapes'], geo, vw, fonts_for, a.font_scale)
        over_lines += sl
        over_labels += st
        reserved += [box_of(l) for l in st]
        log(f"{len(edits['shapes'])} of your drawings")
    if a.info:
        il, it, box = info_block(geo, vw, fonts, a.font_scale, date=capture_time(a.image), optics=optics_text(a.image))
        over_lines += il
        over_labels += it
        reserved.append(box)
    grid_lines, grid_labels = grid_overlay(geo, vw, fonts, a.font_scale) if a.grid else ([], [])
    reserved += [box_of(l) for l in grid_labels]
    labels = layout(feats, geo, vw, fonts, min_px=a.min_size, font_scale=a.font_scale,
                    rims=a.rims, night=a.night, light=light, layers=layers,
                    hidden=edits.get('hidden', ()), overrides=edits.get('labels'), reserved=reserved)
    log(f'{len(labels)} labels placed' + (f" ({len(edits.get('hidden', []))} hidden in the viewer)" if edits.get('hidden') else ''))

    view = raw[y0:y0 + sh, x0:x0 + sw]
    img = view if (ow, oh) == (sw, sh) else cv2.resize(view, (ow, oh), interpolation=cv2.INTER_AREA)
    if fmt == 'jpg':          # 16-bit -> 8-bit keeps your tonality (value / 257)
        img = cv2.convertScaleAbs(img, alpha=1 / 257.0) if img.dtype == np.uint16 else img
    else:
        img = img.astype(np.uint16) * 257 if img.dtype == np.uint8 else img   # drawn in place: raw is not reused
    draw(img, grid_labels, fonts, a.font_scale, lines=grid_lines)
    draw(img, labels, fonts, a.font_scale)
    draw(img, over_labels, fonts, a.font_scale, lines=over_lines)
    log('labels drawn' + (' · lat/lon grid' if grid_lines else '') + (' · info block' if a.info else ''))

    if fmt == 'jpg':
        ok = cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, a.quality])
    elif fmt == 'png':
        ok = cv2.imwrite(out, img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    else:
        ok = cv2.imwrite(out, img, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
    if not ok:
        raise SystemExit(f'could not write {out}')
    log(f'wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)')


def cmd_view(a):
    from atlas_view import serve
    geo = geometry(a.image, force=a.force)
    geo, d = load_geo(a.image)
    raw = cv2.imread(a.image, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f'cannot read {a.image}')
    serve(os.path.abspath(a.image), geo, d, raw, port=a.port, open_browser=a.open, log=log)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('locate', help='position the image on the Moon (saves IMAGE.atlas.json)')
    s.add_argument('image')
    s.add_argument('--force', action='store_true', help='locate and annotate even if the quality gate refuses the image')
    s.set_defaults(fn=cmd_locate)
    s = sub.add_parser('info', help='show the saved positioning')
    s.add_argument('image'); s.set_defaults(fn=cmd_info)
    s = sub.add_parser('find', help='where is a named feature in the image')
    s.add_argument('image'); s.add_argument('name'); s.set_defaults(fn=cmd_find)
    s = sub.add_parser('view', help='open the image in the browser viewer and editor')
    s.add_argument('image')
    s.add_argument('--port', type=int, default=ts.get('MOON_ATLAS_VIEW_PORT', 8766, int), help='first port to try (the next free one is used)')
    s.add_argument('--open', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_VIEW_OPEN'), help='open the browser')
    s.add_argument('--force', action='store_true', help='view even if the quality gate refuses the image')
    s.set_defaults(fn=cmd_view)
    s = sub.add_parser('export', help='labelled image: 16-bit TIFF / 16-bit PNG / JPEG',
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    s.add_argument('image')
    s.add_argument('-o', '--output', help='output file (default IMAGE_atlas[_NAME].EXT)')
    s.add_argument('--format', choices=['tiff', 'png', 'jpg'], help='tiff/png are 16-bit; default from -o, else tiff')
    s.add_argument('--scale', type=float, help='output scale, at most 1 (never upscaled)')
    s.add_argument('--max-size', type=int, default=ts.get('MOON_ATLAS_MAX_SIZE') or None, help='longest output side in px (never upscaled)')
    s.add_argument('--region', help='x,y,w,h in source px')
    s.add_argument('--around', metavar='NAME', help='centre the view on a named feature')
    s.add_argument('--size', default=ts.get('MOON_ATLAS_AROUND_SIZE'), help='view size in source px for --around')
    s.add_argument('--min-size', type=float, default=ts.get('MOON_ATLAS_MIN_SIZE', 24.0, float), help='smallest crater (apparent diameter, output px) that gets a name')
    s.add_argument('--font', help=f'any Google Fonts family, e.g. Inter, "IBM Plex Sans" (default: the viewer\'s choice, else {DEFAULT_FONT})')
    s.add_argument('--font-scale', type=float, default=ts.get('MOON_ATLAS_FONT_SCALE', 1.0, float), help='label size factor')
    s.add_argument('--night', choices=['hide', 'dim', 'show'], default=ts.get('MOON_ATLAS_NIGHT', 'hide'), help='names on the unlit side')
    s.add_argument('--layers', metavar='LIST', help=f"which names: comma list of {','.join(LAYERS)}, or none (default all)")
    s.add_argument('--rims', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_RIMS'), help='crater outlines')
    s.add_argument('--lettered', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_LETTERED'), help='lettered satellite craters (Copernicus A, ...)')
    s.add_argument('--landing', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_LANDING'), help='landing sites')
    s.add_argument('--grid', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_GRID'), help='lat/lon grid')
    s.add_argument('--drawings', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_DRAWINGS'), help="the drawings and measurements made in the viewer")
    s.add_argument('--info', action=argparse.BooleanOptionalAction, default=ts.get('MOON_ATLAS_INFO'), help='info block (date, optics, scale bar, north arrow)')
    s.add_argument('--quality', type=int, default=ts.get('MOON_ATLAS_JPEG_QUALITY', 92, int), help='JPEG quality')
    s.add_argument('--force', action='store_true', help='annotate even if the quality gate refuses the image')
    s.set_defaults(fn=cmd_export)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
