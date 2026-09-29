# LunarAtlas UI: screenshots for design review

Screens and states of the LunarAtlas desktop app after the redesign to match the app icon. Taken at 1440 × 900 (2× pixel
density) unless the name says otherwise, in headless Chrome on the real pages with real photos. The app itself runs in
a native window (WebKit on macOS, WebView2 on Windows) showing these same pages.

## Screens

| File | What it shows |
|---|---|
| [`01-home.png`](screenshots/01-home.png) | Home: hero (icon, name, tagline), drop zone with drawn crescent + grid, earlier photos with thumbnail, capture time, solve status, Open button |
| [`02-home-drop-focus.png`](screenshots/02-home-drop-focus.png) | Drop zone with keyboard focus (amber focus ring) |
| [`03-home-drag-over.png`](screenshots/03-home-drag-over.png) | Drag-over state: solid amber border, amber tint, "Release to open this photo" |
| [`04-home-row-hover.png`](screenshots/04-home-row-hover.png) | Earlier photos: row hover (whole row is clickable; explicit Open button kept) |
| [`05-home-photo-chosen.png`](screenshots/05-home-photo-chosen.png) | A photo chosen without a time stamp in its name: asks when it was taken |
| [`06-progress-downloading.png`](screenshots/06-progress-downloading.png) | Progress, first run: named stages; "Downloading Moon maps" shows real MB (per file and in total) |
| [`07-progress-searching.png`](screenshots/07-progress-searching.png) | Progress, later runs: the download stage is skipped ("already on this computer") |
| [`08-progress-details-open.png`](screenshots/08-progress-details-open.png) | Details (the raw log) expanded: monospace, Copy button |
| [`09-progress-quality-refused.png`](screenshots/09-progress-quality-refused.png) | Quality refused: plain-language reasons (raw measurement below each), "Name it anyway" |
| [`10-progress-error.png`](screenshots/10-progress-error.png) | Failure: plain-language title and advice; raw text stays in Details |
| [`11-viewer.png`](screenshots/11-viewer.png) | Viewer: brand icon in the top bar, tool rail in groups, Layers panel with amber switches and right-aligned counts, split status bar (cursor lat/lon + km/px | zoom, Fit, 1:1, Export) |
| [`12-viewer-grid.png`](screenshots/12-viewer-grid.png) | Lat/lon grid in cyan; degree labels only where they collide with no name and no other label |
| [`13-viewer-tool-tooltip.png`](screenshots/13-viewer-tool-tooltip.png) | Tool rail tooltip: tool name + shortcut; active tool = amber fill + side marker |
| [`14-viewer-zoomed-labels.png`](screenshots/14-viewer-zoomed-labels.png) | Zoomed in: names placed by priority (type, then size), colliding lower-priority names hidden; they fade in as you zoom |
| [`15-viewer-feature-card.png`](screenshots/15-viewer-feature-card.png) | A name selected: amber crater outline, info card |
| [`16-viewer-arrow-popover.png`](screenshots/16-viewer-arrow-popover.png) | Annotation popover: anchored beside the arrow with a pointer, never over it; suggested names as chips |
| [`17-export-dialog.png`](screenshots/17-export-dialog.png) | Export dialog: tokens, selected cards = amber border on lighter navy, live preview thumbnail of the output |
| [`18-export-dialog-hover.png`](screenshots/18-export-dialog-hover.png) | Export dialog: hover on an unselected card |
| [`19-export-dialog-view-region.png`](screenshots/19-export-dialog-view-region.png) | Export dialog: "Current view" chosen, the preview follows |
| [`20-viewer-quality-chip.png`](screenshots/20-viewer-quality-chip.png) | A photo named despite the quality check: amber warning chip in the status bar instead of raw text |
| [`21-viewer-quality-popover.png`](screenshots/21-viewer-quality-popover.png) | Quality chip opened: friendly explanation, the raw measurement underneath |
| [`22-viewer-narrow.png`](screenshots/22-viewer-narrow.png) | Viewer at 960 × 680 |
| [`23-home-narrow.png`](screenshots/23-home-narrow.png) | Home at 960 × 680 |
| [`24-home-phone-width.png`](screenshots/24-home-phone-width.png) | Home at 420 px wide (drop zone stacks) |
| [`25-viewer-moved-name-dashed-arrow.png`](screenshots/25-viewer-moved-name-dashed-arrow.png) | A moved name keeps a dashed amber line (with a dark edge) to its feature; a dashed arrow keeps a solid head |
| [`26-viewer-craters-off.png`](screenshots/26-viewer-craters-off.png) | Craters off: "Lettered craters" is greyed out and keeps its own setting for when craters come back |

Screens 06–10 (progress and failures) are the real page driven with a realistic log, so every state can be shown
without waiting for a download or a failing photo. All other screens are live.

## Design tokens

All colours come from the icon (`packaging/icon/README.md`) and live in one file,
[`lunaratlas/viewer/theme.css`](../lunaratlas/viewer/theme.css); the canvas reads the same tokens.

| Token | Value | Use |
|---|---|---|
| `--bg-0` … `--bg-3` | `#0A0F25` `#111934` `#18224A` `#1F2C5A` | app background → panel → card → raised / selected |
| `--line`, `--line-strong` | white at 8 % / 16 % | 1 px borders |
| `--text`, `--text-2`, `--text-3` | `#FCF8EE` `#B7BFD8` `#97A1C2` | ivory text; 2 and 3 are ≥ 4.5:1 on every surface up to `--bg-3` |
| `--accent` (+ hover, press, soft) | `#F5A742` | the one accent: primary buttons, switches, selection, focus ring, crater outlines |
| `--grid` | `#8FD8EC` | lat/lon grid and its labels, "Solved" status |
| `--label` | `#FFF4E2` | names on the Moon (shared with the export renderer) |
| `--danger` | `#F08A7E` | errors only |

Font: IBM Plex Sans for the interface and (by default) the names; Source Sans 3 and Roboto are the alternatives. All
three are bundled with the app, so nothing is downloaded.

## Open questions for design

- **Names outside a close-up photo.** *Decided:* names are clipped at the photo's edge, as in an export, instead of
  being drawn on the navy background around it.
- **Viewer and export label density.** *Decided:* the export's layout uses the viewer's room around a name (padding for
  descenders and the shade, the same 4 px grid), so both hide the same crowded names. The viewer still fades names in,
  which an export has no use for, and it keeps clear of its own panels.
- **Several names picked (Alt/⌥)** are shown as a dashed amber outline, a single selection as a solid one. The old
  separate coral colour is gone.
- **"System UI" font** is not offered: the export renders names with bundled font files and cannot use it.

## Regenerating

With the app running on a work folder (`python3 lunaratlas/lunaratlas.py app --no-open --no-window --port 8791
--folder FOLDER`), `node design/shoot.mjs http://localhost:8791 OUT_DIR FOLDER` drives Chrome through every screen. It
needs Chrome and Node 22 or newer, and no packages. It expects the photo names used here, so adjust them for other
photos.
