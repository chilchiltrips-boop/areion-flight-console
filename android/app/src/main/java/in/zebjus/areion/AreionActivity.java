package in.zebjus.areion;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
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
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONObject;

public class AreionActivity extends Activity {
    private WebView browser;
    private KitGateway gateway;
    private volatile boolean active;
    private volatile boolean trusted;

    @Override @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        gateway = new KitGateway(getApplicationContext(), this::socketEvent);
        ControllerAssets site = new ControllerAssets(getAssets());
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
                return !req.isForMainFrame() || !ControllerAssets.isController(req.getUrl());
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                trusted = ControllerAssets.isController(Uri.parse(url));
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
        browser.loadUrl(ControllerAssets.START);
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
        finish();
    }
    @Override protected void onDestroy() {
        active = false;
        trusted = false;
        gateway.destroy();
        if (browser != null) {
            browser.removeJavascriptInterface("AreionAndroid");
            browser.destroy();
        }
        super.onDestroy();
    }
}
