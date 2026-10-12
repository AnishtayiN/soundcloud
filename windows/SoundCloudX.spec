# -*- mode: python ; coding: utf-8 -*-
"""Self-contained Windows executable, including its Python/Tcl/SDL runtimes.

Do not exclude standard-library packages (email/http) or PIL.ImageTk: requests
and customtkinter need them even if they are not imported by our entry point.
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ctk_data, ctk_binaries, ctk_hidden = collect_all("customtkinter")
pygame_data, pygame_binaries, pygame_hidden = collect_all("pygame")

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=ctk_binaries + pygame_binaries,
    datas=ctk_data + pygame_data + collect_data_files("certifi") + [
        ("assets/icon.ico", "assets"), ("assets/icon.png", "assets"),
        ("selftest.py", "."),
    ],
    hiddenimports=ctk_hidden + pygame_hidden + collect_submodules("scx") +
                  collect_submodules("mutagen") + ["PIL.ImageTk", "email.utils", "http.client"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Optional, unrelated GUI/scientific frameworks only. Never trim runtime
    # dependencies to meet an arbitrary download-size target.
    excludes=["matplotlib", "scipy", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="SoundCloudX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join("assets", "icon.ico"),
    version=os.path.join("version_info.txt"),
)
