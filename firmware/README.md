# Areion FC A1 browser AP

The stock 3.2.0 sketch serves Areion Link v2 over serial and UDP. This optional sketch adds a WebSocket endpoint to the board for the published [Areion Flight Console](https://chilchiltrips-boop.github.io/areion-flight-console/). Existing boards can use the website over USB immediately.

## Install for AP Wi-Fi

1. Extract the repository. Copy the two folders inside `firmware/libraries/` to your Arduino sketchbook's `libraries/` folder. Both contain the Areion project’s original C++ libraries. Use one installed copy of each.
2. Open `firmware/AreionBrowserAP/AreionBrowserAP.ino` in Arduino IDE and select the XIAO ESP32C6 board with your usual USB settings. The CI build uses Espressif’s Arduino core 3.3.7.
3. Set a private Wi-Fi password of 8–63 characters in `AreionWifiConfig.h`. The default empty value leaves the AP off. Keep your configured password in your local sketch.
4. With propellers removed, upload over USB. The firmware reports version 3.2.0 to the existing clients and uses the existing settings keys. Upload using the board’s normal flash settings to retain saved data.
5. Open the GitHub Pages console while online. Join the kit’s Wi-Fi, select **AP Wi-Fi** in the header, then connect to `ws://192.168.4.1:8081/areion` and allow the browser's local network permission when prompted. Recent desktop Chrome and Edge with Local Network Access support can connect from HTTPS to this private IP. Open the published site in the same browser profile used to grant permission.

The connection method in the header selects how the computer talks to the board. The flight input setting selects who controls the channels. Choose AP flight input on the kit to send channels over AP. Existing Python clients can still use UDP port 8080.

## How it works

The gateway accepts one browser from this repository owner's Pages origin on the kit’s AP interface. Its on-board UDP socket forwards the original checksummed Link frames to the flight controller's existing UDP port. The browser must complete the same HELLO handshake, own the session, and receive the controller’s acknowledgements. Selection, arming, output tests and saved settings use the original firmware handlers.

The web client polls every 20 ms, with one poll outstanding. The board issues short-lived send tickets in its replies. It drops expired sends and closes stalled connections, preventing old joystick frames from resuming control after Wi-Fi recovers. I/O runs in the HTTP server task. The flight loop does not call the WebSocket server. The browser sends during an active session only, and reconnecting requires a new handshake.

The `Compile browser AP firmware` workflow builds the complete sketch, Link library and RMT-based PPM decoder for the specified board. Wi-Fi range, RF loss, motor response and timing with real ESCs still require bench verification. Keep the propellers removed for setup and calibration.
