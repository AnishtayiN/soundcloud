"""Persistent settings / favorites / download history (plain JSON files)."""
from __future__ import annotations

import json
import os
import threading

from . import util


DEFAULTS = {
    "download_dir": None,          # computed from the profile when empty
    "language": "fa",
    "volume": 0.8,
    "genre": "all-music",
    "cookie_header": "",
    "client_id": "",
    "client_id_time": 0,
    "favorites": [],
    "downloads": [],
    "cache_limit_mb": 500,
}


class Store(object):
    def __init__(self, path=None):
        self.path = path or os.path.join(util.config_dir(), "settings.json")
        self._lock = threading.RLock()
        self.data = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io --
    def load(self):
        with self._lock:
            try:
                if os.path.isfile(self.path):
                    with open(self.path, "r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        for key, value in loaded.items():
                            self.data[key] = value
            except Exception:
                pass
            if not self.data.get("download_dir"):
                self.data["download_dir"] = util.default_download_dir()
            if not self.data.get("favorites"):
                self.data["favorites"] = []
            if not self.data.get("downloads"):
                self.data["downloads"] = []

    def save(self):
        with self._lock:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False, indent=1)
                if os.path.exists(self.path):
                    os.remove(self.path)
                os.rename(tmp, self.path)
            except Exception:
                pass

    # --------------------------------------------------------------- access --
    def get(self, key, default=None):
        with self._lock:
            value = self.data.get(key, DEFAULTS.get(key, default))
            return default if value is None and default is not None else value

    def set(self, key, value, save=True):
        with self._lock:
            self.data[key] = value
        if save:
            self.save()

    # ------------------------------------------------------------ favorites --
    def favorites(self):
        with self._lock:
            return list(self.data.get("favorites", []))

    def is_favorite(self, track_id):
        return any(int(item.get("id", 0)) == int(track_id) for item in self.favorites())

    def toggle_favorite(self, track):
        """Returns True when the track has been added."""
        with self._lock:
            items = list(self.data.get("favorites", []))
            for index, item in enumerate(items):
                if int(item.get("id", 0)) == int(track.id):
                    items.pop(index)
                    self.data["favorites"] = items
                    self.save()
                    return False
            items.insert(0, track.to_json())
            self.data["favorites"] = items
            self.save()
            return True

    def favorite_tracks(self):
        from .models import Track
        out = []
        for item in self.favorites():
            try:
                track = Track(**item)
            except Exception:
                continue
            if track.id:
                out.append(track)
        return out

    # ------------------------------------------------------------ downloads --
    def add_download(self, name, path, title, artist, url="", size=0):
        with self._lock:
            items = [d for d in self.data.get("downloads", []) if d.get("path") != path]
            items.insert(0, {
                "name": name,
                "path": path,
                "title": title,
                "artist": artist,
                "url": url,
                "size": size,
            })
            self.data["downloads"] = items[:200]
            self.save()

    def downloads(self):
        with self._lock:
            return list(self.data.get("downloads", []))
