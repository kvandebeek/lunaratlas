# Installing

LunarAtlas comes as an ordinary app. You do not need Python, a terminal, or any other software.

Get it from the **[releases page](https://github.com/kvandebeek/lunaratlas/releases)**.

| Your computer | Download | What to do |
|---|---|---|
| **macOS**, Apple silicon | `LunarAtlas-1.0.0-macos-arm64.dmg` | Open it, drag **LunarAtlas** to Applications. |
| **macOS**, Intel | `LunarAtlas-1.0.0-macos-x64.dmg` | The same. |
| **Windows** | `LunarAtlas-1.0.0-windows-setup.exe` | Run it. It installs for you alone and needs no administrator rights. |
| **Linux**, 64-bit | `LunarAtlas-1.0.0-linux-x64.tar.gz` | Unpack it, then run `./LunarAtlas`, or `./install.sh` to get a menu entry. |

Not sure which Mac you have? Apple menu → **About This Mac**. "Apple M1" or later means `arm64`;
"Intel" means `x64`.

## The first start warns you

The builds are not signed with a paid developer certificate, so both macOS and Windows will stop you the
first time. This is the standard warning for any unsigned app, not a sign that anything is wrong.

- **macOS** says *"LunarAtlas cannot be opened because it is from an unidentified developer"*. Open
  **System Settings → Privacy & Security**, scroll down, and press **Open Anyway**. You do this once.
- **Windows** shows *"Windows protected your PC — Microsoft Defender SmartScreen prevented an
  unrecognised app from starting"*, naming the publisher as unknown and advising you not to run it.
  Press **More info**, then **Run anyway**. Once, on the installer.

Both warnings mean the same thing: nobody has paid a certificate authority to vouch for the publisher.
Neither checks whether the app is safe. If you would rather not take that on trust, verify the download's
checksum below, or build it yourself from source — the whole thing is on GitHub.

> **"LunarAtlas is damaged and can't be opened"** on macOS is a *different* message, and **Open Anyway
> will not help**. It means the app's seal does not validate. Versions built before 1.0.1 had a broken
> seal on the unsigned macOS builds; update to the current release. If you must run an affected build:
> `xattr -dr com.apple.quarantine /Applications/LunarAtlas.app`

If you would rather check the download first, every release has a `SHA256SUMS.txt`. Put it next to the
file you downloaded, then:

```sh
shasum -a 256 --ignore-missing -c SHA256SUMS.txt      # macOS
sha256sum --ignore-missing -c SHA256SUMS.txt          # Linux
```

```powershell
Get-FileHash LunarAtlas-1.0.0-windows-setup.exe       # Windows; compare with the line in SHA256SUMS.txt
```

You want to see `OK` for your file. `--ignore-missing` matters: the file lists all four downloads, and
without it the three you did not download are reported as **FAILED**, which looks alarming and is not.

## What happens on the first photo

LunarAtlas downloads its reference data the first time it needs it, and never again:

| | Size | When |
|---|---|---|
| The IAU list of names | ≈ 24 MB | first photo |
| LROC WAC albedo map | ≈ 88 MB (4 parts) | first photo |
| LOLA elevation model, 16 px/degree | ≈ 33 MB | first photo |
| LOLA elevation model, 64 px/degree | ≈ 530 MB | first **close-up** only |

So the first full-disk photo needs about 145 MB and an internet connection. After that you can work
offline, until the first close-up asks for the detailed elevation model.

[Files and folders](Files-and-folders) says where all of this is kept, and how to remove it again.

## Running it from the source instead

If you would rather not use the packaged app, a checkout works the same way. You need Python 3.14 with
numpy, OpenCV and Pillow:

```sh
git clone https://github.com/kvandebeek/lunaratlas
cd lunaratlas
python3 -m pip install -r requirements.txt
python3 lunaratlas/lunaratlas.py app          # the same window the app opens
```

Everything in this manual applies either way. See [The command line](The-command-line) for what else a
checkout gives you, and [`packaging/`](https://github.com/kvandebeek/lunaratlas/tree/main/packaging) if
you want to build the app yourself.

## Uninstalling

Delete the app (macOS: drag it from Applications to the Bin; Windows: Add or remove programs; Linux:
delete the unpacked folder). That leaves your photos, exports and the downloaded maps alone —
[Files and folders](Files-and-folders) lists them so you can remove those too if you want the space back.
