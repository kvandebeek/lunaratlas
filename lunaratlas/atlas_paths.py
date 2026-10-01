"""Where the tools keep their files, the same from a checkout and from the packaged app (PyInstaller).

From a checkout the reference data stays in lunaratlas/data and .env next to tool_settings.py, as before. The packaged
app's own folder is read-only (and signed on macOS), so there both live in the user's application-data folder.
LUNARATLAS_DATA overrides the data folder either way.
"""
import contextlib
import os
import sys
import tempfile
import time as _time

FROZEN = bool(getattr(sys, 'frozen', False))
HERE = os.path.dirname(os.path.abspath(__file__))
APP = 'LunarAtlas'


def user_dir(kind):
    """The per-user folder of this platform for kind 'data' or 'cache' (not created here)."""
    home = os.path.expanduser('~')
    if sys.platform == 'darwin':
        base = os.path.join(home, 'Library', 'Caches' if kind == 'cache' else 'Application Support')
    elif sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')
        return os.path.join(base, APP, 'Cache' if kind == 'cache' else 'Data')
    else:
        base = (os.environ.get('XDG_CACHE_HOME') if kind == 'cache' else os.environ.get('XDG_DATA_HOME')) or \
            os.path.join(home, '.cache' if kind == 'cache' else os.path.join('.local', 'share'))
    return os.path.join(base, APP if sys.platform == 'darwin' else APP.lower())


# ---------------------------------------------------------------- image/export identity
#
# Shared here (not in atlas_app.py or lunaratlas.py, which cannot import each other without a cycle) so the
# launcher's recent-photos list and the CLI's batch mode agree on what counts as an image and what is one of
# LunarAtlas's own exports (bugs-overview BUG-13: App.recent() used to list every image file, including its own
# IMAGE_atlas….ext exports, as an unsolved photo).
IMAGE_EXT = ('.tif', '.tiff', '.png', '.jpg', '.jpeg')
_ATLAS_RE = None


def is_export_name(name):
    """True for a name this app would itself have written as a default export (IMAGE_atlas….ext,
    IMAGE_atlas_NAME.ext): the stem ends in "_atlas" or contains "_atlas_"."""
    global _ATLAS_RE
    if _ATLAS_RE is None:
        import re
        _ATLAS_RE = re.compile(r'_atlas(_|$)')
    stem = os.path.splitext(name)[0]
    return bool(_ATLAS_RE.search(stem))


FONTS = os.path.join(HERE, 'fonts')          # the bundled label fonts (OFL), shipped with the app: no download
DATA = os.environ.get('LUNARATLAS_DATA') or (os.path.join(user_dir('data'), 'data') if FROZEN else os.path.join(HERE, 'data'))
CACHE = user_dir('cache')


def self_command(*args):
    """argv that runs a lunaratlas.py subcommand in a new process: the packaged app runs itself."""
    if FROZEN:      # the console twin of the windowed app, when there is one (Windows: its output reaches the pipe)
        cli = os.path.join(os.path.dirname(sys.executable), 'lunaratlas-cli' + ('.exe' if sys.platform == 'win32' else ''))
        return [cli if os.path.exists(cli) else sys.executable, *args]
    return [sys.executable, os.path.join(HERE, 'lunaratlas.py'), *args]


_UMASK = os.umask(0)
os.umask(_UMASK)


# ---------------------------------------------------------------- cross-process file lock
#
# threading.Lock() alone only serializes callers inside one process; two processes with the same image open (the
# launcher's `view` subprocess and a second `lunaratlas.py` CLI invocation, or two viewer servers pointed at one
# work folder) can still race on the same sidecar (bugs-overview BUG-04/BUG-14). This advisory lock is held on a
# "<sidecar>.lock" file beside the sidecar, using flock on POSIX and a byte-range lock on Windows; it is never
# deleted, so a process that opens it after another is already waiting never has the file disappear under it.
def _lock_path(path):
    return path + '.lock'


if sys.platform == 'win32':
    import msvcrt

    @contextlib.contextmanager
    def file_lock(path, timeout=30):
        lp = _lock_path(path)
        fh = open(lp, 'a+b')
        try:
            t0 = _time.monotonic()
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if _time.monotonic() - t0 > timeout:
                        raise TimeoutError(f'timed out waiting for the lock on {os.path.basename(path)}') from None
                    _time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            fh.close()
else:
    import fcntl

    @contextlib.contextmanager
    def file_lock(path, timeout=30):
        lp = _lock_path(path)
        fh = open(lp, 'a+b')
        try:
            t0 = _time.monotonic()
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if _time.monotonic() - t0 > timeout:
                        raise TimeoutError(f'timed out waiting for the lock on {os.path.basename(path)}') from None
                    _time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            fh.close()


def temp_beside(path, suffix=None):
    """A new, empty, unpredictably named temporary file in path's folder (closed, made with O_EXCL, mode 0600), to write
    and then publish(). Never path + '.part': a symlink someone planted at that name would be written through.
    suffix defaults to path's extension (cv2.imwrite picks the encoder from it)."""
    d, name = os.path.split(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=f'.{name}.', suffix=os.path.splitext(name)[1] if suffix is None else suffix, dir=d)
    os.close(fd)
    return tmp


def publish(tmp, path):
    """tmp (from temp_beside) becomes path, with the mode a file made in the ordinary way would have."""
    try:
        os.chmod(tmp, 0o666 & ~_UMASK)
    except OSError:
        pass
    os.replace(tmp, path)


def private_dir(path):
    """Create path (and parents) for files only this user reads (photos' tiles and thumbnails): mode 0700 where the
    platform has modes. An existing folder is tightened only when it is ours to write to (a read-only one stays as it is)."""
    new = not os.path.isdir(path)
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name == 'posix' and (new or os.access(path, os.W_OK)):
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
