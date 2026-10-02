IAU feature names on your own photo of the Moon. Drop a photo on the window and the names appear — no
coordinates, no plate solving, no calibration.

**[Full manual](https://github.com/kvandebeek/lunaratlas/wiki)** · [Your first photo](https://github.com/kvandebeek/lunaratlas/wiki/Your-first-photo) · [Troubleshooting](https://github.com/kvandebeek/lunaratlas/wiki/Troubleshooting)

<!-- Before publishing: add a "## What is new in {VERSION}" section here, in plain language. -->

## Which file

| Your computer | Download |
|---|---|
| **macOS**, Apple silicon (M1 and later) | `LunarAtlas-{VERSION}-macos-arm64.dmg` |
| **macOS**, Intel | `LunarAtlas-{VERSION}-macos-x64.dmg` |
| **Windows**, 64-bit | `LunarAtlas-{VERSION}-windows-setup.exe` |
| **Linux**, 64-bit | `LunarAtlas-{VERSION}-linux-x64.tar.gz` |

Not sure which Mac you have? Apple menu → **About This Mac**. "Apple M1" or later is `arm64`, "Intel" is `x64`.

## macOS: the first start needs your permission

These builds are not signed with a paid Apple certificate, so macOS stops the first launch. It is the
standard warning for any unsigned app. You allow it **once**, and never again.

1. Open the `.dmg` and drag **LunarAtlas** to **Applications**.
2. Open **Applications** and double-click **LunarAtlas**. macOS refuses: *"LunarAtlas cannot be opened
   because it is from an unidentified developer"*. Press **Done** or **Cancel**.
3. Open the Apple menu → **System Settings** → **Privacy & Security**.
4. Scroll down to the **Security** section. There is a line saying *"LunarAtlas was blocked from use
   because it is not from an identified developer"*, with an **Open Anyway** button. Press it.
5. Confirm with **Open**, and your password or Touch ID if asked.

LunarAtlas starts, and every later launch is normal.

> **A faster way, if you prefer the terminal:**
> ```sh
> xattr -dr com.apple.quarantine /Applications/LunarAtlas.app
> ```

On **macOS 15 Sequoia and later** the Open Anyway button appears only *after* you have tried to open the
app and been refused, so do step 2 first.

## Windows: SmartScreen

*"Windows protected your PC"*, naming the publisher as unknown and advising you not to run it. Press
**More info**, then **Run anyway**. Once, on the installer. Same reason: no paid certificate.

Neither warning says anything about whether the app is safe — only that nobody has paid a certificate
authority to vouch for the publisher. If you would rather not take that on trust, check the download
against `SHA256SUMS.txt` below, or build it yourself: the whole thing is on GitHub.

## Checking your download

Put `SHA256SUMS.txt` next to the file you downloaded:

```sh
shasum -a 256 --ignore-missing -c SHA256SUMS.txt      # macOS
sha256sum --ignore-missing -c SHA256SUMS.txt          # Linux
```

```powershell
Get-FileHash LunarAtlas-{VERSION}-windows-setup.exe   # Windows; compare with the line in SHA256SUMS.txt
```

You want to see `OK` for your file. `--ignore-missing` matters: the file lists all four downloads, and
without it the three you did not download are reported as FAILED, which looks alarming and is not.

## First run

The first photo downloads about 145 MB of Moon maps, once; the first close-up about 530 MB more. After
that LunarAtlas works offline. Exports go to `Pictures/LunarAtlas`.

**Every commit in this release:** https://github.com/kvandebeek/lunaratlas/commits/{TAG}
