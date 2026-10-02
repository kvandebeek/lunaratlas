# Settings reference

LunarAtlas keeps settings in three places, each for a different kind of thing.

| | Where | What |
|---|---|---|
| **Your equipment and site** | `equipment.json` | Telescopes, barlows, cameras, observing site. Edit in **Settings** in the app. |
| **Your viewer edits** | `IMAGE.atlas.json` | Per photo: hidden and moved names, colours, drawings, layer switches. |
| **Export defaults** | `.env` | What `export` should do when you do not say. |

The first two are managed for you by the app. The third is for people who use the command line.

## Equipment and observing site

Set in the app: **Settings** at the bottom of the home page, or the short form at the first close-up. The
command line reads exactly the same file. See [Close-ups and your equipment](Close-ups-and-equipment).

`LUNARATLAS_EQUIPMENT` can point at a different file, which is useful for testing.

> The old `.env` keys `LUNARATLAS_TELESCOPE`, `_FOCAL_MM`, `_EXTENDERS`, `_CAMERAS`, `_BINNINGS` and
> `_OBSERVER_*` are no longer read. If you still have them, LunarAtlas warns you and says where they went.

## Export defaults: `.env`

Create a `.env` in the repository root. `.env.example` lists every key with its default, and is generated
from the single declaration of each setting, so its documented ranges are the ones actually enforced:

```sh
python3 tool_settings.py --example     # regenerate .env.example
python3 tool_settings.py --check       # the value in effect for every setting, with warnings
```

### Export

| Key | Default | What it does |
|---|---|---|
| `LUNARATLAS_FORMAT` | `tiff` | Output format when `-o` does not decide it. One of tiff, png, jpg. |
| `LUNARATLAS_MAX_SIZE` | `0` | Longest output side in px; 0 means 1:1. Never upscaled. 0–100000. |
| `LUNARATLAS_AROUND_SIZE` | `3000x2000` | View size in source px for `--around NAME`. |
| `LUNARATLAS_MIN_SIZE` | `24.0` | Smallest crater that gets a name, in output px. 4–400; 16–40 is typical. |
| `LUNARATLAS_FONT` | `IBM Plex Sans` | IBM Plex Sans, Source Sans 3 or Roboto (bundled), or any Google Fonts family. |
| `LUNARATLAS_FONT_SCALE` | `1.0` | Label size factor. 0.3–5; 0.8–1.6 is typical. |
| `LUNARATLAS_NIGHT` | `dim` | Names on the unlit side: hide, dim or show. |
| `LUNARATLAS_LAYERS` | `area,crater,lettered,relief,landing` | Which classes of names, or `none`. |
| `LUNARATLAS_RIMS` | `1` | Crater outlines in exports. |
| `LUNARATLAS_LETTERED` | `1` | Lettered satellite craters (Copernicus A, …). |
| `LUNARATLAS_LANDING` | `1` | Landing sites. |
| `LUNARATLAS_GRID` | `1` | Lat/lon grid in exports. |
| `LUNARATLAS_DRAWINGS` | `1` | Your viewer drawings and measurements in exports. |
| `LUNARATLAS_INFO` | `1` | Info block: date, optics, scale bar, N/E arrows. |
| `LUNARATLAS_JPEG_QUALITY` | `92` | JPEG quality. 0–100; 85–95 is typical. |

### Viewer

| Key | Default | What it does |
|---|---|---|
| `LUNARATLAS_VIEW_PORT` | `8766` | First port to try; the next free one is used. 1024–65535. |
| `LUNARATLAS_VIEW_OPEN` | `1` | Open the browser when the viewer starts. |

### Paths and other environment variables

| Variable | What it does |
|---|---|
| `LUNARATLAS_DATA` | Use another folder for the downloaded reference data. |
| `LUNARATLAS_EQUIPMENT` | Use another equipment file instead of `equipment.json`. |
| `LUNARATLAS_TOKEN` | Set the viewer's access token yourself, for scripts and tests. |

## Precedence

```
command-line option  >  environment variable  >  .env  >  built-in default
```

`--help` on any command shows the value in effect, not just the built-in default.

On/off settings have both forms on the command line (`--rims` / `--no-rims`), so a `.env` default can
always be overridden either way.

Out-of-range values and unknown keys are reported and the default is used — LunarAtlas never silently
accepts a setting it does not understand. A `.env` saved by Windows as UTF-8 with a byte-order mark is
read correctly.

The same `.env` also carries settings for the companion tools (`lunar_finish`, `mosaic_builder`,
`panel_classifier`); only the `LUNARATLAS_*` keys above concern this project. All 52 settings across the
tools are declared once, in `tool_settings.py`.
