"""A frame with only a stretch of limb (and a ragged terminator): too little of its outline is limb for a full disk, but
the arc gives the scale and the capture time the libration and the Sun, so atlas_geo.partial_pose finds the turn
against the lit relief. Before it, such frames went to the blind close-up search and were not found."""
import io
import math
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

import cv2
import numpy as np

import _support as S
import atlas_geo as ag
from atlas_ephem import ephemeris

W, H = 1200, 800
WHEN = datetime(2026, 10, 1, 23, 26, tzinfo=timezone.utc)     # the real frame this was made for: Clavius at the limb


class Arc(unittest.TestCase):
    def test_the_share_of_the_disk_in_the_frame(self):
        self.assertAlmostEqual(ag.disk_in_frame(600, 400, 300, W, H), 1.0, places=2)
        self.assertAlmostEqual(ag.disk_in_frame(0, 400, 300, W, H), 0.5, delta=0.02)
        self.assertLess(ag.disk_in_frame(600, 2100, 1900, W, H), 0.2)

    def test_a_stretch_of_limb_along_a_ragged_terminator_is_a_long_clean_arc(self):
        img = np.zeros((H, W), np.uint8)
        cv2.circle(img, (600, 2100), 1900, 200, -1)
        rng = np.random.default_rng(1)
        ys = np.arange(H)
        edge = (250 + 0.35 * ys + rng.normal(0, 25, H).cumsum() * 0.3).astype(int)    # a ragged shadow line
        for y, x in zip(ys, edge):
            img[y, :max(0, x)] = 0
        cx, cy, R, share, span = ag.fit_limb(img.astype(np.float32), arc=True)
        self.assertAlmostEqual(R, 1900, delta=1900 * 0.02)
        self.assertGreaterEqual(span, ag.PARTIAL_SPAN)
        self.assertEqual(len(ag.fit_limb(img.astype(np.float32))), 4, 'without arc, as every caller had it')


@S.needs_relief
class PartialPose(unittest.TestCase):
    """A synthetic frame: the LOLA relief lit by the Sun at WHEN, a sunlit stretch of the limb across the top and a
    fifth of the disk in the frame. (Near the south pole, which the libration tips away that night, the rendered relief
    stops short of the limb, so a synthetic frame there has no true limb to fit.)"""

    def test_the_turn_and_place_are_found_from_the_limb_and_the_time(self):
        from atlas_closeup import Relief, render_shaded
        e = ephemeris(WHEN)
        A, t = ag.similarity(600, 1500, 1250, 140, False)
        truth = ag.Geometry(e['sub_obs_lat'], e['sub_obs_lon'], A, t)
        img, _ = render_shaded(truth, W, H, Relief(16, S.quiet), S.reference(), (e['sub_sun_lat'], e['sub_sun_lon']))
        img = cv2.GaussianBlur(img, (0, 0), 0.8) / max(float(img.max()), 1e-6)
        img = np.clip(img + np.random.default_rng(2).normal(0, 0.004, img.shape), 0, 1) * 50000 + 800
        self.assertLess(ag.disk_in_frame(600, 1500, 1250, W, H), ag.PARTIAL_DISK)
        log = io.StringIO()
        with redirect_stdout(log):
            geo, q = ag.locate(img.astype(np.float32), when=WHEN)
        self.assertIn('turning the lit relief', log.getvalue())
        for x, y in ((W / 2, H / 2), (900, 300), (300, 600)):
            got, want = geo.to_latlon(x, y), truth.to_latlon(x, y)
            with self.subTest(x=x, y=y):
                self.assertTrue(want[2] and got[2], 'on the disk')
                self.assertLess(abs(float(got[0]) - float(want[0])), 0.3)
                self.assertLess(abs(float(got[1]) - float(want[1])) * math.cos(math.radians(float(want[0]))), 0.3)
        self.assertGreaterEqual(q['matches'], 30)


if __name__ == '__main__':
    unittest.main()
