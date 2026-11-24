package in.zebjus.areion;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Collections;

/** Standalone, bundled PC simulator controller. There is no native kit bridge in this WebView. */
public final class SimulatorActivity extends Activity {
    private static final String HOST = "simulator.areion.invalid";
    private static final String ENTRY = "https://" + HOST + "/index.html";
    private static final int CAMERA_REQUEST = 28;
    private WebView web;
    private PermissionRequest camera;
    private boolean webPaused;

    private static boolean local(Uri uri) {
        return "https".equals(uri.getScheme()) && HOST.equals(uri.getHost())
                && uri.getPort() == -1 && uri.getUserInfo() == null;
    }

    private static WebResourceResponse denied() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
                Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        web = new WebView(this);
        web.setKeepScreenOn(true);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !ENTRY.equals(request.getUrl().toString());
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                // The optional six-digit signaling broker is the sole external HTTP origin.
                if (!local(uri)) {
                    boolean broker = "https".equals(uri.getScheme()) && "0.peerjs.com".equals(uri.getHost())
                            && (uri.getPort() == -1 || uri.getPort() == 443) && uri.getUserInfo() == null;
                    return !request.isForMainFrame() && broker ? null : denied();
                }
                String path = uri.getEncodedPath();
                if (!"GET".equals(request.getMethod()) || path == null || !path.matches("/[A-Za-z0-9._/-]+")
                        || path.contains("..") || path.contains("//")) return denied();
                String type = path.endsWith(".html") ? "text/html" : path.endsWith(".js") ? "application/javascript"
                        : path.endsWith(".css") ? "text/css" : "text/plain";
                try {
                    InputStream input = getAssets().open("simulator" + path);
                    return new WebResourceResponse(type, "UTF-8", input);
                } catch (IOException missing) {
                    return denied();
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                if (!local(request.getOrigin()) || camera != null ||
                        !Arrays.asList(request.getResources()).contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) {
                    request.deny();
                    return;
                }
                if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                } else {
                    camera = request;
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_REQUEST);
                }
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) {
                if (camera == request) camera = null;
            }
        });
        setContentView(web);
        web.loadUrl(ENTRY);
    }

    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code != CAMERA_REQUEST || camera == null) return;
        PermissionRequest pending = camera;
        camera = null;
        if (!isFinishing() && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            pending.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        } else {
            pending.deny();
        }
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN);
    }

    private void pauseWeb() {
        if (web == null || webPaused) return;
        web.evaluateJavascript("window.zebjusAppPaused && window.zebjusAppPaused()", null);
        web.onPause();
        webPaused = true;
    }

    @Override protected void onPause() {
        if (camera == null) pauseWeb(); // Android's camera permission sheet also pauses the activity.
        super.onPause();
    }

    @Override protected void onStop() {
        pauseWeb();
        super.onStop();
    }

    @Override protected void onResume() {
        super.onResume();
        if (web != null && webPaused) web.onResume();
        webPaused = false;
    }

    @Override protected void onDestroy() {
        if (camera != null) camera.deny();
        camera = null;
        if (web != null) {
            if (web.getParent() instanceof ViewGroup) ((ViewGroup) web.getParent()).removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
