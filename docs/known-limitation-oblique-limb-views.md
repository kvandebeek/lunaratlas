# Known limitation: extreme oblique/polar limb views don't locate — 2026-10-01

## Status

Observed, not fixed. Refuses cleanly (no crash, no wrong answer), so it is
safe as-is, but it means some legitimate photos never auto-locate.

## What it is

Found during a large batch test (`scripts/test_testimages.py` over
`/Users/kristofvandebeek/Documents/TestImages`, 590+ files across Originals
and ~38 deliberately-edited variant folders). Across that run, 7 of 101
**unedited** Originals files refused to locate — all mosaic panels or
single-channel (R/G/B) frames showing the Moon's edge at a steep, oblique
angle (near the pole, often near the terminator too), for example:

- `2026-05-26-2013_0-Moonmos__lapl2_ap13020.tif`
- `2026-05-22-2101_7-MoonRGB__lapl4_ap467.tif`
- `2026-05-21-1941_9-Moon2__lapl3_ap902.tif`

## Why

Two things compound:

1. **The full-disk circle fit is unstable on a shallow arc.** When the
   visible limb is only gently curved across the frame (a grazing view,
   not a full round disk), fitting a circle to it is ill-conditioned: small
   point noise swings the fitted centre/radius wildly, sometimes far
   outside the frame entirely. This used to crash outright (see the two
   crash fixes below); it now refuses cleanly instead
   (`atlas_geo.py`: the `disk.sum() < 100` guard in `locate()`, and the
   `usable_centres`/`grid` guard against a degenerate matching window).
2. **The close-up fallback doesn't pick it up either.** `locate()` falls
   back to `locate_closeup()` on any full-disk failure, but the close-up
   blind search also comes back with 0 terrain matches on these frames —
   the combination of extreme foreshortening near the limb/pole and partial
   shadow near the terminator seems to be a harder matching problem than a
   typical tight crater crop.

## What's confirmed, so this is scoped correctly

- It is not a crash (both crash classes behind it are fixed and covered by
  regression tests — see `test_functional_geometry.py` and
  `test_closeup_search.py`).
- It is not a wrong answer: across the whole batch, 0 "solved but >1° from
  the Originals ground truth" results were seen (the per-file comparison in
  `scripts/report_testimages.py`). So the existing accept gates
  (`MAX_CLOSEUP_RMS_PX`, the `>= 15` match floor) are holding up; images in
  this class correctly refuse rather than confidently mislabel.

## If this is picked back up

Start from one of the three files above with
`python3 lunaratlas/lunaratlas.py locate <file>` and look at why the
close-up blind search's candidates all land near 0 terrain matches even
at scores of 0.3-0.4 — that's the open question, not the full-disk side
(which is already behaving as designed: refuse rather than guess).
