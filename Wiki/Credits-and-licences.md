# Credits and licences

LunarAtlas is a thin layer over decades of other people's work. None of this would exist without the
missions that mapped the Moon and the people who published the results openly.

## The data

| What | Who | Used for |
|---|---|---|
| **Gazetteer of Planetary Nomenclature** | USGS Astrogeology / IAU | Every name, its position, its class and its diameter. 9087 lunar features. |
| **LROC WAC empirically normalized 643 nm mosaic** | NASA / GSFC / Arizona State University | The albedo map: what the Moon reflects, independent of lighting. |
| **LOLA gridded elevation, LDEM 16 and 64 px/degree** | NASA / GSFC | The shape of the Moon, lit from where the Sun actually was, which is what your photo is matched against. |

Landing-site positions are approximate.

All of it is downloaded on first use, each file checked against a known SHA-256 and fetched only from an
explicit list of allowed hosts. Nothing is bundled into the app and nothing is redistributed.

## The fonts

IBM Plex Sans, Source Sans 3, Roboto and Barlow — all under the **SIL Open Font License**, bundled with
the app so nothing has to be downloaded to render a label.

`--font` also accepts any Google Fonts family, which is then downloaded once.

## The software

| | |
|---|---|
| **numpy, OpenCV, Pillow** | the image and numerical work |
| **PyInstaller** | the packaged app |
| **pywebview** | the app's own window (WebKit on macOS, Edge WebView2 on Windows) |

The packaged app ships `THIRD-PARTY-NOTICES.txt` with every dependency's own licence text. The build
fails if a GPL-only codec library turns up in it — OpenCV's default wheel can bundle video codecs that
LunarAtlas has no use for, so the release build uses an OpenCV compiled without video I/O.

The ephemeris follows Meeus, *Astronomical Algorithms*.

## LunarAtlas itself

Copyright 2026 Kristof Vandebeek, under the **[Apache License 2.0](https://github.com/kvandebeek/lunaratlas/blob/main/LICENSE)**.

Use it, change it, build on it, commercially or not. Keep the copyright notice and say where it came
from.

If it saved you time, [sponsoring](https://github.com/sponsors/kvandebeek) is welcome but never expected.

## Related

[LunarMosaic](https://github.com/kvandebeek/lunarmosaic) builds the gigapixel mosaics that LunarAtlas
annotates. It depends on this repository; this one depends on nothing.
