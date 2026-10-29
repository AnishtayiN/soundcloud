package com.soundcloudx.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.text.TextUtils;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Ordinary settings stay in JSON/preferences; credentials and signed favorites do not. */
public final class Prefs {
    private static final String NAME = "soundcloud_x";
    private static final String SECURE_NAME = "soundcloud_x_secure";
    private static Prefs sInstance;

    private final SharedPreferences sp;
    private SharedPreferences secure;

    public static synchronized Prefs get(Context ctx) {
        if (sInstance == null) {
            sInstance = new Prefs(ctx);
        }
        return sInstance;
    }

    public Prefs(Context ctx) {
        Context app = ctx.getApplicationContext();
        sp = app.getSharedPreferences(NAME, Context.MODE_PRIVATE);
        try {
            MasterKey key = new MasterKey.Builder(app)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build();
            secure = EncryptedSharedPreferences.create(app, SECURE_NAME, key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
            migrateSecrets();
        } catch (Exception error) {
            secure = null;
            // Never fall back to plaintext credentials. Old non-secret favorites
            // remain readable until they can be migrated without data loss.
            sp.edit().remove("cookie_header").remove("oauth_token").commit();
            ScLog.e("secure credential storage unavailable", error);
        }
    }

    private void migrateSecrets() {
        SharedPreferences.Editor target = secure.edit();
        if (sp.contains("cookie_header") && !secure.contains("cookie_header")) {
            target.putString("cookie_header", sp.getString("cookie_header", ""));
        }
        if (sp.contains("favorites") && !secure.getBoolean("favorites_migrated", false)) {
            target.putString("favorites", sp.getString("favorites", "[]"));
            target.putBoolean("favorites_migrated", true);
        }
        if (!target.commit()) {
            throw new IllegalStateException("credential migration commit failed");
        }
        // commit(), not apply(): plaintext must be gone before login/API work continues.
        if (!sp.edit().remove("cookie_header").remove("oauth_token").remove("favorites").commit()) {
            ScLog.e("could not remove legacy plaintext storage");
        }
    }

    public boolean secureStorageAvailable() {
        return secure != null;
    }

    public String clientId() {
        return sp.getString("client_id", "");
    }

    public long clientIdTime() {
        return sp.getLong("client_id_time", 0L);
    }

    public void saveClientId(String id) {
        sp.edit().putString("client_id", id)
                .putLong("client_id_time", System.currentTimeMillis()).apply();
    }

    public synchronized void clearClientId(String rejected) {
        if (rejected == null || rejected.equals(clientId())) {
            sp.edit().remove("client_id").putLong("client_id_time", 0L).commit();
        }
    }

    public String cookieHeader() {
        return secure == null ? "" : secure.getString("cookie_header", "");
    }

    public boolean saveCookieHeader(String cookie) {
        if (secure == null) {
            return false;
        }
        return secure.edit().putString("cookie_header", cookie == null ? "" : cookie).commit();
    }

    public boolean isLoggedIn() {
        String cookie = cookieHeader();
        return !TextUtils.isEmpty(cookie) && cookie.matches("(?s).*\\boauth_token=[^;\\s]+.*");
    }

    public String language() {
        String value = sp.getString("language", "fa");
        return "en".equals(value) ? "en" : "fa";
    }

    public void setLanguage(String lang) {
        sp.edit().putString("language", "en".equals(lang) ? "en" : "fa").apply();
    }

    public boolean allowRoaming() {
        return sp.getBoolean("allow_roaming", false);
    }

    public void setAllowRoaming(boolean value) {
        sp.edit().putBoolean("allow_roaming", value).apply();
    }

    public synchronized List<Track> favorites() {
        List<Track> out = new ArrayList<>();
        String raw = secure != null && secure.getBoolean("favorites_migrated", false)
                ? secure.getString("favorites", "[]") : sp.getString("favorites", "[]");
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                Track track = Track.fromJson(arr.optJSONObject(i));
                if (track != null && track.id != 0) {
                    out.add(track);
                }
            }
        } catch (Exception error) {
            ScLog.e("cannot read favorites", error);
        }
        return out;
    }

    public synchronized void saveFavorites(List<Track> tracks) {
        if (secure == null) {
            throw new IllegalStateException("secure storage unavailable");
        }
        JSONArray arr = new JSONArray();
        for (Track track : tracks) {
            arr.put(track.toJson());
        }
        boolean saved = secure.edit().putString("favorites", arr.toString())
                .putBoolean("favorites_migrated", true).commit();
        if (!saved) {
            throw new IllegalStateException("favorites commit failed");
        }
        sp.edit().remove("favorites").commit();
    }

    public boolean isFavorite(long id) {
        for (Track track : favorites()) {
            if (track.id == id) {
                return true;
            }
        }
        return false;
    }

    public synchronized boolean toggleFavorite(Track track) {
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

    public String lastQuery() {
        return sp.getString("last_query", "");
    }

    public void saveLastQuery(String query) {
        sp.edit().putString("last_query", query == null ? "" : query).apply();
    }

    public int lastGenre() {
        return sp.getInt("last_genre", 0);
    }

    public void saveLastGenre(int index) {
        sp.edit().putInt("last_genre", index).apply();
    }

    public synchronized void addDownload(long id, String name, String title, String artist) {
        try {
            JSONArray arr = downloads();
            JSONObject item = new JSONObject();
            item.put("id", id);
            item.put("name", name);
            item.put("title", title);
            item.put("artist", artist);
            item.put("time", System.currentTimeMillis());
            arr.put(item);
            sp.edit().putString("downloads", arr.toString()).apply();
        } catch (Exception error) {
            ScLog.e("cannot save download metadata", error);
        }
    }

    /** Replace the staging record atomically with respect to other app threads. */
    public synchronized void putDownload(JSONObject item) {
        try {
            JSONArray input = downloads();
            JSONArray output = new JSONArray();
            long id = item.optLong("id");
            for (int i = 0; i < input.length(); i++) {
                JSONObject old = input.optJSONObject(i);
                if (old != null && old.optLong("id") != id) {
                    output.put(old);
                }
            }
            output.put(item);
            sp.edit().putString("downloads", output.toString()).commit();
        } catch (Exception error) {
            ScLog.e("cannot update download metadata", error);
        }
    }

    public synchronized void removeDownload(long id) {
        JSONArray input = downloads();
        JSONArray output = new JSONArray();
        for (int i = 0; i < input.length(); i++) {
            JSONObject item = input.optJSONObject(i);
            if (item != null && item.optLong("id") != id) {
                output.put(item);
            }
        }
        sp.edit().putString("downloads", output.toString()).apply();
    }

    public JSONArray downloads() {
        try {
            return new JSONArray(sp.getString("downloads", "[]"));
        } catch (Exception error) {
            ScLog.e("cannot read download history", error);
            return new JSONArray();
        }
    }
}
