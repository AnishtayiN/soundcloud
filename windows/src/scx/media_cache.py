"""Track/type-keyed playback cache with validation and a real byte budget."""
from __future__ import annotations

import os
import threading
from urllib.parse import urlsplit

from .diagnostics import LOG, failed
from .player import Player


class InvalidCache(Exception):
    pass


class MediaCache(object):
    def __init__(self, folder, downloader, limit_mb=500):
        self.folder = folder
        self.downloader = downloader
        self.limit_mb = max(1, int(limit_mb or 500))
        self._lock = threading.RLock()
        self._active = set()
        os.makedirs(folder, exist_ok=True)
        self.trim()

    @staticmethod
    def stream_type(url):
        path = urlsplit(url).path.lower()
        return "hls" if path.endswith((".m3u8", ".m3u")) else "progressive"

    def path_for(self, track, url):
        kind = self.stream_type(url)
        path = urlsplit(url).path.lower()
        extension = os.path.splitext(path)[1]
        if kind == "hls":
            extension = ".m3u8"
        elif extension not in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".flac"):
            extension = ".mp3"
        return os.path.join(self.folder, "scx-%s-%s%s" % (int(track.id), kind, extension))

    @staticmethod
    def validate(path):
        """Check structure as well as size; never feed an HTML error page to pygame."""
        try:
            playlist = path.lower().endswith((".m3u8", ".m3u"))
            if not os.path.isfile(path) or os.path.getsize(path) < (32 if playlist else 128):
                raise InvalidCache("empty or short cache")
            if playlist:
                with open(path, "r", encoding="utf-8-sig") as stream:
                    text = stream.read(1024 * 1024 + 1)
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if len(text) > 1024 * 1024 or not lines or lines[0] != "#EXTM3U":
                    raise InvalidCache("invalid HLS playlist")
                if not any(not line.startswith("#") for line in lines[1:]):
                    raise InvalidCache("HLS playlist has no media")
                return True
            if os.path.getsize(path) < 4096:
                raise InvalidCache("short audio cache")
            with open(path, "rb") as stream:
                header = stream.read(16)
            if header.lstrip().startswith((b"<", b"{", b"[")):
                raise InvalidCache("audio cache contains an error response")
            if Player.measure_duration(path) <= 0:
                raise InvalidCache("audio decoder cannot read cache")
            return True
        except (OSError, IOError, ValueError, UnicodeError, InvalidCache) as error:
            failed("validate playback cache", error)
            return False

    def discard(self, path):
        with self._lock:
            for name in (path, path + ".part", path + ".part.json", path + ".part.json.tmp"):
                try:
                    if os.path.isfile(name):
                        os.unlink(name)
                except OSError as error:
                    failed("remove invalid cache", error)

    def get_or_fetch(self, track, url, on_progress=None, cancel_event=None):
        path = self.path_for(track, url)
        with self._lock:
            self._active.add(path)
        try:
            if os.path.exists(path):
                if self.validate(path):
                    os.utime(path, None)
                    return path
                self.discard(path)
            self.downloader.fetch_to(url, path, on_progress=on_progress,
                                     cancel_event=cancel_event,
                                     verify_audio=self.stream_type(url) != "hls")
            if not self.validate(path):
                self.discard(path)
                raise InvalidCache("downloaded media is not playable")
            return path
        finally:
            with self._lock:
                self._active.discard(path)
            self.trim()

    def trim(self):
        """Evict oldest complete/part files until the configured disk budget is met."""
        with self._lock:
            entries = []
            try:
                for name in os.listdir(self.folder):
                    if not name.startswith("scx-"):
                        continue
                    path = os.path.join(self.folder, name)
                    if os.path.isfile(path):
                        entries.append((os.stat(path).st_mtime, path, os.path.getsize(path)))
            except OSError as error:
                failed("enumerate audio cache", error)
                return 0
            budget = self.limit_mb * 1024 * 1024
            total = sum(item[2] for item in entries)
            freed = 0
            protected = {os.path.join(self.folder, os.path.basename(p)) for p in self._active}
            for _mtime, path, size in sorted(entries):
                if total <= budget:
                    break
                bases = [path]
                if path.endswith(".part"):
                    bases.extend([path + ".json", path + ".json.tmp"])
                group = [p for p in bases if os.path.isfile(p)]
                if any(p in protected or p[:-5] in protected for p in group):
                    continue
                try:
                    actual = sum(os.path.getsize(p) for p in group)
                    for p in group:
                        os.unlink(p)
                    total -= actual
                    freed += actual
                except OSError as error:
                    failed("evict audio cache", error)
            if total > budget:
                LOG.info("audio cache budget deferred while media is in use")
            return freed
