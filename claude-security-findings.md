# LunarAtlas — Security Findings

Prepared by **Claude** (Claude Code) on 2026-09-29.
Inspection only: no source files were changed to produce this report.

## Scope and method

- **Code reviewed:** the working tree on branch `desktop-app`: all of `lunaratlas/` (CLI, localhost server, launcher,
  viewer front end, experiments), `tool_settings.py`, `packaging/`, `.github/workflows/` and the `.env` handling. The
  committed `moon_atlas/` tree (still on `main`) was compared against it where the difference matters.
- **Method:** a manual read of every request handler, subprocess call, download, file write and HTML sink, followed by
  live probes against a throwaway instance of the real `atlas_view` server (findings 2 and 3 were reproduced this way).
- **Threat model:** a single-user desktop app with a `127.0.0.1` HTTP server. The attackers considered are:
  - a malicious website open in the same browser while the app runs, including DNS rebinding;
  - another local user or process;
  - a compromised or intercepted download source;
  - an image and `.atlas.json` sidecar received from someone else;
  - the CI and release pipeline.

## Summary

| # | Severity | Finding | Where |
|---|---|---|---|
| 1 | **High** (published `main` only) | The released viewer has no Host/Origin checks, so any website can rewrite edits and start exports (CSRF, DNS rebinding) | `moon_atlas/atlas_view.py` at `HEAD` |
| 2 | **Medium** | `HEAD` requests bypass the Host/Origin guard and reveal whether any file exists, with its size and date | [atlas_view.py:360](lunaratlas/atlas_view.py#L360) |
| 3 | **Medium** | Any website can load `/data.js` with a `<script>` tag and read the photo's full path (username), name and positioning | [atlas_view.py:424](lunaratlas/atlas_view.py#L424) |
| 4 | **Medium** (shared machines) / Low | No authentication on the localhost API: any local user or process can drive it | [atlas_view.py:388](lunaratlas/atlas_view.py#L388) |
| 5 | **Medium–Low** | Downloaded reference data and fonts have no integrity pinning | [atlas_geo.py:180](lunaratlas/atlas_geo.py#L180), [atlas_names.py:63](lunaratlas/atlas_names.py#L63), [atlas_render.py:82](lunaratlas/atlas_render.py#L82) |
| 6 | **Low** | No security headers (CSP, `frame-ancestors`, `nosniff`, CORP), so the pages can be framed (clickjacking) | [atlas_view.py:370](lunaratlas/atlas_view.py#L370) |
| 7 | **Low** | Request bodies and uploads have no size limit; a negative `Content-Length` makes a handler wait | [atlas_view.py:450](lunaratlas/atlas_view.py#L450), [atlas_app.py:133](lunaratlas/atlas_app.py#L133) |
| 8 | **Low** | A sidecar from someone else can trigger font downloads and very heavy drawing work | [lunaratlas.py:305](lunaratlas/lunaratlas.py#L305), [atlas_render.py:542](lunaratlas/atlas_render.py#L542) |
| 9 | **Low** | CI/CD hardening: token permissions, action pinning, unpinned build dependencies, unsigned releases | `.github/workflows/`, `packaging/` |
| 10 | **Low** (developer tool) | The experiments labelling server has no Host/Origin checks, and its page puts file names into `innerHTML` | [label_server.py](lunaratlas/experiments/quality/label_server.py) |
| 11 | Info | Smaller hardening items | various |

---

## 1. The published viewer accepts requests from any website (High, `main` only)

**Where:** `moon_atlas/atlas_view.py` at `HEAD` / `origin/main` (commit `5db5268`), lines 340–400.

**What:** The released server has no Host allowlist and no Origin check. `do_POST` parses the body as JSON whatever
its `Content-Type`. That makes `/edits`, `/export` and `/reveal` reachable from any web page with a "simple" request
(`fetch(url, {method: 'POST', mode: 'no-cors', body: '{…}'})`), which needs no CORS preflight.

**Impact:** While someone has `moon_atlas.py view` running, any site they visit can:
- replace or erase all their viewer edits: drawings, hidden names and moved labels, stored in `IMAGE.atlas.json`;
- start exports that overwrite earlier `_atlas` files;
- read everything through DNS rebinding.

The default port (8766) is predictable.

**Status:** Fixed in the working tree by `Handler.local()` ([atlas_view.py:388](lunaratlas/atlas_view.py#L388)), which
the probes confirmed refuses cross-site and `null` Origins. The fix is **not yet committed or released**.

**Recommendation:** Commit and release the `desktop-app` work soon, or backport `local()` to `main`. Consider a short
note in the release that older versions should not be left running.

## 2. `HEAD` requests bypass the guard and reveal files across the disk (Medium)

**Where:** [atlas_view.py:360](lunaratlas/atlas_view.py#L360). `Handler` subclasses `SimpleHTTPRequestHandler` and
overrides `do_GET` and `do_POST`, but not `do_HEAD`.

**What:** The inherited `do_HEAD` skips `local()` and serves the static-file handler's view of the **current working
directory**. On macOS a Finder-launched app starts in `/`. From a terminal, it starts in the folder the command was
run from.

**Evidence** (live probe, working directory `/`, forged `Host: evil.example`):

```
GET  ~/.zshrc          Host=evil.example  -> 403                      (guarded)
HEAD ~/.zshrc          Host=evil.example  -> 200, Content-Length 159, Last-Modified …
HEAD ~/does-not-exist  Host=evil.example  -> 404
HEAD /etc/hosts        Host=evil.example  -> 200, Content-Length 214, Last-Modified …
```

**Impact:** A file-existence, size and modification-time oracle over the whole filesystem. A website can use it
through DNS rebinding, because rebinding is exactly what the Host check exists to stop. Any local process can use it
directly. Examples: whether `~/.ssh/id_ed25519` exists, which apps are installed, the names of other home folders.
File contents are not returned.

**Recommendation:** Base `Handler` on `BaseHTTPRequestHandler` rather than `SimpleHTTPRequestHandler`: nothing uses
the directory-serving behaviour. Alternatively, override `do_HEAD` to apply `local()` and answer 405. Also consider
refusing every method other than GET and POST explicitly.

## 3. Any website can read `/data.js` through a `<script>` include (Medium)

**Where:** [atlas_view.py:424](lunaratlas/atlas_view.py#L424) (`/data.js`) and
[atlas_view.py:158](lunaratlas/atlas_view.py#L158) (`path=os.path.abspath(image)`).

**What:** `/data.js` is executable JavaScript (`window.ATLAS = {…}`). A `<script src>` request carries no `Origin`
header, and the browser sends `Host: localhost:8766` itself. `local()` therefore lets it through, and the script then
runs in the attacker's page.

**Evidence** (a probe with the headers a browser sends for a cross-site script include):

```
GET /data.js  Sec-Fetch-Site: cross-site, Referer: https://evil.example/
  -> 200  window.ATLAS = {"image":"moon.tif","path":"/Users/someone/Pictures/LunarAtlas/moon.tif"};
```

**Impact:** A site open in the same browser learns:
- the local account name (from the path) and the image's file name, which usually carries the capture date and time;
- the image size and full positioning;
- that LunarAtlas is running. This is also visible through `<img src="/tiles/…">` and `/app/thumb` load/error
  events.

Recent Chrome versions may ask the user before a public site can reach `localhost`. Firefox and Safari do not.

**Recommendation:**
- Refuse any request whose `Sec-Fetch-Site` header is present and not `same-origin` or `none`. This is a single check
  in `local()`, and it also covers the tile and thumbnail probes.
- Send `Cross-Origin-Resource-Policy: same-origin` on every response.
- Serve the page data as JSON fetched by the page (`/data.json`) rather than as a script.
- Drop the absolute `path` from the payload, or only send it once the page has proved it is same-origin.

## 4. No authentication on the localhost API (Medium on shared machines, Low otherwise)

**Where:** [atlas_view.py:388](lunaratlas/atlas_view.py#L388). The only guard is `local()`, which accepts any request
without an `Origin` header, as native clients never send one.

**What:** Every other user and process on the machine can reach `127.0.0.1:8766` and use the whole API as the person
who started LunarAtlas:
- `POST /app/upload` writes files into their `~/Pictures/LunarAtlas`;
- `/app/locate`, `/export`, `/edits` and `/app/quit` run jobs, rewrite edits and stop the app;
- `/app/recent`, `/app/thumb` and `/data.js` list and show their photos.

A related gap: `already_running()` ([atlas_app.py:343](lunaratlas/atlas_app.py#L343)) trusts any process that answers
`lunaratlas` on the port. A local process squatting on 8766 would receive the user's uploads.

**Impact:** Small on a single-user Mac. Real on shared Linux machines, lab computers and multi-user Windows.

**Recommendation:**
- Generate a random token per launch.
- Hand it to the window or browser in the URL once (`/app?t=…`), then keep it in an `HttpOnly; SameSite=Strict`
  cookie.
- Require the cookie on every route except the ping.
- Make the ping answer with an HMAC of a nonce, so a second start can tell it is its own instance.

## 5. Downloads have no integrity pinning (Medium–Low)

**Where:** [atlas_geo.py:180](lunaratlas/atlas_geo.py#L180) (`download`), with its callers
[atlas_geo.py:259](lunaratlas/atlas_geo.py#L259) (WAC tiles),
[atlas_closeup.py:109](lunaratlas/atlas_closeup.py#L109) (LOLA),
[atlas_names.py:67](lunaratlas/atlas_names.py#L67) (gazetteer zip) and
[atlas_render.py:85](lunaratlas/atlas_render.py#L85) (Google Fonts through the GitHub API).

**What:** The files come over HTTPS but are only checked structurally: that they decode, have the right size, or are
a zip. The code does not check that they are the expected bytes. Specific points:
- `urllib` follows redirects to plain `http://` (and `ftp://`), so an HTTPS→HTTP redirect upstream would drop
  transport security without notice.
- `zipfile.extractall(GAZ_DIR)` extracts every member. CPython neutralises `..` and absolute paths, but a replaced
  archive could still be a zip bomb or plant extra files in the data folder.
- The font path trusts the GitHub API response. `os.path.join(d, e['name'])` does not reduce `name` to a basename,
  and `e['download_url']` is fetched whatever its scheme or host.
- There is no upper size limit, apart from the LOLA size check, which only runs after the whole download.

**Impact:** A compromised mirror, bucket or API (or a broken TLS path) delivers files that are then parsed by
libtiff/OpenCV, FreeType/Pillow and the dBASE parser. These are memory-unsafe native parsers. The same files also end
up in the viewer and the exports. The fonts are also served to the webview.

**Recommendation:**
- Pin SHA-256 digests for the fixed products: the four WAC tiles and `ldem_16.img` / `ldem_64.img`.
- For the gazetteer, which USGS updates, pin the digest and refresh it on purpose, or at least extract only
  `MOON_nomenclature_center_pts.dbf`.
- Refuse non-HTTPS redirects, for example with a redirect handler that rejects other schemes.
- For fonts:
  - use `os.path.basename(e['name'])`;
  - check that `download_url` is `https://raw.githubusercontent.com/google/fonts/…`;
  - cap the size of each file.

## 6. No security headers, so the pages can be framed (Low)

**Where:** `Handler.reply` ([atlas_view.py:370](lunaratlas/atlas_view.py#L370)). The probe confirmed that `/` has no
`Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options` or `Cross-Origin-Resource-Policy` header.

**What:** Any site can load `http://localhost:8766/` or `/app` in an iframe, because GET navigations carry no Origin
header and the Host is legitimate. The framed page is same-origin with the server, so a clickjacking overlay can make
real, persistent clicks: hide labels, delete drawings, start an export, quit. There is also no CSP to limit the damage
of any future HTML-injection bug.

The viewer currently escapes consistently (`esc()`, `textContent`), so no XSS was found.

**Recommendation:** On HTML responses, send:

```
Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'
X-Frame-Options: DENY
```

On every response, send `X-Content-Type-Options: nosniff`.

The injected inline `<script>` in `page()` ([atlas_view.py:402](lunaratlas/atlas_view.py#L402)) would need a nonce,
or should move into `viewer.js` behind a flag in `data.js`. The launcher page `app.html` also has inline script to
move out or cover with a hash.

## 7. Request bodies and uploads have no size limit (Low)

**Where:** [atlas_view.py:450](lunaratlas/atlas_view.py#L450) (`body()`) and
[atlas_app.py:133](lunaratlas/atlas_app.py#L133) (`upload`).

**What:**
- `body()` reads whatever `Content-Length` says into memory. A negative value becomes `rfile.read(-1)`, which blocks
  the thread until the client disconnects.
- Deeply nested JSON raises `RecursionError`, which is not caught.
- The upload streams any size to disk.
- The server sets no socket timeouts, so slow clients hold threads open.

**Impact:** A local denial of service (memory, threads, disk), reachable only by local processes because of the
Host/Origin guard.

**Recommendation:**
- Reject a negative or missing `Content-Length`.
- Cap JSON bodies at about 16 MB (the edits payload), and catch `RecursionError` alongside `ValueError`.
- Cap uploads at a generous limit, for example 4 GB, and check free disk space first.
- Set `timeout` on the handler.

## 8. A sidecar from someone else is trusted input (Low)

**Where:** [lunaratlas.py:305](lunaratlas/lunaratlas.py#L305) (edits read at export),
[atlas_render.py:542](lunaratlas/atlas_render.py#L542) (`clean_shape`).

**What:** People share images with their `.atlas.json`. At export time the sidecar's `edits.style.font` and any
shape's `font` go into `Fonts(family)`, which searches for and downloads an arbitrary Google Fonts family from GitHub.
The slug is sanitised, so there is no path traversal, but the network requests are unexpected. `clean_shape` allows
5 000 shapes of up to 10 000 points each (50 million points), enough to stall the viewer and the export.

**Recommendation:**
- Take per-drawing fonts only from the bundled families, or ask before downloading one a sidecar names.
- Cap the total number of points across all shapes (for example 200 000).

## 9. CI/CD and release hardening (Low)

**Where:** `.github/workflows/*.yml` and `packaging/`.

- **Token permissions:** `build-app.yml` grants `permissions: contents: write` to the whole workflow, including the
  four build jobs. Only `release` needs it.
- **Default permissions:** `test.yml` and `browsers.yml` declare no `permissions:` and so get the repository default.
  Add `permissions: contents: read` at the top of each.
- **Action pinning:** actions are pinned to major tags (`actions/checkout@v4`, …). Pin them to commit SHAs, at least
  in the workflow that publishes releases.
- **Build dependencies:** `requirements.txt` and `packaging/requirements-build.txt` use only lower bounds
  (`pyinstaller>=6.16`, `pywebview>=6.2`, `opencv-python-headless>=4.11,<5`, …). Release builds are therefore not
  reproducible and take whatever PyPI serves that day. Use a lock file with hashes (`pip-compile --generate-hashes`,
  then `pip install --require-hashes`) for the build workflow.
- **Signing:**
  - Windows installers are never Authenticode-signed.
  - macOS signing and notarisation are optional and off by default, so users are taught to click through
    Gatekeeper and SmartScreen.
  - `codesign --deep` is deprecated for signing: sign nested code individually, or let PyInstaller's `codesign_identity`
    do it.
- **Checksums:** publish SHA-256 checksums with the draft release.

## 10. The experiments labelling server is unguarded (Low, developer tool)

**Where:** [label_server.py](lunaratlas/experiments/quality/label_server.py) and
[label_page.html](lunaratlas/experiments/quality/label_page.html).

**What:** This server has none of the viewer's protections:
- **No Host or Origin check.** Any website can `POST` a `text/plain` body to `http://localhost:8765/labels.json` and
  overwrite the calibration labels, and DNS rebinding exposes the gallery.
- **Unescaped file names.** The page puts file names into `innerHTML` without escaping (`${t.name}` at lines 139–140
  and in `title="${t.name}"` at line 202), so a crafted image file name in the survey folder runs script.

**Recommendation:** Reuse `atlas_view.Handler.local()` and an `esc()` helper, or keep the tool out of the published
tree.

## 11. Informational

- **Export argument injection is blocked only by argparse.**
  - **What:** In [atlas_view.py:293](lunaratlas/atlas_view.py#L293), `--around` is followed by a name that comes from
    the page. Names starting with `-` (`--output=…`, `-o…`, `--help`) were tested and argparse refuses them.
  - **Recommendation:** Pass `f'--around={name}'` so the safety does not depend on argparse's handling of dashes.
- **Test hooks in production.** The `/selftest` route and `window.__atlas` are available in every build. They are
  harmless today, because the packaged app has no `tests/` folder, but they are worth gating behind a test flag.
- **Log file.** `lunaratlas.log` in the app data folder ([launcher.py](packaging/launcher.py)) is appended to forever
  and records full paths. Rotate it or cap its size.
- **Cache permissions.** Cache and work files are created with the default umask. On Linux with a world-readable home,
  the tile pyramid and thumbnails of the user's photos are readable by other local users. Consider `0700` on the
  cache and data folders.
- **`.env`.** `.env` holds the precise observing site. It is correctly gitignored and has never been committed
  (verified in the git history). No secrets were found in the tracked files.
- **`install.sh`.** `install.sh` builds the `Exec=` line with `sed "s|…|…$dest…|"`. A `|` or `&` in the path would
  corrupt it, and paths with spaces are not quoted as the desktop-entry spec requires. This is a robustness issue
  rather than an exploitable one.

---

## Controls that were checked and hold up

- **Localhost only.** The server binds `127.0.0.1` only, never `0.0.0.0`.
- **GET and POST guard.**
  - The Host allowlist stops DNS rebinding for GET and POST.
  - The Origin check refuses cross-site and `null` Origins (probed).
- **Export command.**
  - Export options are allowlisted or clamped (format, layers, night, font, numeric ranges).
  - The command runs as an argv list with no shell.
  - Output names are sanitised to `[\w.-]`.
- **Launcher file access.**
  - `/app/locate`, `/app/open` and `/app/thumb` are confined to the work folder through `realpath` plus a directory
    comparison, so symlinks out of the folder are refused.
  - Upload names are reduced to a basename, sanitised, and limited to image extensions.
- **Static routes.** The tile and font routes are regex-bound with `..` refused. No path traversal was found.
- **Viewer and launcher pages.** Server data reaches HTML only through `esc()` or `textContent`. No XSS sink was found
  in `viewer.js`, `app.html` or `friendly.js`.
- **Saving edits.** Sidecar edits are re-validated by type and length on save (`clean_edits`) and again at export
  (`clean_shape`).
- **Sidecar geometry.** Geometry is shape- and finiteness-checked (`Geometry.from_dict`).
- **Parsers.** The dBASE parser bounds-checks its header against the file length. JSON errors are caught everywhere a
  sidecar is read.
- **Image size.** Export sizes are cut to the image bounds and never upscaled, so no memory blow-up comes from the
  dialog's numbers.
- **Code execution.** No `eval`, `pickle`, `shell=True` or dynamic imports of user data anywhere.
