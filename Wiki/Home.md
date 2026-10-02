# LunarAtlas 1.0.0

LunarAtlas puts the official (IAU) names of craters, seas and mountains on **your own** photo of the
Moon. Think of LROC QuickMap, but with your picture instead of a spacecraft mosaic.

![The viewer with a full disk named](https://raw.githubusercontent.com/wiki/kvandebeek/lunaratlas/images/viewer.jpg)

You drop in a photo. LunarAtlas works out, by itself, where on the Moon it points, which way round it
is, whether it is mirrored, and how the Moon was tilted that night. Then it names what it sees, and you
can look around, measure, draw, and export a labelled picture.

It handles full disks, any phase, mosaics, and close-ups that do not show the edge of the Moon at all.

---

## Start here

| | |
|---|---|
| **[Installing](Installing)** | Download the app for macOS, Windows or Linux, and get past the first-start warning. |
| **[Your first photo](Your-first-photo)** | Drop a photo in, and understand what it tells you while it works. |
| **[The viewer](The-viewer)** | Look around, search, measure, draw, and change which names you see. |
| **[Exporting](Exporting)** | Turn what you see into a labelled image to keep or share. |

## When something is different

| | |
|---|---|
| **[Close-ups and your equipment](Close-ups-and-equipment)** | Photos without the Moon's edge in them, and why LunarAtlas asks what took them. |
| **[The quality check](The-quality-check)** | Why a photo can be refused, what each reason means, and how to override it. |
| **[Troubleshooting](Troubleshooting)** | It will not start, it cannot find the Moon, the download fails. |
| **[Testing](Testing)** | 1.0.1 is a first release. What to try, and what is most useful to report. |
| **[Limits](Limits)** | What LunarAtlas does not do, honestly. |

## Going deeper

| | |
|---|---|
| **[The command line](The-command-line)** | Every command and option, for batches and scripting. |
| **[How it works](How-it-works)** | Limb fit, orientation search, terrain matching, and how accurate it is. |
| **[Settings reference](Settings-reference)** | Every setting, where it lives and what it does. |
| **[Files and folders](Files-and-folders)** | Where your photos, exports, downloads and caches are kept. |
| **[Credits and licences](Credits-and-licences)** | The data and fonts LunarAtlas uses, and who made them. |
| **[Release notes](Release-notes)** | What is in 1.0.0. |

---

## What you need

A photo of the Moon, as a TIFF, PNG or JPEG. Nothing else: no coordinates, no plate solving, no
calibration. A capture time helps, and is required for close-ups — see
[Close-ups and your equipment](Close-ups-and-equipment).

The first photo downloads about **145 MB** of Moon maps, once. The first close-up downloads about
**530 MB** more, also once. After that LunarAtlas works offline.

## What it is not

It is not a stacker, a sharpener or a mosaic builder. Feed it a finished picture. If you build gigapixel
mosaics, [LunarMosaic](https://github.com/kvandebeek/lunarmosaic) is the companion project that makes
them; LunarAtlas annotates them.
