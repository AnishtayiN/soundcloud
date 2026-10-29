#!/usr/bin/env python3
"""Offline self test for SoundCloud X (Windows).

Everything runs without a network connection: HTTP is replaced by a fake
session that answers with canned SoundCloud payloads.  It is executed by the
GitHub Actions workflow before the exe is built, so a broken build fails early.

    python selftest.py            # logic tests
    python selftest.py --ui       # logic tests + build the Tk window once
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

FAILURES = []
CHECKS = [0]


def check(name, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILURES.append("%s %s" % (name, detail))


def section(title):
    print("\n== %s ==" % title)


# --------------------------------------------------------------- fake http ---
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02"
       b"\x08\x02\x00\x00\x00\xfd\xd4\x9as\x00\x00\x00\x13IDATx\x9cc\xf8\xcf"
       b"\xc0\xf0\x9f\x81\x11\x0c\x8c\x0c\x0c\x00\x0e\x02\x01\x00\x18\xc9"
       b"\x1f\x9d\x00\x00\x00\x00IEND\xaeB`\x82")

TRACK_A = {
    "id": 111,
    "title": "Around the World",
    "duration": 428000,
    "streamable": True,
    "downloadable": True,
    "policy": "ALLOW",
    "genre": "Electronic",
    "playback_count": 1234567,
    "permalink_url": "https://soundcloud.com/daftpunk/around-the-world",
    "artwork_url": "https://i1.sndcdn.com/artworks-111-large.jpg",
    "track_authorization": "eyJhbGciOiJIUzI1NiJ9.test",
    "user": {"username": "Daft Punk",
             "avatar_url": "https://i1.sndcdn.com/avatars-000-large.jpg"},
}

TRACK_B = {
    "id": 222,
    "title": "Short one",
    "duration": 61000,
    "streamable": True,
    "downloadable": False,
    "permalink_url": "https://soundcloud.com/example/short-one",
    "artwork_url": "https://i1.sndcdn.com/artworks-222-large.jpg",
    "user": {"username": "Example"},
}

HOME_HTML = ("<html><head><script src=\"https://a-v2.sndcdn.com/assets/app-abc123.js\">"
             "</script></head><body><script>window.__sc_hydration = [{\"hydratable\":"
             "\"apiClient\",\"data\":{\"id\":\"0123456789abcdef0123456789abcdef\"}}]"
             "</script></body></html>")


class FakeResponse(object):
    def __init__(self, status_code=200, text="", content=None, headers=None,
                 json_data=None, chunks=None):
        self.status_code = status_code
        if not text and json_data is not None:
            text = json.dumps(json_data)
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers or {}
        self._json = json_data
        self._chunks = chunks

    def close(self):
        pass

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)

    def iter_content(self, chunk_size=1024):
        if self._chunks is not None:
            for chunk in self._chunks:
                yield chunk
            return
        data = self.content
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class FakeSession(object):
    def __init__(self, routes=None):
        self.headers = {}
        self.routes = routes or {}
        self.calls = []
        self.requests = []

    def get(self, url, **kwargs):
        """Routes are URL prefixes, the most specific one wins."""
        self.calls.append(url)
        self.requests.append((url, kwargs))
        best_key = None
        best_value = None
        for key, value in self.routes.items():
            if url.startswith(key) and (best_key is None or len(key) > len(best_key)):
                best_key, best_value = key, value
        if best_value is None:
            raise AssertionError("unexpected request: %s" % url)
        return best_value(url) if callable(best_value) else best_value


def make_routes():
    search_json = {"collection": [TRACK_A, TRACK_B], "total_results": 2}
    charts_json = {"collection": [{"track": TRACK_A}, {"track": TRACK_B}]}
    base = "https://api-v2.soundcloud.com"
    return {
        "https://soundcloud.com/": FakeResponse(text=HOME_HTML),
        "https://api-v2.soundcloud.com/":
            FakeResponse(status_code=404, json_data={"error": "not routed"}),
        base + "/search/tracks": FakeResponse(json_data=search_json),
        base + "/charts": FakeResponse(json_data=charts_json),
        base + "/resolve": FakeResponse(json_data=dict(TRACK_A, kind="track")),
        base + "/tracks/111/download":
            FakeResponse(status_code=302,
                         headers={"Location": "https://cf-media.sndcdn.com/original-111.wav"}),
        base + "/tracks/111":
            FakeResponse(json_data=dict(
                TRACK_A, kind="track",
                download_url="https://api.soundcloud.com/tracks/111/download")),
        base + "/media/soundcloud:tracks:111/stream/progressive":
            FakeResponse(status_code=302,
                         headers={"Location": "https://cf-media.sndcdn.com/stream-111.mp3?x=1"}),
        "https://api.soundcloud.com/tracks/111/download":
            FakeResponse(status_code=302,
                         headers={"Location": "https://cf-media.sndcdn.com/original-111.wav"}),
        "https://cf-media.sndcdn.com/": FakeResponse(content=b"MP3DATA" * 5000),
        "https://i1.sndcdn.com/": FakeResponse(content=PNG),
    }


# ------------------------------------------------------------------- tests ---
def test_util():
    section("util")
    from scx import util
    check("safe_filename strips slashes",
          util.safe_filename("a/b\\c:d*e?f") == "a_b_c_d_e_f",
          util.safe_filename("a/b\\c:d*e?f"))
    check("safe_filename keeps persian", util.safe_filename("آهنگ تست") == "آهنگ تست")
    check("safe_filename never empty", util.safe_filename("   ") == "track")
    check("human_size", util.human_size(1536) == "1.5 KB", util.human_size(1536))
    check("human_count", util.human_count(1234567) == "1.2M", util.human_count(1234567))
    check("format_duration", util.format_duration(428000) == "7:08",
          util.format_duration(428000))
    check("format_duration hours", util.format_duration(3725000) == "1:02:05",
          util.format_duration(3725000))
    with tempfile.TemporaryDirectory() as folder:
        first = util.unique_path(folder, "song.mp3")
        open(first, "wb").write(b"x")
        second = util.unique_path(folder, "song.mp3")
        check("unique_path avoids overwrite", second.endswith("song (1).mp3"), second)


def test_models():
    section("models")
    from scx.models import Track
    track = Track.from_json(TRACK_A)
    check("title parsed", track.title == "Around the World")
    check("artist parsed", track.artist == "Daft Punk")
    check("duration parsed", track.duration == 428000)
    check("subtitle contains artist", "Daft Punk" in track.subtitle)
    check("filename", track.filename() == "Daft Punk - Around the World.mp3",
          track.filename())
    check("thumb url", track.thumb_url.endswith("-t67x67.jpg"), track.thumb_url)
    check("to_json roundtrip", Track(**track.to_json()).id == 111)


def test_store():
    section("store")
    from scx.store import Store
    from scx.models import Track
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "settings.json")
        store = Store(path)
        store.set("language", "en")
        track = Track.from_json(TRACK_A)
        check("toggle favorite on", store.toggle_favorite(track) is True)
        check("favorite listed", len(store.favorites()) == 1)
        check("is_favorite", store.is_favorite(111))
        check("toggle favorite off", store.toggle_favorite(track) is False)
        store.add_download("a.mp3", os.path.join(folder, "a.mp3"), "title", "artist")
        reloaded = Store(path)
        check("settings persisted", reloaded.get("language") == "en")
        check("downloads persisted", len(reloaded.downloads()) == 1)
        check("favorite tracks usable", isinstance(store.favorite_tracks(), list))


def test_api():
    section("api")
    from scx.api import SoundCloud
    from scx.store import Store
    with tempfile.TemporaryDirectory() as folder:
        store = Store(os.path.join(folder, "settings.json"))
        session = FakeSession(make_routes())
        api = SoundCloud(store, session=session)

        check("client id scraped from the home page",
              api.client_id == "0123456789abcdef0123456789abcdef", api.client_id)
        check("client id cached", store.get("client_id") == api.client_id)

        results = api.search("daft punk")
        check("search returns tracks", len(results) == 2, len(results))
        check("search parses artist", results[0].artist == "Daft Punk")

        charts = api.charts("electronic")
        check("charts unwrap track objects", len(charts) == 2 and charts[0].id == 111)

        resolved = api.resolve("https://soundcloud.com/daftpunk/around-the-world")
        check("resolve returns one track", len(resolved) == 1 and resolved[0].id == 111)

        stream = api.stream_url(results[0])
        check("stream url follows the redirect",
              stream == "https://cf-media.sndcdn.com/stream-111.mp3?x=1", stream)

        original = api.download_url(results[0], original=True)
        check("original download url", original == "https://cf-media.sndcdn.com/original-111.wav",
              original)
        check("extension from url", SoundCloud.extension_for(original, True) == ".wav")

        api.forget_client_id()
        check("forget client id", api._client_id is None)


def test_downloader():
    section("downloader")
    from scx.downloader import Downloader
    from scx.api import SoundCloud
    from scx.store import Store
    with tempfile.TemporaryDirectory() as folder:
        store = Store(os.path.join(folder, "s.json"))
        session = FakeSession(make_routes())
        api = SoundCloud(store, session=session)
        downloader = Downloader(session)
        progress = []
        target = downloader.fetch_to(
            "https://cf-media.sndcdn.com/stream-111.mp3",
            os.path.join(folder, "out.mp3"),
            on_progress=lambda done, total, speed: progress.append((done, total)))
        size = os.path.getsize(target)
        check("file written", size == len(b"MP3DATA" * 5000), size)
        check("part file removed", not os.path.exists(target + ".part"))
        check("progress reported", bool(progress))

        url = api.stream_url(api.search("x")[0])
        path = downloader.download_track(url, folder, "Daft Punk - Around the World.mp3")
        check("download_track writes a named file",
              os.path.basename(path) == "Daft Punk - Around the World.mp3",
              os.path.basename(path))
        path2 = downloader.download_track(url, folder, "Daft Punk - Around the World.mp3")
        check("second download gets a new name", path2 != path, path2)

        import threading
        cancel = threading.Event()
        cancel.set()
        try:
            downloader.fetch_to("https://cf-media.sndcdn.com/stream-111.mp3",
                                os.path.join(folder, "cancel.mp3"), cancel_event=cancel)
            check("cancel raises", False)
        except Exception as exc:
            check("cancel raises", exc.__class__.__name__ == "DownloadCancelled",
                  exc.__class__.__name__)


def test_player():
    section("player")
    from scx.player import NullPlayer, Player
    check("format", Player.format(61000) == "1:01", Player.format(61000))
    player = NullPlayer("unit test")
    try:
        player.play()
        check("null player refuses to play", False)
    except Exception as exc:
        check("null player refuses to play", "unit test" in str(exc), str(exc))
    check("measure_duration of junk is 0", Player.measure_duration(__file__) == 0)


def test_regressions():
    section("P0 regressions")
    import threading
    import wave
    import io
    from unittest import mock
    from scx.api import SoundCloud, HOME
    from scx.downloader import Downloader, IncompleteDownload
    from scx.media_cache import MediaCache
    from scx.models import Track
    from scx.store import Store
    from scx.ui.playback import PlaybackMixin
    from scx.ui.lists import ListsMixin

    class MemoryVault(object):
        def __init__(self):
            self.values = {}
        def get(self, key):
            return self.values.get(key, "")
        def set(self, key, value):
            self.values[key] = value
        def delete(self, key):
            self.values.pop(key, None)
        def clear(self):
            self.values.clear()

    class UiStub(object):
        play_token = 0
        lang = "fa"
        def __init__(self):
            self.messages = []
            self.play_cancel = threading.Event()
            self.api = mock.Mock()
            self.media_cache = mock.Mock()
        def set_status(self, message):
            self.messages.append(message)
        def T(self, key, *args):
            from scx.strings import translate
            return translate("fa", key, *args)
        def show_progress(self, *args):
            pass
        def run_bg(self, work, done, failed):
            raise AssertionError("unstreamable track must return before background work")

    with tempfile.TemporaryDirectory() as folder:
        vault = MemoryVault()
        store = Store(os.path.join(folder, "settings.json"), credentials=vault)
        track = Track.from_json(dict(TRACK_A, download_url="https://api.soundcloud.com/tracks/111/download"))
        restored = Track(**json.loads(json.dumps(track.to_json())))
        check("authorization survives JSON round trip", restored.track_authorization == track.track_authorization)
        check("download URL survives JSON round trip", restored.download_url == track.download_url)
        check("artist survives JSON round trip", restored.artist == track.artist)
        ui = UiStub()
        PlaybackMixin.play_track(ui, Track.from_json(dict(TRACK_B, streamable=False)))
        check("unstreamable track never reaches API/cache", ui.api.stream_url.call_count == 0
              and ui.media_cache.get_or_fetch.call_count == 0 and ui.play_token == 0)
        check("unstreamable message is Persian", ui.messages == ["این آهنگ قابل پخش نیست"])

        # A tiny but structurally valid WAV, not arbitrary bytes with an .mp3 suffix.
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 8000)
        wav_bytes = audio.getvalue()
        check("default playback cache budget is 500 MB", Store(os.path.join(folder, "defaults.json"),
              credentials=MemoryVault()).get("cache_limit_mb") == 500)
        cache = MediaCache(os.path.join(folder, "cache"), Downloader(FakeSession()), 1)
        cached = cache.path_for(track, "https://cdn.example/audio?token=secret")
        with open(cached, "wb") as stream:
            stream.write(b"broken" * 2000)
        check("corrupt cache rejected", not cache.validate(cached))
        hls = cache.path_for(track, "https://cdn.example/playlist.m3u8?token=secret")
        check("HLS has track/type-specific playlist suffix", hls.endswith("scx-111-hls.m3u8"))
        with open(hls, "wb") as stream:
            stream.write(b"#EXTM3U\n#EXTINF:1,\nsegment.aac\n#EXT-X-ENDLIST\n")
        check("HLS playlist is not decoded as MP3", cache.validate(hls))
        session = FakeSession({"https://cdn.example/audio": FakeResponse(content=wav_bytes,
                               headers={"Content-Length": str(len(wav_bytes))})})
        cache.downloader = Downloader(session)
        result = cache.get_or_fetch(track, "https://cdn.example/audio")
        check("corrupt cache replaced with playable audio", result == cached and cache.validate(result))
        check("valid cache reused without request", cache.get_or_fetch(track, "https://cdn.example/audio") == result
              and len(session.calls) == 1)
        for index in range(3):
            path = os.path.join(cache.folder, "scx-%d-progressive.mp3" % (900 + index))
            with open(path, "wb") as stream:
                stream.write(b"x" * (450 * 1024))
            os.utime(path, (index + 1, index + 1))
        cache.trim()
        size = sum(os.path.getsize(os.path.join(cache.folder, name)) for name in os.listdir(cache.folder))
        check("500 MB default / configured byte budget enforced", size <= 1024 * 1024, str(size))

        target = os.path.join(folder, "download.wav")
        short = FakeResponse(content=wav_bytes[:-100], headers={"Content-Length": str(len(wav_bytes))})
        downloader = Downloader(FakeSession({"https://cdn.example/file": short}))
        try:
            with mock.patch("scx.downloader.CHUNK", 64):
                downloader.fetch_to("https://cdn.example/file", target)
            check("short download rejected", False)
        except IncompleteDownload:
            check("short download rejected", not os.path.exists(target) and os.path.exists(target + ".part"))
        remaining = wav_bytes[-100:]
        resume_session = FakeSession()
        def resume(url, **kwargs):
            sent = resume_session.requests[-1][1]
            check("resume sends HTTP Range", sent.get("headers", {}).get("Range") == "bytes=%d-" % (len(wav_bytes)-100))
            return FakeResponse(206, content=remaining, headers={"Content-Length": str(len(remaining)),
                                "Content-Range": "bytes %d-%d/%d" % (len(wav_bytes)-100, len(wav_bytes)-1, len(wav_bytes))})
        resume_session.routes["https://cdn.example/file"] = resume
        downloader = Downloader(resume_session)
        downloader.fetch_to("https://cdn.example/file", target)
        check("Range resume completes exact bytes", open(target, "rb").read() == wav_bytes)
        check("resume metadata removed", not os.path.exists(target + ".part.json"))
        ignored = FakeResponse(200, content=wav_bytes, headers={"Content-Length": str(len(wav_bytes))})
        with open(target + ".part", "wb") as stream:
            stream.write(b"old")
        Downloader(FakeSession({"https://cdn.example/file": ignored})).fetch_to("https://cdn.example/file", target)
        check("server ignoring Range restarts safely", open(target, "rb").read() == wav_bytes)

        store.toggle_favorite(track)
        store.set("volume", 0.65)
        backup_volume = json.load(open(store.backup_path, encoding="utf-8"))["volume"]
        with open(store.path, "w", encoding="utf-8") as stream:
            stream.write("{broken settings")
        recovered = Store(store.path, credentials=vault)
        check("corrupt settings restored from .bak", recovered.recovered_backup
              and recovered.is_favorite(track.id) and recovered.get("volume") == backup_volume)
        check("backup recovery itself persisted", Store(store.path, credentials=vault).is_favorite(track.id))
        before = open(store.path, "rb").read()
        with mock.patch("scx.store.os.replace", side_effect=OSError("disk full")):
            try:
                recovered.set("volume", 0.1)
                check("save failure reported", False)
            except OSError:
                check("save failure reported", True)
        check("atomic failure preserves settings", open(store.path, "rb").read() == before)
        check("failed setting rolled back in memory", recovered.get("volume") == backup_volume)
        favorites_before = recovered.favorites()
        with mock.patch("scx.store.os.replace", side_effect=OSError("disk full")):
            try:
                recovered.toggle_favorite(Track.from_json(dict(TRACK_B, id=222)))
                check("favorite save failure reported", False)
            except OSError:
                check("favorite save failure reported", True)
        check("failed favorite mutation rolled back", recovered.favorites() == favorites_before)
        legacy = os.path.join(folder, "legacy.json")
        with open(legacy, "w", encoding="utf-8") as stream:
            json.dump({"cookie_header": "oauth_token=SECRET", "favorites": [track.to_json()]}, stream)
        with open(legacy + ".bak", "w", encoding="utf-8") as stream:
            json.dump({"cookie_header": "oauth_token=OLD_SECRET", "favorites": []}, stream)
        migrated_vault = MemoryVault()
        migrated = Store(legacy, credentials=migrated_vault)
        check("legacy cookie migrated to vault", migrated_vault.get("cookie_header") == "oauth_token=SECRET")
        check("legacy plaintext removed from primary and backup", "SECRET" not in open(legacy).read()
              and "SECRET" not in open(legacy + ".bak").read())
        check("migration preserves favorites", migrated.is_favorite(track.id))
        migrated.set("cookie_header", "")
        Store(legacy, credentials=migrated_vault)
        check("migration cannot resurrect backed-up login after logout", migrated_vault.get("cookie_header") == "")

        # All candidates, including later HTML and JS matches, are validated.
        old = "a" * 32; stale = "b" * 32; fresh = "c" * 32; js_id = "d" * 32
        home = 'client_id="%s" clientId:"%s" client_id=%s <script src="https://a-v2.sndcdn.com/app.js"></script>' % (old, stale, fresh)
        def validation(url):
            return FakeResponse(json_data={"collection": []}) if url.endswith(js_id) else FakeResponse(403)
        routes = {HOME: FakeResponse(text=home),
                  "https://a-v2.sndcdn.com/app.js": FakeResponse(text="client_id='%s'" % js_id),
                  "https://api-v2.soundcloud.com/search/tracks": validation}
        api = SoundCloud(Store(os.path.join(folder, "api.json"), credentials=MemoryVault()), session=FakeSession(routes))
        check("scraper tries every HTML and JS candidate", api.client_id == js_id)
        check("scraper has no unused ids accumulator", all(len(x) == 32 for x in api._candidates(home)))

        for operation in ("search", "charts", "stream", "original"):
            calls = []
            api = SoundCloud(session=FakeSession())
            api._client_id = old; api._client_time = time.time()
            def scrape(rejected=None):
                check(operation + " invalidates rejected id", rejected == old and api._client_id is None)
                return fresh
            api._scrape_client_id = scrape
            def respond(url, **kwargs):
                calls.append(url)
                if len(calls) == 1:
                    return FakeResponse(401)
                if operation == "stream":
                    return FakeResponse(302, headers={"Location": "https://cdn.example/a.mp3"})
                if operation == "original":
                    return FakeResponse(302, headers={"Location": "https://cdn.example/a.wav"})
                return FakeResponse(json_data={"collection": [TRACK_A]})
            api.session = FakeSession({"https://": respond})
            if operation == "search": api.search("test")
            elif operation == "charts": api.charts()
            elif operation == "stream": api.stream_url(track)
            else: api.download_url(track, True)
            check(operation + " retries 401 exactly once with fresh id", len(calls) == 2
                  and old in calls[0] and fresh in calls[1] and fresh not in calls[0])

        # A stalled validation must not hold the client-id cache lock.
        api = SoundCloud(session=FakeSession())
        entered = threading.Event(); release = threading.Event(); outcomes = []
        def stalled(url, **kwargs):
            entered.set(); release.wait(3)
            return FakeResponse(json_data={"collection": []})
        api.session.get = stalled
        worker = threading.Thread(target=lambda: outcomes.append(api._valid_client_id(old)))
        worker.start(); entered.wait(2)
        acquired = api._id_lock.acquire(timeout=0.2)
        if acquired: api._id_lock.release()
        release.set(); worker.join(3)
        check("client-id lock excludes network work", acquired and outcomes == [True])

        class ListStub(ListsMixin):
            PAGE_SIZE = 30
            def __init__(self):
                self.busy = False; self._closing = False; self.list_generation = 0
                self._load_lock = threading.Lock(); self.mode = "search"; self.query = "old"
                self.offset = 0; self.jobs = []; self.rendered = []; self.errors = []
            def set_status(self, text): self.status = text
            def T(self, key, *args): return key
            def show_progress(self, *args, **kwargs): pass
            def _genre_slug(self): return "all-music"
            def run_bg(self, work, done, failed): self.jobs.append((done, failed))
            def _render_tracks(self, tracks, append): self.rendered.append((tracks, append))
        lists = ListStub(); lists.api = mock.Mock()
        lists.load_page(False); lists.query = "new"; lists.load_page(False)
        lists.jobs[0][0]([Track.from_json(TRACK_B)])
        lists.jobs[0][1]("old error")
        check("stale search cannot render or clear busy state", not lists.rendered and lists.busy)
        new_track = Track.from_json(TRACK_A)
        lists.jobs[1][0]([new_track])
        check("newest search wins", lists.rendered == [([new_track], False)] and not lists.busy)


def test_ui():
    section("ui")
    try:
        import tkinter
    except Exception as exc:
        print("  skip: tkinter unavailable (%s)" % exc)
        return
    try:
        from scx.ui import App
    except Exception:
        check("ui module imports", False, traceback.format_exc())
        return
    from scx.api import SoundCloud
    from scx.store import Store
    with tempfile.TemporaryDirectory() as folder:
        class UiVault(object):
            value = ""
            def get(self, key): return self.value
            def set(self, key, value): self.value = value
        store = Store(os.path.join(folder, "settings.json"), credentials=UiVault())
        api = SoundCloud(store, session=FakeSession(make_routes()))
        try:
            app = App(api, store, auto_load=False)
        except tkinter.TclError as exc:
            print("  skip: no display (%s)" % exc)
            return
        except Exception:
            check("window builds", False, traceback.format_exc())
            return
        check("window builds", True)
        try:
            app.update()
            app.search_var.set("daft punk")
            app.do_search()
            deadline = time.time() + 15
            while time.time() < deadline and not app.tracks:
                app.update()
                time.sleep(0.05)
            check("search renders rows", len(app.tracks) == 2, len(app.tracks))
            deadline = time.time() + 10
            while time.time() < deadline and not app.image_cache:
                app.update()
                time.sleep(0.05)
            check("cover art loaded", bool(app.image_cache))
            app.show_favorites()
            app.update()
            check("favorites view works", app.mode == "favorites")
            app.load_trending()
            deadline = time.time() + 15
            while time.time() < deadline and len(app.tracks) < 2:
                app.update()
                time.sleep(0.05)
            check("trending renders rows", len(app.tracks) == 2, len(app.tracks))
            app.open_downloads()
            app.update()
            app.open_settings()
            app.update()
            app.open_about if False else None
            check("windows opened", True)
        except Exception:
            check("ui interactions", False, traceback.format_exc())
        finally:
            try:
                app.on_close()
            except Exception:
                pass


def main(argv):
    print("SoundCloud X self test")
    tests = [test_util, test_models, test_store, test_api, test_downloader, test_player, test_regressions]
    if "--ui" in argv:
        tests.append(test_ui)
    for test in tests:
        try:
            test()
        except Exception:
            FAILURES.append(test.__name__)
            print("  EXCEPTION in %s\n%s" % (test.__name__, traceback.format_exc()))

    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        for item in FAILURES:
            print(" -", item)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
