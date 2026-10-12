package com.soundcloudx.app;

import android.content.ComponentName;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.ActivityInfo;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;
import android.widget.ListView;
import androidx.core.content.FileProvider;
import androidx.lifecycle.Lifecycle;
import androidx.media3.common.MediaItem;
import androidx.media3.common.Player;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

/** Real lifecycle, images/resources, storage and playback; no SoundCloud network needed. */
@androidx.annotation.OptIn(markerClass = androidx.media3.common.util.UnstableApi.class)
@RunWith(AndroidJUnit4.class)
public class AppSmokeTest {
    private Context context() { return InstrumentationRegistry.getInstrumentation().getTargetContext(); }

    @Test public void realActivityStartsAndResumes() {
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            assertEquals(Lifecycle.State.RESUMED, activity.getState());
            activity.onActivity(a -> {
                assertNotNull(a.findViewById(R.id.editSearch));
                assertNotNull(a.findViewById(R.id.btnPlayPause));
                a.findViewById(R.id.btnFavorites).performClick();
            });
            activity.moveToState(Lifecycle.State.CREATED);
            activity.moveToState(Lifecycle.State.RESUMED); // register/unregister receiver again.
            activity.onActivity(a -> assertNotNull(a.findViewById(R.id.seekBar)));
        }
    }

    @Test public void favoritesActuallyRender() {
        Prefs prefs = Prefs.get(context());
        Track track = new Track(); track.id = 777; track.title = "آهنگ تست"; track.artist = "Test";
        if (!prefs.isFavorite(track.id)) prefs.toggleFavorite(track);
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            activity.onActivity(a -> {
                a.findViewById(R.id.btnFavorites).performClick();
                ListView list = a.findViewById(R.id.listTracks);
                assertTrue(list.getAdapter().getCount() >= 1);
            });
        } finally { if (prefs.isFavorite(track.id)) prefs.toggleFavorite(track); }
    }

    @Test public void declaredMediaAndDownloadComponentsExist() throws Exception {
        Context c = context();
        ActivityInfo receiver = c.getPackageManager().getReceiverInfo(new ComponentName(c,
                com.soundcloudx.app.receiver.MediaBtnReceiver.class), 0);
        assertFalse(receiver.exported);
        ServiceInfo service = c.getPackageManager().getServiceInfo(new ComponentName(c, PlayerService.class), 0);
        assertFalse(service.exported);
        assertNotNull(c.getPackageManager().getServiceInfo(new ComponentName(c, DownloadService.class), 0));
        if (Build.VERSION.SDK_INT >= 29) assertTrue((service.getForegroundServiceType() & ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK) != 0);
    }

    @Test public void realAudioEngineLoadsLocalWav() throws Exception {
        Context c = context();
        File wav = new File(c.getCacheDir(), "smoke.wav");
        int length = 44100 * 2 * 2 * 2;
        ByteBuffer header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        header.put("RIFF".getBytes("US-ASCII")).putInt(length + 36).put("WAVEfmt ".getBytes("US-ASCII"))
                .putInt(16).putShort((short)1).putShort((short)2).putInt(44100).putInt(176400)
                .putShort((short)4).putShort((short)16).put("data".getBytes("US-ASCII")).putInt(length);
        try (OutputStream out = new FileOutputStream(wav)) { out.write(header.array()); out.write(new byte[length]); }
        CountDownLatch played = new CountDownLatch(1);
        ExoPlayer[] player = new ExoPlayer[1];
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
                player[0] = new ExoPlayer.Builder(c).build();
                player[0].addListener(new Player.Listener() {
                    @Override public void onIsPlayingChanged(boolean playing) { if (playing) played.countDown(); }
                });
                player[0].setMediaItem(MediaItem.fromUri(Uri.fromFile(wav)));
                player[0].prepare(); player[0].play();
            });
            assertTrue("bundled playback engine did not start", played.await(20, TimeUnit.SECONDS));
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
                player[0].pause(); player[0].seekTo(500); player[0].setVolume(0.5f);
                assertEquals(0.5f, player[0].getVolume(), 0.01f);
                player[0].play();
            });
        } finally {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> { if (player[0] != null) player[0].release(); });
            wav.delete();
        }
    }

    @Test public void scopedStorageAndFileSharingWork() throws Exception {
        Context c = context();
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.MediaColumns.DISPLAY_NAME, "scx-smoke.mp3");
            values.put(MediaStore.MediaColumns.MIME_TYPE, "audio/mpeg");
            values.put(MediaStore.MediaColumns.RELATIVE_PATH, "Music/SoundCloudX");
            values.put(MediaStore.MediaColumns.IS_PENDING, 1);
            Uri target = c.getContentResolver().insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values);
            assertNotNull(target);
            try {
                try (OutputStream out = c.getContentResolver().openOutputStream(target)) { assertNotNull(out); out.write("ID3test".getBytes()); }
                ContentValues published = new ContentValues(); published.put(MediaStore.MediaColumns.IS_PENDING, 0);
                assertEquals(1, c.getContentResolver().update(target, published, null, null));
            } finally { c.getContentResolver().delete(target, null, null); }
        } else {
            File dir = new File(Downloader.folderPath());
            assertTrue(dir.exists() || dir.mkdirs());
            File file = new File(dir, "scx-smoke.mp3");
            try {
                try (OutputStream out = new FileOutputStream(file)) { out.write("ID3test".getBytes()); }
                Uri uri = FileProvider.getUriForFile(c, c.getPackageName() + ".files", file);
                assertEquals("content", uri.getScheme());
            } finally { file.delete(); }
        }
    }
}
