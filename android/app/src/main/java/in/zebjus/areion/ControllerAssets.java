package in.zebjus.areion;

import android.content.res.AssetManager;
import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/** Serves the installed AP transmitter UI at the HTTPS origin accepted by the FC. */
final class ControllerAssets {
    private static final String PREFIX = "/areion-flight-console/controller/";
    static final String START = KitGateway.ORIGIN + PREFIX + "index.html";
    private static final Uri DOCUMENT = Uri.parse(START);
    private final AssetManager assets;

    ControllerAssets(AssetManager assets) {
        this.assets = assets;
    }

    static boolean isController(Uri url) {
        return DOCUMENT.equals(url);
    }

    WebResourceResponse serve(WebResourceRequest request) {
        Uri url = request.getUrl();
        String path = url.getPath();
        if (!"GET".equals(request.getMethod()) || !"https".equals(url.getScheme())
                || !DOCUMENT.getEncodedAuthority().equals(url.getEncodedAuthority())
                || path == null || !path.startsWith(PREFIX)
                || (request.isForMainFrame() && !isController(url))) return unavailable();

        String asset = path.substring(PREFIX.length());
        if (!asset.matches("(?:shared/)?[a-z0-9-]+\\.(?:html|js|css)")) return unavailable();
        String type = asset.endsWith(".js") ? "text/javascript" :
                asset.endsWith(".css") ? "text/css" : "text/html";
        try {
            InputStream stream = assets.open("controller/" + asset, AssetManager.ACCESS_STREAMING);
            Map<String, String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-store");
            headers.put("X-Content-Type-Options", "nosniff");
            return new WebResourceResponse(type, "UTF-8", 200, "OK", headers, stream);
        } catch (IOException missing) {
            return unavailable();
        }
    }

    private static WebResourceResponse unavailable() {
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                java.util.Collections.singletonMap("Cache-Control", "no-store"),
                new ByteArrayInputStream(new byte[0]));
    }
}
