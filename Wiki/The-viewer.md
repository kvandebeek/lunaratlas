# The viewer

The viewer is where you actually use the result: look around, find things, measure, annotate, and decide
which names belong in the picture you will export.

![The viewer](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer.jpg)

Four areas:

- **top bar** — the photo's name, the Moon's phase that night, and the search box;
- **tool rail**, left — pan, measure, and the drawing tools;
- **Layers panel**, right — which names appear, how many, and how dense;
- **status bar**, below — where your cursor is on the Moon, the scale, the zoom, and **Export**.

## Moving around

| | |
|---|---|
| Drag | Pan |
| Scroll / pinch | Zoom at the pointer |
| `+` / `-` | Zoom in / out |
| `F` | Fit the whole picture |
| `1` | Actual pixels, 1:1 |

The status bar shows the latitude and longitude under your cursor and the scale in **km per pixel**, so
you always know how much Moon one pixel of your photo is worth.

## Names appear as there is room

LunarAtlas does not draw 6500 names at once. A crater is named when it is at least about 24 pixels across
on your screen, so zooming in brings in smaller features, and names that would collide give way to the
more important ones (type first, then size).

![Zoomed in near Copernicus](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-zoomed.jpg)

The **Detail** slider in the Layers panel changes that threshold if you want more or fewer names, and
**Label size** changes how big they are drawn.

## Searching

Press `/` or click the search box and start typing. It searches all the names in your picture.

![Searching for a name](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-search.jpg)

Pick a result and the viewer flies there and selects it.

## Clicking a name

![A feature card](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-feature-card.jpg)

Clicking a name selects the feature, outlines it, and opens a card with what the gazetteer knows about
it: its kind, diameter, position, and where that is in your picture.

To pick **several** names at once, hold ⌥ (Alt on Windows and Linux) and click them, or ⌥-drag a box
around an area. `Delete` (or the Hide button) hides them all in one step, which you can undo. `Esc`
clears the selection.

## Measuring

Press `M`, click where you want to start, click where you want to end.

![Measuring a distance](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-measure.jpg)

The distance is the real one along the Moon's curved surface (a great circle), not a flat ruler on your
photo. Click a saved measurement to adjust or delete it. Measurements are saved with the photo and are
drawn into exports.

## Drawing your own things

| Key | Tool |
|---|---|
| `V` | Pan and select |
| `M` | Measure |
| `C` | Circle |
| `E` | Ellipse |
| `R` | Rectangle |
| `O` | Outline — click points, double-click to close |
| `T` | Text |
| `A` | Arrow |

Draw an arrow and a panel opens beside it, offering the names nearby as ready-made labels:

![Annotating with an arrow](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-annotate.jpg)

Everything you draw can be moved (drag it) and reshaped (drag its square handles), recoloured, resized,
and made dashed. `⌘Z` / `Ctrl+Z` undoes, `⇧⌘Z` redoes.

## Moving a name out of the way

Drag a name and it moves; a thin dashed line stays, pointing at the feature it belongs to, so the picture
stays honest.

![A moved name keeps a line to its feature](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-moved-name.jpg)

You can also recolour or resize a single name from its card. All of this is kept, and used by the export.

## The Layers panel

![Craters switched off](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-layers-off.jpg)

| Switch | What it controls |
|---|---|
| Maria, lakes, bays | The big named areas, in spaced capitals |
| Craters | Named craters |
| Lettered craters | The satellite craters: Copernicus A, B, … (follows the Craters switch) |
| Mountains, rilles, ridges | Montes, Rimae, Dorsa, Rupes, … |
| Landing sites | Apollo, Luna, Surveyor, Chang'e, … (positions are approximate) |
| All crater outlines | Normally only the selected crater is outlined; this shows them all |
| Lat/lon grid | `G` |
| My drawings | Everything you drew and measured |

The counts on the right tell you how many of each are in this picture.

![The lat/lon grid](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-grid.jpg)

**Names on the night side** — hide, dim, or show. The default is hide: LunarAtlas knows where the Sun
was, so it knows which features are in darkness. Showing them is useful on a crescent, when most of the
disk is unlit but you still want to know what is there.

**Font** — IBM Plex Sans, Source Sans 3 or Roboto, all bundled with the app. Nothing is downloaded.

`L` switches all name layers off and on together, which is the quickest way to compare your picture with
and without annotation.

## Your edits are saved

Everything — hidden names, moved names, colours, drawings, measurements, the layer switches — is saved
automatically a moment after each change, in a small `IMAGE.atlas.json` file beside the photo. It
survives closing the app, and the command-line `export` uses exactly the same edits.

The status bar says *saved* when it has been written. If a save ever fails, an export will refuse to
start and tell you why, rather than quietly exporting the wrong thing.

## In a small window

The panels fold themselves away when there is no room:

![The viewer in a small window](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-narrow.jpg)

## Next

[Exporting](Exporting) — turning this into a picture you can keep.
