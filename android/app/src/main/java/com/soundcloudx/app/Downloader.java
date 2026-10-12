package com.soundcloudx.app;

import android.app.DownloadManager;
import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.TextUtils;

import java.io.File;
import java.io.IOException;

/**
 * Hands the direct CDN url to the system DownloadManager, which takes care of
 * the progress notification, retries and writing the file into
 * {@code /sdcard/Music/SoundCloudX} (Android 10+ through MediaStore).
 */
public final class Downloader {

    public static final String FOLDER = "SoundCloudX";

    private Downloader() {
    }

    public static class Result {
        public long downloadId;
        public String fileName;
    }

    public static Result enqueue(Context ctx, Track track, String url, boolean original)
            throws IOException {
        if (TextUtils.isEmpty(url)) {
            throw new IOException("empty url");
        }
        DownloadManager dm = (DownloadManager) ctx.getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) {
            throw new IOException("DownloadManager unavailable");
        }
        String ext = ScApi.extensionOf(url, original);
        String name = Fmt.safeFileName(track.fileName(ext));

        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        request.setTitle(track.title);
        request.setDescription(track.artist);
        request.setMimeType("audio/mpeg");
        request.setNotificationVisibility(
                DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setAllowedOverMetered(true);
        request.setAllowedOverRoaming(true);
        request.addRequestHeader("User-Agent", ScApi.UA);
        String cookie = ScApi.cookieHeader(ctx);
        if (!TextUtils.isEmpty(cookie)) {
            request.addRequestHeader("Cookie", cookie);
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
            values.put(MediaStore.MediaColumns.MIME_TYPE, "audio/mpeg");
            values.put(MediaStore.MediaColumns.RELATIVE_PATH,
                    Environment.DIRECTORY_MUSIC + "/" + FOLDER);
            Uri target = ctx.getContentResolver().insert(
                    MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY),
                    values);
            if (target == null) {
                throw new IOException("MediaStore refused the destination");
            }
            request.setDestinationUri(target);
        } else {
            File dir = new File(
                    Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC),
                    FOLDER);
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IOException("cannot create " + dir.getAbsolutePath());
            }
            request.setDestinationUri(Uri.fromFile(new File(dir, name)));
        }

        Result result = new Result();
        result.fileName = name;
        result.downloadId = dm.enqueue(request);
        Prefs.get(ctx).addDownload(result.downloadId, name, track.title, track.artist);
        ScLog.d("download queued id=" + result.downloadId + " file=" + name);
        return result;
    }

    /** Human readable path of the destination folder. */
    public static String folderPath() {
        return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC)
                .getAbsolutePath() + "/" + FOLDER;
    }
}
