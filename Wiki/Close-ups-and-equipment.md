# Close-ups and your equipment

A photo that shows the edge of the Moon is easy: the edge is a circle, and a circle tells LunarAtlas
almost everything — where the Moon's centre is, how big it is, which way it is turned.

A close-up has no edge. A crop around Copernicus is just grey terrain. To place it, LunarAtlas has to
search the whole Earth-facing hemisphere for the patch that matches — and to do that it needs two
things from you.

## 1. When it was taken

Required, no exception. The capture time fixes how the Moon was lit and how it was tilted that night
(libration), and both change what the terrain looks like.

It comes from the file name when SharpCap or WinJUPOS wrote one (`2026-10-01-2323_4-Moon…`), from the
camera's EXIF, or from you. See [Your first photo](Your-first-photo).

## 2. What took it

The scale of the picture — how many kilometres one pixel covers — narrows the search enormously. The
first time you open a close-up, LunarAtlas asks:

![The equipment question](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/equipment-asked.png)

- **Telescope** — a name you will recognise, and its focal length in mm *without* a barlow.
- **Barlow** — none, a standard factor, or your own. A barlow's real factor depends on how far it sits
  from the camera, so LunarAtlas searches 15 % either side of what you give.
- **Camera** — search by model or by sensor:

![Searching for the camera](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/equipment-camera.png)

  A camera that is not in the list needs only its pixel size in µm. Set the binning if you binned.

As you fill it in, the line at the bottom shows the resulting scale in arcseconds per pixel, so you can
sanity-check it against what you know.

You are asked **once**. Later close-ups use the same answer, with a "Taken with" choice if you own more
than one setup. Full-disk photos never ask.

**Not sure?** Press *Not sure: search every scale*. It works — it is simply slower, because every scale
you own has to be tried.

Once it is placed, a close-up behaves like any other photo:

![A close-up named](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer-closeup.jpg)

## Settings

Everything is editable afterwards from **Settings**, at the bottom of the home page.

![Settings](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/settings.png)

Add as many telescopes, barlows and cameras as you own. LunarAtlas then combines them.

### Your setups

![Your setups](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/settings-setups.png)

Every telescope × barlow × camera combination, with its focal length, image scale, field of view, and how
much Moon it shows. **Untick the ones you never use** — each setup left ticked is another scale to
search, so close-ups are found faster when the list is honest.

### Your observing site

![The observing site](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/settings-site.png)

Optional. Where you are on Earth shifts how the Moon is tilted, by up to about 1° (parallax). Leave it
empty and LunarAtlas computes from the Earth's centre, which is close enough for most photos.

**Use my location** rounds to 0.1°, about 10 km. Your location is stored only in your own settings file
on your own computer: it is never sent anywhere, and never written into an exported image, its metadata,
or the info block.

## Where this is kept

In `equipment.json` in your LunarAtlas data folder ([Files and folders](Files-and-folders)). The command
line reads the same file, so the app and the terminal always agree. **Reset equipment** at the bottom of
Settings forgets all of it.

## How long a close-up takes

20–100 seconds, typically. The first close-up of a new setup is the slow one, because the detailed
elevation model (≈ 530 MB) is downloaded then, and more scales have to be tried. Later close-ups with
known optics search only a few scales and are quicker.

## When a close-up is not found

The page offers two ways on:

- **Try every scale** — in case the equipment answer was wrong;
- **It was another setup…** — to pick or add a different one.

If neither works, see [Troubleshooting](Troubleshooting) and [Limits](Limits). Some photos genuinely
cannot be placed: a featureless mare at low resolution has nothing to match, and LunarAtlas would rather
say so than guess.
