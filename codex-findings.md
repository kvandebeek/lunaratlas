# LunarAtlas performance and functional findings

Reviewed 2026-09-29 against the current on-disk worktree. Scope: launcher, viewer, CLI export, configuration, caches, and automated user journeys. Existing source changes were left untouched. Security findings are in `codex-security-findings.md`.

## Functional findings

### F-01 · A different photo with the same name and byte count reopens the old photo — High · confirmed

**Expected:** Dropping a new capture preserves its pixels and starts a fresh locate. **Actual:** `/app/upload` compares only filename and size; when both match an existing work-folder file, it drains and discards the new bytes and returns the old path and sidecar (`lunaratlas/atlas_app.py:145-158`). The repository already has an expected-failure regression test for two equal-length, different TIFFs (`lunaratlas/tests/test_app.py:203-212`). This is plausible for repeated uncompressed captures from one camera.

**Fix:** Compare content hashes before reuse. If contents differ, give the new copy a unique name even when its size matches. Preserve the old image and sidecar.

### F-02 · Quick navigation can lose the last viewer edit — Medium · source-confirmed, browser timing untested

**Expected:** A changed label or drawing survives immediately when the user selects “Other image,” closes the tab, or reloads. **Actual:** `save()` waits 300 ms before POSTing the current edits (`lunaratlas/viewer/viewer.js:85-103`), while the “Other image” link navigates directly to `/app` (`lunaratlas/viewer/index.html:41`). There is no `pagehide`/`visibilitychange` flush or navigation guard. Leaving before the timer fires discards that change.

**Fix:** Send a final revision on page exit (for example, `navigator.sendBeacon` or `fetch(..., {keepalive:true})` within payload limits), and use a revision/acknowledgement scheme so earlier requests cannot overwrite later edits. Add a browser journey that changes a label and navigates away immediately.

### F-03 · Export proceeds after its required edit save fails — Medium · source-confirmed

**Expected:** If current drawings cannot be saved, Export stops and explains that the image would be stale. **Actual:** `post()` catches a failed `/edits` request and resolves its promise after changing only the small save-state text (`lunaratlas/viewer/viewer.js:92-95`). The Export click handler `await`s `flush()` and then starts `/export` unconditionally (`lunaratlas/viewer/viewer.js:1047-1052`). The export process reads the sidecar, so it can silently omit the visible unsaved drawings.

**Fix:** Let `post()` reject on failure; make Export display the error and stop. A retry should save successfully before starting the subprocess.

### F-04 · A partial tile cache remains broken on reopen — Medium · confirmed

**Expected:** If one cached tile is missing, the viewer rebuilds it or its pyramid. **Actual:** `build_tiles()` accepts the cache from `meta.json` whenever the image signature and tile size match, without checking that the listed tiles still exist (`lunaratlas/atlas_view.py:55-69`). In an isolated probe, deleting `0/0_0.jpg` and calling `build_tiles()` again returned the cached levels while the tile stayed absent. The viewer requests that URL and receives 404, leaving a blank patch.

**Fix:** Validate every listed level/tile at least once on cache reuse, or recover a missing tile on request. Write the manifest only after all tile writes succeed, and verify `cv2.imwrite` results.

### F-05 · A UTF-8 BOM causes the first `.env` setting to be ignored — Low · confirmed by expected-failure test

**Expected:** A Windows-created UTF-8-with-BOM `.env` applies every setting. **Actual:** The first key includes the BOM and is treated as unknown; subsequent keys work. `lunaratlas/tests/test_functional_cli.py:484-490` reproduces this as an expected failure. The user may think a telescope, observer, or export setting took effect when it did not.

**Fix:** Read `.env` with `encoding='utf-8-sig'` and turn the regression into a normal passing test.

## Performance findings and quick wins

### P-01 · Reopening an image still decodes the full source even with valid cached tiles — Medium · code-backed opportunity

`App.open()` always calls `cv2.imread(..., IMREAD_UNCHANGED)` before constructing a session (`lunaratlas/atlas_app.py:204-220`). `Session` then checks whether the tile pyramid can be reused (`lunaratlas/atlas_view.py:55-65`, `lunaratlas/atlas_view.py:338-349`). This makes repeat opens pay for a full 16-bit image decode and allocation even when the viewer already has all tiles. It matters most for the advertised 200 MP mosaics. The current timing suite measures `build_tiles` cache reuse, but not the complete repeat-open path (`lunaratlas/tests/test_performance.py:212-225`).

**Quick win:** Persist the page data/light summary with the tile manifest and image signature, then construct a repeat session without loading full-resolution pixels. Revalidate the manifest as in F-04. Measure repeat-open wall time and peak resident memory before and after.

### P-02 · Every export-option change schedules two full preview renders — Low · code-backed opportunity

`schedulePreview()` invokes `renderPreview()` at 30 ms and again at 600 ms, regardless of whether new tiles arrived (`lunaratlas/viewer/viewer.js:1101-1125`). Each call resets the canvas and runs tile, grid, label, and drawing passes. A checkbox/radio change therefore does this work twice. Browser tile `onload` already requests a redraw (`lunaratlas/viewer/viewer.js:121-129`).

**Quick win:** Render once after the option change, and render again only when a required tile finishes loading. A browser performance profile should measure the saving on a feature-dense image; no CPU-time claim is made here.

### Measured baseline and limits

- The latest isolated performance suite ran 35 tests in 24.20 s on this Mac. Export, layout, quality, memory, reference, tile-cache, and font checks passed. One viewer-latency test errors because its `/data.json` response is still parsed as the retired JavaScript assignment (T-01). The suite's budgets are generous regression limits, not user-experienced timings.
- The latest isolated functional suite ran 197 tests in 10.53 s: green with one expected failure (F-05). It does not include `test_app.py`, which contains the separate expected-failure regression for F-01.
- A scratch work folder containing 30, 300, then 1,000 tiny JPEGs took about 0.003, 0.015, and 0.038 seconds for `App.recent()` while still returning at most 30 rows. This path was not a meaningful quick win in that probe; larger EXIF-bearing files and slow storage were not measured.
- Concurrent development/test processes were present during this review, so absolute timing numbers should be treated as indicative. The structural costs in P-01 and P-02 do not depend on those timings.

## Test-suite findings

### T-01 · One viewer latency test parses JSON as the retired JavaScript route — confirmed

The current server serves `/data.json`. `lunaratlas/tests/test_performance.py:338-340` now requests that route, but still strips a `window.ATLAS = ` prefix before `json.loads()`. Its response is already plain JSON, so the latest performance run had one error and did not time the individual tile requests. Parse the body directly, then rerun this test.

### T-02 · The full suite was not stable during concurrent edits — test-status limitation

A full run took 604.30 s: 476 tests, 10 failures, 7 errors, 4 skipped, 2 expected failures. While it ran, another process modified both source and tests. The final output includes failures against old assertions for `/data.js`, `--around`, HTTP method status, and temporary-file naming that no longer match the on-disk tests. Thus this is not a reliable aggregate verdict on the final worktree. The focused reruns above establish the current functional/performance status; a clean full-suite rerun is needed once edits stop.

### Resolved during this review · direct export write could destroy an earlier output

My first isolated failure-injection probe showed that an encoder returning failure after writing partial bytes replaced an existing output. A concurrent source change then switched `cmd_export` to `write_atomic()` (`lunaratlas/lunaratlas.py:459-465`). This issue is **not claimed as an open finding** on the latest worktree; the probe has not been repeated against the new implementation.

The same concurrent work updated the three stale `--around` assertions and switched `https_open()` back to guarded `urllib.request.urlopen()`. Those initial test failures are likewise not counted as open findings; the focused functional rerun is green.

## Coverage not established in this round

The 200 MP real-image workflow, first-use network downloads, and Windows/Linux desktop packaging were not timed on this Mac. Browser timing for F-02 and failed-save export behavior for F-03 were code-reviewed but not reproduced in an instrumented browser. A clean full-suite rerun remains necessary after concurrent edits end.
