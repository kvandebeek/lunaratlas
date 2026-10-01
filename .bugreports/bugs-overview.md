# LunarAtlas bugs overview

Combined from `claude-bugs-code.md`, `codex-bugs-code.md`, and `spacebunny-bugs-code.md`. The reports inspect the 2026-10-01 working tree (`main` at `8f80392` plus uncommitted changes). Duplicate findings are consolidated below; source report IDs are retained in each entry.

Severity: **High** means wrong output or a crash in normal use; **Medium** means a plausible edge-case failure or silent data-loss/correctness risk; **Low** means a minor, cosmetic, test, or robustness issue.

## High

### BUG-01 — Viewer export ignores the selected “Hide” night-side setting

**Source:** Claude BUG-09  
**Where:** `lunaratlas/atlas_view.py:440-448`, `viewer.js:75`

`export_command()` forwards `--night` only for `dim` and `show`. The viewer’s default is `hide`, so the export subprocess falls back to the `.env` or built-in default (`dim`). With no explicit environment setting, an export contains dimmed night-side names that were hidden in the viewer. The same omission affects selected “on” states for layers, rims, grid, drawings, and info: the export inherits environment defaults instead of the dialog state.

**Suggested fix:** Always pass explicit values for `--night`, layers, and every viewer boolean.

### BUG-02 — Full-disk failures are misrouted into close-up search

**Source:** Claude BUG-08  
**Where:** `lunaratlas/lunaratlas.py:92-111`

`geometry()` catches every `SystemExit` from `locate()` and treats it as a missing-limb condition. Download rejection, failed cache writes, a full disk, or too few terrain matches can therefore trigger a misleading close-up error or a long blind close-up search that downloads the LOLA model before failing again.

**Suggested fix:** Use a dedicated no-limb exception and only fall back to close-up search for that condition.

### BUG-03 — Upload fallback can overwrite a concurrent same-name upload

**Source:** Codex BUG-003  
**Where:** `lunaratlas/atlas_app.py:190-220`

When hard-link creation is unavailable, `place()` checks that the destination does not exist and then calls `os.replace()`. Two uploads can pass the vacancy check and both return the same path; the later payload destroys the earlier one. A controlled two-thread probe reproduced this, with both calls returning `same.png` and only the second payload surviving.

**Suggested fix:** Use an exclusive destination claim (`O_CREAT|O_EXCL` or equivalent), or fail rather than replacing after a separate existence check.

### BUG-04 — An older edit save can overwrite a newer save

**Source:** Claude BUG-10; Codex BUG-004  
**Where:** `lunaratlas/atlas_view.py:756-769`, `write_edits()` at `377-394`, `viewer.js:148-160`

The server checks and advances `s.rev` under the lock, releases it, and only then reacquires the lock to write the sidecar. Two requests can both pass the revision check and write out of order. The independent `leave()` POST makes this reachable when a visibility change overlaps a normal debounced save. The sidecar can end with older content while the server reports the newer revision; the browser may clear its pending copy after the newer request receives 200.

**Suggested fix:** Make revision validation, sidecar write, and revision update one locked operation, advancing the revision only after a successful write.

### BUG-05 — Shared sidecars corrupt geometry and edits for same-stem images

**Source:** Claude BUG-03; Space Bunny BUG-04  
**Where:** `lunaratlas/atlas_geo.py:787-788`, `save_geo()`, `load_geo()`

`moon.tif` and `moon.jpg` both map to `moon.atlas.json`. Locating one replaces the stored signature and geometry for the other while preserving unrelated edits. The two files then ping-pong on subsequent operations; viewer drawings, hidden labels, and moved names can be silently applied to the wrong pixel dimensions. Batch processing a folder containing a master and preview reaches the same collision.

**Suggested fix:** Include the image extension in the sidecar path, with a carefully validated legacy fallback. At minimum reject a sidecar whose recorded image does not match the requested file.

## Medium

### BUG-06 — Close-up viewer crashes when capture time is unavailable

**Source:** Space Bunny BUG-01  
**Where:** `lunaratlas/atlas_view.py:265-287`, `lunaratlas/lunaratlas.py:sun_elevation_light()`

For a close-up without a usable capture time, `sun_elevation_light()` returns `None`. `night_side()` converts it to a 0-D NumPy array and `page_data()` later iterates it with `zip()`, producing `TypeError: iteration over a 0-d array`. The launcher reports failure and the CLI viewer can traceback instead of opening the image.

**Suggested fix:** Treat unknown lighting as an explicit full-length “unknown” array, such as ones for all features.

### BUG-07 — `layout()` can index a short lighting array

**Source:** Space Bunny BUG-02  
**Where:** `lunaratlas/atlas_render.py:299`

`layout()` checks only `light is not None` before indexing `light[i]`. A stale cache or a caller that supplies a lighting array for a different feature list can raise `IndexError`; a longer mismatched array can silently associate lighting values with the wrong features.

**Suggested fix:** Validate that lighting is one-dimensional and exactly matches the feature count, otherwise treat lighting as unknown.

### BUG-08 — Offline first run can end in a raw traceback

**Source:** Claude BUG-07  
**Where:** `lunaratlas/atlas_geo.py:220-247`, callers in `atlas_geo.py`, `atlas_names.py`, `atlas_closeup.py`, and `lunaratlas.py`

`download()` lets `URLError`, connection resets, and socket timeouts escape. Reference maps, the IAU gazetteer, and LOLA data do not consistently convert these into a user-facing failure, so a fresh offline install can print a traceback. Batch mode reports a raw exception instead of a clear download failure.

**Suggested fix:** Convert network failures to a clear `SystemExit` while retaining temporary-file cleanup.

### BUG-09 — Posterisation quality check misclassifies common bit depths

**Source:** Claude BUG-06  
**Where:** `lunaratlas/atlas_quality.py:335-337`

The 16-bit check counts every unused numeric level. A dim 10/12-bit capture stored in 16-bit can be refused as posterised because its quantisation gaps are expected. Conversely, 8-bit data stretched to 16-bit spans more than the shortcut range and can evade the check.

**Suggested fix:** Detect the actual quantisation step before measuring empty levels.

### BUG-10 — `export --north-up` misplaces viewer-moved labels

**Source:** Claude BUG-04  
**Where:** `lunaratlas/atlas_render.py:343-345, 711-720`

Moved labels are stored as offsets from an automatically selected anchor. `transform_edits()` rotates only the offset while `layout()` recomputes a new automatic anchor after the image turn. A 180° or 90° turn therefore moves the label to the wrong side of its feature and can leave a misleading leader line.

**Suggested fix:** Transform the absolute old anchor plus offset, then express it relative to the new anchor, or store absolute label positions.

### BUG-11 — Batch `--skip-existing` ignores sidecar edits and export options

**Source:** Codex BUG-002  
**Where:** `lunaratlas/lunaratlas.py:409-455, 509-515`

The skip check compares the existing export only with the source image mtime. Viewer edits, hidden labels, font changes, or output-option changes made after the last export do not invalidate it, so batch mode can report `skipped` while leaving stale output.

**Suggested fix:** Include sidecar mtime and an output-options fingerprint, or store an export manifest with input signatures and options.

### BUG-12 — Windows port probing can bind two servers to one port

**Source:** Claude BUG-11  
**Where:** `lunaratlas/atlas_view.py:785-792, 532-536`

`SO_REUSEADDR` inherited by the HTTP server can allow a second Windows socket to bind a port already in use. The launcher may therefore fail to advance to the next port, leaving two processes competing for the same port and causing cookie or image-session failures.

**Suggested fix:** Disable address reuse on Windows and use `SO_EXCLUSIVEADDRUSE` when probing/binding.

### BUG-13 — Recent-images list treats LunarAtlas exports as unsolved photos

**Source:** Claude BUG-12  
**Where:** `lunaratlas/atlas_app.py:326-345`

`App.recent()` includes every image file, including `IMAGE_atlas...` exports. Exports appear as “Not solved”, can crowd real captures out of the 30-entry list, and can be selected for a pointless new locate operation.

**Suggested fix:** Share the existing `_atlas` exclusion rule from `batch_images()`.

### BUG-14 — Pending browser edits can overwrite newer edits after restart

**Source:** Codex BUG-005  
**Where:** `lunaratlas/atlas_view.py:503-505, 665-666`, `viewer.js:143-155, 1289-1301`

`Session.rev` is in memory and resets to zero. A tab’s `localStorage` snapshot can therefore look newer than the reset server revision after a restart, even if another tab already saved newer sidecar content. The old snapshot is replayed and overwrites the newer edits.

**Suggested fix:** Persist a monotonic edit revision with the sidecar and compare pending snapshots against it before replaying.

### BUG-15 — `cache_size()` does not count thumbnail files

**Source:** Claude BUG-06; Codex BUG-001; Space Bunny BUG-06  
**Where:** `lunaratlas/atlas_view.py:53-58, 61-105`, `lunaratlas/atlas_app.py:319-327`

`cache_size()` walks directory contents. When `evict_cache()` passes an individual thumbnail JPEG, `os.walk()` yields nothing and the file contributes zero bytes. A direct probe with a 1,024-byte file returned zero. The thumbnail cache can grow without the 2 GiB limit being enforced.

**Suggested fix:** Count a regular file directly and walk only directories.

### BUG-16 — Blurred quality checks emit `All-NaN slice` warnings

**Source:** Space Bunny BUG-03  
**Where:** `lunaratlas/atlas_quality.py:153-158`

Aligned limb profiles use NaN padding and call `np.nanmedian()` on columns that can be entirely NaN for a blurred image. The result is later masked, but the warning pollutes output and can become a hard failure under warning-as-error settings.

**Suggested fix:** Drop all-NaN columns before taking the median.

### BUG-17 — Blank feature names match arbitrary features

**Source:** Claude BUG-13  
**Where:** `lunaratlas/lunaratlas.py:180-191`

`find_matches()` strips input and then uses `startswith('')`, so an empty name matches the first feature. `find IMAGE ""` reports an unrelated result, and `export --around " "` can export around an arbitrary feature.

**Suggested fix:** Reject blank names before matching or constructing an `--around` export.

### BUG-18 — Float images can be too dark or black in viewer tiles

**Source:** Claude BUG-14  
**Where:** `lunaratlas/atlas_view.py:171-173`

The display stretch caps gain with `max(white, 1)`, so a valid 0–1 float image with a 99.95th percentile below 1 is shown too dark. If the percentile is NaN, the gain becomes NaN and tiles can be black.

**Suggested fix:** Use `np.nanpercentile()` and apply `250 / white` whenever `white > 0`, with a finite fallback.

### BUG-19 — Google Fonts family without usable top-level TTF files crashes later

**Source:** Claude BUG-05  
**Where:** `lunaratlas/atlas_render.py:98-110, 141-144`

If a Google Fonts listing contains no usable top-level `.ttf` files, `Fonts` is created empty and the first `fonts.get()` raises `ValueError: min() arg is an empty sequence` instead of the expected “font not found” error.

**Suggested fix:** Raise a clear `SystemExit` when no usable font files are found.

## Low

### BUG-20 — Quoted `.env` values are truncated at `#`

**Source:** Claude BUG-01  
**Where:** `tool_settings.py:162-165`

The parser strips comments with `line.split('#', 1)` before removing quotes, so a quoted value such as `"C#11 EdgeHD"` becomes `C`. Hash characters inside quoted values should remain literal.

### BUG-21 — Trailing comma invalidates an entire `pairs` setting

**Source:** Claude BUG-02  
**Where:** `tool_settings.py:232-233`

`LUNARATLAS_CAMERAS=IMX678:2.0, IMX533:3.76,` leaves an empty part. The `pairs` parser attempts to split it and falls back to defaults with a cryptic warning, unlike the existing list parser which skips empty entries.

### BUG-22 — UI progress test flakes when locate completes between polls

**Source:** Space Bunny BUG-05  
**Where:** `lunaratlas/tests/ui/journeys.mjs:790-797`

The test polls every 250 ms and stops as soon as navigation reaches the viewer. A fast locate can complete between samples, leaving the recorded progress at zero even though the product succeeded.

**Suggested fix:** Record a high-water progress mark in the page and assert it after navigation, or instrument the transition instead of relying on polling.

## Findings preserved from all three reports

The combined overview includes 22 unique findings. The following overlap groups were consolidated: Claude BUG-03 with Space Bunny BUG-04 (shared sidecars), Claude BUG-06/Codex BUG-001 with Space Bunny BUG-06 (thumbnail cache accounting), and Claude BUG-10 with Codex BUG-004 (edit-save race). The original reports remain unchanged for traceability.
