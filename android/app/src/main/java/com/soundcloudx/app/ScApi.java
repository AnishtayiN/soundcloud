package com.soundcloudx.app;

import android.content.Context;
import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.GZIPInputStream;

/**
 * SoundCloud client.
 *
 * Everything is done with the Android framework only (HttpURLConnection +
 * org.json), so the app has no third party dependency at all.
 *
 * The public SoundCloud HTML5 API needs a "client_id" that SoundCloud rotates.
 * This class: (1) re-uses the last working id, (2) discovers a fresh one by
 * scraping soundcloud.com (HTML + JS bundles + the hydration payload) and
 * (3) falls back to a list of well known ids. The first id that answers a
 * cheap /search request is cached for 6 hours.
 */
public final class ScApi {

    public static final String API_V1 = "https://api.soundcloud.com";
    public static final String API_V2 = "https://api-v2.soundcloud.com";

    public static final String UA =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    + "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

    /** Genre slugs understood by the /charts endpoint. */
    public static final String[] GENRE_SLUGS = {
            "all-music", "electronic", "hiphoprap", "danceedm", "rock", "pop", "chill",
            "indie", "house", "techno", "trance", "dubstep", "trap", "drumandbass",
            "jazzblues", "classical", "piano", "rnb", "reggae", "latin", "metal",
            "world", "soul", "country", "soundtrack", "kpop"
    };

    public static final String[] GENRE_LABELS = {
            "همه سبک‌ها", "الکترونیک", "هیپ‌هاپ / رپ", "دنس / EDM", "راک", "پاپ", "چیل",
            "ایندی", "هاوس", "تکنو", "ترنس", "داب‌استپ", "ترپ", "درام اند باس",
            "جز / بلوز", "کلاسیک", "پیانو", "آر اند بی", "رگه", "لاتین", "متال",
            "موسیقی جهانی", "سول", "کانتری", "ساندترک", "کی‌پاپ"
    };

    /**
     * Ids seen in the wild. They are only a last resort: the scraper above is
     * the main source and any id that works is cached for a few hours.
     */
    private static final String[] BUILTIN_IDS = {
            "a3e059563d7fd3372b49b37f00a00bcf",
            "iZIs9mchVcX5lhVRyQGGAYlNPVldzAoX",
            "pW2mOdGXHLYYtcHgJWpJfFfpPOJdqnfS",
            "1c9zBsSbjLQcNoZOO2KdkfBQPBGCXkGy",
            "2t9Io8hwK8bNyoAKrCqEDECUqFFdKUcn",
            "YUKXc5GKnkHm9FCGvoVvPAvLcPQXqSG9",
            "kkjFA7QMutOwcO6VWRejWmvBQWyvXqBs"
    };

    private static final String SOUNDCLOUD_HOME = "https://soundcloud.com/";
    private static String testApiV1;
    private static String testApiV2;
    private static String testHome;

    // Package-private test seam, compiled to a rejecting operation in release.
    static void setTestEndpoints(String home, String v1, String v2) {
        if (!BuildConfig.DEBUG) {
            throw new IllegalStateException("test endpoints are disabled in release");
        }
        testHome = home;
        testApiV1 = v1;
        testApiV2 = v2;
    }
    private static String apiV1() { return testApiV1 == null ? API_V1 : testApiV1; }
    private static String apiV2() { return testApiV2 == null ? API_V2 : testApiV2; }
    private static String home() { return testHome == null ? SOUNDCLOUD_HOME : testHome; }

    private static final Pattern P_JS = Pattern.compile(
            "https://[a-zA-Z0-9.\\-]*sndcdn\\.com/[a-zA-Z0-9._/\\-]+\\.js");
    private static final Pattern P_CLIENT_ID_1 = Pattern.compile(
            "client_id[\"'\\s]{0,4}[:=][\"'\\s]{0,4}([0-9a-zA-Z]{32})");
    private static final Pattern P_CLIENT_ID_2 = Pattern.compile(
            "client_id=([0-9a-zA-Z]{32})");
    private static final Pattern P_CLIENT_ID_3 = Pattern.compile(
            "clientId[\"'\\s]{0,4}[:=][\"'\\s]{0,4}([0-9a-zA-Z]{32})");
    private static final Pattern P_HYDRATION = Pattern.compile(
            "\"apiClient\".{0,400}?\"id\"\\s*:\\s*\"([0-9a-zA-Z]{32})\"");
    private static final Pattern P_OAUTH = Pattern.compile("oauth_token=([^;\\s]+)");

    private static final long CLIENT_ID_TTL_MS = 6L * 60L * 60L * 1000L;

    // LOCK protects cached values only. Network discovery/validation is outside it.
    private static volatile String sClientId;
    private static volatile long sClientTime;
    private static final Object LOCK = new Object();
    private static final AtomicLong CLIENT_GENERATION = new AtomicLong();

    private ScApi() {
    }

    // =======================================================================
    //  errors
    // =======================================================================

    public static class ApiException extends IOException {
        private static final long serialVersionUID = 1L;

        public final int statusCode;

        public ApiException(String message) {
            this(message, 0);
        }

        public ApiException(String message, int statusCode) {
            super(message);
            this.statusCode = statusCode;
        }

        public boolean isAuthorizationFailure() {
            return statusCode == 401 || statusCode == 403;
        }
    }

    // =======================================================================
    //  very small http layer
    // =======================================================================

    private static boolean isSoundCloudHost(URL url) {
        String host = url.getHost();
        return "https".equals(url.getProtocol())
                && ("soundcloud.com".equals(host) || host.endsWith(".soundcloud.com"));
    }

    private static String httpGet(Context ctx, String url, boolean withCookies) throws IOException {
        return httpGet(ctx, url, withCookies, 5);
    }

    private static String httpGet(Context ctx, String url, boolean withCookies, int redirectsLeft)
            throws IOException {
        IOException last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            HttpURLConnection c = null;
            try {
                URL u = new URL(url);
                c = (HttpURLConnection) u.openConnection();
                c.setInstanceFollowRedirects(false);
                c.setConnectTimeout(15000);
                c.setReadTimeout(25000);
                c.setRequestMethod("GET");
                c.setRequestProperty("User-Agent", UA);
                c.setRequestProperty("Accept", "application/json, text/html, */*");
                c.setRequestProperty("Accept-Language", "en-US,en;q=0.9");
                c.setRequestProperty("Accept-Encoding", "gzip");
                if (withCookies && isSoundCloudHost(u)) {
                    String cookie = cookieHeader(ctx);
                    if (!TextUtils.isEmpty(cookie)) {
                        c.setRequestProperty("Cookie", cookie);
                    }
                }
                int code = c.getResponseCode();
                if (code >= 300 && code < 400) {
                    String loc = c.getHeaderField("Location");
                    if (loc == null) {
                        throw new IOException("HTTP " + code);
                    }
                    loc = new URL(new URL(url), loc).toString();
                    if (!loc.startsWith("https://")) {
                        throw new IOException("insecure redirect rejected");
                    }
                    if (redirectsLeft <= 0) {
                        throw new IOException("too many redirects");
                    }
                    return httpGet(ctx, loc, withCookies, redirectsLeft - 1);
                }
                if (code == 401 || code == 403) {
                    throw new ApiException("unauthorized (" + code + ")", code);
                }
                if (code >= 400) {
                    throw new IOException("HTTP " + code);
                }
                InputStream in = c.getInputStream();
                if ("gzip".equalsIgnoreCase(c.getContentEncoding())) {
                    in = new GZIPInputStream(in);
                }
                return readAll(in);
            } catch (ApiException e) {
                throw e;
            } catch (IOException e) {
                ScLog.failed("HTTP request attempt " + (attempt + 1), url, e);
                last = e;
                sleep(400L * (attempt + 1));
            } finally {
                if (c != null) {
                    c.disconnect();
                }
            }
        }
        throw last == null ? new IOException("network error") : last;
    }

    /** Follows one redirect (without downloading the body) and returns the target. */
    private static String redirectTarget(Context ctx, String url) throws IOException {
        HttpURLConnection c = null;
        try {
            URL u = new URL(url);
            c = (HttpURLConnection) u.openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            c.setRequestMethod("GET");
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept-Encoding", "identity");
            if (isSoundCloudHost(u)) {
                String cookie = cookieHeader(ctx);
                if (!TextUtils.isEmpty(cookie)) {
                    c.setRequestProperty("Cookie", cookie);
                }
            }
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                return c.getHeaderField("Location");
            }
            if (code == 401 || code == 403) {
                throw new ApiException("unauthorized (" + code + ")", code);
            }
            if (code >= 400) {
                throw new IOException("HTTP " + code);
            }
            InputStream in = c.getInputStream();
            try {
                byte[] buf = new byte[2048];
                int n = in.read(buf);
                if (n > 0) {
                    String body = new String(buf, 0, n, "UTF-8").trim();
                    if (body.startsWith("http")) {
                        int end = body.indexOf('\n');
                        return end > 0 ? body.substring(0, end).trim() : body;
                    }
                }
            } finally {
                try {
                    in.close();
                } catch (Exception error) {
                    ScLog.failed("close redirect response", url, error);
                }
            }
            return null;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    private static String readAll(InputStream raw) throws IOException {
        InputStream in = raw;
        ByteArrayOutputStream out = new ByteArrayOutputStream(16384);
        try {
            byte[] buf = new byte[16384];
            int n;
            int total = 0;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                total += n;
                // Safety valve: no single API/JS answer should be bigger than 24 MB.
                if (total > 24 * 1024 * 1024) {
                    break;
                }
            }
            return out.toString("UTF-8");
        } finally {
            try {
                out.close();
            } catch (Exception error) {
                ScLog.e("close API output", error);
            }
            try {
                in.close();
            } catch (Exception error) {
                ScLog.e("close API response", error);
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            ScLog.e("API retry interrupted", error);
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception error) {
            ScLog.e("UTF-8 URL encoding unavailable", error);
            return "";
        }
    }

    // =======================================================================
    //  cookies / session
    // =======================================================================

    /**
     * Cookie header used for API calls. Written by {@link #refreshCookies(Context)}
     * (always called from the UI thread) and read from worker threads afterwards.
     */
    private static volatile String sCookieHeader = "";

    /** Must be called from the UI thread (WebView/CookieManager). */
    public static boolean refreshCookies(Context ctx) {
        try {
            String cookie = android.webkit.CookieManager.getInstance()
                    .getCookie("https://soundcloud.com");
            if (cookie == null) {
                cookie = "";
            }
            if (!Prefs.get(ctx).saveCookieHeader(cookie)) {
                sCookieHeader = "";
                ScLog.e("cannot securely save session; credential storage unavailable");
                return false;
            }
            sCookieHeader = cookie;
            return true;
        } catch (Exception error) {
            sCookieHeader = "";
            ScLog.e("cannot refresh session securely", error);
            return false;
        }
    }

    public static void forgetCookies() {
        sCookieHeader = "";
    }

    public static String cookieHeader(Context ctx) {
        String cached = sCookieHeader;
        if (TextUtils.isEmpty(cached)) {
            cached = Prefs.get(ctx).cookieHeader();
        }
        return cached == null ? "" : cached;
    }

    public static boolean isLoggedIn(Context ctx) {
        return cookieHeader(ctx).contains("oauth_token");
    }

    public static String oauthToken(Context ctx) {
        Matcher m = P_OAUTH.matcher(cookieHeader(ctx));
        return m.find() ? m.group(1) : "";
    }

    // =======================================================================
    //  client id
    // =======================================================================

    public static String clientId(Context ctx) throws IOException {
        return clientId(ctx, null);
    }

    private static String clientId(Context ctx, String rejected) throws IOException {
        Prefs prefs = Prefs.get(ctx);
        long generation = CLIENT_GENERATION.get();
        String cached;
        long cachedTime;
        synchronized (LOCK) {
            if (sClientId == null) {
                sClientId = prefs.clientId();
                sClientTime = prefs.clientIdTime();
            }
            cached = sClientId;
            cachedTime = sClientTime;
        }
        long age = System.currentTimeMillis() - cachedTime;
        if (!TextUtils.isEmpty(cached) && !cached.equals(rejected)
                && age >= 0 && age < CLIENT_ID_TTL_MS) {
            return cached;
        }
        String discovered = scrapeClientId(ctx, rejected);
        if (!TextUtils.isEmpty(discovered)) {
            return publishClientId(ctx, discovered, generation);
        }
        if (!TextUtils.isEmpty(cached) && !cached.equals(rejected) && validClientId(ctx, cached)) {
            return publishClientId(ctx, cached, generation);
        }
        for (String id : BUILTIN_IDS) {
            if (!id.equals(rejected) && validClientId(ctx, id)) {
                return publishClientId(ctx, id, generation);
            }
        }
        throw new ApiException("no working client_id");
    }

    private static String publishClientId(Context ctx, String id, long generation) throws IOException {
        synchronized (LOCK) {
            if (CLIENT_GENERATION.get() != generation) {
                // A failure invalidated the cache while this discovery was running.
                if (!TextUtils.isEmpty(sClientId)) {
                    return sClientId;
                }
                throw new ApiException("client_id changed during discovery; retry request");
            }
            sClientId = id;
            sClientTime = System.currentTimeMillis();
            Prefs.get(ctx).saveClientId(id);
            return id;
        }
    }

    public static void clearClientId() {
        synchronized (LOCK) {
            CLIENT_GENERATION.incrementAndGet();
            sClientId = null;
            sClientTime = 0;
        }
    }

    /** Compare-and-clear: an old 401 must not invalidate another thread's new id. */
    public static void invalidateClientId(Context ctx, String rejected) {
        synchronized (LOCK) {
            if (rejected != null && !TextUtils.isEmpty(sClientId) && !rejected.equals(sClientId)) {
                return;
            }
            CLIENT_GENERATION.incrementAndGet();
            sClientId = null;
            sClientTime = 0;
            Prefs.get(ctx).clearClientId(rejected);
        }
    }

    public static void clearClientId(Context ctx) {
        invalidateClientId(ctx, null);
    }

    public static boolean validClientId(Context ctx, String id) {
        String url = apiV2() + "/search/tracks?q=test&limit=1&client_id=" + enc(id);
        try {
            String body = httpGet(ctx, url, false);
            return body != null && body.contains("\"collection\"");
        } catch (Exception error) {
            ScLog.failed("validate client_id", url, error);
            return false;
        }
    }

    private static void collectIds(String text, Set<String> ids) {
        for (Pattern pattern : new Pattern[]{P_CLIENT_ID_1, P_CLIENT_ID_2, P_CLIENT_ID_3, P_HYDRATION}) {
            Matcher matcher = pattern.matcher(text);
            while (matcher.find()) {
                ids.add(matcher.group(1));
            }
        }
    }

    /** Public for diagnostics; returns a validated id, trying EVERY candidate. */
    public static String scrapeClientId(Context ctx) throws IOException {
        return scrapeClientId(ctx, null);
    }

    private static String scrapeClientId(Context ctx, String rejected) throws IOException {
        String html = httpGet(ctx, home(), false);
        Set<String> scripts = new LinkedHashSet<>();
        Matcher matcher = P_JS.matcher(html);
        while (matcher.find() && scripts.size() < 10) {
            scripts.add(matcher.group());
        }
        Set<String> ids = new LinkedHashSet<>();
        collectIds(html, ids);
        for (String id : ids) {
            if (!id.equals(rejected) && validClientId(ctx, id)) {
                return id;
            }
        }
        int tried = 0;
        for (String script : scripts) {
            if (tried++ >= 8) {
                break;
            }
            try {
                ids.clear();
                collectIds(httpGet(ctx, script, false), ids);
                for (String id : ids) {
                    if (!id.equals(rejected) && validClientId(ctx, id)) {
                        return id;
                    }
                }
            } catch (Exception error) {
                ScLog.failed("scrape JavaScript", script, error);
            }
        }
        return null;
    }

    private interface ClientRequest<T> {
        T run(String clientId) throws IOException;
    }

    /** At most one authorization retry, with a newly scraped and validated id. */
    private static <T> T withClient(Context ctx, ClientRequest<T> request) throws IOException {
        String id = clientId(ctx);
        try {
            return request.run(id);
        } catch (ApiException error) {
            if (!error.isAuthorizationFailure()) {
                throw error;
            }
            ScLog.e("API authorization failed; refreshing client_id once");
            invalidateClientId(ctx, id);
            String fresh = clientId(ctx, id);
            return request.run(fresh);
        }
    }

    // =======================================================================
    //  search / charts / resolve
    // =======================================================================

    /**
     * Parses an api-v2 answer. org.json's checked JSONException is converted
     * into an IOException so callers only have to deal with one exception type.
     */
    private static JSONObject parseJson(String body) throws IOException {
        if (TextUtils.isEmpty(body)) {
            throw new IOException("empty answer from SoundCloud");
        }
        try {
            return new JSONObject(body);
        } catch (JSONException e) {
            throw new IOException("malformed answer from SoundCloud: " + e.getMessage(), e);
        }
    }

    public static List<Track> search(Context ctx, String query, int limit, int offset) throws IOException {
        if (!TextUtils.isEmpty(query) && query.startsWith("http")) {
            return resolveUrl(ctx, query.trim());
        }
        return withClient(ctx, id -> {
            String url = apiV2() + "/search/tracks?q=" + enc(query)
                    + "&client_id=" + enc(id) + "&limit=" + limit + "&offset=" + offset
                    + "&app_locale=en&linked_partitioning=1";
            return collection(parseJson(httpGet(ctx, url, true)));
        });
    }

    public static List<Track> charts(Context ctx, String genreSlug, int limit) throws IOException {
        JSONObject json = withClient(ctx, id -> parseJson(httpGet(ctx,
                apiV2() + "/charts?kind=trending&genre=soundcloud:genres:" + enc(genreSlug)
                        + "&limit=" + limit + "&client_id=" + enc(id) + "&app_locale=en", true)));
        List<Track> out = new ArrayList<>();
        JSONArray col = json.optJSONArray("collection");
        if (col != null) {
            for (int i = 0; i < col.length(); i++) {
                JSONObject item = col.optJSONObject(i);
                if (item == null) {
                    continue;
                }
                JSONObject track = item.optJSONObject("track");
                Track t = Track.fromJson(track != null ? track : item);
                if (t != null && t.id != 0) {
                    out.add(t);
                }
            }
        }
        return out;
    }

    /** Resolves a SoundCloud URL (track or playlist) into tracks. */
    public static List<Track> resolveUrl(Context ctx, String url) throws IOException {
        return withClient(ctx, id -> fromResolved(parseJson(httpGet(ctx,
                apiV2() + "/resolve?url=" + enc(url) + "&client_id=" + enc(id), true))));
    }

    private static List<Track> fromResolved(JSONObject json) {
        List<Track> out = new ArrayList<>();
        String kind = json.optString("kind", "");
        if ("playlist".equals(kind) || json.has("tracks")) {
            JSONArray arr = json.optJSONArray("tracks");
            if (arr != null) {
                for (int i = 0; i < arr.length(); i++) {
                    Track t = Track.fromJson(arr.optJSONObject(i));
                    if (t != null && t.id != 0) {
                        out.add(t);
                    }
                }
            }
        }
        if (out.isEmpty()) {
            Track t = Track.fromJson(json);
            if (t != null && t.id != 0) {
                out.add(t);
            }
        }
        return out;
    }

    /** Downloads a single track object (adds download_url / track_authorization). */
    public static Track getTrack(Context ctx, long id) throws IOException {
        return withClient(ctx, cid -> Track.fromJson(parseJson(httpGet(ctx,
                apiV2() + "/tracks/" + id + "?client_id=" + enc(cid), true))));
    }

    private static List<Track> collection(JSONObject json) {
        List<Track> out = new ArrayList<>();
        JSONArray arr = json.optJSONArray("collection");
        if (arr == null) {
            arr = json.optJSONArray("tracks");
        }
        if (arr == null) {
            return out;
        }
        for (int i = 0; i < arr.length(); i++) {
            Track t = Track.fromJson(arr.optJSONObject(i));
            if (t != null && t.id != 0) {
                out.add(t);
            }
        }
        return out;
    }

    // =======================================================================
    //  streaming / downloading
    // =======================================================================

    /** Direct CDN url of the 128 kbps progressive stream (fallbacks included). */
    public static String streamUrl(Context ctx, Track track) throws IOException {
        if (!track.streamable) {
            throw new ApiException("not streamable");
        }
        return withClient(ctx, id -> streamUrlWithClient(ctx, track, id));
    }

    private static String streamUrlWithClient(Context ctx, Track track, String cid) throws IOException {
        String auth = TextUtils.isEmpty(track.trackAuth) ? "" : "&track_authorization=" + enc(track.trackAuth);

        String[] paths = {
                "/media/soundcloud:tracks:" + track.id + "/stream/progressive?client_id=" + enc(cid) + auth,
                "/media/soundcloud:tracks:" + track.id + "/stream/hls?client_id=" + enc(cid) + auth,
        };
        for (String path : paths) {
            try {
                String direct = directUrlFrom(ctx, apiV2() + path);
                if (!TextUtils.isEmpty(direct)) {
                    return direct;
                }
            } catch (ApiException error) {
                if (error.isAuthorizationFailure()) {
                    throw error;
                }
                ScLog.e("stream format unavailable", error);
            } catch (Exception error) {
                ScLog.failed("resolve stream format", apiV2() + "/media/soundcloud:tracks:" + track.id, error);
            }
        }
        // Legacy redirect endpoint, still answers for most public tracks.
        try {
            String target = redirectTarget(ctx, apiV1() + "/tracks/" + track.id + "/stream?client_id=" + enc(cid));
            if (!TextUtils.isEmpty(target)) {
                return target;
            }
        } catch (ApiException error) {
            if (error.isAuthorizationFailure()) {
                throw error;
            }
            ScLog.e("legacy stream unavailable", error);
        } catch (Exception error) {
            ScLog.failed("resolve legacy stream", apiV1() + "/tracks/" + track.id + "/stream", error);
        }
        throw new ApiException("not streamable");
    }

    /**
     * @return the media url found in a api-v2 JSON answer, or the redirect target
     * of the endpoint when it answers with a 30x.
     */
    private static String directUrlFrom(Context ctx, String url) throws IOException {
        HttpURLConnection c = null;
        try {
            URL u = new URL(url);
            c = (HttpURLConnection) u.openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(15000);
            c.setReadTimeout(25000);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept", "application/json, */*");
            c.setRequestProperty("Accept-Encoding", "gzip");
            if (isSoundCloudHost(u)) {
                String cookie = cookieHeader(ctx);
                if (!TextUtils.isEmpty(cookie)) {
                    c.setRequestProperty("Cookie", cookie);
                }
            }
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                return c.getHeaderField("Location");
            }
            if (code == 401 || code == 403) {
                throw new ApiException("unauthorized (" + code + ")", code);
            }
            if (code >= 400) {
                throw new IOException("HTTP " + code);
            }
            InputStream in = c.getInputStream();
            if ("gzip".equalsIgnoreCase(c.getContentEncoding())) {
                in = new GZIPInputStream(in);
            }
            String body = readAll(in);
            if (TextUtils.isEmpty(body)) {
                return null;
            }
            String trimmed = body.trim();
            if (trimmed.startsWith("http")) {
                int nl = trimmed.indexOf('\n');
                return (nl > 0 ? trimmed.substring(0, nl) : trimmed).trim();
            }
            if (trimmed.startsWith("{")) {
                JSONObject json;
                try {
                    json = new JSONObject(trimmed);
                } catch (JSONException broken) {
                    ScLog.failed("parse stream response", url, broken);
                    return null;
                }
                String direct = json.optString("url", "");
                if (!TextUtils.isEmpty(direct) && direct.startsWith("http")) {
                    return direct;
                }
                JSONObject hls = json.optJSONObject("hls");
                if (hls != null) {
                    String hlsUrl = hls.optString("url", "");
                    if (!TextUtils.isEmpty(hlsUrl) && hlsUrl.startsWith("http")) {
                        return hlsUrl;
                    }
                }
            }
            return null;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    /**
     * @param original when true the original (best quality) file is requested,
     *                 which needs a signed in account and a downloadable track.
     * @return direct url of the file that can be handed to DownloadManager.
     */
    public static String downloadUrl(Context ctx, Track track, boolean original) throws IOException {
        if (!original) {
            return streamUrl(ctx, track);
        }
        return withClient(ctx, cid -> {
            String raw = track.downloadUrl;
            if (TextUtils.isEmpty(raw)) {
                Track fresh = getTrack(ctx, track.id);
                raw = fresh == null ? "" : fresh.downloadUrl;
            }
            if (TextUtils.isEmpty(raw)) {
                throw new ApiException("original file unavailable");
            }
            String full = raw + (raw.contains("?") ? "&" : "?") + "client_id=" + enc(cid);
            // The DownloadManager receives the Cookie header separately. Do not
            // put oauth_token in a URL persisted in the system download database.
            String target = redirectTarget(ctx, full);
            if (TextUtils.isEmpty(target)) {
                throw new ApiException("original file unavailable");
            }
            return target;
        });
    }

    /** Best effort guess of the file extension for a direct media url. */
    public static String extensionOf(String url, boolean original) {
        if (!TextUtils.isEmpty(url)) {
            String path = url;
            int q = path.indexOf('?');
            if (q > 0) {
                path = path.substring(0, q);
            }
            String lower = path.toLowerCase();
            String[] exts = {".m3u8", ".m3u", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".flac"};
            for (String ext : exts) {
                if (lower.endsWith(ext)) {
                    return ext;
                }
            }
        }
        return original ? ".bin" : ".mp3";
    }
}
