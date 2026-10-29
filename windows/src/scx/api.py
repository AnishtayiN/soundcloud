"""SoundCloud client with bounded client-id retries and privacy-safe diagnostics."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse

import requests

from .credentials import CredentialError
from .diagnostics import LOG, failed
from .models import Track

API_V1 = "https://api.soundcloud.com"
API_V2 = "https://api-v2.soundcloud.com"
HOME = "https://soundcloud.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CLIENT_ID_TTL = 6 * 60 * 60

GENRES = [
    ("all-music", "همه سبک‌ها (All music)"),
    ("electronic", "الکترونیک"), ("hiphoprap", "هیپ‌هاپ / رپ"),
    ("danceedm", "دنس / EDM"), ("rock", "راک"), ("pop", "پاپ"),
    ("chill", "چیل"), ("indie", "ایندی"), ("house", "هاوس"),
    ("techno", "تکنو"), ("trance", "ترنس"), ("dubstep", "داب‌استپ"),
    ("trap", "ترپ"), ("drumandbass", "درام اند باس"),
    ("jazzblues", "جز / بلوز"), ("classical", "کلاسیک"),
    ("piano", "پیانو"), ("rnb", "آر اند بی"), ("reggae", "رگه"),
    ("latin", "لاتین"), ("metal", "متال"), ("world", "موسیقی جهانی"),
    ("soul", "سول"), ("country", "کانتری"), ("soundtrack", "ساندترک"),
    ("kpop", "کی‌پاپ"),
]
BUILTIN_IDS = [
    "a3e059563d7fd3372b49b37f00a00bcf", "iZIs9mchVcX5lhVRyQGGAYlNPVldzAoX",
    "pW2mOdGXHLYYtcHgJWpJfFfpPOJdqnfS", "1c9zBsSbjLQcNoZOO2KdkfBQPBGCXkGy",
    "2t9Io8hwK8bNyoAKrCqEDECUqFFdKUcn", "YUKXc5GKnkHm9FCGvoVvPAvLcPQXqSG9",
    "kkjFA7QMutOwcO6VWRejWmvBQWyvXqBs",
]
_RE_JS = re.compile(r'https://[a-zA-Z0-9.\-]*sndcdn\.com/[a-zA-Z0-9._/\-]+\.js')
_PATTERNS = (
    re.compile(r'client_id["\'\s]{0,4}[:=]["\'\s]{0,4}([0-9a-zA-Z]{32})'),
    re.compile(r'client_id=([0-9a-zA-Z]{32})'),
    re.compile(r'clientId["\'\s]{0,4}[:=]["\'\s]{0,4}([0-9a-zA-Z]{32})'),
    re.compile(r'"apiClient".{0,400}?"id"\s*:\s*"([0-9a-zA-Z]{32})"'),
)
_RE_OAUTH = re.compile(r'(?:^|;\s*)oauth_token=([^;\s]+)')


class SoundCloudError(Exception):
    pass


class AuthorizationError(SoundCloudError):
    def __init__(self, status):
        self.status_code = status
        super().__init__("unauthorized (%s)" % status)


class SoundCloud(object):
    def __init__(self, store=None, timeout=20, session=None):
        self.store = store
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({"User-Agent": UA,
                                     "Accept": "application/json, text/html, */*",
                                     "Accept-Language": "en-US,en;q=0.9"})
        self._client_id = None
        self._client_time = 0.0
        self._id_lock = threading.RLock()
        self._generation = 0
        self._install_cookies(self.cookie_header)

    # ================================================================ cookies
    def _install_cookies(self, cookie):
        # Do not use a global Cookie header: requests also talks to image/CDN
        # hosts and follows redirects. Domain-scoped cookies stay on SoundCloud.
        self.session.headers.pop("Cookie", None)
        jar = getattr(self.session, "cookies", None)
        if jar is None:
            return
        for item in list(jar):
            if item.domain.endswith("soundcloud.com"):
                jar.clear(item.domain, item.path, item.name)
        for part in (cookie or "").split(";"):
            if "=" in part:
                name, value = part.strip().split("=", 1)
                if name:
                    jar.set(name, value, domain=".soundcloud.com", path="/", secure=True)

    @property
    def cookie_header(self):
        if not self.store:
            return ""
        try:
            return self.store.get("cookie_header") or ""
        except CredentialError as error:
            failed("load session", error)
            return ""

    def set_cookie_header(self, cookie):
        # Persist first. A vault failure must not look like a successful login.
        if self.store:
            self.store.set("cookie_header", cookie or "")
        self._install_cookies(cookie)

    def import_cookies_file(self, path):
        pairs = []
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7 and parts[0].endswith("soundcloud.com"):
                    pairs.append("%s=%s" % (parts[5], parts[6]))
        cookie = "; ".join(pairs)
        if not cookie:
            raise SoundCloudError("no soundcloud cookies in this file")
        self.set_cookie_header(cookie)
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
        return self._get_client_id()

    def _snapshot(self):
        with self._id_lock:
            if self._client_id is None and self.store:
                self._client_id = self.store.get("client_id") or ""
                self._client_time = float(self.store.get("client_id_time", 0) or 0)
            return self._client_id, self._client_time, self._generation

    def _get_client_id(self, rejected=None):
        cached, cached_at, generation = self._snapshot()
        age = time.time() - cached_at
        if cached and cached != rejected and 0 <= age < CLIENT_ID_TTL:
            return cached
        # No lock is held during scraping or any HTTP request.
        discovered = self._scrape_client_id(rejected)
        if discovered:
            return self._remember(discovered, generation)
        if cached and cached != rejected and self._valid_client_id(cached):
            return self._remember(cached, generation)
        for candidate in BUILTIN_IDS:
            if candidate != rejected and self._valid_client_id(candidate):
                return self._remember(candidate, generation)
        raise SoundCloudError("could not find a working SoundCloud client_id")

    def _remember(self, client_id, generation=None):
        with self._id_lock:
            if generation is not None and generation != self._generation:
                if self._client_id and self._client_id != client_id:
                    return self._client_id
                raise SoundCloudError("client_id changed during discovery")
            self._client_id = client_id
            self._client_time = time.time()
            if self.store:
                self.store.set("client_id", client_id, save=False)
                self.store.set("client_id_time", self._client_time, save=True)
            return client_id

    def forget_client_id(self, rejected=None):
        with self._id_lock:
            if rejected is not None and self._client_id and self._client_id != rejected:
                return
            self._generation += 1
            self._client_id = None
            self._client_time = 0
            if self.store:
                stored = self.store.get("client_id")
                if rejected is None or stored == rejected:
                    self.store.set("client_id", "", save=False)
                    self.store.set("client_id_time", 0, save=True)

    def _valid_client_id(self, client_id):
        url = API_V2 + "/search/tracks?q=test&limit=1&client_id=" + urllib.parse.quote(client_id)
        try:
            response = self.session.get(url, timeout=self.timeout)
            return response.status_code == 200 and '"collection"' in response.text
        except Exception as error:
            failed("validate client_id", error, url)
            return False

    @staticmethod
    def _candidates(text):
        # Deduplicate while retaining every distinct result and its discovery order.
        return dict.fromkeys(match.group(1) for pattern in _PATTERNS
                             for match in pattern.finditer(text))

    def _scrape_client_id(self, rejected=None):
        try:
            html = self._get_text(HOME)
        except Exception as error:
            failed("scrape homepage", error, HOME)
            return None
        for candidate in self._candidates(html):
            if candidate != rejected and self._valid_client_id(candidate):
                return candidate
        for script in list(dict.fromkeys(_RE_JS.findall(html)))[:8]:
            try:
                js = self._get_text(script)
                for candidate in self._candidates(js):
                    if candidate != rejected and self._valid_client_id(candidate):
                        return candidate
            except Exception as error:
                failed("scrape JavaScript", error, script)
        return None

    def _with_client(self, operation):
        client_id = self.client_id
        try:
            return operation(client_id)
        except AuthorizationError:
            LOG.warning("API authorization failed; refreshing client_id once")
            self.forget_client_id(client_id)
            fresh = self._get_client_id(rejected=client_id)
            return operation(fresh)  # A second 401/403 reaches the caller.

    # ==================================================================== http
    def _check(self, response):
        if response.status_code in (401, 403):
            raise AuthorizationError(response.status_code)
        response.raise_for_status()
        return response

    def _get_text(self, url, follow=True):
        response = self.session.get(url, timeout=self.timeout, allow_redirects=follow)
        return self._check(response).text

    def _get_json(self, url):
        response = self._check(self.session.get(url, timeout=self.timeout))
        return response.json() if response.content else None

    def _api_v2(self, path, params=None):
        def request(client_id):
            values = dict(params or {})
            values["client_id"] = client_id
            values.setdefault("app_locale", "en")
            url = API_V2 + path + "?" + urllib.parse.urlencode(values)
            return self._get_json(url)
        return self._with_client(request)

    # ================================================================== search
    def search(self, query, limit=30, offset=0):
        query = (query or "").strip()
        if not query:
            return []
        if query.startswith("http"):
            return self.resolve(query)
        return self._collection(self._api_v2("/search/tracks", {
            "q": query, "limit": limit, "offset": offset, "linked_partitioning": 1}))

    def charts(self, genre="all-music", limit=30, offset=0):
        data = self._api_v2("/charts", {"kind": "trending", "genre": "soundcloud:genres:" + genre,
                                       "limit": limit, "offset": offset})
        tracks = []
        for item in (data or {}).get("collection", []) or []:
            track = Track.from_json(item.get("track") or item)
            if track:
                tracks.append(track)
        return tracks

    def resolve(self, url):
        data = self._api_v2("/resolve", {"url": url})
        if not data:
            return []
        tracks = []
        if data.get("kind") == "playlist" or data.get("tracks"):
            tracks = [Track.from_json(raw) for raw in data.get("tracks") or []]
            tracks = [track for track in tracks if track]
        if not tracks:
            track = Track.from_json(data)
            if track:
                tracks.append(track)
        return tracks

    def track_details(self, track_id):
        return self._api_v2("/tracks/%s" % track_id) or {}

    @staticmethod
    def _collection(data):
        raw_tracks = (data or {}).get("collection") or (data or {}).get("tracks") or []
        return [track for track in (Track.from_json(raw) for raw in raw_tracks) if track]

    # ================================================================ playback
    def _media_response(self, url):
        response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location or not location.startswith("https://"):
                raise SoundCloudError("invalid media redirect")
            return location
        self._check(response)
        text = response.text.strip()
        if text.startswith("https://"):
            return text.split("\n")[0].strip()
        try:
            data = json.loads(text)
        except ValueError as error:
            failed("parse media response", error, url)
            return None
        if isinstance(data, dict):
            for value in (data.get("url"), (data.get("hls") or {}).get("url")):
                if str(value or "").startswith("https://"):
                    return value
        return None

    def stream_url(self, track):
        if not track.streamable:
            raise SoundCloudError("this track can not be streamed")

        def request(client_id):
            params = {"client_id": client_id}
            if track.track_authorization:
                params["track_authorization"] = track.track_authorization
            paths = ["/media/soundcloud:tracks:%s/stream/progressive" % track.id,
                     "/media/soundcloud:tracks:%s/stream/hls" % track.id,
                     None]
            for path in paths:
                url = ((API_V2 + path) if path else (API_V1 + "/tracks/%s/stream" % track.id))
                url += "?" + urllib.parse.urlencode(params)
                try:
                    target = self._media_response(url)
                    if target:
                        return target
                except AuthorizationError:
                    raise  # Never hide an expired id behind the next format.
                except Exception as error:
                    failed("resolve stream format", error, url)
            raise SoundCloudError("this track can not be streamed")
        return self._with_client(request)

    def download_url(self, track, original=False):
        if not original:
            return self.stream_url(track)

        def request(client_id):
            raw = track.download_url
            if not raw:
                try:
                    raw = self.track_details(track.id).get("download_url") or ""
                except AuthorizationError:
                    raise
                except Exception as error:
                    failed("load original download metadata", error)
            if not raw:
                raise SoundCloudError("original file needs a signed in account")
            full = raw + ("&" if "?" in raw else "?") + urllib.parse.urlencode({"client_id": client_id})
            try:
                target = self._media_response(full)
                if target:
                    return target
            except AuthorizationError:
                raise
            except Exception as error:
                failed("resolve original download", error, raw)
            raise SoundCloudError("original file needs a signed in account")
        return self._with_client(request)

    @staticmethod
    def extension_for(url, original=False):
        path = urllib.parse.urlsplit(url or "").path.lower()
        for ext in (".m3u8", ".m3u", ".mp3", ".m4a", ".aac", ".ogg", ".opus",
                    ".wav", ".aiff", ".aif", ".flac"):
            if path.endswith(ext):
                return ext
        return ".bin" if original else ".mp3"
