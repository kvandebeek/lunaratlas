# LunarAtlas Bugs and Design Choices

## Bugs to Fix

### 1. Dashed line visibility when dragging names
When using the Pan and Select tool, dragging a name on the lunar map creates a dashed line that shows where that name belongs to, but when letting it go, the name will simply be moved and the dashed line is no longer shown.

**Status:** Fixed. Every moved name keeps a dashed amber line to its feature, drawn with a dark edge so it reads on bright ground. It ends at the edge of the name and is left out when the name sits within 6 px of its feature. It is drawn in exports too. Screenshot: `design/screenshots/25-viewer-moved-name-dashed-arrow.png`.

### 2. Disable 'Lettered craters' toggle when 'Craters' is disabled
When disabling the "Craters" layer, the "Lettered craters" toggle is still active. It should be disabled (greyed out) but preserve its state for when "Craters" is re-enabled.

**Status:** Fixed. With Craters off, the Lettered craters switch and its row are greyed out and no lettered names are drawn, in the viewer or in exports. The switch keeps its own setting, which is saved and applies again when Craters comes back on. Screenshot: `design/screenshots/26-viewer-craters-off.png`.

### 3. Clarify Pan and Select requirement for editing measurements
In order to delete or edit a line drawn by the user, the user needs to select the "Pan and Select" tool, but this is not clear from the instructions. The tooltip says "click the line to adjust or delete it" but doesn't mention the tool requirement.

**Possible solutions:**
- Update the tooltip to mention the Pan and Select requirement
- Auto-switch to the Pan and Select tool when the user tries to click a saved measurement

**Status:** Fixed (auto-switch). With the Measure tool active and no measurement half-drawn, a click on a saved measurement or one of its handles switches to Pan and Select and picks it up. The toast now says "click the line to adjust or delete it (switches to Pan and select)".

### 4. Make arrow tips solid on dashed lines
When drawing dashed arrow lines, the arrow tip (arrowhead) is also dashed, which looks broken. The arrowhead should be solid even when the line is dashed to maintain clarity of direction.

**Status:** Fixed. Only the shaft of a dashed arrow is dashed; the head is always solid. Screenshot: `design/screenshots/25-viewer-moved-name-dashed-arrow.png`.

Checks for all four are in the `fixes` group of `lunaratlas/tests/viewer_selftest.js`, run by `test_e2e_journeys.py`.

---

## Design Choices to Make

### 1. Grid overlay: Transparency vs. Prefilled Data
The lat/lon grid overlay should either be:
- **Transparent (wireframe only)**: Just coordinate lines, clean and minimal, doesn't distract from the photo
- **Prefilled with data**: Show something inside the grid cells, such as:
  - The underlying moon map/albedo data
  - Elevation or terrain data visualization
  - A subtle animation/texture to show reference coverage
  - Tile load indicators

**Decision:** Lines only (the current grid). The photo is the content: filled cells would cover detail and compete with the names, albedo or elevation fills would need extra data sources, and tile-load indicators show the app's internals rather than anything a user needs. A possible later addition is a slightly heavier equator and central meridian.

**Status:** Decided.
