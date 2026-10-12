package com.soundcloudx.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Persisted settings, cached client_id and favorites. */
public final class Prefs {

    private static final String NAME = "soundcloud_x";

    private final SharedPreferences sp;

    public Prefs(Context ctx) {
        sp = ctx.getApplicationContext().getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    /** Shared instance to keep WebView-free access cheap. */
    private static Prefs sInstance;

    public static synchronized Prefs get(Context ctx) {
        if (sInstance == null) {
            sInstance = new Prefs(ctx);
        }
        return sInstance;
    }

    // ------------------------------------------------------------- client id --
    public String clientId() {
        return sp.getString("client_id", "");
    }

    public long clientIdTime() {
        return sp.getLong("client_id_time", 0L);
    }

    public void saveClientId(String id) {
        sp.edit().putString("client_id", id).putLong("client_id_time", System.currentTimeMillis()).apply();
    }

    // --------------------------------------------------------------- cookies --
    public String cookieHeader() {
        return sp.getString("cookie_header", "");
    }

    public void saveCookieHeader(String cookie) {
        sp.edit().putString("cookie_header", cookie == null ? "" : cookie).apply();
    }

    public boolean isLoggedIn() {
        String c = cookieHeader();
        return !TextUtils.isEmpty(c) && c.contains("oauth_token");
    }

    // -------------------------------------------------------------- language --
    public String language() {
        return sp.getString("language", "fa");
    }

    public void setLanguage(String lang) {
        sp.edit().putString("language", lang).apply();
    }

    // ------------------------------------------------------------ favorites ---
    public List<Track> favorites() {
        List<Track> out = new ArrayList<>();
        String raw = sp.getString("favorites", "[]");
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                Track t = Track.fromJson(o);
                if (t != null && t.id != 0) {
                    out.add(t);
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    public void saveFavorites(List<Track> tracks) {
        JSONArray arr = new JSONArray();
        for (Track t : tracks) {
            arr.put(t.toJson());
        }
        sp.edit().putString("favorites", arr.toString()).apply();
    }

    public boolean isFavorite(long id) {
        for (Track t : favorites()) {
            if (t.id == id) {
                return true;
            }
        }
        return false;
    }

    /** @return true when the track was added, false when it was removed. */
    public boolean toggleFavorite(Track track) {
        List<Track> list = favorites();
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).id == track.id) {
                list.remove(i);
                saveFavorites(list);
                return false;
            }
        }
        list.add(0, track);
        saveFavorites(list);
        return true;
    }

    public void removeFavorite(long id) {
        List<Track> list = favorites();
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).id == id) {
                list.remove(i);
                break;
            }
        }
        saveFavorites(list);
    }

    // ------------------------------------------------------------- last query --
    public String lastQuery() {
        return sp.getString("last_query", "");
    }

    public void saveLastQuery(String q) {
        sp.edit().putString("last_query", q == null ? "" : q).apply();
    }

    public int lastGenre() {
        return sp.getInt("last_genre", 0);
    }

    public void saveLastGenre(int index) {
        sp.edit().putInt("last_genre", index).apply();
    }

    // ------------------------------------------------------------ downloads ---
    public void addDownload(long id, String name, String title, String artist) {
        try {
            JSONArray arr = downloads();
            JSONObject o = new JSONObject();
            o.put("id", id);
            o.put("name", name);
            o.put("title", title);
            o.put("artist", artist);
            o.put("time", System.currentTimeMillis());
            arr.put(o);
            sp.edit().putString("downloads", arr.toString()).apply();
        } catch (Exception ignored) {
        }
    }

    public void removeDownload(long id) {
        try {
            JSONArray arr = downloads();
            JSONArray out = new JSONArray();
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o != null && o.optLong("id") != id) {
                    out.put(o);
                }
            }
            sp.edit().putString("downloads", out.toString()).apply();
        } catch (Exception ignored) {
        }
    }

    public JSONArray downloads() {
        try {
            return new JSONArray(sp.getString("downloads", "[]"));
        } catch (Exception e) {
            return new JSONArray();
        }
    }
}
