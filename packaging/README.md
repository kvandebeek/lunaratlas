# Packaging

The packaged LunarAtlas is the `lunaratlas.py app` launcher with Python, numpy, OpenCV and Pillow built in
(PyInstaller). Double-clicking it opens the launcher in a window of its own; nothing else needs installing.

The window is [pywebview](https://pywebview.flowrl.com) on the system's web engine: WebKit on macOS, Edge WebView2
on Windows (part of Windows 10 and 11). Closing it stops the app, including a locate or export still running. Linux
builds use the browser instead (pywebview there needs the distribution's GTK WebKit, which does not bundle well), and
stop by themselves three minutes after the last page was closed.

| Platform | Result | Install |
|---|---|---|
| macOS (Apple silicon, Intel) | `LunarAtlas-VERSION-macos-ARCH.dmg` | drag *LunarAtlas* to Applications |
| Windows | `LunarAtlas-VERSION-windows-setup.exe` (Inno Setup) | per user, no administrator rights |
| Linux | `LunarAtlas-VERSION-linux-ARCH.tar.gz` | unpack, run `./LunarAtlas` or `./install.sh` (menu entry) |

## Building

On the platform the build is for (PyInstaller does not cross-compile):

```sh
python3 -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m pip install --require-hashes -r packaging/requirements-build.lock
python3 packaging/build.py --version 1.0.0             # -> dist/
```

On Windows the installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc`); without it the build
makes a `.zip` of the folder instead.

[`.github/workflows/build-app.yml`](../.github/workflows/build-app.yml) builds all four on GitHub: run it from the
Actions tab, or push a tag `v1.0.0` to get a draft release with the installers attached.

## Files

| File | What it does |
|---|---|
| `launcher.py` | Entry point: no arguments → the launcher; a `lunaratlas.py` subcommand (`lunaratlas.COMMANDS`, the CLI's own list) → that command. |
| `lunaratlas.spec` | PyInstaller: one folder, two executables (`LunarAtlas` windowed, `lunaratlas-cli` console, which the launcher runs `locate` and `export` with), the whole `viewer/` folder bundled as data so a page script can never go missing. |
| `build.py` | Runs PyInstaller, writes the third-party notices and checks for GPL-only codec libraries (`notices.py`), and makes the platform's installer. |
| `build_opencv_minimal.py` | Rebuilds the pinned OpenCV source without FFmpeg/video I/O before a release build, so the app ships only the still-image functionality it uses. |
| `notices.py` | Collects every dependency's own licence text into `THIRD-PARTY-NOTICES.txt` in the built app, and fails the build if a GPL-only library (x264, x265, …, which OpenCV's default wheel can bundle although LunarAtlas does no video I/O) is found in it. Override with `LUNARATLAS_ALLOW_GPL_CODECS=1` while that is being fixed at the source (rebuild `opencv-python-headless` with `WITH_FFMPEG=OFF`). |
| `windows/lunaratlas.iss` | Inno Setup script. |
| `linux/` | `.desktop` entry and `install.sh`. |
| `icon/` | The app icon: SVG masters, `macos/LunarAtlas.icns`, `windows/LunarAtlas.ico`, `linux/hicolor/` (see `icon/README.md`). The pages use `svg/lunaratlas.svg` as their favicon (`lunaratlas/viewer/lunaratlas.svg`). |

## Where the app keeps things

| | macOS | Windows | Linux |
|---|---|---|---|
| Reference data (≈ 145 MB on first use, ≈ 530 MB more for the first close-up) and `.env` | `~/Library/Application Support/LunarAtlas` | `%LOCALAPPDATA%\LunarAtlas\Data` | `~/.local/share/lunaratlas` |
| Tile cache | `~/Library/Caches/LunarAtlas` | `%LOCALAPPDATA%\LunarAtlas\Cache` | `~/.cache/lunaratlas` |
| Photos and exports | `~/Pictures/LunarAtlas` | `Pictures\LunarAtlas` | `~/Pictures/LunarAtlas` |
| Log | `lunaratlas.log` in the data folder | same | same |

## Locked dependencies

The builds and the tests install from lock files with a hash for every wheel (`pip install --require-hashes`), so what
goes into a release is what was reviewed, not what PyPI serves that day:

| File | For |
|---|---|
| `requirements.lock` | running LunarAtlas from a checkout (`requirements.txt` has the loose bounds) |
| `requirements-ci.lock` | the test workflows (the same, plus certifi) |
| `packaging/requirements-build.lock` | the app builds (adds PyInstaller, pywebview, certifi) |

`packaging/lock.sh` rewrites all three (`uv`, universal: one file for macOS, Windows and Linux); run it to update a
dependency, read the diff, commit it. The workflow actions are pinned to commit SHAs (the tag is in the comment).

## Signing

Unsigned builds work, but the first start needs the user's permission:
- **macOS:** "LunarAtlas cannot be opened" → System Settings > Privacy & Security > *Open Anyway* (once).
  With an Apple Developer ID, set `MACOS_SIGN_IDENTITY` (and `MACOS_NOTARY_PROFILE` from
  `xcrun notarytool store-credentials`) before `build.py` to sign and notarise; then there is no warning.
- **Windows:** SmartScreen shows "Windows protected your PC" → *More info* > *Run anyway*. An Authenticode
  code-signing certificate removes it; there is none yet, so the installer is not signed.

macOS signing signs every nested binary and bundle inside the app one by one, innermost first, then the app (not
`codesign --deep`). Every release lists `SHA256SUMS.txt`; check a download with `shasum -a 256 -c SHA256SUMS.txt`.
