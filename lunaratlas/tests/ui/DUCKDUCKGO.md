# DuckDuckGo browser: the manual check

DuckDuckGo's browser cannot be automated: it has no WebDriver or DevTools access. Its page engines are tested
already. On macOS it uses Apple's WebKit, the same engine as Safari (the `safari` job in `browsers.yml`). On Windows it
uses Microsoft's WebView2, the same engine as Edge (the `edge` job). What remains is its own privacy layer: tracker
blocking, cookie and storage limits, and the "Fire" button that clears site data. Check it by hand before a release,
on macOS and on Windows, about ten minutes each.

Start the viewer with `python3 lunaratlas/lunaratlas.py view IMAGE --no-open` and open the printed
`http://127.0.0.1:…` address in DuckDuckGo. Then the launcher with `python3 lunaratlas/lunaratlas.py app --no-window`.

| # | Do | Expect |
|---|---|---|
| 1 | Open the viewer | The Moon, the names and the panels appear; no "blocked" shield count for the page |
| 2 | Search "Tycho", press Enter | The card opens and the view flies there |
| 3 | Draw a circle, label it, Done; reload the page | The circle is still there ("edits loaded" in the status bar) |
| 4 | Measure between two points | A distance in km, kept after a reload |
| 5 | Drag a name, then Undo (⌘Z / Ctrl+Z) | It moves with the mouse and goes back |
| 6 | Turn Craters off and on in Layers | The crater names go and come back |
| 7 | Export as PNG at 1:2, then "Show in Finder / Explorer" | The file is written; the file manager opens on it |
| 8 | Launcher: drop a photo on the page, "Find the names" | Progress, then the viewer opens by itself |
| 9 | Launcher: click the drop zone | The system file chooser opens |
| 10 | Use the Fire button on the tab, open the viewer again | The page works; the edits come back from the sidecar, not the browser |
| 11 | Leave the launcher tab in the background for a minute | It keeps running (its 20 s ping is not throttled into an idle exit) |

Record the DuckDuckGo version, the system and anything that differs from the table in the release notes.
