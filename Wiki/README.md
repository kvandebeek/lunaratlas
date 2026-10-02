# Wiki source

The source of the [LunarAtlas wiki](https://github.com/kvandebeek/lunaratlas/wiki) — the user manual for
the app. It lives here so it is reviewed, versioned and changed alongside the code it describes.

Edit these files, not the wiki pages on GitHub: a publish overwrites whatever is there.

| | |
|---|---|
| `Home.md` | The wiki's landing page. |
| `_Sidebar.md`, `_Footer.md` | Navigation, shown on every page. |
| `*.md` | One page each. The file name is the page name and the link target: `The-viewer.md` is linked as `[The viewer](The-viewer)`. |
| `images/` | Screenshots and example exports. Pages link them by their **raw wiki URL** (`https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/NAME.png`), because a relative `images/NAME.png` does not resolve on a rendered wiki page — GitHub leaves it relative to `/wiki/PAGE`, which serves HTML, and the image breaks. The raw URL works both on the wiki and when browsing this folder on GitHub. |

## Publishing

The wiki is a git repository of its own. It can only be cloned after the first page has been created in
the web UI (Wiki tab → Create the first page → Save).

```sh
git clone https://github.com/kvandebeek/lunaratlas.wiki.git /tmp/lunaratlas.wiki
rsync -a --delete --exclude .git Wiki/ /tmp/lunaratlas.wiki/
cd /tmp/lunaratlas.wiki && git add -A && git commit -m "Manual for 1.0.0" && git push
```

## Taking the screenshots again

The screenshots are real: headless Chrome driven through the DevTools protocol over a pipe, against the
real pages, with real photos. Nothing is mocked except the progress and failure states, which are driven
with a realistic log so they can be shown without waiting for a download or a failing photo.

[`design/shoot.mjs`](../design/shoot.mjs) is the equivalent script for the design screenshots and is the
best starting point. Start the app on a work folder with a token of your choosing, then drive it:

```sh
LUNARATLAS_TOKEN=shoot python3 lunaratlas/lunaratlas.py app \
  --no-open --no-window --port 8791 --folder WORKFOLDER
LUNARATLAS_TOKEN=shoot node design/shoot.mjs http://localhost:8791 OUT_DIR WORKFOLDER
```

It needs Chrome and Node 22 or newer, and no packages. It expects particular photo names, so adjust them
for your own.

Two things to watch for when regenerating:

- **Clear the sidecars' `edits`** in the work folder first, or drawings from an earlier run appear in the
  next one's screenshots.
- **Do not shoot the Settings page against your real `equipment.json`** — it shows your observing site.
  Point `LUNARATLAS_EQUIPMENT` at a copy with example coordinates.

Screenshots are saved at 1440 px wide; anything over 400 kB as PNG is converted to JPEG at quality 92.

## Writing

The audience is someone who downloaded the app and has a photo, not someone who has read the code. Say
what a thing is for before saying what it is called. Keep the honest limits in — they are
[a page of their own](Limits.md) for a reason.
