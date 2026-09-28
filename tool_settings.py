"""Settings for the lunar tools (moon_atlas, lunar_finish, mosaic_builder, panel_classifier) from
the .env file next to this module (not committed). Every key is declared once in SPECS below, with its type, default and
allowed range, so the tools, their --help and .env.example agree.

    KEY=VALUE per line; # starts a comment; surrounding quotes are stripped.
    Precedence: command-line option > environment variable of the same name > .env > built-in default.
    A value outside its range (or an unknown key: a typo) is reported once and the default is used.

    python3 tool_settings.py --example     rewrite .env.example from SPECS
    python3 tool_settings.py --check       validate .env and show the value in effect for every key
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CPU = os.cpu_count() or 2


def S(key, kind, default, help, lo=None, hi=None, choices=None, lo_open=False, hi_open=False, typical=None):
    return dict(key=key, kind=kind, default=default, help=help, lo=lo, hi=hi, choices=choices, lo_open=lo_open,
                hi_open=hi_open, typical=typical)


LAYER_NAMES = ('area', 'crater', 'lettered', 'relief', 'landing')
SPECS = [
    ('Observing site (only the parallax of the lunar ephemeris: up to 1° of libration)', [
        S('MOON_ATLAS_OBSERVER_NAME', 'str', 'Belgium', 'a name for the site (shown nowhere yet)'),
        S('MOON_ATLAS_OBSERVER_LAT', 'float', 50.9, 'latitude, ° north', -90, 90),
        S('MOON_ATLAS_OBSERVER_LON', 'float', 4.4, 'longitude, ° east', -180, 180),
        S('MOON_ATLAS_OBSERVER_HEIGHT_M', 'float', 50.0, 'height above sea level, m', -500, 9000),
    ]),
    ('Equipment (close-up search and the optics prompt)', [
        S('MOON_ATLAS_TELESCOPE', 'str', '250 PDS', 'telescope name, used in the info block'),
        S('MOON_ATLAS_FOCAL_MM', 'float', 1200.0, 'native focal length, mm', 50, 30000),
        S('MOON_ATLAS_EXTENDERS', 'pairs', 'native:1, 2× ES Focal Extender:2, 2.5× TV Powermate:2.5, 3× ES Focal Extender:3',
          'focal extenders as name:factor, comma-separated; factor per entry', 0.2, 10),
        S('MOON_ATLAS_CAMERAS', 'pairs', 'IMX678:2.0, IMX533:3.76, IMX462:2.9',
          'cameras as name:pixel size in µm, comma-separated; µm per entry', 0.5, 30),
    ]),
    ('moon_atlas export (labelled images)', [
        S('MOON_ATLAS_FORMAT', 'choice', 'tiff', 'output format when -o does not decide it', choices=('tiff', 'png', 'jpg')),
        S('MOON_ATLAS_MAX_SIZE', 'int', 0, 'longest output side in px (never upscaled); 0 = 1:1', 0, 100000),
        S('MOON_ATLAS_AROUND_SIZE', 'str', '3000x2000', 'view size W x H in source px for --around NAME'),
        S('MOON_ATLAS_MIN_SIZE', 'float', 24.0, 'smallest crater that gets a name, apparent diameter in output px', 4, 400,
          typical='16–40'),
        S('MOON_ATLAS_FONT', 'str', 'Roboto', 'label font: any Google Fonts family (the viewer serves Roboto, Inter, '
          'IBM Plex Sans, Barlow, Geist, Space Grotesk)'),
        S('MOON_ATLAS_FONT_SCALE', 'float', 1.0, 'label size factor', 0.3, 5, typical='0.8–1.6'),
        S('MOON_ATLAS_NIGHT', 'choice', 'hide', 'names on the unlit side', choices=('hide', 'dim', 'show')),
        S('MOON_ATLAS_LAYERS', 'list', ','.join(LAYER_NAMES), 'which names, comma-separated, or none',
          choices=LAYER_NAMES + ('none',)),
        S('MOON_ATLAS_RIMS', 'bool', True, 'crater outlines in exports'),
        S('MOON_ATLAS_LETTERED', 'bool', True, 'lettered satellite craters (Copernicus A, …)'),
        S('MOON_ATLAS_LANDING', 'bool', True, 'landing sites'),
        S('MOON_ATLAS_GRID', 'bool', True, 'lat/lon grid in exports'),
        S('MOON_ATLAS_DRAWINGS', 'bool', True, "the viewer's drawings and measurements in exports"),
        S('MOON_ATLAS_INFO', 'bool', True, 'info block (date, optics, scale bar, N/E arrows) in exports'),
        S('MOON_ATLAS_JPEG_QUALITY', 'int', 92, 'JPEG quality', 0, 100, typical='85–95'),
    ]),
    ('moon_atlas viewer', [
        S('MOON_ATLAS_VIEW_PORT', 'int', 8766, 'first port to try (the next free one is used)', 1024, 65535),
        S('MOON_ATLAS_VIEW_OPEN', 'bool', True, 'open the browser when the viewer starts'),
    ]),
    ('lunar_finish: wavelet sharpening (first step; PixInsight ATrousWaveletTransform on lightness)', [
        S('LUNAR_FINISH_WAVELETS', 'str', '', "empty = off; 'pixinsight' = 4 layers, linear (3), layer 1 bias +3; or 1–8 "
          'comma-separated layer biases, layer weight = 1 + bias; each bias ≥ −1 (−1 removes the layer, 0 keeps it); '
          'typical 0–4 for layer 1, less for coarser layers'),
        S('LUNAR_FINISH_WAVELET_KERNEL', 'choice', 'linear', "scaling function: linear = 'Linear Interpolation (3)', "
          "b3 = 'B3 Spline (5)'", choices=('linear', 'b3')),
        S('LUNAR_FINISH_WAVELET_DENOISE', 'str', '', 'per layer, comma-separated: coefficients within K × the '
          "layer's noise keep weight 1; each K ≥ 0; 0 or empty = off; typical 0.5–3"),
    ]),
    ('lunar_finish: unsharp mask (as Photoshop; optional, after contrast)', [
        S('LUNAR_FINISH_USM', 'str', '', 'empty = off; AMOUNT,RADIUS,THRESHOLD, e.g. 100,1.5,0 or "100;1,5;0": amount '
          '≥ 0 % (Photoshop 1–500 %), radius > 0 px (Gaussian σ; Photoshop 0.1–1000), threshold 0–255 levels; '
          'typical 50–150 %, 0.5–2 px, 0–6 levels'),
        S('LUNAR_FINISH_USM_MODE', 'choice', 'luminosity', 'luminosity = brightness only (no colour fringes); rgb = '
          'every channel, as Photoshop in RGB mode', choices=('luminosity', 'rgb')),
    ]),
    ('lunar_finish: tone, colour and orientation', [
        S('LUNAR_FINISH_HIGHLIGHTS', 'float', 0.3, 'fraction by which the knee-to-top span is lowered; 0 = off', 0, 0.5,
          hi_open=True, typical='0.2–0.4'),
        S('LUNAR_FINISH_KNEE_PERCENTILE', 'float', 90.0, 'highlight roll-off starts at this brightness percentile of '
          'the disk', 0, 99.9, lo_open=True, hi_open=True, typical='85–95'),
        S('LUNAR_FINISH_SATURATION', 'float', 2.0, 'saturation factor on the lunar hues per pass; 1 = off', 0, 10,
          lo_open=True, typical='1.5–3'),
        S('LUNAR_FINISH_SATURATION_PASSES', 'int', 2, 'how many times the saturation boost is applied', 0, 10,
          typical='1–3'),
        S('LUNAR_FINISH_CONTRAST', 'float', 0.12, 'midtone contrast increase (0.12 = +12 %); 0 = off', 0, 0.5,
          hi_open=True, typical='0.05–0.2'),
        S('LUNAR_FINISH_CHROMA_DENOISE', 'float', 3.0, 'colour-only smoothing before the saturation boost, px '
          '(Gaussian σ); 0 = off', 0, 50, typical='2–4'),
        S('LUNAR_FINISH_LIMB_TAPER', 'float', 80.0, 'px inside the limb without extra saturation (colour fringing)',
          0, 2000),
        S('LUNAR_FINISH_NORTH_UP', 'bool', True, 'last step: turn lunar north up, east right (never mirrored)'),
        S('LUNAR_FINISH_PREVIEW', 'bool', True, 'live preview window'),
        S('LUNAR_FINISH_DISPLAY_TIF', 'bool', True, 'also write <out>_display.tif (the movie tone mapping)'),
    ]),
    ('mosaic_builder', [
        S('MOSAIC_MODEL', 'choice', 'poly3+mesh', 'pose model for fine alignment',
          choices=('poly3+mesh', 'poly3', 'poly2', 'affine', 'similarity')),
        S('MOSAIC_NORTH_UP', 'bool', False, 'turn the mosaic itself north up (normally lunar_finish does it)'),
        S('MOSAIC_WORKERS', 'int', max(1, CPU - 1), 'parallel worker threads', 1, 256),
        S('MOSAIC_PROXY_FACTOR', 'int', 4, 'proxy downscale factor for pair discovery (4 = 0.25×)', 1, 16),
        S('MOSAIC_FEATURES', 'int', 4000, 'SIFT keypoints per panel (on the proxy)', 100, 50000, typical='2000–8000'),
        S('MOSAIC_MIN_KEYPOINTS', 'int', 150, 'panels with fewer keypoints are not placed', 0, 50000),
        S('MOSAIC_PAIR_SEARCH', 'choice', 'index', 'index = one feature index over all panels (fast); all = every pair',
          choices=('index', 'all')),
        S('MOSAIC_MAX_POINTS', 'int', 300, 'correspondences per pair in the global solve', 1, 10000),
        S('MOSAIC_LEVELS', 'int', 7, 'multi-band pyramid levels', 1, 10),
        S('MOSAIC_BORDER', 'str', 'auto', 'px cropped at every frame edge: auto (measured artefact + 3 px) or 0–499'),
        S('MOSAIC_BACKGROUND', 'choice', 'neutral-black', 'neutral-black = neutral sky, then black space; neutral = '
          'neutral sky only; keep = unchanged', choices=('neutral-black', 'neutral', 'keep')),
        S('MOSAIC_LIMB_FEATHER', 'int', 12, 'px cosine ramp from the limb to black', 0, 1000),
        S('MOSAIC_COLOUR_BALANCE', 'choice', 'highlands', 'highlands = neutral grey highlands; disk = neutral whole '
          'disk; none', choices=('highlands', 'disk', 'none')),
        S('MOSAIC_PREVIEW', 'bool', True, 'live preview window'),
        S('MOSAIC_DISPLAY_TIF', 'bool', True, 'also write <out>_display.tif (the movie tone mapping)'),
    ]),
    ('panel_classifier', [
        S('MOSAIC_CLASSIFIER_BORDER', 'int', 32, 'px trimmed from every edge', 0, 499),
        S('MOSAIC_CLASSIFIER_ERODE', 'int', 40, 'px removed along a real subject edge', 0, 1000),
        S('MOSAIC_CLASSIFIER_TIERS', 'str', '10,25,75', 'percentile cut points, comma-separated, each 0–100'),
        S('MOSAIC_CLASSIFIER_RADIUS_TOL', 'int', 200, 'px: overlapping images compared at equal distance from their '
          'frame centres, within this', 1, 5000),
        S('MOSAIC_CLASSIFIER_WORKERS', 'int', max(1, CPU - 2), 'parallel worker threads', 1, 256),
    ]),
]
BY_KEY = {s['key']: s for _, group in SPECS for s in group}
PREFIXES = ('MOON_ATLAS_', 'LUNAR_FINISH_', 'MOSAIC_')
_raw, _warned = None, set()


def _read():
    global _raw
    if _raw is None:
        raw = {}
        try:
            with open(os.path.join(ROOT, '.env'), encoding='utf-8') as fh:
                for line in fh:
                    line = line.split('#', 1)[0].strip()
                    if '=' in line:
                        k, v = line.split('=', 1)
                        raw[k.strip()] = (v.strip().strip('"').strip("'"), '.env')
        except OSError:
            pass
        raw.update({k: (v, 'environment') for k, v in os.environ.items() if k.startswith(PREFIXES)})
        for k, (v, where) in raw.items():
            if k not in BY_KEY:
                _warn(k, f'unknown setting {k} in {where} (a typo?); ignored')
        _raw = raw
    return _raw


def _warn(key, text):
    if key not in _warned:
        _warned.add(key)
        print(f'settings: {text}', file=sys.stderr, flush=True)


def _in_range(s, x):
    lo, hi = s['lo'], s['hi']
    if lo is not None and (x < lo or (s['lo_open'] and x == lo)):
        return False
    return not (hi is not None and (x > hi or (s['hi_open'] and x == hi)))


def range_text(s):
    if s['choices'] and s['kind'] in ('choice', 'list'):
        return ('one or more of ' if s['kind'] == 'list' else 'one of ') + ' | '.join(s['choices'])
    if s['kind'] == 'bool':
        return '1 or 0'
    if s['lo'] is None and s['hi'] is None:
        return ''
    a = ('>' if s['lo_open'] else '≥') + f" {s['lo']:g}" if s['lo'] is not None else ''
    b = ('<' if s['hi_open'] else '≤') + f" {s['hi']:g}" if s['hi'] is not None else ''
    if s['lo'] is not None and s['hi'] is not None:
        return f"{s['lo']:g}{' (excl.)' if s['lo_open'] else ''} – {s['hi']:g}{' (excl.)' if s['hi_open'] else ''}"
    return a or b


def _convert(s, v):
    k = s['kind']
    if k == 'bool':
        t = v.strip().lower()
        if t in ('1', 'yes', 'true', 'on'):
            return True
        if t in ('0', 'no', 'false', 'off'):
            return False
        raise ValueError('expected 1 or 0')
    if k in ('int', 'float'):
        x = int(v) if k == 'int' else float(v)
        if not _in_range(s, x):
            raise ValueError(f'outside {range_text(s)}')
        return x
    if k == 'choice':
        if v not in s['choices']:
            raise ValueError(range_text(s))
        return v
    if k == 'list':
        items = [p.strip() for p in v.split(',') if p.strip()]
        bad = [p for p in items if p not in s['choices']]
        if bad or not items:
            raise ValueError(f"{', '.join(bad) or 'empty'}: {range_text(s)}")
        return items
    if k == 'pairs':
        out = []
        for part in v.split(','):
            name, val = part.rsplit(':', 1)
            x = float(val)
            if not _in_range(s, x):
                raise ValueError(f'{name.strip()}: {x:g} outside {range_text(s)}')
            out.append((name.strip(), x))
        if not out:
            raise ValueError('empty')
        return out
    return v


def get(key, default=None, kind=None):
    """The setting's value in effect (typed, range-checked), else its built-in default. default/kind are only used
    for keys not declared in SPECS (kept for callers from before the registry)."""
    s = BY_KEY.get(key)
    raw = _read().get(key)
    if s is None:
        if raw is None or raw[0] == '':
            return default
        try:
            return raw[0].strip().lower() in ('1', 'yes', 'true', 'on') if kind is bool else (kind or str)(raw[0])
        except ValueError:
            return default
    base = s['default']
    if s['kind'] == 'pairs' and isinstance(base, str):
        base = _convert(s, base)
    if s['kind'] == 'list' and isinstance(base, str):
        base = _convert(s, base)
    if raw is None or (raw[0] == '' and s['kind'] != 'str'):
        return base
    try:
        return _convert(s, raw[0])
    except (ValueError, TypeError) as e:
        _warn(key, f'{key}={raw[0]!r} in {raw[1]}: {e}; using the default {s["default"]!r}')
        return base


def pairs(key, default=None):
    v = get(key)
    return v if v else default


def example():
    lines = ['# Settings for the lunar tools: moon_atlas, lunar_finish, mosaic_builder, panel_classifier.',
             '# Copy to .env (not committed) and uncomment what you change. Written by `python3 tool_settings.py --example`',
             '# from the SPECS in tool_settings.py, so the ranges here are the ones the tools enforce.',
             '# Precedence: command-line option > environment variable > .env > this default.',
             '# Out-of-range values and unknown keys are reported and the default is used.', '']
    for title, group in SPECS:
        lines.append(f'# ---- {title}')
        for s in group:
            r = range_text(s)
            note = s['help'] + (f' · range {r}' if r and s['kind'] not in ('bool',) else '') + \
                (f' · typical {s["typical"]}' if s['typical'] else '')
            d = s['default']
            d = ('1' if d else '0') if s['kind'] == 'bool' else d
            lines.append(f'#   {note}')
            lines.append(f'# {s["key"]}={d}')
        lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    if '--example' in sys.argv:
        with open(os.path.join(ROOT, '.env.example'), 'w', encoding='utf-8') as fh:
            fh.write(example())
        print(f'wrote {os.path.join(ROOT, ".env.example")} ({len(BY_KEY)} settings)')
    else:
        raw = _read()
        for title, group in SPECS:
            print(f'\n{title}')
            for s in group:
                src = raw.get(s['key'], (None, 'default'))[1]
                print(f"  {s['key']:34s} = {get(s['key'])!r}  ({src})")
