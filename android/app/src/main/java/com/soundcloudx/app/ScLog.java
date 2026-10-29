package com.soundcloudx.app;

import android.content.Context;
import android.util.Log;

import java.io.File;
import java.io.FileWriter;
import java.net.URI;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Date;
import java.util.Deque;
import java.util.List;
import java.util.Locale;

/** Bounded diagnostics. Query strings, authorization headers and cookies are never logged. */
public final class ScLog {
    private static final String TAG = "SoundCloudX";
    private static final int MAX_LINES = 400;
    private static final Deque<String> LINES = new ArrayDeque<>();
    private static final SimpleDateFormat TIME = new SimpleDateFormat("HH:mm:ss", Locale.US);

    private ScLog() { }

    /** Keep the operation/address, but discard queries (which may contain OAuth tokens). */
    public static String safeUrl(String value) {
        if (value == null) {
            return "";
        }
        try {
            URI uri = new URI(value);
            if (uri.getScheme() == null || uri.getHost() == null) {
                return "[local resource]";
            }
            String path = uri.getRawPath();
            if (path != null) {
                path = path.replaceAll("(?i)/s-[A-Za-z0-9_-]+", "/[private]");
            }
            return uri.getScheme() + "://" + uri.getHost() + (path == null ? "" : path);
        } catch (Exception error) {
            return "[invalid address]";
        }
    }

    public static String safe(String message) {
        if (message == null) {
            return "";
        }
        String clean = message.replaceAll("(?i)(oauth_token|track_authorization|client_id|access_token)=([^&\\s;,]+)", "$1=[redacted]");
        clean = clean.replaceAll("(?i)(authorization|cookie)\\s*[:=]\\s*[^\\r\\n]+", "$1: [redacted]");
        clean = clean.replaceAll("(https?://[^\\s?#]+)\\?[^\\s]+", "$1?[redacted]");
        return clean;
    }

    public static void d(String message) {
        String clean = safe(message);
        Log.d(TAG, clean);
        add(clean);
    }

    public static void e(String message) {
        String clean = safe(message);
        Log.e(TAG, clean);
        add("ERROR " + clean);
    }

    public static void e(String message, Throwable error) {
        // Do not pass the original throwable to Logcat: HTTP exceptions often
        // embed the complete request URL, including oauth_token, in their message.
        String detail = error == null ? "" : " (" + error.getClass().getSimpleName()
                + ": " + safe(error.getMessage()) + ")";
        e(message + detail);
    }

    public static void failed(String operation, String address, Throwable error) {
        e(operation + " failed: " + safeUrl(address), error);
    }

    private static void add(String message) {
        synchronized (LINES) {
            LINES.addLast(TIME.format(new Date()) + "  " + message);
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
            e("cannot create log directory");
            return;
        }
        File out = new File(dir, "soundcloudx-log.txt");
        try (FileWriter writer = new FileWriter(out, false)) {
            for (String line : lines()) {
                writer.write(line);
                writer.write('\n');
            }
        } catch (Exception error) {
            e("cannot write or close log file", error);
        }
    }

    public static File logFile(Context ctx) {
        return new File(new File(ctx.getExternalFilesDir(null), "logs"), "soundcloudx-log.txt");
    }
}
