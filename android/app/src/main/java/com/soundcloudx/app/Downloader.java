package com.soundcloudx.app;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Environment;
import android.text.TextUtils;
import android.webkit.MimeTypeMap;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicLong;

/** Starts an owned foreground download; HLS must not be handed to DownloadManager. */
public final class Downloader {
    public static final String FOLDER = "SoundCloudX";
    private static final AtomicLong NEXT_ID = new AtomicLong(System.currentTimeMillis());
    private Downloader() { }
    public static class Result {
        public long downloadId;
        public String fileName;
    }

    public static Result enqueue(Context ctx, Track track, String url, boolean original) throws IOException {
        if (track == null || track.id == 0) throw new IOException("missing track");
        Result result = new Result();
        result.downloadId = NEXT_ID.incrementAndGet();
        result.fileName = Fmt.safeFileName(track.fileName(ScApi.extensionOf(url, original)));
        Prefs.get(ctx).addDownload(result.downloadId, result.fileName, track.title, track.artist);
        Prefs.get(ctx).updateDownload(result.downloadId, "queued", "", "", 0, 0, "");
        Intent intent = new Intent(ctx, DownloadService.class);
        intent.putExtra("id", result.downloadId);
        intent.putExtra("track", track);
        intent.putExtra("url", url);
        intent.putExtra("original", original);
        try {
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(intent);
            else ctx.startService(intent);
        } catch (RuntimeException error) {
            Prefs.get(ctx).updateDownload(result.downloadId, "failed", "", "", 0, 0, "download service could not start");
            throw new IOException("download service could not start", error);
        }
        return result;
    }

    public static String mime(String extension) {
        String value = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension.replace(".", ""));
        return TextUtils.isEmpty(value) ? "audio/mpeg" : value;
    }

    public static String extensionFromHeader(byte[] p, String fallback) {
        if (p.length >= 4) {
            String magic = new String(p, 0, 4, java.nio.charset.StandardCharsets.US_ASCII);
            if ("RIFF".equals(magic)) return ".wav";
            if ("fLaC".equals(magic)) return ".flac";
            if ("OggS".equals(magic)) return ".ogg";
            if ("FORM".equals(magic)) return ".aiff";
        }
        if (p.length >= 8 && p[4] == 'f' && p[5] == 't' && p[6] == 'y' && p[7] == 'p') return ".m4a";
        return fallback;
    }

    public static String folderPath() {
        return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC)
                .getAbsolutePath() + "/" + FOLDER;
    }
}
