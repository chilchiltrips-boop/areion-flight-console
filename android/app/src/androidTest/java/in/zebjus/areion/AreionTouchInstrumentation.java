package in.zebjus.areion;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Runs against the installed APK. The only kit endpoint used by the test is a loopback peer. */
public final class AreionTouchInstrumentation extends Instrumentation {
    private static final String PAD_LEFT = "[data-pad=left]";
    private static final String PAD_RIGHT = "[data-pad=right]";
    private static final String STOP = "[data-deck-action=stop]";
    private static final String NEUTRAL = "[1500,1500,1000,1500]";
    private Bundle arguments;
    private WebView web;
    private long gestureStart;

    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        arguments = args;
        start();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context = getTargetContext();
            if (arguments != null && "true".equals(arguments.getString("requireOffline"))) {
                ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
                NetworkCapabilities caps = cm.getNetworkCapabilities(cm.getActiveNetwork());
                require(caps == null || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED),
                        "Disable emulator data and Wi-Fi for the offline acceptance run");
            }
            Intent intent = new Intent().setClassName(context, "in.zebjus.areion.AreionActivity")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            final Activity started = startActivitySync(intent);
            runOnMainSync(() -> web = findWeb(started.getWindow().getDecorView()));
            require(web != null, "A1 cockpit has no WebView");
            waitFor("document.querySelector('.a1-touch-deck')?.getBoundingClientRect().width>0", 60000);
            waitFor("document.hasFocus() && location.origin==='https://chilchiltrips-boop.github.io'");
            testTouch();
            byte[][] messages = encodeWithPackagedConsole();
            String telemetry = A1GatewayFixture.exchange(context, messages[0], messages[1]);
            checkReturnedChannels(telemetry);
            runOnMainSync(started::finish);
            result.putString("stream", "PASS Areion Android: packaged touch deck, simultaneous fingers, "
                    + "throttle latch, cancel, third-finger stop, offline preview, "
                    + "A1 WebSocket handshake, HELLO, CONTROL and FC channel readback.\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            String diagnostic;
            try {
                diagnostic = js("JSON.stringify({url:location.href,title:document.title,"
                        + "ready:document.readyState,body:document.body.innerText.slice(0,650)})");
            } catch (Throwable unavailable) { diagnostic = "WebView unavailable"; }
            Log.e("AreionAcceptance", "Android check failed", failure);
            result.putString("stream", "FAIL Areion Android: " + Log.getStackTraceString(failure) + "\n" + diagnostic + "\n");
            result.putString("shortMsg", failure.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private void testTouch() throws Exception {
        js("window.__pulses=()=>['roll','pitch','throttle','yaw'].map(k=>parseInt(document"
                + ".querySelector('.a1-touch-deck [data-channel='+k+']').textContent,10));true");
        waitFor("JSON.stringify(__pulses())==='" + NEUTRAL + "'");
        waitFor("document.querySelector('[data-deck-action=send]').disabled"
                + " && document.querySelector('[data-deck-action=arm]').disabled && typeof AreionNativeSocket==='function'");
        js("window.__socketOpens=0;window.__originalSocket=window.AreionNativeSocket;"
                + "window.AreionNativeSocket=class{constructor(){__socketOpens++;throw Error('Socket attempted during preview')}};"
                + "window.__trustedTouches=0;addEventListener('pointerdown',e=>{"
                + "if(e.isTrusted && e.pointerType==='touch')__trustedTouches++},true);true");

        float[] left = point(PAD_LEFT, .38, .64);
        float[] leftMove = point(PAD_LEFT, .61, .32);
        float[] right = point(PAD_RIGHT, .40, .65);
        float[] rightMove = point(PAD_RIGHT, .68, .34);
        float[] stop = point(STOP, .5, .5);
        touch(MotionEvent.ACTION_DOWN, new int[]{0}, left);
        touch(pointer(MotionEvent.ACTION_POINTER_DOWN, 1), new int[]{0, 1}, left, right);
        waitFor("__trustedTouches===2 && JSON.stringify(__pulses())==='" + NEUTRAL + "'");
        touch(MotionEvent.ACTION_MOVE, new int[]{0, 1}, leftMove, rightMove);
        waitFor("__pulses()[0]>1520 && __pulses()[1]>1520 && __pulses()[2]>1030 && __pulses()[3]>1520");

        // Releasing the left thumb must not release the right thumb. Throttle stays where released.
        touch(pointer(MotionEvent.ACTION_POINTER_UP, 0), new int[]{0, 1}, leftMove, rightMove);
        waitFor("__pulses()[0]>1520 && __pulses()[1]>1520 && __pulses()[3]===1500");
        String held = js("__pulses()[2]");
        touch(MotionEvent.ACTION_CANCEL, new int[]{1}, rightMove);
        waitFor("__pulses()[0]===1500 && __pulses()[1]===1500 && __pulses()[2]===" + held);
        // This pause allows multiple animation frames to detect an accidentally continuing throttle ramp.
        SystemClock.sleep(250);
        require(held.equals(js("__pulses()[2]")), "Released throttle kept moving");

        touch(MotionEvent.ACTION_DOWN, new int[]{0}, left);
        touch(pointer(MotionEvent.ACTION_POINTER_DOWN, 1), new int[]{0, 1}, left, right);
        touch(MotionEvent.ACTION_MOVE, new int[]{0, 1}, leftMove, rightMove);
        waitFor("__pulses()[0]>1520 && __pulses()[3]>1520");
        touch(pointer(MotionEvent.ACTION_POINTER_DOWN, 2), new int[]{0, 1, 2}, leftMove, rightMove, stop);
        waitFor("JSON.stringify(__pulses())==='" + NEUTRAL + "'");
        touch(pointer(MotionEvent.ACTION_POINTER_UP, 2), new int[]{0, 1, 2}, leftMove, rightMove, stop);
        touch(MotionEvent.ACTION_MOVE, new int[]{0, 1}, left, right);
        touch(MotionEvent.ACTION_CANCEL, new int[]{0, 1}, left, right);
        waitFor("JSON.stringify(__pulses())==='" + NEUTRAL + "' && __trustedTouches===5");
        waitFor("__socketOpens===0 && document.querySelector('[data-deck-action=send]').disabled"
                + " && document.querySelector('#frames').textContent.trim()==='0 packets'");
        js("window.AreionNativeSocket=window.__originalSocket;true");
    }

    private byte[][] encodeWithPackagedConsole() throws Exception {
        js("import('./protocol.js').then(p=>{window.__fwProtocol=p;"
                + "const base64=v=>btoa(String.fromCharCode(...v));window.__a1messages=["
                + "base64(p.encodeRequest('HELLO',0,1,41,1)),"
                + "base64(p.encodeCommand('CONTROL',9,41,2,[1600,1400,1000,1500,1000,1000,1500,2000]))]"
                + "});true");
        waitFor("Array.isArray(window.__a1messages)");
        JSONArray values = new JSONArray(js("__a1messages"));
        return new byte[][]{android.util.Base64.decode(values.getString(0), android.util.Base64.DEFAULT),
                android.util.Base64.decode(values.getString(1), android.util.Base64.DEFAULT)};
    }

    private void checkReturnedChannels(String encoded) throws Exception {
        String result = js("(()=>{const bytes=Uint8Array.from(atob(" + JSONObject.quote(encoded)
                + "),c=>c.charCodeAt(0));const [reply]=new __fwProtocol.FrameDecoder().push(bytes);"
                + "return reply && reply.type==='DATA' && reply.group===22 && reply.session===67"
                + " && JSON.stringify(reply.data)==='[1600,1400,1000,1500,1000,1000,1500,2000]'})()");
        require("true".equals(result), "Bundled decoder did not accept echoed A1 channels");
    }

    private WebView findWeb(View view) {
        if (view instanceof WebView) return (WebView) view;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                WebView result = findWeb(group.getChildAt(i));
                if (result != null) return result;
            }
        }
        return null;
    }

    private String js(String script) throws Exception {
        if (web == null) throw new AssertionError("No activity WebView");
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<String> answer = new AtomicReference<>();
        runOnMainSync(() -> web.evaluateJavascript(script, response -> { answer.set(response); ready.countDown(); }));
        require(ready.await(20, TimeUnit.SECONDS), "No WebView response");
        return answer.get();
    }

    private void waitFor(String condition) throws Exception {
        waitFor(condition, 15000);
    }

    private void waitFor(String condition, long timeoutMillis) throws Exception {
        long end = SystemClock.uptimeMillis() + timeoutMillis;
        while (SystemClock.uptimeMillis() < end) {
            if ("true".equals(js("Boolean(" + condition + ")"))) return;
            SystemClock.sleep(70);
        }
        throw new AssertionError("Did not observe " + condition);
    }

    private float[] point(String selector, double rx, double ry) throws Exception {
        String found = js("(()=>{const el=document.querySelector(" + JSONObject.quote(selector) + ");"
                + "const r=el.getBoundingClientRect(),x=r.x+r.width*" + rx + ",y=r.y+r.height*" + ry + ";"
                + "return [x,y,el.contains(document.elementFromPoint(x,y)),innerWidth]})()");
        JSONArray rect = new JSONArray(found);
        require(rect.getBoolean(2), selector + " is obscured");
        int[] origin = new int[3];
        runOnMainSync(() -> { web.getLocationOnScreen(origin); origin[2] = web.getWidth(); });
        double scale = origin[2] / rect.getDouble(3);
        return new float[]{origin[0] + (float) (rect.getDouble(0) * scale),
                origin[1] + (float) (rect.getDouble(1) * scale)};
    }

    private static int pointer(int action, int index) {
        return action | (index << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
    }

    private void touch(int action, int[] ids, float[]... positions) {
        long now = SystemClock.uptimeMillis();
        if (action == MotionEvent.ACTION_DOWN) gestureStart = now;
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[ids.length];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[ids.length];
        for (int i = 0; i < ids.length; i++) {
            properties[i] = new MotionEvent.PointerProperties();
            properties[i].id = ids[i];
            properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[i] = new MotionEvent.PointerCoords();
            coords[i].x = positions[i][0];
            coords[i].y = positions[i][1];
            coords[i].pressure = 1;
            coords[i].size = .15f;
        }
        MotionEvent event = MotionEvent.obtain(gestureStart, now, action, ids.length, properties, coords,
                0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            require(getUiAutomation().injectInputEvent(event, true), "Android rejected touch");
        } finally { event.recycle(); }
    }

    static void require(boolean condition, String detail) {
        if (!condition) throw new AssertionError(detail);
    }
}
