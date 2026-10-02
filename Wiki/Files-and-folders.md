# Files and folders

Where LunarAtlas puts things, so you can find them, back them up, or delete them.

## Your photos and exports

| macOS | Windows | Linux |
|---|---|---|
| `~/Pictures/LunarAtlas` | `Pictures\LunarAtlas` | `~/Pictures/LunarAtlas` |

When you drop a photo on the app, a **copy** lands here. Your original is never touched or moved.
(A web page is handed a file's contents, not its path, so there is no way for the app to work in place.)

Each photo here is joined by:

| File | What it is |
|---|---|
| `NAME.tif` | The copy of your photo. |
| `NAME.tif.atlas.json` | Its position on the Moon, the quality of the fit, and all your viewer edits. |
| `NAME_atlas.tif` | An export of the whole picture. |
| `NAME_atlas_Copernicus.jpg` | An export around a feature. |

The sidecar is small, plain JSON, and safe to delete — you lose your edits and the photo has to be
located again. Keep the two together when you move a photo, and the app and the command line will both
pick up where you left off.

Open the folder from the app: the link at the bottom of the home page shows it in Finder, Explorer or
your Linux file manager.

The command line does not copy anything: it works on the file you name, and writes the sidecar and
exports beside it.

## The downloaded reference data

| macOS | Windows | Linux |
|---|---|---|
| `~/Library/Application Support/LunarAtlas` | `%LOCALAPPDATA%\LunarAtlas\Data` | `~/.local/share/lunaratlas` |

| In it | Size |
|---|---|
| IAU nomenclature | ≈ 24 MB |
| LROC WAC 643 nm albedo mosaic | ≈ 88 MB |
| LOLA elevation, 16 px/degree | ≈ 33 MB |
| LOLA elevation, 64 px/degree (close-ups only) | ≈ 530 MB |
| Fonts, quality thresholds | small |

Also here: `equipment.json` (your telescopes, cameras and observing site), `.env` if you use one, and
`lunaratlas.log`.

Deleting this folder costs you your equipment settings and means the maps are downloaded again. Nothing
else is lost.

Running from a checkout, the data goes to `lunaratlas/data/` instead. `LUNARATLAS_DATA` overrides it
either way.

## The tile cache

| macOS | Windows | Linux |
|---|---|---|
| `~/Library/Caches/LunarAtlas` | `%LOCALAPPDATA%\LunarAtlas\Cache` | `~/.cache/lunaratlas` |

The viewer's zoom pyramid, so that reopening a 200-megapixel mosaic does not decode it again. Rebuilt
automatically when a photo changes, and completely safe to delete at any time — it just costs you one
slow reopen.

**This is the folder to clear if you need disk space back in a hurry.**

## Privacy

Everything above is on your own computer.

- The viewer is a local server on `127.0.0.1`, reachable only from your machine, and only by pages that
  carry the token made at that start. Requests with a foreign `Host`, another site's `Origin`, or no
  token are refused, and only GET and POST are answered at all.
- Your **observing site** is stored in `equipment.json` and nowhere else. It is never sent anywhere, and
  never written into an exported image, its metadata, or the info block. "Use my location" rounds it to
  0.1°, about 10 km.
- Nothing about your photos, your account or your usage is sent anywhere. The only network traffic
  LunarAtlas ever makes is downloading the reference data listed above, from NASA and USGS, each file
  checked against a known SHA-256 and fetched only from an explicit list of allowed hosts.
