# Areion Flight Console

[Open Flight Data](https://chilchiltrips-boop.github.io/areion-flight-console/#flight) · [Open the setup wizard](https://chilchiltrips-boop.github.io/areion-flight-console/#configuration/wizard)

The GitHub Pages application runs in the browser and talks directly to the Areion FC A1. The laptop needs only a compatible browser. The toolbar keeps navigation, TX/RX rates, the kit connection, arming status and STOP on one line. The notification bell shows offline readiness and update messages. Opening it marks the messages as read.

## Connect the kit

- **USB.** Use desktop Chrome or Edge. Connect the kit by USB, choose **USB ports → Choose a new port…**, grant access to the board and press **Connect**. Close other applications using the same port. The list updates when devices are attached or removed. The console remembers the last confirmed USB type. If several identical adapters are present, choose the intended one. The browser may identify a port by vendor and product IDs.
- **AP Wi-Fi.** Stock 3.2.0 firmware provides a UDP endpoint for desktop clients. Direct access from this website requires the optional [browser AP firmware](firmware/README.md) on the kit. Open the console online first and allow it to finish preparing for offline use. Open **Notifications** and wait for **Offline ready**. Join the kit’s Wi-Fi in the computer’s Wi-Fi settings. Select **AP Wi-Fi → Find kit → Connect**. Find kit checks the selected address and the factory address with a read-only gateway poll. Connect opens the FC session. Allow local network access when prompted by your browser.
- **Recordings.** Use **Flight Data → Controls → Recordings** to import a telemetry CSV or export the current session. Replay drives the instruments and plots from recorded packets. Hardware commands require a live controller.

The header chooses the link to the kit. **Flight Data → Save input** independently selects PPM, AP or USB flight input. Switching input preserves the rest of the setup. Disarm the kit and stop its sender before changing input.

## Embed the console

On an HTTPS platform, place this iframe in the desktop workspace. It fills the available width and uses the frame’s own viewport for the header, instruments and workbench. Allow about 1024 px of width for side-by-side work.

```html
<iframe
  title="Areion Flight Console"
  src="https://chilchiltrips-boop.github.io/areion-flight-console/"
  allow="serial; local-network; local-network-access; clipboard-write"
  style="display:block;width:100%;height:85vh;min-height:540px;border:0">
</iframe>
```

If the platform sends a restrictive `Permissions-Policy` header, include `https://chilchiltrips-boop.github.io` in its allowlist for those features on every embedding ancestor. The newer `local-network` and earlier `local-network-access` directives cover different Chromium versions. When an iframe sandbox is required, allow scripts, same-origin identity and downloads. Allow popups and popups to escape the sandbox if using the standalone link. The host's CSP must allow this origin in `frame-src`. Keep the console's published URL as the iframe source so the kit recognizes the WebSocket Origin. If a platform removes device permissions, open the console directly.

### Switching to kit Wi-Fi

1. Open the **actual embedded page** online in the browser profile that will connect to the kit. Open the console’s **Notifications** and wait for **Offline ready**. This verifies the cached files for every console page, including the assembly and PID models. Use **Retry** if a download was interrupted.
2. Leave this window open and join the kit’s access point in the computer’s Wi-Fi menu (the example firmware calls it **aerion drone**). **Find kit** checks the Areion gateway on that network. Browsers do not list or join nearby SSIDs for the page.
3. Choose **Connect** and allow local network access. The header’s TX/RX meters show actual traffic after the FC handshake. USB uses the same pages via desktop Web Serial. Choose a port when prompted. Neither discovery nor changing networks starts a sender.
4. To reload the **entire platform page** without internet, the host site must also cache its own page. Chrome partitions embedded storage by the top-level site, so warm each platform separately. For a host you control, [copy the offline embed example](examples/offline-embed/) into its own HTTPS directory, or cache the embedding page in your existing site worker. The example shows separate host and console readiness. If you use the standalone console as a fallback, open that tab online once as well.

## Firmware and Wi-Fi recovery

Open **Firmware** in desktop Chrome or Edge. Remove propellers and disconnect the LiPo. For an existing kit, connect over USB and choose **Update via USB**. For a new board, choose **Install / recover board** and select its USB port. Reconnect after flashing to check the running version.

The Firmware page shows the installed FC version and available release. Firmware 3.4.0 adds AP installation and reports the versions of both Arduino libraries. Update older boards once by USB. For later AP updates, join the kit Wi-Fi with the console ready offline, power the board over USB, remove the propellers, disconnect the LiPo and hold BOOT while starting the update. Release BOOT when writing starts. Reconnect after restart to verify the installed version. The same page provides the matching Arduino source ZIP.

With firmware 3.3.0 or later, **Firmware → Kit Wi-Fi** lets you set the SSID and password over USB. **Recover access → Restore Wi-Fi** restores the release's default SSID `aerion drone` and generates a new password. Keep the displayed password and restart the board. Flight settings are stored separately. Set the credentials once when upgrading a kit whose password existed only in its old sketch.

## Calibrate the IMU

Open [Configuration → IMU](https://chilchiltrips-boop.github.io/areion-flight-console/#configuration/imu) or **Setup wizard → Sensors**. With the propellers removed and the kit connected, confirm the arming lock and choose **Start calibration** once. Rest the kit in each of six positions in any order. The guide shows the measured orientation, how long it has been steady, and which positions are still needed. Leave it still until the position is marked captured. Movement restarts the current hold.

After all six pass, choose **Save calibration to kit**. The console reads back both the active and stored accelerometer offsets and confirms the sensor check with the controller. The gyroscope’s stationary rates are checked during capture. The kit measures its own gyro bias at power-up.

## Console pages

| Page | Controls and readings |
| --- | --- |
| Welcome | Page shortcuts, setup verification, kit status and session events |
| Assembly | Guided F450 assembly, free build, a 3D parts shelf and a 2D wiring exercise. The browser saves the virtual project locally. [Open Assembly](https://chilchiltrips-boop.github.io/areion-flight-console/#assembly) |
| Flight Data | Dual-stick transmitter, keyboard and auxiliary controls, eight channels, attitude display, relative yaw, animated IMU, system health and motor outputs |
| Configuration | Guided setup and restart verification, receiver calibration, IMU capture, ESCs and motor outputs, rate and attitude PID editors with controller readback |
| System | Live fields with age and state, connection details, event log, copyable diagnostics and CSV export |
| Scopes | Motion, control, spectrum and receiver plots, freeze, time window and export |
| Firmware | USB installation, AP updates, installed and release versions, Arduino source bundle, and USB Wi-Fi name, password and recovery |

Remove the propellers before setup and motor calibration. Hardware-in-the-loop is unavailable in this release. The IMU shows relative yaw. GPS position requires a reported fix.

## Development

Run `npm ci`, `npm test` and `npm run build`. The build creates the static app and its offline cache in `dist/`. GitHub Actions tests and publishes this directory to GitHub Pages. The Pages workflow compiles firmware with the pinned board core and packages the USB installer, release images and checksums for offline use. The [desktop source](desktop/README.md) is included for users of the original Python application.
