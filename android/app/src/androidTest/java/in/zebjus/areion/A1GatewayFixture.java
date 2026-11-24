package in.zebjus.areion;

import android.content.Context;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.CRC32;
import javax.net.SocketFactory;

import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okio.ByteString;

import static in.zebjus.areion.AreionTouchInstrumentation.require;

/** The test socket connects only to 127.0.0.1. The production URI, WebSocket client and bytes stay intact. */
final class A1GatewayFixture extends WebSocketListener {
    private static final String ENDPOINT = "ws://192.168.4.1:8081/areion";
    private static final String CHANNELS = "[1600,1400,1000,1500,1000,1000,1500,2000]";
    private final BlockingQueue<String> requests = new LinkedBlockingQueue<>();
    private final AtomicReference<Throwable> failed = new AtomicReference<>();
    private byte[] pending = new byte[0];
    private int ticket;
    private boolean owner;

    static String exchange(Context context, byte[] hello, byte[] channelFrame) throws Exception {
        A1GatewayFixture peer = new A1GatewayFixture();
        InetAddress local = InetAddress.getByAddress(new byte[]{127, 0, 0, 1});
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().withWebSocketUpgrade(peer).setHeader("Sec-WebSocket-Protocol", "areion-link-v2"));
            server.start(local, 0);
            BlockingQueue<String[]> events = new LinkedBlockingQueue<>();
            KitGateway socket = new KitGateway(context, (id, type, value) -> {
                if (id == 7) events.add(new String[]{type, value});
            }, () -> new LocalSocketFactory(new InetSocketAddress(local, server.getPort())));
            try {
                require(!socket.open(7, ENDPOINT).isEmpty(), "Background socket accepted");
                socket.foreground(true);
                require(!socket.open(7, "ws://192.168.4.1:4210/areion").isEmpty(), "Legacy kit endpoint accepted");
                require(socket.open(7, ENDPOINT).isEmpty(), "A1 AP connection could not open");
                require(event(events, "open").equals("areion-link-v2"), "Upgrade negotiated the wrong version");
                RecordedRequest handshake = server.takeRequest(5, TimeUnit.SECONDS);
                require(handshake != null && "/areion".equals(handshake.getPath())
                        && "192.168.4.1:8081".equals(handshake.getHeader("Host"))
                        && "https://chilchiltrips-boop.github.io".equals(handshake.getHeader("Origin"))
                        && "areion-link-v2".equals(handshake.getHeader("Sec-WebSocket-Protocol")),
                        "Upgrade did not meet A1 gateway requirements");

                byte[] initial = poll(socket, events, 1);
                send(socket, 7, envelope(0x46, ticket(initial), hello));
                peer.expect("HELLO");
                byte[] ack = poll(socket, events, 2);
                require(decode(Arrays.copyOfRange(ack, 9, ack.length)).getString("type").equals("ACK"), "Missing HELLO ACK");
                byte[] command = envelope(0x46, ticket(ack), channelFrame);
                require(!socket.send(9, base64(command)), "Another session's write was accepted");
                send(socket, 7, command);
                peer.expect("CONTROL");
                byte[] echoed = poll(socket, events, 3);
                socket.foreground(false);
                require(!socket.send(7, base64(command)), "Stale channels accepted after app backgrounded");
                require(peer.failed.get() == null, "Loopback peer failed: " + peer.failed.get());
                return base64(Arrays.copyOfRange(echoed, 9, echoed.length));
            } finally { socket.destroy(); }
        }
    }

    @Override public void onMessage(WebSocket webSocket, ByteString message) {
        try {
            byte[] bytes = message.toByteArray();
            ByteBuffer data = ByteBuffer.wrap(bytes);
            int type = data.get() & 0xff;
            int sequence = data.getInt();
            if (type == 0x50) {
                require(!data.hasRemaining(), "Extra bytes in AP poll");
                byte[] reply = ByteBuffer.allocate(9 + pending.length).put((byte) 0x41)
                        .putInt(sequence).putInt(++ticket).put(pending).array();
                pending = new byte[0];
                require(webSocket.send(ByteString.of(reply)), "Could not write gateway reply");
                return;
            }
            require(type == 0x46 && sequence == ticket && ticket > 0, "Missing or stale AP ticket");
            JSONObject request = decode(Arrays.copyOfRange(bytes, 5, bytes.length));
            String name = request.getString("type");
            require(request.getInt("session") == 41 && request.getInt("v") == 2, "Wrong wire session/version");
            if (!owner) {
                require(name.equals("HELLO") && request.getInt("group") == 0 && request.getInt("seq") == 1, "Expected Link HELLO");
                pending = frame("{\"v\":2,\"type\":\"ACK\",\"group\":0,\"schema\":1,\"session\":41,\"seq\":1,\"data\":[\"HELLO\",67]}");
                owner = true;
            } else {
                require(name.equals("CONTROL") && request.getInt("group") == 9 && request.getInt("seq") == 2
                        && request.getInt("schema") == 1, "Expected group 9 control");
                JSONArray channels = request.getJSONArray("data");
                require(CHANNELS.equals(channels.toString()), "Wrong channel order or pulse values");
                pending = frame("{\"v\":2,\"type\":\"DATA\",\"group\":22,\"schema\":1,\"session\":67,\"seq\":2,\"data\":" + channels + "}");
            }
            requests.add(name);
        } catch (Throwable failure) {
            failed.set(failure);
            requests.add("ERROR");
            webSocket.cancel();
        }
    }

    private void expect(String type) throws Exception {
        String actual = requests.poll(5, TimeUnit.SECONDS);
        require(type.equals(actual), "Expected " + type + " from app, received " + actual + " (" + failed.get() + ")");
    }

    private static String event(BlockingQueue<String[]> events, String type) throws Exception {
        String[] result = events.poll(5, TimeUnit.SECONDS);
        require(result != null && result[0].equals(type), "Expected native " + type + ", got " + Arrays.toString(result));
        return result[1];
    }

    private static byte[] poll(KitGateway socket, BlockingQueue<String[]> events, int sequence) throws Exception {
        send(socket, 7, envelope(0x50, sequence, new byte[0]));
        byte[] reply = Base64.decode(event(events, "message"), Base64.DEFAULT);
        ByteBuffer header = ByteBuffer.wrap(reply);
        require(header.get() == 0x41 && header.getInt() == sequence && header.getInt() > 0, "Bad gateway poll reply");
        return reply;
    }

    private static int ticket(byte[] reply) { return ByteBuffer.wrap(reply).getInt(5); }
    private static String base64(byte[] value) { return Base64.encodeToString(value, Base64.NO_WRAP); }
    private static void send(KitGateway socket, int id, byte[] bytes) {
        require(socket.send(id, base64(bytes)), "Native socket refused current A1 data");
    }
    private static byte[] envelope(int kind, int token, byte[] body) {
        return ByteBuffer.allocate(5 + body.length).put((byte) kind).putInt(token).put(body).array();
    }
    private static byte[] frame(String json) {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        CRC32 crc = new CRC32();
        crc.update(body);
        return String.format(Locale.ROOT, "$%d:%s*%08X\n", body.length, json, crc.getValue()).getBytes(StandardCharsets.UTF_8);
    }
    private static JSONObject decode(byte[] bytes) throws Exception {
        String text = new String(bytes, StandardCharsets.UTF_8);
        String json = text.substring(text.indexOf(':') + 1, text.lastIndexOf('*'));
        require(Arrays.equals(bytes, frame(json)), "Invalid Areion payload length or CRC32");
        return new JSONObject(json);
    }

    /** Retains the production Host and Origin while routing the TCP socket exclusively to this test server. */
    private static final class LocalSocketFactory extends SocketFactory {
        private final InetSocketAddress loopback;
        LocalSocketFactory(InetSocketAddress loopback) { this.loopback = loopback; }
        @Override public Socket createSocket() {
            return new Socket() {
                @Override public void connect(SocketAddress target, int timeout) throws IOException {
                    InetSocketAddress address = (InetSocketAddress) target;
                    if (!"192.168.4.1".equals(address.getAddress().getHostAddress()) || address.getPort() != 8081)
                        throw new IOException("Unexpected outbound endpoint: " + target);
                    super.connect(loopback, timeout);
                }
            };
        }
        @Override public Socket createSocket(String host, int port) throws IOException { throw new IOException("Use routed socket"); }
        @Override public Socket createSocket(String host, int port, InetAddress source, int sourcePort) throws IOException { throw new IOException("Use routed socket"); }
        @Override public Socket createSocket(InetAddress host, int port) throws IOException { throw new IOException("Use routed socket"); }
        @Override public Socket createSocket(InetAddress host, int port, InetAddress source, int sourcePort) throws IOException { throw new IOException("Use routed socket"); }
    }
}
