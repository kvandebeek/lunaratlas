# LunarAtlas — Repository Inventory and Feature Roadmap

Prepared by **Cline** (Cline CLI coding agent) on 2026-09-29.
Inspection only: no source files were changed to produce this report.

---

## Part 1 — What the app actually does

**LunarAtlas** is a Python 3.14 + numpy/OpenCV/Pillow tool (no JS build; the viewer is vanilla
HTML/canvas/JS) that puts IAU feature names on *your own* lunar photos — "LROC QuickMap but with
your data". Python 3,972 lines in `lunaratlas/`, ~2,355 lines of viewer frontend, ~6,287 lines of
tests, plus PyInstaller packaging for macOS/Windows/Linux.

### Architecture

| File | Role |
|---|---|
| `lunaratlas/lunaratlas.py` | CLI: `locate`, `export`, `info`, `find`, `view`, `app` |
| `atlas_geo.py` | Full-disk positioning: RANSAC limb fit, brute-force orientation over angle × mirror × libration, coarse-to-fine terrain patch matching, perspective-sphere + affine + polynomial correction, sidecar I/O |
| `atlas_closeup.py` | Close-ups without a limb: optics registry (12 setups from the 250 PDS), blind search over LOLA relief at 2.4 km/px in 4° steps |
| `atlas_ephem.py` | Meeus ephemeris: libration, sub-solar point, Earth–Moon distance, phase; SharpCap/WinJUPOS filename timestamp parsing |
| `atlas_quality.py` | 9-measure quality gate, thresholds calibrated on 80 labelled images |
| `atlas_names.py` | 9,110 IAU features (dBASE parser, hand-rolled) + 23 landing sites |
| `atlas_render.py` | Label layout/priority/collision, drawing, lat-lon grid, shapes overlay, info block |
| `atlas_view.py` | Localhost server: JPEG tile pyramid, feature payload, edits API, export subprocess |
| `atlas_app.py` + `viewer/app.html` | No-terminal launcher (pywebview window or browser) |
| `tool_settings.py` | 60 settings, single source of truth; generates `.env.example` |

### Feature inventory

**Positioning (the hard part, and genuinely good):** solves position, rotation, mirroring,
libration and scale automatically. Full disks 10–20 s, close-ups 30–100 s. Measured 0.42–1.55 px
RMS. Handles the full range: any phase, mosaics, limb-less close-ups.

**Quality gate:** saturation, limb edge width, over-sharpening rings, mare grain, JPEG blocking,
posterisation, chroma boost, chromatic fringing, fine-detail level. Refuses 6/9 known-bad, 0/71
good. `--force` overrides.

**Viewer/editor:** canvas with cached tile pyramid, zoom-dependent label fade-in, search (`/`),
feature info card (diameter, lat/lon, px size, "named after", IAU gazetteer link), lat/lon grid
(`G`), km measuring along great circles, drawing tools (circle/ellipse/rect/polygon-outline/arrow/
text), multi-select via Alt-click and Alt-marquee, drag-to-move names with reset, per-label
recolour/resize, layer toggles, night-side hide/dim/show, detail and label-size sliders, font
picker, undo/redo, quality chip with plain-language explanations. All edits persist to
`IMAGE.atlas.json` and are honoured by the CLI export.

**Export:** 16-bit TIFF/PNG/JPEG, 1:1 or smaller (never upscaled), region or `--around NAME`,
19 options (format, scale, layers, rims, grid, drawings, info, font, night, min-size…), live preview
in the dialog, progress, reveal-in-Finder.

**Packaging:** PyInstaller `.dmg`/Inno Setup/`.tar.gz`, CI on 3 OSes, headless-Chrome UI journey
tests via CDP.

### Two housekeeping findings

1. **6 failing tests in `test_functional_cli.py`** — stale expectations left over from the
   `moon_atlas` → `lunaratlas` rename. `output_plan` derives the default stem from the *input*
   filename (`moon.tif` → `moon_atlas.tif`, `lunaratlas.py:212`) but the test expects the literal
   `lunaratlas.tif`. Test-side, not product-side.
2. **`BUGS_AND_DESIGN_CHOICES.md` is stale** — all 4 listed bugs are already fixed in `viewer.js`
   (`syncLettered()` at line 963, dashed-arrowheads, etc.) and `test_e2e_journeys.py:467` tests
   exactly those fixes.

## Part 2 — Ranked list of functions worth implementing

Ranking is by **value per unit of risk**, assuming the current user is a lunar imager with a folder
of SharpCap raws.

### Tier 1 — Highly usable, high value, low risk

**1. Fix the 6 failing tests (and the stale BUGS doc).** ~20 minutes. Nothing ships behind a red
suite; the rename left the baseline broken and it hides real regressions.

**2. North-up export (`--north-up`).** `atlas_geo.north_up_matrix()` (line 697) is **already
written, tested, and completely unused by any product code** — it even returns the exact rotation +
mirror the viewer's compass uses. This is finished work with no UI. High value: every
astrophotographer wants a north-up, east-right version, and the repo's own design notes state the
user's preference as "North up, east right, never mirrored." Pure win — a `--north-up` flag on
`export` plus a checkbox in the export dialog. Also removes the awkward "north arrow" info block,
since north is then up.

**3. A batch/folder mode.** `lunaratlas.py batch FOLDER` — walk the folder, locate each image,
export each, one summary table at the end. This is the single biggest workflow gap: the app is
strictly one-image-per-invocation, and an observer shooting a 2,000-frame session has to loop in a
shell. The launcher already has `recent()` and folder logic, and `test_e2e_journeys.BatchOfImages`
already proves the per-image loop works. The test even asserts "one damaged image does not stop the
others" — the resilience is already designed, just not exposed.

**4. `--around` / region for the *whole named feature*, not a fixed box.** Currently
`--around NAME --size 3600x2400` requires you to guess a box size. `--around NAME --fit` could size
the box from the feature's own diameter (which is in the gazetteer) and derive the aspect ratio from
the disk. Small, obvious ergonomics win on an existing code path.

**5. `find` with several names, and a CSV/JSON report.** `find_feature` (line 150) takes exactly
one name and returns only the first exact-or-prefix hit — no list of near matches, no
disambiguation when you type "Copernicus" and get an A/B/C. Making it accept multiple names, print
near-misses on failure, and support `--json`/`--csv` makes it scriptable for building observation
logs.

### Tier 2 — Usable, clearly wanted, moderate effort

**6. Surface the ephemeris in the viewer and `info`.** `phase_angle` is computed by
`atlas_ephem.ephemeris()` and then **used by nothing outside tests** — the same "finished but
unwired" status as `north_up_matrix`. Illumination percentage, phase name (waxing crescent etc.),
and the exact sub-solar point cost almost nothing and are exactly the metadata an astrophotographer
records. The `info` command and the info block are the natural homes.

**7. Close-ups without a capture time.** This is item #1 on the repo's own `REMAINING_WORK.md`
"Next" list. `atlas_geo.estimate_sun()` (line 491) already estimates the Sun from the image for
full disks — the same technique could serve close-ups, or the CLI could gain `--time` as an explicit
override so a renamed file doesn't need to be renamed back. Unlocks a whole class of
currently-unusable files.

**8. Coarse-to-fine angle search for the close-up blind search.** `REMAINING_WORK.md` item 3:
currently 80–100 s with unknown optics because `blind_search` turns in flat 4° steps. A 1°
refinement inside the top candidates would cut this dramatically, and search speed is the main
friction in the close-up path.

**9. A "next image" / filmstrip navigator in the viewer.** The viewer session is one image at a
time with no in-viewer way to reach the next photo. Given the launcher's `recent()` list already
exists, letting the viewer page through the folder (←/→) closes the loop between "annotate" and
"annotate the next one."

**10. Fix the 4 open questions in `design/README.md`.** Concretely: names outside the photo edge are
currently drawn on the navy background (one-line clip change), and the viewer/export label-density
mismatch is a known inconsistency the author flagged. Both are small and both are visible in every
single export.

---

### Tier 3 — Nice to have

**11. Terrain-corrected labels on the far side / behind the limb.** `--night show` exists;
libration-aware and horizon-aware visibility (which features are actually *observable* from your
site at that date, given the 1° parallax) would be a genuinely novel feature — "what can I see
tonight from Belgium" as a first-class output.

**12. KML/GeoJSON export of located features + the sidecar.** Cheap (the sidecar is already
structured JSON with lat/lon), and it plugs the results into Google Earth and QGIS. `link_id()` in
`atlas_view.py` shows the IAU feature IDs are already parsed for links.

**13. Measurement history / a measurement list.** Currently a measurement exists only as an
anonymous shape with a label. Listing them with their km values, and letting one be clicked to fly
to it, is a real usability gain for anyone measuring craters.

**14. Memory: crop `Relief(64)` to the near side.** `REMAINING_WORK.md` item 4 — ~2 GB for the
global 64 px/deg LOLA slopes. Not user-facing, but it removes a hard ceiling on close-up image
sizes.

### Tier 4 — Mostly cosmetic

**15. Grid cells prefilled with data** (albedo/elevation backdrop behind the graticule). The open
design question #1. Genuinely pretty, and arguably useful as a reference-underlay, but strictly
additive.

**16. Arrowhead/dashed-line polish and a few iconography refinements.** The listed bugs are already
fixed; this tier is now just visual tightening (spinner states, empty-search messaging, the app icon
in more places).

**17. A lunar-phase thumbnail strip in the launcher's "Earlier photos" row.** Cute, no workflow
value.

---

## Recommendation

Items **1 → 2 → 3** in that order. Fix the suite, expose `north_up_matrix` as `--north-up` (nearly
free, high impact), then build batch mode (the largest real workflow gap). That trio is a fraction
of the work of item 7 and delivers more than everything in Tiers 2–4 combined.

## Two caveats before any implementation

- `lunaratlas/data` is currently **symlinked** to `/Volumes/Astro/scripts/moon_atlas/data/...`, so
  data-touching work is entangled with another checkout.
- The 6 failing tests mean the suite should be made green **before** starting new work, not after.

