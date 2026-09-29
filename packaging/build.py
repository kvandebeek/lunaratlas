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
DIST, WORK = os.path.join(ROOT, 'dist'), os.path.join(ROOT, 'build')


def run(*cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


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

    if sys.platform == 'darwin':
        app = os.path.join(DIST, 'LunarAtlas.app')
        ident = os.environ.get('MACOS_SIGN_IDENTITY')     # "Developer ID Application: …" in the keychain; else unsigned
        if ident:
            run('codesign', '--force', '--deep', '--options', 'runtime', '--timestamp', '--sign', ident, app)
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
