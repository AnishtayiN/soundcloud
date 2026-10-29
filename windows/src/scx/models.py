"""Data holder for one SoundCloud track."""
from __future__ import annotations

from . import util


class Track(object):
    __slots__ = (
        "id", "title", "artist", "duration", "artwork_url", "permalink_url",
        "genre", "playback_count", "streamable", "downloadable", "policy",
        "track_authorization", "download_url", "stream_url", "created_at",
    )

    def __init__(self, **kwargs):
        self.id = int(kwargs.get("id") or 0)
        self.title = kwargs.get("title") or ""
        self.artist = kwargs.get("artist") or ""
        self.duration = int(kwargs.get("duration") or 0)
        self.artwork_url = kwargs.get("artwork_url") or ""
        self.permalink_url = kwargs.get("permalink_url") or ""
        self.genre = kwargs.get("genre") or ""
        self.playback_count = int(kwargs.get("playback_count") or 0)
        self.streamable = bool(kwargs.get("streamable", True))
        self.downloadable = bool(kwargs.get("downloadable", False))
        self.policy = kwargs.get("policy") or "ALLOW"
        self.track_authorization = kwargs.get("track_authorization") or ""
        self.download_url = kwargs.get("download_url") or ""
        self.stream_url = kwargs.get("stream_url") or ""
        self.created_at = kwargs.get("created_at") or ""

    # ------------------------------------------------------------------ api --
    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            return None
        user = data.get("user") or {}
        artwork = data.get("artwork_url") or user.get("avatar_url") or ""
        track = cls(
            id=data.get("id"),
            title=data.get("title"),
            artist=user.get("username"),
            duration=data.get("duration"),
            artwork_url=artwork,
            permalink_url=data.get("permalink_url"),
            genre=data.get("genre"),
            playback_count=data.get("playback_count"),
            streamable=data.get("streamable", True),
            downloadable=data.get("downloadable", False),
            policy=data.get("policy", "ALLOW"),
            track_authorization=data.get("track_authorization"),
            download_url=data.get("download_url"),
        )
        return track if track.id else None

    def to_json(self):
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "artwork_url": self.artwork_url,
            "permalink_url": self.permalink_url,
            "genre": self.genre,
            "playback_count": self.playback_count,
            "streamable": self.streamable,
            "downloadable": self.downloadable,
            "policy": self.policy,
            "track_authorization": self.track_authorization,
            "download_url": self.download_url,
        }

    # --------------------------------------------------------------- helpers --
    @property
    def duration_text(self):
        return util.format_duration(self.duration)

    @property
    def plays_text(self):
        return util.human_count(self.playback_count)

    @property
    def thumb_url(self):
        return self.artwork_url.replace("-large", "-t67x67") if self.artwork_url else ""

    @property
    def cover_url(self):
        if not self.artwork_url:
            return ""
        # 200x200 does not exist for every upload, "-large" (100x100) always does.
        return self.artwork_url.replace("-large", "-t200x200")

    @property
    def subtitle(self):
        parts = []
        if self.artist:
            parts.append(self.artist)
        if self.duration:
            parts.append(self.duration_text)
        if self.plays_text:
            parts.append("▶ " + self.plays_text)
        if self.genre:
            parts.append(self.genre)
        if self.downloadable:
            parts.append("original ⬇")
        return "   •   ".join(parts)

    def filename(self, extension=".mp3"):
        base = (self.artist + " - " if self.artist else "") + self.title
        return util.safe_filename(base) + extension

    def __str__(self):
        return ("%s — %s" % (self.artist, self.title)).strip(" —")
