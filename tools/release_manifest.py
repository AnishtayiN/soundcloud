#!/usr/bin/env python3
"""Require runtime reports and create a checksum/size manifest for real binaries."""
import hashlib
import json
import os
from pathlib import Path
import sys

folder, reports = Path(sys.argv[1]), Path(sys.argv[2])
version = os.environ["APP_VERSION"]
windows = []
for name in ("windows-portable.json", "windows-installed.json"):
    paths = list(reports.rglob(name))
    assert len(paths) == 1, "missing/ambiguous runtime report: " + name
    report = json.loads(paths[0].read_text(encoding="utf-8-sig"))
    assert report["ok"] and report["frozen"] and report["normal_startup_and_close"], "unverified EXE"
    windows.append({"file": name, "checks": report["checks"], "normal_startup_and_close": True})
android = []
for api in (24, 34, 36):
    paths = list(reports.rglob("android-%d/instrumentation.txt" % api))
    assert len(paths) == 1 and "OK (5 tests)" in paths[0].read_text(), "missing Android runtime result"
    android.append({"api": api, "release_install_launch_resume": True, "instrumentation_tests": 5})
required = ["SoundCloudX-%s.apk" % version, "SoundCloudX.exe", "SoundCloudX-Setup-%s-x64.exe" % version]
files = []
for name in required:
    path = folder / name
    assert path.is_file() and path.stat().st_size > 0, "missing binary: " + name
    with path.open("rb") as stream:
        header = stream.read(4)
        assert header.startswith(b"PK") if name.endswith(".apk") else header.startswith(b"MZ"), "not a real APK/PE"
        stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    files.append({"name": name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
(folder / "SHA256SUMS.txt").write_text("".join("%s  %s\n" % (f["sha256"], f["name"]) for f in files))
manifest = {"version": version, "commit": os.environ["GITHUB_SHA"], "signing": os.environ["SIGNING"],
            "files": files, "windows_runtime": windows, "android_runtime": android,
            "not_verified": ["live SoundCloud connectivity/login", "Windows 7/8/8.1", "every physical device"]}
(folder / "build-info.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
