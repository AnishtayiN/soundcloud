"""Explicit EXE smoke mode used by CI; normal startup never enters this module."""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
import wave


def run():
    import faulthandler
    faulthandler.dump_traceback_later(90, exit=True)
    def checkpoint(stage):
        path = os.environ.get("SCX_SMOKE_REPORT")
        if path:
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"success": False, "stage": stage}, stream)

    checkpoint("imports")
    from . import util
    from .api import SoundCloud
    from .store import Store
    from .ui import App

    class Response(object):
        def __init__(self, data=b"", status=200, headers=None):
            self.content = data
            self.text = data.decode("utf-8", "replace")
            self.status_code = status
            self.headers = headers or {}
        def json(self):
            return json.loads(self.text)
        def raise_for_status(self):
            if self.status_code >= 400:
                raise IOError("HTTP %d" % self.status_code)
        def iter_content(self, chunk_size=8192):
            for offset in range(0, len(self.content), chunk_size):
                yield self.content[offset:offset + chunk_size]
        def close(self):
            pass

    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(22050)
        stream.writeframes(b"\x00\x00" * 22050 * 4)
    wav = audio.getvalue()
    raw = {"id": 111, "title": "آهنگ آزمایشی", "artist": "خواننده آزمایشی",
           "duration": 4000, "streamable": True, "track_authorization": "fixture-auth",
           "download_url": "https://api-v2.soundcloud.com/tracks/111/download"}
    client_id = "a" * 32

    class Session(object):
        headers = {}
        def get(self, url, **kwargs):
            if url == "https://soundcloud.com/":
                return Response(("client_id='%s'" % client_id).encode())
            if "/stream/progressive" in url:
                return Response(b"https://fixture.invalid/audio.wav")
            if url.startswith("https://fixture.invalid/") or url.endswith("/download"):
                return Response(wav, headers={"Content-Length": str(len(wav))})
            if "/search/tracks" in url or "/charts" in url:
                return Response(json.dumps({"collection": [raw]}).encode())
            raise AssertionError("unexpected smoke request")

    report = {"platform": "windows", "checks": []}
    with tempfile.TemporaryDirectory(prefix="scx-smoke-") as folder:
        cache = os.path.join(folder, "cache")
        os.makedirs(cache)
        util.cache_dir = lambda: cache
        checkpoint("credential-vault")
        if os.name == "nt":
            store = Store(os.path.join(folder, "settings.json"))
            # Real DPAPI round trip on the Windows runner, not a mocked vault.
            store.set("cookie_header", "oauth_token=smoke-only")
            assert Store(store.path).get("cookie_header") == "oauth_token=smoke-only"
            store.set("cookie_header", "")
            report["checks"].append("dpapi-roundtrip-and-clear")
        else:
            # The production vault deliberately refuses plaintext on Linux.
            class MemoryVault(object):
                values = {}
                def get(self, key): return self.values.get(key, "")
                def set(self, key, value): self.values[key] = value
            store = Store(os.path.join(folder, "settings.json"), credentials=MemoryVault())
        checkpoint("ui-start")
        api = SoundCloud(store, session=Session())
        app = App(api, store, auto_load=False)

        def pump(seconds=0.1, until=None):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.update()
                if until is not None and until():
                    return
                time.sleep(0.02)
            app.update()
            if until is not None:
                assert until(), "timed out waiting for smoke condition"

        try:
            assert app.lang == "fa" and app.text_justify == "right"
            app.search_var.set("آهنگ")
            app.do_search()
            pump(10, lambda: bool(app.tracks))
            assert app.tracks[0].title == raw["title"]
            report["checks"].append("persian-search")
            checkpoint("play")
            app.play_index(0)
            pump(15, lambda: app.now_playing is not None and app.player.playing)
            report["checks"].append("play")
            app.toggle_play()
            assert app.player.paused
            app.toggle_play()
            assert app.player.playing
            report["checks"].append("pause-resume")
            checkpoint("download")
            app.toggle_favorite_current()
            app.start_download(app.now_playing)
            try:
                pump(15, lambda: bool(app.download_jobs) and app.download_jobs[0].state == "done")
            except AssertionError:
                job = app.download_jobs[0] if app.download_jobs else None
                raise AssertionError("download smoke state=%s error=%s" %
                                     (getattr(job, "state", None), getattr(job, "error", None)))
            assert os.path.getsize(app.download_jobs[0].path) == len(wav)
            report["checks"].append("complete-download")
            checkpoint("restart")
        finally:
            app.on_close()
        restored = Store(store.path)
        favorite = restored.favorite_tracks()[0]
        assert favorite.track_authorization == "fixture-auth"
        assert restored.downloads()[0]["track_id"] == 111
        second = App(SoundCloud(restored, session=Session()), restored, auto_load=False)
        try:
            second.show_favorites()
            second.update()
            assert second.tracks[0].id == 111
            report["checks"].append("restart-favorites-and-download-history")
        finally:
            second.on_close()
    report["success"] = True
    faulthandler.cancel_dump_traceback_later()
    return report
