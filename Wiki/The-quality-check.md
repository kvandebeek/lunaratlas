# The quality check

Before it tries to place your photo, LunarAtlas measures it. If the picture has been damaged in ways that
make the result untrustworthy, it says so and stops.

This is deliberate. A wrong label placed confidently is worse than no label.

![A photo refused by the quality check](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/quality-refused.png)

## What it measures

| Reason you may see | What it means | What usually causes it |
|---|---|---|
| **Overexposed** | A large patch of the Moon is clipped to pure white, with no detail left to match. | Exposure too long; a stretch that pushed the highlights off the top. |
| **Too blurry** | The edge of the Moon is soft, so small craters cannot be placed reliably. | Poor seeing, missed focus, too long an exposure per frame. |
| **Over-sharpened** | A bright and dark halo rings the limb — detail that is not on the Moon. | Too much wavelet or unsharp mask. |
| **Too noisy** | Grain in the smooth maria hides the fine detail used to match. | Too few frames stacked, or high gain. |
| **Heavy JPEG compression** | Blocky artefacts across the Moon. | A re-saved JPEG. Use the original, or TIFF/PNG. |
| **Colours boosted** | Saturation far beyond the Moon's own, disturbing the brightness matching relies on. | Heavy colour processing. |
| **Colour fringes** | Red and blue edges of the Moon do not line up. | Atmospheric dispersion (low altitude, no ADC) or chromatic aberration. |
| **Posterised** | Grey levels are missing. | A strong stretch applied to an 8-bit image. |

Each reason comes with the raw measurement and the limit it crossed, under the plain-language
explanation, so you can see how far over it was.

## Where the limits come from

They were calibrated on 80 labelled images. On that set they refuse every rejected image that could still
be located (6 of 9), and none of the 71 good ones. The limits live in `quality_thresholds.json`, next to
the downloaded data.

The check is deliberately generous: it is looking for pictures that are *damaged*, not pictures that are
merely soft or faint.

## Naming it anyway

**Name it anyway** overrides the check and annotates the photo regardless. This is often perfectly
reasonable — the gate cannot know that a soft night was the only clear night you got.

What you lose is confidence, not the result. The photo keeps a warning in the viewer's status bar:

![The quality warning in the status bar](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-quality-chip.jpg)

Click it and you get the full explanation again, with the measurement:

![The quality warning explained](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-quality-explained.jpg)

The warning is remembered with the photo, so you cannot forget later why a name sits slightly off a
crater.

## On the command line

The same gate applies, and `--force` is the same override:

```sh
python3 lunaratlas/lunaratlas.py locate photo.tif --force
python3 lunaratlas/lunaratlas.py export photo.tif --force
python3 lunaratlas/lunaratlas.py view   photo.tif --force
```

`info` shows the verdict for a photo already located, and `find` never applies the gate at all.

## What it is not for

It is not a judgement of your photo as a photo. It measures only the things that break *matching*. A
beautiful picture can be refused for one over-sharpened limb, and a dull one can sail through.
