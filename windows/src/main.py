"""Windows entry point. The distributed EXE never invokes an external Python."""
from __future__ import annotations

import os
import sys
import traceback


def _log_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "SoundCloudX", "logs")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "startup.log")


def _fatal(message):
    """Report a startup failure even when Tcl/Tk itself could not be loaded."""
    try:
        path = _log_path()
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")
        message += "\n\nDiagnostic log / فایل گزارش:\n" + path
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "SoundCloud X", 0x10)
            return
        except Exception:
            pass
    if sys.stderr is not None:
        sys.stderr.write(message + "\n")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # A windowed PyInstaller process has stdout/stderr=None. Keep library
    # diagnostics from crashing it; store them locally instead of hiding them.
    if sys.stdout is None or sys.stderr is None:
        try:
            stream = open(_log_path(), "a", encoding="utf-8", buffering=1)
        except OSError:
            stream = open(os.devnull, "w")
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    try:
        if "--self-test" in argv:
            from scx.smoke import run
            return run(argv)
        from scx.ui import main as run
        run()
        return 0
    except Exception:
        _fatal("برنامه نتوانست اجرا شود. نصب پایتون راه‌حل این خطا نیست.\n"
               "SoundCloud X could not start; this EXE includes Python.\n\n" +
               traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
