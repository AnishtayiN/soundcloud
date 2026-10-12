#!/usr/bin/env python3
"""Inspect contents, not an arbitrary APK size. Signature/install tests are separate."""
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as apk:
    assert apk.testzip() is None, "corrupt APK ZIP entry"
    names = apk.namelist()
    assert "AndroidManifest.xml" in names and "resources.arsc" in names
    dex = b"".join(apk.read(n) for n in names if n.startswith("classes") and n.endswith(".dex"))
    assert dex.startswith(b"dex\n"), "no compiled application code"
    for cls in ("com/soundcloudx/app/MainActivity", "com/soundcloudx/app/PlayerService",
                "com/soundcloudx/app/DownloadService", "com/soundcloudx/app/ScApi",
                "androidx/media3/exoplayer/ExoPlayer", "androidx/media3/exoplayer/hls/HlsMediaSource"):
        assert cls.encode() in dex, "missing application/runtime class: " + cls
    assert any("ic_launcher" in n for n in names), "launcher icon missing"
print("APK contains compiled app, resources, background/download services and MP3/HLS engine")
