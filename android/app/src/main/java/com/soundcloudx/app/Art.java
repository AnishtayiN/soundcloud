package com.soundcloudx.app;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.text.TextUtils;
import android.util.LruCache;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/** Cover art loader: memory cache -> disk cache -> network. */
public final class Art {

    private static final LruCache<String, Bitmap> MEM = new LruCache<String, Bitmap>(96) {
        @Override
        protected int sizeOf(String key, Bitmap value) {
            return value == null ? 0 : value.getByteCount() / 1024;
        }
    };

    private Art() {
    }

    public interface Callback {
        void ready(Bitmap bitmap);
    }

    public static File cacheDir(android.content.Context ctx) {
        File dir = new File(ctx.getCacheDir(), "art");
        if (!dir.exists() && !dir.mkdirs()) {
            ScLog.e("cannot create art cache dir");
        }
        return dir;
    }

    public static Bitmap memory(String url) {
        return TextUtils.isEmpty(url) ? null : MEM.get(key(url));
    }

    /** Loads a cover. Callback always runs on the UI thread and may receive null. */
    public static void load(final android.content.Context ctx, final String url, final Callback cb) {
        if (TextUtils.isEmpty(url)) {
            if (cb != null) {
                cb.ready(null);
            }
            return;
        }
        Bitmap cached = MEM.get(key(url));
        if (cached != null) {
            if (cb != null) {
                cb.ready(cached);
            }
            return;
        }
        Bg.run(new Bg.Job<Bitmap>() {
            @Override
            public Bitmap run() throws Exception {
                File f = new File(cacheDir(ctx), key(url) + ".jpg");
                if (!f.exists()) {
                    download(url, f);
                }
                return decode(f);
            }
        }, new Bg.Then<Bitmap>() {
            @Override
            public void done(Bitmap value, Exception error) {
                if (value != null) {
                    MEM.put(key(url), value);
                }
                if (cb != null) {
                    cb.ready(value);
                }
            }
        });
    }

    private static void download(String url, File target) throws Exception {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(12000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", ScApi.UA);
            if (c.getResponseCode() >= 400) {
                throw new java.io.IOException("HTTP " + c.getResponseCode());
            }
            InputStream in = c.getInputStream();
            FileOutputStream out = new FileOutputStream(target);
            try {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
            } finally {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
                try {
                    in.close();
                } catch (Exception ignored) {
                }
            }
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    private static Bitmap decode(File f) {
        try {
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inPreferredConfig = Bitmap.Config.ARGB_8888;
            return BitmapFactory.decodeFile(f.getAbsolutePath(), o);
        } catch (Throwable t) {
            return null;
        }
    }

    /** Frees up space, newest files are kept. */
    public static void trimCache(android.content.Context ctx, int keep) {
        try {
            File dir = cacheDir(ctx);
            File[] files = dir.listFiles();
            if (files == null || files.length <= keep) {
                return;
            }
            List<File> list = new ArrayList<>(Arrays.asList(files));
            java.util.Collections.sort(list, new Comparator<File>() {
                @Override
                public int compare(File a, File b) {
                    return Long.compare(a.lastModified(), b.lastModified());
                }
            });
            for (int i = 0; i < list.size() - keep; i++) {
                //noinspection ResultOfMethodCallIgnored
                list.get(i).delete();
            }
        } catch (Throwable ignored) {
        }
    }

    public static void clearMemory() {
        MEM.evictAll();
    }

    private static String key(String url) {
        int hash = url.hashCode();
        return (hash == Integer.MIN_VALUE ? Integer.MAX_VALUE : Math.abs(hash)) + "-" + url.length();
    }
}
