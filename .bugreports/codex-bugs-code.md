# Code inspection bugs

Inspection of the 2026-10-01 working tree. Findings are recorded when verified. Severity describes user impact; the report contains bugs, not proposed code changes.

## BUG-001 — Medium — Thumbnail files escape the cache limit

**Location:** `lunaratlas/atlas_view.py:53-58`, `lunaratlas/atlas_view.py:61-105`, `lunaratlas/atlas_app.py:319-327`.

`cache_size(path)` sums files returned by `os.walk(path)`. This works for tile directories, but `evict_cache()` also passes individual thumbnail JPEG files to it. `os.walk()` yields nothing for a file, so each thumbnail contributes zero bytes to `total`. The launcher creates thumbnails and calls `evict_cache()`, but their accumulated size can never trigger the 2 GiB limit. A direct probe with a 1,024-byte temporary file returned `cache_size(file) == 0`.

**Suggested fix:** Count a regular file with `os.path.getsize(path)` before walking directories, and cover mixed tile-directory/thumbnail-file eviction with a regression test.

## BUG-002 — Medium — Batch skips exports after viewer edits change

**Location:** `lunaratlas/lunaratlas.py:409-455`, `lunaratlas/lunaratlas.py:509-515`.

`cmd_export()` reads drawing, hidden-name, label, and font changes from `IMAGE.atlas.json`, but `batch --skip-existing` compares the existing export's modification time only with the source image. Save a viewer edit after exporting, then rerun `batch --skip-existing`: the source image is unchanged, so the command reports `skipped` and leaves an export without the new edit. The same check can reuse an export after output options change.

**Suggested fix:** Make the skip decision depend on the sidecar's modification time and an output-option fingerprint (or retain an export manifest with input signatures and options).

## BUG-003 — High — Upload fallback can overwrite another concurrent upload

**Location:** `lunaratlas/atlas_app.py:190-220`.

When `os.link(tmp, dest)` fails because hard links are unavailable, `place()` checks `not os.path.lexists(dest)` and then calls `publish(tmp, dest)`, which uses `os.replace`. Two uploads with the same name can both pass the existence check and both return the same destination; the later replace silently destroys the earlier photo. A controlled two-thread probe forced `os.link` to fail and synchronized the existence checks: both calls returned `same.png`, while only the second payload survived.

**Suggested fix:** Claim a destination exclusively on the fallback path (for example, create it with `O_CREAT | O_EXCL` and copy into the claim) or fail clearly when atomic no-replace publication is unavailable. Do not use `os.replace` after a separate vacancy check.

## BUG-004 — High — An older edit save can overwrite a newer one

**Location:** `lunaratlas/atlas_view.py:756-769`, `lunaratlas/atlas_view.py:377-394`.

The `/edits` handler checks and advances `s.rev` under `s.lock`, releases that lock, and then reacquires it inside `write_edits()`. If request A (revision 1) passes the first lock and pauses, request B (revision 2) can pass and write its edits first. A then writes its older edits and both requests return success. The sidecar ends with revision 1's content while the session advertises revision 2. This is a source-confirmed interleaving in the current handler; the lock does not span check and write.

**Suggested fix:** Perform the revision check, sidecar write, and revision update as one operation under the same lock. Advance the revision only after a successful write.

## BUG-005 — High — Pending browser edits can replace newer saved edits after restart

**Location:** `lunaratlas/atlas_view.py:503-505`, `lunaratlas/atlas_view.py:665-666`, `lunaratlas/viewer/viewer.js:143-155`, `lunaratlas/viewer/viewer.js:1289-1301`.

The edit revision lives only in `Session.rev` and starts at zero for every new session. A tab stores an unsent snapshot in `localStorage` when it closes. If another tab later saves newer sidecar edits, then the server restarts, reopening the first tab compares its old snapshot revision with the reset server revision of zero. It replays the old snapshot and overwrites the newer edits. The code does not compare the snapshot with a revision or timestamp persisted alongside the sidecar edits.

**Suggested fix:** Persist a monotonic edit revision with the sidecar and compare pending snapshots against that persisted version before replaying; resolve divergent edits explicitly.
