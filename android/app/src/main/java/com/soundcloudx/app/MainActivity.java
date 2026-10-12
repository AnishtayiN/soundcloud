package com.soundcloudx.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.text.TextUtils;
import android.view.KeyEvent;
import android.view.LayoutInflater;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.ListView;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.soundcloudx.app.receiver.MediaBtnReceiver;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * The single screen of the app: search bar + result list + player bar.
 * Everything uses plain framework widgets, no libraries.
 */
public class MainActivity extends Activity implements AdapterView.OnItemClickListener {

    private static final int REQ_LOGIN = 101;
    private static final int REQ_STORAGE = 102;

    private static final String MODE_SEARCH = "search";
    private static final String MODE_CHARTS = "charts";
    private static final String MODE_FAVORITES = "favorites";

    private final List<Track> tracks = new ArrayList<>();
    private TrackAdapter adapter;
    private Prefs prefs;

    private EditText editSearch;
    private ListView listTracks;
    private Spinner spinnerGenre;
    private TextView txtStatus;
    private TextView txtAccount;
    private TextView txtTitle;
    private TextView txtSub;
    private TextView txtPos;
    private TextView txtDur;
    private ImageView imgArt;
    private ImageButton btnPlayPause;
    private ImageButton btnFav;
    private SeekBar seekBar;
    private ProgressBar progressLoading;

    private PlayerService player;
    private boolean bound;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private String mode = MODE_CHARTS;
    private String query = "";
    private int offset;
    private boolean loading;
    private int queryToken;
    private boolean hasMore;
    private boolean userSeeking;
    private int lastState = PlayerService.STATE_IDLE;
    private Track currentTrack;
    private Track pendingDownload;
    private boolean pendingOriginal;
    private String artUrl = "";

    // ------------------------------------------------------------ receivers --

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            onPlayerState(intent);
        }
    };

    private final ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            PlayerService.LocalBinder binder = (PlayerService.LocalBinder) service;
            player = binder.service();
            bound = true;
            syncFromService();
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            player = null;
            bound = false;
        }
    };

    // =======================================================================
    //  lifecycle
    // =======================================================================

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        prefs = Prefs.get(this);

        editSearch = (EditText) findViewById(R.id.editSearch);
        listTracks = (ListView) findViewById(R.id.listTracks);
        spinnerGenre = (Spinner) findViewById(R.id.spinnerGenre);
        txtStatus = (TextView) findViewById(R.id.txtStatus);
        txtAccount = (TextView) findViewById(R.id.txtAccount);
        txtTitle = (TextView) findViewById(R.id.txtTitle);
        txtSub = (TextView) findViewById(R.id.txtSub);
        txtPos = (TextView) findViewById(R.id.txtPos);
        txtDur = (TextView) findViewById(R.id.txtDur);
        imgArt = (ImageView) findViewById(R.id.imgArt);
        btnPlayPause = (ImageButton) findViewById(R.id.btnPlayPause);
        btnFav = (ImageButton) findViewById(R.id.btnFav);
        seekBar = (SeekBar) findViewById(R.id.seekBar);
        progressLoading = (ProgressBar) findViewById(R.id.progressLoading);

        txtTitle.setSelected(true);

        adapter = new TrackAdapter(this, tracks, new TrackAdapter.RowMenuListener() {
            @Override
            public void onRowMenu(Track track, int position, View anchor) {
                showTrackMenu(track, position, anchor);
            }
        });
        listTracks.setAdapter(adapter);
        listTracks.setOnItemClickListener(this);
        listTracks.setOnScrollListener(new android.widget.AbsListView.OnScrollListener() {
            @Override
            public void onScrollStateChanged(android.widget.AbsListView view, int scrollState) {
            }

            @Override
            public void onScroll(android.widget.AbsListView view, int firstVisibleItem,
                                 int visibleItemCount, int totalItemCount) {
                if (!loading && hasMore && totalItemCount > 0
                        && firstVisibleItem + visibleItemCount >= totalItemCount - 2) {
                    loadMore();
                }
            }
        });

        setupGenreSpinner();
        setupSearch();
        setupPlayerBar();
        setupMenu();

        editSearch.setText(prefs.lastQuery());

        // Bind while idle; the service becomes started/foreground on Play.
        bindService(new Intent(this, PlayerService.class), connection, Context.BIND_AUTO_CREATE);

        Art.trimCache(this, 400);
        requestNotificationPermission();

        loadCharts();
        handleExternalIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleExternalIntent(intent);
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(PlayerService.STATE_CHANGED);
        androidx.core.content.ContextCompat.registerReceiver(this, stateReceiver, filter,
                androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED);
        ScApi.refreshCookies(this);
        updateAccountLabel();
        syncFromService();
    }

    @Override
    protected void onStop() {
        super.onStop();
        try {
            unregisterReceiver(stateReceiver);
        } catch (Throwable ignored) {
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        queryToken++;
        ui.removeCallbacksAndMessages(null);
        if (bound) {
            try {
                unbindService(connection);
            } catch (Throwable ignored) {
            }
            bound = false;
        }
    }

    @Override
    public void onBackPressed() {
        if (loading) {
            toast(getString(R.string.state_loading_more));
            return;
        }
        super.onBackPressed();
    }

    // =======================================================================
    //  ui setup
    // =======================================================================

    private void setupGenreSpinner() {
        ArrayAdapter<String> genreAdapter = new ArrayAdapter<>(
                this, R.layout.spinner_item, ScApi.GENRE_LABELS);
        genreAdapter.setDropDownViewResource(R.layout.spinner_item);
        spinnerGenre.setAdapter(genreAdapter);
        int saved = Math.max(0, Math.min(prefs.lastGenre(), ScApi.GENRE_LABELS.length - 1));
        spinnerGenre.setSelection(saved);
        spinnerGenre.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.saveLastGenre(position);
                if (MODE_CHARTS.equals(mode)) {
                    loadCharts();
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
    }

    private void setupSearch() {
        findViewById(R.id.btnSearch).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                doSearch();
            }
        });
        findViewById(R.id.btnTrending).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                loadCharts();
            }
        });
        findViewById(R.id.btnFavorites).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showFavorites();
            }
        });
        editSearch.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, KeyEvent event) {
                if (actionId == EditorInfo.IME_ACTION_SEARCH
                        || (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                    doSearch();
                    return true;
                }
                return false;
            }
        });
    }

    private void setupPlayerBar() {
        btnPlayPause.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (player != null) {
                    player.toggle();
                } else {
                    MediaBtnReceiver.dispatch(MainActivity.this, PlayerService.CMD_TOGGLE, null, 0);
                }
            }
        });
        findViewById(R.id.btnNext).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                command(PlayerService.CMD_NEXT);
            }
        });
        findViewById(R.id.btnPrev).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                command(PlayerService.CMD_PREV);
            }
        });
        btnFav.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Track t = current();
                if (t == null) {
                    return;
                }
                boolean added = prefs.toggleFavorite(t);
                toast(added ? R.string.action_add_favorite : R.string.action_remove_favorite);
                updateFavIcon();
            }
        });
        findViewById(R.id.btnDownload).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                final Track t = current();
                if (t == null) {
                    return;
                }
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle(t.title)
                        .setItems(new CharSequence[]{
                                getString(R.string.action_download_128),
                                getString(R.string.action_download_original)},
                                new android.content.DialogInterface.OnClickListener() {
                                    @Override
                                    public void onClick(android.content.DialogInterface d, int which) {
                                        download(t, which == 1);
                                    }
                                })
                        .setNegativeButton(R.string.dlg_close, null)
                        .show();
            }
        });
        seekBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar bar, int value, boolean fromUser) {
                if (fromUser) {
                    txtPos.setText(Track.format(value * duration() / 1000));
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar bar) {
                userSeeking = true;
            }

            @Override
            public void onStopTrackingTouch(SeekBar bar) {
                userSeeking = false;
                int target = bar.getProgress() * duration() / 1000;
                if (player != null) {
                    player.seekTo(target);
                } else {
                    MediaBtnReceiver.dispatch(MainActivity.this, PlayerService.CMD_SEEK, null, target);
                }
            }
        });
    }

    private void setupMenu() {
        findViewById(R.id.btnMenu).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PopupMenu popup = new PopupMenu(MainActivity.this, v);
                popup.getMenu().add(0, 1, 0, prefs.isLoggedIn()
                        ? R.string.menu_logout : R.string.menu_login);
                popup.getMenu().add(0, 2, 1, R.string.menu_downloads);
                popup.getMenu().add(0, 3, 2, R.string.menu_reload_api);
                popup.getMenu().add(0, 4, 3, R.string.menu_clear_cache);
                popup.getMenu().add(0, 5, 4, R.string.menu_view_log);
                popup.getMenu().add(0, 6, 5, R.string.dlg_about_title);
                popup.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
                    @Override
                    public boolean onMenuItemClick(android.view.MenuItem item) {
                        switch (item.getItemId()) {
                            case 1:
                                if (prefs.isLoggedIn()) {
                                    signOut();
                                } else {
                                    startActivityForResult(
                                            new Intent(MainActivity.this, LoginActivity.class),
                                            REQ_LOGIN);
                                }
                                return true;
                            case 2:
                                showDownloads();
                                return true;
                            case 3:
                                ScApi.clearClientId(MainActivity.this);
                                toast(R.string.toast_client_id_reloaded);
                                return true;
                            case 4:
                                clearCaches();
                                return true;
                            case 5:
                                showLog();
                                return true;
                            case 6:
                                showAbout();
                                return true;
                            default:
                                return false;
                        }
                    }
                });
                popup.show();
            }
        });
    }

    // =======================================================================
    //  data loading
    // =======================================================================

    private void doSearch() {
        String q = editSearch.getText().toString().trim();
        if (TextUtils.isEmpty(q)) {
            toast(R.string.search_hint);
            return;
        }
        hideKeyboard();
        prefs.saveLastQuery(q);
        query = q;
        mode = MODE_SEARCH;
        offset = 0;
        hasMore = false;
        tracks.clear();
        adapter.notifyDataSetChanged();
        status(getString(R.string.state_searching));
        runQuery(false);
    }

    private void loadCharts() {
        mode = MODE_CHARTS;
        query = "";
        offset = 0;
        hasMore = false;
        status(getString(R.string.state_searching));
        runQuery(false);
    }

    private void showFavorites() {
        queryToken++;
        loading = false;
        showLoading(false);
        mode = MODE_FAVORITES;
        List<Track> favorites = prefs.favorites();
        tracks.clear();
        tracks.addAll(favorites);
        adapter.notifyDataSetChanged();
        hasMore = false;
        if (favorites.isEmpty()) {
            status(getString(R.string.state_favorites_empty));
        } else {
            status(favorites.size() + " " + getString(R.string.btn_favorites));
        }
        listTracks.setSelection(0);
    }

    private void loadMore() {
        if (MODE_FAVORITES.equals(mode) || !hasMore) {
            return;
        }
        offset += 30;
        runQuery(true);
    }

    private void runQuery(final boolean append) {
        if (loading && append) return;
        final int token = ++queryToken;
        loading = true;
        showLoading(true);
        final String currentMode = mode;
        final String currentQuery = query;
        final int currentOffset = offset;
        final int genreIndex = Math.max(0, spinnerGenre.getSelectedItemPosition());

        Bg.run(new Bg.Job<List<Track>>() {
            @Override
            public List<Track> run() throws Exception {
                if (MODE_SEARCH.equals(currentMode)) {
                    return ScApi.search(MainActivity.this, currentQuery, 30, currentOffset);
                }
                return ScApi.charts(MainActivity.this, ScApi.GENRE_SLUGS[genreIndex], 30, currentOffset);
            }
        }, new Bg.Then<List<Track>>() {
            @Override
            public void done(List<Track> result, Exception error) {
                if (token != queryToken || isFinishing() || isDestroyed()) return;
                loading = false;
                showLoading(false);
                if (error != null) {
                    ScLog.e("query failed", error);
                    status(error instanceof ScApi.ApiException
                            ? getString(R.string.state_api_error)
                            : getString(R.string.state_network_error));
                    return;
                }
                List<Track> list = result == null ? new ArrayList<Track>() : result;
                if (append) {
                    // Skip tracks that are already visible.
                    for (Track t : list) {
                        boolean known = false;
                        for (Track existing : tracks) {
                            if (existing.id == t.id) {
                                known = true;
                                break;
                            }
                        }
                        if (!known) {
                            tracks.add(t);
                        }
                    }
                } else {
                    tracks.clear();
                    tracks.addAll(list);
                }
                hasMore = MODE_SEARCH.equals(currentMode) && list.size() >= 30;
                adapter.notifyDataSetChanged();
                if (!append) {
                    listTracks.setSelection(0);
                }
                if (tracks.isEmpty()) {
                    status(getString(R.string.state_no_results));
                } else {
                    String label = MODE_SEARCH.equals(currentMode)
                            ? currentQuery : ScApi.GENRE_LABELS[genreIndex];
                    status(getString(R.string.status_results, tracks.size(), label));
                }
            }
        });
    }

    private void performDownload(final Track track, final boolean original) {
        if (original && !prefs.isLoggedIn()) {
            toast(R.string.toast_need_login);
            return;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = track;
            pendingOriginal = original;
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            return;
        }
        toast(R.string.toast_download_started);
        try {
            // Promote immediately while the user is in the app. URL discovery
            // and transfer are done by DownloadService, also after leaving UI.
            Downloader.enqueue(this, track, null, original);
        } catch (Exception error) {
            ScLog.e("download failed", error);
            toast(getString(R.string.toast_download_failed, error.getMessage()));
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] granted) {
        super.onRequestPermissionsResult(requestCode, permissions, granted);
        if (requestCode == REQ_STORAGE) {
            if (granted.length > 0 && granted[0] == PackageManager.PERMISSION_GRANTED) {
                if (pendingDownload != null) {
                    performDownload(pendingDownload, pendingOriginal);
                }
            } else {
                toast(R.string.toast_need_permission);
            }
            pendingDownload = null;
        }
    }

    // =======================================================================
    //  list interaction
    // =======================================================================

    @Override
    public void onItemClick(AdapterView<?> parent, View view, int position, long id) {
        if (position < 0 || position >= tracks.size()) {
            return;
        }
        Track track = tracks.get(position);
        if (!track.streamable) {
            toast(R.string.toast_not_streamable);
            return;
        }
        if (player != null) {
            player.playAll(new ArrayList<>(tracks), position);
        } else {
            MediaBtnReceiver.dispatch(this, PlayerService.CMD_PLAY, track, 0);
        }
    }

    private void showTrackMenu(final Track track, final int position, View anchor) {
        PopupMenu popup = new PopupMenu(this, anchor);
        popup.getMenu().add(0, 1, 0, R.string.action_play_now);
        popup.getMenu().add(0, 2, 1, R.string.action_play_next);
        popup.getMenu().add(0, 3, 2, R.string.action_queue_add);
        popup.getMenu().add(0, 4, 3, R.string.action_download_128);
        popup.getMenu().add(0, 5, 4, R.string.action_download_original);
        popup.getMenu().add(0, 6, 5, prefs.isFavorite(track.id)
                ? R.string.action_remove_favorite : R.string.action_add_favorite);
        popup.getMenu().add(0, 7, 6, R.string.action_copy_link);
        popup.getMenu().add(0, 8, 7, R.string.action_open_browser);
        popup.getMenu().add(0, 9, 8, R.string.action_share);
        popup.setOnMenuItemClickListener(new PopupMenu.OnMenuItemClickListener() {
            @Override
            public boolean onMenuItemClick(android.view.MenuItem item) {
                switch (item.getItemId()) {
                    case 1:
                        if (player != null) {
                            player.playAll(new ArrayList<>(tracks), position);
                        } else {
                            MediaBtnReceiver.dispatch(MainActivity.this,
                                    PlayerService.CMD_PLAY, track, 0);
                        }
                        return true;
                    case 2:
                        if (player != null) {
                            player.enqueueNext(track);
                        } else {
                            MediaBtnReceiver.dispatch(MainActivity.this,
                                    PlayerService.CMD_ENQUEUE_NEXT, track, 0);
                        }
                        return true;
                    case 3:
                        if (player != null) {
                            player.enqueue(track);
                        } else {
                            MediaBtnReceiver.dispatch(MainActivity.this,
                                    PlayerService.CMD_ENQUEUE, track, 0);
                        }
                        return true;
                    case 4:
                        download(track, false);
                        return true;
                    case 5:
                        download(track, true);
                        return true;
                    case 6:
                        boolean added = prefs.toggleFavorite(track);
                        toast(added ? R.string.action_add_favorite : R.string.action_remove_favorite);
                        if (MODE_FAVORITES.equals(mode)) {
                            showFavorites();
                        }
                        updateFavIcon();
                        return true;
                    case 7:
                        copyLink(track);
                        return true;
                    case 8:
                        openBrowser(track);
                        return true;
                    case 9:
                        share(track);
                        return true;
                    default:
                        return false;
                }
            }
        });
        popup.show();
    }

    private void download(Track track, boolean original) {
        performDownload(track, original);
    }

    private void copyLink(Track track) {
        if (TextUtils.isEmpty(track.permalink)) {
            return;
        }
        android.content.ClipboardManager clipboard =
                (android.content.ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(android.content.ClipData.newPlainText("soundcloud", track.permalink));
            toast(R.string.toast_copied);
        }
    }

    private void openBrowser(Track track) {
        if (TextUtils.isEmpty(track.permalink)) {
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(track.permalink)));
        } catch (Throwable t) {
            toast(R.string.state_network_error);
        }
    }

    private void share(Track track) {
        if (TextUtils.isEmpty(track.permalink)) {
            return;
        }
        Intent share = new Intent(Intent.ACTION_SEND);
        share.setType("text/plain");
        share.putExtra(Intent.EXTRA_TEXT, track.toString() + "\n" + track.permalink);
        startActivity(Intent.createChooser(share, getString(R.string.action_share)));
    }

    // =======================================================================
    //  player bridging
    // =======================================================================

    private void command(String cmd) {
        if (player != null) {
            if (PlayerService.CMD_NEXT.equals(cmd)) {
                player.next();
            } else if (PlayerService.CMD_PREV.equals(cmd)) {
                player.previous();
            } else if (PlayerService.CMD_PAUSE.equals(cmd)) {
                player.pause();
            } else if (PlayerService.CMD_RESUME.equals(cmd)) {
                player.resume();
            }
        } else {
            MediaBtnReceiver.dispatch(this, cmd, null, 0);
        }
    }

    /** Current track: prefer the service, fall back to the last broadcast. */
    private Track current() {
        if (player != null && player.getCurrent() != null) {
            return player.getCurrent();
        }
        return currentTrack;
    }

    private int duration() {
        if (player != null && player.getDuration() > 0) {
            return player.getDuration();
        }
        Track t = current();
        return t == null ? 0 : t.durationMs;
    }

    private void syncFromService() {
        if (player == null) {
            return;
        }
        currentTrack = player.getCurrent();
        lastState = player.getState();
        renderPlayerUi();
    }

    private void onPlayerState(Intent intent) {
        if (intent == null) {
            return;
        }
        int state = intent.getIntExtra(PlayerService.EXTRA_STATE, PlayerService.STATE_IDLE);
        String title = intent.getStringExtra(PlayerService.EXTRA_TITLE);
        String artist = intent.getStringExtra(PlayerService.EXTRA_ARTIST);
        String art = intent.getStringExtra(PlayerService.EXTRA_ART);
        String message = intent.getStringExtra(PlayerService.EXTRA_MESSAGE);
        int durationMs = intent.getIntExtra(PlayerService.EXTRA_DURATION, 0);
        int position = intent.getIntExtra("position", -1);

        if (state == PlayerService.STATE_ERROR && !TextUtils.isEmpty(message)) {
            toast(getString(R.string.toast_download_failed, message).replace(":", ": "));
        }
        if (title != null) {
            txtTitle.setText(title);
            currentTrack = player != null ? player.getCurrent() : currentTrack;
        }
        if (artist != null) {
            txtSub.setText(artist);
        }
        if (art != null && !art.equals(artUrl)) {
            artUrl = art;
            imgArt.setImageBitmap(null);
            Art.load(this, art, new Art.Callback() {
                @Override
                public void ready(Bitmap bitmap) {
                    if (bitmap != null) {
                        imgArt.setImageBitmap(bitmap);
                    }
                }
            });
        }
        if (state != lastState || position < 0) {
            lastState = state;
            renderPlayerUi();
        }
        if (position >= 0 && !userSeeking) {
            updateProgress(position, durationMs);
        }
    }

    private void renderPlayerUi() {
        boolean playing = lastState == PlayerService.STATE_PLAYING;
        btnPlayPause.setImageResource(playing ? R.drawable.ic_pause : R.drawable.ic_play);
        progressLoading.setVisibility(lastState == PlayerService.STATE_LOADING
                ? View.VISIBLE : View.GONE);
        if (lastState == PlayerService.STATE_IDLE) {
            txtTitle.setText("—");
            txtSub.setText(R.string.state_idle);
        }
        updateFavIcon();
    }

    private void updateFavIcon() {
        Track t = current();
        btnFav.setImageResource(t != null && prefs.isFavorite(t.id)
                ? R.drawable.ic_star_on : R.drawable.ic_star_off);
    }

    private void updateProgress(int position, int durationMs) {
        if (durationMs <= 0) {
            durationMs = duration();
        }
        if (durationMs > 0) {
            seekBar.setProgress(Math.max(0, Math.min(1000, position * 1000 / durationMs)));
        } else {
            seekBar.setProgress(0);
        }
        txtPos.setText(Track.format(position));
        txtDur.setText(Track.format(durationMs));
    }

    // =======================================================================
    //  dialogs
    // =======================================================================

    private void showAbout() {
        String version = "1.0";
        try {
            version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Throwable ignored) {
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.dlg_about_title)
                .setMessage(getString(R.string.about_text, version))
                .setPositiveButton(R.string.dlg_close, null)
                .show();
    }

    private void showLog() {
        ScLog.writeToFile(this);
        ArrayList<String> lines = new ArrayList<>(ScLog.lines());
        StringBuilder sb = new StringBuilder();
        for (int i = Math.max(0, lines.size() - 300); i < lines.size(); i++) {
            sb.append(lines.get(i)).append('\n');
        }
        View view = LayoutInflater.from(this).inflate(R.layout.dialog_log, null);
        ((TextView) view.findViewById(R.id.txtLog)).setText(sb.toString());
        new AlertDialog.Builder(this)
                .setTitle(R.string.menu_view_log)
                .setView(view)
                .setPositiveButton(R.string.dlg_close, null)
                .show();
    }

    private void showDownloads() {
        final JSONArray arr = prefs.downloads();
        if (arr.length() == 0) {
            new AlertDialog.Builder(this)
                    .setTitle(R.string.menu_downloads)
                    .setMessage(getString(R.string.dlg_downloads_empty)
                            + "\n\n" + getString(R.string.dlg_downloads_folder))
                    .setPositiveButton(R.string.dlg_close, null)
                    .show();
            return;
        }
        final long[] ids = new long[arr.length()];
        final CharSequence[] items = new CharSequence[arr.length()];
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            ids[i] = o == null ? 0 : o.optLong("id");
            String name = o == null ? "" : o.optString("title", "");
            String state = "";
            String ownState = o == null ? "" : o.optString("state");
            if (!TextUtils.isEmpty(ownState)) {
                long done = o.optLong("done"), total = o.optLong("total");
                if ("done".equals(ownState)) state = "✔ " + Fmt.bytes(done);
                else if ("failed".equals(ownState)) state = "✖ " + o.optString("error");
                else if ("cancelled".equals(ownState)) state = getString(R.string.download_cancelled);
                else state = "… " + (total > 0 ? (100 * done / total) + "%" : Fmt.bytes(done));
            } else if (dm != null && ids[i] != 0) {
                Cursor c = null;
                try {
                    c = dm.query(new DownloadManager.Query().setFilterById(ids[i]));
                    if (c != null && c.moveToFirst()) {
                        int status = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                        long done = c.getLong(c.getColumnIndexOrThrow(
                                DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR));
                        long total = c.getLong(c.getColumnIndexOrThrow(
                                DownloadManager.COLUMN_TOTAL_SIZE_BYTES));
                        if (status == DownloadManager.STATUS_SUCCESSFUL) {
                            state = "✔ " + Fmt.bytes(total);
                        } else if (status == DownloadManager.STATUS_FAILED) {
                            state = "✖";
                        } else {
                            state = "… " + (total > 0 ? (100 * done / total) + "%" : "0%");
                        }
                    }
                } catch (Throwable ignored) {
                    state = "";
                } finally {
                    if (c != null) {
                        c.close();
                    }
                }
            }
            items[i] = name + "  " + state;
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.menu_downloads)
                .setItems(items, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        openDownload(ids[which]);
                    }
                })
                .setNeutralButton(R.string.dlg_downloads_folder, null)
                .setPositiveButton(R.string.dlg_close, null)
                .show();
    }

    private void openDownload(final long id) {
        JSONObject own = prefs.download(id);
        if (own != null && !TextUtils.isEmpty(own.optString("state"))) {
            String state = own.optString("state");
            if ("queued".equals(state) || "running".equals(state)) {
                new AlertDialog.Builder(this).setTitle(R.string.menu_downloads)
                        .setMessage(own.optString("title"))
                        .setPositiveButton(R.string.download_cancel, (dialog, which) -> {
                            Intent cancel = new Intent(this, DownloadService.class);
                            cancel.putExtra("cancel", id);
                            startService(cancel);
                        }).setNegativeButton(R.string.dlg_close, null).show();
            } else if ("done".equals(state)) {
                try {
                    Intent view = new Intent(Intent.ACTION_VIEW);
                    view.setDataAndType(Uri.parse(own.optString("uri")), own.optString("mime", "audio/mpeg"));
                    view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    startActivity(view);
                } catch (RuntimeException error) { toast(R.string.download_no_player); }
            } else toast(own.optString("error", getString(R.string.download_cancelled)));
            return;
        }
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null || id == 0) {
            return;
        }
        try {
            Uri uri = dm.getUriForDownloadedFile(id);
            if (uri == null) {
                toast(R.string.dlg_downloads_empty);
                return;
            }
            Intent view = new Intent(Intent.ACTION_VIEW);
            view.setDataAndType(uri, "audio/mpeg");
            view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(view);
        } catch (Throwable t) {
            ScLog.e("cannot open download", t);
        }
    }

    private void signOut() {
        try {
            android.webkit.CookieManager.getInstance().removeAllCookies(null);
            android.webkit.CookieManager.getInstance().flush();
        } catch (Throwable ignored) {
        }
        ScApi.refreshCookies(this);
        ScApi.clearClientId(MainActivity.this);
        updateAccountLabel();
        toast(R.string.menu_logout);
    }

    private void clearCaches() {
        Bg.run(new Bg.Job<Boolean>() {
            @Override
            public Boolean run() {
                Art.clearMemory();
                java.io.File dir = Art.cacheDir(MainActivity.this);
                java.io.File[] files = dir.listFiles();
                if (files != null) {
                    for (java.io.File f : files) {
                        //noinspection ResultOfMethodCallIgnored
                        f.delete();
                    }
                }
                return true;
            }
        }, new Bg.Then<Boolean>() {
            @Override
            public void done(Boolean value, Exception error) {
                toast(R.string.toast_cache_cleared);
            }
        });
    }

    private void updateAccountLabel() {
        txtAccount.setText(prefs.isLoggedIn() ? R.string.logged_in : R.string.logged_out);
    }

    // =======================================================================
    //  helpers
    // =======================================================================

    private void status(String text) {
        txtStatus.setText(text);
    }

    private void showLoading(boolean show) {
        progressLoading.setVisibility(show ? View.VISIBLE : View.GONE);
        if (show) {
            status(getString(R.string.state_searching));
        }
    }

    private void hideKeyboard() {
        try {
            InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.hideSoftInputFromWindow(editSearch.getWindowToken(), 0);
            }
        } catch (Throwable ignored) {
        }
    }

    private void toast(int res) {
        Toast.makeText(this, res, Toast.LENGTH_SHORT).show();
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_LOGIN) {
            ScApi.refreshCookies(this);
            updateAccountLabel();
            if (resultCode == RESULT_OK) {
                toast(R.string.toast_login_success);
            }
        }
    }

    /** Android 13+ hides notifications (including the player one) unless asked. */
    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33) {
            return;
        }
        try {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 103);
            }
        } catch (Throwable ignored) {
        }
    }

    /** Handles "share to app" / "open with app" SoundCloud links. */
    private void handleExternalIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        String text = null;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            text = intent.getStringExtra(Intent.EXTRA_TEXT);
        } else if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            text = intent.getData().toString();
        }
        if (TextUtils.isEmpty(text) || !text.contains("soundcloud.com")) {
            return;
        }
        String url = text.trim();
        int start = url.indexOf("http");
        if (start > 0) {
            url = url.substring(start);
        }
        int space = url.indexOf(' ');
        if (space > 0) {
            url = url.substring(0, space);
        }
        editSearch.setText(url);
        doSearch();
    }
}
