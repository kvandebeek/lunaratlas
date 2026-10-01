"""Re-locate the baseline images without touching their sidecars; compare with the recorded numbers.

  albedo: matched against the LROC albedo map only (no capture time)
  shaded: against LOLA relief lit by the real Sun (capture time from the name), as lunaratlas locate does
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from atlas_geo import locate
from atlas_ephem import capture_time
# The baseline images are not in this repository. Point LUNARATLAS_BASELINE_DIR at a folder holding them.
IMAGES = os.environ.get('LUNARATLAS_BASELINE_DIR', os.path.expanduser('~/moon-baseline'))
# (name, file, time override, albedo matches / rms, shaded matches / rms) measured 2026-09-28
BASE = [('Mosaic 25 Sep', 'mosaic.tif', '2026-09-25-2110_0', 610, 1.52, 620, 1.55),
        ('5 Aug', '2026-08-05-0508_2-Moon_R_lapl2_ap1690_Drizzle15.tif', None, 227, 0.75, 390, 0.42),
        ('23 Sep', '2026-09-23-2138_1-Moon_Filter 4_lapl2_ap5276_Drizzle15.tif', None, 317, 0.90, 353, 0.58),
        ('22 Sep', '2026-09-22-2120_9-Moon_Filter 4_lapl2_ap12765_Drizzle15.tif', None, 337, 0.89, 464, 0.62)]
bad = 0
for name, fname, tname, m0, r0, m1, r1 in BASE:
    path = os.path.join(IMAGES, fname)
    for kind, when, m_, r_ in (('albedo', None, m0, r0), ('shaded', capture_time(tname or path), m1, r1)):
        geo, q = locate(path, log=lambda *a: None, when=when)
        ok = q['matches'] >= 0.9 * m_ and q['rms_px'] <= r_ * 1.1 + 0.05
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name:14s} {kind}: {q['matches']:4d} matches (was {m_}), {q['rms_px']:.2f} px (was {r_}), "
              f"libration {geo.lat0:+.2f} {geo.lon0:+.2f}, {q['seconds']} s", flush=True)
sys.exit(1 if bad else 0)
