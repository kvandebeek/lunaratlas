# moon_atlas

IAU feature names on your own lunar images, like LROC QuickMap but with your data. It works on full disks, any phase, mosaics and close-ups without a limb. It finds the image's position, orientation, mirroring and libration automatically, refuses images that are too poor to annotate, and exports labelled images at 1:1 or smaller (never upscaled). It needs Python 3.14 with numpy, OpenCV and Pillow, like the mosaic tools, on macOS, Linux or Windows.

| File | What it does |
|---|---|
| `moon_atlas.py` | The CLI: `locate`, `export`, `info`, `find`, `view`. |
| `atlas_geo.py` | Positioning of full disks: limb fit, orientation candidates verified by terrain matching, perspective sphere model with a smooth correction, and sidecar I/O. |
| `atlas_closeup.py` | Close-ups without a limb: optics, the lit LOLA relief reference, and the blind search. |
| `atlas_ephem.py` | Ephemeris (Meeus) from the SharpCap UTC time: libration, subsolar point, Earth–Moon distance. |
| `atlas_quality.py` | The quality gate's measures and verdict; limits in `data/quality_thresholds.json`. |
| `atlas_names.py` | IAU nomenclature (9087 features) and landing sites. |
| `atlas_render.py` | Label layout and drawing, lat/lon grid, the viewer's drawings, and the info block. |
| `atlas_view.py`, `viewer/` | `view`: the local browser viewer and editor. |
| `data/` | Downloaded once: IAU list, LROC WAC 643 nm albedo, LOLA elevation (16 and 64 px/deg, `lola/`), fonts. |
| `experiments/quality/` | Quality survey, labelling page, `calibrate.py`, and `baseline.py` (a regression test, exit 1 on a regression). |
| `tests/viewer_selftest.js` | Editor self-test (open `/selftest` on a running viewer; `?group=NAME` runs one journey). |
| `tests/` | The test suite, stdlib `unittest` and nothing else: `python3 -m unittest discover -s moon_atlas/tests -t moon_atlas/tests`. |

## Typical use

```sh
A=../moon_atlas/moon_atlas.py   # path to moon_atlas.py in your checkout
python3 $A locate mosaic_finished.tif          # quality gate, then position (10–20 s; close-ups 30–100 s)
python3 $A info mosaic_finished.tif
python3 $A view mosaic_finished.tif            # browser viewer and editor
python3 $A export mosaic_finished.tif --max-size 2400 -o overview.jpg
python3 $A export mosaic_finished.tif --around Copernicus --size 3600x2400
python3 $A find mosaic_finished.tif "Rupes Recta"
```

## Quality gate

Before locating, the image is measured:
- saturation (the largest clipped area);
- the limb's edge width;
- dark and bright rings at the limb (over-sharpening);
- grain in flat maria;
- JPEG blocking on the Moon;
- posterisation;
- colour boost (chroma);
- red/blue fringes at the limb relative to its width.

The limits were calibrated on 80 labelled images (`calibrate.py`). They refuse every rejected image that can be located (6 of 9) and none of the 71 accepted ones. A refused image is not annotated. Use `--force` on `locate`, `export` or `view` to override. `find` always works. `info` shows the verdict, which is also stored in the sidecar.

## Close-ups without a limb

The observing site (used for the parallax, up to 1° of libration) and the equipment are settings; see "Settings" below.

A close-up needs its capture time, taken from the SharpCap name `YYYY-MM-DD-HHMM_T-…` in UTC. For a mosaic, the middle of its panels' times from `mosaic_layout.json` is used. From the time, the ephemeris gives the lighting and the libration. The optics are asked once per folder when a terminal is attached, and stored in `moon_atlas_optics.json`. Otherwise all 12 setups of the 250 PDS are tried: native, 2× ES, 2.5× TV Powermate or 3× ES, with the IMX678, IMX533 or IMX462. The setup that fits is then recognised and saved for the folder.

The search works in three steps:
1. The image is reduced to 2.4 km/px and turned in 4° steps, mirrored and not.
2. Each view is correlated against LOLA relief of the whole Earth-facing hemisphere, lit by the real Sun and multiplied by the albedo.
3. The best places are verified by terrain matching, and the winner is fitted with the libration held.

Measured on 5 of the user's close-ups and one close-up mosaic: all found correctly, in 20–100 s.

## Settings

Per-machine settings live in `.env` in the repository root, which is not committed; `.env.example` lists every key with its default. The same file serves moon_atlas, lunar_finish and mosaic_builder.
- **moon_atlas:** observing site, equipment (telescope, focal length, extenders, cameras), export defaults (font, detail level, label size, night side, JPEG quality) and the viewer port.

Command-line options override `.env`; environment variables of the same name override the file; `--help` shows the value in effect. All 60 settings are declared once in `tool_settings.py`, with their type, default and range. `.env.example` is generated from there (`python3 tool_settings.py --example`), so its documented ranges are the enforced ones. `python3 tool_settings.py --check` shows the value in effect for every setting and reports out-of-range values and unknown keys, which fall back to the default. On/off settings have both forms on the command line, for example `--rims` / `--no-rims`.

## Export

```sh
--format tiff|png|jpg    --scale S | --max-size N    --region x,y,w,h | --around NAME --size WxH
--min-size PX (24)       --font FAMILY               --font-scale F    --night hide|dim|show
--layers area,crater,lettered,relief,landing|none    --no-rims  --no-lettered  --no-landing
--no-grid  --no-drawings  --no-info                  --quality Q (JPEG)  --force
```

Exports include:
- the names, in one colour, with maria in larger spaced capitals, Roboto and a soft shadow;
- crater outlines;
- the lat/lon grid, labelled along the equator and the central meridian;
- the drawings and measurements made in the viewer;
- names hidden, moved or restyled in the viewer;
- an info block with the capture time, the optics, a scale bar and N/E arrows.

On close-ups, night-side names are hidden by the Sun's elevation at the capture time.

## Viewer (`view`)

A local server on 127.0.0.1 opens the page in the browser.
- **Tiles** are cached in `~/Library/Caches/moon_atlas` and rebuilt when the image changes.
- **Names** appear by zoom level: craters from 24 px across, one label colour. Crater outlines show for the selected crater only; a switch shows them all.
- **Search and info:** search, an info card, and a lat/lon grid (G).
- **Measuring:** km along the great circle.
- **Your own drawings:** circles, ellipses, rectangles, outlines, arrows and text.
- **Editing:** drag drawings and their square handles; drag a name to move it, and recolour or resize it in its card; undo and redo with ⌘Z and ⇧⌘Z.
- **Fonts:** Roboto, Inter, IBM Plex Sans, Barlow, Geist and Space Grotesk, served locally.
- **Saving:** edits are stored in `IMAGE.atlas.json` under `edits`.
- **Export:** the Export button runs the real export, with progress and a button that shows the result in
  the desktop file manager (Finder, Explorer, or whatever `xdg-open` picks).

## How positioning works (full disks)

1. **Limb:** a RANSAC circle through the sharp sunlit edge.
2. **Orientation:** a brute-force score over every angle, both mirror states and the libration. The best 10 peaks are refined and each is verified by real terrain matching. On crescents the highest score is often wrong.
3. **Terrain matching:** 200–1000 patches are matched coarse to fine (disk 1024 → 2048 → 4096 px). The grid gets denser when little sunlit terrain is available. The reference is LOLA relief lit by the Sun, times the albedo. The Sun comes from the capture time or, without one, from the terminator, which covers the polar regions and terminator shadows. A weak finer stage never replaces a good coarser one.
4. **Model:** a perspective sphere (Earth–Moon distance 221 lunar radii), an affine map, and a smooth polynomial correction whose degree is chosen by cross-validation.

Measured on 2026-09-28, with the lit-relief reference, using `experiments/quality/baseline.py`:

| Image | Matches | RMS |
|---|---|---|
| 25 Sep mosaic | 620 | 1.55 px |
| 5 Aug | 390 | 0.42 px |
| 23 Sep | 353 | 0.58 px |
| 22 Sep | 464 | 0.62 px |

## Limits

- Close-ups need a capture time; a renamed file without one cannot be searched yet.
- Very thin crescents from AstroBin (no timestamp) often cannot be located: 28 of 78 of that test set locate. The rest are close-ups without a time and thin crescents.
- The correction field is fitted on the sunlit side and extrapolates onto the night side (up to about 4 px); night-side names are hidden by default.

Data: USGS Gazetteer of Planetary Nomenclature (IAU); LROC WAC empirically normalized 643 nm mosaic (NASA/GSFC/Arizona State University); LOLA gridded elevation LDEM 16 and 64 px/deg (NASA/GSFC). Landing-site positions are approximate.
