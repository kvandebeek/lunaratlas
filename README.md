# LunarAtlas

IAU feature names on your own lunar images, like LROC QuickMap but with your data.

It works on full disks, any phase, mosaics and close-ups without a limb. It finds the image's position,
orientation, mirroring and libration automatically, refuses images too poor to annotate, and exports
labelled images at 1:1 or smaller (never upscaled). A browser viewer lets you search, measure in km,
draw, and move or restyle the labels; your edits are kept and reused by the command-line export.

```sh
python3 moon_atlas/moon_atlas.py locate mosaic_finished.tif   # position the image (10-20 s; close-ups 30-100 s)
python3 moon_atlas/moon_atlas.py view   mosaic_finished.tif   # browser viewer and editor
python3 moon_atlas/moon_atlas.py export mosaic_finished.tif --around Copernicus --size 3600x2400
```

Measured on a 200 Mpx lunar mosaic: 621 terrain matches at 1.56 px RMS (0.43 km).

See [`moon_atlas/README.md`](moon_atlas/README.md) for how the positioning works, the quality gate, the
close-up search, the viewer and every export option.

## Requirements

macOS or Linux, Python 3.14 with numpy, OpenCV and Pillow. Reference data (IAU gazetteer, LROC WAC
albedo, LOLA elevation, fonts) is downloaded once on first use into `moon_atlas/data/`.

## Settings

Per-machine settings live in `.env`, which is not committed; [`.env.example`](.env.example) lists every
key with its default. All settings are declared once in [`tool_settings.py`](tool_settings.py) with
their type, default and range, and `.env.example` is generated from it:

```sh
python3 tool_settings.py --check      # value in effect for every setting, with out-of-range warnings
python3 tool_settings.py --example    # regenerate .env.example
```

Set your observing site before locating close-ups: it is used for the parallax, worth up to 1 degree of
libration.

Precedence: command-line option > environment variable > `.env` > built-in default.

## Related

[LunarMosaic](https://github.com/kvandebeek/lunarmosaic) builds the gigapixel mosaics this annotates. It
depends on this repository; this one depends on nothing.

## Licence

[Apache License 2.0](LICENSE). Use it, change it, build on it, commercially or not; keep the copyright
notice and say where it came from.

If it saved you time, [sponsoring](https://github.com/sponsors/kvandebeek) is welcome but never expected.
