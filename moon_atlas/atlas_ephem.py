"""Where the Earth and the Sun are, seen from the Moon, at a given UTC time (J. Meeus, Astronomical Algorithms,
2nd ed.: ch. 22 nutation left out, 25 Sun, 47 Moon (main terms), 40 parallax, 53 physical ephemeris).

  sub-observer point   (optical libration, topocentric): the image's lat0 / lon0
  subsolar point       where the Sun is overhead: the lighting (colongitude = 90° − its longitude)
  distance             Earth–Moon (km, topocentric): the image scale for a known pixel angle

The observer's site (for the parallax) comes from MOON_ATLAS_OBSERVER_LAT / _LON / _HEIGHT_M in a .env file in the
scripts folder (or the environment); default Belgium.

Accuracy against the positions moon_atlas fitted on the user's images: see tests (≈ 0.1–0.3° in libration).
"""
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tool_settings as ts  # noqa: E402

R_EARTH = 6378.14
DEG = math.pi / 180
OBSERVER_DEFAULT = (50.9, 4.4, 0.05)  # lat °N, lon °E, height km: Belgium; only the parallax (≤ 1° of libration) uses it


def observer():
    """(lat °N, lon °E, height km) from MOON_ATLAS_OBSERVER_LAT / _LON / _HEIGHT_M (.env or environment)."""
    return (ts.get('MOON_ATLAS_OBSERVER_LAT', OBSERVER_DEFAULT[0], float),
            ts.get('MOON_ATLAS_OBSERVER_LON', OBSERVER_DEFAULT[1], float),
            ts.get('MOON_ATLAS_OBSERVER_HEIGHT_M', OBSERVER_DEFAULT[2] * 1000, float) / 1000)


OBSERVER = observer()

# ch. 47, table 47.A: (D, M, M', F, Σl coefficient 1e-6°, Σr coefficient 1e-3 km), largest terms
TERMS_LR = [
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111), (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925), (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138), (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586), (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321), (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661), (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208), (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379), (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650), (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003), (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884),
]
# table 47.B: (D, M, M', F, Σb coefficient 1e-6°)
TERMS_B = [
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693), (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271), (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266), (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463), (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870), (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794),
]


def julian_day(t):
    """datetime (UTC) -> Julian Ephemeris Day (ΔT ≈ 69 s for the 2020s)."""
    t = t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
    y, m = t.year, t.month
    d = t.day + (t.hour + (t.minute + (t.second + t.microsecond / 1e6) / 60) / 60) / 24
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5
    return jd + 69.0 / 86400


def _norm(x):
    return x % 360.0


def moon_ecliptic(jde):
    """Geocentric ecliptic longitude, latitude (°) and distance (km) of the Moon; mean node Ω (°); T."""
    T = (jde - 2451545.0) / 36525
    Lp = _norm(218.3164477 + 481267.88123421 * T - 0.0015786 * T * T)
    D = _norm(297.8501921 + 445267.1114034 * T - 0.0018819 * T * T)
    M = _norm(357.5291092 + 35999.0502909 * T)
    Mp = _norm(134.9633964 + 477198.8675055 * T + 0.0087414 * T * T)
    F = _norm(93.2720950 + 483202.0175233 * T - 0.0036539 * T * T)
    A1, A2, A3 = _norm(119.75 + 131.849 * T), _norm(53.09 + 479264.290 * T), _norm(313.45 + 481266.484 * T)
    E = 1 - 0.002516 * T - 0.0000074 * T * T
    sl = sr = sb = 0.0
    for d, m, mp, f, cl, cr in TERMS_LR:
        arg = (d * D + m * M + mp * Mp + f * F) * DEG
        e = E ** abs(m)
        sl += cl * e * math.sin(arg)
        sr += cr * e * math.cos(arg)
    for d, m, mp, f, cb in TERMS_B:
        sb += cb * E ** abs(m) * math.sin((d * D + m * M + mp * Mp + f * F) * DEG)
    sl += 3958 * math.sin(A1 * DEG) + 1962 * math.sin((Lp - F) * DEG) + 318 * math.sin(A2 * DEG)
    sb += (-2235 * math.sin(Lp * DEG) + 382 * math.sin(A3 * DEG) + 175 * math.sin((A1 - F) * DEG)
           + 175 * math.sin((A1 + F) * DEG) + 127 * math.sin((Lp - Mp) * DEG) - 115 * math.sin((Lp + Mp) * DEG))
    lam = _norm(Lp + sl / 1e6)
    beta = sb / 1e6
    dist = 385000.56 + sr / 1e3
    omega = _norm(125.0445479 - 1934.1362891 * T + 0.0020754 * T * T)
    return lam, beta, dist, omega, T


def sun_ecliptic(T):
    """Geometric ecliptic longitude (°) and distance (km) of the Sun (ch. 25, low precision)."""
    L0 = _norm(280.46646 + 36000.76983 * T)
    M = _norm(357.52911 + 35999.05029 * T)
    e = 0.016708634 - 0.000042037 * T
    C = ((1.914602 - 0.004817 * T) * math.sin(M * DEG) + (0.019993 - 0.000101 * T) * math.sin(2 * M * DEG)
         + 0.000289 * math.sin(3 * M * DEG))
    lon = _norm(L0 + C)
    nu = M + C
    R = 1.000001018 * (1 - e * e) / (1 + e * math.cos(nu * DEG))
    return lon, R * 149597870.7


def obliquity(T):
    return 23.4392911 - 0.0130042 * T


def gmst(jd_ut):
    T = (jd_ut - 2451545.0) / 36525
    return _norm(280.46061837 + 360.98564736629 * (jd_ut - 2451545.0) + 0.000387933 * T * T)


def ecl_to_eq(lam, beta, eps):
    l, b, e = lam * DEG, beta * DEG, eps * DEG
    ra = math.atan2(math.sin(l) * math.cos(e) - math.tan(b) * math.sin(e), math.cos(l))
    dec = math.asin(math.sin(b) * math.cos(e) + math.cos(b) * math.sin(e) * math.sin(l))
    return ra / DEG % 360, dec / DEG


def eq_to_ecl(ra, dec, eps):
    a, d, e = ra * DEG, dec * DEG, eps * DEG
    lam = math.atan2(math.sin(a) * math.cos(e) + math.tan(d) * math.sin(e), math.cos(a))
    beta = math.asin(math.sin(d) * math.cos(e) - math.cos(d) * math.sin(e) * math.sin(a))
    return lam / DEG % 360, beta / DEG


def topocentric(lam, beta, dist, eps, jd_ut, obs=OBSERVER):
    """Ecliptic position and distance of the Moon seen from the observer (vector difference, exact)."""
    ra, dec = ecl_to_eq(lam, beta, eps)
    x = dist * math.cos(dec * DEG) * math.cos(ra * DEG)
    y = dist * math.cos(dec * DEG) * math.sin(ra * DEG)
    z = dist * math.sin(dec * DEG)
    lat, lon, h = obs
    f = 1 / 298.257
    phi = lat * DEG
    u = math.atan((1 - f) * math.tan(phi))
    rs = (1 - f) * math.sin(u) + h / R_EARTH * math.sin(phi)
    rc = math.cos(u) + h / R_EARTH * math.cos(phi)
    lst = (gmst(jd_ut) + lon) * DEG
    x -= R_EARTH * rc * math.cos(lst)
    y -= R_EARTH * rc * math.sin(lst)
    z -= R_EARTH * rs
    d = math.sqrt(x * x + y * y + z * z)
    ra_t, dec_t = math.atan2(y, x) / DEG % 360, math.asin(z / d) / DEG
    lam_t, beta_t = eq_to_ecl(ra_t, dec_t, eps)
    return lam_t, beta_t, d


def _sub_point(lam, beta, omega, F):
    """(lat, lon) in degrees of the sub-point for ecliptic direction (lam, beta) from the Moon, F the argument of
    latitude (ch. 53: l' = A − F, b' = asin(−sin W cos β sin I − sin β cos I))."""
    I = 1.54242 * DEG
    W = (lam - omega) * DEG
    b = beta * DEG
    A = math.atan2(math.sin(W) * math.cos(b) * math.cos(I) - math.sin(b) * math.sin(I), math.cos(W) * math.cos(b))
    lon = ((A / DEG - F + 180) % 360) - 180
    lat = math.asin(-math.sin(W) * math.cos(b) * math.sin(I) - math.sin(b) * math.cos(I)) / DEG
    return lat, lon


def ephemeris(t, obs=OBSERVER):
    """dict(sub_obs_lat, sub_obs_lon, sub_sun_lat, sub_sun_lon, colongitude, distance_km, phase_angle) at UTC t."""
    jde = julian_day(t)
    jd_ut = jde - 69.0 / 86400
    lam, beta, dist, omega, T = moon_ecliptic(jde)
    F = _norm(93.2720950 + 483202.0175233 * T - 0.0036539 * T * T)
    eps = obliquity(T)
    lt, bt, dt = topocentric(lam, beta, dist, eps, jd_ut, obs) if obs else (lam, beta, dist)
    ob_lat, ob_lon = _sub_point(lt, bt, omega, F)
    sun_lon, sun_R = sun_ecliptic(T)
    # heliocentric direction of the Moon, i.e. where the Sun is seen from the Moon, reversed (ch. 53)
    lh = sun_lon + 180 + dist / sun_R * 57.296 * math.cos(beta * DEG) * math.sin((sun_lon - lam) * DEG)
    bh = dist / sun_R * beta
    ss_lat, ss_lon = _sub_point(lh, bh, omega, F)
    # phase angle from the two sub-points (angle Sun–Moon–Earth)
    p = lambda la, lo: (math.cos(la * DEG) * math.cos(lo * DEG), math.cos(la * DEG) * math.sin(lo * DEG), math.sin(la * DEG))
    a, b_ = p(ob_lat, ob_lon), p(ss_lat, ss_lon)
    phase = math.acos(max(-1, min(1, sum(x * y for x, y in zip(a, b_))))) / DEG
    return dict(sub_obs_lat=ob_lat, sub_obs_lon=ob_lon, sub_sun_lat=ss_lat, sub_sun_lon=ss_lon,
                colongitude=_norm(90 - ss_lon), distance_km=dt, phase_angle=phase)


SHARPCAP = re.compile(r'(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})_(\d)')


def capture_time(name):
    """UTC datetime from a SharpCap / WinJUPOS name 'YYYY-MM-DD-HHMM_T-…' (T = tenths of a minute); for a mosaic
    without one, the middle of its panels' times (IMAGE_layout.json or mosaic_layout.json next to it); else None."""
    m = SHARPCAP.search(os.path.basename(name))
    if not m:
        return _layout_time(name)
    y, mo, d, h, mi, tenth = (int(v) for v in m.groups())
    try:
        return datetime(y, mo, d, h, mi, tenth * 6, tzinfo=timezone.utc)
    except ValueError:
        return None


def _layout_time(path):
    folder = os.path.dirname(os.path.abspath(path))
    for p in (os.path.splitext(os.path.abspath(path))[0] + '_layout.json', os.path.join(folder, 'mosaic_layout.json')):
        try:
            with open(p) as fh:
                panels = json.load(fh).get('panels', {})
        except (OSError, ValueError, AttributeError):
            continue
        times = sorted(t for t in (capture_time(os.path.basename(v.get('path', k))) for k, v in panels.items()
                                   if isinstance(v, dict)) if t)
        if times:
            return times[len(times) // 2]
    return None
