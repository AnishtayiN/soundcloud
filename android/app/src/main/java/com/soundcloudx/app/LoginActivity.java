package com.soundcloudx.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.TextView;

/**
 * Sign in with the real SoundCloud website inside a WebView.
 *
 * SoundCloud answers the normal browser login with HTTP 302 responses that carry
 * the session cookies, so a plain WebView is enough - no embedded OAuth client
 * and no API keys of our own. As soon as the oauth_token cookie shows up we
 * flush the cookie store (needed by {@link ScApi}) and finish.
 */
public class LoginActivity extends Activity {

    private WebView webView;
    private ProgressBar progress;
    private TextView info;
    private boolean finished;

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(LocaleHelper.wrap(base));
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_login);

        webView = (WebView) findViewById(R.id.webView);
        progress = (ProgressBar) findViewById(R.id.loginProgress);
        info = (TextView) findViewById(R.id.txtLoginInfo);
        info.setText(R.string.menu_login);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(ScApi.UA);

        CookieManager.getInstance().setAcceptCookie(true);
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progress.setVisibility(View.VISIBLE);
                checkCookies();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
                checkCookies();
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progress.setVisibility(newProgress < 100 ? View.VISIBLE : View.GONE);
                checkCookies();
            }
        });

        webView.loadUrl("https://soundcloud.com/signin");
    }

    private void checkCookies() {
        if (finished) {
            return;
        }
        final String cookie = CookieManager.getInstance().getCookie("https://soundcloud.com");
        if (!TextUtils.isEmpty(cookie) && cookie.contains("oauth_token")) {
            finished = true;
            CookieManager.getInstance().flush();
            if (!ScApi.refreshCookies(this)) {
                finished = false;
                info.setText(R.string.error_storage);
                return;
            }
            ScLog.d("login successful");
            setResult(RESULT_OK, new Intent());
            // Give the cookie store a moment, then hand control back.
            webView.postDelayed(new Runnable() {
                @Override
                public void run() {
                    finish();
                }
            }, 350);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            setResult(RESULT_CANCELED);
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        ScApi.refreshCookies(this);
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
    }
}
