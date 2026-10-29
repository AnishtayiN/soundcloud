package com.soundcloudx.app;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class TrackTest {
    @Test public void signedMetadataAndArtistSurviveRoundTrip() throws Exception {
        Track track = new Track();
        track.id = 123;
        track.title = "آهنگ";
        track.artist = "خواننده";
        track.trackAuth = "signed-authorization";
        track.downloadUrl = "https://api.soundcloud.com/tracks/123/download";
        track.streamable = false;
        Track copy = Track.fromJson(new JSONObject(track.toJson().toString()));
        assertNotNull(copy);
        assertEquals(track.id, copy.id);
        assertEquals(track.title, copy.title);
        assertEquals(track.artist, copy.artist);
        assertEquals(track.trackAuth, copy.trackAuth);
        assertEquals(track.downloadUrl, copy.downloadUrl);
        assertFalse(copy.streamable);
    }

    @Test public void diagnosticsNeverContainSessionOrSignedQuery() {
        String secret = "super-secret-value";
        String clean = ScLog.safe("GET https://api.soundcloud.com/tracks/1?oauth_token=" + secret
                + "&client_id=public Cookie: oauth_token=" + secret);
        assertFalse(clean.contains(secret));
        assertEquals("https://api.soundcloud.com/tracks/1",
                ScLog.safeUrl("https://api.soundcloud.com/tracks/1?oauth_token=" + secret));
    }
}
