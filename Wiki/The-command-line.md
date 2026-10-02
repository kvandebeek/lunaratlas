# The command line

Everything the app does, and a few things it does not: whole folders at once, scripted exports, and
feature positions as data.

From a checkout:

```sh
python3 lunaratlas/lunaratlas.py COMMAND …
```

The packaged app ships the same thing as `lunaratlas-cli` beside the app binary.

| Command | What it does |
|---|---|
| `locate IMAGE` | Work out where every pixel lies on the Moon; saves `IMAGE.atlas.json`. |
| `export IMAGE` | A labelled 16-bit TIFF, 16-bit PNG or JPEG, at 1:1 or smaller. |
| `info IMAGE` | The geometry and quality of a photo already located. |
| `find IMAGE NAME …` | Where named features are in the image. |
| `batch FOLDER` | Locate and export every photo in a folder, then a table of what happened. |
| `view IMAGE` | The browser viewer and editor. |
| `app` | The launcher: pick a photo, locate it, view and export it. |

A typical session:

```sh
A=lunaratlas/lunaratlas.py
python3 $A locate mosaic_finished.tif                       # 10–20 s; close-ups 30–100 s
python3 $A info   mosaic_finished.tif
python3 $A view   mosaic_finished.tif                       # look around, draw, hide names
python3 $A export mosaic_finished.tif --max-size 2400 -o overview.jpg
python3 $A export mosaic_finished.tif --around Copernicus --size 3600x2400
```

## locate

```
locate IMAGE [--force] [--time UTC] [--setup ID] [--any-scale]
```

| | |
|---|---|
| `--force` | Locate even if [the quality check](The-quality-check) refuses the photo. |
| `--time YYYY-MM-DDTHH:MM` | The capture time in **UTC**, for a file whose name has none. |
| `--setup ID` | For a close-up: the equipment it was taken with (an id from your equipment). |
| `--any-scale` | For a close-up: search every scale instead of the known optics. |

The result is saved beside the photo as `IMAGE.atlas.json`, and every later command reuses it.

## export

```
export IMAGE [-o FILE] [--format tiff|png|jpg] [options]
```

**How much, and how big**

| | |
|---|---|
| `--scale S` | Output scale, at most 1 (never upscaled). |
| `--max-size N` | Longest output side in px (never upscaled). |
| `--region x,y,w,h` | A rectangle in source pixels. |
| `--around NAME` | Centre on a named feature. |
| `--size WxH` | The view size for `--around` (default 3000x2000). |
| `--fit` | With `--around`: size the view from the feature's own diameter — 2.2 × it, at least 600 px. `--size` then gives only the shape. |
| `--north-up` | Turn so lunar north is up and east right, never mirrored. Not with `--region`. |

**What goes on it**

| | |
|---|---|
| `--min-size PX` | Smallest crater that gets a name, in output px (default 24). |
| `--layers LIST` | `area,crater,lettered,relief,landing`, or `none`. |
| `--no-rims` / `--no-lettered` / `--no-landing` | Drop crater outlines, satellite craters, landing sites. |
| `--no-grid` / `--no-drawings` / `--no-info` | Drop the grid, your viewer drawings, the info block. |
| `--night hide\|dim\|show` | Names on the unlit side (default `dim`). |
| `--font FAMILY` | IBM Plex Sans, Source Sans 3, Roboto (bundled) or any Google Fonts family (downloaded once). |
| `--font-scale F` | Label size factor. |
| `--quality Q` | JPEG quality (default 92). |
| `--force` | Export despite the quality check. |
| `--overwrite` | With `-o`: replace a file that is already there. The default name is always replaced. |

Every on/off option has both forms, for example `--rims` / `--no-rims`, so you can override a `.env`
default from the command line.

Your viewer edits — hidden names, moved names, colours, drawings, measurements — are used automatically.

## batch

```
batch FOLDER [-r] [--skip-existing] [--locate-only] [any export option]
```

Locates (when needed) and exports every TIFF, PNG and JPEG in the folder, in name order. `-r` includes
sub-folders. Hidden files and earlier exports (`IMAGE_atlas….ext`) are skipped.

One photo that cannot be done — damaged, refused, no limb and no time — is reported and the rest carry
on. A table at the end lists every photo's result, and the exit status is 1 if any failed.

`--skip-existing` leaves alone photos whose export is already there and not older than the source.

```sh
python3 $A batch ~/Pictures/session --max-size 2400 --format jpg --skip-existing
```

## find

```
find IMAGE NAME [NAME …] [--json|--csv] [--time UTC]
```

Answers, for each name, where it is in your picture. An exact name wins; otherwise names that start with
what you typed (`Copernicus` also lists `Copernicus A`, `B`, …); a misspelling gets suggestions.

`--json` and `--csv` print the answers as data, with progress messages going to stderr so you can pipe
cleanly. The exit status is 1 if any name was not found. `find` ignores the quality check.

```sh
python3 $A find mosaic.tif "Rupes Recta" Tycho --csv
```

## info

Prints the geometry, the quality of the fit (matches, RMS), and the quality-check verdict. With a capture
time it also prints the sky: the phase (`first quarter, 51 % of the disk lit`), the phase angle, where
the Sun was overhead, the colongitude and the Earth–Moon distance.

## view

```
view IMAGE [--port PORT] [--no-open] [--force] [--time UTC]
```

Starts a local server on 127.0.0.1 and opens the page. `--no-open` prints the address instead.

## app

```
app [--port PORT] [--no-open] [--folder FOLDER] [--no-window] [--idle-exit SECONDS]
```

The launcher — what the packaged app runs. `--folder` changes the work folder (default
`~/Pictures/LunarAtlas`). With [pywebview](https://pywebview.flowrl.com) installed it gets a window of
its own; `--no-window` forces the browser, and `--idle-exit SECONDS` then stops it that long after the
last page was closed.

Starting it twice brings the running one forward instead of starting a second.

## Settings and precedence

Options can be given defaults in a `.env` file; see [Settings reference](Settings-reference).

```
command-line option  >  environment variable  >  .env  >  built-in default
```

`--help` on any command shows the value actually in effect.
