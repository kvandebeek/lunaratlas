# lunaratlas

IAU feature names on your own lunar images, like LROC QuickMap but with your data. It works on full disks, any phase, mosaics and close-ups without a limb. It finds the image's position, orientation, mirroring and libration automatically, refuses images that are too poor to annotate, and exports labelled images at 1:1 or smaller (never upscaled). It needs Python 3.14 with numpy, OpenCV and Pillow, like the mosaic tools, on macOS, Linux or Windows.

| File | What it does |
|---|---|
| `lunaratlas.py` | The CLI: `locate`, `export`, `batch`, `info`, `find`, `view`, `app`. |
| `atlas_geo.py` | Positioning of full disks: limb fit, orientation candidates verified by terrain matching, perspective sphere model with a smooth correction, and sidecar I/O. |
| `atlas_closeup.py` | Close-ups without a limb: optics, the lit LOLA relief reference, and the blind search. |
| `atlas_ephem.py` | Ephemeris (Meeus) from the SharpCap UTC time: libration, subsolar point, Earth–Moon distance. |
| `atlas_quality.py` | The quality gate's measures and verdict; limits in `data/quality_thresholds.json`. |
| `atlas_names.py` | IAU nomenclature (9087 features) and landing sites. |
| `atlas_render.py` | Label layout and drawing, lat/lon grid, the viewer's drawings, and the info block. |
| `atlas_view.py`, `viewer/` | `view`: the local browser viewer and editor. |
| `atlas_app.py`, `viewer/app.html` | `app`: the browser launcher (pick a photo, locate, view, export), also what the packaged app runs. |
| `atlas_paths.py` | Data, cache and settings folders per platform, from a checkout or from the packaged app. |
| `data/` | Downloaded once: IAU list, LROC WAC 643 nm albedo, LOLA elevation (16 px/deg, ≈ 33 MB; 64 px/deg, ≈ 530 MB, close-ups only; `lola/`), fonts. In the packaged app: the user's application-data folder; `LUNARATLAS_DATA` overrides it. |
| `experiments/quality/` | Quality survey, labelling page, `calibrate.py`, and `baseline.py` (a regression test, exit 1 on a regression). |
| `tests/viewer_selftest.js` | Editor self-test (open `/selftest` on a running viewer; `?group=NAME` runs one journey). |
| `tests/` | The test suite, stdlib `unittest` and nothing else: `python3 -m unittest discover -s lunaratlas/tests -t lunaratlas/tests`. |

## Typical use

```sh
A=../lunaratlas/lunaratlas.py   # path to lunaratlas.py in your checkout
python3 $A locate mosaic_finished.tif          # quality gate, then position (10–20 s; close-ups 30–100 s)
python3 $A info mosaic_finished.tif
python3 $A view mosaic_finished.tif            # browser viewer and editor
python3 $A export mosaic_finished.tif --max-size 2400 -o overview.jpg
python3 $A export mosaic_finished.tif --around Copernicus --size 3600x2400
python3 $A export mosaic_finished.tif --north-up -o north_up.tif        # north up, east right, never mirrored
python3 $A export mosaic_finished.tif --around Copernicus --fit         # the view sized from the crater's own diameter
python3 $A find mosaic_finished.tif "Rupes Recta" Tycho --csv           # several names, as data (or --json)
python3 $A batch ~/Pictures/session --max-size 2400                     # every photo of a folder, then a table
python3 $A app                                 # no terminal needed after this: pick photos in the browser
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

A close-up needs its capture time, taken from the SharpCap name `YYYY-MM-DD-HHMM_T-…` in UTC. A file that has been renamed can be given its time with `--time YYYY-MM-DDTHH:MM` (UTC) on `locate` (or on `export`, `view` and `find`, which locate a photo that has no positioning yet): the time is kept in the sidecar and used by every later step, the name's own time still comes first. For a mosaic, the middle of its panels' times from `mosaic_layout.json` is used. From the time, the ephemeris gives the lighting and the libration. The optics are asked once per folder when a terminal is attached, and stored in `lunaratlas_optics.json`. Otherwise all 12 setups of the 250 PDS are tried: native, 2× ES, 2.5× TV Powermate or 3× ES, with the IMX678, IMX533 or IMX462. The setup that fits is then recognised and saved for the folder.

The search works in four steps:
1. The image is reduced to 4.8 km/px and turned in 4° steps, mirrored and not.
2. Each view is correlated against LOLA relief of the whole Earth-facing hemisphere, lit by the real Sun and multiplied by the albedo, at the same coarse scale (a quarter of the pixels). The 30 best distinct places are kept.
3. Each of those is searched again at 2.4 km/px, in a window around where it was found, at every 1° within ±4° of its angle. The correlation is sharp in angle, so this also finds the angle better than the 4° steps of a full search at 2.4 km/px (still available as `blind_search_full`).
4. The best places are verified by terrain matching, and the winner is fitted with the libration held.

Compared with the full search on synthetic close-ups, it finds the same place and is 2–3 times faster overall (28 s to 15 s with known optics, 97 s to 38 s with all 12 setups tried).

Measured on 5 of the user's close-ups and one close-up mosaic: all found correctly, in 20–100 s (before the coarse-to-fine search; see below for the speed-up).

## Settings

Per-machine settings live in `.env` in the repository root, which is not committed; `.env.example` lists every key with its default. The same file serves lunaratlas, lunar_finish and mosaic_builder.
- **lunaratlas:** observing site, equipment (telescope, focal length, extenders, cameras), export defaults (font, detail level, label size, night side, JPEG quality) and the viewer port.

Command-line options override `.env`; environment variables of the same name override the file; `--help` shows the value in effect. All 60 settings are declared once in `tool_settings.py`, with their type, default and range. `.env.example` is generated from there (`python3 tool_settings.py --example`), so its documented ranges are the enforced ones. `python3 tool_settings.py --check` shows the value in effect for every setting and reports out-of-range values and unknown keys, which fall back to the default. On/off settings have both forms on the command line, for example `--rims` / `--no-rims`.

## Export

```sh
--format tiff|png|jpg    --scale S | --max-size N    --region x,y,w,h | --around NAME --size WxH
--min-size PX (24)       --font FAMILY               --font-scale F    --night hide|dim|show
--layers area,crater,lettered,relief,landing|none    --no-rims  --no-lettered  --no-landing
--no-grid  --no-drawings  --no-info                  --quality Q (JPEG)  --force
--north-up               --around NAME --fit         --time YYYY-MM-DDTHH:MM (UTC, if it must be located)
```

`--north-up` turns the picture (and the drawings and moved names with it) so lunar north is up and east is right, never mirrored. Turning by other than a right angle makes the canvas larger; its corners are black. It works on the whole picture or with `--around`; `--region` counts pixels of the picture as it was taken and is refused with it. The viewer's export dialog has the same choice.

`--fit` with `--around` sizes the view from the feature's diameter in the gazetteer (2.2 times it, at least 600 px); `--size` then gives only the shape. A feature without a diameter (a landing site) uses `--size` as it is.

Files are written through a temporary file: an export that is stopped never leaves a half-written picture.

### Several photos: `batch`

```sh
python3 lunaratlas.py batch FOLDER [-r] [--skip-existing] [--locate-only] [any export option]
```

Locates (when needed) and exports every TIFF, PNG and JPEG in the folder in name order (`-r`: the sub-folders too), skipping hidden files and earlier exports (`IMAGE_atlas….ext`). One photo that cannot be done (damaged, refused by the quality gate, no limb and no time) is reported and the rest carry on; a table at the end lists each photo's result, and the exit status is 1 if any failed. `--skip-existing` leaves alone photos whose export is already there and not older. Each photo uses its own viewer edits.

### Finding features: `find`

`find IMAGE NAME [NAME …]` answers for each name: the exact name first, else names that start with what you typed (the others that fit are listed: `Copernicus` also lists `Copernicus A`, `B`, …), and a misspelt name gets suggestions. `--json` or `--csv` print the answers as data (progress messages go to stderr then); the exit status is 1 if any name was not found.

### The sky at the capture time

With a capture time (name or `--time`), `info` prints the phase (`first quarter, 51 % of the disk lit`), the phase angle, where the Sun is overhead, the colongitude and the Earth–Moon distance. The export's info block and the viewer's top bar show the phase too (the viewer's tooltip has the Sun and colongitude). They use the observing site of your settings for the parallax.

Exports include:
- the names, in one colour, with maria in larger spaced capitals, IBM Plex Sans and a soft shadow;
- crater outlines;
- the lat/lon grid, labelled along the equator and the central meridian;
- the drawings and measurements made in the viewer;
- names hidden, moved or restyled in the viewer;
- an info block with the capture time, the optics, a scale bar and N/E arrows.

On close-ups, night-side names are hidden by the Sun's elevation at the capture time.

## Viewer (`view`)

A local server on 127.0.0.1 opens the page in the browser.
- **Tiles** are cached in `~/Library/Caches/LunarAtlas` (Windows `%LOCALAPPDATA%\LunarAtlas\Cache`, Linux
  `~/.cache/lunaratlas`) and rebuilt when the image changes.
- **Only this machine, and only its own page:** requests with a foreign `Host` (DNS rebinding), another site's `Origin` or `Sec-Fetch-Site` (a script or image include, a frame), or without this run's token are refused; only GET and POST are answered. The token is made at every start; the address the browser is sent to carries it once and it is then kept in an HttpOnly, SameSite=Strict cookie (`lunaratlas.py view --no-open` prints that address, `--open` sends the browser to it and prints none). `LUNARATLAS_TOKEN` sets a token instead (for scripts and tests). Pages get a strict Content-Security-Policy (no inline script, no framing), the page data is JSON that the page fetches (`/data.json`; it does not name your account), and request bodies, uploads and drawings have size limits.
- **Names** appear by zoom level: craters from 24 px across, one label colour. Crater outlines show for the selected crater only; a switch shows them all.
- **Search and info:** search, an info card, and a lat/lon grid (G).
- **Measuring:** km along the great circle.
- **Your own drawings:** circles, ellipses, rectangles, outlines, arrows and text.
- **Several names at once:** hold Alt (⌥ on a Mac) and click names to add them to a selection or take them out
  again, or Alt-drag a box around an area. Delete (or the Hide button) hides them all in one undo step; Esc clears.
- **Editing:** drag drawings and their square handles; drag a name to move it, and recolour or resize it in its card; undo and redo with ⌘Z and ⇧⌘Z.
- **Fonts:** IBM Plex Sans, Source Sans 3 and Roboto, bundled with the app (lunaratlas/fonts, SIL Open Font License): nothing is downloaded. `--font` still accepts any Google Fonts family, downloaded once.
- **Saving:** edits are stored in `IMAGE.atlas.json` under `edits`.
- **Export:** the Export button runs the real export, with progress and a button that shows the result in
  the desktop file manager (Finder, Explorer, or whatever `xdg-open` picks).

## Launcher (`app`)

`lunaratlas.py app` opens a page where a photo is dropped or chosen, and the rest runs without a terminal:
locate (with its log on the page), then the viewer on the same server, with its Export button. A page link, "Other
image", goes back.
- **Work folder:** a browser gives the page a file's contents, not its path, so the photo is copied into
  `~/Pictures/LunarAtlas` (or `~/LunarAtlas`; `--folder` to change). Its sidecar and exports land next to the copy.
  The same photo again is recognised by name and size and opens at once; earlier photos are listed on the page.
- **Capture time:** when the name has no SharpCap/WinJUPOS time, the page asks for it (local time; optional for full
  disks, needed for close-ups) and puts it in front of the copy's name, so every later step finds it.
- **Refused photos:** a quality-gate refusal shows its reasons and an "Annotate anyway" button (`--force`).
- **Close-up optics** are not asked (no terminal): all setups are tried, which is slower. A
  `lunaratlas_optics.json` in the work folder is used when present.
- **Window or browser:** with [pywebview](https://pywebview.flowrl.com) installed the page gets an app window of its
  own (WebKit on macOS, Edge WebView2 on Windows) and closing it stops the launcher, including a locate or export
  that is still running. Without it (or with `--no-window`) the browser is used; `--idle-exit SECONDS` then stops the
  launcher that long after its last page was closed (the pages ping it every 20 s).
- **One at a time:** a second start brings the running window forward (or opens a browser page on it). It finds the first one through a file only you can read (`running.json` in the data folder) and checks, with a proof that needs the token, that what answers on the port is that launcher.
  "Quit LunarAtlas" on the page stops it.

The packaged app (see [`packaging/`](../packaging/README.md)) is this launcher with Python and the libraries built in.

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

- Close-ups need a capture time, from the name or from `--time`.
- Very thin crescents downloaded without a timestamp often cannot be located: 28 of 78 of that test set locate. The rest are close-ups without a time and thin crescents.
- The correction field is fitted on the sunlit side and extrapolates onto the night side (up to about 4 px); night-side names are hidden by default.

Data: USGS Gazetteer of Planetary Nomenclature (IAU); LROC WAC empirically normalized 643 nm mosaic (NASA/GSFC/Arizona State University); LOLA gridded elevation LDEM 16 and 64 px/deg (NASA/GSFC). Landing-site positions are approximate.
