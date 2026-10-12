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

    # ================================================================ cookies
    @property
    def cookie_header(self):
        return (self.store.get("cookie_header") or "") if self.store else ""

    def set_cookie_header(self, cookie):
        if self.store:
            self.store.set("cookie_header", cookie or "")

    def import_cookies_file(self, path):
        """Imports a Netscape cookies.txt exported from a browser."""
        pairs = []
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _flag, _path_, _secure, _exp, name, value = parts[:7]
                if "soundcloud.com" in domain:
                    pairs.append("%s=%s" % (name, value))
        cookie = "; ".join(pairs)
        if not cookie:
            raise SoundCloudError("no soundcloud cookies in this file")
        self.set_cookie_header(cookie)
        self.session.headers["Cookie"] = cookie
        return cookie

    @property
    def oauth_token(self):
        match = _RE_OAUTH.search(self.cookie_header)
        return match.group(1) if match else ""

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
        scripts = list(dict.fromkeys(_RE_JS.findall(html)))[:8]
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
    def _get_text(self, url, follow=True):
        response = self.session.get(url, timeout=self.timeout, allow_redirects=follow)
        if response.status_code in (401, 403):
            raise SoundCloudError("unauthorized (%s)" % response.status_code)
        response.raise_for_status()
        return response.text

    def _get_json(self, url):
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code in (401, 403):
            raise SoundCloudError("unauthorized (%s)" % response.status_code)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def _api_v2(self, path, params=None):
        params = dict(params or {})
        params["client_id"] = self.client_id
        params.setdefault("app_locale", "en")
        url = API_V2 + path + "?" + urllib.parse.urlencode(params)
        return self._get_json(url)

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
    def stream_url(self, track):
        """Direct CDN url of the 128 kbps progressive stream."""
        params = {"client_id": self.client_id}
        if track.track_authorization:
            params["track_authorization"] = track.track_authorization
        paths = [
            "/media/soundcloud:tracks:%s/stream/progressive" % track.id,
            "/media/soundcloud:tracks:%s/stream/hls" % track.id,
        ]
        for path in paths:
            try:
                url = API_V2 + path + "?" + urllib.parse.urlencode(params)
                response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    return response.headers.get("Location")
                if response.status_code == 200:
                    text = response.text.strip()
                    if text.startswith("http"):
                        return text.split("\n")[0].strip()
                    try:
                        data = json.loads(text)
                    except ValueError:
                        data = {}
                    if isinstance(data, dict):
                        if str(data.get("url", "")).startswith("http"):
                            return data["url"]
                        hls = data.get("hls") or {}
                        if str(hls.get("url", "")).startswith("http"):
                            return hls["url"]
            except Exception:
                continue
        # legacy endpoint
        try:
            url = "%s/tracks/%s/stream?client_id=%s" % (API_V1, track.id,
                                                        urllib.parse.quote(self.client_id))
            response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
            if response.status_code in (301, 302, 303, 307, 308):
                return response.headers.get("Location")
        except Exception:
            pass
        raise SoundCloudError("this track can not be streamed")

    def download_url(self, track, original=False):
        """Url to hand to the downloader. original=True asks for the source file."""
        if original:
            raw = track.download_url
            if not raw:
                try:
                    raw = self.track_details(track.id).get("download_url") or ""
                except Exception:
                    raw = ""
            if raw:
                params = {"client_id": self.client_id}
                if self.oauth_token:
                    params["oauth_token"] = self.oauth_token
                sep = "&" if "?" in raw else "?"
                full = raw + sep + urllib.parse.urlencode(params)
                try:
                    response = self.session.get(full, timeout=self.timeout, allow_redirects=False)
                    if response.status_code in (301, 302, 303, 307, 308):
                        return response.headers.get("Location")
                    if response.status_code == 200 and response.text.strip().startswith("http"):
                        return response.text.strip().split("\n")[0]
                except Exception:
                    pass
                raise SoundCloudError("original file needs a signed in account")
        return self.stream_url(track)

    @staticmethod
    def extension_for(url, original=False):
        if url:
            path = url.split("?")[0].lower()
            for ext in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".flac"):
                if path.endswith(ext):
                    return ext
        return ".mp3"
