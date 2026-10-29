package com.soundcloudx.app;

import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Publishes a verified, completed download; removes all partial MediaStore entries. */
public class DownloadCompletionReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !DownloadManager.ACTION_DOWNLOAD_COMPLETE.equals(intent.getAction())) {
            return;
        }
        long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
        if (id < 0) {
            return;
        }
        Context app = context.getApplicationContext();
        PendingResult pending = goAsync();
        Bg.run(new Bg.Job<Boolean>() {
            @Override
            public Boolean run() {
                return finish(app, id);
            }
        }, new Bg.Then<Boolean>() {
            @Override
            public void done(Boolean value, Exception error) {
                if (error != null) {
                    ScLog.e("download completion failed id=" + id, error);
                }
                pending.finish();
            }
        });
    }

    public static synchronized boolean finish(Context ctx, long id) {
        Prefs prefs = Prefs.get(ctx);
        JSONArray items = prefs.downloads();
        JSONObject record = null;
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item != null && item.optLong("id") == id) {
                record = item;
                break;
            }
        }
        if (record == null || !"running".equals(record.optString("status"))) {
            return false;
        }
        File stage = Downloader.stagingFile(ctx, record.optString("stage"));
        DownloadManager manager = (DownloadManager) ctx.getSystemService(Context.DOWNLOAD_SERVICE);
        Uri published = null;
        File legacyTarget = null;
        boolean success = false;
        try {
            if (manager == null) {
                throw new IllegalStateException("DownloadManager unavailable");
            }
            long bytes;
            try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(id))) {
                if (cursor == null || !cursor.moveToFirst()) {
                    throw new IllegalStateException("download record missing");
                }
                int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                bytes = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR));
                long total = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES));
                if (status != DownloadManager.STATUS_SUCCESSFUL || bytes <= 0 || (total > 0 && total != bytes)) {
                    throw new IllegalStateException("download did not complete successfully");
                }
            }
            if (!stage.isFile() || stage.length() != bytes) {
                throw new IllegalStateException("staged download is incomplete");
            }
            String mime = record.optString("mime", "application/octet-stream");
            String name = record.optString("name", "track.bin");
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_MUSIC + "/" + Downloader.FOLDER);
                values.put(MediaStore.MediaColumns.IS_PENDING, 1);
                published = ctx.getContentResolver().insert(
                        MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values);
                if (published == null) {
                    throw new IllegalStateException("MediaStore insert failed");
                }
                long copied = 0;
                try (InputStream input = new FileInputStream(stage);
                     OutputStream output = ctx.getContentResolver().openOutputStream(published)) {
                    if (output == null) {
                        throw new IllegalStateException("MediaStore output unavailable");
                    }
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        output.write(buffer, 0, count);
                        copied += count;
                    }
                }
                if (copied != bytes) {
                    throw new IllegalStateException("MediaStore copy incomplete");
                }
                ContentValues complete = new ContentValues();
                complete.put(MediaStore.MediaColumns.IS_PENDING, 0);
                ctx.getContentResolver().update(published, complete, null, null);
                record.put("uri", published.toString());
            } else {
                File folder = new File(Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_MUSIC), Downloader.FOLDER);
                if (!folder.exists() && !folder.mkdirs()) {
                    throw new IllegalStateException("cannot create public music directory");
                }
                legacyTarget = new File(folder, name);
                int suffix = 1;
                while (legacyTarget.exists()) {
                    String base = name.contains(".") ? name.substring(0, name.lastIndexOf('.')) : name;
                    String ext = name.contains(".") ? name.substring(name.lastIndexOf('.')) : "";
                    legacyTarget = new File(folder, base + " (" + suffix++ + ")" + ext);
                }
                try (InputStream input = new FileInputStream(stage);
                     FileOutputStream output = new FileOutputStream(legacyTarget)) {
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        output.write(buffer, 0, count);
                    }
                    output.getFD().sync();
                }
                if (legacyTarget.length() != bytes) {
                    throw new IllegalStateException("public download copy incomplete");
                }
                final File scan = legacyTarget;
                MediaScannerConnection.scanFile(ctx, new String[]{scan.getAbsolutePath()},
                        new String[]{mime}, null);
                record.put("uri", Uri.fromFile(legacyTarget).toString());
                record.put("name", legacyTarget.getName());
            }
            record.put("status", "done").put("size", bytes);
            success = true;
        } catch (Exception error) {
            ScLog.e("cannot publish download id=" + id, error);
            if (published != null) {
                try {
                    ctx.getContentResolver().delete(published, null, null);
                } catch (Exception cleanup) {
                    ScLog.e("cannot remove failed MediaStore entry", cleanup);
                }
            }
            if (legacyTarget != null && legacyTarget.exists() && !legacyTarget.delete()) {
                ScLog.e("cannot remove failed public download");
            }
            try {
                record.put("status", "failed");
            } catch (Exception metadataError) {
                ScLog.e("cannot mark download failed", metadataError);
            }
        } finally {
            if (stage.exists() && !stage.delete()) {
                ScLog.e("cannot remove staging file id=" + id);
            }
            prefs.putDownload(record);
            Intent changed = new Intent(Downloader.ACTION_CHANGED).setPackage(ctx.getPackageName());
            changed.putExtra(Downloader.EXTRA_SUCCESS, success);
            changed.putExtra(Downloader.EXTRA_DOWNLOAD_ID, id);
            ctx.sendBroadcast(changed);
        }
        return success;
    }
}
