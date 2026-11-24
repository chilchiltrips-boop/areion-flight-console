package in.zebjus.areion;

import android.content.res.AssetManager;
import android.net.Uri;
import android.webkit.MimeTypeMap;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** Local APK assets have their original HTTPS module origin. No remote page gets the app bridge. */
final class PackagedConsole {
    static final String HOST = "chilchiltrips-boop.github.io";
    static final String PREFIX = "/areion-flight-console/";
    static final String START = "https://" + HOST + PREFIX + "index.html#flight";
    private final AssetManager assets;

    PackagedConsole(AssetManager assets) { this.assets = assets; }

    static boolean owns(Uri url) {
        if (url == null || !"https".equals(url.getScheme()) || !HOST.equals(url.getEncodedAuthority()))
            return false;
        String path = url.getPath();
        if (path == null || !path.startsWith(PREFIX) || path.indexOf('\\') >= 0 || path.indexOf('\0') >= 0)
            return false;
        for (String field : path.split("/")) if ("..".equals(field) || ".".equals(field)) return false;
        return true;
    }

    WebResourceResponse serve(WebResourceRequest request) {
        if (!owns(request.getUrl()) || !"GET".equalsIgnoreCase(request.getMethod())) return unavailable();
        String path = request.getUrl().getPath().substring(PREFIX.length());
        if (path.isEmpty() || path.endsWith("/")) path += "index.html";
        // The APK owns offline delivery; never install a web worker that can replace a packaged module.
        if (path.equals("offline-worker.js")) return unavailable();
        try {
            InputStream in = assets.open("console/" + path, AssetManager.ACCESS_STREAMING);
            int dot = path.lastIndexOf('.');
            String ext = dot < 0 ? "" : path.substring(dot + 1).toLowerCase(Locale.ROOT);
            String mime;
            switch (ext) {
                case "mjs": case "js": mime = "text/javascript"; break;
                case "css": mime = "text/css"; break;
                case "html": mime = "text/html"; break;
                case "webmanifest": case "json": mime = "application/json"; break;
                case "svg": mime = "image/svg+xml"; break;
                case "glb": mime = "model/gltf-binary"; break;
                case "gltf": mime = "model/gltf+json"; break;
                case "wasm": mime = "application/wasm"; break;
                case "mtl": case "obj": mime = "text/plain"; break;
                default: mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
            }
            if (mime == null) mime = "application/octet-stream";
            Map<String,String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-store");
            headers.put("X-Content-Type-Options", "nosniff");
            headers.put("Referrer-Policy", "no-referrer");
            String encoding = mime.startsWith("text/") || ext.equals("json") || ext.equals("svg") ? "UTF-8" : null;
            return new WebResourceResponse(mime, encoding, 200, "OK", headers, in);
        } catch (IOException e) {
            return unavailable();
        }
    }

    private static WebResourceResponse unavailable() {
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                java.util.Collections.singletonMap("Cache-Control","no-store"), new ByteArrayInputStream(new byte[0]));
    }
}
