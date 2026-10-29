package com.soundcloudx.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.text.TextUtils;
import android.util.LruCache;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/** Bounded cover cache. Files are published only after a complete transfer. */
public final class Art {
    public static final int MEMORY_BUDGET = 8 * 1024 * 1024;
    private static final int MAX_FILE_BYTES = 20 * 1024 * 1024;
    private static final int MAX_DIMENSION = 512;
    private static final LruCache<String, Bitmap> MEM = new LruCache<String, Bitmap>(MEMORY_BUDGET) {
        @Override
        protected int sizeOf(String key, Bitmap value) {
            return value == null ? 0 : value.getAllocationByteCount();
        }
    };

    private Art() { }

    public interface Callback {
        void ready(Bitmap bitmap);
    }

    public static File cacheDir(Context ctx) {
        File dir = new File(ctx.getCacheDir(), "art");
        if (!dir.exists() && !dir.mkdirs()) {
            ScLog.e("cannot create art cache directory");
        }
        return dir;
    }

    public static Bitmap memory(String url) {
        return TextUtils.isEmpty(url) ? null : MEM.get(key(url));
    }

    public static int memoryBytes() {
        return MEM.size();
    }

    public static void load(final Context ctx, final String url, final Callback callback) {
        if (TextUtils.isEmpty(url)) {
            if (callback != null) {
                callback.ready(null);
            }
            return;
        }
        Bitmap cached = memory(url);
        if (cached != null) {
            if (callback != null) {
                callback.ready(cached);
            }
            return;
        }
        final Context app = ctx.getApplicationContext();
        Bg.run(new Bg.Job<Bitmap>() {
            @Override
            public Bitmap run() throws Exception {
                File target = new File(cacheDir(app), key(url) + ".jpg");
                Bitmap bitmap = target.exists() ? decode(target) : null;
                if (bitmap == null) {
                    delete(target);
                    download(url, target);
                    bitmap = decode(target);
                    if (bitmap == null) {
                        delete(target);
                    }
                }
                return bitmap;
            }
        }, new Bg.Then<Bitmap>() {
            @Override
            public void done(Bitmap value, Exception error) {
                if (error != null) {
                    ScLog.failed("load cover", url, error);
                }
                if (value != null) {
                    MEM.put(key(url), value);
                }
                if (callback != null) {
                    callback.ready(value);
                }
            }
        });
    }

    private static void download(String url, File target) throws Exception {
        File part = File.createTempFile(key(url) + "-", ".part", target.getParentFile());
        HttpURLConnection connection = null;
        boolean complete = false;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setConnectTimeout(12000);
            connection.setReadTimeout(15000);
            connection.setRequestProperty("User-Agent", ScApi.UA);
            connection.setRequestProperty("Accept-Encoding", "identity");
            int status = connection.getResponseCode();
            if (status >= 400) {
                throw new java.io.IOException("HTTP " + status);
            }
            long expected = connection.getContentLengthLong();
            long total = 0;
            try (InputStream input = connection.getInputStream();
                 FileOutputStream output = new FileOutputStream(part)) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > MAX_FILE_BYTES) {
                        throw new java.io.IOException("cover exceeds size limit");
                    }
                    output.write(buffer, 0, count);
                }
                output.getFD().sync();
            }
            if (total == 0 || (expected >= 0 && total != expected)) {
                throw new java.io.IOException("incomplete cover download");
            }
            if (!part.renameTo(target)) {
                throw new java.io.IOException("cannot publish cover cache file");
            }
            complete = true;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
            if (!complete) {
                delete(part);
            }
        }
    }

    private static Bitmap decode(File file) {
        try {
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(file.getAbsolutePath(), bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
                return null;
            }
            int sample = 1;
            while (bounds.outWidth / sample > MAX_DIMENSION
                    || bounds.outHeight / sample > MAX_DIMENSION) {
                sample *= 2;
            }
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inSampleSize = sample;
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            return BitmapFactory.decodeFile(file.getAbsolutePath(), options);
        } catch (OutOfMemoryError error) {
            ScLog.e("cover decode exceeded memory budget", error);
            return null;
        } catch (Exception error) {
            ScLog.e("cannot decode cover", error);
            return null;
        }
    }

    private static void delete(File file) {
        if (file.exists() && !file.delete()) {
            ScLog.e("cannot remove incomplete or invalid cover cache");
        }
    }

    public static void trimCache(Context ctx, int keep) {
        File[] files = cacheDir(ctx).listFiles();
        if (files == null || files.length <= keep) {
            return;
        }
        List<File> list = new ArrayList<>(Arrays.asList(files));
        java.util.Collections.sort(list, new Comparator<File>() {
            @Override
            public int compare(File first, File second) {
                return Long.compare(first.lastModified(), second.lastModified());
            }
        });
        for (int i = 0; i < list.size() - keep; i++) {
            delete(list.get(i));
        }
    }

    public static void clearMemory() {
        MEM.evictAll();
    }

    private static String key(String url) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(url.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder();
            for (int i = 0; i < 16; i++) {
                result.append(String.format(java.util.Locale.US, "%02x", hash[i]));
            }
            return result.toString();
        } catch (Exception error) {
            throw new IllegalStateException("SHA-256 unavailable", error);
        }
    }
}
