"""Entry point of the packaged LunarAtlas: without arguments the browser launcher (`lunaratlas.py app`), with a
lunaratlas.py subcommand that command (the launcher runs locate and export this way, in their own process)."""
import os
import sys

COMMANDS = ('locate', 'export', 'info', 'find', 'view', 'app')


def log_to_file():
    """A windowed app has no terminal: its output goes to lunaratlas.log in the app's data folder."""
    from atlas_paths import user_dir
    d = user_dir('data')
    os.makedirs(d, exist_ok=True)
    f = open(os.path.join(d, 'lunaratlas.log'), 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = f


def certificates():
    """HTTPS for the first-use downloads: the bundled Python would look for the build machine's certificate file."""
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())


def main():
    certificates()
    args = [a for a in sys.argv[1:] if not a.startswith('-psn_')]      # macOS Finder's process serial number
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except AttributeError:                                          # None (windowed) or not a text stream
            pass
    if not args or args[0] not in COMMANDS:
        if sys.stdout is None or not sys.stdout.isatty():
            log_to_file()
        # an app window when pywebview is built in; else the browser, and then the launcher stops by itself
        # three minutes after its last page was closed
        args = ['app', '--idle-exit', '180'] + args
    import lunaratlas
    lunaratlas.main(args)


if __name__ == '__main__':
    main()
