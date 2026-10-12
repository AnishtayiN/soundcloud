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
REQUIRE_UI = False


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
        self.closed = False

    def close(self):
        self.closed = True

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
        "https://cf-media.sndcdn.com/": FakeResponse(content=b"ID3DATA" * 5000),
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
        check("file written", size == len(b"ID3DATA" * 5000), size)
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


def test_media_regressions():
    section("HLS / download regression tests")
    from scx.media import parse_playlist, PlaylistError
    from scx.downloader import Downloader
    from scx.api import SoundCloud, SoundCloudError
    from scx.models import Track
    from scx.store import Store
    base = "https://cdn.example/list.m3u8"
    body = "#EXTM3U\n#EXTINF:1,\na.mp3\nb.mp3\n#EXT-X-ENDLIST\n"
    child, segments = parse_playlist(body, base)
    check("HLS relative segments", len(segments) == 2 and segments[0][0] == "https://cdn.example/a.mp3")
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=64000\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=128000\nhigh.m3u8"
    check("HLS master variant", parse_playlist(master, base)[0].endswith("high.m3u8"))
    ranged = "#EXTM3U\n#EXT-X-BYTERANGE:10@0\na.mp3\n#EXT-X-BYTERANGE:20\na.mp3\n#EXT-X-ENDLIST"
    check("HLS implicit byte range", parse_playlist(ranged, base)[1][1][1:] == (10, 20))
    for name, bad in (
        ("encrypted", "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128\na.mp3\n#EXT-X-ENDLIST"),
        ("live", "#EXTM3U\na.mp3"),
        ("fMP4", "#EXTM3U\n#EXT-X-MAP:URI=init.mp4\na.m4a\n#EXT-X-ENDLIST"),
        ("unsafe URL", "#EXTM3U\nfile:///etc/passwd\n#EXT-X-ENDLIST"),
        ("implicit first range", "#EXTM3U\n#EXT-X-BYTERANGE:5\na.mp3\n#EXT-X-ENDLIST"),
        ("HTML", "<html>error</html>"),
    ):
        try:
            parse_playlist(bad, base)
            check("reject " + name, False)
        except PlaylistError:
            check("reject " + name, True)
    with tempfile.TemporaryDirectory() as folder:
        data_a, data_b = b"ID3" + b"a" * 5000, b"ID3" + b"b" * 5000
        session = FakeSession({base: FakeResponse(text=body),
            "https://cdn.example/a.mp3": FakeResponse(content=data_a),
            "https://cdn.example/b.mp3": FakeResponse(content=data_b)})
        path = os.path.join(folder, "real.mp3")
        Downloader(session).fetch_to(base, path)
        with open(path, "rb") as stream:
            check("HLS writes audio segments, not playlist", stream.read() == data_a + data_b)
        check("HLS temporary file removed", not os.path.exists(path + ".part"))
        html = FakeSession({base: FakeResponse(text="<html>not audio</html>")})
        try:
            Downloader(html).fetch_to(base, path)
            check("HTML not saved as audio", False)
        except IOError:
            with open(path, "rb") as stream:
                check("failed transfer preserves existing file", stream.read() == data_a + data_b)
            check("failed transfer removes partial", not os.path.exists(path + ".part"))
        short = FakeSession({base: FakeResponse(content=data_a, headers={"Content-Length": "999999"})})
        try:
            Downloader(short).fetch_to(base, os.path.join(folder, "short.mp3"))
            check("truncated audio rejected", False)
        except IOError:
            check("truncated audio rejected", True)
        store = Store(os.path.join(folder, "settings.json"))
        routes = make_routes()
        opaque = "https://api-v2.soundcloud.com/media/opaque/encoded/hls"
        raw = dict(TRACK_A, media={"transcodings": [{"url": opaque, "snipped": False,
            "format": {"protocol": "hls", "mime_type": "audio/mpeg"}}]})
        routes[opaque] = FakeResponse(json_data={"url": base})
        api = SoundCloud(store, session=FakeSession(routes))
        api.set_cookie_header("oauth_token=secret")
        check("actual advertised transcoding used", api.stream_url(Track.from_json(raw)) == base)
        calls = api.session.requests
        check("OAuth scoped to API host", any(k.get("headers", {}).get("Authorization") == "OAuth secret" for u,k in calls if u.startswith(opaque)))
        check("no global Cookie leaked to media CDN", "Cookie" not in api.session.headers)
        blocked = Track.from_json(dict(TRACK_A, streamable=False))
        try:
            api.stream_url(blocked)
            check("blocked tracks respected", False)
        except SoundCloudError:
            check("blocked tracks respected", True)
        routes["https://api-v2.soundcloud.com/tracks/111"] = FakeResponse(json_data=dict(TRACK_A, downloadable=False))
        try:
            api.download_url(Track.from_json(TRACK_A), original=True)
            check("Original never silently falls back to MP3", False)
        except SoundCloudError:
            check("Original never silently falls back to MP3", True)
        cookies = os.path.join(folder, "cookies.txt")
        with open(cookies, "w", encoding="utf-8") as stream:
            stream.write("#HttpOnly_.soundcloud.com\tTRUE\t/\tTRUE\t0\toauth_token\tvalid\n")
            stream.write("evil-soundcloud.com\tTRUE\t/\tTRUE\t0\toauth_token\twrong\n")
        check("HttpOnly cookies and strict domain", api.import_cookies_file(cookies) == "oauth_token=valid")


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


def test_ui():
    section("ui")
    try:
        import tkinter
    except Exception as exc:
        check("tkinter available", not REQUIRE_UI, str(exc))
        return
    try:
        from scx.ui import App
    except Exception:
        check("ui module imports", False, traceback.format_exc())
        return
    from scx.api import SoundCloud
    from scx.store import Store
    with tempfile.TemporaryDirectory() as folder:
        store = Store(os.path.join(folder, "settings.json"))
        api = SoundCloud(store, session=FakeSession(make_routes()))
        try:
            app = App(api, store, auto_load=False)
        except tkinter.TclError as exc:
            check("UI display available", not REQUIRE_UI, str(exc))
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
            app.do_search()
            app.show_favorites()
            until = time.time() + 0.3
            while time.time() < until:
                app.update()
                time.sleep(0.02)
            check("favorites ignores stale search response", app.mode == "favorites" and not app.tracks)
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
    global REQUIRE_UI
    REQUIRE_UI = "--require-ui" in argv
    FAILURES.clear()
    CHECKS[0] = 0
    print("SoundCloud X self test")
    tests = [test_util, test_models, test_store, test_api, test_downloader, test_media_regressions, test_player]
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
