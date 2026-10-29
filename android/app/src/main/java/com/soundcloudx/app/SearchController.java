package com.soundcloudx.app;

import android.content.Context;
import android.content.Intent;
import android.text.TextUtils;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.Spinner;
import android.widget.TextView;

import com.soundcloudx.app.receiver.MediaBtnReceiver;

import java.util.ArrayList;
import java.util.List;

/** Search/charts/favorites and monotonically guarded pagination. */
final class SearchController {
    static final String MODE_SEARCH = "search";
    static final String MODE_CHARTS = "charts";
    static final String MODE_FAVORITES = "favorites";
    private final MainActivity activity;
    private final List<Track> tracks = new ArrayList<>();
    private final TrackAdapter adapter;
    private final EditText editSearch;
    private final ListView listTracks;
    private final Spinner spinnerGenre;
    private final TextView txtStatus;
    private String mode = MODE_CHARTS;
    private String query = "";
    private int offset;
    private int generation;
    private boolean loading;
    private boolean hasMore;

    SearchController(MainActivity activity) {
        this.activity = activity;
        editSearch = (EditText) activity.findViewById(R.id.editSearch);
        listTracks = (ListView) activity.findViewById(R.id.listTracks);
        spinnerGenre = (Spinner) activity.findViewById(R.id.spinnerGenre);
        txtStatus = (TextView) activity.findViewById(R.id.txtStatus);
        adapter = new TrackAdapter(activity, tracks, new TrackAdapter.RowMenuListener() {
            @Override
            public void onRowMenu(Track track, int position, View anchor) {
                activity.dialogs.showTrackMenu(track, position, anchor);
            }
        });
        listTracks.setAdapter(adapter);
        listTracks.setOnItemClickListener(activity);
        listTracks.setOnScrollListener(new android.widget.AbsListView.OnScrollListener() {
            @Override
            public void onScrollStateChanged(android.widget.AbsListView view, int state) { }
            @Override
            public void onScroll(android.widget.AbsListView view, int first, int visible, int total) {
                if (!loading && hasMore && total > 0 && first + visible >= total - 2) {
                    loadMore();
                }
            }
        });
        setupGenres();
        setupSearch();
        editSearch.setText(activity.prefs.lastQuery());
    }

    private void setupGenres() {
        ArrayAdapter<String> genres = new ArrayAdapter<>(activity, R.layout.spinner_item, ScApi.GENRE_LABELS);
        genres.setDropDownViewResource(R.layout.spinner_item);
        spinnerGenre.setAdapter(genres);
        spinnerGenre.setSelection(Math.max(0, Math.min(activity.prefs.lastGenre(), ScApi.GENRE_LABELS.length - 1)));
        spinnerGenre.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                activity.prefs.saveLastGenre(position);
                if (MODE_CHARTS.equals(mode)) {
                    loadCharts();
                }
            }
            @Override
            public void onNothingSelected(AdapterView<?> parent) { }
        });
    }

    private void setupSearch() {
        activity.findViewById(R.id.btnSearch).setOnClickListener(v -> doSearch());
        activity.findViewById(R.id.btnTrending).setOnClickListener(v -> loadCharts());
        activity.findViewById(R.id.btnFavorites).setOnClickListener(v -> showFavorites());
        editSearch.setOnEditorActionListener((v, action, event) -> {
            if (action == EditorInfo.IME_ACTION_SEARCH
                    || (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                doSearch();
                return true;
            }
            return false;
        });
    }

    boolean isLoading() { return loading; }
    String mode() { return mode; }
    List<Track> tracks() { return tracks; }

    void doSearch() {
        String text = editSearch.getText().toString().trim();
        if (TextUtils.isEmpty(text)) {
            activity.toast(R.string.search_hint);
            return;
        }
        InputMethodManager keyboard = (InputMethodManager) activity.getSystemService(Context.INPUT_METHOD_SERVICE);
        if (keyboard != null) {
            keyboard.hideSoftInputFromWindow(editSearch.getWindowToken(), 0);
        }
        activity.prefs.saveLastQuery(text);
        query = text;
        mode = MODE_SEARCH;
        offset = 0;
        hasMore = false;
        tracks.clear();
        adapter.notifyDataSetChanged();
        runQuery(false);
    }

    void loadCharts() {
        mode = MODE_CHARTS;
        query = "";
        offset = 0;
        hasMore = false;
        runQuery(false);
    }

    void showFavorites() {
        generation++;
        loading = false;
        activity.showLoading(false);
        mode = MODE_FAVORITES;
        List<Track> favorites = activity.prefs.favorites();
        tracks.clear();
        tracks.addAll(favorites);
        adapter.notifyDataSetChanged();
        hasMore = false;
        status(favorites.isEmpty() ? activity.getString(R.string.state_favorites_empty)
                : favorites.size() + " " + activity.getString(R.string.btn_favorites));
        listTracks.setSelection(0);
    }

    private void loadMore() {
        if (MODE_FAVORITES.equals(mode) || !hasMore || loading) {
            return;
        }
        offset += 30;
        runQuery(true);
    }

    private void runQuery(final boolean append) {
        final int requestGeneration = ++generation;
        loading = true;
        activity.showLoading(true);
        status(activity.getString(R.string.state_searching));
        final String requestMode = mode;
        final String requestQuery = query;
        final int requestOffset = offset;
        final int genre = Math.max(0, spinnerGenre.getSelectedItemPosition());
        Bg.run(new Bg.Job<List<Track>>() {
            @Override
            public List<Track> run() throws Exception {
                return MODE_SEARCH.equals(requestMode)
                        ? ScApi.search(activity, requestQuery, 30, requestOffset)
                        : ScApi.charts(activity, ScApi.GENRE_SLUGS[genre], 30);
            }
        }, new Bg.Then<List<Track>>() {
            @Override
            public void done(List<Track> result, Exception error) {
                // Errors and spinners are gated too, not just successful rows.
                if (requestGeneration != generation || activity.isFinishing() || activity.isDestroyed()) {
                    return;
                }
                loading = false;
                activity.showLoading(false);
                if (error != null) {
                    ScLog.e("search/charts request failed", error);
                    status(activity.getString(error instanceof ScApi.ApiException
                            ? R.string.state_api_error : R.string.state_network_error));
                    return;
                }
                List<Track> list = result == null ? new ArrayList<Track>() : result;
                if (!append) {
                    tracks.clear();
                }
                for (Track track : list) {
                    boolean known = false;
                    for (Track existing : tracks) {
                        if (existing.id == track.id) {
                            known = true;
                            break;
                        }
                    }
                    if (!known) {
                        tracks.add(track);
                    }
                }
                hasMore = MODE_SEARCH.equals(requestMode) && list.size() >= 30;
                adapter.notifyDataSetChanged();
                if (!append) {
                    listTracks.setSelection(0);
                }
                if (tracks.isEmpty()) {
                    status(activity.getString(R.string.state_no_results));
                } else {
                    status(activity.getString(R.string.status_results, tracks.size(),
                            MODE_SEARCH.equals(requestMode) ? requestQuery : ScApi.GENRE_LABELS[genre]));
                }
            }
        });
    }

    void playAt(int position) {
        if (position < 0 || position >= tracks.size()) {
            return;
        }
        Track track = tracks.get(position);
        if (!track.streamable) {
            activity.toast(R.string.toast_not_streamable);
            return;
        }
        if (activity.playerBar.service() != null) {
            activity.playerBar.service().playAll(new ArrayList<>(tracks), position);
        } else {
            MediaBtnReceiver.dispatch(activity, PlayerService.CMD_PLAY, track, 0);
        }
    }

    void refreshFavorites() {
        if (MODE_FAVORITES.equals(mode)) {
            showFavorites();
        }
        activity.playerBar.updateFavIcon();
    }

    void handleExternalIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        String text = Intent.ACTION_SEND.equals(intent.getAction())
                ? intent.getStringExtra(Intent.EXTRA_TEXT)
                : Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null
                ? intent.getData().toString() : null;
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

    private void status(String text) { txtStatus.setText(text); }
}
