"""Atomic settings/favorites/history storage with a last-known-good backup."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

from . import util
from .credentials import CredentialError, CredentialVault
from .diagnostics import LOG

DEFAULTS = {
    "download_dir": None,
    "language": "fa",
    "volume": 0.8,
    "genre": "all-music",
    "client_id": "",
    "client_id_time": 0,
    "favorites": [],
    "downloads": [],
    "cache_limit_mb": 500,
}
_SECRET_KEYS = ("cookie_header", "oauth_token")


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError("settings root must be an object")
    for key in ("favorites", "downloads"):
        if key in data and (not isinstance(data[key], list)
                            or any(not isinstance(item, dict) for item in data[key])):
            raise ValueError("invalid %s collection" % key)
    if "language" in data and data["language"] not in ("fa", "en"):
        raise ValueError("invalid language")
    return data


def _strip_url(value):
    try:
        parts = urlsplit(value or "")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except (TypeError, ValueError):
        return ""


class Store(object):
    def __init__(self, path=None, credentials=None):
        self.path = os.path.abspath(path or os.path.join(util.config_dir(), "settings.json"))
        self.backup_path = self.path + ".bak"
        self.credentials = credentials if credentials is not None else CredentialVault(
            os.path.join(os.path.dirname(self.path), "credentials.bin"))
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load_error = None
        self.recovered_backup = False
        self.credential_error = None
        self.load()

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as stream:
            return _validate(json.load(stream))

    def _normalize(self, loaded):
        data = copy.deepcopy(DEFAULTS)
        data.update(loaded)
        if not data.get("download_dir"):
            data["download_dir"] = util.default_download_dir()
        data["language"] = "en" if data.get("language") == "en" else "fa"
        try:
            data["cache_limit_mb"] = max(1, int(data.get("cache_limit_mb") or 500))
        except (TypeError, ValueError):
            data["cache_limit_mb"] = 500
        # Old history contained signed download URLs. Keep only the public address.
        for item in data["downloads"]:
            if "url" in item:
                item["url"] = _strip_url(item.get("url"))
        return data

    def _migrate(self, candidates):
        legacy = next((data[key] for data in candidates for key in _SECRET_KEYS
                       if data.get(key)), "")
        contaminated = any(any(key in data for key in _SECRET_KEYS)
                           or any("?" in (item.get("url") or "") for item in data.get("downloads", []))
                           for data in candidates)
        if legacy:
            try:
                existing = self.credentials.get("cookie_header")
                if not existing:
                    self.credentials.set("cookie_header", legacy)
            except CredentialError as error:
                self.credential_error = str(error)
                LOG.error("legacy credential migration failed; plaintext will be removed")
        return contaminated

    def load(self):
        with self._lock:
            candidates = []
            chosen = None
            chosen_backup = False
            errors = []
            for path, backup in ((self.path, False), (self.backup_path, True)):
                try:
                    if os.path.isfile(path):
                        raw = self._read(path)
                        candidates.append(raw)
                        if chosen is None:
                            chosen, chosen_backup = raw, backup
                except (OSError, IOError, ValueError, UnicodeError) as error:
                    errors.append("%s (%s)" % (os.path.basename(path), type(error).__name__))
            if chosen is not None:
                contaminated = self._migrate([chosen])
                contaminated = contaminated or any(any(key in raw for key in _SECRET_KEYS) for raw in candidates)
                self.data = self._normalize(chosen)
                self.recovered_backup = chosen_backup
                if chosen_backup or contaminated:
                    # Never copy a corrupt or plaintext-credential file into .bak.
                    self.save(backup=False)
                    if chosen_backup or os.path.exists(self.backup_path):
                        self._write_atomic(self.backup_path, self._public_data())
                if chosen_backup:
                    LOG.warning("settings recovered from backup after: %s", ", ".join(errors))
                if contaminated:
                    LOG.info("legacy plaintext credentials removed from settings and backup")
            else:
                self.data = self._normalize({})
                if errors:
                    self.load_error = "; ".join(errors)
                    LOG.error("settings load failed; no valid backup: %s", self.load_error)
            return self.data

    def _public_data(self):
        data = copy.deepcopy(self.data)
        for key in _SECRET_KEYS:
            data.pop(key, None)
        return data

    def _write_atomic(self, path, data):
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="." + os.path.basename(path) + "-", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=1)
                stream.flush()
                os.fsync(stream.fileno())
            # Validate the actual serialized file before touching the destination.
            self._read(temporary)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError as error:
                    LOG.warning("temporary settings cleanup failed (%s)", type(error).__name__)

    def save(self, backup=True):
        with self._lock:
            data = self._public_data()
            try:
                if backup and os.path.isfile(self.path):
                    try:
                        previous = self._read(self.path)
                        if not any(key in previous for key in _SECRET_KEYS):
                            self._write_atomic(self.backup_path, previous)
                    except (OSError, IOError, ValueError, UnicodeError) as error:
                        LOG.warning("not backing up invalid settings (%s)", type(error).__name__)
                self._write_atomic(self.path, data)
                return True
            except (OSError, IOError, ValueError, TypeError) as error:
                LOG.error("settings save failed (%s); previous file and backup retained",
                          type(error).__name__)
                raise

    def get(self, key, default=None):
        with self._lock:
            if key in _SECRET_KEYS:
                return self.credentials.get(key) or (default or "")
            value = self.data.get(key, DEFAULTS.get(key, default))
            return default if value is None and default is not None else value

    def set(self, key, value, save=True):
        if key in _SECRET_KEYS:
            self.credentials.set(key, value)
            return
        with self._lock:
            previous = self.data.get(key)
            self.data[key] = value
        if save:
            try:
                self.save()
            except Exception:
                with self._lock:
                    self.data[key] = previous
                raise

    def favorites(self):
        with self._lock:
            return copy.deepcopy(self.data.get("favorites", []))

    def is_favorite(self, track_id):
        return any(int(item.get("id", 0)) == int(track_id) for item in self.favorites())

    def toggle_favorite(self, track):
        with self._lock:
            previous = self.favorites()
            items = self.favorites()
            for index, item in enumerate(items):
                if int(item.get("id", 0)) == int(track.id):
                    items.pop(index)
                    self.data["favorites"] = items
                    try:
                        self.save()
                    except Exception:
                        self.data["favorites"] = previous
                        raise
                    return False
            items.insert(0, track.to_json())
            self.data["favorites"] = items
            try:
                self.save()
            except Exception:
                self.data["favorites"] = previous
                raise
            return True

    def favorite_tracks(self):
        from .models import Track
        out = []
        for item in self.favorites():
            try:
                track = Track(**item)
                if track.id:
                    out.append(track)
            except (TypeError, ValueError) as error:
                LOG.warning("favorite skipped (%s)", type(error).__name__)
        return out

    def add_download(self, name, path, title, artist, url="", size=0, track_id=None):
        with self._lock:
            previous = copy.deepcopy(self.data.get("downloads", []))
            items = [item for item in self.data.get("downloads", []) if item.get("path") != path]
            items.insert(0, {"name": name, "path": path, "title": title, "artist": artist,
                             "url": _strip_url(url), "size": size, "track_id": track_id})
            self.data["downloads"] = items[:200]
            try:
                self.save()
            except Exception:
                self.data["downloads"] = previous
                raise

    def downloads(self):
        with self._lock:
            return copy.deepcopy(self.data.get("downloads", []))
