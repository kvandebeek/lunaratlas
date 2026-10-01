"""Third-party notices for the packaged app: every dependency's own licence text, collected from the build
environment's installed distributions, plus a warning if a GPL-only codec library slipped into the bundle.

Both are compliance requirements, not cosmetic: distributing (L)GPL, BSD, MIT, MPL and PSF-licensed binary code
requires their notices to travel with the distribution, and distributing GPL object code needs the source too, which
LunarAtlas does not offer for anything beyond its own code. See claude-findings.md C-12.
"""
import glob
import importlib.metadata as im
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# every distribution actually installed for a build, whether or not this platform needs all of them
WANTED = ('numpy', 'opencv-python-headless', 'opencv-python', 'pillow', 'certifi', 'pywebview',
          'pyobjc-core', 'pyobjc-framework-cocoa', 'pyobjc-framework-quartz', 'pyobjc-framework-security',
          'pyobjc-framework-webkit', 'pyobjc-framework-uniformtypeidentifiers')

# GPL-only libraries that must never reach a release bundle: opencv-python's macOS wheel bundles FFmpeg built with
# --enable-gpl (x264, x265) unless it was rebuilt without them (WITH_FFMPEG=OFF, or a source build that disables
# these encoders). A hit here means the build must not ship as it is.
FORBIDDEN_LIBS = ('x264', 'x265', 'postproc', 'rubberband', 'vidstab', 'fdk')

PYTHON_NOTICE = """Python
------
This application embeds a CPython interpreter, distributed under the Python Software Foundation License:
https://docs.python.org/3/license.html
"""


def _license_files(dist):
    """Every LICENSE*/COPYING*/NOTICE* file this distribution ships, including a licenses/ subfolder."""
    root = dist._path if hasattr(dist, '_path') else None      # the .dist-info folder on disk
    if root is None:
        return []
    out = []
    for pat in ('LICENSE*', 'COPYING*', 'NOTICE*', 'licenses/*'):
        out += sorted(glob.glob(os.path.join(str(root), pat)))
    return [f for f in out if os.path.isfile(f)]


def collect(dest):
    """Write dest as one THIRD-PARTY-NOTICES.txt: every wanted distribution's own licence text, or its declared
    licence classifier/metadata when it ships no file, plus CPython's."""
    seen = set()
    parts = [
        'LunarAtlas — third-party notices',
        '=================================',
        '',
        'LunarAtlas itself is Apache-2.0 (see LICENSE, NOTICE). It is built with the following, each under its own',
        'licence; the full text of each, as shipped by the project, follows.',
        '',
        PYTHON_NOTICE,
    ]
    for name in WANTED:
        try:
            dist = im.distribution(name)
        except im.PackageNotFoundError:
            continue
        key = dist.metadata['Name'].lower()
        if key in seen:
            continue
        seen.add(key)
        version = dist.version
        parts.append(f'{dist.metadata["Name"]} {version}')
        parts.append('-' * len(f'{dist.metadata["Name"]} {version}'))
        files = _license_files(dist)
        if files:
            for f in files:
                try:
                    with open(f, encoding='utf-8', errors='replace') as fh:
                        parts.append(fh.read().rstrip())
                except OSError:
                    pass
        else:
            lic = next((c.split(' :: ')[-1] for c in dist.metadata.get_all('Classifier', ())
                       if c.startswith('License ::')), None) or dist.metadata.get('License') or 'see the project page'
            parts.append(f'Licence: {lic}. No licence file was found in this build environment; see the project\'s '
                         'own repository for the full text.')
        parts.append('')
    text = '\n'.join(parts)
    with open(dest, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return dest


def find_forbidden(folder):
    """Paths under folder whose name contains a GPL-only library this app must not ship (see FORBIDDEN_LIBS)."""
    hits = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            low = f.lower()
            if any(lib in low for lib in FORBIDDEN_LIBS):
                hits.append(os.path.join(root, f))
    return sorted(hits)


def check_forbidden(folder):
    """Raise SystemExit with the offending files if the bundle contains a GPL-only codec library.

    LunarAtlas does no video I/O; these come from OpenCV's default wheel bundling a full FFmpeg build. Fix: build
    opencv-python-headless from source with WITH_FFMPEG=OFF (or otherwise excluding x264/x265/…), or remove the
    matching files from the built dist_dir before packaging further (only if licence terms for their removal are
    understood: a link-time dependency removed from a binary is a packaging fix, not a licence workaround on its own).
    """
    hits = find_forbidden(folder)
    if hits:
        listing = '\n  '.join(os.path.relpath(h, folder) for h in hits)
        raise SystemExit(
            'refusing to package a build that bundles GPL-only codec libraries LunarAtlas does not need '
            f'(see packaging/notices.py, claude-findings.md C-12):\n  {listing}\n'
            'Build opencv-python-headless from source with WITH_FFMPEG=OFF (or an equivalent that drops these '
            'encoders), or set LUNARATLAS_ALLOW_GPL_CODECS=1 to override while that is being arranged.')


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'THIRD-PARTY-NOTICES.txt')
    collect(out)
    print(f'wrote {out}')
