package com.soundcloudx.app;

import android.content.Context;
import android.content.res.Configuration;

import java.util.Locale;

/** Persian is the default, independently of the device locale. English is opt-in. */
public final class LocaleHelper {
    private LocaleHelper() { }

    public static Context wrap(Context context) {
        String language = Prefs.get(context).language();
        Locale locale = new Locale(language);
        Locale.setDefault(locale);
        Configuration configuration = new Configuration(context.getResources().getConfiguration());
        configuration.setLocale(locale);
        configuration.setLayoutDirection(locale);
        return context.createConfigurationContext(configuration);
    }
}
