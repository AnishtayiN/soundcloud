#!/usr/bin/env python3
"""Inspect actual contents, never gate a native APK on an arbitrary size."""
import sys
import zipfile
import re
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path, badging=None):
    with zipfile.ZipFile(path) as apk:
        require(apk.testzip() is None, "corrupt APK ZIP entry")
        names = apk.namelist()
        require("AndroidManifest.xml" in names and "resources.arsc" in names, "manifest/resources missing")
        dex_names = [n for n in names if n.startswith("classes") and n.endswith(".dex")]
        dex = b"".join(apk.read(n) for n in dex_names)
        print("::notice title=APK contents::%d ZIP entries; DEX files: %s; %d bytes of code" %
              (len(names), ", ".join(dex_names), len(dex)))
        require(dex.startswith(b"dex\n"), "no compiled application DEX code")
        for cls in ("com/soundcloudx/app/MainActivity", "com/soundcloudx/app/PlayerService",
                    "com/soundcloudx/app/DownloadService", "com/soundcloudx/app/ScApi",
                    "androidx/media3/exoplayer/ExoPlayer", "androidx/media3/exoplayer/hls/HlsMediaSource"):
            require(cls.encode() in dex, "missing application/runtime class: " + cls)
        # AAPT2 may shorten ZIP resource paths even with minify disabled.
        # Verify the actual paths referenced by the resource table/manifest,
        # not a source filename that Android never uses at runtime.
        if badging:
            text = Path(badging).read_text(encoding="utf-8")
            icons = re.findall(r"application-icon-\d+:'([^']+)'", text)
            icons += re.findall(r"(?m)^application:.*?\bicon='([^']+)'", text)
            require(bool(icons), "manifest has no resolved application icon")
            require(all(icon in names for icon in icons), "resolved launcher icon is not in APK")
        else:
            table = apk.read("resources.arsc")
            require(b"ic_launcher" in table or "ic_launcher".encode("utf-16le") in table,
                    "launcher icon resource missing")
    print("APK contains compiled app, resources, background/download services and MP3/HLS engine")


if __name__ == "__main__":
    try:
        verify(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    except Exception as error:
        print("::error title=APK contents::%s: %s" % (type(error).__name__, str(error).replace("\n", "%0A")))
        sys.exit(1)
