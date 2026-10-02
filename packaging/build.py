"""Build the LunarAtlas app for this platform into dist/:

    macOS    dist/LunarAtlas-VERSION-macos-ARCH.dmg   (LunarAtlas.app, drag to Applications)
    Windows  dist/LunarAtlas-VERSION-windows-setup.exe with Inno Setup's iscc on PATH, else a .zip of the folder
    Linux    dist/LunarAtlas-VERSION-linux-ARCH.tar.gz (the folder, a .desktop file and install.sh)

    python3 -m pip install -r packaging/requirements-build.txt
    python3 packaging/build.py [--version 1.2.3]

macOS signing and notarisation are optional: MACOS_SIGN_IDENTITY (a Developer ID Application identity in the keychain)
signs the app, and with MACOS_NOTARY_PROFILE (from `xcrun notarytool store-credentials`) the .dmg is notarised too.
Unsigned, macOS asks the user to allow the app once (System Settings > Privacy & Security > Open Anyway).

Windows signing is optional in the same way: WINDOWS_SIGN_SHA1 (a certificate's thumbprint in the user's store, which
is how a hardware token presents itself) or WINDOWS_SIGN_PFX with WINDOWS_SIGN_PASSWORD signs the two .exe files and
the installer, timestamped so the signature outlives the certificate. Unsigned, SmartScreen warns that the publisher
is unknown and advises against running it; only a certificate removes that, and only an EV one removes it at once.

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


SECRET_ENV = ('WINDOWS_SIGN_PASSWORD',)     # values never to print: a build log is often public


def run(*cmd, **kw):
    secrets = {os.environ[k] for k in SECRET_ENV if os.environ.get(k)}
    print('+', ' '.join('***' if c in secrets else c for c in cmd), flush=True)
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


def signtool():
    """signtool.exe: on PATH, else the newest one in the Windows SDK."""
    found = shutil.which('signtool')
    if found:
        return found
    roots = [os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Windows Kits', '10', 'bin')]
    cand = []
    for root in roots:
        for dirpath, _dirs, files in os.walk(root) if os.path.isdir(root) else []:
            if 'signtool.exe' in files and os.path.basename(dirpath) in ('x64', 'x86'):
                cand.append(os.path.join(dirpath, 'signtool.exe'))
    return sorted(cand)[-1] if cand else None


def sign_windows(paths):
    """Authenticode-sign the given files, if a certificate was given. No certificate is not an error: the build
    then produces the same unsigned installer it always did, and SmartScreen warns the user about the publisher.

    A signature without a timestamp stops being trusted the day the certificate expires, so every signature is
    timestamped (RFC 3161). Signing the .exe files and the installer is what SmartScreen looks at; the bundled
    DLLs do not need it."""
    sha1, pfx = os.environ.get('WINDOWS_SIGN_SHA1'), os.environ.get('WINDOWS_SIGN_PFX')
    if not (sha1 or pfx):
        print('no WINDOWS_SIGN_SHA1 or WINDOWS_SIGN_PFX: leaving the build unsigned', flush=True)
        return
    tool = signtool()
    if not tool:
        raise SystemExit('a signing certificate was given but signtool.exe was not found (install the Windows SDK)')
    url = os.environ.get('WINDOWS_TIMESTAMP_URL', 'http://timestamp.digicert.com')
    cert = ['/sha1', sha1] if sha1 else ['/f', pfx]
    if pfx and os.environ.get('WINDOWS_SIGN_PASSWORD'):
        cert += ['/p', os.environ['WINDOWS_SIGN_PASSWORD']]
    for path in paths:
        run(tool, 'sign', '/fd', 'sha256', '/tr', url, '/td', 'sha256', *cert, path)
    run(tool, 'verify', '/pa', *paths)                              # fails the build if a signature did not take


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
        # the programs first, so the installer carries signed files, then the installer itself: that is the one
        # SmartScreen judges when the user runs the download.
        sign_windows([os.path.join(folder, name) for name in ('LunarAtlas.exe', 'lunaratlas-cli.exe')
                      if os.path.exists(os.path.join(folder, name))])
        if iscc:
            run(iscc, f'/DVersion={a.version}', f'/DSource={folder}', f'/O{DIST}',
                f'/FLunarAtlas-{a.version}-windows-setup', os.path.join(HERE, 'windows', 'lunaratlas.iss'))
            out = f'{base}-windows-setup.exe'
            sign_windows([out])
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
