"""IAU lunar nomenclature (USGS Gazetteer of Planetary Nomenclature) + landing sites."""
import json
import os
import struct
import zipfile

from atlas_geo import DATA, download, write_json_atomic

GAZ_URL = 'https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip'
GAZ_DIR = os.path.join(DATA, 'iau')
GAZ_DBF = os.path.join(GAZ_DIR, 'MOON_nomenclature_center_pts.dbf')
GAZ_JSON = os.path.join(GAZ_DIR, 'features.json')

# style class per IAU feature type
CLASS = {
    'Mare, maria': 'area', 'Oceanus, oceani': 'area', 'Lacus, lacūs': 'area', 'Sinus, sinūs': 'area',
    'Palus, paludes': 'area', 'Planitia, planitiae': 'area',
    'Crater, craters': 'crater', 'Satellite Feature': 'lettered',
    'Mons, montes': 'relief', 'Rima, rimae': 'relief', 'Dorsum, dorsa': 'relief', 'Vallis, valles': 'relief',
    'Catena, catenae': 'relief', 'Rupes, rupēs': 'relief', 'Promontorium, promontoria': 'relief',
    'Albedo Feature': 'relief',
    'Statio': 'site', 'Astronaut-named features': 'apollo',
}

# Landing sites (approximate, from published LROC positions). Near side only.
SITES = [
    ('Apollo 11', 0.674, 23.473), ('Apollo 12', -3.012, -23.422), ('Apollo 14', -3.645, -17.471),
    ('Apollo 15', 26.132, 3.634), ('Apollo 16', -8.973, 15.500), ('Apollo 17', 20.191, 30.772),
    ('Luna 9', 7.08, -64.37), ('Luna 16', -0.514, 56.364), ('Luna 17 / Lunokhod 1', 38.238, -35.002),
    ('Luna 20', 3.787, 56.624), ('Luna 21 / Lunokhod 2', 25.85, 30.45), ('Luna 24', 12.714, 62.213),
    ('Surveyor 1', -2.474, -43.339), ('Surveyor 3', -3.014, -23.416), ('Surveyor 5', 1.455, 23.194),
    ('Surveyor 6', 0.490, -1.428), ('Surveyor 7', -41.008, -11.440),
    ("Chang'e 3 / Yutu", 44.121, -19.512), ("Chang'e 5", 43.058, -51.916), ('SLIM', -13.316, 25.251),
    ('Chandrayaan-3', -69.373, 32.319), ('IM-1 Odysseus', -80.130, 1.437), ('Blue Ghost 1', 18.562, 61.810),
]


def _read_dbf(path):
    """dBASE records as dicts; records flagged deleted ('*') are skipped. ValueError if damaged."""
    b = open(path, 'rb').read()
    if len(b) < 33:
        raise ValueError('DBF too short')
    n, hl, rl = struct.unpack('<IHH', b[4:12])
    fields, o = [], 32
    while o < min(hl, len(b)) and b[o] != 0x0D:
        if o + 32 > len(b):
            raise ValueError('DBF header truncated')
        fields.append((b[o:o + 11].split(b'\0')[0].decode('ascii', 'replace'), b[o + 16])); o += 32
    if o >= hl or 1 + sum(ln for _, ln in fields) != rl or hl + n * rl > len(b):
        raise ValueError('DBF header does not match its records (truncated or damaged file)')
    rows = []
    for i in range(n):
        rec = b[hl + i * rl:hl + (i + 1) * rl]
        if rec[:1] == b'*':
            continue
        r, p, d = rec[1:], 0, {}
        for name, ln in fields:
            d[name] = r[p:p + ln].decode('utf-8', 'replace').strip(); p += ln
        rows.append(d)
    return rows


def _download(log):
    os.makedirs(GAZ_DIR, exist_ok=True)
    z = os.path.join(GAZ_DIR, 'MOON_nomenclature_center_pts.zip')
    log('downloading the IAU nomenclature (≈ 24 MB, once)')
    download(GAZ_URL, z, zipfile.is_zipfile, log=log)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(GAZ_DIR)


def _build_json(log):
    try:
        rows = _read_dbf(GAZ_DBF)
    except (OSError, ValueError) as e:
        log(f'IAU nomenclature file is damaged ({e}): downloading it again')
        _download(log)
        rows = _read_dbf(GAZ_DBF)
    feats = []
    for r in rows:
        if not r['name']:
            continue
        lon = (float(r['center_lon']) + 180) % 360 - 180
        feats.append(dict(name=r['name'], cls=CLASS.get(r['type'], 'relief'), type=r['type'],
                          lat=round(float(r['center_lat']), 5), lon=round(lon, 5),
                          diam=round(float(r['diameter'] or 0), 3), origin=r['origin'], link=r['link']))
    write_json_atomic(GAZ_JSON, feats, ensure_ascii=False)
    return feats


def load_features(log=print, sites=True):
    """List of dicts: name, cls, type, lat, lon (east, -180..180), diam (km), origin, link."""
    feats = None
    if os.path.exists(GAZ_JSON) and not (os.path.exists(GAZ_DBF) and os.path.getmtime(GAZ_DBF) > os.path.getmtime(GAZ_JSON)):
        try:
            with open(GAZ_JSON, encoding='utf-8') as fh:
                feats = json.load(fh)
        except (OSError, ValueError):
            log('feature cache is damaged: rebuilding it')
    if feats is None:
        if not os.path.exists(GAZ_DBF):
            _download(log)
        feats = _build_json(log)
    if sites:
        feats += [dict(name=n, cls='landing', type='Landing site', lat=a, lon=o, diam=0.0, origin='', link='')
                  for n, a, o in SITES]
    return feats
