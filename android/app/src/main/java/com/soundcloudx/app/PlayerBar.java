package com.soundcloudx.app;

import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.ServiceConnection;
import android.graphics.Bitmap;
import android.os.Build;
import android.os.IBinder;
import android.text.TextUtils;
import android.view.View;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.TextView;

import com.soundcloudx.app.receiver.MediaBtnReceiver;

/** Player service binding and the existing player bar, without search/list logic. */
final class PlayerBar {
    private final MainActivity activity;
    private final TextView title;
    private final TextView subtitle;
    private final TextView position;
    private final TextView duration;
    private final ImageView art;
    private final ImageButton playPause;
    private final ImageButton favorite;
    private final SeekBar seek;
    private final ProgressBar loading;
    private PlayerService player;
    private boolean bound;
    private boolean registered;
    private boolean seeking;
    private int lastState = PlayerService.STATE_IDLE;
    private Track current;
    private String artUrl = "";
    private int artGeneration;

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) { onState(intent); }
    };
    private final ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            player = ((PlayerService.LocalBinder) service).service();
            bound = true;
            sync();
        }
        @Override
        public void onServiceDisconnected(ComponentName name) {
            player = null;
            bound = false;
        }
    };

    PlayerBar(MainActivity activity) {
        this.activity = activity;
        title = (TextView) activity.findViewById(R.id.txtTitle);
        subtitle = (TextView) activity.findViewById(R.id.txtSub);
        position = (TextView) activity.findViewById(R.id.txtPos);
        duration = (TextView) activity.findViewById(R.id.txtDur);
        art = (ImageView) activity.findViewById(R.id.imgArt);
        playPause = (ImageButton) activity.findViewById(R.id.btnPlayPause);
        favorite = (ImageButton) activity.findViewById(R.id.btnFav);
        seek = (SeekBar) activity.findViewById(R.id.seekBar);
        loading = (ProgressBar) activity.findViewById(R.id.progressLoading);
        title.setSelected(true);
        setup();
    }

    PlayerService service() { return player; }
    Track current() { return player != null && player.getCurrent() != null ? player.getCurrent() : current; }

    private int durationMs() {
        if (player != null && player.getDuration() > 0) {
            return player.getDuration();
        }
        return current() == null ? 0 : current().durationMs;
    }

    private void setup() {
        playPause.setOnClickListener(v -> {
            if (player != null) {
                player.toggle();
            } else {
                MediaBtnReceiver.dispatch(activity, PlayerService.CMD_TOGGLE, null, 0);
            }
        });
        activity.findViewById(R.id.btnNext).setOnClickListener(v -> command(PlayerService.CMD_NEXT));
        activity.findViewById(R.id.btnPrev).setOnClickListener(v -> command(PlayerService.CMD_PREV));
        favorite.setOnClickListener(v -> {
            if (current() != null) {
                activity.dialogs.toggleFavorite(current());
            }
        });
        activity.findViewById(R.id.btnDownload).setOnClickListener(v -> {
            if (current() != null) {
                activity.dialogs.showDownloadMenu(current());
            }
        });
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar bar, int value, boolean user) {
                if (user) {
                    position.setText(Track.format(value * durationMs() / 1000));
                }
            }
            @Override
            public void onStartTrackingTouch(SeekBar bar) { seeking = true; }
            @Override
            public void onStopTrackingTouch(SeekBar bar) {
                seeking = false;
                int target = bar.getProgress() * durationMs() / 1000;
                if (player != null) {
                    player.seekTo(target);
                } else {
                    MediaBtnReceiver.dispatch(activity, PlayerService.CMD_SEEK, null, target);
                }
            }
        });
    }

    void start() {
        try {
            activity.startService(new Intent(activity, PlayerService.class));
        } catch (Exception error) {
            ScLog.e("start player service failed", error);
        }
        try {
            bound = activity.bindService(new Intent(activity, PlayerService.class), connection, Context.BIND_AUTO_CREATE);
        } catch (Exception error) {
            ScLog.e("bind player service failed", error);
        }
    }

    void onStart() {
        if (!registered) {
            IntentFilter filter = new IntentFilter(PlayerService.STATE_CHANGED);
            if (Build.VERSION.SDK_INT >= 33) {
                activity.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                activity.registerReceiver(receiver, filter);
            }
            registered = true;
        }
        sync();
    }

    void onStop() {
        if (registered) {
            try {
                activity.unregisterReceiver(receiver);
            } catch (IllegalArgumentException error) {
                ScLog.e("player receiver already unregistered", error);
            }
            registered = false;
        }
    }

    void destroy() {
        artGeneration++;
        if (bound) {
            try {
                activity.unbindService(connection);
            } catch (IllegalArgumentException error) {
                ScLog.e("player service already unbound", error);
            }
            bound = false;
        }
    }

    private void command(String cmd) {
        if (player == null) {
            MediaBtnReceiver.dispatch(activity, cmd, null, 0);
        } else if (PlayerService.CMD_NEXT.equals(cmd)) {
            player.next();
        } else if (PlayerService.CMD_PREV.equals(cmd)) {
            player.previous();
        }
    }

    private void sync() {
        if (player == null) {
            return;
        }
        current = player.getCurrent();
        lastState = player.getState();
        render();
        if (current != null) {
            title.setText(current.title);
            subtitle.setText(current.artist);
            loadArt(current.coverUrl());
        }
        updateProgress(player.getPosition(), player.getDuration());
    }

    private void onState(Intent intent) {
        if (intent == null) {
            return;
        }
        int state = intent.getIntExtra(PlayerService.EXTRA_STATE, PlayerService.STATE_IDLE);
        String message = intent.getStringExtra(PlayerService.EXTRA_MESSAGE);
        if (state == PlayerService.STATE_ERROR && !TextUtils.isEmpty(message)) {
            activity.toast(activity.getString(R.string.toast_play_error, message));
        }
        String text = intent.getStringExtra(PlayerService.EXTRA_TITLE);
        if (text != null) {
            title.setText(text);
            current = player != null ? player.getCurrent() : current;
        }
        text = intent.getStringExtra(PlayerService.EXTRA_ARTIST);
        if (text != null) {
            subtitle.setText(text);
        }
        loadArt(intent.getStringExtra(PlayerService.EXTRA_ART));
        if (state != lastState || intent.getIntExtra("position", -1) < 0) {
            lastState = state;
            render();
        }
        int pos = intent.getIntExtra("position", -1);
        if (pos >= 0 && !seeking) {
            updateProgress(pos, intent.getIntExtra(PlayerService.EXTRA_DURATION, 0));
        }
    }

    private void loadArt(String url) {
        if (url == null || url.equals(artUrl)) {
            return;
        }
        artUrl = url;
        final int token = ++artGeneration;
        art.setImageBitmap(null);
        Art.load(activity, url, bitmap -> {
            if (token == artGeneration && bitmap != null && !activity.isDestroyed()) {
                art.setImageBitmap(bitmap);
            }
        });
    }

    private void render() {
        playPause.setImageResource(lastState == PlayerService.STATE_PLAYING ? R.drawable.ic_pause : R.drawable.ic_play);
        loading.setVisibility(lastState == PlayerService.STATE_LOADING ? View.VISIBLE : View.GONE);
        if (lastState == PlayerService.STATE_IDLE) {
            title.setText("—");
            subtitle.setText(R.string.state_idle);
        }
        updateFavIcon();
    }

    void updateFavIcon() {
        Track track = current();
        favorite.setImageResource(track != null && activity.prefs.isFavorite(track.id)
                ? R.drawable.ic_star_on : R.drawable.ic_star_off);
    }

    private void updateProgress(int pos, int total) {
        if (total <= 0) {
            total = durationMs();
        }
        seek.setProgress(total > 0 ? Math.max(0, Math.min(1000, pos * 1000 / total)) : 0);
        position.setText(Track.format(pos));
        duration.setText(Track.format(total));
    }
}
