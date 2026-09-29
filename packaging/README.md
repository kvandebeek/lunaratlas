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
python3 -m pip install -r packaging/requirements-build.txt
python3 packaging/build.py --version 1.0.0             # -> dist/
```

On Windows the installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc`); without it the build
makes a `.zip` of the folder instead.

[`.github/workflows/build-app.yml`](../.github/workflows/build-app.yml) builds all four on GitHub: run it from the
Actions tab, or push a tag `v1.0.0` to get a draft release with the installers attached.

## Files

| File | What it does |
|---|---|
| `launcher.py` | Entry point: no arguments → the launcher; a `lunaratlas.py` subcommand → that command. |
| `lunaratlas.spec` | PyInstaller: one folder, two executables (`LunarAtlas` windowed, `lunaratlas-cli` console, which the launcher runs `locate` and `export` with). |
| `build.py` | Runs PyInstaller and makes the platform's installer. |
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

## Signing

Unsigned builds work, but the first start needs the user's permission:
- **macOS:** "LunarAtlas cannot be opened" → System Settings > Privacy & Security > *Open Anyway* (once).
  With an Apple Developer ID, set `MACOS_SIGN_IDENTITY` (and `MACOS_NOTARY_PROFILE` from
  `xcrun notarytool store-credentials`) before `build.py` to sign and notarise; then there is no warning.
- **Windows:** SmartScreen shows "Windows protected your PC" → *More info* > *Run anyway*. A code-signing
  certificate removes it (not wired in yet).
