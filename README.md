# Areion Flight Console

Areion FC A1 telemetry in the browser and the full PyCharm desktop console.

## Web console

Open [Areion Flight Console on GitHub Pages](https://chilchiltrips-boop.github.io/areion-flight-console/). Use a desktop browser with Web Serial support such as Chrome. Close other applications using the USB port, click **Connect USB**, and select the board. The console waits for a verified Link v2 handshake and shows live attitude, receiver channels, motor output commands and system health. Relative yaw is measured from gyro data. Disconnect releases the port.

The **Recordings** tab can export the current session or replay a telemetry CSV from the browser or desktop console. A recording works offline after the page has loaded and does not require a serial port. Live status and recording controls are independent of flight control. USB and recordings stay in the browser.

## Desktop console

The Python application and SDK are in [desktop](desktop/README.md). Open that directory in PyCharm, install its requirements and run its main file.

```sh
cd desktop
python -m pip install -r requirements.txt
python main.py --check
python main.py
```

Use the desktop console for AP Wi-Fi, the setup wizard, transmitter control, PID writes and calibration. The desktop release is 3.12.3 and uses the Areion Link v2 protocol. Its paired controller firmware is 3.2.0.

## Develop and publish

Serve the browser app locally from the repository root with `python -m http.server 8000 --directory web`, then open `http://localhost:8000`. Run the browser protocol, instrument and recording tests with `npm test` on Node.js 22 or newer. The frontend has no npm installation or build step.

For GitHub Pages, choose **Settings → Pages → Build and deployment → Source → GitHub Actions**. The **Publish web console** workflow tests the code and deploys the contents of `web/` when the web app or its tests change on `main`. It can also be run from the Actions tab.
