# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for SoundCloudX.exe (single file, no console)."""
import os

block_cipher = None

hidden = [
    "scx", "scx.api", "scx.downloader", "scx.models", "scx.player",
    "scx.store", "scx.strings", "scx.ui", "scx.util", "scx.version",
]

# Things that must never end up inside a 30 MB downloader.
excludes = [
    "numpy", "matplotlib", "scipy", "pandas", "test", "unittest",
    "setuptools", "pip", "wheel", "email", "http.server", "xmlrpc",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "PIL.ImageQt", "PIL.ImageTk", "PIL.ImageShow",
    "curses", "distutils", "lib2to3", "pydoc_data",
]

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SoundCloudX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("assets", "icon.ico"),
    version=os.path.join("version_info.txt"),
)
