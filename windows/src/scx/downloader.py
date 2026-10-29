"""Interruptible downloads with validated resume and atomic publication."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time

from . import util
from .diagnostics import failed

CHUNK = 128 * 1024


class DownloadCancelled(Exception):
    pass


class IncompleteDownload(IOError):
    pass


class Downloader(object):
    def __init__(self, session, timeout=30):
        self.session = session
        self.timeout = timeout

    @staticmethod
    def _remove(path):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError as error:
            failed("remove incomplete download", error)

    @staticmethod
    def _read_meta(path):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                value = json.load(stream)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, UnicodeError):
            return {}

    @staticmethod
    def _write_meta(path, value):
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled()

    def fetch_to(self, url, target_path, on_progress=None, cancel_event=None,
                 verify_audio=True):
        """Publish only a complete body. Keep a valid .part for the next Range retry.

        Content-Length is an entity length, so compressed transfer encodings are
        refused rather than incorrectly compared with decoded output bytes.
        """
        target_path = os.path.abspath(target_path)
        folder = os.path.dirname(target_path)
        os.makedirs(folder, exist_ok=True)
        part = target_path + ".part"
        meta_path = part + ".json"
        fingerprint = hashlib.sha256(url.encode("utf-8")).hexdigest()
        meta = self._read_meta(meta_path)
        done = os.path.getsize(part) if os.path.isfile(part) else 0
        if meta.get("url_hash") != fingerprint or not done:
            done = 0
            self._remove(part)
            meta = {"url_hash": fingerprint}
        attempt = 0
        while attempt < 2:
            attempt += 1
            self._cancel(cancel_event)
            headers = {"Accept-Encoding": "identity"}
            if done:
                headers["Range"] = "bytes=%d-" % done
                if meta.get("etag") and not meta["etag"].startswith("W/"):
                    headers["If-Range"] = meta["etag"]
                elif meta.get("last_modified"):
                    headers["If-Range"] = meta["last_modified"]
            response = None
            append = False
            try:
                response = self.session.get(url, stream=True, timeout=self.timeout,
                                            headers=headers, allow_redirects=True)
                status = response.status_code
                if status == 416 and done:
                    self._close(response)
                    response = None
                    done = 0
                    self._remove(part)
                    meta = {"url_hash": fingerprint}
                    continue
                if status >= 400:
                    raise IOError("HTTP %d" % status)
                response_headers = response.headers
                encoding = response_headers.get("Content-Encoding", "identity").lower()
                if encoding not in ("", "identity"):
                    raise IOError("server did not honor identity transfer encoding")
                length_header = response_headers.get("Content-Length")
                length = int(length_header) if length_header not in (None, "") else -1
                if length < 0 and length_header not in (None, ""):
                    raise IOError("invalid Content-Length")
                total = max(0, length)
                if status == 206 and done:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)",
                                         response_headers.get("Content-Range", ""))
                    if not match or int(match.group(1)) != done:
                        raise IncompleteDownload("invalid Content-Range")
                    expected = None if match.group(3) == "*" else int(match.group(3))
                    if length >= 0 and expected is not None and done + length != expected:
                        raise IncompleteDownload("inconsistent Content-Range length")
                    if meta.get("total") not in (None, expected) and expected is not None:
                        raise IncompleteDownload("resource changed during resume")
                    total = expected if expected is not None else int(match.group(2)) + 1
                    append = True
                elif status == 200:
                    done = 0
                else:
                    raise IOError("unexpected HTTP status %d" % status)
                if verify_audio and length >= 0 and total < 4096:
                    raise IOError("the server did not send an audio file (%d bytes)" % total)
                meta.update({"total": total if total else None,
                             "etag": response_headers.get("ETag"),
                             "last_modified": response_headers.get("Last-Modified")})
                self._write_meta(meta_path, meta)
                start = time.monotonic()
                transferred = 0
                with open(part, "ab" if append else "wb") as stream:
                    for chunk in response.iter_content(chunk_size=CHUNK):
                        self._cancel(cancel_event)
                        if not chunk:
                            continue
                        stream.write(chunk)
                        done += len(chunk)
                        transferred += len(chunk)
                        if total and done > total:
                            raise IncompleteDownload("download exceeds Content-Length")
                        if on_progress:
                            on_progress(done, total, transferred / max(0.001, time.monotonic() - start))
                    stream.flush()
                    os.fsync(stream.fileno())
                self._cancel(cancel_event)
                if length >= 0 and done != total:
                    raise IncompleteDownload("incomplete download: %d of %d bytes" % (done, total))
                if verify_audio and done < 4096:
                    raise IncompleteDownload("download is too small to be audio")
                if verify_audio and not target_path.lower().endswith((".m3u8", ".m3u")):
                    with open(part, "rb") as stream:
                        prefix = stream.read(64).lstrip()
                    if prefix.startswith(b"#EXTM3U"):
                        raise IncompleteDownload("HLS playlist cannot be published as an audio file")
                os.replace(part, target_path)
                self._remove(meta_path)
                return target_path
            except Exception as error:
                # A short body/cancellation leaves ONLY .part, never a final file.
                # HTTP errors and changed resources cannot be safely resumed.
                response_status = getattr(response, "status_code", 0)
                if 400 <= response_status < 500 and response_status != 416:
                    self._remove(part)
                    self._remove(meta_path)
                failed("download", error, url)
                raise
            finally:
                self._close(response)
        raise IncompleteDownload("could not restart download")

    @staticmethod
    def _close(response):
        close = getattr(response, "close", None)
        if close:
            try:
                close()
            except Exception as error:
                failed("close download response", error)

    def download_track(self, url, folder, filename, on_progress=None, cancel_event=None,
                       verify_audio=True):
        target = util.unique_path(folder, filename)
        return self.fetch_to(url, target, on_progress=on_progress, cancel_event=cancel_event,
                             verify_audio=verify_audio)


class DownloadJob(object):
    def __init__(self, track, url, folder, filename, original=False):
        self.track = track
        self.url = url
        self.folder = folder
        self.filename = filename
        self.original = original
        self.done = 0
        self.total = 0
        self.speed = 0.0
        self.path = None
        self.error = None
        self.state = "queued"
        self.cancel_event = threading.Event()

    @property
    def progress(self):
        if self.state == "done":
            return 1.0
        return max(0.0, min(1.0, float(self.done) / float(self.total))) if self.total else 0.0

    @property
    def label(self):
        return "%s — %s" % (self.track.artist, self.track.title)

    def cancel(self):
        self.cancel_event.set()
