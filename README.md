# Areion Flight Console

Open [Areion Flight Console](https://chilchiltrips-boop.github.io/areion-flight-console/) for the Areion FC A1. The top bar follows the desktop console’s page order. Welcome has shortcuts to the setup wizard, flight instruments, input, IMU, ESCs, PID and scopes.

## Choose how to open the console

| | Published web app | Full browser console |
| --- | --- | --- |
| Flight Data | Live USB telemetry, CSV replay, artificial horizon, relative yaw, airframe animation, joystick monitor and system health | Original Python instruments and interactive transmitter, keyboard, flight-mode switch and input selection |
| Configuration | Browse setup, inspect input and ESC settings, capture IMU/PPM measurements and preview PID settings | Complete the original wizard, calibrate ESCs and motor outputs, change PID, save settings and verify controller readback |
| System, Scopes and Firmware | Inspect telemetry, diagnostics, motion and control plots, receiver history, spectra and firmware information | Use the original desktop pages, dialogs, keyboard controls, animations and exports |
| Connection | Web Serial in a supported desktop browser, or a local recording | USB or the kit’s AP Wi-Fi through the computer running the launcher |

The full browser console runs the same Python 3.12.3 GUI and Areion Link v2 implementation as the desktop application. Its browser tab displays the actual Qt widgets and sends mouse, touch and keyboard input to the local application. Hardware connections and settings stay on the computer connected to the kit. HITL and firmware flashing are disabled in this desktop release. The paired controller firmware is 3.2.0.

## Open the full console

On macOS, [download the project ZIP](https://github.com/chilchiltrips-boop/areion-flight-console/archive/refs/heads/main.zip), extract it and open **Start Areion.command**. Install Python 3.10 or newer beforehand. On first launch the script sets up the project environment and installs its dependencies. The full console then opens in your default browser. Leave its terminal running while using it.

With an existing Python environment on macOS, Windows or Linux, run the following from the extracted project folder.

```sh
cd desktop
python -m pip install -r requirements.txt
python browser_console.py
```

To reopen the running console, choose **Full browser console → Open running console** on the published site, or open the private local link printed by the launcher. Disconnect USB from the published page first if that tab owns the port. Select **USB** or **AP** inside the full console and click **Connect**. The launcher accepts one controlling tab on the same computer. Switching away releases held controls and ends an active sender or motor test.

## Open USB telemetry or a recording

On the published page, select **Connect USB** in a browser with Web Serial support and select the board. The cockpit waits for the Link v2 handshake. **Flight Data → Recordings** imports telemetry CSV files from either console and exports packets from the current USB session. Roll, pitch, relative yaw, receiver channels and scopes update from the live link or the playback position. Configure, save and operate the kit in the full browser console.

## Development

Serve the published app locally with `python -m http.server 8000 --directory web` and open `http://localhost:8000`. The JavaScript app needs no build step. Run `npm test` for its protocol, recording, instrument, scope and calibration tests. From the repository root, run `python -m unittest discover -s tests -p 'host_*.py'` with the desktop dependencies installed to test the local browser host. The desktop application and SDK have their own [guide](desktop/README.md).

GitHub Actions tests the browser app and host and publishes the contents of `web/` to GitHub Pages on changes to `main`.
