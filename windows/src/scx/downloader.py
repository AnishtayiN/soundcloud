"""Background downloads with progress callbacks."""
from __future__ import annotations

import os
import threading

from . import util

CHUNK = 128 * 1024


class DownloadCancelled(Exception):
    pass


class Downloader(object):
    def __init__(self, session, timeout=30):
        self.session = session
        self.timeout = timeout

    def fetch_to(self, url, target_path, on_progress=None, cancel_event=None,
                 verify_audio=True):
        """Streams url into target_path ('.part' while running).

        on_progress(done_bytes, total_bytes, speed_bytes_per_second)
        """
        folder = os.path.dirname(target_path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        part = target_path + ".part"
        headers = {}
        done = 0
        start = None
        try:
            response = self.session.get(url, stream=True, timeout=self.timeout, headers=headers)
            if response.status_code >= 400:
                raise IOError("HTTP %d" % response.status_code)
            total = int(response.headers.get("Content-Length") or 0)
            if verify_audio and total and total < 4096:
                raise IOError("the server did not send an audio file (%d bytes)" % total)
            import time
            start = time.time()
            with open(part, "wb") as fh:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if not chunk:
                        continue
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadCancelled()
                    fh.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        elapsed = max(0.001, time.time() - (start or time.time()))
                        on_progress(done, total, done / elapsed)
            if os.path.exists(target_path):
                os.remove(target_path)
            os.rename(part, target_path)
            return target_path
        except Exception:
            try:
                if os.path.exists(part):
                    os.remove(part)
            except Exception:
                pass
            raise

    def download_track(self, url, folder, filename, on_progress=None, cancel_event=None):
        target = util.unique_path(folder, filename)
        return self.fetch_to(url, target, on_progress=on_progress,
                             cancel_event=cancel_event)


class DownloadJob(object):
    """One queued download, exposed to the UI."""

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
        self.state = "queued"          # queued | running | done | failed | cancelled
        self.cancel_event = threading.Event()

    @property
    def progress(self):
        if self.state == "done":
            return 1.0
        if not self.total:
            return 0.0
        return max(0.0, min(1.0, float(self.done) / float(self.total)))

    @property
    def label(self):
        return "%s — %s" % (self.track.artist, self.track.title)

    def cancel(self):
        self.cancel_event.set()
