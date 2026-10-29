package com.soundcloudx.app;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;

/** Download permission and background URL-resolution workflow. */
final class DownloadCoordinator {
    private static final int REQ_STORAGE = 102;
    private final MainActivity activity;
    private Track pending;
    private boolean original;

    DownloadCoordinator(MainActivity activity) {
        this.activity = activity;
    }

    void start(Track track, boolean originalQuality) {
        if (originalQuality && !activity.prefs.isLoggedIn()) {
            activity.toast(R.string.toast_need_login);
            return;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && activity.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pending = track;
            original = originalQuality;
            activity.requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            return;
        }
        Bg.run(new Bg.Job<Downloader.Result>() {
            @Override
            public Downloader.Result run() throws Exception {
                String url = ScApi.downloadUrl(activity, track, originalQuality);
                return Downloader.enqueue(activity, track, url, originalQuality);
            }
        }, new Bg.Then<Downloader.Result>() {
            @Override
            public void done(Downloader.Result result, Exception error) {
                if (error != null) {
                    ScLog.e("download failed", error);
                    activity.toast(activity.getString(R.string.toast_download_failed,
                            activity.getString(R.string.error_media)));
                } else if (result.duplicate) {
                    activity.toast(R.string.toast_download_duplicate);
                } else {
                    activity.toast(R.string.toast_download_started);
                }
            }
        });
    }

    void onPermissionResult(int code, int[] granted) {
        if (code != REQ_STORAGE) {
            return;
        }
        Track track = pending;
        boolean quality = original;
        pending = null;
        if (granted.length > 0 && granted[0] == PackageManager.PERMISSION_GRANTED) {
            if (track != null) {
                start(track, quality);
            }
        } else {
            activity.toast(R.string.toast_need_permission);
        }
    }
}
