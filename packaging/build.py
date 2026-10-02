"""Build the LunarAtlas app for this platform into dist/:

    macOS    dist/LunarAtlas-VERSION-macos-ARCH.dmg   (LunarAtlas.app, drag to Applications)
    Windows  dist/LunarAtlas-VERSION-windows-setup.exe with Inno Setup's iscc on PATH, else a .zip of the folder
    Linux    dist/LunarAtlas-VERSION-linux-ARCH.tar.gz (the folder, a .desktop file and install.sh)

    python3 -m pip install -r packaging/requirements-build.txt
    python3 packaging/build.py [--version 1.2.3]

macOS signing and notarisation are optional: MACOS_SIGN_IDENTITY (a Developer ID Application identity in the keychain)
signs the app, and with MACOS_NOTARY_PROFILE (from `xcrun notarytool store-credentials`) the .dmg is notarised too.
Unsigned, macOS asks the user to allow the app once (System Settings > Privacy & Security > Open Anyway).

A build runs on the platform it is for (PyInstaller does not cross-compile); .github/workflows/build-app.yml
builds all three.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)         # notices.py, next to this file: importable whether run as a script or loaded by
import notices  # noqa: E402      # path (as the tests do), from any working directory
DIST, WORK = os.path.join(ROOT, 'dist'), os.path.join(ROOT, 'build')


def run(*cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


MACHO_MAGIC = {b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe'}


def signables(app):
    """What codesign must sign inside an .app, innermost first: every Mach-O file and every nested bundle (.framework,
    .app), so that each seal covers code that is already sealed. (codesign --deep signs in no defined order and is
    deprecated for signing.) The app itself is signed last, by the caller."""
    found = []
    for root, dirs, files in os.walk(app):
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            try:
                with open(path, 'rb') as fh:
                    if fh.read(4) in MACHO_MAGIC:
                        found.append(path)
            except OSError:
                pass
        for name in dirs:
            if name.endswith(('.framework', '.app', '.xpc', '.bundle')) and not os.path.islink(os.path.join(root, name)):
                found.append(os.path.join(root, name))
    return sorted(found, key=lambda p: (-p.count(os.sep), p))


def seal_macos(app, ident):
    """Seal the .app, always — with a Developer ID when there is one, else ad-hoc.

    PyInstaller ad-hoc signs the bundle as it builds it, and writing THIRD-PARTY-NOTICES.txt into
    Contents/Resources afterwards adds a file the seal does not cover, which invalidates it. macOS refuses a
    quarantined app whose seal does not validate with "LunarAtlas is damaged and can't be opened", and no
    "Open Anyway" gets past that — unlike the ordinary unidentified-developer warning an ad-hoc signed app
    gets, which the user can allow once. So the bundle is sealed again here, after everything is in place.
    `--timestamp` and `--options runtime` need a real identity and are left off the ad-hoc path."""
    if ident:
        for path in signables(app):
            run('codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', ident, path)
        run('codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', ident, app)
    else:
        run('codesign', '--force', '--sign', '-', app)
    run('codesign', '--verify', '--strict', '--verbose=2', app)     # fails the build if anything is unsealed


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', default=os.environ.get('LUNARATLAS_VERSION', '0.1.0'))
    a = p.parse_args()
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine().lower(),
                                                                                     platform.machine().lower())
    env = dict(os.environ, LUNARATLAS_VERSION=a.version)
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', DIST, '--workpath', WORK,
        os.path.join(HERE, 'lunaratlas.spec'), env=env)
    folder = os.path.join(DIST, 'LunarAtlas')
    base = os.path.join(DIST, f'LunarAtlas-{a.version}')

    # compliance: every dependency's licence must travel with the binaries, and a GPL-only codec library (which
    # opencv-python's default wheel can bundle, although LunarAtlas does no video I/O) must not ship at all.
    # macOS wraps `folder`'s contents into LunarAtlas.app (data under Contents/Resources, libraries under
    # Contents/Frameworks): check and write notices there too, since that is what is actually distributed.
    check_folders = [folder]
    if sys.platform == 'darwin':
        check_folders.append(os.path.join(DIST, 'LunarAtlas.app'))
    for cf in check_folders:
        notices.collect(os.path.join(cf, 'THIRD-PARTY-NOTICES.txt') if cf == folder
                        else os.path.join(cf, 'Contents', 'Resources', 'THIRD-PARTY-NOTICES.txt'))
        if not os.environ.get('LUNARATLAS_ALLOW_GPL_CODECS'):
            notices.check_forbidden(cf)

    if sys.platform == 'darwin':
        app = os.path.join(DIST, 'LunarAtlas.app')
        ident = os.environ.get('MACOS_SIGN_IDENTITY')     # "Developer ID Application: …" in the keychain; else ad-hoc
        seal_macos(app, ident)                            # always: the notices file above broke PyInstaller's seal
        out = f'{base}-macos-{arch}.dmg'
        if os.path.exists(out):
            os.remove(out)
        # the disk image's contents: the app and a link to /Applications to drag it onto. Staged in a temporary
        # folder that is removed again, so no second copy of the app lingers for macOS to find and start
        with tempfile.TemporaryDirectory(prefix='lunaratlas-dmg-') as stage:
            shutil.copytree(app, os.path.join(stage, 'LunarAtlas.app'), symlinks=True)
            os.symlink('/Applications', os.path.join(stage, 'Applications'))
            run('hdiutil', 'create', '-volname', 'LunarAtlas', '-srcfolder', stage, '-ov', '-format', 'UDZO', out)
        if ident and os.environ.get('MACOS_NOTARY_PROFILE'):   # xcrun notarytool store-credentials PROFILE
            run('codesign', '--force', '--timestamp', '--sign', ident, out)
            run('xcrun', 'notarytool', 'submit', out, '--keychain-profile', os.environ['MACOS_NOTARY_PROFILE'], '--wait')
            run('xcrun', 'stapler', 'staple', out)
    elif sys.platform == 'win32':
        iscc = shutil.which('iscc') or next((p for p in (r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
                                                         r'C:\Program Files\Inno Setup 6\ISCC.exe') if os.path.exists(p)), None)
        if iscc:
            run(iscc, f'/DVersion={a.version}', f'/DSource={folder}', f'/O{DIST}',
                f'/FLunarAtlas-{a.version}-windows-setup', os.path.join(HERE, 'windows', 'lunaratlas.iss'))
            out = f'{base}-windows-setup.exe'
        else:
            print('Inno Setup (iscc) not found: making a .zip instead of an installer')
            out = shutil.make_archive(f'{base}-windows-{arch}', 'zip', DIST, 'LunarAtlas')
    else:
        linux = os.path.join(HERE, 'linux')
        for f in ('lunaratlas.desktop', 'install.sh'):
            shutil.copy(os.path.join(linux, f), folder)
        shutil.copytree(os.path.join(HERE, 'icon', 'linux', 'hicolor'), os.path.join(folder, 'icons', 'hicolor'),
                        dirs_exist_ok=True)
        os.chmod(os.path.join(folder, 'install.sh'), 0o755)
        out = f'{base}-linux-{arch}.tar.gz'
        with tarfile.open(out, 'w:gz') as t:
            t.add(folder, arcname='LunarAtlas')
    print(f'built {out}')


if __name__ == '__main__':
    main()
