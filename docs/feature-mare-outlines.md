# Feature idea: clickable mare outlines (like crater rims) — 2026-09-30

## Status

Deferred. Not started. Parked here so it isn't lost while the close-up
locate-accuracy work (false positives / low-resolution reference data) is
finished first.

## The ask

In the viewer, clicking a crater label draws its rim outline
(`drawRim` in [`lunaratlas/viewer/viewer.js`](../lunaratlas/viewer/viewer.js),
around line 543). The request: do the same for maria (Mare Imbrium, Mare
Serenitatis, etc.) — click the label, see its outline.

## Why it's not a small extension of the crater code

Crater rims work because each gazetteer entry (from the IAU planetary
nomenclature data LunarAtlas already loads, see `atlas_names.py`) gives a
centroid lat/lon *and* a diameter, and a circle of that diameter is
basically the real rim — craters are close enough to circular.

Maria are not. Checked the actual gazetteer entry:

```
{'name': 'Mare Imbrium', 'cls': 'area', 'lat': 34.72, 'lon': -14.91,
 'diam': 1145.527, ...}
```

Same shape as a crater entry — one centroid, one nominal diameter — but
Mare Imbrium is a roughly pear-shaped lava-filled basin, not a 1145 km
circle. Drawing a circle that size would be actively wrong (not just a
rough approximation): it would be close to the combined size of the whole
Imbrium/Serenitatis/Frigoris/Insularum cluster and would overlap
neighbouring maria on screen.

## What it would actually take

Real mare outlines need true boundary polygons, which is data LunarAtlas
does not currently have anywhere in the codebase. Rough shape of the work:

1. Find a usable source of mare boundary polygons (e.g. a USGS/LOLA-derived
   mare-unit shapefile, or another authoritative geologic-unit dataset).
   Needs a license check and a stable, trustworthy host — this project
   pins every download by sha256 and only fetches from an explicit host
   allowlist (`DOWNLOAD_HOSTS` in `atlas_geo.py`), so a new source is not a
   casual addition.
2. Convert/simplify the polygon(s) into whatever the viewer can render
   cheaply (likely a simplified point list per mare, similar in spirit to
   the existing hand-drawn "outline" shape tool already in `viewer.js`, but
   sourced from data instead of drawn by the user).
3. Wire click-to-select behaviour for `cls == 'area'` labels the same way
   craters do it now, but rendering the polygon instead of `drawRim`'s
   circle.
4. Decide how this interacts with export (do mare outlines appear in
   exported/annotated images the way crater rims can?).

## Next step, whenever this is picked back up

Start at step 1 — find and vet a real mare-boundary dataset — before
touching any viewer code, since the whole feature is gated on having
correct polygon data to draw.
