#!/bin/sh
# Installs LunarAtlas for this user: the folder into ~/.local/share/lunaratlas/app, a menu entry and a
# `lunaratlas` command in ~/.local/bin. Run it from the unpacked folder: ./install.sh
set -e
src=$(cd "$(dirname "$0")" && pwd)
dest="${XDG_DATA_HOME:-$HOME/.local/share}/lunaratlas/app"
rm -rf "$dest"
mkdir -p "$dest" "$HOME/.local/bin" "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
cp -R "$src"/. "$dest"/
ln -sf "$dest/LunarAtlas" "$HOME/.local/bin/lunaratlas"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
mkdir -p "$icons"
cp -R "$src/icons/hicolor" "$icons/"                  # every size, and the SVG
sed "s|^Exec=.*|Exec=$dest/LunarAtlas|" "$src/lunaratlas.desktop" \
  > "${XDG_DATA_HOME:-$HOME/.local/share}/applications/lunaratlas.desktop"
echo "LunarAtlas is installed: find it in the applications menu, or run 'lunaratlas'."
