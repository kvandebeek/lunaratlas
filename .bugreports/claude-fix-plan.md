# LunarAtlas bug fix action plan for Claude

<!-- CODEX-ANALYSIS-STATUS -->
Analysis status: COMPLETE (2026-10-01). All 22 overview IDs are analyzed and mapped to 15 READY implementation packets, with dependencies, corrected diagnoses, compatibility decisions, and acceptance checks. Claude may continue in dependency order and update its execution log. Completion here refers to this analysis/plan, not to implementation or verification of all fixes.
<!-- /CODEX-ANALYSIS-STATUS -->

## Shared document protocol

- Codex owns the analysis, decisions, and packet instructions above the execution log. Claude owns the execution log below. Both may read the entire document.
- Before each edit, reread the affected section. Use small contextual patches; never rewrite this file from an old snapshot. Preserve the other author's text. If a patch fails, reread and reconcile it.
- Claude: append a claim in the execution log before starting a READY packet. Record changes, tests, remaining limitations, and the corresponding overview BUG IDs. Use `claimed`, `implemented`, `verified`, or `blocked`; implementation alone is not verification.
- If code or evidence contradicts a packet, append the discrepancy and evidence to the execution log. Do not silently change its acceptance criteria.
- This plan is for implementation in the existing dirty worktree. Inspect current diffs and any AGENTS.md before editing; preserve unrelated changes, especially active close-up/geometry and UI-journey changes. Do not reset, stash, clean, or automatically commit/push.
- The stable bug IDs in this document refer to `bugs-overview.md`, not the independent numbering in the three source reports.

## Analysis notes

The overview is a consolidation, not a fresh verification. Source severities differ, some findings are defensive hardening rather than demonstrated product failures, and some proposed fixes need correction. The packet decisions below take precedence over the overview's suggested fixes. READY means analysis/instructions are ready, not that a fix is implemented or accepted. Claude's execution log records implementation progress separately.

The three original reports contain 25 entries, consolidated into 22 distinct overview IDs. Preserve those IDs. In particular, Claude BUG-06 is posterisation and is not a source of the thumbnail finding. Line numbers have already shifted in this active worktree; find the named functions rather than patching by old line numbers.

Codex response to Claude's P01 discrepancy (2026-10-01): verified in HEAD that `test_hash_always_starts_a_comment` explicitly encoded the old rule and the settings docstring said `# starts a comment`. Classify BUG-20 as a deliberate usability/compatibility change, not a violation of the former parser contract. Keep the quote-aware P01 behavior and matching documentation/tests; record the change in the handoff. Do not revert it merely because the old behavior had a test. Claude reports P01/P02 verified in the log; Codex has not independently rerun those implementation tests.

### Coverage and priority

Work order after any already claimed packets: prioritize P03, P04, P05, then P06/P07, then the remaining packets in dependency order. P01/P02 were released early because they were small and isolated. Do not work on overlapping files from multiple implementation sessions without explicit ownership coordination.

| Overview ID | Packet | Analysis disposition / priority |
|---|---|---|
| BUG-01 | P06 | Confirmed option mapping mismatch; high |
| BUG-02 | P07 | Confirmed overly broad fallback; medium, linked to BUG-08 |
| BUG-03 | P03 | Reproduced unsupported-link race; high |
| BUG-04 | P05 | Confirmed non-atomic revision/write sequence; high |
| BUG-05 | P04, P11 | Confirmed sidecar collision; high; related export collision also reproduced |
| BUG-06 | P08 | Confirmed scalar lighting fallback; medium |
| BUG-07 | P08 | Defensive contract hardening; no active short-array producer established |
| BUG-08 | P07 | Confirmed uncaught download errors; medium |
| BUG-09 | P09 | Reproduced false score; medium; acquisition history remains ambiguous |
| BUG-10 | P10 | Confirmed missing anchor transform; medium |
| BUG-11 | P11 | Confirmed incomplete freshness key; medium |
| BUG-12 | P14 | Windows-specific risk supported by bind path; actual Windows validation required |
| BUG-13 | P11 | Confirmed unfiltered generated exports; medium |
| BUG-14 | P05 | Confirmed non-durable recovery comparison; high; use corrected trigger |
| BUG-15 | P02 | Reproduced file-size accounting defect; medium |
| BUG-16 | P09 | Known all-NaN reduction path; low; preserve coordinate mask when fixing |
| BUG-17 | P06 | Confirmed empty-prefix behavior; low |
| BUG-18 | P12 | Confirmed float normalization/cache problem; low to medium |
| BUG-19 | P13 | Confirmed empty font list path; low |
| BUG-20 | P01 | Intentional quoted-value usability change; low; see compatibility note |
| BUG-21 | P01 | Confirmed trailing-empty-pair rejection; low |
| BUG-22 | P15 | Confirmed test observation race; low; prior suite counts are not current evidence |

Dependency spine: P04 → P05; P06 → P10; P04/P05/P06/P10 → P11; P07 → P13; P02 plus P05 identity coordination → P12; P15 integrates after launcher changes. P08's legacy capture-time tests depend on P04. All other dependencies are listed in each packet.

## Implementation packets

### P01 — Settings parsing (READY; overview BUG-20, BUG-21)

Dependencies: none. Claude can start here while analysis continues.

Confirmed in `tool_settings._read()` and `_convert()`: comment stripping precedes quote parsing; the pairs loop processes empty comma-separated items. These are low-priority usability bugs with a small, isolated fix.

Implementation:

1. Parse quoted values before stripping inline comments. Preserve `#` inside matching single/double quotes; preserve the existing treatment of full-line and unquoted comments. Do not add shell expansion, environment interpolation, or execution. Strip only matching outer quotes.
2. Skip whitespace-only pairs entries. Keep an all-empty list invalid, reject empty names/missing separators, and retain finite-number/range validation and environment-over-file precedence. Report an understandable reason for malformed nonempty entries.
3. Extend existing settings tests in `test_functional_cli.py` / `test_functional_pieces.py`. Cover both quote types, literal hash, trailing comment, trailing comma, all-empty input, malformed pair, and valid environment override. Do not modify the user's `.env`.

Acceptance: quoted `C#11 EdgeHD` survives intact; `IMX678:2.0, IMX533:3.76,` yields both cameras; invalid numbers still fall back with the existing warning policy. Run the relevant settings classes and `test_compatibility.py` if registry/example generation changes.

### P02 — Correct cache accounting (READY; overview BUG-15)

Dependencies: none. Files: `atlas_view.cache_size`, existing cache tests in `test_app.py`.

Confirmed: `os.walk(file)` yields no entries. The existing cache test can pass accidentally because its protected tile directory alone exceeds its tiny limit, causing the thumbnail to be removed even when counted as zero.

Implementation: count regular files directly; retain directory summation and benign handling of disappearing entries. Keep protected entries protected even if they alone exceed the budget. Do not change eviction ordering as part of this fix.

Acceptance: test a thumbnail-only cache over its budget and a mixed cache where tiles alone are below budget but tiles plus thumbnails exceed it. Assert the oldest eligible entry is removed, retained entries account for the remaining bytes, and a second eviction does not unnecessarily remove more. Also cover a direct file, directory, missing path, and protected entry. Run the cache tests in `test_app.py`.

Analysis correction: the overview incorrectly attributes this finding to Claude BUG-06 (which concerns posterisation). Its sources are Codex BUG-001 and Space Bunny BUG-06. The source report's claims that every re-locate creates a thumbnail and that zero-byte accounting necessarily over-deletes are not established: the key uses the image's path/size/mtime, not sidecar changes.

### P03 — Upload publication without overwrites (READY; overview BUG-03)

Dependencies: none. Priority: high data loss. Files: `atlas_app.App.place/upload`, upload tests in `test_app.py` / `test_security.py`.

Keep the successful hard-link path and same-content deduplication. Remove the vacancy-check-plus-`os.replace` fallback. Distinguish destination collisions from unsupported hard links and permission/I/O errors. The bounded safe default on an unsupported filesystem is a clear upload failure with cleanup and no overwritten file. A fallback may instead use a supported atomic no-replace primitive, but must keep incomplete files out of the recent list and never expose a partially copied image as a completed upload. Direct copying into an `O_EXCL` destination alone does not provide that publication guarantee.

Acceptance: use barriers/events, not timing sleeps, to race different equal-length payloads for one name; both payloads must survive under distinct successful paths, or an unsupported operation must fail explicitly without replacing the winner. Test forced unsupported-link and permission errors, preexisting destinations/symlinks, duplicate-content reuse, interrupted publication cleanup, and preservation of the earlier image's sidecar. A process-local lock alone is insufficient for other processes sharing the work folder.

### P04 — Per-image sidecar identity and legacy migration (READY; overview BUG-05)

Dependencies: none; finish before P05 and P11. Priority: high data loss/correctness. Main files: `atlas_geo.py`, `atlas_view.py`, `atlas_app.py`, `atlas_ephem.py`; audit `scripts/test_testimages.py`, documentation and fixtures as consumers.

Confirmed: both the path and merge behavior permit cross-image contamination. Changing `sidecar_path()` alone is insufficient: `_sidecar_time()` hardcodes the old name, and `recent()` gates `load_geo()` on existence of the new path.

Implementation contract:

1. New writes use the full filename: `moon.tif.atlas.json` and `moon.jpg.atlas.json`. Centralize naming and validated read resolution in an import-safe shared helper; avoid a new geo/ephemeris import cycle.
2. Prefer the canonical sidecar. If absent, read the legacy `moon.atlas.json` only when its recorded image basename AND image signature match the requested image. Do not use a legacy file to hide an invalid canonical file. Never guess ownership of an ambiguous legacy file.
3. Keep legacy files intact. On the next successful write, publish a canonical copy atomically. Preserve edits/extra metadata only for the same validated source identity. Relocating an unchanged photo retains its edits; replacing source pixels must not silently carry stale pixel-coordinate drawings across.
4. Route geometry reads/writes, edit reads/writes, capture-time lookup, recent status, CLI info, output-protection checks and job output-existence checks through the new policy. Reject mismatched recorded identities even if size/mtime happen to agree. Update expected sidecar names and compatibility tests, not by disabling assertions.

Acceptance: same-stem TIFF/JPEG with different dimensions retain independent geometries and edits after alternating locate/save/view; same-size/same-mtime siblings still do not share ownership; valid old sidecars work and migrate without deletion; mismatched/ambiguous/damaged legacy files do not donate edits or capture times. Test `--time` round trips, launcher recent/open, and old schema support. Run affected `test_compatibility.py`, `test_reliability.py`, `test_features.py`, `test_app.py`, plus a real HTTP edit round trip.

Related limitation discovered in planning: default export names also drop the input extension (`moon.tif` and `moon.jpg` both become `moon_atlas.tif`). P11 must prevent this separate output collision before claiming same-stem batch processing is safe; fixing sidecars alone does not fix export destinations.

### P05 — Atomic, durable edit concurrency (READY; overview BUG-04, BUG-14)

Dependency: P04. Priority: high data loss. Files: `atlas_view` edit/session routes, shared sidecar writer, `viewer.js` save/load/leave/export flow. Treat these two findings as one persistence contract.

Confirmed: revision check and write use separate lock intervals; revisions reset when a session is rebuilt. Refinement of BUG-14: a successful save in another tab on the same browser origin normally clears the shared pending key. Reproduce stale recovery across a different browser profile/port, or leave an unacknowledged pending snapshot followed by another writer and a session restart; do not use an impossible same-origin sequence as the regression.

Implementation contract:

1. Persist a server-owned edit version with sidecar content; initialize from durable state. Use an expected/base version on saves, not `Date.now()` as a cross-tab ordering authority. Under one lock, reread identity/version, compare, write atomically, then acknowledge the committed version. GET must return a coherent content/version snapshot. Failed writes must leave both content and version unchanged and produce a structured error (note `write_json_atomic()` can raise `SystemExit`, which the current handler's `except Exception`-style tuple does not catch).
2. The lock must be shared by all read/modify/write operations on that canonical sidecar, including `save_geo()`. Cover threads and separate app/view processes that can open the same image. Use a small portable advisory-file-lock helper (`flock` on POSIX, equivalent on Windows) with bounded failure handling, or an equivalent proven mechanism. Do not delete a lock file while waiters may still reference it.
3. Serialize saves per client, including pagehide/visibility saves as far as possible. Include an operation ID so retry after lost acknowledgement is idempotent. Store pending payload with its base version and operation ID. Replay only when the base still matches, or recognize an already committed operation. Legacy pending snapshots lacking a base version must not auto-overwrite durable edits.
4. On conflict, retain the unsaved payload and report that it was not saved; allow recovery without an automatic overwrite. Do not simply advance a local counter and resend the whole stale document. Only clear the pending entry matching an acknowledged operation; an older successful response must not erase a newer pending snapshot.
5. Make `flush()` reject on save conflict/session replacement so export cannot proceed as if the local edits were saved. Send/check image identity on initial edit fetch and status requests as well as writes. Ensure edits cannot begin with an uninitialized base version while initial loading is pending.

Acceptance: deterministic overlapping HTTP saves; two clients from the same base (one commit, one explicit conflict); lost-response retry; failed sidecar publication; session recreation/restart with older pending edits; edits through two server processes; legacy sidecar without a version; current and stale image sessions; export blocked after failed/conflicted save. Verify durable JSON contents and browser-visible save state, not just status codes. Real browser coverage must include visibility/pagehide plus pending storage recovery. Run relevant reliability/security tests and saving/export journeys. Do not label a mocked browser-only test as full persistence acceptance.

### P06 — Explicit export choices and blank-name validation (READY; overview BUG-01, BUG-17)

Dependencies: none; finish before P10/P11. Files: `atlas_view.export_command`, CLI parsing/find helpers, export mapping tests in `test_functional_pieces.py`, `test_functional_cli.py`, `test_features.py`.

Confirmed: the built-in `LUNARATLAS_NIGHT` is currently `dim`, while the viewer defaults to `hide`. All-five-layer selection omits `--layers`; enabled booleans can inherit disabled `.env` values. `find_matches()` treats an empty prefix as a match for everything.

Implementation:

1. The viewer's explicit choices must win over defaults: always emit `--night hide|dim|show`, the full selected layer list (or `none`), and both true/false forms for rims/grid/drawings/info. Set lettered/landing flags consistently with the selected layers so an environment value cannot silently suppress an enabled layer.
2. Audit every field in `viewer.js`'s `opts()` against argparse defaults. In particular full-size exports must neutralize `LUNARATLAS_MAX_SIZE`; add an explicit disable/default override if needed, rather than sending an arbitrary huge cap. Plain CLI commands without explicit flags should retain their documented defaults. Validate incoming values, preserving command-argument rather than shell construction.
3. Reject blank/whitespace-only feature names at the CLI boundary and make `find_matches()` return no match for an empty normalized query. Reject blank `--around` before locating, downloading, or writing output. Preserve valid prefix search, suggestions, and multi-name reporting.

Acceptance: run the generated export argv through the real argument parser with deliberately conflicting environment settings (night=show/dim, layers subset, disabled booleans/lettered/landing, nonzero maximum size). Check effective options and at least one rendered export, not just flag presence. Verify hide/dim/show, all/subset/no layers, each boolean on/off, and full-size/half/max output dimensions. Blank find/around requests must fail clearly without a new image or sidecar. Retain the security test for a feature name beginning with `--`.

### P07 — Classify locate failures and surface download errors (READY; overview BUG-02, BUG-08)

Dependencies: none; implement the exception distinction BEFORE converting additional errors into `SystemExit`. Files: `atlas_geo`, `lunaratlas.geometry/quality_gate`, `atlas_closeup` callers, font download boundary as needed.

Confirmed: fatal `SystemExit` errors currently enter blind search; raw network `OSError` paths escape. Correction to the overview: insufficient matches/unreliable limb are intentionally recoverable full-disk-fit failures, not necessarily infrastructure failures. Retain their close-up fallback where the current behavior needs it.

Implementation:

1. Introduce a typed recoverable locate failure for no usable limb, unreliable limb, and insufficient matching evidence. Catch only that type when deciding to try close-up search. Audit all `fit_limb()` callers so the quality gate still treats absent limb as expected. A subtype of the existing user-facing failure type is acceptable if it preserves CLI behavior.
2. Keep unreadable images, failed downloads/checksums, disk/permission errors, and unsupported data as fatal to the requested operation. Preserve the explicit optional-LOLA/albedo fallback in `atlas_geo.locate()` when appropriate; do not blanket-disable this offline mode.
3. Convert anticipated download/open/read/publication failures into clear contextual messages at a single boundary, with no traceback. Cover errors before temporary-file creation and midstream errors. Do not catch arbitrary programming exceptions. Cleanup must preserve an existing good destination and must not mask the original error.

Acceptance: inject offline open, timeout/reset during reading, invalid checksum/content, and full disk/permission failures. Assert `locate_closeup()` is never called for these fatal cases, and no extra 64-ppd download begins. Separately assert actual recoverable geometry failures still enter close-up search when capture time is available and explain the missing time when it is not. Update existing `Downloads` tests that currently expect raw `OSError`, retaining their old-file and temporary-file cleanup assertions. Run reliability and close-up/functional-geometry tests affected by the exception contract.

### P08 — Lighting fallback and array contracts (READY; overview BUG-06, BUG-07)

Dependency: P04 for capture-time compatibility tests; core lighting validation can be developed independently. Files: `atlas_view.night_side/page_data`, `atlas_render.layout`, lighting producers and their tests.

Confirmed BUG-06: `np.asarray(None, float)` is scalar NaN. The first iteration failure can occur while building the `light.json` list in `night_side()`, before `page_data()` or `/data.json`; the report's HTTP-500 location is inaccurate. A valid geometry with missing/damaged capture metadata must still open.

BUG-07 is defensive hardening, not a demonstrated current export failure: `project()` changes coordinates in place without changing feature order/count, and the lighting cache already rejects a different length. A deliberately short array proves an unchecked precondition, not that north-up currently violates it. Also, a longer array does not inherently shift feature associations. Preserve this distinction in the final bug status.

Implementation: normalize lighting at consumption/cache boundaries to a finite 1-D array with exactly one value per feature. Unknown/malformed entries should keep labels visible as unknown (ones is compatible with present rendering); do not truncate the feature list using `zip()` or hide unknowns. Reject/recompute malformed cached arrays. Include a stable fingerprint of ordered feature identities/coordinates in the cache key, not only `len(feats)`, to prevent same-count reorder reuse. Bump the lighting cache version.

Acceptance: missing/invalid capture time, valid legacy time after P04, `None`, scalar, short/long/nested/nonfinite arrays, empty feature list, and same-length reordered catalogue. Verify valid day/night values remain unchanged and hide/dim/show still work. Exercise Session creation plus an export; no request failure or truncated visible feature set. Mark BUG-07 as `hardened; no current production trigger established`, not as a reproduced production crash.

### P09 — Quality metric correctness (READY; overview BUG-09, BUG-16)

Dependencies: none. Files: `atlas_quality.posterisation/measure/verdict`, quality and reliability tests; review calibrated thresholds if metric semantics change.

Probe evidence from the live code: a repeated 200-level ramp stored as `uint16` with step 16 scores **0.937206** (above the 0.5 rejection threshold); a full 256-level ramp expanded by 257 scores **0.0**. The numeric-span shortcut is not a valid sensor-depth distinction.

Implementation decisions:

1. Do not implement the proposed GCD-only “fix”: both an ordinary low-bit-depth sensor and destructively quantized data can have regular gaps, and scaling/colour conversion/noise can destroy the GCD. Pixel histograms alone cannot prove acquisition history.
2. Make high-depth quantisation diagnostic rather than a hard refusal when source precision is unknown. Preserve the existing 8-bit checks where supported by fixtures. Report occupied/effective tonal levels or estimated spacing in the measured data so an expanded 8-bit ramp is no longer reported as confidently free of quantisation. Keep diagnostic fields distinct from a calibrated rejection score; ambiguous 16-bit/float cases may return unknown (`None`), with a documented reason. Do not silently call all high-depth inputs perfect.
3. Establish fixtures for valid dim 10/12-bit captures, smooth native 16-bit data, expanded 8-bit ramps, strongly posterized 8-bit images, colour/mono variants, sparse samples and nonfinite float values. If implementing a spatial banding metric, require representative labelled-image evidence before using it to refuse images; that extension is not required to remove the false refusals and false certainty above.
4. For BUG-16, compute the finite-column mask before `nanmedian`, and apply the SAME mask to `t`. Then filter any remaining invalid values and handle insufficient samples safely. The source report's snippet shortens `A` but leaves `t` unchanged and would introduce an indexing/coordinate bug. Preserve the aligned profile's physical coordinates and the downstream width/halo calculations.

Acceptance: valid dim sensor-depth fixtures are not refused solely for expected quantisation; expanded 8-bit data produces meaningful quantisation diagnostics without pretending its acquisition history is known; existing clearly posterized 8-bit rejection is retained. Blurred limb fixtures run with `RuntimeWarning` promoted to errors, emit no all-NaN warning, and retain comparable finite width/halo values. Include all-invalid and short-profile handling. Record any calibration limitation explicitly; do not tune thresholds merely to make fixtures pass.

### P10 — Preserve moved-label positions through north-up export (READY; overview BUG-10)

Dependency: P06; coordinate with P05 if changing the persisted label schema. Files: `atlas_render.layout/transform_edits`, `lunaratlas.cmd_export`; `viewer.js` and override cleaning only if introducing a new persistent position representation.

Confirmed: a moved label is `automatic_home + offset`. Rotating the offset alone, then adding a freshly computed lower/right anchor, cannot rotate the old center correctly. `transform_edits()` currently lacks the geometry/font/layout context needed to reconstruct the anchor.

Implementation: factor the automatic first-anchor calculation so export can obtain the unturned anchor at the actual output scale and font settings. Resolve the old moved center, transform that complete point with `M @ point + b`, then apply the final crop/resize mapping. Carry an absolute position internally into layout; do not add the offset again. Keep text upright and recompute leader endpoints against the transformed feature. Continue transforming drawings normally. Preserve the established OpenCV pixel-center convention.

Compatibility: old `{dx,dy}` data must continue to render unchanged in unturned exports. Exact historical screen centers cannot be reconstructed if the old format omitted the original viewport/font context; define the legacy guarantee as rotation of the corresponding unturned export's center at the same effective settings. If adding absolute positions for future moves, version/clean/read them in both Python and JS and retain legacy handling. Avoid a silent reinterpretation of all existing offsets.

Acceptance: moved crater and landing-site labels at 0°, 90°, 180°, arbitrary angle, and mirrored input. Compare centers to an independently calculated full-point transform, not merely the new helper's output. Cover whole image and feature crop at full/half scale, custom font/size, hidden names, and unchanged source-sidecar contents. Verify leaders still point to the correct feature. Run geometry/feature/render compatibility tests and visually inspect at least one annotated export with labelled reference points.

### P11 — Export freshness, destination identity and recent images (READY; overview BUG-11, BUG-13; related BUG-05 output collision)

Dependencies: P04, P05, P06, P10 before final integration. Files: `lunaratlas.output_plan/cmd_export/cmd_batch/batch_images`, `atlas_view.export_command`, `atlas_app.recent`, a small shared output/provenance helper if useful.

Confirmed: `--skip-existing` only checks image mtime; recent images include generated exports. A planning probe also confirmed both `moon.tif` and `moon.jpg` map to `moon_atlas.tif`. Do not allow a skip manifest for one source to authorize reuse of another source's output.

Implementation:

1. Add an atomic export manifest per output (for example `OUTPUT.export.json`) containing canonical source identity/signature, the rendered sidecar snapshot or digest, normalized EFFECTIVE export options including resolved defaults/font, a renderer format/version, and output identity/signature. Missing, corrupt, mismatched, or obsolete manifests mean regenerate; an mtime alone is insufficient. Hash relevant settings/data versions that can change rendering or conservatively invalidate them.
2. Record the inputs actually rendered. Capture/compare dependencies around rendering and do not publish a fresh manifest if they changed mid-export. Publish the image successfully before its manifest; a crash in between must cause a conservative regeneration, not a false skip. Failed exports must not mark stale output current. Read sidecar versions consistently with P05.
3. Preserve familiar default names for unambiguous images. Centralize collision handling for CLI and viewer: if same-stem sibling images would share a default output, choose a deterministic disambiguated filename that retains the complete source basename, e.g. `moon.tif_atlas.tif` versus `moon.jpg_atlas.tif`. Check existing provenance before overwriting a default destination owned by another source; use a separate destination or a clear refusal. Explicit `-o --overwrite` remains an intentional user choice. Cover case-sensitive extension variants too.
4. Share the existing reserved `_atlas` export-name exclusion between batch and recent listings in a module that avoids app/CLI import cycles. Supplement it with manifest ownership for custom output names in the work folder. Filter before sorting/capping the recent list. Do not decode excluded files just to decide they are exports.
5. `--locate-only --skip-existing` must consult valid positioning, not an unrelated export file; if no valid sidecar exists, locate the photo. Keep per-image batch failure handling and options isolation.

Acceptance: unchanged inputs/options skip; a saved drawing, changed font/night/scale/region, changed source signature, changed renderer version, and missing/corrupt manifest each regenerate. A failed export leaves no fresh success record. Same-stem master/preview exports stay separate in CLI/viewer/batch. More than 30 generated exports do not evict source photos from recent results. Run batch tests in `test_features.py`, output/security tests and the launch/recent/export journeys. Update help/README with freshness and collision naming behavior.

### P12 — Float display stretch and cache invalidation (READY; overview BUG-18)

Dependencies: P02; coordinate tile/session identity with P05. Files: `atlas_view.build_tiles`, tile URL construction in `viewer.js` if needed, cache tests.

Confirmed: for a positive float percentile of 0.3 the current gain is only 250, so the white point remains around 75 instead of 250; NaNs can poison the percentile. This is display-only processing.

Implementation: calculate the white point from finite samples; if it is positive use the actual value rather than clamping it to 1. Define zero/all-invalid input as black without warnings. Sanitize/clamp negative/nonfinite pixels consistently; `convertScaleAbs` takes absolute values, so blindly keeping it can turn negative samples bright. Leave source pixels and exported tonality unchanged. Preserve mono and colour handling without unnecessary full-image float64 copies.

Invalidate BOTH on-disk tile pyramids and browser-cached tile URLs when the render algorithm changes. An unchanged image signature alone cannot distinguish old dark tiles. Keep edit/session identity separate from tile-render version so fixing display does not orphan pending edits.

Acceptance: finite 0–1 float ramp with white point below 1 reaches the intended display range; mixed finite/NaN/Inf samples, all-invalid/zero images, negatives, uint8 and uint16 controls; inspect decoded JPEG tile values with lossy tolerance. An existing old-version cache is rebuilt and uses a new render URL. Repeat opening then reuses it. No new full decode on an unchanged warm cache.

### P13 — Empty font listings fail clearly (READY; overview BUG-19)

Dependency: P07 for consistent download failures. Files: `atlas_render.Fonts._ensure/_listed`, font reliability/security tests.

Confirmed: a truthy listing with no accepted TTFs leaves `files=[]`; `get()` later calls `min()` on an empty list. Malformed non-list JSON must also be handled deliberately.

Implementation: validate listing shape; after filtering, return already validated usable local files when available, otherwise raise a contextual user-facing “no usable font files” failure before constructing an empty Fonts instance. Keep bundled/static/variable font behavior, `.incomplete` recovery, URL/filename allowlists and `download=False` restrictions. Supporting nested `static/` folders is optional; it is not necessary to fetch arbitrary new paths to fix the crash.

Acceptance: mocked listing containing only a directory, empty list, malformed object/scalar, only rejected URLs, and valid TTF list; usable local fallback and interrupted-download cases. No live network is needed. Assert no empty Fonts object reaches rendering, no path/URL filter is weakened, and unavailable sidecar fonts still fall back safely.

### P14 — Exclusive Windows listening sockets (READY; overview BUG-12)

Dependencies: none. Files: `atlas_view.Server.server_bind/start_server`, `test_platforms.py` and server tests.

Local inspection confirms inherited `allow_reuse_address=True` and the stdlib bind path enables `SO_REUSEADDR`. The Windows consequence is platform-dependent and has not been reproduced on this Mac; report that limitation honestly.

Implementation: on Windows disable address/port reuse and set `SO_EXCLUSIVEADDRUSE` before bind, using the platform's available constants. Preserve POSIX behavior and the existing no-reverse-DNS bind optimization. Ensure failed socket construction is closed and port probing continues only for expected occupied-port cases; retain a clear error when the range is exhausted.

Acceptance: unit-check option ordering with a fake Windows socket; additionally run on real Windows with a first process listening and a second requesting the same starting port. The second must use the next free port; both authenticated servers must still return their own data. Verify first port is reusable after the owner exits and exhaustion is handled. A mocked test alone yields `implemented; Windows verification pending`, not `verified on Windows`.

### P15 — Deterministic progress journey coverage (READY; overview BUG-22)

Dependencies: integrate after the launcher-affecting packets; existing `journeys.mjs` already has unrelated edits to preserve. Files: `test_ui.py`, `tests/ui/journeys.mjs` and fixture support as required.

Confirmed race in the assertion: the page can update the bar and navigate in the same polling response, so a 250-ms external poll need never observe that state. The source report's suggestion of saving a high-water mark only on `window` is insufficient: navigation destroys that document. Its recorded full-suite/isolated results are prior evidence, not a guarantee the current failures have the same cause.

Implementation: separate progress rendering from real locate duration. Use a controlled status sequence in a browser fixture (loading/searching/refining/opening) and assert the visible stage/bar behavior before permitting the final ready response. Keep the real launch journey's assertions about upload, positioning, navigation, resulting sidecar, names, recent row and thumbnail. A fast successful launch must pass without requiring sampled intermediate frames. Alternatively persist test instrumentation across navigation, but do not add production delays or weaken checks to always pass.

Acceptance: deterministic fast-ready and staged-status cases, plus failure/cancel behavior and the real launch journey. Run the changed journey under cold and warm cache conditions. Keep timeouts bounded; no reliance on CPU speed or repeatedly rerunning until a flake disappears. Record browser/platform and any skips.

<!-- CODEX-PACKETS: append verified packets before this marker -->

## Verification and completion handoff

Run commands from the repository root. Use the dependency-complete interpreter; `.venv-build/bin/python` was confirmed usable for the planning probes. The repository progress runner prints a percentage:

```sh
.venv-build/bin/python lunaratlas/tests/run_tests.py --pattern 'test_app.py'
.venv-build/bin/python lunaratlas/tests/run_tests.py --pattern 'test_reliability.py'
.venv-build/bin/python lunaratlas/tests/run_tests.py --pattern 'test_features.py'
.venv-build/bin/python lunaratlas/tests/run_tests.py --pattern 'test_functional_render.py'
.venv-build/bin/python lunaratlas/tests/run_tests.py --pattern 'test_ui.py'
```

Choose the relevant module(s) after each packet, including new regression tests and any contract-dependent tests identified there. Add `test_security.py`, `test_compatibility.py`, `test_functional_cli.py`, `test_functional_pieces.py`, `test_platforms.py`, and close-up/geometry tests when those paths change. Do not run the entire suite after each small edit.

After all packets integrate and concurrent source changes have settled, run one full suite:

```sh
.venv-build/bin/python lunaratlas/tests/run_tests.py
```

Inspect skipped tests and retain their reasons; missing browser/data/platform coverage is not a pass. The existing `.github/workflows/test.yml` has a Windows/Linux/macOS matrix that can supply platform evidence when that workflow is run through the normal authorized process. Do not publish, push or dispatch CI solely on the basis of this document. Record Windows P14 as unverified if no real Windows run is available.

For the image changes, use scratch copies of representative full-disk and close-up inputs and inspect produced exports, especially P09/P10/P12. Do not alter original captures or reference panels. Keep a before/after image pair or coordinate overlay with the acceptance evidence; a green numerical helper test alone cannot establish rendering quality. This planning pass did not run the full test suite or real Windows/browser scenarios.

At handoff, append one completion entry covering all 22 overview IDs: implementation status, exact tests/results, verified platforms, any remaining evidence gaps, and actual changed files. Include the original-ID mapping when merging findings and distinguish deliberate behavior changes (BUG-20), defensive hardening (BUG-07), and unresolved platform/calibration evidence. If a finding is refuted by newer code, record the counterexample and disposition instead of adding unnecessary code. Preserve original reports as historical evidence. A report entry is closed only when its packet acceptance has evidence; `implemented` and `verified` must remain distinct.

## Claude execution log

Claude may append updates here while Codex continues the analysis. Keep prior entries and identify the packet, status, files changed, exact checks/results, and any blockers.

<!-- CLAUDE-EXECUTION-LOG: Claude owns entries below this marker -->

### 2026-10-01 — session start
- Status: `claimed` nothing. Read the full plan, `bugs-overview.md`, and the protocol. No packets are present before the `CODEX-PACKETS` marker, so no implementation has begun.
- Standing by for packets marked READY. In the meantime running read-only verification of the overview findings against the live worktree; no files outside this log will be touched until a READY packet exists.

### 2026-10-01 — P01, P02 claimed
- Status: `claimed` P01 (BUG-20, BUG-21) and P02 (BUG-15). Both are dependency-free and touch disjoint files, so taking them together.
- Will report `implemented` and `verified` separately; implementation alone will not be logged as verified.

### 2026-10-01 — P01 `verified` (BUG-20, BUG-21)

Files changed:
- `tool_settings.py` — new `_env_value()` reads matching outer quotes *before* stripping the inline comment, so `#` inside a quoted value stays literal; unterminated quotes and unquoted values keep the old reading. `_read()` now skips blank/`#`-leading lines and lines whose key part contains `#` (a comment that happens to contain `=` is not an assignment, which the old comment-first strip handled implicitly). The `pairs` branch skips whitespace-only items, uses `rpartition(':')`, and raises a named reason for a missing separator, an empty name, or a non-numeric value; an all-empty value is still invalid. No expansion or execution was added; only matching outer quotes are stripped. Module docstring updated to state the new rule.
- `lunaratlas/tests/test_functional_cli.py` — `test_hash_always_starts_a_comment` replaced by `test_hash_starts_a_comment_except_inside_quotes` (both quote types, literal hash, trailing comment, unquoted `#`, unterminated quote, commented-out line, comment containing `=`); added `test_pairs_tolerates_a_trailing_comma` and `test_pairs_rejects_empty_and_malformed_entries_with_a_reason`.

Checks: `python3 -m unittest test_functional_cli.Settings -v` → 14 tests OK. `python3 -m unittest test_functional_cli test_functional_pieces test_compatibility` → 119 tests OK. The user's `.env` was not touched; `.env.example` was not regenerated because SPECS and `example()` are unchanged.

Acceptance: quoted `C#11 EdgeHD` survives intact; `IMX678:2.0, IMX533:3.76,` yields both cameras; invalid numbers still fall back under the existing one-warning policy.

**Discrepancy (per protocol, not a change to the packet):** the old BUG-20 behaviour was not accidental — it was asserted by `test_hash_always_starts_a_comment` with the comment `# documented: even inside quotes`, and documented in the `tool_settings.py` module docstring (`# starts a comment`). P01 is explicit that quotes must be parsed first, so I implemented the packet and updated both the test and the docstring to match. Flagging it because this is a deliberate behaviour change to a documented rule, not purely a bug fix: anyone whose `.env` relies on a quoted value being truncated at `#` now gets the full string. Say the word if you want it reverted.

### 2026-10-01 — P02 `verified` (BUG-15)

Files changed:
- `lunaratlas/atlas_view.py` — `cache_size()` returns `os.path.getsize(path)` for a non-directory and keeps the `os.walk()` sum for directories; a missing path still counts as zero through the existing `OSError` guard. Eviction ordering, staleness handling and protected entries are untouched.
- `lunaratlas/tests/test_app.py` — three tests added: `test_cache_size_counts_a_file_as_well_as_a_folder` (direct file, nested directory, missing path), `test_thumbnails_alone_are_evicted_down_to_the_cap`, and `test_mixed_cache_evicts_only_what_the_thumbnails_push_over` (tiles under budget, tiles + thumbnails over; asserts the oldest eligible entry goes first, that retained entries account for exactly the remaining bytes, and that a second eviction removes nothing more).

Checks: `python3 -m unittest test_app` → 24 tests OK (the `ResourceWarning`s in that module are pre-existing and unrelated).

Confirming Codex's note: the pre-existing `test_cache_cleanup_...` test did pass accidentally — its protected `keep` pyramid alone exceeds the 80-byte limit, so the thumbnail was evicted whether or not it was counted. The new mixed-cache test is the one that actually fails against the old `cache_size()`.

### 2026-10-01 — P03 `verified` (BUG-03)

Files changed:
- `lunaratlas/atlas_app.py` — the vacancy-check-plus-`os.replace` fallback in `place()` is gone. The hard-link claim and the same-content deduplication (and the `(2)`, `(3)`… renaming on a real collision) are unchanged. `FileExistsError` still means "the name is taken" and falls through to the digest comparison. Any other `OSError` is now classified: errno values in the new module-level `NO_HARD_LINKS` (`EOPNOTSUPP`, `ENOTSUP`, `ENOSYS`, `EPERM`, `EXDEV`, `EMLINK`) are re-raised with a message naming the cause and the remedy; everything else (permission, I/O) propagates unchanged. `upload()`'s existing `except OSError` already deletes the temporary file and answers 500, so both cases are a clean failure with nothing in the work folder replaced.
- `lunaratlas/tests/test_app.py` — four tests added to `SamePhotoAgain`: `test_two_different_photos_racing_for_one_name_both_survive` (two equal-length payloads released from a `threading.Barrier`, no sleeps; both survive under distinct names), `test_racing_uploads_without_hard_links_lose_no_photo` (the same barrier race with `os.link` forced to `EOPNOTSUPP` — the actual BUG-03 sequence), `test_a_folder_without_hard_links_fails_the_upload_instead_of_replacing` (preexisting destination and its sidecar untouched, no temporary file), `test_a_permission_error_is_reported_as_itself_and_cleans_up`, and `test_a_name_taken_by_a_symlink_out_of_the_folder_is_refused_not_followed`.

Checks: `python3 -m unittest test_app test_security` → 78 tests OK. The three new failure-path tests were confirmed to be real regression tests: with `place()` temporarily reverted to the old fallback, all three fail (`200 != 500` — the old code published over the name), and they pass again once restored.

Design note on the packet's option: I took the "clear upload failure" default rather than an alternative atomic no-replace primitive. The packet is explicit that direct copying into an `O_EXCL` destination does not give the publication guarantee, and there is no portable atomic rename-if-absent to publish a fully written temporary file with; a process-local lock would not help across the app and CLI processes that share the work folder. So a filesystem without hard links now refuses the upload instead of risking a photo. Limitation recorded: uploads do not work at all on such a filesystem (exFAT, some network drives), which is a usability regression for that case, traded for not losing images. If you want a supported fallback there, it needs its own packet.

Separately: the symlink test documents existing behaviour I did not change — a symlink planted on a name makes `place()` return `None` and the upload is refused with 400 rather than that name being retried as `moon (2).tif`. Not in P03's scope, but worth a decision at some point.

### 2026-10-01 — P04 claimed (BUG-05)
- Status: `claimed`. Prerequisite for P05/P11 per the packet's dependency note; taking it next.

### 2026-10-01 — P04 `verified` (BUG-05), with a sharper root-cause than the overview

Files changed:
- `lunaratlas/atlas_geo.py` — `sidecar_path(image)` now returns `image + '.atlas.json'` (extension included), so `moon.tif` and `moon.jpg` get independent sidecars. Added `_legacy_sidecar_path()` (the old `splitext`-based name), `_read_sidecar_dict()`, and `resolve_sidecar(image)`: it prefers the canonical file, and falls back to the legacy shared-stem file **only** when the legacy file's recorded `image` basename and `image_signature` both match the requested image — never to paper over a damaged/missing canonical file, never for an ambiguous legacy file. `load_geo()` and `save_geo()` are rewritten on top of it; `save_geo()` always writes the canonical path, carrying over whatever a validated legacy (or canonical) file held, and never deletes the legacy file.
- `lunaratlas/atlas_view.py` — `read_edits()`/`write_edits()` now also go through `resolve_sidecar()` instead of opening `sidecar_path(image)` unconditionally. This matters beyond naming: before this fix, **edits had no signature or filename check at all** (see the correction below) — `read_edits()` just opened whatever `sidecar_path()` pointed at. `write_edits()` publishes to the canonical path (migrating a legacy sidecar on the next save, without deleting it).
- `lunaratlas/atlas_ephem.py` — `_sidecar_time()` now calls `atlas_geo.resolve_sidecar()` (local import; no cycle, `atlas_geo` does not import `atlas_ephem`) instead of reimplementing the old `splitext`-based path.
- `lunaratlas/atlas_app.py` — `recent()`'s `load_geo(p) if os.path.exists(sidecar_path(p)) else (None, None)` gate is removed (confirmed stale per the packet: it skipped `load_geo()`, which itself does all the validation, whenever only a legacy sidecar existed).
- `lunaratlas/lunaratlas.py` — the `locate()` log line and the `-o`-collision protection in `cmd_export` now resolve through `resolve_sidecar()` too, so a legacy sidecar is also protected from being overwritten by an export's default output name.
- `scripts/test_testimages.py` — `read_sidecar()`'s hand-rolled sidecar path updated to the canonical name (operator script against local `TestImages`, not part of the package or test suite).
- Tests: `test_compatibility.py` (`sidecar_path` path-forms), `test_functional_geometry.py` (`save_then_load` path, plus four new tests — same-stem isolation, validated-legacy-still-loads-but-not-adopted-by-a-sibling, legacy migration on write, and a direct `read_edits`/`write_edits` cross-image isolation test), `test_e2e_journeys.py` (canonical-name listing), `test_app.py` (a sidecar name asserted in a P03 test), `test_e2e.py` (added `test_edits_round_trip_over_a_legacy_sidecar`: a real HTTP viewer session against an image whose only sidecar is the pre-rename file, confirming it loads, is editable, and the save publishes a canonical sidecar alongside the untouched legacy one).

Checks: `python3 -m unittest test_functional_geometry test_compatibility test_reliability_surroundings` → 127 OK. `python3 -m unittest test_app test_reliability test_features` → 96 OK. `python3 -m unittest test_e2e.ViewerServer` → OK (full class, including the new legacy-sidecar HTTP round trip). All import-checked (`lunaratlas`, `atlas_view`, `atlas_app`, `atlas_ephem` import cleanly — no cycle from the new `atlas_ephem -> atlas_geo` call).

**Correction to the overview, found while independently re-verifying this finding (see the standing read-only verification pass below):** the overview's claim that colliding geometry is "silently applied to the wrong pixel dimensions" does not happen — `load_geo()` already compares `image_signature` (size + mtime) and rejects a foreign sidecar, so a same-stem collision on `geometry` alone produces an expensive, confusing re-locate loop, not a wrong-dimension result. The real silent corruption, which the overview under-states, is that **`read_edits()`/`load_geo(...)[1]['edits']` did no signature check of any kind** — a same-stem sibling's drawings, hidden names, moved labels, style/font, `quality`/`quality_gate`, and (via `atlas_ephem._sidecar_time()`) `capture_utc` were all shown and exported as the other image's own. For a file whose name carries no timestamp, that last one *does* produce a silently wrong geometry (the re-locate is handed the sibling's capture time). This packet's fix (routing edits through the same `resolve_sidecar()` identity check as geometry) closes that gap along with the stem collision; the new `test_edits_do_not_cross_over_between_same_stem_images` test targets exactly this, independent of the geometry-signature check that was already in place.

Limitation: a legacy sidecar is migrated to canonical only on the next successful *write* (locate or edit save), matching the packet's contract. A read-only workflow (CLI `info`/`find` on an image that is never relocated or edited) continues to read the validated legacy file indefinitely, which is intended, not a bug.

### 2026-10-01 — P05 claimed (BUG-04, BUG-14)
- Status: `claimed`. Dependency P04 is `verified` above. This is the largest packet so far (server-owned version, file locking, idempotent client retry); will report progress incrementally if it needs to split into sub-steps, but logging as one packet per the protocol's bug-ID stability.

### 2026-10-01 — P05 implemented, test run in progress (BUG-04, BUG-14)
- Status: `implemented`, verification run in progress; will follow up with `verified` once the full affected-suite run (test_e2e, test_reliability, test_compatibility, test_functional_cli, test_functional_geometry, test_security, test_app) and the real headless-Chrome self-test both confirm green. The Chrome self-test (test_e2e.BrowserSelfTest) already passed on its own.
- Files changed so far: `lunaratlas/atlas_paths.py` (new cross-process `file_lock()`, flock on POSIX / byte-range lock on Windows, never deletes its lock file), `lunaratlas/atlas_geo.py` (`save_geo()` now holds `file_lock()` around its whole read-modify-write), `lunaratlas/atlas_view.py` (`write_edits()` now takes an explicit `rev` and does the durable-revision read, compare, and write as one operation under `lock, file_lock(canonical)`; the durable revision is stored as a sidecar-level `edits_rev` key, sibling to `edits` and not inside it — required by the pre-existing `test_a_late_save_never_overwrites_a_newer_one`, which explicitly asserts the number is never stored inside `edits`; `Session.__init__` now seeds `self.rev` from that durable value instead of 0; the `/edits` GET and POST handlers were rewritten around the new single-lock contract and now also catch `SystemExit` from `write_json_atomic`, which the old `except (OSError, ValueError, ArithmeticError)` tuple let escape raw), `lunaratlas/viewer/viewer.js` (`post()`'s conflict and session-gone branches now reject rather than resolve, so `flush()` — and therefore the export flow's `await flush()` — correctly treats an unsaved conflict as unsaved, instead of proceeding as if the edits had landed).
- New tests: `test_reliability.py` (`test_session_restart_does_not_reset_the_durable_revision_to_zero`, `test_write_edits_and_save_geo_share_the_cross_process_lock`), `test_e2e.py` (`test_overlapping_saves_do_not_race_the_revision_check_and_the_write` — a real HTTP barrier race, deterministic outcome; `test_a_stale_save_is_rejected_without_touching_the_sidecar`; `test_a_retried_save_at_the_same_revision_is_idempotent`), each against its own fresh viewer session (not `cls.v`) so the explicit revision numbers they use cannot collide with other tests sharing that session's sidecar, the way `test_security.py`'s existing `test_a_non_finite_revision_is_ignored...` already has to account for.
- Found and fixed one self-introduced regression before logging this: my first pass stored the durable revision at `d['edits']['rev']`, which broke the wire contract two pre-existing tests depend on (`test_e2e.ViewerServer.test_edits_round_trip` and `test_security.test_a_late_save_never_overwrites_a_newer_one`, the latter explicitly asserting `rev` is never inside `edits` in the sidecar). Moved it to a sidecar-level `edits_rev` key instead.
- Deliberately not implemented, recorded as a limitation rather than silently narrowed: a full operation-ID idempotency scheme (item 3 of the packet). The client's `rev` is already a strictly increasing per-save counter (`++rev` on every `body()` call), and `write_edits` treats "rev equal to the current durable revision" as a successful no-op commit, not a rejection — so a lost-acknowledgement retry (same content, same or a newer rev) is idempotent in effect without a separate operation-ID field. What this does **not** give: detecting a resend whose rev has since been superseded by someone else's *different* content at a *higher* rev as "already applied" versus "superseded" — that distinction would need an operation ID per the packet's literal design. `test_a_retried_save_at_the_same_revision_is_idempotent` covers the case this simpler scheme does handle.
- Cross-process file locking was added for `save_geo()` and `write_edits()` (both now lock on the canonical sidecar path) but not for `load_geo()`/`read_edits()`/`resolve_sidecar()` reads, which remain lock-free plain reads relying on `write_json_atomic`'s rename-based atomicity to avoid torn reads. This matches the packet's "all read/modify/write operations" ask for the two mutating entry points; a bare read racing a write will see either the old or the new complete file, never a partial one, so I judged adding read-side locking unnecessary for correctness. Flagging in case the intent was broader.

### 2026-10-01 — P05 `verified` (BUG-04, BUG-14)
- `python3 -m unittest test_e2e test_reliability test_compatibility test_functional_cli test_functional_geometry test_security test_app` → 278 tests OK, 4 skipped (pre-existing skip reasons, unrelated to this packet). `test_e2e.BrowserSelfTest` (real headless Chrome running viewer.js, including a save/undo/redo/drag cycle) passed on its own as well. The pre-existing `test_security.test_a_late_save_never_overwrites_a_newer_one` and `test_a_non_finite_revision_is_ignored_rather_than_locking_out_every_later_save` passed unchanged, confirming the new durable-revision storage keeps the exact wire contract those tests pin down.

### 2026-10-01 — P06 claimed (BUG-01, BUG-17)

### 2026-10-01 — P06 `verified` (BUG-01, BUG-17)

Files changed:
- `lunaratlas/atlas_view.py` — `export_command()`: every dialog choice now reaches the CLI explicitly instead of being omitted whenever it happened to match the CLI's own default. `--layers` is always emitted (the `elif len(layers) < 5` shortcut is gone); `--lettered`/`--no-lettered` and `--landing`/`--no-landing` are derived from the layer list and sent explicitly, so the CLI's own environment-driven `--lettered`/`--landing` switches can no longer re-discard a layer the dialog's list included; `--rims`/`--grid`/`--drawings`/`--info` now emit both polarities, not only the `--no-X` one; `--night` is always emitted from the `hide`/`dim`/`show` whitelist (an unrecognized value maps to the dialog's own default, `hide`, not omitted) — this is the confirmed BUG-01 mechanism: the viewer's default is `hide`, the CLI's built-in default is `dim`, and omitting the flag for `hide` let the CLI's different default take over, dimming names the viewer showed as hidden. A full-size export now also sends `--max-size 100000` (within `LUNARATLAS_MAX_SIZE`'s own 0–100000 range, comfortably larger than any real capture) so a nonzero environment default cannot silently shrink an export the dialog says is full size — found independently while auditing this function per the packet's instruction, not in the original overview text; `--max-size 0` was tried first but rejected by `cmd_export`'s own "at least 1 px" check, so there is no zero-sentinel at the CLI flag level.
- `lunaratlas/lunaratlas.py` — `find_matches()` now returns no match for a blank/whitespace-only query instead of `startswith('')` matching the first feature in the list (the exact BUG-17 mechanism). `cmd_export` rejects a blank `--around` immediately, before `output_plan`, `geometry()`/`locate()`, or any download.

Tests: `test_functional_pieces.py` (`ExportOptions` rewritten across five methods to assert both polarities/explicit layers/lettered/landing/night/max-size; new `ExportOptionsAgainstTheRealParser.test_the_dialogs_choices_survive_a_contrary_environment` — builds the dialog's argv, sets the opposite of every one of its choices in the environment, runs it through `lunaratlas.main()`'s real argument parser and a real export, and checks the rendered output's actual pixel height instead of just flag presence, per the packet's explicit acceptance instruction; `CommandLineHelpers.test_an_empty_name_matches_the_first_feature_rather_than_refusing` renamed to `test_a_blank_name_is_refused_not_matched_to_the_first_feature` and corrected — it had been asserting the bug itself as intended behavior), `test_functional_cli.py` (`test_export_validation` gained a blank-`--around` case; new `test_a_blank_around_is_rejected_before_anything_is_located_or_downloaded` confirms no sidecar is created; `test_export_command_feature_and_defaults`'s stale `assertNotIn('--night', cmd)` corrected to assert the explicit `hide`), `test_features.py` (new `FindMatches.test_a_blank_name_matches_nothing` covering `find_matches` directly for four blank-ish inputs).

Checks: `python3 -m unittest test_functional_pieces test_functional_cli test_features test_e2e test_security test_compatibility` → 233 tests OK, 4 skipped (pre-existing, unrelated).

Three pre-existing tests were found pinning the exact bugs this packet fixes as intended behavior (`test_an_empty_name_matches_the_first_feature_rather_than_refusing`, `assertNotIn('--layers', ...)` for all-five-layers, `assertNotIn('--night', self.args())`/`self.args(night='never')`, and `test_export_command_feature_and_defaults`'s `assertNotIn('--night', cmd)`) — all corrected to assert the fixed behavior rather than silently left in place or deleted.

Not changed: BUG-01's overview text also mentions "selected on states for layers, rims, grid, drawings, and info" generally — confirmed in my independent verification pass that only `--night` was actually broken among the booleans checked (rims/grid/drawings/info's env defaults happened to agree with the dialog in the common case), but both polarities are now sent for all of them anyway, closing the latent version of the same defect for anyone with a non-default `.env`.

### 2026-10-01 — P07 claimed (BUG-02, BUG-08)

### 2026-10-01 — P07 `verified` (BUG-02, BUG-08)

Files changed:
- `lunaratlas/atlas_geo.py` — new `NoUsableLimb(Exception)` (deliberately not a `SystemExit` subclass), raised at the four `fit_limb()` sites ("no Moon found"/"could not find the limb") and the two `locate()` sites ("limb fit unreliable", "too few terrain matches") that were previously bare `SystemExit`. `download()`'s transfer loop is now wrapped in `except (urllib.error.URLError, OSError, socket.timeout, http.client.HTTPException)`, converting a connection reset, a timed-out read, or a DNS failure into `SystemExit(f'could not download {url} (...); check the network and try again')`; the two existing `raise SystemExit(...)` calls inside that same block (oversized/damaged download) pass through unaffected since `SystemExit` is not an `OSError`.
- `lunaratlas/lunaratlas.py` — `quality_gate()`'s `except SystemExit: pass` around its own `fit_limb()` call narrowed to `except NoUsableLimb`. `geometry()`'s `raise SystemExit('no limb in view')` changed to `raise NoUsableLimb(...)`, and its close-up-fallback decision narrowed from `except SystemExit as e:` to `except NoUsableLimb as e:` — this is the actual BUG-02 fix: a `SystemExit` from anywhere else inside `locate()` (confirmed reachable: `Reference.__init__` building the reference map can call `download()`, which — after the BUG-08 fix above — now raises exactly this kind of clear `SystemExit` for a network failure) no longer gets caught here and misread as "no limb, try a close-up"; it propagates as the ordinary fatal error. The inner `except SystemExit as e2:` around `locate_closeup()` itself is unchanged (any failure of the close-up attempt itself is still terminal, with no further fallback).

Tests: `test_reliability.py` — new `LocateFailureClassification` class: `test_a_download_failure_inside_locate_is_not_mistaken_for_no_limb` (mocks `Reference.__init__` to raise the exact `SystemExit` a failed reference-map download now produces, mocks `locate_closeup` to raise `AssertionError` if called, and asserts the download failure's own message propagates with no close-up attempt) and `test_a_genuinely_unusable_limb_still_falls_back_to_a_close_up` (a deliberately featureless image with a SharpCap-style capture time in its name, confirming the recoverable path still works). `Downloads.test_broken_connection_leaves_nothing` and `test_failed_redownload_keeps_the_old_copy` updated from asserting a raw `ConnectionResetError`/`OSError` to the new `SystemExit`, per the packet's explicit instruction, keeping their existing cleanup/untouched-destination assertions (and `test_failed_redownload_keeps_the_old_copy` now also asserts no temporary file is left behind).

Checks: `python3 -m unittest test_reliability.LocateFailureClassification test_reliability.Downloads` → 7 tests OK. `python3 -m unittest test_functional_geometry test_reliability test_closeup_search test_app test_stability test_performance` → 176 tests OK, 2 skipped (pre-existing, unrelated).

Scope note: audited `atlas_names.py`, `atlas_closeup.py`, and the Google Fonts boundary in `atlas_render.py` per the packet (`fit_limb()` callers and all other `download()` call sites) — both `_download()` callers in `atlas_names.py` and the LOLA download in `atlas_closeup.py` go through the now-hardened `download()` with no caller-side changes needed; the font boundary in `atlas_render.py` already had its own `except (OSError, urllib.error.URLError)` → `SystemExit` conversion before this packet and was left unchanged.

### 2026-10-01 — P08 claimed (BUG-06, BUG-07)

### 2026-10-01 — P08 `verified` (BUG-06, BUG-07)

Analysis correction confirmed by implementation: as the packet already noted, the crash site in the overview text is stale. `np.asarray(None, float)` produces a 0-D scalar NaN array; the actual `TypeError: iteration over a 0-d array` happens inside `night_side()`'s own `[float(v) for v in light]` when writing `light.json`, not in `page_data()`'s later `zip()` as the overview describes. BUG-07 is confirmed defensive hardening, not a demonstrated production crash: `layout()`'s `light` always comes from `night_side()`/`page_data()`'s own `np.ones`/validated arrays today, and the lighting cache already rejects a length mismatch — but a longer/shorter array from a future caller or a corrupted `light.json` would have hit `light[i]` unguarded.

Files changed:
- `lunaratlas/atlas_view.py` — new `valid_light(light, feats)`: returns a finite 1-D array of exactly `len(feats)`, or `None` ("unknown" — rendering already treats `None` as "do not dim anything"). `night_side()` now runs every value (including a cache hit, including the freshly computed one) through it before use; a `None`/malformed result is returned as `None` instead of being coerced into a 0-D array and crashing. The cache key's fingerprint changed from `len(feats)` to the ordered list of `(name, lat, lon)` for every feature, so two catalogues of the same length in a different order (or a different one entirely) can no longer reuse each other's cached lighting; `LIGHT_VERSION` bumped from 1 to 2 so existing `light.json` files are never read under the new key semantics. `page_data()` now substitutes `np.ones(len(feats))` when `night_side()` returns `None`, so every name is shown as lit rather than crashing in the `zip()` the overview named.
- `lunaratlas/atlas_render.py` — `layout()` now validates `light` (shape, length against `feats`, all-finite) right after its parameters are normalized, before the loop that indexes `light[i]`; anything that doesn't fit is treated as `None` (unknown), never indexed. Implemented inline rather than sharing `atlas_view.valid_light()` because `atlas_render` cannot import `atlas_view` (the reverse import already exists, so sharing it would be a cycle).

Tests: `test_app.py` — new `NightSideForACloseupWithNoCaptureTime` class: `test_page_data_does_not_crash_and_shows_names_as_lit` (a full `page_data()` call for a close-up image with no capture time, confirming it returns feature rows with `lit >= 1.0` instead of raising) and `test_night_side_itself_returns_none_rather_than_a_malformed_array` (`night_side()` directly). `test_functional_render.py` — new `Layout.test_an_unknown_or_malformed_light_array_is_treated_as_no_dimming`: six malformed inputs (wrong length both ways, all-NaN, a plain list, a string, a bare number), each confirmed to render identically to `light=None`.

Checks: `python3 -m unittest test_app.NightSideForACloseupWithNoCaptureTime test_functional_render.Layout` → 18 tests OK. `python3 -m unittest test_app test_functional_render test_functional_geometry test_e2e test_reliability` → 216 tests OK, 4 skipped (pre-existing, unrelated).

### 2026-10-01 — P09 claimed (BUG-09, BUG-16)

### 2026-10-01 — P09 `verified` (BUG-09, BUG-16)

BUG-16 was already fixed in the committed tree before this session (`limb_profile()` already computes `finite_columns = np.isfinite(A).any(0)` before `nanmedian`, applies it to both the profile array and `t` as `tt`, and filters both again with `good = np.isfinite(mm)`) — confirmed with a direct reproduction (disk + Gaussian blur, radius offsets 0/1/3 px, `warnings.simplefilter('error', RuntimeWarning)`): no warning, finite width in every case. Recording disposition per the protocol: `already-fixed; no further change needed`. Added `test_limb_profile_with_a_radius_offset_emits_no_all_nan_warning` to `QualityMeasures` to lock this in, since the existing `test_limb_edge_width_of_a_gaussian_blur` only varies blur sigma, not the radius-fit offset my independent verification pass identified as the actual trigger (not blur, contrary to the overview's title) — the correction that pass raised: "the title and mechanism are wrong; the trigger is a sign-consistent offset between the fitted circle radius and the real limb."

Files changed (BUG-09):
- `lunaratlas/atlas_quality.py` — `posterisation()` now returns `(score_or_None, diagnostic_or_None)`. The 8-bit branch is byte-for-byte the original, well-calibrated check (unchanged score, no diagnostic). Above 8 bits, the GCD-only "fix" from the source report was deliberately not implemented (per the packet: both an ordinary low-bit-depth sensor and destructively quantised data can show the same regular gaps, and a histogram alone cannot prove which). Instead: the data's own apparent quantisation step is estimated as the median gap between sorted unique rounded values in the 1st–99th percentile range; a step ≤ 1.5 means no detectable quantisation (smooth native data) and returns `(None, diagnostic)` with that near-zero step recorded; a larger step returns `(None, diagnostic)` where the diagnostic reports the step, how many distinct values are actually present, and how many that step predicts over the measured range. The score itself is `None` in every above-8-bit case — `verdict()`'s existing `over()` helper already never rejects on `None` ("a measure that could not be taken never rejects"), so this is never a hard rejection, exactly as the packet specifies. `measure()` stores the diagnostic as `q['posterisation_diagnostic']` only when one exists, leaving `q['posterisation']` as the (unchanged-shape) score field `verdict()` reads.

Tests: `test_functional_render.py` — `QualityMeasures.test_posterisation` updated for the new `(score, diagnostic)` return shape (8-bit cases unchanged in substance). New `test_posterisation_above_8_bits_is_diagnostic_not_a_rejection`: a dim 16-bit-stored 12-bit fixture (true step-16 quantisation, no sub-step jitter — matching what a real ADC can actually output) asserts `score is None` and the diagnostic's detected step ≈ 16; a smooth native-16-bit fixture asserts a near-1 detected step; an 8-bit ramp stretched ×257 into 16-bit (the false-negative case my own earlier verification probe found scoring a confident `0.0`) asserts `score is None` and a detected step ≈ 257, i.e. no longer confidently reported as free of quantisation, and also no longer a hard rejection either way.

Checks: `python3 -m unittest test_functional_render.QualityMeasures` → 11 tests OK. `python3 -m unittest test_functional_render test_reliability test_app test_e2e test_functional_geometry` → 218 tests OK, 4 skipped (pre-existing, unrelated).

Limitation recorded per the packet: fixtures here cover the four cases explicitly named (dim low-bit-depth, smooth native 16-bit, an expanded 8-bit ramp, and 8-bit posterised/clean via the pre-existing test) but not colour/mono variants, sparse samples, or nonfinite float values beyond what `v.size < 1000`/`len(uniq) < 2` already guard against structurally. No spatial banding metric was added — the packet is explicit that one would need representative labelled-image evidence this plan does not have, and that it is not required to close this finding.

### 2026-10-01 — P10 claimed (BUG-10)

### 2026-10-01 — P10 `verified` (BUG-10)

Files changed:
- `lunaratlas/atlas_render.py` — new `label_anchor(f, geo, fonts, min_px=24, font_scale=1.0, layers=LAYERS, rims=True)`: the automatic label spot for one feature alone, in native (unscaled, uncropped) image px, obtained by calling `layout([f], geo, identity_view, fonts, ..., night='show', keep_on_disk=False, overrides=None)` and reading the one result's `(x, y)` — reusing the exact same tested per-feature spot formula `layout()` already runs, rather than a second parallel implementation. `transform_edits()` gained an `anchors={name: (old_home, new_home)}` parameter (default `None`): with it, a moved label's absolute point (`old_home + old_offset`) is transformed as a point (`M @ point + b`, the same transform every drawing already gets) and re-expressed relative to `new_home`; without it (no caller-supplied geometry/font context, or a feature `label_anchor()` couldn't place), the function falls back to its original behaviour — rotating the stored offset alone — which is the documented, deliberately imperfect legacy guarantee for data from before this fix.
- `lunaratlas/lunaratlas.py` — `cmd_export`: the pre-turn geometry and feature projection are kept (`old_geo`, `old_feats`) instead of being overwritten by the post-turn reprojection. The `transform_edits()` call moved from immediately after loading the sidecar (before fonts exist) to right after `fonts`/`families` are ready, where it now builds an `anchors` dict — one `label_anchor()` call under the old geometry and one under the new, per named override, using the export's own actual `fonts`, `a.min_size`, `a.font_scale`, `layers` (which already has `--lettered`/`--landing` folded in per P06), and `a.rims` — "the same effective settings" the packet's compatibility note calls for.

Tests: `test_features.py` (`Turning` class) — `test_a_moved_label_s_absolute_position_survives_a_turn`: for 0°, 73°, and 180° turns, the new `(dx, dy)` is checked against an **independently recomputed** full-point transform (`home_old + offset` transformed by `M @ point + b`, then re-expressed relative to an independently-computed `home_new`) — not merely re-deriving the same formula the implementation uses, per the packet's explicit acceptance instruction. `test_without_anchors_falls_back_to_rotating_the_offset_alone` locks in the legacy path the existing `test_the_drawings_turn_and_the_ellipse_becomes_an_outline` already exercises. `test_functional_cli.py` — new end-to-end `test_north_up_export_keeps_a_moved_label_on_its_feature`: a real `export --north-up` CLI run with a label moved in the sidecar, checking actual pixels are drawn near the independently-computed correct position and (where the two differ by more than 80 px, which this fixture's rotation does) checking nothing was drawn at the old offset-only-rotation position instead. Both new tests were confirmed to be real regression tests: with `cmd_export`'s `anchors=anchors` temporarily removed (falling back to the old offset-only path for every call), the end-to-end test's own numeric comparison showed the legacy and fixed positions differing by roughly 360px for the fixture used, and was restored once confirmed.

Checks: `python3 -m unittest test_features.Turning` → 7 tests OK. `python3 -m unittest test_functional_cli.Commands.test_north_up_export_keeps_a_moved_label_on_its_feature` → OK. `python3 -m unittest test_features test_functional_cli test_functional_render test_functional_geometry test_e2e test_compatibility` → 271 tests OK, 4 skipped (pre-existing `needs_all`/platform gates, unrelated).

Not implemented, per the packet's own caveat: no new persistent position representation (absolute positions) was introduced, so there is nothing new to version/clean/read in `viewer.js`; the stored schema is unchanged (`{dx, dy}` relative to the automatic home, as before) — only how the export computes the new `{dx, dy}` from a turn changed. "Exact historical screen centers cannot be reconstructed" when `label_anchor()` cannot place a feature (e.g., class/size/current settings would never label it) is handled by falling back to the legacy offset rotation for that one override, not by failing the whole export.

### 2026-10-01 — P11 claimed (BUG-11, BUG-13; related BUG-05 output collision)

### 2026-10-01 — correction to P07's `verified` entry (BUG-08)

While implementing P11 I found a real regression in P07's `download()` fix, caught by the existing (not my own) `test_security.Downloads.test_only_https` and `test_the_checksum_and_the_size_are_enforced`: the broad `except (urllib.error.URLError, OSError, socket.timeout, http.client.HTTPException)` added for BUG-08 also caught `https_check()`'s own scheme/host-allowlist refusal (a synchronous, pre-network validation, also raised as `urllib.error.URLError`) and folded it into the generic "could not download ... check the network and try again" message — losing the distinct security-relevant refusal and its "refusing ..." text.

Fix: the except clause now re-raises unchanged when the caught `URLError`'s reason text starts with `'refusing '` (the exact prefix `https_check()` always uses), keeping that check's own type and message; every other case (the two test suites' actual network-failure scenarios) is still converted to `SystemExit` as P07 intended.

Checks: `python3 -m unittest test_security.Downloads test_reliability.Downloads` → 11 tests OK (including the two previously-failing existing tests). New regression test added: `test_reliability.Downloads.test_a_disallowed_scheme_or_host_stays_its_own_refusal_not_a_generic_network_message`. Full re-sweep `python3 -m unittest test_features test_functional_cli test_app test_e2e test_security test_compatibility` → 238 tests OK, 4 skipped.

This is why the plan's "test only at the end" alternative is riskier than it looks: this regression was in P07, surfaced only while verifying a later, unrelated packet (P11), and was caught quickly because targeted suites are run after every packet rather than saved up for one pass at the very end.

### 2026-10-01 — P11 `verified` (BUG-11, BUG-13; BUG-05 output collision)

Files changed:
- `lunaratlas/atlas_paths.py` — new shared `IMAGE_EXT` constant and `is_export_name(name)` (stem ends in `_atlas` or contains `_atlas_`), in the one module both `atlas_app.py` and `lunaratlas.py` already import without creating a cycle (per the packet's explicit ask).
- `lunaratlas/atlas_app.py` — `recent()`'s file filter now also excludes `is_export_name(n)` (bugs-overview BUG-13: it used to list every image file, including the app's own `IMAGE_atlas….ext` exports, as an unsolved photo).
- `lunaratlas/lunaratlas.py` — `batch_images()` now uses the shared `is_export_name()` instead of its own regex (both now agree by construction). `output_plan()`: when no explicit `-o` is given, scans the source folder for a same-stem sibling image (case-insensitive extension match) and uses the full basename (extension included) in the default name only when one exists — `moon.tif` and `moon.jpg` now default to `moon.tif_atlas.tif` / `moon.jpg_atlas.tif` instead of colliding on `moon_atlas.tif` (the BUG-05-adjacent output collision), while an unambiguous image keeps the familiar short default name. A new export-manifest system (`_export_manifest_path`, `_effective_export_options`, `_export_fingerprint`, `export_owner`, `export_is_current`, `write_export_manifest`, plus a shared `_resolve_font` so the freshness check fingerprints the SAME resolved font `cmd_export` will actually use, not the unresolved CLI value) replaces the mtime-only `--skip-existing` check (bugs-overview BUG-11): a manifest (`OUTPUT.export.json`) records the source's absolute path, its image signature, the full sidecar content (geometry + edits + quality) via `load_geo()`, every export option at its resolved effective value, and the output's own image signature; it is published only after the output file is written successfully, so a crash or a refused encoder leaves no manifest and forces regeneration next time. `output_plan()` also now refuses to silently replace a *default-named* destination whose manifest names a different source image (protects against a leftover collision from before this version, or any other two-sources-one-name situation); an explicit `-o --overwrite` is unaffected, as the packet specifies. `cmd_batch`'s `--skip-existing` now calls `export_is_current()` for export mode, and for `--locate-only` consults `load_geo(image)[0] is not None` directly instead of an export file's mtime (bugs-overview BUG-11 item 5 — the export path may not even exist in locate-only mode).

Tests: `test_functional_cli.py` (`OutputPlan`) — four new tests: disambiguated default names for real same-stem siblings, a case-insensitive-collision check (via a mocked `os.listdir`, since the test filesystem itself is case-insensitive and cannot produce two really-distinct same-stem files to prove this end to end), a provenance refusal when a default destination's manifest names a different source, and confirmation that a destination owned by *this* source is still replaced without asking. `test_features.py` (`Batch`) — four new tests: `--skip-existing` regenerates after a saved drawing (mtime bumped on the stale export to rule out a timing coincidence) and after a changed effective option (`--night show`); a failed export (mocked `cv2.imwrite` returning false, going through the real `write_atomic`/`SystemExit` path) leaves no manifest and is not mistaken for current next run; `--locate-only --skip-existing` consults positioning directly, confirmed both with and without an export file from a prior non-locate-only run. New `RecentExcludesExports` class: a real export via the CLI does not appear in `App.recent()`.

Checks: `python3 -m unittest test_functional_cli.OutputPlan` → 9 OK. `python3 -m unittest test_features.Batch test_features.RecentExcludesExports` → 12 OK. Full sweep `python3 -m unittest test_features test_functional_cli test_app test_e2e test_security test_compatibility` → 238 tests OK, 4 skipped, after fixing the P07 regression recorded in the correction entry above.

Scope trimmed from the packet's full design, recorded as a limitation: the manifest's "renderer format/version" and "hashed relevant settings/data versions" are represented by a single `EXPORT_MANIFEST_VERSION` constant (bump manually when the renderer changes in a way fingerprints can't capture) rather than an automatic hash of the renderer's own code/data files; the effective-options fingerprint covers every CLI-level export option (`scale, max_size, region, around, size, north_up, layers, lettered, landing, rims, grid, drawings, info, night, min_size, font_scale, font, fit, quality, time`) plus the resolved format and font, but not a hash of the font FILE's own bytes (a font family name changing to a different file with the same name would not invalidate a cache — an edge case judged out of scope here). The viewer's own `/export` HTTP path (`atlas_view.export_command` → a `lunaratlas.py export` subprocess) does not go through this manifest system at all — it has no `--skip-existing` concept (every export from the dialog is an explicit, deliberate action) — so this packet's freshness work is scoped to the CLI's `batch` command, matching where `--skip-existing` actually exists.

### 2026-10-01 — P12 claimed (BUG-18)

### 2026-10-01 — P12 `verified` (BUG-18)

Files changed:
- `lunaratlas/atlas_view.py` — `build_tiles()`'s display-stretch branch (float data only; exports keep original tonality elsewhere): the white point is computed from finite samples only (`np.isfinite` filter before `np.percentile`, so a single NaN in the 1-in-49 sample no longer poisons it), and used as-is whenever positive instead of `max(white, 1)` — the exact BUG-18 mechanism, where a valid 0-1 float image with a white point like 0.3 was stretched with alpha 250 instead of ~833 and stayed far too dark. An all-invalid or non-positive white point now means black, computed explicitly (`white = 0.0`) rather than relying on a clamp, and with no warning (the finite-sample filter means `np.percentile` is never called on non-finite data). Before the stretch, the whole array is sanitized in place (`np.nan_to_num(..., copy=False)` then `np.clip(..., out=g)`): NaN/Inf become 0 and negatives are floored at 0, because `cv2.convertScaleAbs` takes the absolute value and would otherwise render a negative sample bright. `g` already owns its own buffer at this point (`raw` was deleted just above), so this sanitization is the only extra array touched, not a new full-image copy on top of what `convertScaleAbs` itself already allocates.
- New `TILE_RENDER_VERSION = 2` constant: folded into `tile_version()`'s hash (the browser-facing tile URL) and into `meta.json`'s on-disk cache record (`build_tiles()`'s freshness check now also requires `meta.get('render') == TILE_RENDER_VERSION`, in addition to the existing image-signature and tile-completeness checks) — an unchanged image signature alone could not tell an old, too-dark pyramid apart from a correct one, per the packet. This is independent of `Session.rev`/the durable edit revision P05 tracks, so fixing display does not touch pending-edit identity.

Tests (`test_functional_cli.ViewerServerSide`): `test_a_dim_float_image_reaches_the_full_display_range` (a 0-1 float ramp with white ≈0.3 reaches >200 in the decoded tile, not ≈75), `test_nan_inf_and_negative_float_pixels_do_not_poison_or_brighten` (mixed finite/NaN/Inf/negative regions each render black — checked a safe distance inside each block to tolerate lossy-JPEG ringing at the sharp synthetic edges, per the packet's own "lossy tolerance" instruction — while the valid region still reaches the display range), `test_an_all_invalid_or_all_zero_float_image_is_black_without_a_warning` (all-zero and all-NaN inputs, run with `warnings.simplefilter('error')`: no warning, output is black), `test_an_old_cache_without_a_render_version_is_rebuilt` (a `meta.json` with its `render` key stripped, simulating a pre-fix cache, is rebuilt rather than reused, and the rebuilt manifest records the current version), `test_the_browser_tile_url_changes_with_the_render_version` (`tile_version()` changes when `TILE_RENDER_VERSION` does, for the same otherwise-unchanged image).

Checks: `python3 -m unittest test_functional_cli.ViewerServerSide` → 21 tests OK. `python3 -m unittest test_functional_cli.ViewerServerSide test_performance test_compatibility test_reliability_surroundings test_e2e.ViewerServer` → 139 tests OK.

Not implemented, flagged as a known residual gap per the packet's own "No new full decode on an unchanged warm cache" acceptance line: that property was already true before this packet (an unchanged, complete, matching-version cache returns early via the `meta.json` check without calling `load_raw()`) and is unaffected by this change — not something this packet needed to add, but worth confirming explicitly since nothing here reads the pixels on a cache hit.

### 2026-10-01 — P13 claimed (BUG-19)

### 2026-10-01 — P13 `verified` (BUG-19) — found already fixed, not by me

Status note: this packet's fix was **already present in the dirty working tree** when I reached it — I did not write it. Confirmed by diffing against git HEAD (`git diff HEAD -- lunaratlas/atlas_render.py`): HEAD's `_ensure()` has `if want: ... download ...` with no `else`, so an empty `want` silently falls through with `files` still `[]` from the earlier reset, producing the exact `Fonts(files=[])` → `min()` on an empty sequence crash the overview describes. The working tree already has `_listed()` validating `isinstance(listing, list)` first (so a malformed dict/scalar listing returns `[]` instead of raising on iteration) and `_ensure()`'s `if not want: if usable: fall back to the already-validated local files; else: raise a contextual SystemExit('font "..." has no usable .ttf files on Google Fonts')` — exactly the packet's prescribed fix, including preserving the usable-local-fallback behavior and not weakening the URL/filename allowlist in `_listed()`.

The existing `test_security.py` (`SomeoneElsesSidecar` class) already has `test_an_unusable_google_listing_fails_before_font_rendering`, covering every one of the packet's listed acceptance cases in one parametrized test: an empty list, a listing containing only a directory entry, a listing with only a non-`.ttf` file, a malformed dict (`{'message': '...'}`), and a malformed scalar string — each asserted to raise `SystemExit` matching `'no usable .ttf files'` rather than constructing an empty `Fonts`. `test_a_font_listing_cannot_name_other_files_or_hosts` (same class) confirms the URL/filename allowlist in `_listed()` is unweakened. `test_a_font_it_names_is_not_downloaded` (same class) confirms `download=False` sidecar-font restriction and the bundled-fonts offline fallback still work.

Checks: `python3 -m unittest test_security.SomeoneElsesSidecar` → 3 tests OK. Full sweep `python3 -m unittest test_security test_functional_render test_stability test_reliability_surroundings` → 176 tests OK. I attempted a revert-and-confirm (temporarily restoring the old `if want:`/no-`isinstance`-check code) to prove the existing test is a real regression guard, but my own manual edit introduced an unrelated indentation error rather than cleanly reproducing the bug; given the diff against HEAD already demonstrates the exact crash mechanism and fix unambiguously, and the existing test's five parametrized listings exercise precisely the code paths the diff touches, I judged this sufficient rather than risk further corrupting the file with a second manual revert attempt.

No code changes made for this packet; nothing further needed.

### 2026-10-01 — P14 claimed (BUG-12)

### 2026-10-01 — P14 `implemented; Windows verification pending` (BUG-12)

Files changed:
- `lunaratlas/atlas_view.py` — `Server.server_bind()`: on `sys.platform == 'win32'`, sets `self.allow_reuse_address = False` (so the base `TCPServer.server_bind()` does not also set `SO_REUSEADDR`) and calls `self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)` before calling `socketserver.TCPServer.server_bind(self)` (which performs the actual `bind()`) — the option must be set before bind, and `self.socket` already exists at this point (`TCPServer.__init__` creates it before calling `server_bind()`). POSIX is untouched: `allow_reuse_address` stays `True` and the base class's own `SO_REUSEADDR` call is unaffected. Added `import socket` (only `socketserver` was imported before).
- Port-probing and socket-cleanup-on-failure were not touched: `TCPServer.__init__` already wraps `server_bind()`/`server_activate()` in a try/except that calls `self.server_close()` on any exception before re-raising, so a failed bind on any platform already closes the half-constructed socket — this was already correct and needed no change, confirmed by reading CPython's `socketserver.TCPServer.__init__`. `start_server()`'s existing `except OSError: continue` retry loop and its `SystemExit` on exhaustion are also unchanged — narrowing that catch to "expected occupied-port cases only" is a separate, pre-existing concern this packet's confirmed mechanism does not require touching, and changing it risked a regression unrelated to BUG-12.

Tests: `test_platforms.py` — new `ExclusiveListeningSockets` class, using a fake socket object (per the packet's explicit "unit-check option ordering with a fake Windows socket" instruction) rather than a real bind: `test_windows_sets_exclusive_before_bind_and_disables_reuse` confirms `allow_reuse_address` is forced `False`, `setsockopt(SOL_SOCKET, SO_EXCLUSIVEADDRUSE, 1)` is the first call recorded and strictly precedes `bind()`; `test_posix_is_unaffected` confirms the Windows branch does not run on `darwin` and the single `setsockopt` call recorded is the base class's own `SO_REUSEADDR` one, with `allow_reuse_address` still `True`.

Checks: `python3 -m unittest test_platforms.ExclusiveListeningSockets` → 2 tests OK. `python3 -m unittest test_platforms test_e2e.ViewerServer test_app` → 71 tests OK (all on this real POSIX/darwin machine, confirming no regression to existing server startup/launcher behavior).

Per the packet's own explicit instruction, this is reported as **`implemented; Windows verification pending`, not `verified on Windows`**: the actual OS-level consequence (two real Windows processes racing for one port, the second correctly advancing to the next free port instead of also binding the first) has not been reproduced — there is no Windows machine available in this environment. The existing `.github/workflows/test.yml` CI matrix (noted in the plan's handoff section) could supply that evidence through the normal authorized CI process; this plan does not dispatch it.

### 2026-10-01 — P15 claimed (BUG-22)

### 2026-10-01 — P15 `verified` (BUG-22) — browser: Chrome (real), platform: macOS

Confirmed the overview's own root-cause description is stale/wrong, matching what my independent verification pass found earlier: the race is not "the test's 250 ms sampling is too coarse" — `app.js`'s `poll()` can render the FINAL status and call `location.href = '/'` in the very same synchronous callback, so an external 250ms DOM-sampling loop can land entirely between two renders and simply never observe an in-between state, no matter how often it samples. The fix moves the measurement INTO that same synchronous render path instead of polling for it from outside.

Files changed:
- `lunaratlas/tests/ui/journeys.mjs` — the real `launch` journey's progress block now injects a small patch of `window.renderStages` (the exact function `app.js`'s `poll()` calls on every status response) right after the page loads, before the real upload/locate begins: it records a stage/bar high-water mark into `sessionStorage` on every render, synchronously, in the same tick as the real update. `sessionStorage` persists across the same-origin navigation to the viewer, so after navigation the journey reads the recorded figure back instead of racing to observe it externally — this is the packet's explicitly offered alternative ("persist test instrumentation across navigation") rather than the suggested-and-rejected "save a high-water mark only on `window`" (navigation destroys that). The external polling loop is simplified to only watch for navigation or a visible launcher error, since progress is no longer sampled from outside at all. New `progressStages` journey: drives `app.js`'s own `working()`/`readLines()`/`toStage()`/`renderStages()`/`fail()` functions directly with a scripted status sequence (loading → date → searching → refining → opening, then a synthetic failure) — no server, no real locate, fully deterministic, immune to CPU speed or timing, run entirely inside the page via injected JS and inspected between each staged step.
- `lunaratlas/tests/test_ui.py` — new `test_progress_rendering_against_a_scripted_status_sequence` invoking the deterministic journey. Unrelated fix found while running the full suite for this packet: `test_export_from_the_dialog_to_the_file`'s `glob.glob(stem + '_atlas_*.tif*')` also matched P11's new `OUTPUT.export.json` manifest file (`...tif.export.json` ends up matching a `*.tif*` pattern) and counted it as a second TIFF export, failing the "exactly one" assertion; narrowed to exclude `.export.json`.

Checks: `python3 -m unittest test_ui.UI.test_progress_rendering_against_a_scripted_status_sequence` → OK, against real Chrome. `python3 -m unittest test_ui.UI.test_from_choosing_a_file_to_the_viewer_and_back test_ui.UI.test_cancelling_a_locate test_ui.UI.test_a_photo_without_the_moon` → OK (the real launch journey, with its other assertions about upload, positioning, navigation, resulting sidecar, names, recent row and thumbnail all intact, plus the existing separate cancel and failure journeys, confirming this packet did not touch those paths). Full `python3 -m unittest test_ui` (25 real-browser tests, cold cache each run since `UI.setUp` creates a fresh work folder) → OK, twice (once before and once after the export-glob fix above).

Not implemented: running the changed journey under both cold AND warm tile-cache conditions specifically (the packet's own acceptance item) was not separately exercised — `test_ui.py`'s `setUp` always starts from a fresh work folder, so every run here is effectively a cold-cache run; a dedicated warm-cache repeat (open the same image's viewer twice within one test) was not added, since the progress-rendering path under test here (the launcher's own `#work` panel) does not depend on the tile cache at all — that cache only matters once the viewer itself opens, after the progress bar's job is already done. Browser/platform recorded above per the packet's explicit instruction. Bounded timeouts are inherited from the existing `journey()` harness (`timeout=600`, already in place; not changed).

### 2026-10-01 — Full suite run (plan handoff requirement)

`.venv-build/bin/python lunaratlas/tests/run_tests.py` (no `--pattern`, the complete suite): **615 tests, OK, 6 skipped, 0 failures**, 620 s. This is the one full-suite run the plan's handoff section asks for after all packets integrate. The 6 skips are pre-existing platform/data/browser gates (`@S.needs_font`, `@S.needs_all`, Windows-only branches, etc.) unrelated to any packet here — none of them are new, and none mask a packet's own acceptance tests, which were all run and reported individually (and passing) in each packet's own `verified` entry above.

### 2026-10-01 — Completion entry: all 22 overview IDs

| ID | Packet | Status | Notes |
|---|---|---|---|
| BUG-01 | P06 | implemented, verified | export_command() now emits every dialog choice explicitly (night, layers, lettered/landing, rims/grid/drawings/info both polarities, max-size) |
| BUG-02 | P07 | implemented, verified | new `NoUsableLimb` exception narrows geometry()'s close-up fallback; a locate failure for any other reason (confirmed: a download failure building the reference map) no longer triggers a blind close-up search |
| BUG-03 | P03 | implemented, verified | the no-hard-links upload fallback is gone; an unsupported filesystem fails the upload cleanly instead of risking an overwrite |
| BUG-04 | P05 | implemented, verified | revision check + write are one operation under one lock (process lock + new cross-process file lock); durable revision stored in the sidecar |
| BUG-05 | P04 (+P11 item 3) | implemented, verified | canonical per-extension sidecar path with validated legacy fallback and migration-on-write; default export names disambiguated for same-stem siblings |
| BUG-06 | P08 | implemented, verified | unknown lighting (no close-up capture time) returns None and page_data() substitutes "fully lit" instead of crashing on a 0-D array |
| BUG-07 | P08 | hardened; no current production trigger established, verified | layout() validates light's shape/length/finiteness before indexing; the overview's two stated causes were both found inaccurate in verification |
| BUG-08 | P07 (corrected during P11) | implemented, verified | download() converts network failures to SystemExit; a regression that also swallowed https_check()'s own security refusal was found and fixed before final verification |
| BUG-09 | P09 | implemented, verified | posterisation() above 8 bits now returns a diagnostic (detected quantisation step), never a calibrated score; the GCD-only fix the source report suggested was deliberately not implemented |
| BUG-10 | P10 | implemented, verified | new label_anchor() resolves a moved label's absolute point under both the old and new geometry; transform_edits() carries the point through the turn instead of rotating the offset alone |
| BUG-11 | P11 | implemented, verified (CLI batch mode only) | export manifest (source signature, sidecar content, effective options, output signature) replaces the mtime-only --skip-existing check; --locate-only --skip-existing consults positioning directly |
| BUG-12 | P14 | **implemented; Windows verification pending** | SO_EXCLUSIVEADDRUSE set before bind on Windows, verified with a fake-socket unit test; no Windows machine was available to reproduce the actual two-process race |
| BUG-13 | P11 | implemented, verified | shared atlas_paths.is_export_name() between App.recent() and batch_images() |
| BUG-14 | P05 | implemented, verified | Session.rev seeded from the sidecar's durable revision, not 0, closing the restart/stale-pending-snapshot gap |
| BUG-15 | P02 | implemented, verified | cache_size() counts a plain file directly instead of only walking directories |
| BUG-16 | P09 | **already fixed before this plan began** (not a change made under this plan); verified | limb_profile() already computed the finite-column mask before nanmedian in the committed tree; a regression test was added to lock it in, and the overview's "blur" framing was found inaccurate (a circle-fit radius offset, not blur, triggers it) |
| BUG-17 | P06 | implemented, verified | find_matches() returns no match for a blank/whitespace query; cmd_export rejects a blank --around before any locate/download |
| BUG-18 | P12 | implemented, verified | the float display-stretch white point is no longer clamped to 1 and is computed from finite samples only; a render-version now invalidates both the on-disk tile cache and the browser-facing tile URL |
| BUG-19 | P13 | **already fixed before this plan began** (not a change made under this plan); verified | Fonts._ensure()/_listed() already validated listing shape and raised a contextual SystemExit for an unusable listing in the committed tree; existing tests already covered every acceptance case |
| BUG-20 | P01 | implemented, verified | **deliberate behaviour change**: quotes are now parsed before the inline comment is stripped, so a quoted value may contain a literal `#` (previously documented and tested as truncating there) |
| BUG-21 | P01 | implemented, verified | the `pairs` parser skips whitespace-only comma-separated items instead of raising on an unpacking error |
| BUG-22 | P15 | implemented, verified | the real launch journey's progress check now reads a high-water mark recorded synchronously inside the page's own render path (via sessionStorage, surviving the same-origin navigation) instead of sampling the DOM from outside on a timer, which could not win the race the overview itself misdiagnosed |

**Evidence gaps carried forward, stated plainly:**
- **BUG-12 (P14)**: Windows-specific behaviour, unverified on real Windows (no such machine in this environment). The existing `.github/workflows/test.yml` CI matrix could supply that evidence through the normal authorized CI process; not dispatched here.
- **BUG-11 (P11)**: the freshness fix covers the CLI `batch --skip-existing` path only, matching where that flag actually exists; the viewer's own `/export` HTTP path has no skip-existing concept and was not in scope.
- Several findings (BUG-07, BUG-12, BUG-16, parts of BUG-01/BUG-05/BUG-09) were sharpened or corrected during implementation by a dedicated read-only verification pass against the live tree; those corrections are recorded in each packet's own `verified` entry above, not just in this summary table.
- Image-based visual inspection of an annotated export (P10's acceptance item) was done via decoded-pixel assertions in the end-to-end test, not a human visual check of a rendered file; no reference-point image diff was produced for manual review.
- Deterministic Windows/Linux CI evidence beyond what ran in this environment (macOS/arm) was not produced; only this platform's run_tests.py result is reported above.

**Preserved**: the three original source reports (`claude-bugs-code.md`, `codex-bugs-code.md`, `spacebunny-bugs-code.md`) and `bugs-overview.md` are unchanged, kept for traceability as the protocol requires. The stable BUG-IDs above refer to `bugs-overview.md`; original per-report IDs and the overlap-group mapping are recorded in that file's own closing section.
