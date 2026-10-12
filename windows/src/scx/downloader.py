"""Atomic audio downloads, including segmented MP3 HLS and cancellation."""
from __future__ import annotations

import itertools
import os
import threading
import time

from . import util
from .media import audio_header, media_url, parse_playlist

CHUNK = 128 * 1024
MAX_PLAYLIST = 1024 * 1024


class DownloadCancelled(Exception):
    pass


def _cancel(event):
    if event is not None and event.is_set():
        raise DownloadCancelled()


def _close(response):
    close = getattr(response, "close", None)
    if close:
        close()


class Downloader(object):
    def __init__(self, session, timeout=30):
        self.session = session
        self.timeout = timeout

    def _request(self, url, cancel, headers=None):
        _cancel(cancel)
        media_url(url, url)
        response = self.session.get(url, stream=True, timeout=self.timeout, headers=headers or {})
        if response.status_code >= 400:
            _close(response)
            raise IOError("HTTP %d" % response.status_code)
        return response

    def _playlist(self, url, text, cancel, depth=0):
        if depth > 3:
            raise IOError("too many nested HLS playlists")
        child, segments = parse_playlist(text, url)
        if not child:
            return segments
        response = self._request(child, cancel)
        try:
            body = self._read_playlist(response.iter_content(CHUNK), cancel)
        finally:
            _close(response)
        return self._playlist(child, body, cancel, depth + 1)

    @staticmethod
    def _read_playlist(chunks, cancel):
        body = bytearray()
        for chunk in chunks:
            _cancel(cancel)
            body.extend(chunk)
            if len(body) > MAX_PLAYLIST:
                raise IOError("HLS playlist is too large")
        return body.decode("utf-8-sig")

    def fetch_to(self, url, target_path, on_progress=None, cancel_event=None, verify_audio=True):
        """Never publish a partial file, HTML error page or playlist as audio."""
        _cancel(cancel_event)
        folder = os.path.dirname(target_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        part = target_path + ".part"
        response = None
        started, done = time.monotonic(), 0

        def progress(total):
            if on_progress:
                on_progress(done, total, done / max(0.001, time.monotonic() - started))

        try:
            response = self._request(url, cancel_event)
            chunks = iter(response.iter_content(chunk_size=CHUNK))
            first = next((c for c in chunks if c), b"")
            if not first:
                raise IOError("the server sent an empty audio file")
            is_hls = first.lstrip(b"\xef\xbb\xbf \r\n").startswith(b"#EXTM3U")
            if is_hls:
                text = self._read_playlist(itertools.chain([first], chunks), cancel_event)
                _close(response)
                response = None
                segments = self._playlist(url, text, cancel_event)
                total = sum(s[2] for s in segments) if all(s[2] is not None for s in segments) else 0
                with open(part, "wb") as stream:
                    for segment_url, offset, length in segments:
                        headers = {"Range": "bytes=%d-%d" % (offset, offset + length - 1)} if length else {}
                        segment = self._request(segment_url, cancel_event, headers)
                        try:
                            if length and segment.status_code != 206:
                                raise IOError("server ignored the HLS byte range")
                            segment_done, checked = 0, False
                            for chunk in segment.iter_content(CHUNK):
                                _cancel(cancel_event)
                                if not chunk:
                                    continue
                                if not checked:
                                    if not audio_header(chunk, mp3_only=True):
                                        raise IOError("HLS segment is not MP3 audio")
                                    checked = True
                                stream.write(chunk)
                                segment_done += len(chunk)
                                done += len(chunk)
                                progress(total)
                            expected = length or int(segment.headers.get("Content-Length") or 0)
                            if not checked or expected and segment_done != expected:
                                raise IOError("incomplete HLS segment")
                        finally:
                            _close(segment)
            else:
                content_type = response.headers.get("Content-Type", "").lower()
                if verify_audio and ("text/" in content_type or "json" in content_type or not audio_header(first)):
                    raise IOError("the server did not send an audio file")
                total = int(response.headers.get("Content-Length") or 0)
                with open(part, "wb") as stream:
                    for chunk in itertools.chain([first], chunks):
                        _cancel(cancel_event)
                        if chunk:
                            stream.write(chunk)
                            done += len(chunk)
                            progress(total)
                if total and done != total:
                    raise IOError("incomplete audio download")
            _cancel(cancel_event)
            os.replace(part, target_path)
            progress(done)
            return target_path
        except Exception:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        finally:
            if response is not None:
                _close(response)

    def download_track(self, url, folder, filename, on_progress=None, cancel_event=None):
        return self.fetch_to(url, util.unique_path(folder, filename), on_progress, cancel_event)


class DownloadJob(object):
    def __init__(self, track, url, folder, filename, original=False):
        self.track, self.url, self.folder, self.filename = track, url, folder, filename
        self.original = original
        self.done, self.total, self.speed = 0, 0, 0.0
        self.path, self.error = None, None
        self.state = "queued"
        self.cancel_event = threading.Event()

    @property
    def progress(self):
        if self.state == "done":
            return 1.0
        return max(0.0, min(1.0, float(self.done) / self.total)) if self.total else 0.0

    @property
    def label(self):
        return "%s — %s" % (self.track.artist, self.track.title)

    def cancel(self):
        self.cancel_event.set()
