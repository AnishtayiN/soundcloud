package com.soundcloudx.app;

import java.io.IOException;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Unencrypted MP3 HLS VOD parser. Kept independent of Android for unit tests. */
public final class HlsPlaylist {
    public static final class Segment {
        public final String url;
        public final long offset, length;
        Segment(String url, long offset, long length) {
            this.url = url; this.offset = offset; this.length = length;
        }
    }
    public final List<Segment> segments = new ArrayList<>();
    public String child;

    public static String resolve(String base, String value) throws IOException {
        try {
            URI uri = new URI(base).resolve(value.trim());
            if (!"https".equals(uri.getScheme()) || uri.getHost() == null) {
                throw new IOException("media URL must use HTTPS");
            }
            return uri.toString();
        } catch (IllegalArgumentException | java.net.URISyntaxException e) {
            throw new IOException("invalid media URL", e);
        }
    }

    public static HlsPlaylist parse(String text, String url) throws IOException {
        String[] lines = text.replace("\uFEFF", "").trim().split("\\r?\\n");
        if (lines.length == 0 || !"#EXTM3U".equals(lines[0].trim())) {
            throw new IOException("invalid HLS playlist");
        }
        HlsPlaylist result = new HlsPlaylist();
        long bandwidth = -1, best = -1, length = -1, offset = -1, previousEnd = 0;
        String previousUrl = null;
        boolean end = false;
        for (int i = 1; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.isEmpty()) continue;
            if (line.startsWith("#EXT-X-KEY:") && !line.substring(11).matches(".*(?:^|,)METHOD=NONE(?:,.*|$)")) {
                throw new IOException("encrypted media is not supported");
            }
            if (line.startsWith("#EXT-X-MAP:")) throw new IOException("HLS format is not MP3");
            if ("#EXT-X-ENDLIST".equals(line)) end = true;
            if (line.startsWith("#EXT-X-STREAM-INF:")) {
                Matcher m = Pattern.compile("(?:^|,)BANDWIDTH=(\\d+)").matcher(line.substring(18));
                try { bandwidth = m.find() ? Long.parseLong(m.group(1)) : 0; }
                catch (NumberFormatException e) { throw new IOException("invalid bandwidth", e); }
            } else if (line.startsWith("#EXT-X-BYTERANGE:")) {
                Matcher m = Pattern.compile("(\\d+)(?:@(\\d+))?").matcher(line.substring(17));
                if (!m.matches()) throw new IOException("invalid HLS byte range");
                try {
                    length = Long.parseLong(m.group(1));
                    offset = m.group(2) == null ? -1 : Long.parseLong(m.group(2));
                    if (length <= 0 || offset > Long.MAX_VALUE - length) throw new IOException("invalid range");
                } catch (NumberFormatException e) { throw new IOException("invalid range", e); }
            } else if (!line.startsWith("#")) {
                String target = resolve(url, line);
                if (bandwidth >= 0) {
                    if (bandwidth > best) { best = bandwidth; result.child = target; }
                    bandwidth = -1;
                    continue;
                }
                if (length >= 0 && offset < 0) {
                    if (!target.equals(previousUrl)) throw new IOException("implicit range without resource");
                    offset = previousEnd;
                }
                if (length >= 0 && offset > Long.MAX_VALUE - length) throw new IOException("invalid range");
                result.segments.add(new Segment(target, offset, length));
                if (result.segments.size() > 10000) throw new IOException("playlist too large");
                previousUrl = target;
                previousEnd = length >= 0 ? offset + length : 0;
                offset = length = -1;
            }
        }
        if (bandwidth >= 0 || length >= 0) throw new IOException("incomplete playlist");
        if (result.child != null) {
            if (!result.segments.isEmpty()) throw new IOException("mixed HLS playlist");
        } else if (result.segments.isEmpty() || !end) {
            throw new IOException("only complete non-live HLS tracks can be downloaded");
        }
        return result;
    }
}
