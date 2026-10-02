# Limits

What LunarAtlas does not do, and where it is known to fall short. Everything here is measured, not
guessed.

## It refuses rather than guesses

This is the design decision everything else follows from. Across a batch of 590+ test files there were
**zero** cases of "positioned confidently, but more than 1° from the truth". When the evidence is not
there, LunarAtlas says it cannot place the photo.

The cost is that some legitimate photos are refused.

## Known: steeply oblique views of the limb

Photos showing the Moon's edge at a grazing angle — mosaic panels or single-channel frames near the pole,
often near the terminator too — do not locate. In the test set, 7 of 101 unedited originals were of this
kind.

Two things compound:

1. **The circle fit is unstable on a shallow arc.** When the visible limb is only gently curved across
   the frame, fitting a circle to it is ill-conditioned: small noise swings the fitted centre and radius
   wildly. LunarAtlas detects this and refuses, rather than returning nonsense.
2. **The close-up fallback does not rescue it.** The blind search comes back with no terrain matches on
   these frames; extreme foreshortening near the limb plus partial shadow is a harder matching problem
   than a normal tight crop.

Status: observed, not fixed. It refuses cleanly, so it is safe — but it means some good photos never
auto-locate.

## Very thin crescents without a timestamp

Of one test set of 78 such images, 28 locate. The rest are close-ups with no capture time, and thin
crescents. A capture time helps a great deal here, because it fixes the lighting that the shape alone
cannot.

## Close-ups need a capture time

No exception. Without one there is no way to know how the Moon was lit or tilted. The name usually
provides it; `--time` or the app's question covers the rest.
See [Close-ups and your equipment](Close-ups-and-equipment).

## The unlit side is extrapolated

The smooth correction field is fitted on the sunlit terrain and extrapolated onto the night side, where
it can be off by up to about 4 pixels. That is why night-side names are hidden by default; `dim` and
`show` are there when you want them anyway.

## Maria have no real outlines

Clicking a crater draws its rim, because the gazetteer gives each crater a centre and a diameter, and
craters are close enough to circular for that to be true.

Maria are not. Mare Imbrium's entry is one centre and a nominal 1145 km diameter, but Imbrium is a
pear-shaped basin — a circle that size would be plain wrong and would swallow its neighbours. Real mare
outlines need true boundary polygons, which LunarAtlas does not have. Deferred rather than approximated.

## Landing-site positions are approximate

Good enough to point at the right place, not survey data.

## What it is not

- **Not a stacker, sharpener or mosaic builder.** Give it a finished picture.
  [LunarMosaic](https://github.com/kvandebeek/lunarmosaic) builds the mosaics; this annotates them.
- **Not a plate solver for the sky.** It positions a photo on the *Moon*, not among the stars.
- **Not an atlas of the far side.** It names what your photo shows, which is the Earth-facing hemisphere
  plus whatever libration brings into view.
- **Not a measurement instrument.** The km figures are good to the accuracy in [How it works](How-it-works)
  — around half a kilometre on a good mosaic — but they are derived from a fit, not from a survey.

## Platform caveat

Developed and measured on macOS (Apple silicon). Windows and Linux are built and tested automatically on
every change, but have had far less use on real hardware. If something is wrong there, please
[say so](https://github.com/kvandebeek/lunaratlas/issues).
