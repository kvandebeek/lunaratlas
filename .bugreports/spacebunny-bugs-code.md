# Code inspection – bugs found (Space Bunny)

Static code inspection of LunarAtlas (working tree as of 2026-10-01, `main` @ 8f80392 plus uncommitted changes).

Bugs are logged **in the order they were found**, as they were found. Severity:

- **High** — wrong output or crash in normal use.
- **Medium** — wrong in plausible edge cases, or a silent data-loss / correctness risk.
- **Low** — minor, cosmetic or robustness issue.

| ID | Severity | File | Title |
|---|---|---|---|
| BUG-01 | Medium | `lunaratlas/atlas_view.py:270,287` | Viewer crashes with `TypeError` when a close-up sidecar has no usable capture time |
| BUG-02 | Medium | `lunaratlas/atlas_render.py:299` | `layout()` raises `IndexError` when `light` is shorter than the feature list |
| BUG-03 | Low | `lunaratlas/atlas_quality.py:153-157` | Blurred images make `np.nanmedian` warn `All-NaN slice` on every quality-gate run |
| BUG-04 | High | `lunaratlas/atlas_geo.py:787-788` | `moon.tif` and `moon.jpg` share one sidecar, clobbering each other's geometry and edits |
| BUG-05 | Low | `lunaratlas/tests/ui/journeys.mjs:790-797` | UI test polls the progress bar every 250 ms and flakes whenever locate is fast |
| BUG-06 | Medium | `lunaratlas/atlas_view.py:53-58,92-103` | `cache_size()` returns 0 for files, so every thumbnail is uncounted and the 2 GB cap never applies to them |


## BUG-01 · Medium · Viewer crashes with `TypeError` when a close-up sidecar has no usable capture time

**Where:** [lunaratlas/atlas_view.py:265-275](lunaratlas/atlas_view.py#L265-L275) and [atlas_view.py:287](lunaratlas/atlas_view.py#L287)

`night_side()` treats "no capture time" as a supported case, but never handles the `None` it receives:

```python
if closeup:
    from lunaratlas import sun_elevation_light
    light = sun_elevation_light(image, feats)      # L267  -> None when there is no capture time
else:
    light = light_levels(load_raw(), geo, feats, xy)
light = np.asarray(light, float)                  # L270  -> np.asarray(None) is a 0-d array, not a list
try:
    with open(p) as fh: ...
...
visible = [(f, a, b, c, li) for f, a, b, c, li in zip(feats, x, y, z, light)]   # L287
```

`np.asarray(None, float)` produces a **0-dimensional** array (`array(nan)`), not a sequence. `zip()` over it raises:

```
TypeError: iteration over a 0-d array
```

Verified end to end: `sun_elevation_light` returns `None` for a close-up sidecar that has no `capture_utc`, a junk `capture_utc`, or no sidecar at all (`_sidecar_time` swallows `ValueError`/`KeyError` and returns `None` — [atlas_ephem.py:245-252](lunaratlas/atlas_ephem.py#L245-L252)). The viewer is then opened on that image and `GET /data.json` returns a traceback / 500 instead of the page.

The `Session` is built in a thread whose exceptions are caught, so the launcher reports `failed: TypeError: iteration over a 0-d array` and the user can never open the image ([atlas_app.py:265-266](lunaratlas/atlas_app.py#L265-L266)); via `lunaratlas.py view` it is an unhandled traceback.

**Fix:** make "unknown" an explicit state and treat it as fully lit, which is what a non-close-up with no measurable sky does anyway:

```python
light = sun_elevation_light(image, feats)
if light is None:                     # no capture time: every name stays, the light is simply unknown
    light = np.ones(len(feats))
light = np.asarray(light, float)
```

The same guard belongs in `write_json_atomic` below it — the cached `light.json` records the key, so a later run with a repaired sidecar recomputes correctly anyway.

## BUG-02 · Medium · `layout()` raises `IndexError` when `light` is shorter than the feature list

**Where:** [lunaratlas/atlas_render.py:299](lunaratlas/atlas_render.py#L299), reached from [lunaratlas.py:453](lunaratlas/lunaratlas.py#L453) and [atlas_view.py:267-269](lunaratlas/atlas_view.py#L267-L269)

`layout()` indexes the night-side array by the feature index with no length check:

```python
for i in order:                       # L286, i indexes feats
    ...
    if light is not None and night != 'show' and light[i] < 0.12:    # L299
```

The only guard is `light is not None`. A `light` sequence that is shorter than `feats` therefore raises `IndexError` as soon as it reaches a feature whose index is past the end:

```
IndexError: index 1 is out of bounds for axis 0 with size 1
```

Verified: with two crater features and `light=np.zeros(1)`, `layout()` raises on the second feature. `light=None` itself is safe (the guard short-circuits) — the defect is the missing **length** contract, not the `None` check.

How a short array arises: `light_levels()` and `sun_elevation_light()` both return one value per feature of the list they were *given*, while `layout()` is handed `feats` from a different, possibly re-filtered or re-projected list. Two concrete routes in the current code:

- `cmd_export` computes `light` from the pre-`--north-up` `feats` ([lunaratlas.py:373](lunaratlas/lunaratlas.py#L373)), then re-projects `feats` after turning the image ([L382](lunaratlas/lunaratlas.py#L382)). The counts happen to match today, so this is latent rather than active.
- The viewer caches `light.json` and reuses it when `len(c['light']) == len(feats)` ([atlas_view.py:261](lunaratlas/atlas_view.py#L261)); any change to the gazetteer between runs invalidates the cache, and the length check is the only thing standing between a stale array and this `IndexError`.

**Fix:** validate the length where the array is produced, and degrade to "unknown" rather than raising, so a stale cache or a changed feature list costs a missing night-side dimming instead of a crash:

```python
def _light_array(light, n):
    a = np.asarray(light, float)
    return a if a.ndim == 1 and a.shape[0] == n else np.ones(n)   # unknown -> every name stays
```

and use it in both `cmd_export` and `night_side`, so `layout` only ever sees a full-length array. This also closes the silent-mislabel hole: an array of the wrong length that is *longer* than `feats` today mislabels every name without any error.

## BUG-03 · Low · A blurred Moon makes `np.nanmedian` print `All-NaN slice encountered` on every run

**Where:** [lunaratlas/atlas_quality.py:153-158](lunaratlas/atlas_quality.py#L153-L158)

`limb_profile()` aligns each radial profile on its own half-level crossing, then medians the aligned set:

```python
aligned.append(np.interp(t, t - x0, q, left=np.nan, right=np.nan))   # L153
...
A = np.array(aligned)
med = np.nanmedian(A, 0)        # L157  <- RuntimeWarning: All-NaN slice encountered
good = np.isfinite(med)         # L158  (the result is masked, so the number is right)
```

`np.interp` with `left=nan, right=nan` fills only the two ends, and the shift `x0` moves them: a profile shifted by `x0` is NaN outside `[x0, 64 + x0]`. With `t = arange(-32, 32, 0.25)` (257 samples) a shift of ±30 makes **120 of 257** samples NaN. When the kept profiles share a large shift — exactly what a heavily blurred limb produces, since the half-level crossing is then poorly localised and the profile is flat — whole columns of `A` are all-NaN and `np.nanmedian` warns.

Traced to the exact call in the existing suite:

```
test_reliability.py:388  test_blurred_moon_is_refused
  lunaratlas.py:68        quality_gate -> measure(raw, limb)
  atlas_quality.py:352    limb_profile(g, cx, cy, R)
  atlas_quality.py:157    med = np.nanmedian(A, 0)
RuntimeWarning: All-NaN slice encountered
```

**Fix:** drop the all-NaN columns before the reduction, which removes the warning and the wasted work:

```python
A = np.array(aligned)
A = A[:, np.isfinite(A).any(0)]        # no column is all-NaN -> no warning
if A.shape[1] < 20:
    return None
med = np.nanmedian(A, 0)
```

Severity is Low: the measure is already masked with `isfinite` at L158, so no wrong number reaches the quality gate. It matters because (a) the warning is printed to the user's terminal for precisely the images the gate is meant to explain, and (b) any future run with `-W error` (or a stricter numpy) turns it into a hard failure.

## BUG-04 · High · `moon.tif` and `moon.jpg` share one sidecar, clobbering each other's geometry and the viewer's edits

**Where:** [lunaratlas/atlas_geo.py:787-788](lunaratlas/atlas_geo.py#L787-L788), with [atlas_geo.py:796-814](lunaratlas/atlas_geo.py#L796-L814) (`save_geo`) and [atlas_geo.py:824-848](lunaratlas/atlas_geo.py#L824-L848) (`load_geo`)

```python
def sidecar_path(image):
    return os.path.splitext(image)[0] + '.atlas.json'
```

`os.path.splitext` drops the extension, so every image with the same stem maps to **one** sidecar. `moon.tif` and `moon.jpg` — a master TIFF next to its JPEG preview, an extremely common pair in astro imaging folders — both use `moon.atlas.json`.

`save_geo` deliberately merges into whatever is already there, keeping unrelated keys:

```python
if os.path.exists(p):              # keep whatever else was stored next to the geometry
    ...
d.update(schema=..., image=os.path.basename(image), image_signature=image_signature(image), ...)
```

Verified end to end:

```
sidecar_path(moon.tif) = moon.atlas.json
sidecar_path(moon.jpg) = moon.atlas.json     SAME FILE: True

# locate moon.tif, put viewer edits in its sidecar, then locate moon.jpg:
after locating moon.jpg, the shared sidecar says:
  image      = moon.jpg        <- now describes the JPEG
  matches    = 99
  edits kept = True {'shapes': [...], 'hidden': ['Copernicus']}
```

Consequences:

- **The TIFF loses its positioning.** After the JPEG is located, `load_geo(moon.tif)` returns `problem='image changed since it was located'` (the stored signature is now the JPEG's), so every `view`/`export`/`info` of the TIFF relocates it — 10–100 s for a close-up — and overwrites the sidecar again. The two files ping-pong.
- **The viewer's edits are silently misapplied.** `edits` is preserved verbatim across the overwrite, so hidden labels, moved names and drawings made in pixel coordinates on the TIFF are re-interpreted against the JPEG. Because they are stored in *source* pixels and the two images are rarely the same size, the annotations land on the wrong features — or off the image entirely. This is the dangerous direction: the user gets a plausible-looking but **wrong** labelled export rather than an error.
- **`batch` walks straight into it.** [lunaratlas.py:483-492](lunaratlas/lunaratlas.py#L483-L492) picks up every `.tif`/`.jpg` in a folder, so any folder holding both a master and a preview corrupts both.

**Fix:** key the sidecar on the extension, and read the old name for compatibility:

```python
def sidecar_path(image):
    return image + '.atlas.json'          # moon.tif.atlas.json, moon.jpg.atlas.json

Then in `load_geo`, fall back to the legacy name only when its recorded `image` matches this file's basename **and** the signature agrees; in `save_geo`, do not carry `edits` across differing `image` values. Rejecting a sidecar whose `d['image'] != os.path.basename(image)` is a one-line safety net that stops the silent misapplication even before the rename lands.

## BUG-05 · Low · The launcher's UI test flakes: it polls the progress bar every 250 ms and can miss it entirely

**Where:** [lunaratlas/tests/ui/journeys.mjs:790-797](lunaratlas/tests/ui/journeys.mjs#L790-L797)

The `launch` journey asserts that the user sees the locate progress move:

```js
let maxDone = 0, sawBar = 0;
const t0 = Date.now();
while (Date.now() - t0 < 240000) {
  const st = await b.js(`location.pathname === '/' ? 'viewer' : [..., #stages li.done count, bar aria-valuenow ...]`).catch(() => 'navigating');
  if (st === 'viewer') break;                     // <- the loop ends the moment the viewer opens
  if (Array.isArray(st)) { maxDone = Math.max(...); sawBar = Math.max(...); }
  await sleep(250);
}
await ok(maxDone >= 2 && sawBar > 10, `the stages tick off and the bar moves (${maxDone} stages done, bar at ${sawBar} %)`);
```

The loop `break`s as soon as the page has navigated to the viewer, so `maxDone`/`sawBar` only ever record what the **250 ms polling** happened to catch. On a fast machine, a warm tile cache, or a small image, the whole locate finishes between two polls and the viewer opens first: the test then reports `0 stages done, bar at 7 %` and fails, even though the product behaved correctly.

Observed exactly once in a full-suite run (563 tests), and confirmed to be a flake rather than a regression:

```
FAIL the stages tick off and the bar moves (0 stages done, bar at 7 %)
...
**Fix:** record the progress from inside the page rather than by polling it. Have `app.js` keep a high-water mark (e.g. `st.maxDone` / `st.maxBar` on `window`), and assert on that after the viewer appears, so the measurement cannot be missed between samples. Failing that, poll from `beforeunload`-style instrumentation or, as a stopgap, only assert `maxDone > 0` when the transition to the viewer was actually observed.

## BUG-06 · Medium · `cache_size()` returns 0 for a file, so thumbnails are never counted and the 2 GB cap does not apply to them

**Where:** [lunaratlas/atlas_view.py:53-58](lunaratlas/atlas_view.py#L53-L58), used by [atlas_view.py:61-105](lunaratlas/atlas_view.py#L61-L105) (`evict_cache`) and [atlas_app.py:308-325](lunaratlas/atlas_app.py#L308-L325) (`App.thumb`)

```python
def cache_size(path):
    """Bytes below path; a disappearing cache entry is simply counted as zero."""
    try:
        return sum(os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(path) for f in files)
    except OSError:
        return 0
```

`os.walk` on a **regular file** yields nothing, so the generator is empty and the function returns 0. Tile pyramids are directories, so they are counted correctly — but the *thumbnails* enumerated in the second root of `evict_cache` are plain `.jpg` files:

```python
for root, is_tiles in ((CACHE, True), (os.path.join(CACHE_ROOT, 'thumbs'), False)):
```

so every one of them is recorded as size 0. Verified on the real cache layout (`CACHE_ROOT/tiles/...` plus `CACHE_ROOT/thumbs/*.jpg`):

```
evict_cache(limit=1GB) called cache_size on:
   tiles/cafebabe           200143
   thumbs/t1.jpg                 0     <- 1000 bytes on disk
   thumbs/t0.jpg                 0
   ...
total counted = 200143
actual bytes  = 205153
```

and directly:

```
cache_size(<a 1000-byte file>) = 0
cache_size(<the folder holding it>) = 1000
```

Consequences:

- **`CACHE_LIMIT` (2 GB) is not enforced for the thumbnail cache at all.** The total is systematically short by every thumbnail, and `total -= size` at L103 decrements by 0 when a thumbnail is evicted, so the accounting drifts further.
- **The thumbnail cache grows without bound.** [atlas_app.py:308](lunaratlas/atlas_app.py#L308) keys a thumbnail per (path, size, mtime), so every re-upload, every re-locate and every replaced photo mints a new file that nothing ever reclaims.
- **Eviction can then over-delete.** Because `total` is wrong, the loop at L93-105 can decide it is still over the limit after the tiles it should have kept are gone, and remove fresh tile pyramids the user will have to rebuild (a full mosaic pyramid is minutes of CPU).

**Fix:** measure a file directly and only walk directories:

```python
def cache_size(path):
    """Bytes at path: a file's own size, a folder's contents; a vanished entry counts as zero."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)
    except OSError:
        return 0
```

Worth pairing with a test that asserts `cache_size` on a populated `thumbs` folder is non-zero, since the failure is silent by construction.

Ran 563 tests in 627.442s
FAILED (failures=1, skipped=6)

# then, in isolation on the same working tree:
$ python3 -m unittest test_ui
Ran 24 tests in 193.689s
OK
```

The same file is listed as modified in the working tree, so this assertion is actively being worked on.

**Fix:** record the progress from inside the page rather than by polling it. Have `app.js` keep a high-water mark (e.g. `st.maxDone` / `st.maxBar` on `window`), and assert on that after the viewer appears, so the measurement cannot be missed between samples. Failing that, poll from `beforeunload`-style instrumentation or, as a stopgap, only assert `maxDone > 0` when the transition to the viewer was actually observed.

def old_sidecar_path(image):
    return os.path.splitext(image)[0] + '.atlas.json'
```

Then in `load_geo`, fall back to the legacy name only when its recorded `image` matches this file's basename **and** the signature agrees; in `save_geo`, do not carry `edits` across differing `image` values. Rejecting a sidecar whose `d['image'] != os.path.basename(image)` is a one-line safety net that stops the silent misapplication even before the rename lands.
