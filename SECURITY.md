# Security

LunarAtlas is a desktop app. The parts that matter for security are the small web server it runs on your own machine
(`127.0.0.1`), the reference data and fonts it downloads on first use, and the photos and sidecar files it reads.

## What it defends against

| Who | How |
|---|---|
| A website open in the same browser (including DNS rebinding) | Requests need a `Host` of localhost, no foreign `Origin`, no cross-site `Sec-Fetch-Site`, and this run's token in an HttpOnly, SameSite=Strict cookie. Only GET and POST are answered. The page data is JSON fetched by the page, not a script another site could include, and it does not contain your account name. Pages are sent with a Content-Security-Policy that allows no inline script and no framing, plus `nosniff` and a same-origin resource policy. |
| Another user or process on the machine | The same token: it is made at every start, and shown only to the browser that is sent to the app (in a link that is used once, then dropped from the address). A second start of the app finds the first through a file only you can read and checks a keyed proof, so something else listening on the port is not mistaken for it, and does not receive your photos. Cache and state folders are private (mode 0700), temporary files have unpredictable names and are never followed through a planted symlink. |
| A hostile or broken download | Only https, only from the hosts the app uses, a redirect never leaves https, a size limit, and the fixed archive products (the four LROC WAC tiles, the two LOLA models) are checked against pinned SHA-256 digests before use. Only the table is taken out of the gazetteer archive. A font listing can name only plain `.ttf` files on `raw.githubusercontent.com/google/fonts`. The packaged app trusts its own certificate bundle whatever the environment says. |
| An image or `.atlas.json` received from someone else | A sidecar cannot start a font download (only bundled and already downloaded families), and the drawings in it are capped (5 000 shapes, 200 000 outline points). Its edits are re-checked by type when read and when exported. |
| A local process that sends too much | Bodies are capped (16 MB JSON, 4 GB upload with a disk-space check), a bad or negative length is refused at once, sockets time out. |
| A compromised release pipeline | Workflow actions are pinned to commits, the token is read-only except in the release job, dependencies are installed from hash-locked files, macOS signing seals every nested binary, releases list SHA-256 checksums. |

## What it does not do

- The Windows installer is not Authenticode-signed (there is no certificate yet), and the macOS app is signed and
  notarised only when the builder has a Developer ID.
- The token protects against other pages and other users. Something running as *you* can read your files, the state file
  and the token anyway.
- The gazetteer archive is updated by the USGS, so it is size- and shape-checked rather than pinned.
- `-o` on the command line replaces an existing file of that name, like any export does; only the input photo and its
  sidecar are protected.

## Reports

Independent reviews of an earlier state are in `claude-security-findings.md`, `codex-security-findings.md` and
`cline-security-findings.md`. What was done about each finding:

| Finding | Status |
|---|---|
| Any site can read `/data.js` (path, name, positioning) | Fixed: `/data.json` fetched by the page, `Sec-Fetch-Site` check, no path in the data |
| Released viewer has no Host/Origin checks | Fixed in this code (the released `main` before it is affected: update, and do not leave an old viewer running) |
| `HEAD` bypasses the guard | Fixed: only GET and POST, everything else answers 405 after the guard |
| No authentication on the local API; port squatting | Fixed: per-run token, keyed proof between the two starts of the app |
| Downloads without integrity checks; `file:` and `http:` URLs; font names as paths; zip extraction | Fixed: https and host allow-list, pinned digests, size limits, basename and host checks, only the table extracted |
| No security headers / framing | Fixed: CSP without inline script, frame-ancestors none, nosniff, CORP, referrer policy; no interpreter version in the banner |
| Unlimited bodies and uploads | Fixed |
| Sidecar from someone else | Fixed: no font downloads from it, capped drawings |
| CI/CD: permissions, action pinning, unpinned dependencies, signing | Fixed except Authenticode (needs a certificate) |
| Labelling server: no CSRF guard, file names in `innerHTML` | Fixed |
| Predictable `.part` files | Fixed: `temp_beside()` / `publish()` |
| `/selftest` in the release | Fixed: only when `LUNARATLAS_SELFTEST` is set |
| Inherited `SSL_CERT_FILE` in the packaged app | Fixed |
| Export `--around` name read as an option | Fixed: `--around=NAME` |
| Dev screenshot tool opens a DevTools port | Not changed (development only, never shipped); it uses a dedicated profile |
| `-o` overwrites an existing file | Not changed: re-exporting replaces the last export, which the viewer's Export button relies on |
