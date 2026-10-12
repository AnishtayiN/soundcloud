package com.soundcloudx.app;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;

/** Writes real audio, never an m3u8/HTML/JSON error page renamed to .mp3. */
public final class AudioTransfer {
    public interface Cancel { boolean cancelled(); }
    public interface Progress { void update(long done, long total); }
    private static final int MAX_PLAYLIST = 1024 * 1024;
    private long done;

    private static void check(Cancel cancel) throws IOException {
        if (Thread.currentThread().isInterrupted() || cancel.cancelled()) {
            throw new InterruptedIOException("download cancelled");
        }
    }

    private static HttpURLConnection open(String url, long offset, long length, Cancel cancel)
            throws IOException {
        for (int redirect = 0; redirect < 6; redirect++) {
            check(cancel);
            URL target = new URL(HlsPlaylist.resolve(url, url));
            HttpURLConnection c = (HttpURLConnection) target.openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(15000);
            c.setReadTimeout(25000);
            c.setRequestProperty("User-Agent", ScApi.UA);
            c.setRequestProperty("Accept-Encoding", "identity");
            if (length >= 0) c.setRequestProperty("Range", "bytes=" + offset + "-" + (offset + length - 1));
            try {
                int status = c.getResponseCode();
                if (status >= 300 && status < 400) {
                    String location = c.getHeaderField("Location");
                    if (location == null) throw new IOException("redirect without destination");
                    url = HlsPlaylist.resolve(url, location);
                    c.disconnect();
                    continue;
                }
                if (status != 200 && status != 206) throw new IOException("HTTP " + status);
                if (length >= 0 && status != 206) throw new IOException("server ignored HLS byte range");
                return c;
            } catch (IOException error) {
                c.disconnect();
                throw error;
            }
        }
        throw new IOException("too many media redirects");
    }

    private static byte[] prefix(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        while (out.size() < 12) {
            int value = in.read();
            if (value < 0) break;
            out.write(value);
        }
        return out.toByteArray();
    }

    private static boolean starts(byte[] bytes, String value) {
        byte[] pattern = value.getBytes(StandardCharsets.US_ASCII);
        if (bytes.length < pattern.length) return false;
        for (int i = 0; i < pattern.length; i++) if (bytes[i] != pattern[i]) return false;
        return true;
    }

    private static boolean isMp3(byte[] p) {
        return starts(p, "ID3") || p.length > 1 && (p[0] & 255) == 255 &&
                (p[1] & 0xe0) == 0xe0 && (p[1] & 6) != 0 && (p[1] & 0x18) != 8;
    }

    private static boolean isAudio(byte[] p) {
        return isMp3(p) || starts(p, "RIFF") || starts(p, "fLaC") || starts(p, "OggS") ||
                starts(p, "FORM") || p.length >= 12 && p[4] == 'f' && p[5] == 't' &&
                p[6] == 'y' && p[7] == 'p';
    }

    private static String playlist(InputStream in, byte[] prefix, Cancel cancel) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(prefix);
        byte[] buffer = new byte[8192];
        int count;
        while ((count = in.read(buffer)) >= 0) {
            check(cancel);
            out.write(buffer, 0, count);
            if (out.size() > MAX_PLAYLIST) throw new IOException("playlist too large");
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

    private static List<HlsPlaylist.Segment> segments(String url, String text, Cancel cancel, int depth)
            throws IOException {
        if (depth > 3) throw new IOException("too many nested HLS playlists");
        HlsPlaylist parsed = HlsPlaylist.parse(text, url);
        if (parsed.child == null) return parsed.segments;
        HttpURLConnection c = open(parsed.child, -1, -1, cancel);
        try (InputStream in = new BufferedInputStream(c.getInputStream())) {
            return segments(parsed.child, playlist(in, new byte[0], cancel), cancel, depth + 1);
        } finally { c.disconnect(); }
    }

    private void copy(InputStream in, byte[] p, OutputStream out, long expected, long total,
                      Cancel cancel, Progress progress) throws IOException {
        check(cancel);
        out.write(p);
        long count = p.length;
        done += p.length;
        byte[] buffer = new byte[64 * 1024];
        int n;
        while ((n = in.read(buffer)) >= 0) {
            check(cancel);
            out.write(buffer, 0, n);
            count += n;
            done += n;
            progress.update(done, total);
        }
        if (count == 0 || expected >= 0 && count != expected) throw new IOException("incomplete audio download");
        progress.update(done, total);
    }

    public long fetch(String url, OutputStream out, boolean original, Cancel cancel, Progress progress)
            throws IOException {
        done = 0;
        HttpURLConnection c = open(url, -1, -1, cancel);
        String text = null;
        try (InputStream in = new BufferedInputStream(c.getInputStream())) {
            byte[] p = prefix(in);
            String start = new String(p, StandardCharsets.UTF_8).replace("\uFEFF", "").trim();
            if (start.startsWith("#EXTM3U")) {
                text = playlist(in, p, cancel);
            } else {
                String type = c.getContentType();
                if ((type != null && (type.startsWith("text/") || type.contains("json"))) ||
                        !(original ? isAudio(p) : isMp3(p))) throw new IOException("server did not send audio");
                long total = c.getContentLengthLong();
                copy(in, p, out, total, Math.max(0, total), cancel, progress);
            }
        } finally { c.disconnect(); }
        if (text != null) {
            List<HlsPlaylist.Segment> parts = segments(url, text, cancel, 0);
            long total = 0;
            for (HlsPlaylist.Segment s : parts) {
                if (s.length < 0) { total = 0; break; }
                total += s.length;
            }
            for (HlsPlaylist.Segment s : parts) {
                c = open(s.url, s.offset, s.length, cancel);
                try (InputStream in = new BufferedInputStream(c.getInputStream())) {
                    byte[] p = prefix(in);
                    if (!isMp3(p)) throw new IOException("HLS segment is not MP3");
                    long expected = s.length >= 0 ? s.length : c.getContentLengthLong();
                    copy(in, p, out, expected, total, cancel, progress);
                } finally { c.disconnect(); }
            }
        }
        check(cancel);
        out.flush();
        progress.update(done, done);
        return done;
    }
}
