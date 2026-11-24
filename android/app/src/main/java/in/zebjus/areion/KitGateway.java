package in.zebjus.areion;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.util.Base64;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.Proxy;
import java.net.URI;
import java.util.Collections;
import java.util.concurrent.TimeUnit;

import javax.net.SocketFactory;

import okhttp3.OkHttpClient;
import okhttp3.Protocol;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/** One explicitly opened socket, bound directly to the kit WLAN even when cellular is Android's default. */
final class KitGateway {
    interface Listener {
        void event(int id, String type, String value);
    }

    interface Route { SocketFactory socketFactory(); }

    static final String HOST = "192.168.4.1";
    static final String PROTOCOL = "areion-link-v2";
    static final String ORIGIN = "https://chilchiltrips-boop.github.io";
    private static final int MAX_WRITE = 5 + 1552;
    private static final int MAX_READ = 9 + 4 * 1552;
    private final ConnectivityManager networks;
    private final Listener listener;
    private final Route route;
    private final OkHttpClient base = new OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY)
            .protocols(Collections.singletonList(Protocol.HTTP_1_1))
            .retryOnConnectionFailure(false)
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(5, TimeUnit.SECONDS)
            .build();
    private boolean foreground;
    private boolean watching;
    private int activeId;
    private Network selected;
    private WebSocket socket;

    KitGateway(Context context, Listener listener) {
        this(context, listener, null);
    }

    KitGateway(Context context, Listener listener, Route route) {
        networks = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        this.listener = listener;
        this.route = route != null ? route : () -> {
            selected = findWifi();
            return selected == null ? null : selected.getSocketFactory();
        };
    }

    private final ConnectivityManager.NetworkCallback changes = new ConnectivityManager.NetworkCallback() {
        @Override public void onLost(Network net) {
            synchronized (KitGateway.this) {
                if (net.equals(selected)) abort("Kit Wi-Fi disconnected.");
            }
        }
    };

    synchronized void foreground(boolean value) {
        foreground = value;
        if (value && !watching) {
            try {
                networks.registerNetworkCallback(new NetworkRequest.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), changes);
                watching = true;
            } catch (RuntimeException ignored) { /* Socket errors still report an unavailable link. */ }
        } else if (!value) {
            abort("App left foreground.");
            if (watching) {
                try { networks.unregisterNetworkCallback(changes); } catch (RuntimeException ignored) { }
                watching = false;
            }
        }
    }

    private static boolean kitEndpoint(String endpoint) {
        try {
            URI uri = URI.create(endpoint);
            return "ws".equals(uri.getScheme()) && HOST.equals(uri.getHost()) && uri.getPort() == 8081
                && "/areion".equals(uri.getRawPath()) && uri.getRawUserInfo() == null
                && uri.getRawQuery() == null && uri.getRawFragment() == null;
        } catch (RuntimeException e) { return false; }
    }

    private boolean routesToKit(Network candidate) {
        if (candidate == null) return false;
        NetworkCapabilities caps = networks.getNetworkCapabilities(candidate);
        LinkProperties props = networks.getLinkProperties(candidate);
        if (caps == null || props == null || !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                || caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return false;
        // Require an on-link Wi-Fi IPv4 subnet. A cellular/VPN/default internet route is insufficient.
        byte[] target = {(byte) 192, (byte) 168, 4, 1};
        for (LinkAddress address : props.getLinkAddresses()) {
            InetAddress ip = address.getAddress();
            if (!(ip instanceof Inet4Address)) continue;
            int prefix = address.getPrefixLength();
            if (prefix <= 0 || prefix > 32) continue;
            byte[] local = ip.getAddress();
            boolean match = true;
            for (int i = 0; i < 4 && match; i++) {
                int bits = Math.min(8, Math.max(0, prefix - 8 * i));
                int mask = (0xff << (8 - bits)) & 0xff;
                match = ((local[i] ^ target[i]) & mask) == 0;
            }
            if (match) return true;
        }
        return false;
    }

    @SuppressWarnings("deprecation") // Lists non-default, local-only WLANs as well as Android's default network.
    private Network findWifi() {
        Network active = networks.getActiveNetwork();
        if (routesToKit(active)) return active;
        for (Network candidate : networks.getAllNetworks()) if (routesToKit(candidate)) return candidate;
        return null;
    }

    static Request request(String endpoint) {
        return new Request.Builder().url(endpoint)
                .header("Origin", ORIGIN).header("Sec-WebSocket-Protocol", PROTOCOL).build();
    }

    synchronized String open(int id, String endpoint) {
        if (id <= 0 || !foreground) return "Open the app before connecting.";
        if (!kitEndpoint(endpoint)) return "Use ws://192.168.4.1:8081/areion for the kit AP.";
        if (socket != null) return "Another kit socket is still closing.";
        try {
            SocketFactory wifi = route.socketFactory();
            if (wifi == null) return "Join the kit Wi-Fi in Android settings, then tap Connect.";
            OkHttpClient client = base.newBuilder().socketFactory(wifi).build();
            Request request = request(endpoint);
            activeId = id;
            socket = client.newWebSocket(request, new WebSocketListener() {
                @Override public void onOpen(WebSocket ws, Response response) {
                    synchronized (KitGateway.this) {
                        if (!current(ws,id)) { ws.cancel(); return; }
                        if (!PROTOCOL.equals(response.header("Sec-WebSocket-Protocol"))) {
                            abort("Kit rejected the Areion Link v2 protocol."); return;
                        }
                        listener.event(id, "open", PROTOCOL);
                    }
                }
                @Override public void onMessage(WebSocket ws, ByteString bytes) {
                    synchronized (KitGateway.this) {
                        if (!current(ws,id)) return;
                        if (bytes.size() < 9 || bytes.size() > MAX_READ) {
                            abort("Invalid AP gateway reply."); return;
                        }
                        listener.event(id, "message", bytes.base64());
                    }
                }
                @Override public void onMessage(WebSocket ws, String message) {
                    synchronized (KitGateway.this) {
                        if (current(ws,id)) abort("Unexpected AP gateway text.");
                    }
                }
                @Override public void onClosing(WebSocket ws, int code, String reason) {
                    ws.close(1000, null);
                }
                @Override public void onClosed(WebSocket ws, int code, String reason) {
                    ended(ws, id, "close", Integer.toString(code));
                }
                @Override public void onFailure(WebSocket ws, Throwable error, Response response) {
                    ended(ws, id, "error", "Kit Wi-Fi connection ended.");
                }
            });
            return "";
        } catch (RuntimeException failure) {
            activeId = 0; selected = null; socket = null;
            return "Could not open the kit Wi-Fi connection.";
        }
    }

    private boolean current(WebSocket ws, int id) { return socket == ws && activeId == id; }

    private synchronized void ended(WebSocket ws, int id, String type, String msg) {
        if (!current(ws,id)) return;
        activeId = 0; selected = null; socket = null;
        listener.event(id, type, msg);
    }

    synchronized boolean send(int id, String encoded) {
        if (!foreground || id != activeId || socket == null || encoded == null
                || encoded.length() > (MAX_WRITE + 2) / 3 * 4 || socket.queueSize() > MAX_WRITE) return false;
        try {
            byte[] bytes = Base64.decode(encoded, Base64.NO_WRAP);
            if (bytes.length < 5 || bytes.length > MAX_WRITE) return false;
            boolean poll = bytes[0] == 0x50 && bytes.length == 5;
            boolean frame = bytes[0] == 0x46 && bytes.length > 5 && bytes[5] == '$' && bytes[bytes.length-1] == '\n';
            return (poll || frame) && socket.send(ByteString.of(bytes));
        } catch (IllegalArgumentException e) { return false; }
    }

    synchronized long queued(int id) { return id == activeId && socket != null ? socket.queueSize() : 0; }

    synchronized void close(int id) {
        if (id != activeId || socket == null) return;
        // cancel() discards any queued control frames. A new socket always needs a new FC handshake.
        WebSocket old = socket;
        activeId = 0; selected = null; socket = null;
        old.cancel();
        listener.event(id, "close", "1000");
    }

    private void abort(String why) {
        if (socket == null) return;
        int id = activeId;
        WebSocket old = socket;
        activeId = 0; selected = null; socket = null;
        old.cancel();
        listener.event(id, "error", why);
    }

    synchronized void destroy() {
        foreground(false);
        base.dispatcher().cancelAll();
        base.dispatcher().executorService().shutdown();
        base.connectionPool().evictAll();
    }
}
