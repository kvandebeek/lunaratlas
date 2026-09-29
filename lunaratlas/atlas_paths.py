"""Where the tools keep their files, the same from a checkout and from the packaged app (PyInstaller).

From a checkout the reference data stays in lunaratlas/data and .env next to tool_settings.py, as before. The packaged
app's own folder is read-only (and signed on macOS), so there both live in the user's application-data folder.
LUNARATLAS_DATA overrides the data folder either way.
"""
import os
import sys

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


FONTS = os.path.join(HERE, 'fonts')          # the bundled label fonts (OFL), shipped with the app: no download
DATA = os.environ.get('LUNARATLAS_DATA') or (os.path.join(user_dir('data'), 'data') if FROZEN else os.path.join(HERE, 'data'))
CACHE = user_dir('cache')


def self_command(*args):
    """argv that runs a lunaratlas.py subcommand in a new process: the packaged app runs itself."""
    if FROZEN:      # the console twin of the windowed app, when there is one (Windows: its output reaches the pipe)
        cli = os.path.join(os.path.dirname(sys.executable), 'lunaratlas-cli' + ('.exe' if sys.platform == 'win32' else ''))
        return [cli if os.path.exists(cli) else sys.executable, *args]
    return [sys.executable, os.path.join(HERE, 'lunaratlas.py'), *args]
