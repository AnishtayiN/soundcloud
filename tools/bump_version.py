#!/usr/bin/env python3
"""Writes a version number into every file that carries one.

usage: python tools/bump_version.py 1.2.3
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGETS = [
    os.path.join(ROOT, "windows", "src", "scx", "version.py"),
    os.path.join(ROOT, "windows", "version_info.txt"),
    os.path.join(ROOT, "android", "app", "build.gradle"),
]


def patch(path, replacements):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    original = text
    for pattern, template in replacements:
        text = re.sub(pattern, template, text)
    if text != original:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("updated", os.path.relpath(path, ROOT))
    else:
        print("unchanged", os.path.relpath(path, ROOT))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    version = argv[1].lstrip("v")
    if not re.match(r"^\d+(\.\d+){0,3}$", version):
        print("not a version number:", version)
        return 2
    parts = [int(p) for p in (version.split(".") + ["0", "0", "0", "0"])[:4]]
    version4 = ".".join(str(p) for p in parts)

    patch(TARGETS[0], [
        (r'__version__\s*=\s*"[^"]*"', '__version__ = "%s"' % version),
    ])
    patch(TARGETS[1], [
        (r"filevers=\([^)]*\)", "filevers=(%s)" % ", ".join(str(p) for p in parts)),
        (r"prodvers=\([^)]*\)", "prodvers=(%s)" % ", ".join(str(p) for p in parts)),
        (r"StringStruct\('FileVersion', '[^']*'\)",
         "StringStruct('FileVersion', '%s')" % version4),
        (r"StringStruct\('ProductVersion', '[^']*'\)",
         "StringStruct('ProductVersion', '%s')" % version4),
    ])
    patch(TARGETS[2], [
        (r'appVersionName\s*=\s*\(project\.findProperty\("appVersionName"\)\s*\?:\s*"'
         r'[^"]*"\)',
         'appVersionName = (project.findProperty("appVersionName") ?: "%s")' % version),
    ])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
