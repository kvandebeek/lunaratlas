# Code inspection – bugs found

Static code inspection of LunarAtlas (working tree as of 2026-10-01, `main` @ 8f80392 plus uncommitted changes).
Bugs are logged in the order they were found. Severity: **High** (wrong output / crash in normal use), **Medium** (wrong in plausible edge cases), **Low** (minor / cosmetic / robustness).

## BUG-01 · Low · `.env` parser truncates values at any `#`, even inside quotes
**Where:** [tool_settings.py:162](tool_settings.py#L162)
`line.split('#', 1)[0]` runs before quotes are stripped, so `LUNARATLAS_TELESCOPE="C#11 EdgeHD"` becomes `"C` and then `C` (the quote stripping at L165 strips the lone leading `"`). The docstring says "surrounding quotes are stripped", implying quoted values are literal. Free-text settings (`LUNARATLAS_TELESCOPE`, `LUNARATLAS_OBSERVER_NAME`, extender/camera names in the `pairs` keys) can legitimately contain `#`.
**Fix:** only treat `#` as a comment when it starts the line or is preceded by whitespace outside quotes; or parse the quoted value first.

## BUG-02 · Low · A trailing comma makes a whole `pairs` setting invalid
**Where:** [tool_settings.py:232-233](tool_settings.py#L232-L233)
`LUNARATLAS_CAMERAS=IMX678:2.0, IMX533:3.76,` → the last `part` is `''`, `rsplit(':', 1)` returns `['']`, the unpack raises `ValueError: not enough values to unpack`, and every camera is replaced by the default with a cryptic warning. The `list` kind (L225) already skips empty items; `pairs` should do the same (`if not part.strip(): continue`) and report a missing `:` with a clear message.

## BUG-03 · Medium · Two photos with the same stem share (and clobber) one sidecar
**Where:** [lunaratlas/atlas_geo.py:787-788](lunaratlas/atlas_geo.py#L787-L788)
`sidecar_path()` drops the extension: `moon.tif` and `moon.png` (or `moon.jpg`, a very common pair: master TIFF + JPEG preview in one folder) both map to `moon.atlas.json`. Consequences:
- locating one overwrites the other's geometry; the signature check then says "image changed since it was located" for the other, so every `view`/`export` of the pair relocates (minutes each) and overwrites again — ping-pong;
- `save_geo()` deliberately keeps everything else in the file ([atlas_geo.py:797-805](lunaratlas/atlas_geo.py#L797-L805)), so the viewer **edits** (hidden labels, moved names, drawings in pixel coordinates) of one image are silently applied to the other;
- `batch` over a folder containing both runs into exactly this.
**Fix:** include the extension in the sidecar name (`moon.tif.atlas.json`), keep reading the old name as a fallback when its `image` field matches the basename; or at least refuse/relocate when `d['image'] != basename(image)`.

## BUG-04 · Medium · `export --north-up` puts names that were moved in the viewer in the wrong place
**Where:** [lunaratlas/atlas_render.py:711-720](lunaratlas/atlas_render.py#L711-L720) (`transform_edits`) with [atlas_render.py:343-345](lunaratlas/atlas_render.py#L343-L345) (`layout`)
A moved name is stored as an offset `(dx, dy)` from its *automatic first spot* (`spots[0]`: under the crater rim for craters, right of the marker for landing sites — [viewer.js:285-286](lunaratlas/viewer/viewer.js#L285-L286)). `transform_edits` only rotates the offset (`M @ [dx, dy]`), but after the turn `layout` recomputes `spots[0]` in the *new* image, where it is again "under the rim". The correct new position is `M·(old_spot + d) + b`, i.e. the anchor must be rotated too. For the common 180° case (inverted telescope view) every moved crater name ends up off by about the crater's projected diameter plus the text height (it jumps to the other side of the crater); for 90° turns it is off sideways. The leader line then points from the wrong spot.
**Fix:** store/convert moved labels as an absolute position (or feature-relative vector) before turning, e.g. in `transform_edits` compute `old_spot` for the feature and replace `(dx,dy)` by `M·(old_spot+d)+b − new_spot`; simplest is to carry an absolute output position through to `layout` for moved names.

## BUG-05 · Low · A Google Fonts family whose listing has no top-level `.ttf` crashes later with an unrelated error
**Where:** [lunaratlas/atlas_render.py:98-110](lunaratlas/atlas_render.py#L98-L110), [atlas_render.py:141-144](lunaratlas/atlas_render.py#L141-L144)
When the GitHub listing is found but `_listed()` returns nothing (family folder holds only a `static/` subfolder, or the API returned a non-list JSON), `want` is empty, `files = []` stays, and `Fonts` is built with no files. The first `fonts.get()` then fails with `ValueError: min() arg is an empty sequence` (static branch) — a traceback in `export` instead of the "font not found" `SystemExit` the other paths give. `_ensure` should raise `SystemExit(f'font "{family}": no usable .ttf files on Google Fonts')` when `want` is empty and there are no `usable` files.

## BUG-06 · Low/Medium · Posterisation check misfires on 16-bit files from 10/12-bit cameras, and misses stretched 8-bit data
**Where:** [lunaratlas/atlas_quality.py:335-337](lunaratlas/atlas_quality.py#L335-L337)
For 16-bit input the measure is `1 − unique_levels / (hi − lo + 1)`, only when `hi − lo < 4096`.
- A 12-bit sensor saved as 16-bit (SharpCap/FireCapture scale ×16, so only every 16th level exists) with a dim exposure (disk spanning < 4096 levels, i.e. < ~6 % of full scale) scores ≈ 0.94 and is **refused** as "posterised" (limit 0.5), although nothing is wrong with it. Same for 10-bit (×64) data at any span below 4096.
- Conversely, 8-bit data stretched to 16-bit (×257, the case the docstring names) always spans > 4096 and gets `0.0`, so real posterisation is never detected.
**Fix:** measure the empty-level share relative to the data's actual quantisation step (e.g. `gcd` of the used levels / histogram of `np.diff(np.unique(q))`), or divide by the detected step before counting.

## BUG-07 · Medium · First run offline (or a dropped connection) ends in a raw traceback
**Where:** [lunaratlas/atlas_geo.py:220-247](lunaratlas/atlas_geo.py#L220-L247) (`download`), callers [atlas_geo.py:282](lunaratlas/atlas_geo.py#L282) (`Reference`), [atlas_names.py:70](lunaratlas/atlas_names.py#L70), [atlas_closeup.py:142-143](lunaratlas/atlas_closeup.py#L142-L143); CLI [lunaratlas.py:640-641](lunaratlas/lunaratlas.py#L640-L641)
`download()` lets `URLError`/`ConnectionResetError`/`socket.timeout` (all `OSError`) escape — the tests assert exactly that ([test_reliability.py:86-99](lunaratlas/tests/test_reliability.py#L86-L99)). Only the font path converts them to a friendly `SystemExit` ([atlas_render.py:102-107](lunaratlas/atlas_render.py#L102-L107), whose comment names this very problem). The reference map, the IAU gazetteer and the LOLA 64 px/deg model do not, and neither `geometry()` nor `main()` catch `OSError`, so `lunaratlas.py locate IMG` on a fresh install without network prints a Python traceback (and the app's progress page shows its last line). In `batch` it is caught but reported as `URLError: <urlopen error …>`.
**Fix:** wrap the network part of `download()` (`except (OSError, http.client.HTTPException) as e: raise SystemExit(f'cannot download {url}: {e}')`), keeping the temp-file cleanup.

## BUG-08 · Low/Medium · Any `SystemExit` inside the full-disk locate is treated as "no limb" and sends the image to the close-up search
**Where:** [lunaratlas/lunaratlas.py:92-111](lunaratlas/lunaratlas.py#L92-L111)
`geometry()` wraps `locate()` in `except SystemExit` and then runs `locate_closeup()`. But `locate()` also raises `SystemExit` for reasons that have nothing to do with the limb: a reference-tile download refused by checksum or `valid()` ("download … is damaged; try again", [atlas_geo.py:240-243](lunaratlas/atlas_geo.py#L240-L243)), a failed cache write (`write_atomic` → "cannot write …"), or a full disk. A full-disk photo then either gets the misleading "…; a close-up needs its capture time: in the name (SharpCap …)" message, or — if it has a time — starts a multi-minute blind close-up search that downloads the 530 MB LOLA model, before failing for the same underlying reason.
**Fix:** raise a dedicated exception (e.g. `NoLimb(SystemExit)`) from `fit_limb`/"too few terrain matches" and only fall back to the close-up search for that.

## BUG-09 · High · Viewer export ignores "Hide" for night-side names (and other "on" choices defer to `.env`)
**Where:** [lunaratlas/atlas_view.py:447-448](lunaratlas/atlas_view.py#L447-L448), also [atlas_view.py:440-446](lunaratlas/atlas_view.py#L440-L446)
`export_command` only forwards `--night` when the page says `dim` or `show`. For `hide` — **the viewer's default** ([viewer.js:75](lunaratlas/viewer/viewer.js#L75), [index.html:84](lunaratlas/viewer/index.html#L84)) — nothing is passed, so the export subprocess falls back to `LUNARATLAS_NIGHT`, whose built-in default is `dim` ([tool_settings.py:60](tool_settings.py#L60)). Result: with no `.env` at all, every export from the viewer shows the night-side names (dimmed) that the user had hidden on screen.
The same pattern affects the booleans and layers: `--no-rims/--no-grid/--no-drawings/--no-info` are sent only when *off*, and `--layers` is omitted when all five are on; the "on" state is then whatever `.env` says (`LUNARATLAS_GRID=0`, `LUNARATLAS_LAYERS=area,crater`, `LUNARATLAS_LETTERED=0`, `LUNARATLAS_LANDING=0` all override what the dialog shows). What you see in the viewer is not what gets exported.
**Fix:** always pass explicit values: `--night {hide|dim|show}`, `--rims/--no-rims`, `--grid/--no-grid`, …, `--lettered --landing`, and `--layers` even when all are selected.

## BUG-10 · Medium · An older edits save can overwrite a newer one (check-then-write race)
**Where:** [lunaratlas/atlas_view.py:737-749](lunaratlas/atlas_view.py#L737-L749), client [viewer.js:148-160](lunaratlas/viewer/viewer.js#L148-L160)
The stale-revision check takes `s.lock`, releases it, and only then `write_edits()` takes the lock again to write. Two requests can both pass the check before either writes, and the lower revision may then write last. The page normally serialises saves, but `leave()` fires a second, independent POST on every `visibilitychange → hidden` (i.e. merely switching tabs) while a debounced/in-flight save may still be running. Sequence: save rev 5 passes the check → leave rev 6 passes the check → rev 6 writes → rev 5 writes. The sidecar now holds the older edits; the page's `localStorage` snapshot is cleared because rev 6 got a 200, so the last change is lost.
**Fix:** do the revision check and the write under one lock acquisition (move the check into `write_edits` or hold `s.lock` around both; `write_edits` would then need a non-reentrant-safe variant or an `RLock`).

## BUG-11 · Medium (Windows) · Port probing never moves on, two servers can share a port
**Where:** [lunaratlas/atlas_view.py:785-792](lunaratlas/atlas_view.py#L785-L792), [atlas_view.py:532-536](lunaratlas/atlas_view.py#L532-L536)
`start_server` finds "the first free port" by trying to bind, but `ThreadingHTTPServer` inherits `allow_reuse_address = True`, and `Server.server_bind` calls `TCPServer.server_bind`, which sets `SO_REUSEADDR` (verified in CPython 3.14's source). On Windows `SO_REUSEADDR` lets a second socket bind a port that another process is already listening on, so a `lunaratlas.py view` started while the app (or another viewer) runs binds 8766 again instead of 8767. Which process then answers the browser is undefined; the cookie is per port, so the page gets 403s or the other image's data. (On macOS/Linux `SO_REUSEADDR` does not allow this, so tests there will not show it.)
**Fix:** set `allow_reuse_address = False` on Windows and use `SO_EXCLUSIVEADDRUSE` (`socket.SO_EXCLUSIVEADDRUSE`) in `server_bind`.

## BUG-12 · Medium · The launcher's "recent images" lists LunarAtlas's own exports as unsolved photos
**Where:** [lunaratlas/atlas_app.py:326-345](lunaratlas/atlas_app.py#L326-L345)
Exports from the viewer are written next to the photo in the work folder (`IMAGE_atlas[_tag].tif/.png/.jpg`, [atlas_view.py:456](lunaratlas/atlas_view.py#L456)). `App.recent()` accepts every file with an image extension, so each export shows up in the list as "Not solved · Find names" ([app.js:262-268](lunaratlas/viewer/app.js#L262-L268)). Because exports are newer than the photos, a few export rounds push the real photos out of the 30-entry list, and one click on an export runs a multi-minute locate of an already-labelled image (and writes it a sidecar of its own). `batch_images()` already excludes these with `re.search(r'_atlas(_|$)', stem)` ([lunaratlas.py:488](lunaratlas/lunaratlas.py#L488)); `recent()` should use the same filter (ideally one shared helper).

## BUG-13 · Low · An empty or blank feature name matches an arbitrary feature
**Where:** [lunaratlas/lunaratlas.py:180-191](lunaratlas/lunaratlas.py#L180-L191)
`find_matches` strips the name and then uses `startswith(n)`; for `n == ''` every feature matches, so `lunaratlas.py find IMG ""` reports the first gazetteer entry, and `export --around " "` (truthy, so it passes the `if a.around` checks) silently exports a view around that unrelated feature (the output name gets an empty tag too). The viewer guards this with `.strip()` ([atlas_view.py:432](lunaratlas/atlas_view.py#L432)); the CLI should reject a blank name with a clear message.

## BUG-14 · Low · Float images look too dark (or black) in the viewer
**Where:** [lunaratlas/atlas_view.py:171-173](lunaratlas/atlas_view.py#L171-L173)
The display stretch uses `alpha = 250 / max(white, 1)`. For a float TIFF on a 0–1 scale (which `export` explicitly supports, [lunaratlas.py:369-373](lunaratlas/lunaratlas.py#L369-L373)) with its 99.95th percentile at, say, 0.3, `max(0.3, 1) = 1` caps the gain, so the tiles show at 30 % brightness. If the float data contains NaN, `np.percentile` returns NaN, `max(nan, 1)` is NaN, and every tile is black. Use `np.nanpercentile` and `alpha = 250 / white if white > 0 else 1`, as `export` does its own scale detection.

---

## Summary

| ID | Severity | Area | One line |
|----|----------|------|----------|
| BUG-09 | High | viewer → export | "Hide" night names (the default) exports as "Dim"; other "on" choices follow `.env`, not the dialog |
| BUG-03 | Medium | sidecar | `moon.tif` and `moon.jpg` share `moon.atlas.json`: geometry ping-pong, edits leak between images |
| BUG-04 | Medium | export `--north-up` | names moved in the viewer are misplaced after the turn |
| BUG-07 | Medium | downloads | offline first run → Python traceback (reference map, gazetteer, LOLA) |
| BUG-10 | Medium | viewer server | revision check and write are not atomic: an older save can overwrite a newer one |
| BUG-11 | Medium (Windows) | viewer server | `SO_REUSEADDR` lets two servers bind one port; the port probing never moves on |
| BUG-12 | Medium | launcher | exports appear in "recent images" as unsolved photos |
| BUG-06 | Low/Medium | quality gate | posterisation false-refuses dim 16-bit captures from 10/12-bit sensors; misses stretched 8-bit |
| BUG-08 | Low/Medium | locate | any `SystemExit` (download, disk full) sends a full-disk image to the close-up search |
| BUG-01 | Low | settings | `#` inside quoted `.env` values truncates them |
| BUG-02 | Low | settings | a trailing comma invalidates a whole `pairs` setting |
| BUG-05 | Low | fonts | a Google Fonts family without top-level `.ttf` files crashes later with `ValueError` |
| BUG-13 | Low | CLI | a blank feature name matches an arbitrary feature |
| BUG-14 | Low | viewer tiles | float images shown too dark, or black with NaNs |

Not covered in depth: `experiments/`, `scripts/`, `packaging/`, the test suite itself, and the drawing/measuring interaction code in `viewer.js` beyond label layout, saving and export options.
