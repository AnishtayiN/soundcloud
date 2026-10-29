package com.soundcloudx.app;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.AdapterView;
import android.widget.Toast;

/** Single-screen coordinator. Lists, player controls and dialogs live in separate modules. */
public class MainActivity extends Activity implements AdapterView.OnItemClickListener {
    static final int REQ_LOGIN = 101;
    Prefs prefs;
    SearchController search;
    PlayerBar playerBar;
    AppDialogs dialogs;
    DownloadCoordinator downloads;
    private boolean receiversRegistered;

    private final BroadcastReceiver downloadReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent.getBooleanExtra(Downloader.EXTRA_SUCCESS, false)) {
                toast(R.string.toast_download_complete);
            } else {
                toast(getString(R.string.toast_download_failed, getString(R.string.error_media)));
            }
        }
    };

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(LocaleHelper.wrap(base));
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        prefs = Prefs.get(this);
        dialogs = new AppDialogs(this);
        playerBar = new PlayerBar(this);
        downloads = new DownloadCoordinator(this);
        search = new SearchController(this);
        dialogs.setupMenu();
        playerBar.start();
        Bg.run(new Bg.Job<Boolean>() {
            @Override
            public Boolean run() {
                Art.trimCache(MainActivity.this, 400);
                Downloader.reconcile(MainActivity.this);
                return true;
            }
        }, null);
        requestNotificationPermission();
        search.loadCharts();
        search.handleExternalIntent(getIntent());
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (!receiversRegistered) {
            IntentFilter filter = new IntentFilter(Downloader.ACTION_CHANGED);
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(downloadReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                registerReceiver(downloadReceiver, filter);
            }
            receiversRegistered = true;
        }
        playerBar.onStart();
        ScApi.refreshCookies(this);
        dialogs.updateAccountLabel();
    }

    @Override
    protected void onStop() {
        if (receiversRegistered) {
            try {
                unregisterReceiver(downloadReceiver);
            } catch (IllegalArgumentException error) {
                ScLog.e("download receiver already unregistered", error);
            }
            receiversRegistered = false;
        }
        playerBar.onStop();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        playerBar.destroy();
        super.onDestroy();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        search.handleExternalIntent(intent);
    }

    @Override
    public void onBackPressed() {
        if (search.isLoading()) {
            toast(R.string.state_loading_more);
            return;
        }
        super.onBackPressed();
    }

    @Override
    public void onItemClick(AdapterView<?> parent, View view, int position, long id) {
        search.playAt(position);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] granted) {
        super.onRequestPermissionsResult(requestCode, permissions, granted);
        downloads.onPermissionResult(requestCode, granted);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_LOGIN) {
            ScApi.refreshCookies(this);
            dialogs.updateAccountLabel();
            if (resultCode == RESULT_OK) {
                toast(R.string.toast_login_success);
            }
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 103);
        }
    }

    void showLoading(boolean show) {
        findViewById(R.id.progressLoading).setVisibility(show ? View.VISIBLE : View.GONE);
    }

    void toast(int resource) {
        Toast.makeText(this, resource, Toast.LENGTH_SHORT).show();
    }

    void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }
}
