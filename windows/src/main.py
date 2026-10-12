"""SoundCloud X for Windows - entry point.

Run from source:   python src/main.py
Run from the exe:  SoundCloudX.exe
"""
from __future__ import annotations

import os
import sys
import traceback


def _fatal(message):
    """Shows an error even when the app is built without a console."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("SoundCloud X", message)
        root.destroy()
    except Exception:
        sys.stderr.write(message + "\n")


def main():
    # PyInstaller one-file builds start in a temporary folder.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    try:
        from scx.ui import main as run
    except Exception:
        _fatal("SoundCloud X could not start:\n\n" + traceback.format_exc())
        return 1

    try:
        run()
    except Exception:
        _fatal("SoundCloud X crashed:\n\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
