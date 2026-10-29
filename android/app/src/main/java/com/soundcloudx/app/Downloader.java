package com.soundcloudx.app;

import android.app.DownloadManager;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.text.TextUtils;
import android.webkit.MimeTypeMap;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.Locale;
import java.util.UUID;

/** System downloads stage in app storage; MediaStore is created only on success. */
public final class Downloader {
    public static final String FOLDER = "SoundCloudX";
    public static final String ACTION_CHANGED = "com.soundcloudx.app.DOWNLOAD_CHANGED";
    public static final String EXTRA_SUCCESS = "success";
    public static final String EXTRA_DOWNLOAD_ID = "download_id";

    private Downloader() { }

    public static class Result {
        public long downloadId;
        public String fileName;
        public boolean duplicate;
    }

    public static String mimeFor(String extension) {
        String ext = (extension == null ? "" : extension).replaceFirst("^\\.", "").toLowerCase(Locale.US);
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
        if (!TextUtils.isEmpty(mime)) {
            return mime;
        }
        switch (ext) {
            case "m3u8": return "application/vnd.apple.mpegurl";
            case "m3u": return "audio/x-mpegurl";
            case "opus": return "audio/ogg";
            case "flac": return "audio/flac";
            case "mp3": return "audio/mpeg";
            case "m4a": return "audio/mp4";
            default: return "application/octet-stream";
        }
    }

    public static synchronized Result enqueue(Context ctx, Track track, String url, boolean original)
            throws IOException {
        Context app = ctx.getApplicationContext();
        if (TextUtils.isEmpty(url)) {
            throw new IOException("empty url");
        }
        String extension = ScApi.extensionOf(url, original);
        if (extension.startsWith(".m3u")) {
            throw new IOException("a playlist is not a downloadable audio file");
        }
        Prefs prefs = Prefs.get(app);
        JSONArray history = prefs.downloads();
        DownloadManager manager = (DownloadManager) app.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            throw new IOException("DownloadManager unavailable");
        }
        for (int i = 0; i < history.length(); i++) {
            JSONObject old = history.optJSONObject(i);
            if (old == null || old.optLong("track_id") != track.id) {
                continue;
            }
            String status = old.optString("status", "running");
            long id = old.optLong("id");
            if ("done".equals(status) || "failed".equals(status)) {
                if ("done".equals(status)) {
                    Result result = new Result();
                    result.downloadId = id;
                    result.fileName = old.optString("name");
                    result.duplicate = true;
                    return result;
                }
                continue;
            }
            int state = queryStatus(manager, id);
            if (state == DownloadManager.STATUS_FAILED) {
                DownloadCompletionReceiver.finish(app, id);
                continue;
            }
            if (state == DownloadManager.STATUS_SUCCESSFUL) {
                DownloadCompletionReceiver.finish(app, id);
            }
            Result result = new Result();
            result.downloadId = id;
            result.fileName = old.optString("name");
            result.duplicate = true;
            return result;
        }
        File staging = new File(app.getExternalFilesDir(Environment.DIRECTORY_MUSIC), "staging");
        if (!staging.exists() && !staging.mkdirs()) {
            throw new IOException("cannot create download staging directory");
        }
        String stageName = UUID.randomUUID().toString() + extension;
        String name = Fmt.safeFileName(track.fileName(extension));
        String mime = mimeFor(extension);
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        request.setTitle(track.title).setDescription(track.artist).setMimeType(mime);
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE);
        request.setAllowedOverMetered(true);
        request.setAllowedOverRoaming(prefs.allowRoaming());
        request.addRequestHeader("User-Agent", ScApi.UA);
        request.addRequestHeader("Accept-Encoding", "identity");
        request.setDestinationUri(Uri.fromFile(new File(staging, stageName)));
        long id = manager.enqueue(request);
        try {
            JSONObject record = new JSONObject();
            record.put("id", id).put("track_id", track.id).put("name", name)
                    .put("title", track.title).put("artist", track.artist)
                    .put("mime", mime).put("stage", stageName).put("status", "running")
                    .put("time", System.currentTimeMillis());
            prefs.putDownload(record);
        } catch (Exception error) {
            manager.remove(id);
            prefs.removeDownload(id);
            throw new IOException("cannot record download", error);
        }
        Result result = new Result();
        result.downloadId = id;
        result.fileName = name;
        ScLog.d("download queued id=" + id + " mime=" + mime);
        return result;
    }

    public static int queryStatus(DownloadManager manager, long id) {
        try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(id))) {
            if (cursor != null && cursor.moveToFirst()) {
                return cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
            }
        } catch (Exception error) {
            ScLog.e("cannot query download id=" + id, error);
        }
        return -1;
    }

    /** Reconcile completions missed while the process was stopped. */
    public static void reconcile(Context ctx) {
        Context app = ctx.getApplicationContext();
        DownloadManager manager = (DownloadManager) app.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            return;
        }
        JSONArray items = Prefs.get(app).downloads();
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item != null && "running".equals(item.optString("status"))) {
                int state = queryStatus(manager, item.optLong("id"));
                if (state == DownloadManager.STATUS_SUCCESSFUL || state == DownloadManager.STATUS_FAILED) {
                    DownloadCompletionReceiver.finish(app, item.optLong("id"));
                }
            }
        }
    }

    public static File stagingFile(Context ctx, String name) {
        return new File(new File(ctx.getExternalFilesDir(Environment.DIRECTORY_MUSIC), "staging"), name);
    }

    public static String folderPath() {
        return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC)
                .getAbsolutePath() + "/" + FOLDER;
    }
}
