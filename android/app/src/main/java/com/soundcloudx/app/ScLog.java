package com.soundcloudx.app;

import android.content.Context;
import android.util.Log;

import java.io.File;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Date;
import java.util.Deque;
import java.util.List;
import java.util.Locale;

/** Tiny in-app + on-disk log so a user can report a broken build. */
public final class ScLog {

    private static final String TAG = "SoundCloudX";
    private static final int MAX_LINES = 400;
    private static final Deque<String> LINES = new ArrayDeque<>();
    private static final SimpleDateFormat TIME =
            new SimpleDateFormat("HH:mm:ss", Locale.US);

    private ScLog() {
    }

    public static void d(String msg) {
        Log.d(TAG, msg);
        add(msg);
    }

    public static void e(String msg) {
        Log.e(TAG, msg);
        add("ERROR " + msg);
    }

    public static void e(String msg, Throwable t) {
        Log.e(TAG, msg, t);
        add("ERROR " + msg + ": " + (t == null ? "" : t.getClass().getSimpleName()
                + " " + t.getMessage()));
    }

    private static void add(String msg) {
        synchronized (LINES) {
            LINES.addLast(TIME.format(new Date()) + "  " + msg);
            while (LINES.size() > MAX_LINES) {
                LINES.removeFirst();
            }
        }
    }

    public static List<String> lines() {
        synchronized (LINES) {
            return new ArrayList<>(LINES);
        }
    }

    public static void clear() {
        synchronized (LINES) {
            LINES.clear();
        }
    }

    public static void writeToFile(Context ctx) {
        File dir = new File(ctx.getExternalFilesDir(null), "logs");
        if (!dir.exists() && !dir.mkdirs()) {
            return;
        }
        File out = new File(dir, "soundcloudx-log.txt");
        FileWriter w = null;
        try {
            w = new FileWriter(out, false);
            for (String line : lines()) {
                w.write(line);
                w.write('\n');
            }
        } catch (Exception ignored) {
        } finally {
            if (w != null) {
                try {
                    w.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    public static File logFile(Context ctx) {
        return new File(new File(ctx.getExternalFilesDir(null), "logs"), "soundcloudx-log.txt");
    }
}
