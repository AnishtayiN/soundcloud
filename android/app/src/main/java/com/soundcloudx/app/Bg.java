package com.soundcloudx.app;

import android.os.Handler;
import android.os.Looper;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Very small helper that runs work on a background pool and delivers the
 * result back on the main (UI) thread.
 */
public final class Bg {

    public static final ExecutorService POOL = Executors.newFixedThreadPool(4);
    public static final Handler MAIN = new Handler(Looper.getMainLooper());

    private Bg() {
    }

    public interface Job<T> {
        T run() throws Exception;
    }

    public interface Then<T> {
        void done(T value, Exception error);
    }

    public static <T> void run(final Job<T> job, final Then<T> then) {
        POOL.execute(new Runnable() {
            @Override
            public void run() {
                T value = null;
                Exception error = null;
                try {
                    value = job.run();
                } catch (Exception e) {
                    error = e;
                }
                if (then != null) {
                    final T resultValue = value;
                    final Exception resultError = error;
                    MAIN.post(new Runnable() {
                        @Override
                        public void run() {
                            then.done(resultValue, resultError);
                        }
                    });
                }
            }
        });
    }

    public static void post(Runnable r) {
        MAIN.post(r);
    }

    public static void postDelayed(Runnable r, long delayMs) {
        MAIN.postDelayed(r, delayMs);
    }
}
