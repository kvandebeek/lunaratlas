# Troubleshooting

## The app will not open

**macOS: "LunarAtlas cannot be opened"** — the build is not signed. System Settings → Privacy &
Security → **Open Anyway**. Once. See [Installing](Installing).

**Windows: "Windows protected your PC"** — same thing. **More info** → **Run anyway**.

**Nothing happens when I start it again** — it is already running. LunarAtlas allows one copy at a time;
starting it again brings the existing window forward. If no window appears, use **Quit LunarAtlas** on
the page and start it again.

## "The Moon maps could not be downloaded"

The first run needs an internet connection, once, for about 145 MB (plus 530 MB at the first close-up).
Check the connection and try again — an interrupted download is resumed, not restarted from zero.

If you are behind a strict proxy or firewall, the downloads go to NASA and USGS hosts only.

## "The Moon could not be found in this photo"

In order of likelihood:

1. **A close-up with no capture time.** It cannot be placed without one. Open it again and fill in when
   it was taken. See [Close-ups and your equipment](Close-ups-and-equipment).
2. **The equipment is wrong.** Press **Try every scale**, or **It was another setup…**.
3. **Too little real detail.** A single unstacked frame, a heavy crop of a smooth mare, or a very small
   image may simply have nothing to match.
4. **A very thin crescent with no timestamp.** These are genuinely hard; see [Limits](Limits).
5. **It is not a photo of the Moon.** It happens.

## The photo was refused by the quality check

That is [the quality check](The-quality-check) doing its job. The reasons are given in plain language
with the measurement behind each. **Name it anyway** overrides it, and the photo keeps a warning
afterwards so you remember.

## The names are slightly off

- If the photo carries a quality warning, that is the most likely cause: a soft or over-sharpened limb
  costs precision.
- On the **unlit side**, names are extrapolated from the fit on the sunlit side and can be off by a few
  pixels. This is why night-side names are hidden by default.
- A close-up placed with the wrong scale will be obviously, not subtly, wrong — if things look plausible
  but shifted, it is precision, not a wrong match.

## It is taking a long time

| | |
|---|---|
| First photo ever | Downloading 145 MB of maps. Once. |
| First close-up ever | Downloading 530 MB more. Once. |
| First close-up of a setup | Every plausible scale is tried: 1.5–2 minutes. |
| Opening a large mosaic | The zoom pyramid is built once, then cached. |

If a close-up is always slow, untick the setups you never use in **Settings** — each one is another scale
to search.

## The viewer is slow or blank

- Clear the tile cache ([Files and folders](Files-and-folders)) and reopen; a half-built pyramid is
  rebuilt automatically, but clearing it is the quick fix.
- In browser mode, make sure you opened the address LunarAtlas printed, with its token. A page without
  the token is refused by design.

## An export did not appear

- Exports go to `Pictures/LunarAtlas`, beside the copy of the photo, not beside your original.
- If your drawings could not be saved, the export refuses to start and says so, rather than exporting
  something that does not match what you see.

## My equipment settings vanished

They live in `equipment.json` in the data folder ([Files and folders](Files-and-folders)). Deleting that
folder, or using `LUNARATLAS_DATA` to point somewhere else, gives you a fresh one.

## Reporting a problem

Open an issue at
[github.com/kvandebeek/lunaratlas/issues](https://github.com/kvandebeek/lunaratlas/issues) with:

- what you expected and what happened;
- the **Details** log from the progress page — there is a Copy button;
- your operating system and the LunarAtlas version;
- the photo, if you can share it, or at least its size and how it was taken.

Linux and Windows are built and tested automatically but have had far less real use than macOS, so
reports from those are especially welcome.
