"""Build the one OpenCV dependency LunarAtlas needs, without video backends.

The upstream ``opencv-python-headless`` wheels bundle FFmpeg, including GPL-only
codecs.  LunarAtlas only reads and writes still images, so every release runner
builds the pinned source distribution with video I/O disabled before PyInstaller
collects it.  This script is deliberately used on each native target: Python
wheels cannot be cross-compiled safely by the application build.
"""
import glob
import hashlib
import os
import subprocess
import sys
import tempfile


PACKAGE = 'opencv-python-headless==4.14.0.94'
SOURCE_SHA256 = '4afa2ea1214453648be88259f035712454faa9039b686de7753569ba8eec1577'
FLAGS = '-DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DBUILD_opencv_videoio=OFF'


def run(*args, **kwargs):
    print('+', ' '.join(map(str, args)))
    subprocess.run(args, check=True, **kwargs)


def main():
    # PEP 517's isolated build environment supplies its pinned CMake/Ninja
    # backend dependencies.  ``--no-binary`` applies only to OpenCV: forcing
    # NumPy itself to compile would add needless hours to a release build.
    with tempfile.TemporaryDirectory(prefix='lunaratlas-opencv-wheel-') as wheel_dir, \
         tempfile.TemporaryDirectory(prefix='lunaratlas-opencv-source-') as source_dir:
        env = dict(os.environ, CMAKE_ARGS=FLAGS, CMAKE_BUILD_PARALLEL_LEVEL=os.environ.get('CMAKE_BUILD_PARALLEL_LEVEL', '4'))
        run(sys.executable, '-m', 'pip', 'download', '--no-binary=opencv-python-headless', '--no-cache-dir', '--no-deps',
            '--dest', source_dir, PACKAGE)
        sources = glob.glob(os.path.join(source_dir, 'opencv_python_headless-*.tar.gz'))
        if len(sources) != 1:
            raise SystemExit(f'expected exactly one OpenCV source archive, found {sources}')
        with open(sources[0], 'rb') as fh:
            got = hashlib.file_digest(fh, 'sha256').hexdigest()
        if got != SOURCE_SHA256:
            raise SystemExit(f'OpenCV source checksum mismatch: expected {SOURCE_SHA256}, got {got}')
        run(sys.executable, '-m', 'pip', 'wheel', '--no-cache-dir', '--no-deps', '--wheel-dir', wheel_dir, sources[0], env=env)
        wheels = glob.glob(os.path.join(wheel_dir, 'opencv_python_headless-*.whl'))
        if len(wheels) != 1:
            raise SystemExit(f'expected exactly one minimal OpenCV wheel, found {wheels}')
        run(sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', wheels[0])


if __name__ == '__main__':
    main()
