package com.soundcloudx.app;

import org.junit.Test;
import java.io.IOException;
import static org.junit.Assert.*;

public class HlsPlaylistTest {
    private static final String URL = "https://cdn.example/audio/list.m3u8?token=x";
    @Test public void relativeSegments() throws Exception {
        HlsPlaylist p = HlsPlaylist.parse("#EXTM3U\n#EXTINF:1,\na.mp3\n../b.mp3\n#EXT-X-ENDLIST", URL);
        assertEquals(2, p.segments.size());
        assertEquals("https://cdn.example/audio/a.mp3", p.segments.get(0).url);
        assertEquals("https://cdn.example/b.mp3", p.segments.get(1).url);
    }
    @Test public void byteRanges() throws Exception {
        HlsPlaylist p = HlsPlaylist.parse("#EXTM3U\n#EXT-X-BYTERANGE:10@0\na.mp3\n#EXT-X-BYTERANGE:20\na.mp3\n#EXT-X-ENDLIST", URL);
        assertEquals(0, p.segments.get(0).offset);
        assertEquals(10, p.segments.get(1).offset);
        assertEquals(20, p.segments.get(1).length);
    }
    @Test public void masterSelectsVariant() throws Exception {
        HlsPlaylist p = HlsPlaylist.parse("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=64000\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=128000\nhigh.m3u8", URL);
        assertEquals("https://cdn.example/audio/high.m3u8", p.child);
    }
    @Test public void bomAndNoEncryption() throws Exception {
        assertEquals(1, HlsPlaylist.parse("\uFEFF#EXTM3U\n#EXT-X-KEY:METHOD=NONE\na.mp3\n#EXT-X-ENDLIST", URL).segments.size());
    }
    @Test(expected=IOException.class) public void encryptedRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\na.mp3\n#EXT-X-ENDLIST", URL);
    }
    @Test(expected=IOException.class) public void liveRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\na.mp3", URL);
    }
    @Test(expected=IOException.class) public void fmp4Rejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\na.m4a\n#EXT-X-ENDLIST", URL);
    }
    @Test(expected=IOException.class) public void unsafeUrlRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\nfile:///etc/passwd\n#EXT-X-ENDLIST", URL);
    }
    @Test(expected=IOException.class) public void firstImplicitRangeRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\n#EXT-X-BYTERANGE:5\na.mp3\n#EXT-X-ENDLIST", URL);
    }
    @Test(expected=IOException.class) public void htmlRejected() throws Exception {
        HlsPlaylist.parse("<html>not audio</html>", URL);
    }
    @Test(expected=IOException.class) public void malformedRangeRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\n#EXT-X-BYTERANGE:0@0\na.mp3\n#EXT-X-ENDLIST", URL);
    }
    @Test(expected=IOException.class) public void danglingRangeRejected() throws Exception {
        HlsPlaylist.parse("#EXTM3U\na.mp3\n#EXT-X-BYTERANGE:5@0\n#EXT-X-ENDLIST", URL);
    }
}
