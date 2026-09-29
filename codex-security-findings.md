# LunarAtlas security findings

Reviewed: 2026-09-29  
Scope: the current `lunaratlas/`, `packaging/`, `.github/`, configuration, and the included quality-label experiment. This was a source-assisted review of the on-disk worktree. Existing worktree changes were not modified.

## Summary

| Severity | Count |
| --- | ---: |
| Medium | 3 |
| Low | 3 |

The production viewer is deliberately loopback-only, and it correctly rejects non-local `Host` values and cross-origin `POST`s. The main gap is that a sensitive response is still usable as a cross-origin JavaScript include. The separate, experimental labelling server has neither of those protections. The app also has unsafe predictable temporary-file handling and an unpinned release supply chain.

## Findings

### SEC-001 — Cross-origin script inclusion leaks the open image's absolute path and metadata

**Severity:** Medium  
**Affected code:** `lunaratlas/atlas_view.py:388-396`, `lunaratlas/atlas_view.py:406-425`, `lunaratlas/atlas_view.py:491-506`, `lunaratlas/atlas_view.py:136-161`

`/data.js` is served as `text/javascript` and contains `window.ATLAS = ...`. Its payload includes the open image's absolute path, filename, geometry, quality data, and visible-feature metadata. The local-origin check permits a request with no `Origin` header. A normal cross-origin classic `<script src="http://localhost:PORT/data.js">` request is a no-CORS GET and does not need to expose an `Origin` header; it is executed in the embedding site's origin. An attacker-controlled website can probe the documented 8766–8785 port range while the viewer is open and read `window.ATLAS` from its own page.

This defeats the intended “only this machine's pages” boundary for this endpoint. It does not expose the original pixels directly, but the local file path is sensitive and the endpoint is a foothold for future data added to `ATLAS`.

**Remediation:** Do not expose private state as executable JavaScript. Serve it as `application/json` and fetch it from the same-origin viewer page. Require an unguessable per-server capability token for every route that reveals data or changes state (preferably in a fragment-derived request header, not only in a URL). Also reject absent/mismatched `Origin` for browser-facing routes where practical, and add a restrictive CSP. `X-Content-Type-Options: nosniff` alone is not enough while the resource is intentionally JavaScript.

### SEC-002 — Experimental label server permits CSRF writes to `labels.json`

**Severity:** Medium  
**Affected code:** `lunaratlas/experiments/quality/label_server.py:39-52`, `lunaratlas/experiments/quality/label_server.py:89-109`, `lunaratlas/experiments/quality/label_server.py:117-119`

The experiment runs an unauthenticated HTTP server on `127.0.0.1` and accepts any `POST /labels.json`. It validates neither `Host`, `Origin`, nor `Content-Type`; JSON sent as the CORS-safelisted `text/plain` type is accepted. A malicious page can therefore issue a cross-site simple POST that adds, replaces, or removes arbitrary labels whenever the researcher has the tool running. The response need not be readable for this state-changing CSRF attack to succeed. Browser private-network protections reduce exposure in some configurations, but are not a portable authorization control (notably across all supported browsers and local contexts).

**Remediation:** Reuse the production server's loopback Host and strict Origin validation, and add a per-run random CSRF/capability token which must be present on every mutating request. Require `Content-Type: application/json`, limit the request size, return the appropriate security headers, and document that the server is for trusted local use only.

### SEC-003 — Experimental label page has stored DOM XSS through image filenames

**Severity:** Medium  
**Affected code:** `lunaratlas/experiments/quality/survey_quality.py:97-103`, `lunaratlas/experiments/quality/label_server.py:19-36`, `lunaratlas/experiments/quality/label_page.html:139-141`, `lunaratlas/experiments/quality/label_page.html:202-203`

`survey_quality.py` persists the input path, and the server turns its basename into `item.name`. The page inserts that value into `innerHTML` twice without escaping: once in the metadata panel and once in the thumbnail `title` attribute. A supplied image named, for example, `<img src=x onerror=...>.jpg` becomes executable markup when the survey is labelled. Script execution has the label-server origin and can alter labels or read the survey data and gallery that the page serves.

**Remediation:** Build these nodes with `textContent` and DOM APIs, or HTML-escape the filename for both element text and attribute contexts. Treat `quality.json` as untrusted input, apply a CSP that disallows inline script/event handlers, and add a regression test using an HTML-bearing filename.

### SEC-004 — Predictable temporary paths follow attacker-created symlinks

**Severity:** Low  
**Affected code:** `lunaratlas/atlas_app.py:151-167`, `lunaratlas/atlas_app.py:273-277`, `lunaratlas/atlas_geo.py:180-203`, `lunaratlas/atlas_geo.py:206-222`, `lunaratlas/atlas_view.py:54-101`, `lunaratlas/experiments/quality/label_server.py:98-108`

Several writes use predictable sibling names such as `DEST.part`, `ROOT.part.EXT`, and `labels.json.part`, then open them normally for writing. Normal `open(..., 'wb')` follows symlinks. A competing local process that can place a symlink at one of these predictable paths can redirect a download/upload/cache/sidecar write to another file writable by the LunarAtlas user; in the upload case it can truncate that file before the later `os.replace`.

This is a same-user/local-adversary issue, so it is not privilege escalation by itself, but it can corrupt arbitrary user-writable files and invalidates the claimed atomic-write safety under hostile filesystem conditions.

**Remediation:** Create temporary files with `tempfile.NamedTemporaryFile` or `mkstemp` in the destination directory, using restrictive permissions and an unpredictable name; close/fsync as needed and atomically replace only after validation. On platforms where it is available, use no-follow semantics and verify ownership/type before replacing. Apply one safe helper consistently rather than hand-constructing `.part` paths.

### SEC-005 — Local HTTP request bodies and uploaded files have no size limits

**Severity:** Low  
**Affected code:** `lunaratlas/atlas_view.py:450-452`, `lunaratlas/atlas_app.py:133-167`, `lunaratlas/atlas_app.py:321-340`

`Handler.body()` trusts `Content-Length` and reads the declared JSON payload into memory in one operation. The launcher upload endpoint accepts any non-negative-sized body and streams it to disk without a configured maximum, content-type check, image preflight, or post-write quota. It later passes the file to OpenCV/Pillow. Any local client that can reach the loopback port can consume RAM, disk, and CPU with an oversized request or decompression-heavy image. This is especially relevant because the service intentionally remains open for the lifetime of the viewer/app.

**Remediation:** Set explicit, documented limits for JSON requests, upload bytes, decoded pixel count, and concurrent work. Reject absent, negative, or oversized `Content-Length` values before reading; enforce a streaming byte counter for chunked/partial input; validate the image dimensions before expensive processing; and return `413 Payload Too Large`. Use a configured limit high enough for supported mosaics rather than an implicit unlimited policy.

### SEC-006 — Release inputs are mutable and unauthenticated

**Severity:** Low  
**Affected code:** `requirements.txt:2-4`, `packaging/requirements-build.txt:1-5`, `.github/workflows/build-app.yml:29-34`, `.github/workflows/build-app.yml:53`, `.github/workflows/build-app.yml:68`

The release workflow installs dependencies from broad lower-bound requirements and does not use a lockfile or `--require-hashes`. It also references GitHub Actions by mutable major tags (for example, `actions/checkout@v4`) rather than commit SHAs. A later package release, registry/account compromise, or action-tag retarget can change the code that builds a signed/published desktop artifact without a corresponding source change in this repository.

**Remediation:** Commit a reviewed, fully pinned lockfile with hashes for runtime and build dependencies; install it with hash enforcement in CI. Pin third-party GitHub Actions to immutable full commit SHAs and maintain them through an automated updater with review. Consider generating an SBOM and signing/provenance-attesting release artifacts.

## Checks performed and notable non-findings

- Searched production, packaging, workflow, and experimental source for embedded credentials, shell injection sinks, unsafe deserialization, unsafe archive extraction, path traversal, and DOM injection sites. No committed secret was found. The ignored local `.env` was deliberately not opened.
- Confirmed the production server binds to `127.0.0.1` (`lunaratlas/atlas_view.py:491-502`), validates the Host header, and checks `Origin` on POSTs. Command construction uses argument arrays rather than a shell (`lunaratlas/atlas_view.py:280-317`).
- The gazetteer ZIP extraction was tested with a `../` member on the installed Python version; `zipfile.extractall` normalized it under the target directory, so no Zip Slip finding was recorded.
- Ran `uvx --from pip-audit pip-audit -r requirements.txt`: **no known vulnerabilities found** for the resolved runtime packages at review time. This does not remedy the absence of reproducible/pinned release inputs described in SEC-006.
