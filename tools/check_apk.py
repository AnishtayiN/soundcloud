#!/usr/bin/env python3
"""Inspect actual contents, never gate a native APK on an arbitrary size."""
import sys
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path):
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
        require(any("ic_launcher" in n for n in names), "launcher icon entry missing")
    print("APK contains compiled app, resources, background/download services and MP3/HLS engine")


if __name__ == "__main__":
    try:
        verify(sys.argv[1])
    except Exception as error:
        print("::error title=APK contents::%s: %s" % (type(error).__name__, str(error).replace("\n", "%0A")))
        sys.exit(1)
