# Release notes

## 1.0.0 — Langrenus

The first release. LunarAtlas puts IAU feature names on your own photos of the Moon, and it is an app
now: there is nothing to install besides the app itself, and no terminal is needed at any point.

### What it does

- **Positions your photo by itself.** Full disks, any phase, mosaics, and close-ups that show no edge of
  the Moon at all. It works out the position, orientation, mirroring and libration without being told.
- **Names what it sees**, from the IAU gazetteer: 9087 features — maria, craters, lettered satellite
  craters, mountains, rilles, ridges — plus landing sites.
- **Refuses what it cannot trust.** A quality check measures the photo first and explains, in plain
  language, what is wrong; **Name it anyway** overrides it and the photo keeps the warning.
- **A viewer and editor** in the browser, or in its own window: search, measure in km along the surface,
  draw, move names, hide names, restyle them.
- **Exports** at 1:1 or smaller — never upscaled — as 16-bit TIFF, 16-bit PNG or JPEG, with the names,
  your drawings, the grid and an info block drawn in.
- **Your edits are kept** in a sidecar beside the photo, and are used again by command-line exports.
- **A command line** for whole folders at once, scripted exports, and feature positions as JSON or CSV.

### Accuracy

On a 200-megapixel mosaic: 621 terrain matches at 1.56 px RMS — 0.43 km. Across 590+ test files, no
confidently-wrong result was seen. See [How it works](How-it-works).

### Platforms

| macOS | Windows | Linux |
|---|---|---|
| `.dmg`, Apple silicon and Intel | installer `.exe`, per user, no admin rights | `.tar.gz`, with an optional menu entry |

Developed and measured on macOS (Apple silicon). Windows and Linux are built and tested on every change
but have had less real-world use — reports welcome.

### Known limits

Steeply oblique views of the limb, very thin crescents without a timestamp, and mare outlines. All
described honestly in [Limits](Limits).

### Credits and licence

Apache License 2.0. Data from USGS, NASA/GSFC and Arizona State University — see
[Credits and licences](Credits-and-licences).

---

## About version numbers

Releases are tagged `v1.0.0`. A tag may carry a crater name after the version — `v1.0.0-Langrenus` — and
it builds version 1.0.0, titled *LunarAtlas 1.0.0 – Langrenus*. The name is decoration; the version is
what counts.
