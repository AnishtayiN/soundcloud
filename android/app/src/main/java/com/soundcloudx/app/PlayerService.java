package com.soundcloudx.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaMetadata;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.Player;
import androidx.media3.common.PlaybackException;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Binder;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.text.TextUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * Foreground media player.
 *
 * Playing in the background is a hard requirement, so this service
 *   * runs as a foreground service with a media-style notification,
 *   * owns a MediaSession (lock screen / bluetooth / headset buttons),
 *   * streams complete MP3/progressive/HLS with bundled Media3.
 *
 * The queue and the play position live here, the UI only talks to it through
 * {@link LocalBinder} (when bound) or through start commands (notifications).
 */
@androidx.annotation.OptIn(markerClass = androidx.media3.common.util.UnstableApi.class)
public class PlayerService extends Service {

    // ------------------------------------------------------------- commands --
    public static final String CMD_PLAY = "play";
    public static final String CMD_PAUSE = "pause";
    public static final String CMD_RESUME = "resume";
    public static final String CMD_TOGGLE = "toggle";
    public static final String CMD_NEXT = "next";
    public static final String CMD_PREV = "prev";
    public static final String CMD_STOP = "stop";
    public static final String CMD_SEEK_REL = "seek_rel";
    public static final String CMD_SEEK = "seek";
    public static final String CMD_ENQUEUE_NEXT = "enqueue_next";
    public static final String CMD_ENQUEUE = "enqueue";

    public static final String EXTRA_TRACK = "extra_track";
    public static final String EXTRA_INDEX = "extra_index";
    public static final String EXTRA_SEEK = "extra_seek";
    public static final String EXTRA_CMD = "extra_cmd";

    // ----------------------------------------------------------- broadcasts ---
    public static final String STATE_CHANGED = "com.soundcloudx.app.STATE_CHANGED";
    public static final String EXTRA_STATE = "state";
    public static final String EXTRA_TITLE = "title";
    public static final String EXTRA_ARTIST = "artist";
    public static final String EXTRA_ART = "art";
    public static final String EXTRA_DURATION = "duration";
    public static final String EXTRA_MESSAGE = "message";
    public static final String EXTRA_PLAYING = "playing";

    public static final int STATE_IDLE = 0;
    public static final int STATE_LOADING = 1;
    public static final int STATE_PLAYING = 2;
    public static final int STATE_PAUSED = 3;
    public static final int STATE_ERROR = 4;

    private static final String CHANNEL_ID = "soundcloudx_player";
    private static final int NOTIF_ID = 4211;

    private static PlayerService sInstance;

    /** Set while the service is alive, used by the UI for direct calls. */
    public static PlayerService get() {
        return sInstance;
    }

    public class LocalBinder extends Binder {
        public PlayerService service() {
            return PlayerService.this;
        }
    }

    private final LocalBinder binder = new LocalBinder();

    private ExoPlayer player;
    private MediaSession session;
    private AudioManager audio;
    private AudioAttributes audioAttributes;
    private AudioFocusRequest focusRequest;

    private final List<Track> queue = new ArrayList<>();
    private int currentIndex = -1;
    private Track current;
    private int state = STATE_IDLE;
    private String message = "";
    private boolean playWhenReady = true;
    private int loadToken;
    private int autoSkip;
    private long lastNotificationUpdate;

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (state == STATE_PLAYING || state == STATE_PAUSED) {
                updateSessionState();
                broadcastProgress();
                long now = System.currentTimeMillis();
                if (state == STATE_PLAYING && now - lastNotificationUpdate > 2000) {
                    lastNotificationUpdate = now;
                    showNotification();
                }
                Bg.postDelayed(this, 500);
            }
        }
    };

    private final AudioManager.OnAudioFocusChangeListener focusListener =
            new AudioManager.OnAudioFocusChangeListener() {
                @Override
                public void onAudioFocusChange(int change) {
                    if (change == AudioManager.AUDIOFOCUS_LOSS) {
                        pause();
                    } else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) {
                        pause();
                    } else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
                        if (player != null) {
                            player.setVolume(0.3f);
                        }
                    } else if (change == AudioManager.AUDIOFOCUS_GAIN) {
                        if (player != null) {
                            player.setVolume(1f);
                        }
                    }
                }
            };

    // =======================================================================
    //  lifecycle
    // =======================================================================

    @Override
    public void onCreate() {
        super.onCreate();
        sInstance = this;
        audio = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        audioAttributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build();
        createChannel();
        setupSession();
        ScLog.d("PlayerService created");
    }

    @Override
    public IBinder onBind(Intent intent) {
        return binder;
    }

    @Override
    public boolean onUnbind(Intent intent) {
        return true;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            pendingSeek = intent.getIntExtra(EXTRA_SEEK, 0);
            String cmd = intent.getStringExtra(EXTRA_CMD);
            if (cmd == null) {
                cmd = intent.getAction();
            }
            Object extra = intent.getSerializableExtra(EXTRA_TRACK);
            Track track = extra instanceof Track ? (Track) extra : null;
            if (cmd != null) {
                handle(cmd, track);
            }
            // A foreground service started through startForegroundService() has
            // to post its notification quickly (Android 8+), so we always do it
            // here and only take it down again when nothing is queued.
            if (state != STATE_IDLE) {
                showNotification();
            } else {
                stopForegroundCompat();
                stopSelf();
            }
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        if (state == STATE_IDLE || state == STATE_ERROR) {
            stopSelf();
        }
    }

    @Override
    public void onDestroy() {
        ScLog.d("PlayerService destroyed");
        Bg.MAIN.removeCallbacks(ticker);
        loadToken++;
        releasePlayer();
        abandonFocus();
        if (session != null) {
            session.setActive(false);
            session.release();
            session = null;
        }
        if (sInstance == this) {
            sInstance = null;
        }
        super.onDestroy();
    }

    // =======================================================================
    //  public API used by the UI
    // =======================================================================

    public int getState() {
        return state;
    }

    public String getMessage() {
        return message;
    }

    public Track getCurrent() {
        return current;
    }

    public List<Track> getQueue() {
        return queue;
    }

    public int getCurrentIndex() {
        return currentIndex;
    }

    public int getPosition() {
        try {
            return player == null ? 0 : (int) player.getCurrentPosition();
        } catch (Throwable t) {
            return 0;
        }
    }

    public int getDuration() {
        try {
            int d = player == null ? 0 : (int) player.getDuration();
            if (d > 0) {
                return d;
            }
        } catch (Throwable ignored) {
        }
        return current == null ? 0 : current.durationMs;
    }

    public boolean isPlaying() {
        try {
            return player != null && player.isPlaying();
        } catch (Throwable t) {
            return false;
        }
    }

    /** Starts a fresh queue with a single track. */
    public void play(Track track) {
        if (track == null) {
            return;
        }
        queue.clear();
        queue.add(track);
        currentIndex = 0;
        autoSkip = 0;
        playCurrent(true);
    }

    /** Replaces the queue and starts playing at {@code index}. */
    public void playAll(List<Track> tracks, int index) {
        if (tracks == null || tracks.isEmpty()) {
            return;
        }
        queue.clear();
        queue.addAll(tracks);
        currentIndex = Math.max(0, Math.min(index, queue.size() - 1));
        autoSkip = 0;
        playCurrent(true);
    }

    public void enqueueNext(Track track) {
        if (track == null) {
            return;
        }
        if (queue.isEmpty()) {
            play(track);
            return;
        }
        int at = Math.min(currentIndex + 1, queue.size());
        queue.add(at, track);
        broadcastState();
    }

    public void enqueue(Track track) {
        if (track == null) {
            return;
        }
        if (queue.isEmpty()) {
            play(track);
            return;
        }
        queue.add(track);
        broadcastState();
    }

    public void pause() {
        if (player != null) {
            try {
                player.pause();
            } catch (Throwable ignored) {
            }
        }
        playWhenReady = false;
        setState(STATE_PAUSED);
        abandonFocus();
        updateSessionState();
        showNotification();
    }

    public void resume() {
        if (player != null) {
            try {
                if (!requestFocus()) return;
                playWhenReady = true;
                player.play();
                setState(STATE_PLAYING);
                updateSessionState();
                showNotification();
                startTicker();
                return;
            } catch (Throwable t) {
                ScLog.e("resume failed", t);
            }
        }
        // Nothing loaded (or the player died) -> load the current track again.
        if (currentIndex >= 0 && currentIndex < queue.size()) {
            playCurrent(true);
        }
    }

    public void toggle() {
        if (isPlaying()) {
            pause();
        } else if (state == STATE_PAUSED) {
            resume();
        } else if (currentIndex >= 0 && currentIndex < queue.size()) {
            playCurrent(true);
        }
    }

    public void seekTo(int ms) {
        if (player != null) {
            try {
                player.seekTo(Math.max(0, Math.min(ms, getDuration())));
            } catch (Throwable ignored) {
            }
        }
    }

    public void seekRelative(int deltaMs) {
        seekTo(getPosition() + deltaMs);
    }

    /** @return true when another track started. */
    public boolean next() {
        if (currentIndex + 1 < queue.size()) {
            currentIndex++;
            playCurrent(true);
            return true;
        }
        pause();
        return false;
    }

    public void previous() {
        if (getPosition() > 4000 && player != null) {
            seekTo(0);
            return;
        }
        if (currentIndex > 0) {
            currentIndex--;
            playCurrent(true);
        } else {
            seekTo(0);
        }
    }

    public void stop() {
        loadToken++;
        releasePlayer();
        current = null;
        currentIndex = -1;
        queue.clear();
        setState(STATE_IDLE);
        abandonFocus();
        updateSessionState();
        stopForegroundCompat();
        stopSelf();
    }

    // =======================================================================
    //  start commands (notifications, media buttons, other apps)
    // =======================================================================

    private void handle(String cmd, Track track) {
        if (cmd == null) {
            return;
        }
        switch (cmd) {
            case CMD_PLAY:
                if (track != null) {
                    play(track);
                } else if (currentIndex >= 0) {
                    playCurrent(true);
                }
                break;
            case CMD_ENQUEUE_NEXT:
                if (track != null) {
                    enqueueNext(track);
                }
                break;
            case CMD_ENQUEUE:
                if (track != null) {
                    enqueue(track);
                }
                break;
            case CMD_PAUSE:
                pause();
                break;
            case CMD_RESUME:
                resume();
                break;
            case CMD_TOGGLE:
                toggle();
                break;
            case CMD_NEXT:
                next();
                break;
            case CMD_PREV:
                previous();
                break;
            case CMD_STOP:
                stop();
                break;
            case CMD_SEEK_REL:
                seekRelative(getIntentSeek());
                break;
            case CMD_SEEK:
                seekTo(getIntentSeek());
                break;
            default:
                break;
        }
    }

    private int pendingSeek;

    private int getIntentSeek() {
        return pendingSeek;
    }

    /** Used by the notification: keeps the seek value for {@link #handle(String, Track)}. */
    public void command(String cmd, int seekMs) {
        pendingSeek = seekMs;
        handle(cmd, null);
    }

    // =======================================================================
    //  playback internals
    // =======================================================================

    private void playCurrent(final boolean autoplay) {
        if (currentIndex < 0 || currentIndex >= queue.size()) {
            stop();
            return;
        }
        final Track track = queue.get(currentIndex);
        current = track;
        message = "";
        playWhenReady = autoplay;
        setState(STATE_LOADING);
        final int token = ++loadToken;
        releasePlayer();
        Intent started = new Intent(this, PlayerService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(started);
        } else {
            startService(started);
        }
        showNotification(); // Before URL discovery; never miss the FGS deadline.

        Bg.run(new Bg.Job<String>() {
            @Override
            public String run() throws Exception {
                return ScApi.streamUrl(PlayerService.this, track);
            }
        }, new Bg.Then<String>() {
            @Override
            public void done(String url, Exception error) {
                if (token != loadToken) {
                    return;
                }
                if (error != null || TextUtils.isEmpty(url)) {
                    fail(error);
                    return;
                }
                try {
                    DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
                            .setUserAgent(ScApi.UA).setConnectTimeoutMs(15000).setReadTimeoutMs(25000);
                    final ExoPlayer mp = new ExoPlayer.Builder(PlayerService.this)
                            .setMediaSourceFactory(new DefaultMediaSourceFactory(http)).build();
                    player = mp;
                    mp.setAudioAttributes(new androidx.media3.common.AudioAttributes.Builder()
                            .setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                            .build(), false); // Focus handled by this service.
                    mp.setHandleAudioBecomingNoisy(true);
                    mp.setWakeMode(C.WAKE_MODE_LOCAL);
                    mp.addListener(new Player.Listener() {
                        @Override
                        public void onPlaybackStateChanged(int playbackState) {
                            if (token != loadToken || player != mp) return;
                            if (playbackState == Player.STATE_READY) {
                                autoSkip = 0;
                                if (playWhenReady && requestFocus()) {
                                    mp.play();
                                    setState(STATE_PLAYING);
                                } else {
                                    playWhenReady = false;
                                    setState(STATE_PAUSED);
                                }
                                startTicker();
                                showNotification();
                            } else if (playbackState == Player.STATE_BUFFERING) {
                                setState(STATE_LOADING);
                            } else if (playbackState == Player.STATE_ENDED) {
                                next();
                            }
                        }

                        @Override
                        public void onIsPlayingChanged(boolean playing) {
                            if (token != loadToken || player != mp) return;
                            if (playing) setState(STATE_PLAYING);
                            else if (mp.getPlaybackState() == Player.STATE_READY) setState(STATE_PAUSED);
                            showNotification();
                        }

                        @Override
                        public void onPlayerError(PlaybackException error) {
                            if (token == loadToken && player == mp) fail(error);
                        }
                    });
                    mp.setMediaItem(MediaItem.fromUri(url));
                    mp.prepare();
                } catch (Throwable t) {
                    fail(t instanceof Exception ? (Exception) t : new IllegalStateException(t));
                }
            }
        });
    }

    private void fail(Exception error) {
        message = describe(error);
        ScLog.e("playback failed: " + message, error);
        releasePlayer();
        abandonFocus();
        setState(STATE_ERROR);
        updateSessionState();
        stopForegroundCompat();
        // Automatically skip broken tracks instead of getting stuck.
        if (autoSkip < 2 && currentIndex + 1 < queue.size()) {
            autoSkip++;
            currentIndex++;
            playCurrent(true);
        }
    }

    private String describe(Exception e) {
        if (e == null) {
            return "unknown error";
        }
        String m = e.getMessage();
        if (e instanceof ScApi.ApiException || (m != null && m.contains("not streamable"))) {
            return "not streamable";
        }
        return m == null ? e.getClass().getSimpleName() : m;
    }

    private void setState(int newState) {
        state = newState;
        broadcastState();
    }

    private void releasePlayer() {
        Bg.MAIN.removeCallbacks(ticker);
        if (player != null) {
            try {
                player.stop();
            } catch (Throwable ignored) {
            }
            try {
                player.release();
            } catch (Throwable ignored) {
            }
            player = null;
        }
    }

    private void startTicker() {
        Bg.MAIN.removeCallbacks(ticker);
        Bg.postDelayed(ticker, 500);
    }

    private void broadcastState() {
        Intent i = new Intent(STATE_CHANGED);
        i.setPackage(getPackageName());
        i.putExtra(EXTRA_STATE, state);
        i.putExtra(EXTRA_MESSAGE, message);
        i.putExtra(EXTRA_PLAYING, isPlaying());
        i.putExtra(EXTRA_DURATION, getDuration());
        if (current != null) {
            i.putExtra(EXTRA_TITLE, current.title);
            i.putExtra(EXTRA_ARTIST, current.artist);
            i.putExtra(EXTRA_ART, current.coverUrl());
        }
        sendBroadcast(i);
        updateSessionState();
    }

    private void broadcastProgress() {
        Intent i = new Intent(STATE_CHANGED);
        i.setPackage(getPackageName());
        i.putExtra(EXTRA_STATE, state);
        i.putExtra(EXTRA_DURATION, getDuration());
        i.putExtra("position", getPosition());
        i.putExtra(EXTRA_PLAYING, isPlaying());
        sendBroadcast(i);
    }

    // =======================================================================
    //  audio focus
    // =======================================================================

    private boolean requestFocus() {
        if (audio == null) {
            return true;
        }
        int result;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (focusRequest == null) {
                focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                        .setAudioAttributes(audioAttributes)
                        .setWillPauseWhenDucked(true)
                        .setOnAudioFocusChangeListener(focusListener)
                        .build();
            }
            result = audio.requestAudioFocus(focusRequest);
        } else {
            result = audio.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN);
        }
        return result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
    }

    private void abandonFocus() {
        if (audio == null) {
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && focusRequest != null) {
                audio.abandonAudioFocusRequest(focusRequest);
            } else {
                audio.abandonAudioFocus(focusListener);
            }
        } catch (Throwable ignored) {
        }
    }

    // =======================================================================
    //  media session (lock screen, headset buttons, bluetooth)
    // =======================================================================

    private void setupSession() {
        session = new MediaSession(this, "SoundCloudX");
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS
                | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        session.setCallback(new MediaSession.Callback() {
            @Override
            public void onPlay() {
                resume();
            }

            @Override
            public void onPause() {
                pause();
            }

            @Override
            public void onSkipToNext() {
                next();
            }

            @Override
            public void onSkipToPrevious() {
                previous();
            }

            @Override
            public void onStop() {
                stop();
            }

            @Override
            public void onSeekTo(long pos) {
                seekTo((int) pos);
            }
        });
        // Makes sure headset buttons wake the app up when the session is idle.
        Intent mediaButton = new Intent(Intent.ACTION_MEDIA_BUTTON);
        mediaButton.setClass(this, com.soundcloudx.app.receiver.MediaBtnReceiver.class);
        session.setMediaButtonReceiver(PendingIntent.getBroadcast(this, 91, mediaButton,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        session.setActive(true);
        updateSessionState();
    }

    private void updateSessionState() {
        if (session == null) {
            return;
        }
        long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE
                | PlaybackState.ACTION_PLAY_PAUSE | PlaybackState.ACTION_SKIP_TO_NEXT
                | PlaybackState.ACTION_SKIP_TO_PREVIOUS | PlaybackState.ACTION_SEEK_TO
                | PlaybackState.ACTION_STOP | PlaybackState.ACTION_PLAY_FROM_MEDIA_ID;
        int playbackState = PlaybackState.STATE_NONE;
        if (state == STATE_PLAYING) {
            playbackState = PlaybackState.STATE_PLAYING;
        } else if (state == STATE_PAUSED) {
            playbackState = PlaybackState.STATE_PAUSED;
        } else if (state == STATE_LOADING) {
            playbackState = PlaybackState.STATE_BUFFERING;
        } else if (state == STATE_ERROR) {
            playbackState = PlaybackState.STATE_ERROR;
        }
        session.setPlaybackState(new PlaybackState.Builder()
                .setActions(actions)
                .setState(playbackState, getPosition(), state == STATE_PLAYING ? 1f : 0f)
                .build());
        if (current != null) {
            session.setMetadata(new MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, current.title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, current.artist)
                    .putLong(MediaMetadata.METADATA_KEY_DURATION, getDuration())
                    .putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART,
                            Art.memory(current.coverUrl()))
                    .build());
        }
    }

    // =======================================================================
    //  notification
    // =======================================================================

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null || nm.getNotificationChannel(CHANNEL_ID) != null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID,
                getString(R.string.app_name), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("player");
        channel.setShowBadge(false);
        channel.setSound(null, null);
        nm.createNotificationChannel(channel);
    }

    private PendingIntent pi(String cmd, int seekMs, int requestCode) {
        Intent i = new Intent(this, PlayerService.class);
        i.putExtra(EXTRA_CMD, cmd);
        i.putExtra(EXTRA_SEEK, seekMs);
        return PendingIntent.getService(this, requestCode, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private void showNotification() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) {
            return;
        }

        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent contentIntent = PendingIntent.getActivity(this, 1, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Notification.Action prev = action(android.R.drawable.ic_media_previous, "prev", CMD_PREV, 0, 11);
        Notification.Action playPause = isPlaying()
                ? action(android.R.drawable.ic_media_pause, "pause", CMD_PAUSE, 0, 12)
                : action(android.R.drawable.ic_media_play, "play", CMD_RESUME, 0, 12);
        Notification.Action next = action(android.R.drawable.ic_media_next, "next", CMD_NEXT, 0, 13);
        Notification.Action stop = action(android.R.drawable.ic_menu_close_clear_cancel, "stop", CMD_STOP, 0, 14);

        String title = current == null ? getString(R.string.app_name) : current.title;
        String text = current == null ? getString(R.string.state_idle) : current.artist;

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
            builder.setPriority(Notification.PRIORITY_LOW);
        }
        builder.setSmallIcon(R.drawable.ic_stat_music)
                .setContentTitle(title)
                .setContentText(text)
                .setContentIntent(contentIntent)
                .setOngoing(isPlaying())
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .addAction(prev)
                .addAction(playPause)
                .addAction(next)
                .addAction(stop);

        Bitmap art = current == null ? null : Art.memory(current.coverUrl());
        if (art != null) {
            builder.setLargeIcon(art);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            builder.setStyle(new Notification.MediaStyle()
                    .setMediaSession(session == null ? null : session.getSessionToken())
                    .setShowActionsInCompactView(0, 1, 2));
        }

        Notification notification;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN) {
            notification = builder.build();
        } else {
            notification = builder.getNotification();
        }
        try {
            startForeground(NOTIF_ID, notification);
        } catch (Throwable t) {
            ScLog.e("startForeground refused", t);
            releasePlayer();
            message = "background playback permission refused";
            setState(STATE_ERROR);
            stopSelf();
        }
    }

    private Notification.Action action(int icon, String title, String cmd, int seekMs, int req) {
        return new Notification.Action.Builder(
                android.graphics.drawable.Icon.createWithResource(this, icon),
                title, pi(cmd, seekMs, req)).build();
    }

    private void stopForegroundCompat() {
        try {
            stopForeground(true);
        } catch (Throwable ignored) {
        }
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.cancel(NOTIF_ID);
            }
        } catch (Throwable ignored) {
        }
    }
}
