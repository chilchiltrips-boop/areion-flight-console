# PC simulator controller

Open **PC simulator pairing** in the Android console to use the landscape touch controller with the DroneLab desktop simulator. Open the desktop pairing panel, scan or paste its offer, and confirm the matching code. The optional six-digit reply uses an internet signaling service. Two-way QR and manual text work when both devices can reach each other on the same local network. The desktop selects whether the phone mirrors joystick input or requests simulator control. Android Back returns to the A1 console.

The simulator uses its own bundled WebView origin and WebRTC data channels. Its only optional external HTTPS/WebSocket destination is the short-code broker. The QR camera is accessed on demand and supports the torch on devices that expose it. The primary console handles all physical controller traffic through Areion Link v2.

## Source and build

The asset preparer reads DroneLab revision `0101b6d77ed9750633baf991664f8fce274da8f6`. The file list in `prepare.py` contains the original joystick mathematics, QR, short-code and RTC support, styles and third-party notices. Local `assets/` adapts the cockpit, touch handlers and pairing messages for the PC simulator. The Gradle build packages these under `assets/simulator/`. No upstream native Android classes are included.

Gradle fetches the pinned inputs during the build. Setting `DRONELAB_SOURCE` to a local Git checkout containing that revision also works. The installed APK includes the complete controller.

To run the isolated desktop-pairing and multitouch tests after a Gradle build, run this at the repository root with Node 22 or newer.

```sh
SIMULATOR_ASSETS="$PWD/android/app/build/generated/areionAssets/simulator" node --test android/legacy/tests/simulator.test.mjs
```

Set `DRONELAB_HOST_PAIRING_JS` to the original desktop `pairing-core.js` to exercise the pinned desktop peer against the Android implementation. The tests substitute an in-memory data channel for WebRTC networking.
