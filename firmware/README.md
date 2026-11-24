# Areion FC A1 browser AP

The stock 3.2.0 sketch serves Areion Link v2 over serial and UDP. This optional sketch adds a WebSocket endpoint to the board for the published [Areion Flight Console](https://chilchiltrips-boop.github.io/areion-flight-console/). Existing boards can use the website over USB immediately.

## Install and connect

1. With propellers removed and the LiPo disconnected, open the web console's **Firmware** page in desktop Chrome or Edge. Connect an existing kit over USB for **Update via USB**, or choose **Install / recover board** for a new board. Reconnect after flashing to verify version 3.5.0.
2. Under **Kit Wi-Fi**, set the name and a password of 8–63 printable characters and click **Save Wi-Fi**. Restart on USB. A fresh stock installation enables its access point after this first configuration.
3. For a forgotten password, connect by USB and choose **Recover access → Restore Wi-Fi**. Save the generated password and restart. The default SSID is `aerion drone`. Previous flight and calibration settings are kept.
4. Wait for **Offline ready** in the header, join the kit’s network and choose **AP Wi-Fi → Find kit → Connect**. The default gateway is `ws://192.168.4.1:8081/areion`.

From firmware 3.4.0 onward, **Firmware → Update via AP Wi-Fi** writes the packaged application to the spare slot. Keep the kit on USB power with the LiPo disconnected and propellers removed. Hold BOOT while clicking the update button. Release it once writing starts. Reconnect after restart to confirm the installed version. A transfer interrupted before image verification keeps the current boot slot.

For an Arduino IDE build, use the two bundled libraries, the XIAO ESP32C6 board and Espressif Arduino core 3.3.7. Optional factory credentials in `AreionWifiConfig.h` apply until credentials are provisioned over USB. The release uses a 4 MB default OTA layout with two app slots. USB updates verify the spare slot before selecting it for the next boot. The settings partition is outside all installer writes.

The connection method in the header selects how the computer talks to the board. The flight input setting selects who controls the channels. Choose AP flight input on the kit to send channels over AP. Existing Python clients can still use UDP port 8080.

## How it works

The gateway accepts one browser from this repository owner's Pages origin on the kit’s AP interface. Its on-board UDP socket forwards the original checksummed Link frames to the flight controller's existing UDP port. The browser must complete the same HELLO handshake, own the session, and receive the controller’s acknowledgements. Selection, arming, output tests and saved settings use the original firmware handlers.

The web client polls every 20 ms, with one poll outstanding. The board issues short-lived send tickets in its replies. In 3.5.0, a late poll can resume telemetry on the same socket. The gateway discards the buffered telemetry after a long gap and ignores expired command tickets. Each joystick update still requires a fresh command and ticket. After three seconds without a gateway reply, the browser reports link loss. I/O runs in the HTTP server task. The flight loop does not call the WebSocket server. The browser sends during an active session only, and a recovered socket requires a new handshake. After an unexpected loss, the console can restore telemetry to the same board and the same FC boot, up to twice in 30 seconds. The sender stays off until started explicitly.

The `Compile browser AP firmware` workflow builds the complete sketch, Link library and RMT-based PPM decoder for the specified board. Wi-Fi range, RF loss, motor response and timing with real ESCs still require bench verification. Keep the propellers removed for setup and calibration.

Firmware 3.5.0 supports independent stationary gyro calibration. The console can start or cancel it through setup action 135 and read progress, result and active bias from group 142. The FC checks motion and a separate verification window before applying the new bias for this boot.
