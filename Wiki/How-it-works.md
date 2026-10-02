# How it works

You do not need any of this to use LunarAtlas. It is here because "it just knows where the photo points"
is the kind of claim that deserves an explanation.

## A photo with the Moon's edge in it

**1. Find the limb.** A circle is fitted through the sharp sunlit edge, with RANSAC so that a few stray
points — a bright cloud edge, a hot pixel — cannot drag it off.

**2. Work out which way is up.** Every angle, both mirror states and the libration are scored by brute
force. The best ten peaks are refined, and each is then *verified* by matching real terrain. This
verification matters: on a crescent the highest-scoring orientation is often the wrong one, and only the
terrain can tell.

**3. Match the terrain.** Between 200 and 1000 patches of your photo are matched against a reference
Moon, coarse to fine — the disk at 1024, then 2048, then 4096 pixels. The grid gets denser when there is
little sunlit terrain to work with. A weak finer stage never replaces a good coarser one.

The reference is not a photograph. It is LOLA elevation data, lit from where the Sun actually was that
night, multiplied by the LROC WAC albedo map. That is why it works at any phase: the shadows in the
reference fall the same way as the shadows in your picture. Without a capture time, the Sun's position is
worked out from the terminator in your own photo, which also covers the polar regions and shadows near
the terminator.

**4. Fit a model.** A perspective sphere (the Moon at 221 lunar radii), an affine map, and a smooth
polynomial correction whose degree is chosen by cross-validation, so it corrects real distortion without
inventing any.

## A close-up with no edge at all

There is no circle to fit, so LunarAtlas searches:

1. Your photo is reduced to 4.8 km/px and turned in 4° steps, mirrored and not.
2. Each view is correlated against the whole Earth-facing hemisphere — again LOLA relief lit by the real
   Sun, times the albedo — at the same coarse scale. The best distinct places of each candidate scale are
   kept, 30 in all, at least 3 per scale, ranked *across* scales so that a small view's lucky peak cannot
   push out the true place at a slightly wrong scale.
3. Each is searched again at 2.4 km/px, in a window around where it was found, at every 1° within ±4°.
   Correlation is sharp in angle, so this also pins the angle down better than a 4° search would.
4. The best places are verified by real terrain matching, best scale first. A fit counts only with at
   least 15 matches and at most 6 px RMS — a wrong place can gather 15 matches that agree with each other
   at 20 px or more. The winner is fitted with the libration held fixed.

Coarse-to-fine makes this 2–3 times faster than searching everything at full scale: 28 s → 15 s with
known optics, 97 s → 38 s with twelve unbinned setups to try.

This is why [your equipment](Close-ups-and-equipment) matters: each setup you own is another scale to
search.

## How accurate is it

Measured on 2026-09-28 with the lit-relief reference, via `experiments/quality/baseline.py`:

| Image | Matches | RMS |
|---|---|---|
| 25 Sep mosaic (200 Mpx) | 620 | 1.55 px |
| 5 Aug | 390 | 0.42 px |
| 23 Sep | 353 | 0.58 px |
| 22 Sep | 464 | 0.62 px |

On the 200-megapixel mosaic that is 621 terrain matches at 1.56 px RMS — **0.43 km** on the Moon.

Across a batch of 590+ test files, including about 38 folders of deliberately damaged variants, there
were **zero** cases of "solved, but more than 1° from the truth". When LunarAtlas is unsure, it refuses.
That is the behaviour the accept thresholds are tuned for.

## What gets saved

Beside your photo, `IMAGE.atlas.json` holds the geometry, the quality of the fit, the quality-check
verdict, and your viewer edits. It is plain JSON, and it is what lets the command line and the app agree
about a photo.

## Where to read the code

| File | What is in it |
|---|---|
| `atlas_geo.py` | Full-disk positioning: limb fit, orientation, terrain matching, the sphere model. |
| `atlas_closeup.py` | Close-ups: optics, the lit LOLA reference, the blind search. |
| `atlas_ephem.py` | Ephemeris (Meeus): libration, subsolar point, Earth–Moon distance. |
| `atlas_quality.py` | The quality gate's measures and verdict. |
| `atlas_names.py` | The IAU nomenclature (9087 features) and landing sites. |
| `atlas_render.py` | Label layout, drawing, the grid, the info block. |
| `atlas_view.py`, `viewer/` | The viewer and editor. |
| `atlas_app.py` | The launcher. |
