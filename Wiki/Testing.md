# Testing LunarAtlas

1.0.2 is an early release. It has been built and measured on a Mac, and tested automatically on Windows
and Linux, but almost all of its real use so far has been by one person with one telescope.

That is the gap. If you have a photo and twenty minutes, you can close it.

## The twenty-minute pass

**1. A full disk.** Drop in a stacked full-disk photo. It should take 10–20 seconds (longer the very
first time, while it downloads the Moon maps). Does it find the right place? Are the names on the right
craters?

**2. Zoom in.** Names should appear as there is room for them, and never pile on top of each other.

**3. Click a crater.** The outline should sit on the rim, not beside it.

**4. Measure.** Press `M`, click twice. Check a distance you already know — the diameter of a crater you
have measured before, say. It should agree within a pixel or two.

**5. Export.** The names are drawn into your own image at its own resolution. Open the result at 100 %
and look at where the labels landed.

**6. A close-up with no limb in the frame.** This is the part that most needs testing. It needs the
capture time and your optics — see [Close-ups and equipment](Close-ups-and-equipment).

## What is most useful to report

In rough order of how much it would help:

| | |
|---|---|
| **A wrong answer** | Named confidently, but in the wrong place. This should never happen; it is the most serious thing you can find. |
| **A photo it refuses that it should manage** | Especially close-ups, mosaics, and thin crescents. |
| **A photo it accepts that it should refuse** | The [quality check](The-quality-check) letting through something that is clearly too poor. |
| **Anything on Windows or Linux** | Both are barely used in anger. Even "it started and worked" is a useful data point. |
| **Names that look off by a pixel or two** | Useful, but expected near the terminator and on the unlit side. |
| **Wording that confused you** | If a message made you stop and think, it is a bug in the message. |

## What is already known

Please check [Limits](Limits) before reporting — these are known, measured, and documented:

- steeply oblique views of the limb (near the pole, grazing angle) do not locate;
- very thin crescents without a capture time often do not locate;
- close-ups always need a capture time;
- names on the unlit side are extrapolated and can be a few pixels out;
- maria have no real outlines, only craters do.

## How to report it

Open an issue: **[github.com/kvandebeek/lunaratlas/issues](https://github.com/kvandebeek/lunaratlas/issues)**

What makes a report easy to act on:

1. **The log.** On the progress page, open **Details** and press **Copy**. It says exactly what was tried.
2. **Your platform and version** — macOS/Windows/Linux, and which LunarAtlas release.
3. **The photo**, if you are willing to share it. If not, its size in pixels, the telescope and camera,
   and whether it is a full disk, a mosaic or a close-up.
4. **What you expected**, and what happened instead.

A screenshot of a name in the wrong place is worth a lot of description.

## If you want to go further

- **Run it from source.** `python3 lunaratlas/lunaratlas.py app` from a checkout does the same as the app.
  See [Installing](Installing).
- **Run the test suite.** `python3 -m unittest discover -s lunaratlas/tests -t lunaratlas/tests`, standard
  library only, no extra packages.
- **Try the command line** on a whole folder at once: `batch` locates and exports an evening's session and
  prints a table of what happened. See [The command line](The-command-line).

Thank you — genuinely. A first release is only as good as the photos it has been pointed at, and so far
that is a small number of them.
