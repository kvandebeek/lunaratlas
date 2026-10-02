# Your first photo

Start LunarAtlas. You get one window with one thing to do.

![The LunarAtlas window when it opens](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/home.png)

## 1. Give it a photo

Drag a photo onto the window, or click the drop zone and pick one. TIFF, PNG and JPEG are accepted; the
picture may be a full disk, a crescent, a mosaic, or a close-up of one crater.

![Dragging a photo onto the window](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/home-drag-over.png)

Use your **finished** picture: stacked, sharpened, the one you would otherwise publish. A single unstacked
video frame usually has too little real detail to match, and oversharpening actively hurts — see
[The quality check](The-quality-check).

### Where your photo goes

A browser hands a page the contents of a file, not its location on disk, so LunarAtlas copies your photo
into its own work folder (`Pictures/LunarAtlas`) and works there. Your original is never touched or moved.
Exports land next to the copy. [Files and folders](Files-and-folders) has the details.

Drop the same photo again and LunarAtlas recognises it — by its actual contents, not just its name — and
opens it immediately instead of locating it a second time. A *different* photo that happens to have the
same name gets a copy of its own, `NAME (2).tif`, and the first one is left alone.

## 2. When was it taken?

If the file name carries a capture time — as SharpCap and WinJUPOS write it,
`2026-10-01-2323_4-Moon…` — LunarAtlas reads it and does not ask.

Otherwise it asks, and fills in the camera's own EXIF time if the file has one:

![A photo with no capture time in its name](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/home-asks-when.png)

Give it **your local time**; LunarAtlas converts. It matters because:

- for a **close-up** it is required — without it there is no way to know how the Moon was lit or tilted;
- for a **full disk** it is optional but makes the result a little more exact. Without one, LunarAtlas
  works out the lighting from the terminator in the picture itself.

If you do not know, leave it empty. Cameras are often set to the wrong time zone or never set at all, so
check the prefilled value rather than trusting it.

Then press **Find the names**.

## 3. While it works

![Progress on the first photo](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/progress-first-run.png)

The stages are named, so you can see what is happening:

| Stage | What it is doing |
|---|---|
| Loading the photo | Reading the image and measuring its quality. |
| Reading date and libration | Working out where the Sun was and how the Moon was tilted. |
| Downloading Moon maps | **First run only.** The reference maps, with real megabytes counted. |
| Searching the Moon | Finding the edge, the orientation, and the matching terrain. |
| Refining the fit | The same match again on larger copies, for precision. |
| Opening the viewer | Building the zoom pyramid. Large mosaics take a minute here, once. |

On later photos the download stage is skipped and says so:

![Progress on a later photo](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/progress-searching.png)

A full disk typically takes 10–20 seconds; a close-up 30–100 seconds, and the first close-up of a session
longer while it tries the possible image scales.

**Details** opens the raw log, with a Copy button. You will want this if you ever report a problem.

![The details log](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/progress-details.png)

## 4. Two things that can stop it

**The quality check refused the photo.** LunarAtlas tells you what it found, in plain language, and offers
**Name it anyway**:

![A photo refused by the quality check](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/quality-refused.png)

Read [The quality check](The-quality-check) before you override it: the reasons are usually worth acting on.

**The Moon could not be found.**

![The Moon could not be found](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/not-found.png)

Most often this is a close-up with no capture time, or with the wrong equipment assumed. See
[Close-ups and your equipment](Close-ups-and-equipment) and [Troubleshooting](Troubleshooting).

## 5. The viewer opens

![The viewer](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer.jpg)

That is it — your photo is now a map. Carry on with [The viewer](The-viewer), or go straight to
[Exporting](Exporting).

Press **Other image** at the top left to come back and open another photo. Earlier photos are listed on
the home page with their thumbnail, capture time and whether they were located, so you can reopen any of
them in one click.
