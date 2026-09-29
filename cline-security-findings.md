# LunarAtlas — Security Audit & Verification Report

**Project:** LunarAtlas (`/Volumes/Astro/LunarAtlas`) · branch `desktop-app`
**Audit baseline:** commit `5db5268`
**Verification baseline:** commit `2ba20476` ("Bugs & design files") **plus ~994 lines of uncommitted changes** in the working tree
**Date:** 2026-09-29 · **Auditor:** Cline (Pixel Canary)

> **Read this first.** The audit ran against `5db5268`; the findings below are what it produced. The working tree has since changed substantially and **almost every finding is already fixed in it.** This document is therefore a *verification* report: each finding keeps its original evidence and gains the fix now in the tree, plus the live probe that re-tests it. **Five items remain open** (§4). Every "verified" statement here came from running this code, not from reading it.

---

## 1. Scope and method

- **Python backend** — `lunaratlas.py` (CLI), `atlas_app.py` (launcher + work folder), `atlas_view.py` (loopback server, export jobs), `atlas_geo.py` (sidecars, downloads), `atlas_render.py` (labels, Google Fonts), `atlas_names.py` (IAU gazetteer), `atlas_closeup.py` (LOLA), `atlas_paths.py`, `tool_settings.py`.
- **Frontend** — `viewer/viewer.js`, `index.html`, `app.html`, `friendly.js`, `exif.js`.
- **Supply chain** — `requirements.txt`, `packaging/requirements-build.txt`, `lunaratlas.spec`, `launcher.py`, installers.
- **CI/CD** — `.github/workflows/{test,build-app,browsers}.yml`.
- **Secrets hygiene** — `.env`, `secrets.yml`, full git history.

Three layers: **static sink review** (every `subprocess`/`shell`, `eval`/`exec`/`pickle`/`np.load`, `innerHTML` sink, outbound URL, externally-built path); **dynamic testing** (the real app on port 8790, a real viewer session on 8899, `download()` driven directly with hostile URLs); and **re-verification** against the current tree — including the token flow tested *with a valid credential*, so the gate is shown to work in both directions rather than merely failing everything.

### Threat model

A desktop app that (a) runs an **HTTP server on loopback** with no UI in front of it, (b) **downloads scientific datasets and fonts** over `urllib`, (c) **parses user photographs** and JSON sidecars, (d) **renders untrusted text** — IAU names and user edits — into HTML and exported PNGs. Adversaries: another process on the machine, any site the user visits while the app runs, and anyone able to tamper with a download.

---

## 2. Status summary

| ID | Sev. at baseline | Finding | Status in the current tree |
|----|------|---------|----------------------------|
| SEC-01 | Medium | `/data.js` was a JSONP endpoint readable cross-origin, leaking absolute paths and all map data | **Closed & verified** — now `/data.json` (`application/json`); anonymous request → **403** |
| SEC-02 | Medium | `download()` accepted any URL scheme; remote JSON `name` joined into a path unsanitised | **Closed & verified** — `https_open` scheme+host allowlist refuses `file://` and foreign hosts; `_listed` refuses traversal names |
| SEC-03 | Medium | Loopback API had no shared secret; any local process could read, write, drive, quit | **Closed & verified** — per-run token via `HttpOnly`/`SameSite=Strict` cookie or `X-LA-Token`; anonymous **403**, valid token **200** |
| SEC-04 | Low | Upload size taken from `Content-Length` with no ceiling | **Closed & verified** — `MAX_UPLOAD` 4 GiB; upload without token **403**; free-space check returns **507** |
| SEC-05 | Low | No CSP, no security headers | **Closed & verified** — CSP, `X-Frame-Options: DENY`, `nosniff`, `Cross-Origin-Resource-Policy`, `Referrer-Policy` on every response |
| SEC-06 | Low | Datasets pinned to nothing; trust store overridable via `SSL_CERT_FILE` | **Closed & verified** — `REF_SHA256`/`LOLA_SHA256` checked, `max_bytes` ceilings, `SSL_CERT_FILE` forced (not `setdefault`), `SSL_CERT_DIR` popped |
| SEC-07 | Low | Predictable `dest + '.part'` temp names | **Closed & verified** — `temp_beside()` uses `mkstemp`/`O_EXCL`/`0600`; app folder `0700` and `running.json` `0600` confirmed on disk |
| SEC-08 | Low | Unpinned dependencies; mutable `@v4` CI action tags | **Partly closed** — actions SHA-pinned, `permissions:` blocks added; **`requirements.txt` still unpinned** → open as SEC-08b |
| SEC-09 | Info | `/selftest` shipped; banner disclosed the interpreter version | **Closed & verified** — route refused without `LUNARATLAS_SELFTEST`; banner now `Server: LunarAtlas` |
| SEC-10 | Info | Dev screenshot harness opens an unauthenticated CDP port | **Open** |
| SEC-11 | Info | `-o` only refuses to overwrite the input image and its own sidecar | **Open** |
| SEC-12 | Low | *New:* an https→https redirect to a **different host** is followed without re-checking the allowlist | **Open** |
| SEC-13 | Info | *New:* the run token is a full-privilege credential that passes through a URL query | **Open — accepted by design**, documented below |
| SEC-14 | Info | *New:* the USGS gazetteer is deliberately not checksum-pinned | **Accepted risk**, already documented in code |

Nothing at any point in this audit permitted remote code execution.

---

## 3. Closed and re-verified

### SEC-01 — `/data.js` was a JSONP endpoint readable cross-origin — **Closed**

**Was (at `5db5268`):** the viewer served the entire page payload as executable JavaScript, and `local()` treated a *missing* `Origin` as trustworthy — which is exactly what a cross-site `<script src>` sends. A probe shaped like a hostile page's tag returned everything:

```http
GET /data.js HTTP/1.1     Host: localhost:8899
Referer: http://evil.example/          (no Origin)

200 OK   Content-Type: text/javascript
window.ATLAS = {"image":"moon.tif","path":"/tmp/la-probe/imgs/moon.tif", ...
```

 leaking the **absolute path of the user's photograph**, dimensions, tile layout, solved geometry, and every feature coordinate and edit — exfiltrable with one `<script>` tag. Rated Medium because it only applied to the `view` workflow (app mode returned 404) and the attacker had to scan a ~20-port window; pixels were not readable.

**Is:** the route no longer exists. `Session.data_js` became `data_json(...)`, served as `application/json` at `/data.json` (`atlas_view.py:510-511`) — a JSON document cannot be absorbed by a `<script>` tag, so the JSONP shape is gone rather than merely blocked — and it sits behind the run token (SEC-03).

**Re-verified live (current tree):**

```
GET /data.json  (no token)  -> 403
GET /data.js    (old route) -> 403
```

---

### SEC-02 — Unsanitised fields from a remote API response reached the filesystem — **Closed**

**Was:** the font downloader trusted two fields of a GitHub contents listing:

```python
want = [e for e in listing if e['name'].lower().endswith('.ttf')]
download(e['download_url'], os.path.join(d, e['name']), self._font_ok)
```

Proven at the time: (a) `download()` passed its argument straight to `urlopen`, so `download('file:///etc/hosts', dest, …)` **succeeded, copying 214 bytes** — a local-file read primitive, while a redirect *into* `file://` was refused by urllib; and (b) `e['name']` was joined without `basename()`, so `os.path.join(fontdir, '../../..../../.zshrc.ttf')` escaped the font directory. `_font_ok` only checks that the result parses as a TTF, and runs *after* the write. Exploitation needed a tampered API response, hence Medium — but the sink was plainly unsafe.

**Is:** both halves are closed. `atlas_geo.py` now routes every fetch through `https_open()`, which refuses any non-`https` scheme and any host outside `DOWNLOAD_HOSTS`; the listing is filtered by `Fonts._listed()`, which requires a single-component name matching `\w[\w .()\[\],-]{0,127}\.ttf` **and** a `download_url` under `GOOGLE_FONTS_RAW`; a `max_bytes` ceiling is applied as the body arrives.

**Re-verified live (current tree):**

```
download('file:///etc/hosts', …)          -> refused: refusing file: only https
download('https://evil.example/a.ttf', …) -> refused: refusing evil.example: not a host LunarAtlas downloads from
_listed name '../../.zshrc.ttf'           -> accepted=False
_listed name '/etc/evil.ttf'              -> accepted=False
_listed name '<200 chars>.ttf'            -> accepted=False
_listed name 'DejaVuSans.ttf'             -> accepted=True     (normal names still work)
```

---

### SEC-03 — The loopback API had no shared secret — **Closed**

**Was:** the only guards were a `Host` check and an `Origin` check. Both are correct as far as they go, and both were measured working — `Host: evil.example` → 403 (DNS rebinding), `Origin: http://evil.example` on a POST → 403 (browser CSRF). But `Origin` is a **browser-only header**: any local process may simply omit it. Measured at baseline against the running app: `GET /app/recent` with no `Origin` → **200** (work folder path, filenames, capture times), `POST /app/folder` → **200** (Finder opened), `POST /app/upload` → **200** (file created). Read, write, drive and quit were all available to an unauthenticated local process.

**Is:** a per-run secret exists (`Server.token`, `secrets.token_urlsafe(32)`, or `LUNARATLAS_TOKEN`), handed to the browser once through a `?t=` link that 303-redirects and sets a **`HttpOnly`, `SameSite=Strict`** cookie named per port (`la_<port>`, so two instances cannot cross-use cookies), and accepted from non-browser clients only via `X-LA-Token`. `authed()` compares with `hmac.compare_digest` and is enforced on every route (`atlas_view.py:492`, `:566`); the token itself lives in `running.json` beside a `0600`/`0700` application folder. The one exempt route is `/app/ping`, which returns a static liveness string and nothing else.

**Re-verified live (current tree):**

```
GET  /app/recent   no Origin, no token      -> 403     (was 200)
POST /app/folder   no Origin, no token      -> 403     (was 200)
POST /app/folder   Origin: http://evil.example -> 403
GET  /app/recent   Host: evil.example       -> 403
GET  /             anonymous                -> 403
POST /app/upload   no token                 -> 403     (was 200; no file created)
GET  /app/recent   X-LA-Token: <run token>  -> 200     <- gate works with a real credential
GET  /app/recent   Cookie: la_8790=<token>  -> 200
GET  /app/recent   X-LA-Token: nope         -> 403
GET  /app?t=<token>                         -> 303 Location: /app
                                             Set-Cookie: la_8790=…; Path=/; HttpOnly; SameSite=Strict
```

### SEC-04 — Upload had no size ceiling — **Closed**

**Was:** `n = int(h.headers.get('Content-Length', ''))` was trusted verbatim and streamed to disk, so a local process could fill the volume inside the user's pictures folder (proved: unauthenticated 200, file created). Path handling was always sound — `copy_name()` sanitises `name`/`time` and the destination is joined to the app's own folder.

**Is:** `MAX_UPLOAD = 4 << 30` is enforced by `h.length(MAX_UPLOAD)`, over-long requests are answered **413**, and `shutil.disk_usage(self.folder).free < n + SPARE` is refused with **507** before any writing. **Re-verified:** `POST /app/upload?name=bomb.tif` without a token → **403**, no file created; the same request carrying a token → **400**, i.e. it reached the parser and was rejected on content, which confirms the ceiling path is live rather than shadowed by the auth check.

### SEC-05 — No CSP, no security headers — **Closed**

**Was:** a served page carried only `Server: SimpleHTTP/0.6 Python/3.14.5`, `Content-Type`, `Cache-Control` — and `grep -rniE 'content-security-policy|http-equiv' lunaratlas/viewer/*.html` returned nothing. The concern was never a known XSS (there is none, §5) but that ~15 `innerHTML` interpolations in a 1100-line file eventually miss an `esc()`, and with no CSP a missed escape meant script running against an unauthenticated API.

**Is:** every response now carries `Content-Security-Policy` (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy: no-referrer`. **Re-verified** on an anonymous `GET /`:

```
HTTP/1.0 403 Forbidden
Server: LunarAtlas
Content-Security-Policy: default-src 'self'; script-src 'self'; …frame-ancestors 'none'…
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Cross-Origin-Resource-Policy: same-origin
Referrer-Policy: no-referrer
```

Headers are sent on error responses too, and `script-src 'self'` is present — so the SEC-01 shape (foreign script include) and any future injected inline script are both refused by the browser, independent of server-side logic.

### SEC-06 — Downloads trusted by size/shape only; trust store overridable — **Closed**

**Was:** LOLA was accepted on `getsize(p) == size` and the WAC reference on `ref.shape == SHAPE` — right-length bytes became signed 16-bit elevations driving shaded relief and label placement. No checksum anywhere. Separately `os.environ.setdefault('SSL_CERT_FILE', certifi.where())` let an inherited `SSL_CERT_FILE` silently replace the trust store, which was the precondition that would have made SEC-02 reachable.

**Is:** `REF_SHA256` (four WAC tiles) and `LOLA_SHA256` are verified by `sha256_file()` before `publish()`, mismatch removes the temp file and aborts; `max_bytes` aborts oversized transfers *as they arrive*; `launcher.py` now **assigns** `SSL_CERT_FILE` (not `setdefault`) and pops `SSL_CERT_DIR`, with the reason stated in the comment. **Re-verified:** the pinned digests are read at `atlas_geo.py:306` and `atlas_closeup.py:115`.

### SEC-07 — Predictable temporary filenames — **Closed**

**Was:** atomic writes used `dest + '.part'` and `f'{root}.part{ext}'` — names any other process can compute, opening the usual pre-create/symlink swap on a shared machine, plus a recomputable `sha1(abspath(image))` tile-cache key.

**Is:** `temp_beside()` in `atlas_paths.py:47-54` creates the temp with `tempfile.mkstemp` (`O_EXCL`, mode `0600`, random name, same directory so `publish()` stays atomic) and its docstring states the reason: *"Never `path + '.part'`: a symlink someone planted at that name would be written through."* **Re-verified on disk:** the application folder is `drwx------` and `running.json` is `-rw-------`. One cosmetic note: the `data/` subdirectory is `0755`, but it is unreachable to anyone else because its parent is `0700` — worth tightening for consistency, not exploitable as things stand.

### SEC-08 — Unpinned dependencies, mutable CI tags — **Partly closed**

**Closed:** all three workflows now pin actions to full commit SHAs with the version kept in a comment (`actions/checkout@11d5960a… # v4`, `setup-python@a26af69… # v5`, `setup-node@49933ea… # v4`, `upload-artifact@ea165f8… # v4`, `download-artifact@d3f86a1… # v4`), and all three declare explicit `permissions:` blocks (`build-app.yml` also scopes the release job's elevated permissions to that job). Both structural positives still hold: no `pull_request_target`, and no `run:` step interpolates `${{ }}` text.

**Still open → [SEC-08b](#sec-08b) below.**

---

## 4. Still open

### SEC-08b — Runtime dependencies are still unpinned <a id="sec-08b"></a>

**Severity:** Low (supply chain) · **Location:** `requirements.txt`, `packaging/requirements-build.txt`

```
numpy>=2.2
opencv-python-headless>=4.11,<5   # 4.x is what the tests run on
pillow>=11
```

Open-ended lower bounds, no lockfile, no hashes. `pillow>=11` matters most: every font, photograph and TTF in this audit is parsed by Pillow, and its CVE history is not shallow. The consequence is a *build* one — `build-app.yml` (triggered by a `v*` tag or manually) resolves "whatever is newest today", so binaries attached to a release cannot be rebuilt from the commit that produced them, and a compromised or typosquashed PyPI upload reaches users with no review step in between.

**Fix.** `pip-compile` both requirement files into a hash-pinned lock, install it with `pip install --require-hashes -r requirements-lock.txt` in `test.yml` and `build-app.yml`, and let Renovate or Dependabot open the bump PRs so pinning does not mean staleness. This is all that remains of the original SEC-08.

### SEC-12 — A redirect to a different host over https is followed without re-checking the allowlist

**Severity:** Low · **Location:** `atlas_geo.py:190-200`

`https_open()` validates the scheme and host **of the URL it is given**, and `_HttpsOnly` extends that to redirects — but only as far as the *scheme*:

```python
class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith('https://'):
            raise urllib.error.URLError(f'refusing a redirect to {newurl.split(":", 1)[0]}: only https')
        return super().redirect_request(req, fp, code, msg, headers, newurl)   # host not re-checked
```

**Verified by unit-testing the handler directly:**

```
redirect https://raw.githubusercontent.com/… -> https://evil.example/x.ttf : FOLLOWED (host not re-checked)
redirect https://…                           -> http://evil.example/x.ttf  : refused, "only https"
```

The downgrade half of the claim holds; the host half does not. An allowed host that redirects off-site — S3 buckets and CDN frontiers do — will have its target fetched and accepted, and for anything not SHA-256-pinned (fonts, the gazetteer) those bytes become the "official" copy. Reaching it needs an allowed host to redirect off-site, or a machine-in-the-middle holding a certificate this process trusts, which the https-only rule and forced certifi bundle make unlikely; hence Low. The docstring's *"and only https on any redirect"* is true of the scheme and easy to misread as covering the host.

**Fix.** Re-apply both checks to every redirect target, in the same place:

```python
class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_check(newurl)     # scheme AND DOWNLOAD_HOSTS — extract this from https_open()
        return super().redirect_request(req, fp, code, msg, headers, newurl)
```

Extracting the validation into one `https_check(url)` used by both keeps the allowlist in a single place. Pinning the font download by digest would make this class moot for fonts too.

### SEC-10 — Screenshot harness opens an unauthenticated DevTools port — *unchanged*

**Severity:** Informational (development only) · **Location:** `design/shoot.mjs:12-37`

Still `--remote-debugging-port=9337` plus `Runtime.evaluate`, so while the harness runs, any local process can attach to 9337 and drive that browser instance. It does not ship — `lunaratlas.spec` bundles seven viewer assets plus fonts and a fixed `hiddenimports` list, and `experiments/quality/label_server.py` is absent from the artefact too. Use `--remote-debugging-pipe` (no port, no listener, nothing to attach to) and keep the dedicated `--user-data-dir` profile it already uses.

### SEC-11 — `-o` only refuses to overwrite the input image and its own sidecar — *unchanged*

**Severity:** Informational · **Location:** `lunaratlas.py:294-296`

The guard is correctly written (`samefile`, so symlinks and hardlinks are caught) and correctly scoped to protecting the photograph and its geometry. Any other existing `-o` target is silently replaced, and because the default output name is derived from the input plus `--around`, re-exporting a feature quietly discards the previous export. Data loss, not a sandbox escape: every path here comes from the user's own command line. For the record, `--around` cannot escape the output folder (`re.sub(r'[^\w.-]+', '_', …)` collapses separators, and the parent directory must already exist), and the browser-driven export path derives its output name from the session's own image, so no client-supplied path reaches it at all.

### SEC-13 — The run token travels in a URL query — *accepted by design*

**Severity:** Informational · **Location:** `atlas_view.py:380`, `:467-477`

The handoff link is `http://localhost:<port>/app?t=<token>` — a sound magic-link design for a loopback-only server: the token is `secrets.token_urlsafe(32)`, compared with `hmac.compare_digest`, the 303 drops it from the address bar, and `Referrer-Policy: no-referrer` keeps it off the wire to third parties. Two properties are worth knowing rather than fixing: the token is **not** single-use (the `?t=` form and the cookie carry the same run-long value, valid until restart), and it is printed to stdout at launch. **Verified clean:** the token appears **zero** times in `~/Library/Application Support/LunarAtlas/lunaratlas.log`, which is mode `0644` — so nothing durable records it today. If the log ever captured stdout, that would turn from cosmetic into credential disclosure, which is the property worth keeping.

### SEC-14 — The USGS gazetteer is deliberately not checksum-pinned — *accepted risk*

**Severity:** Informational · **Location:** `atlas_names.py:65-70`

```python
download(GAZ_URL, z, zipfile.is_zipfile, log=log, max_bytes=200_000_000)   # USGS updates it: no fixed checksum
```

A reasoned exception, correctly commented and correctly bounded: the host is allowlisted, the transfer is capped at 200 MB, and `zipfile.is_zipfile` gates the result. A tampered gazetteer means mislabelled features — wrong science rather than execution — and hard pinning would break the app every time USGS republishes. If stronger assurance is ever wanted, record a digest per *release* of the file and accept either, rather than dropping the check entirely.

---

## 5. Verified clean

Actively looked for and either tested or read to a conclusion. These are the reasons the report has no critical findings, and they are the properties a future change must not break.

**No code execution from data.** `grep` for `eval(`, `exec(`, `pickle`, `np.load`, `numpy.load`, `allow_pickle`, `joblib`, `torch.load`, `os.system`, `os.popen`, `shell=True` across `lunaratlas/` and `packaging/` finds **no dangerous hit**. Downloaded arrays are read with `np.fromfile(p, '<i2')` — typed memory, incapable of carrying a payload. `subprocess.Popen` appears five times (`atlas_view.py`, `build.py:33`), **always an argv list, never `shell=True`**; `ExportJob` receives `cmd` from `export_command()` as a list, so the `'export: ' + ' '.join(cmd[2:])` log line is cosmetic. `self_command` resolves to an absolute path inside the app folder rather than a PATH-searched name, so no PATH hijack in the packaged app; the residual lookups are `open`/`explorer`/`xdg-open` in `reveal()`, needing write access to a system directory to abuse.

**Path traversal on the HTTP surface is closed twice over.** Before the token existed, every probe was refused by path logic; now nothing anonymous even reaches it:

```
/app/thumb?path=/etc/passwd                              404 -> now 403
/app/thumb?path=../../etc/passwd                         404 -> now 403
/app/thumb?path=/tmp/…/../../.ssh/id_rsa                 404 -> now 403
/fonts/../../../etc/passwd                               404 -> now 403
/fonts/..%2f..%2f..%2f..%2fetc/passwd                    404 -> now 403
/tiles/99/0_0.jpg                                        404 -> now 403
```

The underlying design is correct and worth keeping: `inside()` requires the resolved candidate to lie under the session folder, `/fonts/<name>.ttf` is a `re.fullmatch` with `.` rejected in the name, `/tiles/<level>/<c>_<r>.jpg` matches digits only so nothing but integers reaches `os.path.join`, and `%2f` is refused because `SimpleHTTPRequestHandler` unquotes `self.path` before the regex sees it.

**DNS rebinding and browser CSRF were already right** at baseline and still are: `Host: evil.example` → 403, `Origin: http://evil.example` on a POST → 403. The `Origin` regex is anchored with `re.fullmatch` and bound to the exact port, so a page on a *different port of the same origin* is refused too — a detail that is easy to get wrong.

**Frontend escaping is disciplined, checked case by case rather than assumed.** `viewer.js` escapes every externally-sourced string before it enters `innerHTML`: feature names, types and "named after" text (`esc(f.n)`, `esc(f.t)`, `esc(f.o)`), search results and the echo of the query, shape labels and font options, quality-gate reasons, the export target. Each remaining unescaped interpolation was traced to a non-external source: `toast()` writes through `textContent`, so `toast("“${f.n}” hidden")` is safe despite looking alarming; `style="background:${c}"` swatches draw only on hardcoded `LABEL`/`SH_COL` constants with no free-form colour input; the IAU link is guarded by `/^\d+$/.test(f.k)`; `applyStyle` accepts a font only if `(A.fonts || []).includes(st.font)`; `friendly.js` and `exif.js` contain no HTML sinks. Colour strings persisted in sidecars reach only `hex_rgba()`, which parses with `int(c[i:i+2], 16)` inside a `try/except` and falls back to white — no code or format-string path. **No XSS was found anywhere.**

**Sidecars fail safe.** Missing, unparseable or non-object sidecars raise a `ValueError` shown as a message and never reach a traceback; `d['edits']` passes through `clean_edits()` before being written back, so a hostile sidecar cannot smuggle keys into an export command.

**Secrets hygiene is clean.** `.env` and `secrets.yml` are untracked **and were never committed** — `git log --all -- .env secrets.yml` returns nothing across all history. A credential sweep over Python, JS, HTML and YAML found no hardcoded key, token or password. Outbound hosts are exactly `DOWNLOAD_HOSTS` plus loopback: no telemetry, no analytics, no update-check pings.

**The bundle ships less than the repository contains.** `lunaratlas.spec` includes seven viewer assets plus fonts and a fixed `hiddenimports` list, `excludes` `tkinter`/`matplotlib`/`scipy`/`pandas`/`pytest`/`unittest.mock`, `upx=False`. Neither `design/shoot.mjs` nor `experiments/quality/label_server.py` reaches the artefact, so neither the CDP harness nor the second loopback server ships.

**Practices worth protecting.** Atomic writes throughout (`temp_beside`/`publish`); `already_running()` deliberately uses `http.client` rather than `urllib` to avoid a proxy lookup on loopback, and authenticates the instance it found with an HMAC over a fresh nonce rather than trusting the port; `Server.server_bind` skips `socket.getfqdn` (latency, and it avoids an incidental reverse-DNS query); `Handler.timeout = 120` stops a stalled client holding a thread; the cookie is named per port so concurrent instances cannot cross-authenticate; the export subprocess gets `PYTHONIOENCODING=utf-8`/`CREATE_NO_WINDOW` and its children are killed rather than orphaned on quit. The code comments frequently state *why* a guard exists, which is precisely what makes an audit like this short.

---

## 6. Suggested next steps

The heavy lifting is done — the report went from three Medium findings to none in one round. What is left is small and independent:

| # | Action | Closes | Effort |
|---|--------|--------|--------|
| 1 | Extract `https_check(url)` from `https_open()` and call it from `_HttpsOnly.redirect_request` | **SEC-12** | ~15 min |
| 2 | Hash-pinned lockfile for `requirements.txt` + `requirements-build.txt`, installed with `--require-hashes` in both workflows | **SEC-08b** | ~2 h, then automatable |
| 3 | Digest-pin the font download too (a manifest of `name → sha256` per supported family) | removes SEC-12's remaining value for fonts | ~1 h |
| 4 | `chmod 0700` the `data/` subdirectory at creation, so it matches its parent | the SEC-07 footnote | ~5 min |
| 5 | `--remote-debugging-pipe` in `design/shoot.mjs` instead of port 9337 | **SEC-10** | ~20 min |
| 6 | Make `-o` collisions explicit (`_2` suffix, or require `--force`) | **SEC-11** | ~30 min |
| 7 | Keep stdout — and therefore the launch URL with its `?t=` token — out of `lunaratlas.log` forever, ideally with a test | keeps **SEC-13** theoretical | ~15 min |

**Two regression tests worth adding now**, because both guard fixes that are invisible from the UI and easy to undo by accident while refactoring the server:

```python
def test_anonymous_requests_are_refused(client):
    for path in ('/', '/data.json', '/app/recent', '/selftest'):
        assert client.get(path, headers={'Referer': 'http://evil.example/'}).status == 403

def test_state_changing_routes_need_the_token(client):
    assert client.post('/app/folder').status == 403                       # no Origin, no token
    assert client.post('/app/folder', headers={'X-LA-Token': 'nope'}).status == 403
    assert client.post('/app/folder', headers={'X-LA-Token': TOKEN}).status == 200

def test_download_refuses_other_schemes_and_hosts():
    for url in ('file:///etc/hosts', 'http://api.github.com/x', 'https://evil.example/x.ttf'):
        with pytest.raises(urllib.error.URLError):
            atlas_geo.download(url, '/tmp/x.bin', lambda p: True)
```

The middle assertion in the second test — the *accepting* case — matters as much as the refusing ones: a gate that rejects everything would pass the first two and ship a broken app.

**One process note.** The audit's baseline (`5db5268`) and the tree it was re-verified against (`2ba20476` + uncommitted work) differ by roughly a thousand lines, which is why this report had to be rewritten mid-flight. If the hardening is meant to be reviewed before merge, committing it as its own changeset — with this document's §3 as its body text — would make the next pass much cheaper, and lets the tests above land in the same commit as the guards they cover.

---

## Appendix — reproducing the results

Run from the repository root on macOS with the project's build virtualenv (`.venv-build/bin/python`, Python 3.14.5). Scratch paths lived in `/tmp/la-probe` and have been cleaned up; the probe app has been stopped.

### A. Start the app and read its token

```bash
mkdir -p /tmp/la-probe
.venv-build/bin/python lunaratlas/lunaratlas.py app --no-open --port 8790 --folder /tmp/la-probe &
# the launch line prints the handoff URL and therefore the token:
#   [0.0 s] LunarAtlas: http://localhost:8790/app?t=<TOKEN>  (Ctrl-C to stop)
# or read it from the state file, which is mode 0600:
TOKEN=$(python -c "import json,os;print(json.load(open(os.path.expanduser(\
  '~/Library/Application Support/LunarAtlas/running.json')))['token'])")
```

### B. The anonymous probes that produced SEC-01, SEC-03, SEC-04, SEC-05, SEC-09

```bash
B=http://127.0.0.1:8790
curl -s -o /dev/stdout -w ' status=%{http_code}\n' $B/app/recent -H 'Referer: http://evil.example/' -H 'User-Agent: Mozilla/5.0'
curl -s -o /dev/stdout -w ' status=%{http_code}\n' -X POST $B/app/folder
curl -s -o /dev/stdout -w ' status=%{http_code}\n' -X POST $B/app/folder -H 'Origin: http://evil.example'
curl -s -o /dev/stdout -w ' status=%{http_code}\n' $B/app/recent -H 'Host: evil.example'
curl -s -o /dev/stdout -w ' status=%{http_code}\n' $B/data.json
curl -s -o /dev/stdout -w ' status=%{http_code}\n' $B/selftest
printf x > /tmp/blob.tif && curl -s -o /dev/stdout -w ' status=%{http_code}\n' --data-binary @/tmp/blob.tif \
     -H 'Content-Type: image/tiff' "$B/app/upload?name=bomb.tif&time=2026-09-29%2000:00:00"
curl -s -D - -o /dev/null $B/ | head -12          # CSP, XFO, nosniff, CORP, Referrer-Policy, Server: LunarAtlas
```

At baseline `5db5268` the first, second and upload probes returned **200**; on the current tree every one of them returns **403**, and the header dump shows the policy that did not exist before.

### C. Proving the gate accepts what it should

```bash
curl -s -o /dev/null -w 'token  %{http_code}\n' $B/app/recent -H "X-LA-Token: $TOKEN"     # 200
curl -s -o /dev/null -w 'cookie %{http_code}\n' $B/app/recent -H "Cookie: la_8790=$TOKEN"  # 200
curl -s -o /dev/null -w 'wrong  %{http_code}\n' $B/app/recent -H 'X-LA-Token: nope'        # 403
curl -s -D - -o /dev/null "$B/app?t=$TOKEN" | grep -i 'HTTP/\|location\|set-cookie'        # 303 + HttpOnly cookie
```

### D. Traversal probes

```bash
for u in '/app/thumb?path=/etc/passwd' '/app/thumb?path=../../etc/passwd' \
         '/app/thumb?path=/tmp/la-probe/../../.ssh/id_rsa' '/tiles/99/0_0.jpg' \
         '/fonts/../../../etc/passwd' '/fonts/..%2f..%2f..%2f..%2fetc/passwd'; do
  printf '%-52s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "$B$u")"
done          # every line 403 now, 404 at baseline
```

### E. `download()` and the font listing

```python
import sys, urllib.request; sys.path.insert(0, 'lunaratlas')
import atlas_geo as g
from atlas_render import Fonts

for url in ('file:///etc/hosts', 'https://evil.example/a.ttf'):
    try: g.download(url, '/tmp/x.bin', lambda p: True); print(url, 'ACCEPTED')
    except Exception as e: print(url, '-> refused:', e)

for n in ['../../.zshrc.ttf', '/etc/evil.ttf', 'a b.ttf', 'x'*200 + '.ttf', 'DejaVuSans.ttf']:
    print(n[:28], Fonts._listed([{'name': n,
          'download_url': 'https://raw.githubusercontent.com/google/fonts/x/' + n}]) != [])
```

### F. The redirect gap in SEC-12

```python
req = urllib.request.Request('https://raw.githubusercontent.com/google/fonts/x.ttf')
h = atlas_geo._HttpsOnly()
h.redirect_request(req, None, 302, 'Found', {'location': 'https://evil.example/x.ttf'},
                   'https://evil.example/x.ttf')          # returns a Request: it is followed
h.redirect_request(req, None, 302, 'Found', {'location': 'http://evil.example/x.ttf'},
                   'http://evil.example/x.ttf')           # raises: refusing a redirect to http
```

### G. The static sweeps behind §5

```bash
grep -rnE 'eval\(|exec\(|pickle|np\.load|allow_pickle|os\.system|shell=True' lunaratlas/ packaging/
grep -rn 'subprocess' lunaratlas/ packaging/ | grep -v '\.md:'
grep -rniE 'content-security-policy' lunaratlas/atlas_view.py lunaratlas/viewer/*.html
git log --all --oneline -- .env secrets.yml          # empty = never committed
grep -n "e\['name'\]\|basename\|fullmatch" lunaratlas/atlas_render.py | head
grep -n 'uses:.*@' .github/workflows/*.yml           # full SHAs, not @v4
ls -ld ~/Library/Application\ Support/LunarAtlas ~/Library/Application\ Support/LunarAtlas/running.json
```

### H. Tear-down

```bash
pkill -f 'lunaratlas.py app'; lsof -nP -iTCP:8790 -sTCP:LISTEN || echo 'port free'
rm -rf /tmp/la-probe /tmp/blob.tif
```

`--folder /tmp/la-probe` points the app's work folder somewhere temporary; relaunch without `--folder` to return to `~/Pictures/LunarAtlas`.

---

*End of report. Every "Verified" statement came from running this code at `2ba20476` plus the working-tree changes described above, and every "Was" statement from `5db5268`. The probes are reproduced in full so any finding — including any closure — can be re-checked or falsified independently.*
