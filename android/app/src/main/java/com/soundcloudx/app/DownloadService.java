package com.soundcloudx.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.MediaStore;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Owned, cancellable foreground transfers with atomic publication in Music. */
public class DownloadService extends Service {
    private static final String CHANNEL = "soundcloudx_downloads";
    private static final int NOTIFICATION = 4212;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Map<Long, Job> jobs = new ConcurrentHashMap<>();
    private final Handler main = new Handler(Looper.getMainLooper());
    private NotificationManager notifications;

    private static final class Job implements AudioTransfer.Cancel {
        long id;
        Track track;
        String url;
        boolean original;
        volatile boolean cancelled;
        public boolean cancelled() { return cancelled; }
    }

    @Override public void onCreate() {
        super.onCreate();
        notifications = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            notifications.createNotificationChannel(new NotificationChannel(CHANNEL,
                    getString(R.string.download_channel), NotificationManager.IMPORTANCE_LOW));
        }
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) { stopSelf(); return START_NOT_STICKY; }
        long cancel = intent.getLongExtra("cancel", 0);
        if (cancel != 0) {
            Job job = jobs.get(cancel);
            if (job != null) job.cancelled = true;
            if (jobs.isEmpty()) stopSelf();
            return START_NOT_STICKY;
        }
        Object track = intent.getSerializableExtra("track");
        long id = intent.getLongExtra("id", 0);
        if (!(track instanceof Track) || id == 0 || jobs.containsKey(id)) {
            if (jobs.isEmpty()) stopSelf();
            return START_NOT_STICKY;
        }
        Job job = new Job();
        job.id = id; job.track = (Track) track;
        job.url = intent.getStringExtra("url"); job.original = intent.getBooleanExtra("original", false);
        jobs.put(id, job);
        try {
            startForeground(NOTIFICATION, notification(job, getString(R.string.download_preparing), 0, 0, true));
        } catch (RuntimeException error) {
            jobs.remove(id);
            Prefs.get(this).updateDownload(id, "failed", "", "", 0, 0, "foreground download refused");
            stopSelf();
            return START_NOT_STICKY;
        }
        executor.submit(() -> transfer(job));
        return START_NOT_STICKY;
    }

    private Notification notification(Job job, String text, long done, long total, boolean ongoing) {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent content = PendingIntent.getActivity(this, 42, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        builder.setSmallIcon(R.drawable.ic_download).setContentTitle(job.track.title)
                .setContentText(text).setContentIntent(content).setOnlyAlertOnce(true).setOngoing(ongoing);
        if (ongoing) {
            builder.setProgress(100, total > 0 ? (int) Math.min(100, 100.0 * done / total) : 0, total <= 0);
            Intent cancel = new Intent(this, DownloadService.class).putExtra("cancel", job.id);
            PendingIntent action = PendingIntent.getService(this, (int) job.id, cancel,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(new Notification.Action.Builder(
                    android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                    getString(R.string.download_cancel), action).build());
        }
        return builder.build();
    }

    private void transfer(Job job) {
        Uri uri = null;
        File partial = null;
        long size = 0;
        String error = "", state = "failed", mime = "audio/mpeg";
        PowerManager.WakeLock wake = null;
        try {
            if (job.cancelled) throw new java.io.InterruptedIOException("download cancelled");
            PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (power != null) {
                wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SoundCloudX:download");
                wake.acquire(60 * 60 * 1000L);
            }
            Prefs.get(this).updateDownload(job.id, "running", "", "", 0, 0, "");
            if (job.url == null) job.url = ScApi.downloadUrl(this, job.track, job.original);
            String extension = ScApi.extensionOf(job.url, job.original);
            String name = Fmt.safeFileName(job.track.fileName(extension));
            mime = Downloader.mime(extension);
            OutputStream stream;
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                values.put(MediaStore.MediaColumns.RELATIVE_PATH, "Music/" + Downloader.FOLDER);
                values.put(MediaStore.MediaColumns.IS_PENDING, 1);
                uri = getContentResolver().insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values);
                if (uri == null) throw new IOException("MediaStore refused the destination");
                stream = getContentResolver().openOutputStream(uri, "w");
            } else {
                File folder = new File(Downloader.folderPath());
                if (!folder.exists() && !folder.mkdirs()) throw new IOException("cannot create Music folder");
                partial = new File(folder, ".scx-" + job.id + ".part");
                stream = new FileOutputStream(partial);
            }
            if (stream == null) throw new IOException("cannot open download destination");
            final long[] last = {0};
            try (OutputStream out = stream) {
                size = new AudioTransfer().fetch(job.url, out, job.original, job, (done, total) -> {
                    long now = System.currentTimeMillis();
                    if (now - last[0] < 500 && done != total) return;
                    last[0] = now;
                    Prefs.get(this).updateDownload(job.id, "running", "", "", done, total, "");
                    notifications.notify(NOTIFICATION, notification(job, Fmt.bytes(done) +
                            (total > 0 ? " / " + Fmt.bytes(total) : ""), done, total, true));
                });
            }
            if (job.cancelled) throw new java.io.InterruptedIOException("download cancelled");
            if (job.original) {
                byte[] header = new byte[12];
                try (InputStream in = partial != null ? new FileInputStream(partial)
                        : getContentResolver().openInputStream(uri)) {
                    if (in == null) throw new IOException("cannot inspect original file");
                    int index = 0, value;
                    while (index < header.length && (value = in.read()) >= 0) header[index++] = (byte) value;
                }
                extension = Downloader.extensionFromHeader(header, extension);
                name = Fmt.safeFileName(job.track.fileName(extension));
                mime = Downloader.mime(extension);
            }
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues published = new ContentValues();
                published.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                published.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                published.put(MediaStore.MediaColumns.IS_PENDING, 0);
                if (getContentResolver().update(uri, published, null, null) < 1) throw new IOException("cannot publish audio");
            } else {
                File target = new File(Downloader.folderPath(), name);
                for (int i = 1; target.exists(); i++) {
                    target = new File(Downloader.folderPath(), name.substring(0, name.length() - extension.length())
                            + " (" + i + ")" + extension);
                }
                if (!partial.renameTo(target)) throw new IOException("cannot publish audio");
                partial = null;
                uri = FileProvider.getUriForFile(this, getPackageName() + ".files", target);
                android.media.MediaScannerConnection.scanFile(this, new String[]{target.getAbsolutePath()},
                        new String[]{mime}, null);
            }
            state = "done";
        } catch (Exception failure) {
            state = job.cancelled || Thread.currentThread().isInterrupted() ? "cancelled" : "failed";
            error = failure.getMessage() == null ? failure.getClass().getSimpleName() : failure.getMessage();
            // Do not put URLs, access tokens, cookies or stack traces in notifications.
            if (error.contains("http") || error.contains("oauth")) error = "network transfer failed";
            if (uri != null && Build.VERSION.SDK_INT >= 29) {
                try { getContentResolver().delete(uri, null, null); } catch (RuntimeException ignored) { }
            }
            uri = null;
        } finally {
            if (partial != null) partial.delete();
            if (wake != null && wake.isHeld()) wake.release();
        }
        Prefs.get(this).updateDownload(job.id, state, uri == null ? "" : uri.toString(), mime, size, size, error);
        final String finished = state, detail = error;
        main.post(() -> {
            jobs.remove(job.id);
            if (jobs.isEmpty()) {
                stopForeground(true);
                int label = "done".equals(finished) ? R.string.download_complete
                        : "cancelled".equals(finished) ? R.string.download_cancelled : R.string.download_failed;
                notifications.notify(NOTIFICATION, notification(job, getString(label) +
                        (detail.isEmpty() ? "" : ": " + detail), 0, 0, false));
                stopSelf();
            }
        });
    }

    @Override public void onDestroy() {
        for (Job job : jobs.values()) job.cancelled = true;
        executor.shutdownNow();
        super.onDestroy();
    }
}
