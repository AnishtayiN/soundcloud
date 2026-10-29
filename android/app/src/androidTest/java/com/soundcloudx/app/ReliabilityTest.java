package com.soundcloudx.app;

import android.Manifest;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Build;
import android.view.KeyEvent;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.By;
import androidx.test.uiautomator.UiDevice;
import androidx.test.uiautomator.Until;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.io.FileOutputStream;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okio.Buffer;

import static org.junit.Assert.*;

/** Deterministic, offline device smoke test. No SoundCloud account or live CDN required. */
@RunWith(AndroidJUnit4.class)
public class ReliabilityTest {
    private Context context;
    private MockWebServer server;
    private UiDevice device;
    private byte[] wav;
    private String packageName;

    @Before public void setUp() throws Exception {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        packageName = context.getPackageName();
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        if (Build.VERSION.SDK_INT >= 33) {
            InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(
                    "pm grant " + packageName + " android.permission.POST_NOTIFICATIONS").close();
        }
        if (Build.VERSION.SDK_INT < 29) {
            InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(
                    "pm grant " + packageName + " android.permission.WRITE_EXTERNAL_STORAGE").close();
        }
        // PCM WAV is decodable by Android 7 through 16 without a codec download.
        int samples = 22050 * 8;
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        int size = samples * 2;
        bytes.write(new byte[]{'R','I','F','F', (byte)(size+36), (byte)((size+36)>>8),
                (byte)((size+36)>>16), (byte)((size+36)>>24), 'W','A','V','E','f','m','t',' ',
                16,0,0,0, 1,0,1,0, 0x22,0x56,0,0, 0x44,(byte)0xac,0,0, 2,0,16,0,
                'd','a','t','a', (byte)size,(byte)(size>>8),(byte)(size>>16),(byte)(size>>24)});
        for (int i=0; i<samples; i++) {
            int value = (int)(Math.sin(i * 2 * Math.PI * 220 / 22050) * 1000);
            bytes.write(value & 255); bytes.write((value >> 8) & 255);
        }
        wav = bytes.toByteArray();
        server = new MockWebServer();
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                String path = request.getPath();
                if (path.contains("q=stale-old")) {
                    try { Thread.sleep(3000); }
                    catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                }
                if (path.endsWith(".wav")) {
                    return new MockResponse().setHeader("Content-Type", "audio/wav")
                            .setHeader("Content-Length", wav.length).setBody(new Buffer().write(wav));
                }
                if (path.contains("/art.png")) {
                    Bitmap bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888);
                    bitmap.eraseColor(0xffff5500);
                    java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
                    bitmap.recycle();
                    return new MockResponse().setHeader("Content-Type", "image/png")
                            .setBody(new Buffer().write(output.toByteArray()));
                }
                if (path.contains("/stream/progressive")) {
                    return new MockResponse().setResponseCode(302)
                            .setHeader("Location", server.url("/audio.wav").toString());
                }
                String id = path.contains("222") || path.contains("q=stale-old") ? "222" : "111";
                String title = id.equals("111") ? "آهنگ آزمایشی" : "آهنگ دوم";
                String track = "{\"id\":" + id + ",\"title\":\"" + title
                        + "\",\"duration\":8000,\"streamable\":true,\"downloadable\":true,"
                        + "\"policy\":\"ALLOW\",\"track_authorization\":\"fixture-auth\","
                        + "\"download_url\":\"" + server.url("/audio.wav") + "\","
                        + "\"permalink_url\":\"https://soundcloud.com/test/track\","
                        + "\"artwork_url\":\"" + server.url("/art.png") + "\","
                        + "\"user\":{\"username\":\"خواننده آزمایشی\"}}";
                String body = path.contains("/charts") || path.contains("/search/")
                        ? "{\"collection\":[" + track + "]}" : track;
                return new MockResponse().setHeader("Content-Type", "application/json").setBody(body);
            }
        });
        server.start();
        ScApi.setTestEndpoints(server.url("/").toString(), server.url("").toString(), server.url("").toString());
        ScApi.clearClientId(context);
        Prefs.get(context).setLanguage("fa");
        Prefs.get(context).saveLastQuery("");
        Prefs.get(context).setAllowRoaming(false);
        for (Track track : Prefs.get(context).favorites()) {
            Prefs.get(context).removeFavorite(track.id);
        }
        JSONArray downloads = Prefs.get(context).downloads();
        for (int i=0; i<downloads.length(); i++) {
            Prefs.get(context).removeDownload(downloads.getJSONObject(i).getLong("id"));
        }
    }

    @After public void tearDown() throws Exception {
        PlayerService player = PlayerService.get();
        if (player != null) {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(player::stop);
        }
        if (server != null) server.shutdown();
    }

    private void waitForState(int state) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(25);
        while (System.nanoTime() < deadline) {
            PlayerService service = PlayerService.get();
            if (service != null && service.getState() == state) return;
            Thread.sleep(100);
        }
        PlayerService service = PlayerService.get();
        fail("expected state " + state + ", got " + (service == null ? "no service" : service.getState() + " " + service.getMessage()));
    }

    private void click(String resourceId) {
        assertNotNull("missing " + resourceId,
                device.wait(Until.findObject(By.res(packageName, resourceId)), 15000));
        device.findObject(By.res(packageName, resourceId)).click();
        device.waitForIdle();
    }

    @Test public void persianSearchPlayPauseDownloadFavoriteAndRestart() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            device.waitForIdle();
            assertTrue(device.wait(Until.hasObject(By.text("جستجو")), 15000));
            scenario.onActivity(activity -> {
                assertEquals(ViewDirectionRtl(), activity.getWindow().getDecorView().getLayoutDirection());
                assertEquals("fa", activity.prefs.language());
                assertFalse(activity.prefs.allowRoaming());
            });
            assertNotNull(device.wait(Until.findObject(By.text("آهنگ آزمایشی")), 20000));
            device.findObject(By.res(packageName, "editSearch")).setText("آهنگ");
            click("btnSearch");
            assertNotNull(device.wait(Until.findObject(By.text("آهنگ آزمایشی")), 20000));
            device.findObject(By.text("آهنگ آزمایشی")).click();
            waitForState(PlayerService.STATE_PLAYING);
            click("btnPlayPause");
            waitForState(PlayerService.STATE_PAUSED);
            click("btnPlayPause");
            waitForState(PlayerService.STATE_PLAYING);
            click("btnFav");
            assertTrue(Prefs.get(context).isFavorite(111));
            Track favorite = Prefs.get(context).favorites().get(0);
            assertEquals("fixture-auth", favorite.trackAuth);
            assertTrue(favorite.downloadUrl.endsWith("/audio.wav"));

            click("btnDownload");
            assertNotNull(device.wait(Until.findObject(By.text("دانلود MP3 (128kbps)")), 10000));
            device.findObject(By.text("دانلود MP3 (128kbps)")).click();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(35);
            JSONObject record = null;
            while (System.nanoTime() < deadline) {
                JSONArray items = Prefs.get(context).downloads();
                if (items.length() > 0) record = items.getJSONObject(0);
                if (record != null && !"running".equals(record.optString("status"))) break;
                Thread.sleep(200);
            }
            assertNotNull("download not recorded", record);
            assertEquals("download: " + record, "done", record.optString("status"));
            assertEquals("audio/x-wav", record.optString("mime"));
            long downloadId = record.getLong("id");
            Track track = new Track(); track.id = 111; track.title = "آهنگ آزمایشی";
            Downloader.Result duplicate = Downloader.enqueue(context, track, server.url("/audio.wav").toString(), false);
            assertTrue(duplicate.duplicate);
            assertEquals(downloadId, duplicate.downloadId);

            // Media button dispatch uses the same manifest receiver as the session.
            Intent button = new Intent(Intent.ACTION_MEDIA_BUTTON).setComponent(
                    new ComponentName(context, com.soundcloudx.app.receiver.MediaBtnReceiver.class));
            button.putExtra(Intent.EXTRA_KEY_EVENT, new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_MEDIA_PAUSE));
            context.sendBroadcast(button);
            waitForState(PlayerService.STATE_PAUSED);
            File screenshot = new File(context.getExternalFilesDir(null),
                    "smoke-fa-" + Build.VERSION.SDK_INT + ".png");
            device.takeScreenshot(screenshot);
        }
        try (ActivityScenario<MainActivity> ignored = ActivityScenario.launch(MainActivity.class)) {
            click("btnFavorites");
            assertNotNull(device.wait(Until.findObject(By.text("آهنگ آزمایشی")), 15000));
            assertTrue(Prefs.get(context).isFavorite(111));
            assertEquals("done", Prefs.get(context).downloads().getJSONObject(0).getString("status"));
        }
    }

    @Test public void focusDenialLeavesLoadingAndReportsPersianError() throws Exception {
        android.media.AudioManager audio = (android.media.AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        android.media.AudioAttributes attributes = new android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_MEDIA)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_MUSIC).build();
        android.media.AudioFocusRequest hold = null;
        boolean held;
        if (Build.VERSION.SDK_INT >= 26) {
            hold = new android.media.AudioFocusRequest.Builder(android.media.AudioManager.AUDIOFOCUS_GAIN)
                    .setAudioAttributes(attributes).setAcceptsDelayedFocusGain(false).build();
            held = audio.requestAudioFocus(hold) == android.media.AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        } else {
            held = audio.requestAudioFocus(null, android.media.AudioManager.STREAM_MUSIC,
                    android.media.AudioManager.AUDIOFOCUS_GAIN) == android.media.AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        }
        assertTrue(held);
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
                Track track = new Track(); track.id = 111; track.title = "آهنگ آزمایشی"; track.streamable = true;
                PlayerService player = new PlayerService();
                player.onCreate();
                player.playAll(java.util.Collections.singletonList(track), 0);
            });
            waitForState(PlayerService.STATE_ERROR);
            assertEquals(context.getString(R.string.error_audio_focus), PlayerService.get().getMessage());
        } finally {
            if (Build.VERSION.SDK_INT >= 26) audio.abandonAudioFocusRequest(hold);
            else audio.abandonAudioFocus(null);
        }
    }

    @Test public void staleSearchCannotOverwriteNewerSearch() throws Exception {
        try (ActivityScenario<MainActivity> ignored = ActivityScenario.launch(MainActivity.class)) {
            assertNotNull(device.wait(Until.findObject(By.res(packageName, "editSearch")), 15000));
            device.findObject(By.res(packageName, "editSearch")).setText("stale-old");
            click("btnSearch");
            device.findObject(By.res(packageName, "editSearch")).setText("stale-new");
            click("btnSearch");
            assertNotNull(device.wait(Until.findObject(By.text("آهنگ آزمایشی")), 15000));
            Thread.sleep(3500);
            assertNull("late old response replaced the newer rows", device.findObject(By.text("آهنگ دوم")));
            assertNotNull(device.findObject(By.text("آهنگ آزمایشی")));
        }
    }

    private int ViewDirectionRtl() { return android.view.View.LAYOUT_DIRECTION_RTL; }
}
