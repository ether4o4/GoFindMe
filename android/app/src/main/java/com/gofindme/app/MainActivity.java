package com.gofindme.app;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final String URL = "http://127.0.0.1:8000/";
    private static final String HEALTH = URL + "api/health";
    private static final long STARTUP_TIMEOUT_MS = 60000L;
    private static final long RETRY_MS = 350L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService probeExecutor = Executors.newSingleThreadExecutor();
    private FrameLayout root;
    private WebView web;
    private LinearLayout loadingPanel;
    private ProgressBar spinner;
    private TextView statusText;
    private Button retryButton;
    private long startupStartedAt;
    private boolean serverReady;
    private boolean destroyed;
    private String pendingTarget;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setStatusBarColor(Color.rgb(8, 11, 16));
        getWindow().setNavigationBarColor(Color.rgb(8, 11, 16));
        pendingTarget = extractSharedText(getIntent());
        buildShell();
        startPythonServer();
    }

    private String extractSharedText(Intent intent) {
        if (intent == null) return null;
        String action = intent.getAction();
        if (Intent.ACTION_SEND.equals(action) || Intent.ACTION_PROCESS_TEXT.equals(action)) {
            String text = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (text != null) {
                text = text.trim();
                if (text.length() > 0 && text.length() <= 4096) return text;
            }
        }
        return null;
    }

    private String launchUrl() {
        if (pendingTarget == null || pendingTarget.isEmpty()) return URL;
        return Uri.parse(URL).buildUpon().appendQueryParameter("target", pendingTarget).build().toString();
    }

    private void buildShell() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(8, 11, 16));
        web = new WebView(this);
        configureWebView();
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));

        loadingPanel = new LinearLayout(this);
        loadingPanel.setOrientation(LinearLayout.VERTICAL);
        loadingPanel.setGravity(Gravity.CENTER_HORIZONTAL);
        loadingPanel.setPadding(dp(32), dp(32), dp(32), dp(32));
        loadingPanel.setBackgroundColor(Color.rgb(8, 11, 16));

        TextView mark = new TextView(this);
        mark.setText("⌕");
        mark.setTextColor(Color.rgb(45, 212, 167));
        mark.setTextSize(54);
        mark.setGravity(Gravity.CENTER);
        loadingPanel.addView(mark, new LinearLayout.LayoutParams(-1, dp(72)));

        TextView title = new TextView(this);
        title.setText("GoFindMe");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28);
        title.setGravity(Gravity.CENTER);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        loadingPanel.addView(title, new LinearLayout.LayoutParams(-1, dp(42)));

        TextView subtitle = new TextView(this);
        subtitle.setText("OSINT investigations console");
        subtitle.setTextColor(Color.rgb(155, 165, 180));
        subtitle.setTextSize(14);
        subtitle.setGravity(Gravity.CENTER);
        loadingPanel.addView(subtitle, new LinearLayout.LayoutParams(-1, dp(32)));

        spinner = new ProgressBar(this);
        spinner.setIndeterminate(true);
        LinearLayout.LayoutParams spinParams = new LinearLayout.LayoutParams(dp(44), dp(44));
        spinParams.gravity = Gravity.CENTER_HORIZONTAL;
        spinParams.topMargin = dp(26);
        loadingPanel.addView(spinner, spinParams);

        statusText = new TextView(this);
        statusText.setText("Starting local engine…");
        statusText.setTextColor(Color.rgb(155, 165, 180));
        statusText.setTextSize(14);
        statusText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, dp(54));
        statusParams.topMargin = dp(8);
        loadingPanel.addView(statusText, statusParams);

        retryButton = new Button(this);
        retryButton.setText("Retry");
        retryButton.setVisibility(View.GONE);
        retryButton.setOnClickListener(v -> startPythonServer());
        loadingPanel.addView(retryButton, new LinearLayout.LayoutParams(-2, dp(48)));
        root.addView(loadingPanel, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
    }

    private void configureWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) s.setSafeBrowsingEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " GoFindMeAndroid/2.0");

        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl().toString());
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && serverReady) {
                    Toast.makeText(MainActivity.this, "GoFindMe is temporarily unavailable. Retry from the page.", Toast.LENGTH_SHORT).show();
                }
            }
        });

        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                request.setTitle("GoFindMe report");
                request.setDescription("Downloading investigation report");
                request.setMimeType(mimeType);
                String cookies = CookieManager.getInstance().getCookie(url);
                if (cookies != null) request.addRequestHeader("Cookie", cookies);
                request.addRequestHeader("User-Agent", userAgent);
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                DownloadManager manager = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                manager.enqueue(request);
                Toast.makeText(this, "Download started", Toast.LENGTH_SHORT).show();
            } catch (Exception e) {
                Toast.makeText(this, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
    }

    private boolean handleUrl(String raw) {
        Uri uri = Uri.parse(raw);
        String scheme = uri.getScheme();
        if (scheme == null || "http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) return false;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (Exception e) { Toast.makeText(this, "No app can open that link", Toast.LENGTH_SHORT).show(); }
        return true;
    }

    private void startPythonServer() {
        if (destroyed) return;
        serverReady = false;
        retryButton.setVisibility(View.GONE);
        spinner.setVisibility(View.VISIBLE);
        statusText.setText("Starting local engine…");
        loadingPanel.setVisibility(View.VISIBLE);
        startupStartedAt = System.currentTimeMillis();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        Python.getInstance().getModule("android_main").callAttr("start", getFilesDir().getAbsolutePath());
        probeServer();
    }

    private void probeServer() {
        probeExecutor.execute(() -> {
            boolean ok = false;
            try {
                HttpURLConnection conn = (HttpURLConnection) new URL(HEALTH).openConnection();
                conn.setConnectTimeout(700);
                conn.setReadTimeout(900);
                conn.setRequestMethod("GET");
                ok = conn.getResponseCode() == 200;
                conn.disconnect();
            } catch (Exception ignored) { }
            final boolean ready = ok;
            handler.post(() -> {
                if (destroyed) return;
                if (ready) {
                    serverReady = true;
                    spinner.setVisibility(View.GONE);
                    statusText.setText("Ready");
                    handler.postDelayed(() -> {
                        if (!destroyed) { loadingPanel.setVisibility(View.GONE); web.loadUrl(launchUrl()); }
                    }, 120);
                } else if (System.currentTimeMillis() - startupStartedAt < STARTUP_TIMEOUT_MS) {
                    statusText.setText("Preparing local engine…");
                    handler.postDelayed(this::probeServer, RETRY_MS);
                } else {
                    spinner.setVisibility(View.GONE);
                    statusText.setText("The local engine did not start. Check storage, then retry.");
                    retryButton.setVisibility(View.VISIBLE);
                }
            });
        });
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
    @Override protected void onPause() { if (web != null) web.onPause(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() {
        destroyed = true;
        handler.removeCallbacksAndMessages(null);
        probeExecutor.shutdownNow();
        if (web != null) { web.stopLoading(); web.loadUrl("about:blank"); web.destroy(); web = null; }
        super.onDestroy();
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
