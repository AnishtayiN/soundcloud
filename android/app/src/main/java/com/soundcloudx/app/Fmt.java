package com.soundcloudx.app;

import java.text.DecimalFormat;
import java.util.Locale;

/** Small formatting helpers used by the lists and the player. */
public final class Fmt {

    private static final DecimalFormat ONE = new DecimalFormat("0.#");

    private Fmt() {
    }

    /** 1234 -> "1.2K", 4567890 -> "4.6M" */
    public static String plays(long n) {
        if (n <= 0) {
            return "";
        }
        if (n < 1000) {
            return String.valueOf(n);
        }
        if (n < 1000000) {
            return ONE.format(n / 1000.0) + "K";
        }
        if (n < 1000000000L) {
            return ONE.format(n / 1000000.0) + "M";
        }
        return ONE.format(n / 1000000000.0) + "B";
    }

    /** SoundCloud answers are usually 100 chars/second. */
    public static long dasMs(int dasDuration) {
        return dasDuration <= 0 ? 0 : dasDuration * 1000L / 100L;
    }

    public static String bytes(long b) {
        if (b <= 0) {
            return "";
        }
        String[] units = {"B", "KB", "MB", "GB"};
        double v = b;
        int i = 0;
        while (v >= 1024 && i < units.length - 1) {
            v /= 1024;
            i++;
        }
        return String.format(Locale.US, "%.1f %s", v, units[i]);
    }

    /** Keeps only characters that are safe in a file name. */
    public static String safeFileName(String name) {
        if (name == null) {
            return "track";
        }
        StringBuilder sb = new StringBuilder(name.length());
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (Character.isLetterOrDigit(c) || c == ' ' || c == '-' || c == '_'
                    || c == '(' || c == ')' || c == '[' || c == ']' || c == '\''
                    || c == '&' || c == ',' || c == '.' || c == '+' || c == '#') {
                sb.append(c);
            } else if (c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' || c == '"'
                    || c == '<' || c == '>' || c == '|') {
                sb.append('_');
            }
        }
        String out = sb.toString().trim();
        while (out.contains("  ")) {
            out = out.replace("  ", " ");
        }
        if (out.length() > 110) {
            out = out.substring(0, 110).trim();
        }
        return out.isEmpty() ? "track" : out;
    }
}
