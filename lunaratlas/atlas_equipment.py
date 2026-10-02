"""The user's equipment and observing site: equipment.json in the user's data folder (LUNARATLAS_EQUIPMENT names
another file), written by the app (the short form at the first close-up, and Settings) and read by the CLI too.

Nothing is assumed when there is none: no telescope, no camera, no site. A close-up is then searched over every
common scale, and the ephemeris is geocentric (the site only moves the libration by up to 1°).

    {"v": 1,
     "telescopes": [{"id": "t1", "name": "250 PDS", "focal_mm": 1200, "aperture_mm": 254}],
     "barlows":    [{"id": "b1", "name": "ES Focal Extender", "factor": 2}],          imaging without one is implied
     "cameras":    [{"id": "c1", "name": "ZWO ASI678MC", "sensor": "IMX678", "pixel_um": 2.0,
                     "width": 3840, "height": 2160, "binnings": [1, 2]}],
     "site":       {"lat": 50.9, "lon": 4.4, "height_m": 50} or null,
     "unused":     ["t1/b1/c1/1", …],     setups the user ticked off (not searched unless every scale is)
     "recent":     ["t1/native/c1/1", …]}  newest first: the "Taken with" choice for the next photo

A setup is one telescope × barlow (or none: "native") × camera × binning; its id is "t/b/c/binning".
"""
import json
import math
import os
import re
import tempfile

NATIVE = 'native'
NEED = 'equipment needed'                       # locate --ask-equipment stops with this: the app asks, then goes on
MAX_ITEMS = 40                                  # of each kind: a form, not a database
LIMITS = dict(focal_mm=(50, 30000), aperture_mm=(10, 2000), factor=(0.2, 10), pixel_um=(0.5, 30),
              width=(16, 50000), height=(16, 50000), lat=(-90, 90), lon=(-180, 180), height_m=(-500, 9000))


def path():
    p = os.environ.get('LUNARATLAS_EQUIPMENT')
    if p:
        return p
    from atlas_paths import user_dir
    return os.path.join(user_dir('data'), 'equipment.json')


def empty():
    return dict(v=1, telescopes=[], barlows=[], cameras=[], site=None, unused=[], recent=[])


# ---------------------------------------------------------------- checking what a page sends
def _num(d, key, required=True, integer=False):
    v = d.get(key)
    if v is None or v == '':
        if required:
            raise ValueError(f'{key} is missing')
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f'{key}: not a number')
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f'{key}: {v!r} is not a number') from None
    lo, hi = LIMITS[key]
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f'{key}: {v} is outside {lo}–{hi}')
    return int(round(x)) if integer else x


def _name(d, what):
    n = d.get('name')
    if not isinstance(n, str) or not n.strip():
        raise ValueError(f'a {what} needs a name')
    n = re.sub(r'\s+', ' ', n).strip()
    if len(n) > 60 or any(ord(ch) < 32 for ch in n):
        raise ValueError(f'{n[:60]!r}: a name of at most 60 characters')
    return n


def _ids(items, prefix):
    """Every item gets an id of its own: kept when it is a valid unused one, else the next free "<prefix><n>"."""
    seen, out = set(), []
    for it in items:
        i = it.get('id')
        if not (isinstance(i, str) and re.fullmatch(prefix + r'\d{1,6}', i) and i not in seen):
            i = None
        out.append(i)
        if i:
            seen.add(i)
    n = 1
    for k, i in enumerate(out):
        if i is None:
            while f'{prefix}{n}' in seen:
                n += 1
            out[k] = f'{prefix}{n}'
            seen.add(out[k])
        items[k]['id'] = out[k]
    return items


def clean(d):
    """A checked copy of an equipment document (from the page or the file): ValueError says what is wrong."""
    if not isinstance(d, dict):
        raise ValueError('not an equipment document')
    out = empty()
    for key, what in (('telescopes', 'telescope'), ('barlows', 'barlow'), ('cameras', 'camera')):
        items = d.get(key) or []
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError(f'{key}: a list of at most {MAX_ITEMS}')
        for it in items:
            if not isinstance(it, dict):
                raise ValueError(f'{key}: not a list of entries')
            e = dict(name=_name(it, what))
            if isinstance(it.get('id'), str):
                e['id'] = it['id']
            if key == 'telescopes':
                e['focal_mm'] = _num(it, 'focal_mm')
                a = _num(it, 'aperture_mm', required=False)
                if a is not None:
                    e['aperture_mm'] = a
            elif key == 'barlows':
                e['factor'] = _num(it, 'factor')
            else:
                e['pixel_um'] = _num(it, 'pixel_um')
                s = it.get('sensor')
                if isinstance(s, str) and s.strip():
                    e['sensor'] = re.sub(r'[^\w .+-]', '', s)[:30].strip()
                w, h = _num(it, 'width', False, True), _num(it, 'height', False, True)
                if w and h:
                    e['width'], e['height'] = w, h
                b = it.get('binnings') or [1]
                if not isinstance(b, list) or not all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 4
                                                      for x in b):
                    raise ValueError('binnings: a list of 1 to 4')
                e['binnings'] = sorted(set(b)) or [1]
            out[key].append(e)
        _ids(out[key], key[0])
    site = d.get('site')
    if site not in (None, {}):
        if not isinstance(site, dict):
            raise ValueError('site: not a place')
        out['site'] = dict(lat=_num(site, 'lat'), lon=_num(site, 'lon'),
                           height_m=_num(site, 'height_m', required=False) or 0.0)
    known = {s['id'] for s in setups(out, include_unused=True)}
    for key in ('unused', 'recent'):
        v = d.get(key) or []
        if not isinstance(v, list):
            raise ValueError(f'{key}: not a list')
        out[key] = list(dict.fromkeys(x for x in v if isinstance(x, str) and x in known))[:200 if key == 'unused' else 10]
    return out


# ---------------------------------------------------------------- the file
_cache = (None, None)


def load():
    """The equipment in effect: the file's, checked; nothing at all when there is none or it cannot be read.
    (A copy: read again only when the file changed, since the ephemeris asks for the site on every call.)"""
    global _cache
    p = path()
    try:
        st = os.stat(p)
        key = (p, st.st_mtime_ns, st.st_size)
    except OSError:
        return empty()
    if _cache[0] != key:
        try:
            with open(p, encoding='utf-8') as fh:
                _cache = (key, clean(json.load(fh)))
        except (OSError, ValueError, RecursionError):
            _cache = (key, empty())
    return json.loads(json.dumps(_cache[1]))


def save(d):
    """Check d and write it (this user only, never half-written). Returns what was written."""
    d = clean(d)
    p = path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.equipment-', suffix='.tmp', dir=os.path.dirname(os.path.abspath(p)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, indent=1, ensure_ascii=False)
        if os.name == 'posix':
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return d


# ---------------------------------------------------------------- setups
def setups(d=None, include_unused=False):
    """Every telescope × (none + barlows) × camera × binning as a dict: id, telescope, native_mm, extender,
    magnification, focal_mm (with the barlow), camera, pixel_um (binned), binning ('2×2', None unbinned), width/height
    (binned px, when the camera's are known), used. The ticked-off ones only with include_unused."""
    d = load() if d is None else d
    unused = set(d.get('unused') or [])
    out = []
    for t in d['telescopes']:
        for b in [None] + d['barlows']:
            for c in d['cameras']:
                for n in c.get('binnings') or [1]:
                    sid = f"{t['id']}/{b['id'] if b else NATIVE}/{c['id']}/{n}"
                    if sid in unused and not include_unused:
                        continue
                    f = b['factor'] if b else 1.0
                    s = dict(id=sid, telescope=t['name'], native_mm=t['focal_mm'],
                             extender=f"{b['name']} {f:g}×" if b else NATIVE, magnification=f,
                             focal_mm=t['focal_mm'] * f, camera=c['name'], pixel_um=c['pixel_um'] * n,
                             binning=f'{n}×{n}' if n != 1 else None, used=sid not in unused)
                    if c.get('width'):
                        s['width'], s['height'] = c['width'] // n, c['height'] // n
                    out.append(s)
    return out


def find(sid, d=None):
    return next((s for s in setups(d, include_unused=True) if s['id'] == sid), None)


def arcsec_per_px(s, drizzle=1.0):
    """The plate scale of a setup (or of a saved optics file: focal_mm with the barlow, pixel_um binned)."""
    return 206.265 * s['pixel_um'] / s['focal_mm'] / drizzle


def text(s):
    cam = s['camera'] + (f" {s['binning']} binned" if s.get('binning') else '')
    return f"{s['telescope']} · {s['extender']} · {cam} ({s['focal_mm']:.0f} mm, {arcsec_per_px(s):.3f}″/px)"


def add(telescope, barlow, camera, binning=1):
    """The short form's answer: each part added unless an equal one is there already, the setup it makes put first
    in recent. Returns (equipment, setup id)."""
    d = load()

    def same(items, part, *fields):
        for it in d[items]:
            if it['name'].lower() == part['name'].strip().lower() and all(
                    abs(float(it.get(f) or 0) - float(part.get(f) or 0)) < 1e-6 for f in fields):
                return it
        d[items].append(dict(part))
        return None

    if not isinstance(telescope, dict) or not isinstance(camera, dict) or not (barlow is None or isinstance(barlow, dict)):
        raise ValueError('a telescope and a camera are needed')
    camera = dict(camera, binnings=sorted({1, int(binning) if isinstance(binning, int) else 1}))
    same('telescopes', telescope, 'focal_mm')
    if barlow:
        same('barlows', barlow, 'factor')
    hit = same('cameras', camera, 'pixel_um')
    if hit is not None and binning not in hit.get('binnings', [1]):
        hit['binnings'] = sorted(set(hit.get('binnings', [1])) | {binning})
    d = clean(d)                                        # checks the new parts and gives them ids

    def pick(items, part, *fields):
        return next(it for it in d[items] if it['name'].lower() == _name(part, items).lower() and all(
            abs(float(it.get(f) or 0) - float(part.get(f) or 0)) < 1e-6 for f in fields))
    t = pick('telescopes', telescope, 'focal_mm')
    b = pick('barlows', barlow, 'factor') if barlow else None
    c = pick('cameras', camera, 'pixel_um')
    sid = f"{t['id']}/{b['id'] if b else NATIVE}/{c['id']}/{binning}"
    d['unused'] = [x for x in d['unused'] if x != sid]
    d['recent'] = [sid] + [x for x in d['recent'] if x != sid]
    return save(d), sid


def remember(sid):
    """sid was used for a photo: first in recent (nothing happens for an unknown one)."""
    d = load()
    if find(sid, d) is None:
        return
    d['recent'] = [sid] + [x for x in d['recent'] if x != sid]
    save(d)


def site():
    """(lat °N, lon °E, height km) of the observing site, or None (geocentric) when none is set."""
    s = load().get('site')
    return (s['lat'], s['lon'], s['height_m'] / 1000) if s else None
