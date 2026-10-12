# -*- mode: python ; coding: utf-8 -*-
"""Self-contained Windows executable, including its Python/Tcl/SDL runtimes.

Do not exclude standard-library packages (email/http) or PIL.ImageTk: requests
and customtkinter need them even if they are not imported by our entry point.
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata
sys.path.insert(0, os.path.join(SPECPATH, "src"))
license_data = []
for distribution in ("requests", "urllib3", "certifi", "Pillow", "mutagen", "darkdetect", "idna", "charset-normalizer"):
    license_data += copy_metadata(distribution)
for filename in ("LICENSE.txt", "LICENSE"):
    path = os.path.join(sys.base_prefix, filename)
    if os.path.isfile(path):
        license_data.append((path, "licenses/python"))
        break

ctk_data, ctk_binaries, ctk_hidden = collect_all("customtkinter")
pygame_data, pygame_binaries, pygame_hidden = collect_all("pygame")

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=ctk_binaries + pygame_binaries,
    datas=ctk_data + pygame_data + license_data + collect_data_files("certifi") + [
        ("assets/icon.ico", "assets"), ("assets/icon.png", "assets"),
        ("selftest.py", "."), ("THIRD_PARTY_NOTICES.txt", "."),
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
