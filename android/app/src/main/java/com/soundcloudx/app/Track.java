package com.soundcloudx.app;

import android.text.TextUtils;

import org.json.JSONObject;

import java.io.Serializable;

/** One SoundCloud track. */
public class Track implements Serializable {

    private static final long serialVersionUID = 1L;

    public long id;
    public String title = "";
    public String artist = "";
    public int durationMs;
    public String artworkUrl = "";
    public String permalink = "";
    public String genre = "";
    public long plays;
    public boolean streamable = true;
    public boolean downloadable;
    public String policy = "ALLOW";
    public String trackAuth = "";
    public String downloadUrl = "";

    public static Track fromJson(JSONObject o) {
        if (o == null) {
            return null;
        }
        Track t = new Track();
        t.id = o.optLong("id");
        t.title = str(o.optString("title", ""));
        t.durationMs = o.optInt("duration", 0);
        t.permalink = str(o.optString("permalink_url", ""));
        t.genre = str(o.optString("genre", ""));
        t.plays = o.optLong("playback_count", 0);
        t.streamable = o.optBoolean("streamable", true);
        t.downloadable = o.optBoolean("downloadable", false);
        t.policy = str(o.optString("policy", "ALLOW"));
        t.trackAuth = str(o.optString("track_authorization", ""));
        t.downloadUrl = str(o.optString("download_url", ""));

        JSONObject user = o.optJSONObject("user");
        if (user != null) {
            t.artist = str(user.optString("username", ""));
        } else {
            t.artist = str(o.optString("artist", ""));
        }

        String art = str(o.optString("artwork_url", ""));
        if (TextUtils.isEmpty(art) && user != null) {
            art = str(user.optString("avatar_url", ""));
        }
        t.artworkUrl = art;
        return t;
    }

    public JSONObject toJson() {
        JSONObject o = new JSONObject();
        try {
            o.put("id", id);
            o.put("title", title);
            o.put("artist", artist);
            o.put("duration", durationMs);
            o.put("artwork_url", artworkUrl);
            o.put("permalink_url", permalink);
            o.put("genre", genre);
            o.put("playback_count", plays);
            o.put("streamable", streamable);
            o.put("downloadable", downloadable);
            o.put("policy", policy);
            o.put("track_authorization", trackAuth);
            o.put("download_url", downloadUrl);
        } catch (Exception error) {
            ScLog.e("cannot serialize track", error);
        }
        return o;
    }

    private static String str(String s) {
        return s == null || "null".equals(s) ? "" : s;
    }

    public String durationText() {
        return format(durationMs);
    }

    public static String format(int ms) {
        int total = Math.max(0, ms / 1000);
        int m = total / 60;
        int s = total % 60;
        if (m >= 60) {
            int h = m / 60;
            m = m % 60;
            return String.format("%d:%02d:%02d", h, m, s);
        }
        return String.format("%d:%02d", m, s);
    }

    /** 100x100 thumbnail. */
    public String thumbUrl() {
        return artworkUrl.replace("-large", "-t67x67");
    }

    /** Large cover for the player bar. */
    public String coverUrl() {
        return artworkUrl.replace("-large", "-t200x200");
    }

    public boolean isPrivate() {
        return "BLOCK".equals(policy) || !streamable;
    }

    public String fileName(String ext) {
        String base = (TextUtils.isEmpty(artist) ? "" : artist + " - ") + title;
        return base + ext;
    }

    @Override
    public String toString() {
        return TextUtils.isEmpty(artist) ? title : artist + " — " + title;
    }
}
