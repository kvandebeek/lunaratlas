# PyInstaller spec for LunarAtlas: `python3 packaging/build.py` runs it (from any folder).
# One folder with two executables sharing the same libraries: LunarAtlas (windowed, the launcher) and lunaratlas-cli
# (console: what the launcher runs locate/export with, so their output reaches the page on Windows too).
# On macOS the folder becomes LunarAtlas.app.
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
SRC = os.path.join(ROOT, 'lunaratlas')
VERSION = os.environ.get('LUNARATLAS_VERSION', '0.1.0')
ICONS = os.path.join(SPECPATH, 'icon')                       # the icon set (icon/README.md)

a = Analysis(
    [os.path.join(SPECPATH, 'launcher.py')],
    pathex=[SRC, ROOT],
    datas=[(os.path.join(SRC, 'viewer', f), 'viewer')
           for f in ('index.html', 'app.html', 'viewer.js', 'viewer.css', 'theme.css', 'friendly.js', 'exif.js', 'lunaratlas.svg')]
          + [(os.path.join(SRC, 'fonts', fam, f), os.path.join('fonts', fam))          # bundled label fonts (OFL)
             for fam in sorted(os.listdir(os.path.join(SRC, 'fonts'))) if os.path.isdir(os.path.join(SRC, 'fonts', fam))
             for f in os.listdir(os.path.join(SRC, 'fonts', fam)) if f.endswith(('.ttf', '.txt'))],
    hiddenimports=['lunaratlas', 'atlas_app', 'atlas_view', 'atlas_closeup', 'atlas_ephem', 'atlas_geo', 'atlas_names',
                   'atlas_quality', 'atlas_render', 'atlas_paths', 'tool_settings', 'certifi'],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest', 'unittest.mock'],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LunarAtlas', console=False,
          argv_emulation=False, upx=False, icon=os.path.join(ICONS, 'windows', 'LunarAtlas.ico'))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='lunaratlas-cli', console=True, upx=False,
          icon=os.path.join(ICONS, 'windows', 'LunarAtlas.ico'))
coll = COLLECT(gui, cli, a.binaries, a.datas, name='LunarAtlas', upx=False)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='LunarAtlas.app',
        icon=os.path.join(ICONS, 'macos', 'LunarAtlas.icns'),
        bundle_identifier='io.github.kvandebeek.lunaratlas',
        version=VERSION,
        info_plist={
            'CFBundleDisplayName': 'LunarAtlas',
            'CFBundleShortVersionString': VERSION,
            'LSMinimumSystemVersion': '12.0',
            'NSHighResolutionCapable': True,
        },
    )
