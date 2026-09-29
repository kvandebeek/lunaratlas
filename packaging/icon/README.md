# LunarAtlas — app-icoon

Ontwerp A: sikkelmaan met selenografisch raster en plate-solve-markeringen.

## Inhoud
- `svg/` — vectormasters
  - `lunaratlas-macos.svg` — 1024 canvas met Apple-marge (voor macOS)
  - `lunaratlas.svg` — squircle vult het canvas (Windows, Linux, web)
  - `*-small.svg` — vereenvoudigde versie voor 16–32 px (dikkere lijnen, minder detail)
- `png/macos/` en `png/square/` — PNG's van 16 t/m 1024 px (≤32 px gebruikt automatisch de vereenvoudigde versie)
- `macos/LunarAtlas.icns` — klaar voor gebruik; `LunarAtlas.iconset/` om zelf te hergenereren met `iconutil -c icns LunarAtlas.iconset`
- `windows/LunarAtlas.ico` — 16, 24, 32, 48, 64, 128, 256 px
- `linux/hicolor/` — kopieer naar `~/.local/share/icons/hicolor/` (of `/usr/share/icons/hicolor/`) en gebruik `Icon=lunaratlas` in je `.desktop`-bestand

## Kleuren
- Achtergrond: #1F2C5A → #0A0F25
- Maan: #FCF8EE → #D8CEB8, schaduwzijde #26326A
- Raster: #8FD8EC
- Accent (solve-markeringen): #F5A742

## Framework-tips
- Electron: `icon` → `.icns` (mac), `.ico` (win), `png/square/lunaratlas-512.png` (linux)
- Tauri: `tauri icon svg/lunaratlas.svg` genereert alles, of wijs `bundle.icon` naar deze bestanden
