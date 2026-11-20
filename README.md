# Areion Flight Console

[Open Flight Data](https://chilchiltrips-boop.github.io/areion-flight-console/#flight) · [Open the setup wizard](https://chilchiltrips-boop.github.io/areion-flight-console/#configuration/wizard)

The GitHub Pages application runs in the browser and talks directly to the Areion FC A1. The laptop needs only a compatible browser. The two-row header contains the link state, arming status, DISARM / STOP, navigation, TX/RX frame rates, transport selector, port chooser and manual connection controls.

## Connect the kit

- **USB.** Use desktop Chrome or Edge. Connect the kit by USB, choose **USB ports → Choose a new port…**, grant access to the board and press **Connect**. Close other applications using the same port. The list updates when devices are attached or removed. The console remembers the last confirmed USB type. If several identical adapters are present, choose the intended one. The browser may identify a port by vendor and product IDs.
- **AP Wi-Fi.** Stock 3.2.0 firmware provides a UDP endpoint for desktop clients. Direct access from this website requires the optional [browser AP firmware](firmware/README.md) on the kit. Open the console online first and allow it to finish preparing for offline use. Join the kit’s Wi-Fi, select **AP Wi-Fi**, use the default kit address and press **Connect**. Allow local network access when prompted by your browser.
- **Recordings.** Use **Flight Data → Controls → Recordings** to import a telemetry CSV or export the current session. Replay drives the instruments and plots from recorded packets. Hardware commands require a live controller.

The header chooses the link to the kit. **Flight Data → Save input** independently selects PPM, AP or USB flight input. Switching input preserves the rest of the setup. Disarm the kit and stop its sender before changing input.

## Console pages

| Page | Controls and readings |
| --- | --- |
| Welcome | Page shortcuts, setup verification, kit status and session events |
| Flight Data | Dual-stick transmitter, keyboard and auxiliary controls, eight channels, attitude display, relative yaw, animated IMU, system health and motor outputs |
| Configuration | Guided setup and restart verification, receiver calibration, IMU capture, ESCs and motor outputs, rate and attitude PID editors with controller readback |
| System | Live fields with age and state, connection details, event log, copyable diagnostics and CSV export |
| Scopes | Motion, control, spectrum and receiver plots, freeze, time window and export |
| Firmware | Controller-reported firmware identity and capabilities |

Remove the propellers before setup and motor calibration. Hardware-in-the-loop and browser firmware flashing are unavailable in this release. The IMU shows relative yaw. GPS position requires a reported fix.

## Development

Run `npm test` and `npm run build`. The build creates the static app and its offline cache in `dist/`. GitHub Actions tests and publishes this directory to GitHub Pages. The separate firmware workflow compiles the AP-enabled sketch for the target board. The [desktop source](desktop/README.md) is included for users of the original Python application.
