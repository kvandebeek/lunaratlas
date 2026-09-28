# moon_atlas and mosaic tools: remaining work

Status 2026-09-28 08:00. Run `git log --oneline` for the history.

## Done (2026-09-27/28)

**Quality gate**
- Calibrated on the user's 80 labels; `--force` overrides it.
- It refuses 6 of 9 rejects and none of the 71 accepted images.

**Locate**
- Orientation candidates are verified by terrain matching.
- Crescents get a denser patch grid.
- The lit LOLA relief is the reference (Sun from the capture time, or from the terminator).
- Close-ups without a limb are found by a blind search.
- An ephemeris is included.
- The optics are recognised from the fitted scale.

**Viewer and export**
- `view`: the viewer and editor, with edits in the sidecar, undo, a real export and fonts.
- Exports include the grid, the drawings and the info block.

**Mosaic builder**
- poly3+mesh is the default model.
- The contact sheet in the build movie has balanced rows.
- A sky pedestal above 2 % of full scale is now handled.
- `--north-up` is optional.

**lunar_finish**
- Optional wavelets first (PixInsight style); north up last, animated.

**Tests and outputs**
- `experiments/quality/baseline.py` (8 checks) and `mosaic/tests/review_regressions.py` (12 checks) all pass.
- The 25 Sep outputs were rebuilt.
- The 27 Sep set was built into `mosaic_2026-09-27/`.

## Waiting on the user

- Re-finish the 25 Sep outputs so they are north up. This rewrites `mosaic_finished*.tif` and the finishing movies in the session folder; ask first.
- Should the wavelets be on by default for unsharpened stacks? It is currently opt-in with `--wavelets pixinsight`.

## Settled 2026-09-28

- Observer site: set in `.env` (not committed; `.env.example` shows the keys).

## Next

1. **Close-ups without a capture time** (renamed files such as `marenectaris.tif`): estimate the Sun from the image, as for full disks, or ask for the date.
2. **Thin crescents without a timestamp** (AstroBin set: 28 of 78 located): try more orientation candidates, or verify at a coarser disk size.
3. **Close-up search time:** 80–100 s with unknown optics, 20–30 s once the folder's optics are known. It could be sped up with a coarse-to-fine angle search.
4. **Memory:** `Relief(64)` holds the global 64 px/deg LOLA slopes (about 2 GB); it could be cropped to the near side.
5. **Robustness still to run:** the 26 Apr session (`april/`, PSD layers) and 22/23 Jun (already-stitched images). 24 and 26 May were tested and are fine after the sky-pedestal fix.

## Known limitations (left on purpose)

- **Night-side names on full disks with an additive sky pedestal and less than 1 % sky:** the brightness test falls back to 0. Close-ups use the Sun's elevation instead.
- **Correction field:** fitted on the sunlit side; it extrapolates up to about 4 px onto the night side.
- **Mosaic builder, stage 3:** drops the worst half of the inconsistent pairs per round (accepted).

## Useful facts

- **Headless Chrome for the viewer:** use `--headless=new --dump-dom` with its own `--user-data-dir`. Run it in the background, poll for a result element, then `pkill -9 -f <profile>`. Headless Chrome does not run `requestAnimationFrame`, so the self-test calls `render()` directly.
- **LOLA data:** `data/lola/ldem_{16,64}.img`, from pds-geosciences.wustl.edu. The LROC WAC polar albedo tiles are no longer at the old archive addresses; they are not needed, because lit relief covers the poles.
- **User preferences:**
  - Roboto with a soft shadow, never outlined text; one label colour.
  - Numbers without thousands separators, always with units.
  - Show real mockups before building UI; benchmark before quoting runtimes.
  - North up, east right, never mirrored.
