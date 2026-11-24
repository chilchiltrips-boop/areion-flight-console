# Areion Flight Console for Android

The Android app opens on the two-stick transmitter in landscape. It includes the Areion FC A1 console, F450 assembly, setup wizard, IMU and ESC calibration, PID controls, scopes, recordings and firmware update over the kit AP. The console, models and matching firmware are installed with the APK and available offline.

## Connect to an Areion FC A1

1. Join the kit Wi-Fi in Android Settings. If Android asks whether to keep using this network without internet, keep the connection.
2. Open the app and tap **Connect AP**. The phone opens the FC's existing WebSocket gateway at `ws://192.168.4.1:8081/areion`. The socket uses the kit Wi-Fi even when cellular data is enabled.
3. With the kit disarmed, select **Use AP input** if the FC is set to PPM or USB. Tap **Start sender** with the sticks neutral. The shared console verifies the FC's channel readback before showing the sender as ready.
4. Use **Console** to open setup, live channels, PID, diagnostics, scopes or firmware. Use **Touch deck** to return. On Android, the Firmware page updates an AP-capable kit over Wi-Fi. Initial USB installation and USB Wi-Fi recovery are available on the desktop console.

Areion FC A1 browser AP firmware 3.5.0 supports this app. All physical kit communication uses Areion Link v2 with the same device session, frame encoding, eight-channel mapping, command acknowledgments and telemetry as the web console. Kit settings and input selection are shared across clients.

## Touch controls

- Touch anywhere inside a pad to set its centre. Each pad tracks its own finger. The left pad changes throttle and yaw. Throttle holds when released, yaw returns to centre. The right pad controls pitch and roll and springs back when released.
- **Slow**, **Medium** and **Fast** set stick response and throttle ramp speed. The phone remembers the selected response.
- Use a third finger to tap **STOP** while both sticks are held. The deck shows the FC's reported arm state, attitude and channel feedback. Offline, the sticks provide local practice. Returning from another app requires a fresh, explicit control session.
- **PC simulator pairing** opens a separate controller for the DroneLab PC simulator. It supports QR and manual offer/answer, optional online short-code pairing and two-thumb input. Only the simulator uses this pairing channel. The A1 kit always uses Areion Link v2.

## Build

Use JDK 17, Android SDK 35, Node 22 and Python 3. From the repository root run:

```sh
npm ci --ignore-scripts
npm test
android/gradlew -p android :app:assembleDebug :app:assembleDebugAndroidTest
python3 android/scripts/verify-apk.py android/app/build/outputs/apk/debug/app-debug.apk
```

The first build stages a pinned set of DroneLab simulator assets and downloads the published A1 firmware if a local `build/firmware-release` is missing. The packaging step compares that release's bundled firmware sources to this checkout and verifies its asset checksums. For a local build with a pre-existing DroneLab Git checkout, set `DRONELAB_SOURCE` to its path. The installed APK needs no internet for the A1 connection.

The preview package is `in.zebjus.areion.console.preview` (Android 8.0+ with a current Android System WebView). It installs alongside DroneLab. Development APKs use a debug signature. Retain your own signing key for installations that require in-place updates across releases.
