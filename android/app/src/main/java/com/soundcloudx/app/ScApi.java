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

    private static String sClientId;
    private static final Object LOCK = new Object();

    private ScApi() {
    }

    // =======================================================================
    //  errors
    // =======================================================================

    public static class ApiException extends IOException {
        private static final long serialVersionUID = 1L;

        public ApiException(String message) {
            super(message);
        }
    }

    // =======================================================================
    //  very small http layer
    // =======================================================================

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
                if (withCookies) {
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
                    if (loc.startsWith("/")) {
                        URL base = new URL(url);
                        loc = base.getProtocol() + "://" + base.getHost() + loc;
                    }
                    if (redirectsLeft <= 0) {
                        throw new IOException("too many redirects");
                    }
                    return httpGet(ctx, loc, withCookies, redirectsLeft - 1);
                }
                if (code == 401 || code == 403) {
                    throw new ApiException("unauthorized (" + code + ")");
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
            String cookie = cookieHeader(ctx);
            if (!TextUtils.isEmpty(cookie)) {
                c.setRequestProperty("Cookie", cookie);
            }
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                return c.getHeaderField("Location");
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
                } catch (Exception ignored) {
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
            } catch (Exception ignored) {
            }
            try {
                in.close();
            } catch (Exception ignored) {
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
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
    public static void refreshCookies(Context ctx) {
        try {
            String cookie = android.webkit.CookieManager.getInstance()
                    .getCookie("https://soundcloud.com");
            if (cookie == null) {
                cookie = "";
            }
            sCookieHeader = cookie;
            Prefs.get(ctx).saveCookieHeader(cookie);
        } catch (Throwable ignore) {
        }
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
        synchronized (LOCK) {
            if (!TextUtils.isEmpty(sClientId)) {
                return sClientId;
            }
            Prefs prefs = Prefs.get(ctx);
            String cached = prefs.clientId();
            long age = System.currentTimeMillis() - prefs.clientIdTime();
            if (!TextUtils.isEmpty(cached) && age < CLIENT_ID_TTL_MS) {
                sClientId = cached;
                return cached;
            }
            // 1) scrape a fresh id straight from soundcloud.com
            try {
                String scraped = scrapeClientId(ctx);
                if (!TextUtils.isEmpty(scraped) && validClientId(ctx, scraped)) {
                    prefs.saveClientId(scraped);
                    sClientId = scraped;
                    return scraped;
                }
            } catch (Exception ignored) {
            }
            // 2) the cached one (maybe it is still fine, just older than the TTL)
            if (!TextUtils.isEmpty(cached) && validClientId(ctx, cached)) {
                prefs.saveClientId(cached);
                sClientId = cached;
                return cached;
            }
            // 3) built in ids
            for (String id : BUILTIN_IDS) {
                try {
                    if (validClientId(ctx, id)) {
                        prefs.saveClientId(id);
                        sClientId = id;
                        return id;
                    }
                } catch (Exception ignored) {
                }
            }
            throw new ApiException("no working client_id");
        }
    }

    /** Forces a fresh discovery on the next call (used by the "reload" action). */
    public static void clearClientId() {
        synchronized (LOCK) {
            sClientId = null;
        }
    }

    public static boolean validClientId(Context ctx, String id) {
        try {
            String url = API_V2 + "/search/tracks?q=test&limit=1&client_id=" + enc(id);
            String body = httpGet(ctx, url, false);
            return body != null && body.contains("\"collection\"");
        } catch (Exception e) {
            return false;
        }
    }

    public static String scrapeClientId(Context ctx) throws IOException {
        String html = httpGet(ctx, SOUNDCLOUD_HOME, false);
        Set<String> scripts = new LinkedHashSet<>();
        Matcher m = P_JS.matcher(html);
        while (m.find() && scripts.size() < 10) {
            scripts.add(m.group());
        }

        for (Pattern p : new Pattern[]{P_CLIENT_ID_1, P_CLIENT_ID_2, P_CLIENT_ID_3, P_HYDRATION}) {
            Matcher mm = p.matcher(html);
            if (mm.find()) {
                return mm.group(1);
            }
        }

        int tried = 0;
        for (String script : scripts) {
            if (tried++ >= 8) {
                break;
            }
            try {
                String js = httpGet(ctx, script, false);
                for (Pattern p : new Pattern[]{P_CLIENT_ID_1, P_CLIENT_ID_2, P_CLIENT_ID_3}) {
                    Matcher mm = p.matcher(js);
                    if (mm.find()) {
                        return mm.group(1);
                    }
                }
            } catch (Exception ignored) {
            }
        }
        return null;
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
        String url = API_V2 + "/search/tracks?q=" + enc(query)
                + "&client_id=" + enc(clientId(ctx))
                + "&limit=" + limit + "&offset=" + offset
                + "&app_locale=en&linked_partitioning=1";
        JSONObject json = parseJson(httpGet(ctx, url, true));
        return collection(json);
    }

    public static List<Track> charts(Context ctx, String genreSlug, int limit) throws IOException {
        String url = API_V2 + "/charts?kind=trending&genre=soundcloud:genres:" + enc(genreSlug)
                + "&limit=" + limit + "&client_id=" + enc(clientId(ctx))
                + "&app_locale=en";
        JSONObject json = parseJson(httpGet(ctx, url, true));
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
        String api = API_V2 + "/resolve?url=" + enc(url) + "&client_id=" + enc(clientId(ctx));
        JSONObject json = parseJson(httpGet(ctx, api, true));
        return fromResolved(json);
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
        String url = API_V2 + "/tracks/" + id + "?client_id=" + enc(clientId(ctx));
        return Track.fromJson(parseJson(httpGet(ctx, url, true)));
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
        String cid = clientId(ctx);
        String auth = TextUtils.isEmpty(track.trackAuth) ? "" : "&track_authorization=" + enc(track.trackAuth);

        String[] paths = {
                "/media/soundcloud:tracks:" + track.id + "/stream/progressive?client_id=" + enc(cid) + auth,
                "/media/soundcloud:tracks:" + track.id + "/stream/hls?client_id=" + enc(cid) + auth,
        };
        for (String path : paths) {
            try {
                String direct = directUrlFrom(ctx, API_V2 + path);
                if (!TextUtils.isEmpty(direct)) {
                    return direct;
                }
            } catch (Exception ignored) {
            }
        }
        // Legacy redirect endpoint, still answers for most public tracks.
        try {
            String target = redirectTarget(ctx, API_V1 + "/tracks/" + track.id + "/stream?client_id=" + enc(cid));
            if (!TextUtils.isEmpty(target)) {
                return target;
            }
        } catch (Exception ignored) {
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
            String cookie = cookieHeader(ctx);
            if (!TextUtils.isEmpty(cookie)) {
                c.setRequestProperty("Cookie", cookie);
            }
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                return c.getHeaderField("Location");
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
        if (original) {
            String raw = track.downloadUrl;
            if (TextUtils.isEmpty(raw)) {
                try {
                    Track fresh = getTrack(ctx, track.id);
                    raw = fresh == null ? "" : fresh.downloadUrl;
                } catch (Exception ignored) {
                }
            }
            if (!TextUtils.isEmpty(raw)) {
                String sep = raw.contains("?") ? "&" : "?";
                String full = raw + sep + "client_id=" + enc(clientId(ctx));
                String token = oauthToken(ctx);
                if (!TextUtils.isEmpty(token)) {
                    full += "&oauth_token=" + enc(token);
                }
                String target = redirectTarget(ctx, full);
                if (!TextUtils.isEmpty(target)) {
                    return target;
                }
            }
        }
        return streamUrl(ctx, track);
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
            String[] exts = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".flac"};
            for (String ext : exts) {
                if (lower.endsWith(ext)) {
                    return ext;
                }
            }
        }
        return ".mp3";
    }
}
