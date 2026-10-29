package com.soundcloudx.app;

import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.text.TextUtils;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.PopupMenu;
import android.widget.TextView;

import com.soundcloudx.app.receiver.MediaBtnReceiver;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;

/** Existing menus and dialogs, isolated from activity lifecycle and search code. */
final class AppDialogs {
    private final MainActivity activity;
    private final TextView account;

    AppDialogs(MainActivity activity) {
        this.activity = activity;
        account = (TextView) activity.findViewById(R.id.txtAccount);
    }

    void setupMenu() {
        activity.findViewById(R.id.btnMenu).setOnClickListener(view -> {
            PopupMenu popup = new PopupMenu(activity, view);
            popup.getMenu().add(0, 1, 0, activity.prefs.isLoggedIn() ? R.string.menu_logout : R.string.menu_login);
            popup.getMenu().add(0, 2, 1, R.string.menu_downloads);
            popup.getMenu().add(0, 7, 2, R.string.menu_settings);
            popup.getMenu().add(0, 3, 3, R.string.menu_reload_api);
            popup.getMenu().add(0, 4, 4, R.string.menu_clear_cache);
            popup.getMenu().add(0, 5, 5, R.string.menu_view_log);
            popup.getMenu().add(0, 6, 6, R.string.dlg_about_title);
            popup.setOnMenuItemClickListener(item -> {
                switch (item.getItemId()) {
                    case 1:
                        if (activity.prefs.isLoggedIn()) {
                            signOut();
                        } else {
                            activity.startActivityForResult(new Intent(activity, LoginActivity.class), MainActivity.REQ_LOGIN);
                        }
                        return true;
                    case 2: showDownloads(); return true;
                    case 7: showSettings(); return true;
                    case 3: ScApi.clearClientId(activity); activity.toast(R.string.toast_client_id_reloaded); return true;
                    case 4: clearCaches(); return true;
                    case 5: showLog(); return true;
                    case 6: showAbout(); return true;
                    default: return false;
                }
            });
            popup.show();
        });
    }

    void showDownloadMenu(Track track) {
        new AlertDialog.Builder(activity).setTitle(track.title)
                .setItems(new CharSequence[]{activity.getString(R.string.action_download_128),
                                activity.getString(R.string.action_download_original)},
                        (dialog, which) -> activity.downloads.start(track, which == 1))
                .setNegativeButton(R.string.dlg_close, null).show();
    }

    void showTrackMenu(Track track, int position, View anchor) {
        PopupMenu popup = new PopupMenu(activity, anchor);
        popup.getMenu().add(0, 1, 0, R.string.action_play_now);
        popup.getMenu().add(0, 2, 1, R.string.action_play_next);
        popup.getMenu().add(0, 3, 2, R.string.action_queue_add);
        popup.getMenu().add(0, 4, 3, R.string.action_download_128);
        popup.getMenu().add(0, 5, 4, R.string.action_download_original);
        popup.getMenu().add(0, 6, 5, activity.prefs.isFavorite(track.id)
                ? R.string.action_remove_favorite : R.string.action_add_favorite);
        popup.getMenu().add(0, 7, 6, R.string.action_copy_link);
        popup.getMenu().add(0, 8, 7, R.string.action_open_browser);
        popup.getMenu().add(0, 9, 8, R.string.action_share);
        popup.setOnMenuItemClickListener(item -> {
            PlayerService player = activity.playerBar.service();
            switch (item.getItemId()) {
                case 1: activity.search.playAt(position); return true;
                case 2:
                    if (player != null) { player.enqueueNext(track); }
                    else { MediaBtnReceiver.dispatch(activity, PlayerService.CMD_ENQUEUE_NEXT, track, 0); }
                    return true;
                case 3:
                    if (player != null) { player.enqueue(track); }
                    else { MediaBtnReceiver.dispatch(activity, PlayerService.CMD_ENQUEUE, track, 0); }
                    return true;
                case 4: activity.downloads.start(track, false); return true;
                case 5: activity.downloads.start(track, true); return true;
                case 6: toggleFavorite(track); return true;
                case 7: copyLink(track); return true;
                case 8: openBrowser(track); return true;
                case 9: share(track); return true;
                default: return false;
            }
        });
        popup.show();
    }

    void toggleFavorite(Track track) {
        try {
            boolean added = activity.prefs.toggleFavorite(track);
            activity.toast(added ? R.string.action_add_favorite : R.string.action_remove_favorite);
            activity.search.refreshFavorites();
        } catch (Exception error) {
            ScLog.e("cannot save favorite", error);
            activity.toast(R.string.error_storage);
        }
    }

    private void copyLink(Track track) {
        if (TextUtils.isEmpty(track.permalink)) {
            return;
        }
        android.content.ClipboardManager clipboard = (android.content.ClipboardManager)
                activity.getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(android.content.ClipData.newPlainText("soundcloud", track.permalink));
            activity.toast(R.string.toast_copied);
        }
    }

    private void openBrowser(Track track) {
        if (!TextUtils.isEmpty(track.permalink)) {
            try {
                activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(track.permalink)));
            } catch (Exception error) {
                ScLog.e("cannot open track in browser", error);
                activity.toast(R.string.state_network_error);
            }
        }
    }

    private void share(Track track) {
        if (!TextUtils.isEmpty(track.permalink)) {
            Intent intent = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, track.toString() + "\n" + track.permalink);
            activity.startActivity(Intent.createChooser(intent, activity.getString(R.string.action_share)));
        }
    }

    private void showAbout() {
        String version = "1.0";
        try {
            version = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0).versionName;
        } catch (Exception error) {
            ScLog.e("cannot read app version", error);
        }
        new AlertDialog.Builder(activity).setTitle(R.string.dlg_about_title)
                .setMessage(activity.getString(R.string.about_text, version))
                .setPositiveButton(R.string.dlg_close, null).show();
    }

    private void showLog() {
        ScLog.writeToFile(activity);
        ArrayList<String> lines = new ArrayList<>(ScLog.lines());
        StringBuilder text = new StringBuilder();
        for (int i = Math.max(0, lines.size() - 300); i < lines.size(); i++) {
            text.append(lines.get(i)).append('\n');
        }
        View view = LayoutInflater.from(activity).inflate(R.layout.dialog_log, null);
        ((TextView) view.findViewById(R.id.txtLog)).setText(text.toString());
        new AlertDialog.Builder(activity).setTitle(R.string.menu_view_log).setView(view)
                .setPositiveButton(R.string.dlg_close, null).show();
    }

    void showDownloads() {
        JSONArray records = activity.prefs.downloads();
        if (records.length() == 0) {
            new AlertDialog.Builder(activity).setTitle(R.string.menu_downloads)
                    .setMessage(activity.getString(R.string.dlg_downloads_empty) + "\n\n"
                            + activity.getString(R.string.dlg_downloads_folder))
                    .setPositiveButton(R.string.dlg_close, null).show();
            return;
        }
        long[] ids = new long[records.length()];
        Uri[] uris = new Uri[records.length()];
        String[] mimes = new String[records.length()];
        CharSequence[] labels = new CharSequence[records.length()];
        DownloadManager manager = (DownloadManager) activity.getSystemService(Context.DOWNLOAD_SERVICE);
        for (int i = 0; i < records.length(); i++) {
            JSONObject record = records.optJSONObject(i);
            ids[i] = record == null ? 0 : record.optLong("id");
            String name = record == null ? "" : record.optString("title");
            String state = "";
            String uri = record == null ? "" : record.optString("uri");
            if (!TextUtils.isEmpty(uri)) {
                uris[i] = Uri.parse(uri);
            }
            mimes[i] = record == null ? "audio/mpeg" : record.optString("mime", "audio/mpeg");
            if (manager != null && ids[i] != 0) {
                try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(ids[i]))) {
                    if (cursor != null && cursor.moveToFirst()) {
                        int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                        long done = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR));
                        long total = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES));
                        state = status == DownloadManager.STATUS_SUCCESSFUL ? "✔ " + Fmt.bytes(done)
                                : status == DownloadManager.STATUS_FAILED ? "✖"
                                : "… " + (total > 0 ? (100 * done / total) + "%" : "0%");
                    }
                } catch (Exception error) {
                    ScLog.e("cannot query download status", error);
                }
            }
            labels[i] = name + "  " + state;
        }
        new AlertDialog.Builder(activity).setTitle(R.string.menu_downloads)
                .setItems(labels, (dialog, which) -> openDownload(uris[which], mimes[which]))
                .setNeutralButton(R.string.dlg_downloads_folder, null)
                .setPositiveButton(R.string.dlg_close, null).show();
    }

    private void openDownload(Uri uri, String mime) {
        if (uri == null) {
            activity.toast(R.string.dlg_downloads_empty);
            return;
        }
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            activity.startActivity(intent);
        } catch (Exception error) {
            ScLog.e("cannot open completed download", error);
            activity.toast(R.string.error_media);
        }
    }

    void showSettings() {
        android.widget.CheckBox roaming = new android.widget.CheckBox(activity);
        roaming.setText(R.string.allow_roaming);
        roaming.setChecked(activity.prefs.allowRoaming());
        roaming.setOnCheckedChangeListener((button, checked) -> activity.prefs.setAllowRoaming(checked));
        int padding = (int) (20 * activity.getResources().getDisplayMetrics().density);
        android.widget.LinearLayout content = new android.widget.LinearLayout(activity);
        content.setOrientation(android.widget.LinearLayout.VERTICAL);
        content.setPadding(padding, padding, padding, padding);
        content.addView(roaming);
        TextView description = new TextView(activity);
        description.setText(R.string.roaming_description);
        content.addView(description);
        new AlertDialog.Builder(activity).setTitle(R.string.menu_settings).setView(content)
                .setPositiveButton(R.string.dlg_close, null)
                .setNeutralButton(R.string.language, (dialog, which) -> showLanguages()).show();
    }

    private void showLanguages() {
        String[] labels = {activity.getString(R.string.language_fa), activity.getString(R.string.language_en)};
        int checked = "en".equals(activity.prefs.language()) ? 1 : 0;
        new AlertDialog.Builder(activity).setTitle(R.string.language)
                .setSingleChoiceItems(labels, checked, (dialog, which) -> {
                    activity.prefs.setLanguage(which == 1 ? "en" : "fa");
                    dialog.dismiss();
                    activity.recreate();
                }).setNegativeButton(R.string.dlg_close, null).show();
    }

    void signOut() {
        try {
            activity.prefs.saveCookieHeader("");
            ScApi.forgetCookies();
            android.webkit.CookieManager.getInstance().removeAllCookies(removed -> {
                android.webkit.CookieManager.getInstance().flush();
                ScApi.refreshCookies(activity);
            });
            android.webkit.WebStorage.getInstance().deleteAllData();
        } catch (Exception error) {
            ScLog.e("cannot clear WebView session", error);
        }
        if (!activity.prefs.saveCookieHeader("")) {
            activity.toast(R.string.error_storage);
        }
        ScApi.refreshCookies(activity);
        ScApi.clearClientId(activity);
        updateAccountLabel();
        activity.toast(R.string.menu_logout);
    }

    private void clearCaches() {
        Bg.run(new Bg.Job<Boolean>() {
            @Override
            public Boolean run() {
                Art.clearMemory();
                File[] files = Art.cacheDir(activity).listFiles();
                if (files != null) {
                    for (File file : files) {
                        if (!file.delete()) {
                            ScLog.e("cannot clear an image cache file");
                        }
                    }
                }
                return true;
            }
        }, new Bg.Then<Boolean>() {
            @Override
            public void done(Boolean value, Exception error) {
                if (error != null) { ScLog.e("clear image cache failed", error); }
                else { activity.toast(R.string.toast_cache_cleared); }
            }
        });
    }

    void updateAccountLabel() {
        account.setText(activity.prefs.isLoggedIn() ? R.string.logged_in : R.string.logged_out);
    }
}
