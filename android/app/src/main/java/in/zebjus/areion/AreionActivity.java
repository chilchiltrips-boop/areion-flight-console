package in.zebjus.areion;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONObject;

public class AreionActivity extends Activity {
    private static final int OPEN_INPUT = 6211;
    private WebView browser;
    private KitGateway gateway;
    private DocumentExport export;
    private ValueCallback<Uri[]> fileInput;
    private volatile boolean active;
    private volatile boolean trusted;

    @Override @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        export = new DocumentExport(this);
        gateway = new KitGateway(getApplicationContext(), this::socketEvent);
        PackagedConsole site = new PackagedConsole(getAssets());
        browser = new WebView(this);
        setContentView(browser);
        browser.setFocusableInTouchMode(true);
        browser.requestFocus();
        immersive();
        WebSettings settings = browser.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        browser.addJavascriptInterface(new MobileBridge(), "AreionAndroid");
        browser.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                return site.serve(req);
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return !PackagedConsole.owns(req.getUrl());
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                trusted = PackagedConsole.owns(Uri.parse(url));
            }
            @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                trusted = false;
                gateway.foreground(false);
                view.removeJavascriptInterface("AreionAndroid");
                if (view.getParent() instanceof android.view.ViewGroup)
                    ((android.view.ViewGroup) view.getParent()).removeView(view);
                view.destroy();
                browser = null;
                recreate();
                return true;
            }
        });
        browser.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> result, FileChooserParams params) {
                if (!permitted()) return false;
                if (fileInput != null) fileInput.onReceiveValue(null);
                fileInput = result;
                Intent open = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,
                        new String[]{"text/csv", "text/plain", "application/csv", "application/octet-stream"});
                try { startActivityForResult(open, OPEN_INPUT); }
                catch (ActivityNotFoundException error) { fileInput.onReceiveValue(null); fileInput = null; }
                return true;
            }
        });
        // A new process always starts with a disarmed local touch preview.
        browser.loadUrl(PackagedConsole.START);
    }

    private boolean permitted() { return active && trusted; }

    @SuppressWarnings("deprecation")
    private void immersive() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController controls = getWindow().getInsetsController();
            if (controls != null) {
                controls.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controls.hide(WindowInsets.Type.systemBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    private void socketEvent(int id, String type, String message) {
        String script = "window.AreionNativeSocket&&window.AreionNativeSocket.receive(" + id + ","
                + JSONObject.quote(type) + "," + JSONObject.quote(message) + ")";
        runOnUiThread(() -> {
            if (browser != null && trusted && !isDestroyed()) browser.evaluateJavascript(script, null);
        });
    }

    public final class MobileBridge {
        @JavascriptInterface public String openSocket(int id, String endpoint) {
            return permitted() ? gateway.open(id, endpoint) : "Open the app before connecting.";
        }
        @JavascriptInterface public boolean sendSocket(int id, String encoded) { return permitted() && gateway.send(id, encoded); }
        @JavascriptInterface public long queuedSocket(int id) { return gateway.queued(id); }
        @JavascriptInterface public void closeSocket(int id) { gateway.close(id); }

        @JavascriptInterface public void haptic(String kind) {
            if (!permitted()) return;
            runOnUiThread(() -> {
                if (browser == null || !permitted()) return;
                int effect = HapticFeedbackConstants.CLOCK_TICK;
                if ("stop".equals(kind)) effect = HapticFeedbackConstants.LONG_PRESS;
                else if ("confirm".equals(kind)) effect = Build.VERSION.SDK_INT >= 30
                    ? HapticFeedbackConstants.CONFIRM : HapticFeedbackConstants.VIRTUAL_KEY;
                browser.performHapticFeedback(effect);
            });
        }
        @JavascriptInterface public void openWifiSettings() {
            if (!permitted()) return;
            runOnUiThread(() -> {
                if (!permitted()) return;
                try { startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS)); }
                catch (ActivityNotFoundException e) {
                    Toast.makeText(AreionActivity.this,"Open Wi-Fi in Android Settings.",Toast.LENGTH_SHORT).show();
                }
            });
        }
        @JavascriptInterface public void openSimulator() {
            if (!permitted()) return;
            runOnUiThread(() -> {
                if (permitted()) startActivity(new Intent(AreionActivity.this, SimulatorActivity.class));
            });
        }

        @JavascriptInterface public int beginExport(String name, int size) { return permitted() ? export.begin(name, size) : 0; }
        @JavascriptInterface public boolean appendExport(int token, String data) { return permitted() && export.append(token,data); }
        @JavascriptInterface public boolean finishExport(int token) { return permitted() && export.finish(token); }
        @JavascriptInterface public void cancelExport(int token) { export.cancel(token); }
        @JavascriptInterface public boolean copyText(String text) {
            if (!permitted() || text == null || text.length() > 131072) return false;
            try {
                ClipboardManager clipboard = (ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);
                clipboard.setPrimaryClip(ClipData.newPlainText("Areion diagnostics", text));
                return true;
            } catch (RuntimeException e) { return false; }
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request,result,data);
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        if (request == DocumentExport.REQUEST) export.selected(uri);
        if (request == OPEN_INPUT && fileInput != null) {
            fileInput.onReceiveValue(uri != null && "content".equals(uri.getScheme()) ? new Uri[]{uri} : null);
            fileInput = null;
        }
    }
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) immersive();
    }
    @Override protected void onResume() {
        super.onResume();
        active = true;
        gateway.foreground(true);
        if (browser != null) browser.onResume();
        immersive();
    }
    @Override protected void onPause() {
        active = false;
        if (browser != null) {
            browser.evaluateJavascript("window.dispatchEvent(new Event('areion-app-pause'));window.dispatchEvent(new Event('blur'))", null);
            browser.onPause();
        }
        gateway.foreground(false);
        super.onPause();
    }
    @Override public void onBackPressed() {
        if (browser != null && browser.canGoBack()) browser.goBack();
        else super.onBackPressed();
    }
    @Override protected void onDestroy() {
        active = false;
        trusted = false;
        gateway.destroy();
        export.clear();
        if (fileInput != null) fileInput.onReceiveValue(null);
        if (browser != null) {
            browser.removeJavascriptInterface("AreionAndroid");
            browser.destroy();
        }
        super.onDestroy();
    }
}
