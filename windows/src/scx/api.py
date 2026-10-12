"""SoundCloud client for the desktop app.

Same idea as the Android side: no API key of our own is needed. The public
HTML5 API wants a rotating "client_id" that is published inside the website, so
we scrape it from soundcloud.com (HTML, hydration payload and the JS bundles),
verify it with a cheap /search call and cache the working value for 6 hours.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

import requests

from .models import Track

API_V1 = "https://api.soundcloud.com"
API_V2 = "https://api-v2.soundcloud.com"
HOME = "https://soundcloud.com/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CLIENT_ID_TTL = 6 * 60 * 60  # seconds

GENRES = [
    ("all-music", "همه سبک‌ها (All music)"),
    ("electronic", "الکترونیک"),
    ("hiphoprap", "هیپ‌هاپ / رپ"),
    ("danceedm", "دنس / EDM"),
    ("rock", "راک"),
    ("pop", "پاپ"),
    ("chill", "چیل"),
    ("indie", "ایندی"),
    ("house", "هاوس"),
    ("techno", "تکنو"),
    ("trance", "ترنس"),
    ("dubstep", "داب‌استپ"),
    ("trap", "ترپ"),
    ("drumandbass", "درام اند باس"),
    ("jazzblues", "جز / بلوز"),
    ("classical", "کلاسیک"),
    ("piano", "پیانو"),
    ("rnb", "آر اند بی"),
    ("reggae", "رگه"),
    ("latin", "لاتین"),
    ("metal", "متال"),
    ("world", "موسیقی جهانی"),
    ("soul", "سول"),
    ("country", "کانتری"),
    ("soundtrack", "ساندترک"),
    ("kpop", "کی‌پاپ"),
]

# Last resort ids; a freshly scraped one always wins.
BUILTIN_IDS = [
    "a3e059563d7fd3372b49b37f00a00bcf",
    "iZIs9mchVcX5lhVRyQGGAYlNPVldzAoX",
    "pW2mOdGXHLYYtcHgJWpJfFfpPOJdqnfS",
    "1c9zBsSbjLQcNoZOO2KdkfBQPBGCXkGy",
    "2t9Io8hwK8bNyoAKrCqEDECUqFFdKUcn",
    "YUKXc5GknkHm9FCGvoVvPAvLcPQXqSG9",
    "kkjFA7QMutOwcO6VWRejWmvBQWyvXqBs",
]

_RE_JS = re.compile(r'https://[a-zA-Z0-9.\-]*sndcdn\.com/[a-zA-Z0-9._/\-]+\.js')
_RE_ID_1 = re.compile(r'client_id["\'\s]{0,4}[:=]["\'\s]{0,4}([0-9a-zA-Z]{32})')
_RE_ID_2 = re.compile(r'client_id=([0-9a-zA-Z]{32})')
_RE_ID_3 = re.compile(r'clientId["\'\s]{0,4}[:=]["\'\s]{0,4}([0-9a-zA-Z]{32})')
_RE_HYDRATION = re.compile(r'"apiClient".{0,400}?"id"\s*:\s*"([0-9a-zA-Z]{32})"')
_RE_OAUTH = re.compile(r'oauth_token=([^;\s]+)')


class SoundCloudError(Exception):
    pass


class SoundCloud(object):
    def __init__(self, store=None, timeout=20, session=None):
        self.store = store
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self._client_id = None
        self._closed = False

    # ================================================================ cookies
    @property
    def cookie_header(self):
        return (self.store.get("cookie_header") or "") if self.store else ""

    def set_cookie_header(self, cookie):
        self.session.headers.pop("Cookie", None)
        if self.store:
            self.store.set("cookie_header", cookie or "")

    def import_cookies_file(self, path):
        """Imports a Netscape cookies.txt exported from a browser."""
        pairs = []
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _flag, _path_, _secure, _exp, name, value = parts[:7]
                if domain.lstrip(".") == "soundcloud.com" or domain.endswith(".soundcloud.com"):
                    pairs.append("%s=%s" % (name, value))
        cookie = "; ".join(pairs)
        if not cookie:
            raise SoundCloudError("no soundcloud cookies in this file")
        self.set_cookie_header(cookie)
        return cookie

    @property
    def oauth_token(self):
        match = _RE_OAUTH.search(self.cookie_header)
        return urllib.parse.unquote(match.group(1)) if match else ""

    @property
    def logged_in(self):
        return bool(self.oauth_token)

    # =============================================================== client id
    @property
    def client_id(self):
        if self._client_id:
            return self._client_id
        cached = self.store.get("client_id") if self.store else ""
        cached_time = float(self.store.get("client_id_time", 0) or 0) if self.store else 0
        if cached and (time.time() - cached_time) < CLIENT_ID_TTL:
            self._client_id = cached
            return cached
        try:
            scraped = self._scrape_client_id()
        except Exception:
            scraped = None
        if scraped and self._valid_client_id(scraped):
            self._remember(scraped)
            return scraped
        if cached and self._valid_client_id(cached):
            self._remember(cached)
            return cached
        for candidate in BUILTIN_IDS:
            try:
                if self._valid_client_id(candidate):
                    self._remember(candidate)
                    return candidate
            except Exception:
                continue
        raise SoundCloudError("could not find a working SoundCloud client_id")

    def _remember(self, client_id):
        self._client_id = client_id
        if self.store:
            self.store.set("client_id", client_id, save=False)
            self.store.set("client_id_time", time.time(), save=True)

    def forget_client_id(self):
        self._client_id = None
        if self.store:
            self.store.set("client_id", "", save=False)
            self.store.set("client_id_time", 0, save=True)

    def _valid_client_id(self, client_id):
        if self._closed:
            return False
        try:
            url = API_V2 + "/search/tracks?q=test&limit=1&client_id=" + urllib.parse.quote(client_id)
            response = self.session.get(url, timeout=self.timeout)
            return response.status_code == 200 and '"collection"' in response.text
        except Exception:
            return False

    def _scrape_client_id(self):
        html = self._get_text(HOME)
        ids = []
        for pattern in (_RE_ID_1, _RE_ID_2, _RE_ID_3, _RE_HYDRATION):
            match = pattern.search(html)
            if match:
                return match.group(1)
        scripts = list(reversed(list(dict.fromkeys(_RE_JS.findall(html)))))[:12]
        for script in scripts:
            try:
                js = self._get_text(script)
            except Exception:
                continue
            for pattern in (_RE_ID_1, _RE_ID_2, _RE_ID_3):
                match = pattern.search(js)
                if match:
                    return match.group(1)
        return ids[0] if ids else None

    # ==================================================================== http
    def close(self):
        self._closed = True
        close = getattr(self.session, "close", None)
        if close:
            close()

    def _ensure_open(self):
        if self._closed:
            raise SoundCloudError("application closed")

    def _get_text(self, url, follow=True):
        self._ensure_open()
        response = self.session.get(url, timeout=self.timeout, allow_redirects=follow)
        if response.status_code in (401, 403):
            raise SoundCloudError("unauthorized (%s)" % response.status_code)
        response.raise_for_status()
        return response.text

    def _auth_headers(self, url):
        host = urllib.parse.urlparse(url).hostname or ""
        if host == "soundcloud.com" or host.endswith(".soundcloud.com"):
            headers = {"Cookie": self.cookie_header} if self.cookie_header else {}
            if self.oauth_token:
                headers["Authorization"] = "OAuth " + self.oauth_token
            return headers
        return {}

    def _get_json(self, url):
        self._ensure_open()
        response = self.session.get(url, timeout=self.timeout, headers=self._auth_headers(url))
        if response.status_code in (401, 403):
            raise SoundCloudError("unauthorized (%s)" % response.status_code)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def _api_v2(self, path, params=None):
        params = dict(params or {})
        params.setdefault("app_locale", "en")
        for attempt in range(2):
            params["client_id"] = self.client_id
            url = API_V2 + path + "?" + urllib.parse.urlencode(params)
            try:
                return self._get_json(url)
            except SoundCloudError:
                if attempt:
                    raise
                self.forget_client_id()

    # ================================================================== search
    def search(self, query, limit=30, offset=0):
        query = (query or "").strip()
        if not query:
            return []
        if query.startswith("http"):
            return self.resolve(query)
        data = self._api_v2("/search/tracks", {
            "q": query, "limit": limit, "offset": offset, "linked_partitioning": 1,
        })
        return self._collection(data)

    def charts(self, genre="all-music", limit=30, offset=0):
        data = self._api_v2("/charts", {
            "kind": "trending",
            "genre": "soundcloud:genres:" + genre,
            "limit": limit,
            "offset": offset,
        })
        tracks = []
        for item in (data or {}).get("collection", []) or []:
            raw = item.get("track") or item
            track = Track.from_json(raw)
            if track:
                tracks.append(track)
        return tracks

    def resolve(self, url):
        data = self._api_v2("/resolve", {"url": url})
        if not data:
            return []
        tracks = []
        if data.get("kind") == "playlist" or data.get("tracks"):
            for raw in data.get("tracks") or []:
                track = Track.from_json(raw)
                if track:
                    tracks.append(track)
        if not tracks:
            track = Track.from_json(data)
            if track:
                tracks.append(track)
        return tracks

    def track_details(self, track_id):
        data = self._api_v2("/tracks/%s" % track_id)
        return data or {}

    @staticmethod
    def _collection(data):
        tracks = []
        for raw in (data or {}).get("collection", []) or (data or {}).get("tracks", []) or []:
            track = Track.from_json(raw)
            if track:
                tracks.append(track)
        return tracks

    # ================================================================ playback
    def _direct_url(self, url):
        self._ensure_open()
        response = self.session.get(url, timeout=self.timeout, allow_redirects=False,
                                    headers=self._auth_headers(url))
        if response.status_code in (301, 302, 303, 307, 308):
            target = response.headers.get("Location") or ""
        elif response.status_code == 200:
            text = response.text.strip()
            if text.startswith("https://"):
                target = text.split("\n")[0]
            else:
                data = response.json()
                target = data.get("url") or data.get("redirectUri") or ""
        else:
            raise SoundCloudError("media request failed (HTTP %d)" % response.status_code)
        target = urllib.parse.urljoin(url, target)
        if not target or urllib.parse.urlparse(target).scheme != "https" or target == url:
            raise SoundCloudError("no valid media URL returned")
        return target

    def stream_url(self, track):
        """Use the actual transcoding endpoints advertised by SoundCloud.

        MP3 progressive first, then complete, unencrypted MP3 HLS. Guessing
        /media/<id>/stream URLs is only a legacy fallback, not the main path.
        """
        if not track.streamable or track.policy == "BLOCK":
            raise SoundCloudError("this track is not available for streaming")
        transcodings, auth = track.transcodings, track.track_authorization
        if not transcodings:
            details = self.track_details(track.id)
            transcodings = (details.get("media") or {}).get("transcodings") or []
            auth = details.get("track_authorization") or auth
        params = {"client_id": self.client_id}
        if auth:
            params["track_authorization"] = auth
        candidates = []
        for item in transcodings:
            fmt = item.get("format") or {}
            if (fmt.get("protocol") in ("progressive", "hls") and
                    "mpeg" in fmt.get("mime_type", "") and not item.get("snipped") and
                    "/preview/" not in item.get("url", "")):
                candidates.append(item)
        candidates.sort(key=lambda t: t["format"].get("protocol") != "progressive")
        for item in candidates:
            url = item.get("url") or ""
            if urllib.parse.urlparse(url).hostname != "api-v2.soundcloud.com":
                continue
            try:
                return self._direct_url(url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params))
            except Exception:
                continue
        if transcodings:
            raise SoundCloudError("no complete, unencrypted MP3 stream is available for this track")
        for path in ("/media/soundcloud:tracks:%s/stream/progressive" % track.id,
                     "/media/soundcloud:tracks:%s/stream/hls" % track.id):
            try:
                return self._direct_url(API_V2 + path + "?" + urllib.parse.urlencode(params))
            except Exception:
                continue
        raise SoundCloudError("this track cannot be streamed")

    def download_url(self, track, original=False):
        if not original:
            return self.stream_url(track)
        details = self.track_details(track.id)
        if not details.get("downloadable", track.downloadable):
            raise SoundCloudError("the artist has not enabled original downloads")
        params = {"client_id": self.client_id}
        # OAuth stays in the scoped request headers, not in a URL/log/CDN request.
        endpoints = [API_V2 + "/tracks/%s/download" % track.id]
        raw = details.get("download_url") or track.download_url
        if raw and urllib.parse.urlparse(raw).hostname in ("api.soundcloud.com", "api-v2.soundcloud.com"):
            endpoints.append(raw)
        for url in endpoints:
            try:
                return self._direct_url(url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params))
            except Exception:
                continue
        raise SoundCloudError("original file unavailable; sign in with an authorized account")

    @staticmethod
    def extension_for(url, original=False):
        if url:
            path = url.split("?")[0].lower()
            for ext in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".flac"):
                if path.endswith(ext):
                    return ext
        return ".mp3"
