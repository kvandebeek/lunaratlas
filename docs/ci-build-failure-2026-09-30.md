# CI "Build app" workflow failure — 2026-09-30

## Status

Investigated only. No fix applied yet — kept as reference for when we're
ready to rebuild.

## What failed

GitHub Actions workflow **Build app** (`workflow_dispatch`), run
[36754623185](https://github.com/kvandebeek/lunaratlas/actions/runs/36754623185),
triggered 2026-09-30 17:53 UTC.

All four platform `build` jobs failed at the same step, **"Minimal OpenCV"**:

- `build (macos-15-intel, dist/LunarAtlas.app/Contents/MacOS)`
- `build (macos-15, dist/LunarAtlas.app/Contents/MacOS)`
- `build (ubuntu-22.04, dist/LunarAtlas)`
- `build (windows-latest, dist/LunarAtlas)`

The dependent `Inno Setup`, `Version`, `Build`, `Smoke test`, and `release`
jobs never ran as a result.

## Root cause

`packaging/build_opencv_minimal.py` builds `opencv-python-headless==4.14.0.94`
from source with:

```
CMAKE_ARGS = -DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DBUILD_opencv_videoio=OFF
```

This is intentional — LunarAtlas only reads/writes still images, and the goal
is to avoid bundling FFmpeg's GPL-only codecs (see the docstring at the top
of that script).

With `BUILD_opencv_videoio=OFF`, the `videoio` module's headers
(`opencv2/videoio.hpp`) are not generated/installed. However, the `gapi`
module (built by default) unconditionally includes that header:

```
modules/gapi/include/opencv2/gapi/streaming/cap.hpp:27:10:
  fatal error: 'opencv2/videoio.hpp' file not found
```

This breaks compilation of `modules/python3/.../cv2.cpp` on every platform:

- macOS (both intel and arm runners): `fatal error: 'opencv2/videoio.hpp' file not found`
- Ubuntu: `fatal error: opencv2/videoio.hpp: No such file or directory`
- Windows (MSVC): `error C1083: Cannot open include file: 'opencv2/videoio.hpp'`

In other words, disabling `videoio` without also disabling (or otherwise
satisfying) `gapi`'s dependency on it breaks the build. This is apparently a
new incompatibility introduced by the pinned OpenCV version
(`4.14.0.94`) — `gapi`'s `cap.hpp` pulls in `videoio.hpp` regardless of
whether video I/O support is actually enabled.

## Where to look when fixing this later

- `packaging/build_opencv_minimal.py` — the `FLAGS` constant (line 19) is
  where the CMake flags are defined.
- Likely fix directions (not yet evaluated/applied):
  - Add `-DBUILD_opencv_gapi=OFF` to `FLAGS`, since LunarAtlas doesn't use
    the G-API module either.
  - Or find/patch the specific `gapi` header so it doesn't hard-require
    `videoio.hpp` when video I/O is disabled (more fragile, would need to
    survive future OpenCV version bumps).
  - Whichever direction is taken, the `SOURCE_SHA256` pin will stay the
    same (it pins the *source archive*, not the build flags), but the
    resulting wheel's contents will change, so smoke tests should be
    re-run afterward.

## Secondary notes (non-blocking)

- All four jobs show a deprecation warning: `actions/checkout` and
  `actions/setup-python` target Node.js 20 but are being forced onto
  Node.js 24 by the runner. Not related to this failure, but worth
  revisiting the pinned action versions at some point.
