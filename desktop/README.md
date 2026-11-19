# Areion Flight Console 3.12.3

Native Python / PySide6 desktop and Python SDK for **Areion FC A1**.
Use the desktop with FC firmware **3.1.0 or 3.2.0**. For a new installation, pair Arduino main **3.2.0** with ZebjusAreionLink Arduino library **3.2.0**.

## Welcome and saved input

Welcome opens offline. Select a shortcut to open Flight Data, Flight input, IMU, ESC / motors, PID settings or Scopes. The yellow tile opens the setup wizard. Kit status and recent session activity appear below the tiles.

On a completed kit, open **Configuration → Input**, choose **PPM**, **AP** or **USB**, and click **Save input** while disarmed with the sender stopped. The kit stores the new source for its next startup. Profile, PID, calibration, channel mapping, motor settings and verified completion carry over. If this receiver has never been calibrated for PPM, complete the receiver step in Setup wizard first.

## Flight Data

**Joystick TX** is the default view. In PPM mode the two sticks follow the physical receiver. With USB/AP selected, the sticks, flight mode and sender controls use the existing digital transmitter. The lower tabs group auxiliary channels, the eight-channel monitor, and keyboard/bench options.

Beside **Joystick TX** or **GPS map**, the default instrument view shows a horizon, a moving Quad X and all twelve System Health tiles. **Expand health** enlarges the tiles and aircraft. **Show instruments** restores the horizon. Read bank on the upper arc and pitch against the fixed aircraft symbol. The attitude values are in degrees. **Tilt** is the inclination calculated from the controller’s filtered roll and pitch. Level reads 0°. A pure 30° bank reads 30° tilt. Banking and pitching at the same time both contribute.

The Quad X follows roll, pitch and relative yaw. Its front marker helps you see the direction of rotation. The yaw tape uses the same gyro reference. **Zero yaw** sets the present direction to 0° in both views. At 80° of pitch or steeper the aircraft shows tilt only. Loss of IMU data clears the aircraft and its readings until a fresh sample arrives. Read the arm indication separately from the horizon. It comes from the controller’s status message. If status expires, the arm indication becomes unknown. If IMU readings expire, the horizon drops its live angles.

**GPS map** opens an offline Natural Earth overview. Current Areion firmware 3.2.0 has no GPS position message. The map starts with “Waiting for GPS” and displays a marker only after a valid position arrives. A running or pending sender keeps the joystick view selected.

For a future FC GPS decoder, hand validated position updates to the GUI thread via `gps_map.update_fix(latitude, longitude, valid=has_fix, stamp=receipt_time, session=identity)`. Coordinates are decimal degrees. Use the monotonic host receipt time and the active link identity used by `set_link`. The map centers a fresh fix, clears it on loss or reconnect, and expires it after five seconds. The bundled 1:110m atlas shows regional coastlines.

The earlier [layout sketch](docs/Flight_Data_Layout.html) is included for reference.

## PPM transmitter status

Flight Data shows the physical transmitter’s status in **TX LINK**. Green **TX ON** requires a verified receiver check. Orange indicates a lost signal, a receiver that still needs checking, or a reading the console cannot verify. The label gives the reason.

To set up a receiver, open **Configuration → Input → Check transmitter…**. With propellers removed and the kit disarmed, capture **ON → OFF → restored**, leaving the kit and receiver powered throughout. Choose **Save check**. The desktop remembers the result for this kit.

- If the receiver stops sending pulses on radio loss, choose **PPM pulses stop**.
- If the receiver keeps sending pulses, reserve an unused auxiliary channel. For example, with CH5 assigned to flight mode and CH6 free, keep CH6 at 2000 µs during normal use and set its receiver failsafe to 1000 µs. Select CH6 for the check. Keep that channel dedicated to the transmitter link.
- If every channel holds its last value on radio loss, there is no observable OFF signal. The check explains how to supply one. Holding the sticks still is normal.

The check reads telemetry and stores the receiver profile on this computer. Flight-control input selection, arming and the kit’s signal-loss response are configured separately.

## Choosing a USB port

Choose **USB** in the top bar, open the port selector, choose the full device path and press **Connect**. New ports appear automatically, even while the list is open. A device that is unplugged becomes unavailable. Use the arrow keys and Enter, or click a port to select it. The console opens with the last successfully connected USB port selected. Selecting a port, refreshing the list and reconnecting the cable leave the connection under your control.

The **Flight Data** input selector chooses PPM, USB channels or AP Wi-Fi channels for flight control. Use **Save input** to apply that choice to the kit.

## Top navigation

The top bar holds **Welcome, Flight Data, Configuration, System, Scopes, HITL** and **Firmware**, alongside TX/RX activity and USB/AP connection controls. Connection controls wrap onto a second row at smaller widths. The status strip keeps board identity, connection/arming state and **DISARM / STOP** visible. The minimum window size is 900 × 700 logical pixels.

- **Welcome:** view connection and setup status, open Flight Data, or resume setup.
- **Flight Data:** the dark transmitter at left, health/attitude/relative yaw and
  output telemetry at right. Control-source selection stays separate from the
  USB/AP telemetry connection. Control, mode and secured PID-tuning behavior is retained.
- **Configuration:** Setup wizard, Input / receiver, IMU, ESC / motors, PID / settings.
  Direct calibration remains outside the wizard. A first-time PPM receiver must
  be selected/configured in Setup; an existing PPM kit can recalibrate directly.
- **System:** live values, freshness, event log, CSV/diagnostics export and detailed
  connection state. Table updates are bounded to the visible page.
- **Scopes** shows motion, control response, IMU spectra and receiver activity. Select a 5, 15 or 30 second window. Freeze holds the visible capture while new packets continue into the session log.
- **HITL:** reserved for future hardware-in-the-loop support.
- **Firmware:** installed-version/compatibility information and update guidance.
  The flash control is disabled because this desktop has no verified uploader.

### Reading Scopes

| View | Signals |
| --- | --- |
| Motion | Gyroscope rates, accelerometer X/Y/Z, and roll and pitch from the accelerometer and Kalman filter. |
| Control | Target and measured roll, pitch and yaw rates, plus the four motor commands in µs. Motor commands report the flight controller’s output pulse. |
| Spectrum | Accelerometer and gyro peak amplitudes by frequency. The footer shows the measured packet rate, FFT sample count and bin width. |
| Receiver | Accepted PPM/AP/USB input, raw PPM when the FC streams it, and two channel-history plots covering CH1–CH8. The monitor shows the saved channel mapping and endpoints when available. |

Click a trace label to hide or show it. Point to the plot to inspect a sample. **Export session CSV** includes the latest 5,000 received packets from the current session, including those received during Freeze.

The spectrum uses 32–256 successive IMU packets. It removes the mean, resamples by desktop receipt time and applies a Hann window. The highest displayed frequency is half the measured receipt rate. For example, a 13.3 samples/s capture reaches about 6.7 Hz. The onboard 250 Hz loop runs independently. Missing, stale or irregular samples are identified on screen.

The endpoint button beside USB/AP opens the shared port/address/advanced settings
panel. Choose settings, close the panel, then **Connect / Reconnect**. The **×**
button disconnects. Changing a dropdown does not reconnect or change flight input.
The same top controls remain available during setup and calibration. A scheduled
ESC request survives expected reconnects; the sender and motor tests never resume
automatically. DISARM / STOP retains its explicit cancellation behavior.

TX/RX bars show measured transport frames/s, including protocol requests, retries
and heartbeats. TX counts successful local writes, not remote acknowledgement;
RX counts decoded incoming frames, including those later rejected by session/schema checks. Combined paths count each physical path. These
are activity meters, not Wi-Fi/PPM signal strength. TX can legitimately be idle.
Stale or disconnected links clear live indicators. The rate counters reset when the connection or kit session changes.

The wizard shows the setup navigation rail in wide windows and a step selector
in smaller windows. Back, Next and Finish remain visible as the page scrolls. Calibration pages use the shared top
connection bar; persistent ARM locking and verified finishing are unchanged.

## Direct calibration pages

**Configuration → IMU → Calibration** provides six-position ACC capture, manual
offsets with corrected g, live attitude and gyro-zero preview outside Setup wizard.
The **Readings** tab retains the existing sensor telemetry and graphs.
**Configuration → ESC / motors** provides endpoint scheduling, USB/AP reconnect,
result confirmation and a **Motor verification** tab on one page.

1. Connect the kit using the top USB/AP connection bar. Opening a calibration
   page only displays telemetry; it sends no calibration or motor commands.
2. Remove every propeller, tick the confirmation, then choose **Begin calibration**.
   The kit persistently locks flight arming and loads its current settings. Existing
   valid receiver, sensor, ESC and motor checks are retained.
3. For IMU, capture the required positions or edit offsets, review level/direction,
   and use **Save offsets & confirm sensor check**. Gyro zero is a Python preview;
   repeat the existing FC gyro calibration by power-cycling the stationary kit.
4. For ESCs, confirm actual PWM/endpoint compatibility and use **Save & calibrate
   on next startup**. Follow the documented complete power cycle below. Reconnect
   on this same page, wait for sensor recovery, then click **Resume calibration**.
   No calibration is scheduled or replayed merely by reconnecting.
5. Confirm the ESC response, then use **Motor verification** to verify all four
   outputs. ESC recalibration clears the old motor checks, so they must be repeated.
6. After the relevant section saves and checks are complete, tick the review box
   and click **Finish & verify saved settings**. This verifies the current kit's
   stored configuration without applying hidden PID/profile drafts. It releases
   the calibration lock and leaves the motors DISARMED.

Unsaved offsets/idle values, incomplete checks, a failed save or stale connection
cannot finish calibration. A fresh/unconfigured kit still needs its remaining
checks in Setup wizard. Leaving the page cancels captures and stops motor tests;
physical checks and the ARM lock remain on the kit until verified completion.
A pending one-shot ESC request survives the expected power-off/reconnect interval.
Global **DISARM / STOP** explicitly cancels that request when storage succeeds.

### ESC sound capability

The current kit uses fixed 250 Hz PWM and exposes no ESC tone command. This GUI
therefore does not synthesize ARM/DISARM sounds by changing throttle pulses.
Startup and endpoint-calibration tones are generated by the ESC itself, according
to its own firmware. Selectable beep commands require a compatible protocol and
ESC implementation, such as DShot; DShot beep commands are executed with motors
stopped. Choosing an ESC illustration does not enable DShot or change the PWM.
Reference: https://betaflight.com/docs/development/API/Dshot

## Install the complete release

1. Extract **AreionFC_PyCharm_v3.12.3** into a new folder and open that folder in PyCharm.
2. Run `install_requirements.py`, then `main.py`, using the same interpreter. You can run `python main.py --check` to verify imports offline.
3. If your kit already runs firmware **3.1.0 or 3.2.0**, connect it. For a fresh kit or older firmware, install the **3.2.0** Arduino main and matching **3.2.0** ZebjusAreionLink library. Keep the existing ZebjusPpm dependency. Open the complete `AreionUSBAP_CurrentMain` sketch directory with its `.ino` and both `.h` files together.

**Keep the LiPo/ESC supply disconnected while flashing.** A USB-only startup can consume a pending calibration request while the ESCs have no power. If that happens, schedule a new request in the wizard when needed and follow its power-cycle instructions.

A fresh kit or firmware without a valid saved completion record starts **ARM LOCKED**. Existing valid stored setup from 3.0.x is read back on 3.1.0; reconnect alone does not erase it. A successful final save enables future explicit arming; it never arms the aircraft automatically. See VALIDATION.txt for the checks performed on this release. Target-board upload, ESC behavior, physical sensor/receiver/motor checks and flight behavior still require validation on the actual kit.

## Scrolling and Live data

Mouse wheels and trackpads scroll the page without changing numeric fields, closed selection boxes or sliders, even when a field has focus. Edit deliberately by typing, using the step buttons/arrow keys, choosing a list item or dragging a slider. Entering a page focuses its container instead of selecting the first editable value. Wizard capture, motor-test and save buttons no longer cause Qt focus to jump the page down when controls become temporarily disabled; the current scroll position is retained.

The Live data table uses fixed initial column widths that can be resized manually. Only changed visible-page cells are refreshed, and plots are refreshed while their page is visible. Telemetry collection and control/safety processing continue in the background. This removes repeated whole-table size calculations on every sample.

## Setup wizard and restart verification

The wizard has nine steps for configuring the kit and an optional tenth step for checking it after a restart. It includes two original Quad X airframe models in `areion_gui/assets/airframes`. The 450 and 250 profiles use separate Wavefront OBJ files and a shared MTL palette. They render locally in Qt. The aircraft models show the airframe with its propellers removed. The wiring page uses the board's fixed 2D connection diagram.

On **Sensors**, compare the target pose with the live aircraft and watch capture progress while holding each position still. A movement or orientation error identifies the position to retry. The six-position illustration uses the measured gravity direction at rest, including upside down. The gyroscope tab shows relative yaw. A gyro-zero capture applies to the Python display for the current session. **Save offsets** stores the supported ACC offsets on the kit.

On **PPM receiver**, the left stick shows throttle and yaw and the right stick shows pitch and roll. The sticks follow raw receiver pulses through the selected mapping, reversal and range settings. Sweep the assigned channels to learn their endpoints, then lower throttle and centre the other three axes for neutral capture. A lost receiver signal clears the live sticks.

Open **Configuration → Setup wizard**. Opening it requests a durable firmware arming lock immediately; the propeller checkbox is a separate physical confirmation. A previously completed kit is re-locked for review, but its saved settings and still-valid physical checks are retained. Readback from the connected kit takes precedence over an old local draft. Repeat checks only when the relevant settings changed, you choose reset, or a check is shown as pending. Closing the wizard, disconnecting or rebooting does not unlock ARM. Reconnecting to an already locked setup resumes its recorded state.

The table describes checks that are pending. Review retained valid results without recapturing them unless the hardware or relevant settings changed.

| Step | Page | What to do |
| --- | --- | --- |
| 1 | Safety & connect | Remove every propeller, connect through USB/AP and confirm the setup lock. Continue with the loaded kit settings, or explicitly reset all settings to defaults. |
| 2 | Aircraft profile | Review the loaded aircraft profile. Choose and save a different illustrated profile only when needed; profile templates use the stable default PID. |
| 3 | Input & wiring | Save PPM, AP or USB as the flight input. Only the source selection is saved by this action. Use the fixed 2D map for OUT1–OUT4, PPM and IMU wiring. |
| 4 | Sensors | Capture ACC positions, review corrected g values and attitude direction, then save offsets and confirm the sensor check. Gyro zero is a Python preview. |
| 5 | PPM receiver | For PPM only, capture full stick travel and neutral, map/reverse channels, then save and verify. AP/USB skip this check. |
| 6 | ESC calibration | Explicitly schedule one calibration for the next startup, follow the ESC maker's procedure and confirm the result; or record that calibration is not required. |
| 7 | Motor outputs | With props removed and the LiPo connected, test single/all motors, record starting/idle outputs and confirm motor order and rotation. |
| 8 | Arming & flight modes | Move the assigned switch on the PPM transmitter to preview its Low and High modes. Review timing and signal-loss timeouts, then save changes. |
| 9 | Review & save | Review changed settings beside their original kit values. Finish setup verifies the stored configuration and releases the setup lock. |
| 10 | Verify after restart (optional) | Reconnect to the same kit after it restarts. Compare the new readings with the settings verified at Finish. A reconnect within the same boot leaves the check waiting. |

**Test mode switch** uses the raw pulse on the selected PPM channel. Move the physical switch both ways. A pulse below 1500 µs selects Low and 1500 µs or above selects High. The preview labels the displayed mapping when there are unsaved edits. A lost signal clears the current pulse. The check is optional.

**What changed?** compares original kit settings from this setup visit with the values for final save. Changing just the flight input shows one row. If a fresh initial read is still needed, the review says so.

**Verify after restart** opens after the verified final save. You can also open **Verify last setup** on Welcome using the receipt saved by this installation. A USB/AP reconnect in the same boot leaves the check waiting. After the same controller starts a new boot, the console reads its active and stored settings, checks the selected input and compares setup completion and calibration checks. Differences list the saved and observed values. A different kit, incomplete reads or an unavailable storage service cannot produce a verified result. You can finish setup without running this additional check.

The shared top connection bar is available on every wizard page. After unplugging USB, a kit restart or an AP drop, choose USB/AP (or USB + AP), update the serial port or AP address if needed, and click **Reconnect** there. The old connection is closed and replaced; no separate visit to Connections is required. The same kit resumes the current step and reads its saved settings and confirmations. Offline checkmarks are labelled as last confirmed, not live proof. Incomplete sensor/receiver captures are cancelled; motor output never resumes automatically. A different kit cannot inherit another kit’s confirmations.

Back and Next stay visible while the page scrolls. The first Back is disabled. On step 9, **Save & finish** writes the setup. After verification, **Done** returns to Welcome. **Verify after restart** opens the optional read-only page.

### Keep current settings or reset

Step 1 automatically reads the connected kit. **Reload from kit** refreshes that readback. You can review each page with the current values and valid checks, save the sections you change, and use the final verified save to release the setup lock. Opening setup alone does not restore PID defaults or erase calibration.

**Reset all settings** is optional and requires both the propeller-removal and reset confirmations. It restores PID, ACC offsets, receiver calibration/mapping, input and flight-mode settings, motor idle values and timing to the kit defaults. It clears saved setup checks and a pending ESC-calibration request. Progress shows the reset and readback; success means active and stored settings were verified. The kit stays ARM LOCKED and requires setup completion again. Reset cannot run during an active motor/ESC operation. If reset is interrupted or cannot be verified, reconnect and **Reload from kit** before continuing; do not assume nothing changed.

### ESC calibration is an explicit, one-time operation

Selecting an ESC picture does not calibrate it. **Save & calibrate on next startup** saves a single-use request after the sensor check and, for PPM input, receiver verification. It does not send a high output immediately.

Follow the selected ESC manufacturer's supported endpoint-calibration and power-up procedure. After scheduling, disconnect **both USB and LiPo** so the kit actually restarts. Power the kit and ESCs with all propellers removed; USB power alone cannot calibrate unpowered ESCs. The pending request is restored and consumed before PWM starts. Maximum is the first commanded pulse, before AP initialization; the signal stays high for three seconds, then low for three seconds. AP becomes available after the high phase, so an AP connection may first show the low phase or the completed result. USB/AP do not have to remain connected for the bounded sequence to finish.

After the sequence, outputs stay at minimum while the firmware **automatically initializes the IMU in the same boot**, normally about 3.5 seconds. Keep the kit stationary. Reconnect from the top connection bar and use **Read calibration result**; saved sensor/receiver settings remain on the kit. No second power cycle is required. Wait for fresh sensor data, confirm the expected ESC tones/result, then continue to motor testing. Do not schedule another calibration merely to check progress. A failed IMU startup keeps outputs at minimum and ARM/motor testing unavailable; it does not report successful ESC acceptance.

The software can confirm that the signal sequence ran, not that a particular ESC accepted new endpoints. If the ESC maker says endpoint calibration is unnecessary, use the explicit **Record calibration not required** option.

The pending request is consumed and recorded before the high output. A reset/interruption during the sequence is reported as interrupted and is not retried automatically. Ordinary later startups do not repeat it. STOP/DISARM stops current output and cancels a pending or active calibration when its storage update succeeds. If cancellation reports a storage error, keep ESC power disconnected: the older pending request may still exist, so verify and cancel it after storage recovery before powering the ESCs. Do not use STOP merely to reconnect to a scheduled/running sequence; the wizard reads its existing state when resuming.

### Real motor-output checks

The motor page now uses the firmware's independent bench-test API; flight ARM remains blocked. Confirm that all props are removed, the frame is secured and LiPo wiring/polarity are correct. Start with one motor at **1000 µs**, increase only as needed within **1000–1500 µs**, and record its reliable starting value. Stop before saving/confirming its order and direction. Repeat for all four; an all-motors option is also available.

The FC limits a session to **30 seconds**, stops if command refresh is missing for **350 ms**, and binds the test to the current owner/session. Unselected motors stay at minimum. The GUI stops an active test on navigation, focus loss, disconnect or Stop and never resumes it automatically. Output readback and animation show commands, not measured RPM. A motor check is a recorded operator observation, not automatic detection that a rotor turned.

### PPM calibration, arming and failsafe

Receiver capture reads **raw group 131** before the neutral-input gate. Move every assigned stick fully both ways, then center roll/pitch/yaw and lower throttle. Save channel min/center/max/reverse in group 132 and the four unique physical-channel assignments in group 134. Firmware normalizes these into the existing logical Roll/Pitch/Throttle/Yaw path. The throttle uses its endpoints; its stored center is not used for normalization. ARM stays locked during capture, including yaw sweeps.

Default PPM gestures remain throttle low + yaw right for **5 seconds** to ARM, and throttle low + yaw left for **1 second** to DISARM. Low-throttle idle auto-disarm defaults to **15 seconds**. The wizard permits adjustment and can restore these defaults. AP/USB use explicit ARM/DISARM commands; they do not use stick gestures or the PPM idle timer. Default signal-loss timeouts are 250 ms for PPM and digital inputs.

Default flight mode uses CH5: below 1500 selects ANGLE; 1500 or above selects RATE/ACRO. Choose a mode channel separate from all four mapped axes. Digital AP/USB flight mode must use CH5–CH8. Low and High must differ. Changing receiver/mode/timing settings can invalidate the corresponding earlier check, so review the status and repeat any check shown as pending. A completed AP/USB setup cannot switch to unverified PPM; choose and verify PPM in the wizard first.

The wizard no longer requires a transmitter-off/loss-and-recovery test or a failsafe-confirmation checkbox. Existing sensor, PPM calibration, ESC and motor checks still apply. Runtime PPM and USB/AP signal-loss handling is unchanged: detected input loss stops the motors and requires normal neutral recovery. This cannot detect a receiver that continues sending valid held pulses after its radio link is lost. Group 130 index 7 remains a legacy optional check; false does not block final save or later arming, and the wizard never fabricates a successful test.

### Fixed hardware and illustrated profiles

Areion FC A1 pins are read-only. The 2D signal drawing follows the fixed mapping; connector locations are schematic and do not establish power polarity. See [hardware/README.md](hardware/README.md). No hardware 3D viewer or CAD dependency is included.

ESC profile cards retain the same compiled output settings: **250 Hz, 12-bit, 1000–2000 µs, duty 1024–2048**. Selecting Standard 50 Hz or OneShot does not change the waveform or enable that protocol. No frequency, resolution or endpoint editors are exposed in the wizard.

The four illustrated aircraft profiles currently share the known stable PID baseline. They are starting templates, not tested frame-specific tuning. The wizard has no P/I/D editors; use **PID & settings** for later tuning. Ordinary configuration changes re-lock readiness and invalidate dependent checks. The dedicated PID and saved-input actions described below preserve an already completed setup only after their own verification succeeds.

### Live roll, pitch and relative yaw

The artificial horizon now animates bank, pitch and a relative-yaw tape. Firmware updates the Kalman attitude during locked setup as well as normal operation; the 3.0.0 early return had left the displayed Kalman roll/pitch frozen during setup. Invalid or stale IMU data displays a waiting state instead of invented movement.

The MPU6050 has no magnetic heading reference. Python integrates fresh gyro samples for **relative yaw**, which may drift and is not North or a compass heading. **Reset relative yaw** sets the current direction to zero. A changed kit/session or a data gap resets that reference; stale and duplicate samples are not integrated. Yaw is marked unavailable near vertical pitch. The display calculation never feeds the flight controller.

### ACC and gyroscope scope

**After offset (g)** appears beside each X/Y/Z offset. Incoming ACC values already contain the active FC additive offset, so the draft preview applies it only once:

```text
after_offset_g = received_acc_g - active_fc_offset_g + draft_offset_g
```

| ACC position | Expected dominant reading |
| --- | --- |
| Flat / level | Z +1 g |
| Nose up | X −1 g |
| Nose down | X +1 g |
| Left side down | Y −1 g |
| Right side down | Y +1 g |
| Upside down | Z −1 g |

Each position needs fresh, distinct stationary samples and orientation checks. Motion, stale/invalid data, a changed FC session or changed active offsets invalidate the affected capture. Opposing positions estimate **additive offsets only**, limited to ±0.5 g. Scale factors and fit residuals are diagnostic; the FC does not apply scale/cross-axis calibration. The sensor page saves offsets explicitly and requires a separate level/orientation review.

**Capture gyro zero** measures residual drift after the FC's existing boot calibration. Its subtraction changes the Python display only. There is no remote gyro-bias save, gyro recalibration or hardware reboot command. To repeat FC gyro calibration, power-cycle the kit and keep it still through startup. Neither Python gyro zero nor ACC scale is written to the FC. Previously saved captures are shown as history. New measurements require fresh readings from the connected kit.

### Saving and lock ownership

The FC owns the setup lock and completion record. The final operation verifies persisted Rate PID, Angle PID, arming, ACC, flight-mode, timeout, receiver-calibration and setup-config sections, plus sensor/receiver/ESC/motor evidence. Only then is completion saved and read back. A rejected completion keeps runtime ARM locked; earlier section saves may already have succeeded. A lost response or interrupted storage readback makes the durable result uncertain, so the GUI keeps ARM unavailable until it can read the kit. Read active/stored values and setup status before retrying an unknown/partial outcome.

The local `setup_wizard.json` backup is written atomically and verified. Schema 4 includes profiles, fixed board settings, calibration provenance, motor observations and the final FC receipt when present. Older drafts migrate without granting permission or restoring physical confirmations. The connected kit confirms its own completion and ARM state. A failure to write the local backup is reported separately from the FC's actual completion state.

Verified setup completion still leaves the kit disarmed and resets neutral readiness. Arming requires current valid IMU/input, neutral controls and a new explicit PPM gesture or AP/USB command. See [FUTURE_FIRMWARE_SETUP.md](FUTURE_FIRMWARE_SETUP.md) for the exact setup contract and remaining unsupported operations.

## Startup / missing project module

If the error names `areion_gui.wizard_extended`, `areion_gui.calibration_panel` or another `areion_gui` module, that is bundled project code. Installing PySide6 or pyserial does not restore it.

The 3.12.3 launcher verifies all required GUI source files and icons, reports exact missing paths, and checks the GUI and SDK version/location before opening the application. A complete `--check` imports the GUI and setup wizard, prints their paths, and opens no hardware. Console mode remains usable without the desktop package.

Download and extract the complete ZIP. Open the new **AreionFC_PyCharm_v3.12.3** folder in PyCharm and run the `main.py` inside it. Ensure the Run configuration's Script path points to that new file, not the old `areon drone /main.py`. You may keep your existing virtual environment as the interpreter; the script must come from the complete new folder. A folder name containing spaces is supported.

### `No module named 'zebjus_areion_link.control'`

Extract this entire ZIP into a **new folder**. Do not copy only main.py or merge selected files into an older project. Open the extracted AreionFC_PyCharm folder in PyCharm, stop any old Python Console, and use the same interpreter for these two runs:

1. Run **install_requirements.py** once. It installs the dependencies and the bundled SDK using that exact interpreter and project directory, even if the working directory differs.
2. Run **main.py** as a normal Run configuration.

The previous launcher displayed the same requirements hint for every import error. This patch distinguishes missing external packages, incomplete extracted SDK files, and an old SDK retained in the Python Console. It gives the affected paths and selects the complete bundled SDK before GUI imports. A preloaded SDK from another project requires restarting that console; it is never silently replaced while it may be in use.

To check imports without opening a hardware connection:

```sh
python main.py --check
```

The check prints the interpreter, SDK version/path and control.py location. The terminal equivalent, **from this extracted project folder**, is `python -m pip install -r requirements.txt`; requirements now include the local SDK as well as PySide6 and pyserial. If the terminal uses a different Python, run install_requirements.py through the selected PyCharm interpreter instead.

## Reuse the Python library

Run `python -m pip install .` in this extracted folder to install the standalone SDK in any Python project. It needs no Qt GUI dependency. See [SDK_README.md](SDK_README.md) and the runnable `examples/read_arrays.py` / `examples/control_arrays.py` scripts. `Link.send_control`, `Link.arm`, `Link.disarm`, `Link.poll`, `read_group`, `set_group`, `save_group` and the same `ControlSession` used by this GUI are available for other projects.

## Run in PyCharm

1. Close Arduino Serial Monitor and any other programs using the FC port. See **Install the complete release** above for supported firmware.
2. Extract this complete Python folder and open it as a PyCharm project. Use a Python 3.10+ interpreter supported by PySide6 on your OS.
3. In that interpreter's terminal:

```sh
python -m pip install -r requirements.txt
python main.py
```

`gui.py` also opens the GUI directly. The app starts disconnected and opens no hardware until you click Connect. `python main.py --console` retains the earlier text menu. CLI options such as `--transport ap` still use the console.

## Connect, then select flight input

The top connection bar offers USB, AP, or USB + AP; System → Connections shows detailed path status. Choose the actual serial port, default 115200 baud, or AP address 192.168.4.1 / UDP8080. A four-second USB startup wait allows the existing calibration. An abandoned owner may need up to six seconds to expire while disarmed. No reset command is sent.

For AP, first join **aerion drone**, using the kit Wi-Fi password, in the computer's Wi-Fi settings. The GUI checks association separately from protocol connectivity. macOS may hide the SSID; UNKNOWN does not mean that FC communication failed. FC CONNECTED requires actual handshake, status and qualified 3.1.0 or 3.2.0 device-info replies. Firmware 2.5.0 cannot enforce the new setup lock or run the new calibration API; install all three matching release components before setup. Path status shows USB/AP confirmation and reply age independently. Opening a UDP socket alone is not connection proof.

The Flight Data page selects **PPM**, **USB**, or **AP** as flight input. With the kit disarmed and the sender stopped, click **Save input**. The guarded action verifies both active selection and the stored boot source, so the choice is restored after startup. An already completed setup remains complete after successful verification; changing source never automatically arms. PPM requires previously verified receiver calibration/mapping. If that check is missing, select and calibrate PPM in the wizard first. AP/USB require a flight-mode channel in CH5–CH8. Connecting the USB cable or joining the AP only establishes telemetry. A PPM-controlled kit keeps PPM selected until you explicitly save a different input. Every source change resets controls and requires fresh neutral input. An unconfigured kit defaults to PPM and stays setup-locked. There is no automatic source fallback, background reconnect, control replay or arming. The wizard provides an explicit Reconnect button on every page.

## PPM: watch your physical transmitter sticks

1. Connect to the FC through USB, AP, or both. This connection carries telemetry.
2. On the Flight Data page, select **PPM receiver → Save input** while disarmed, if PPM is not already selected.
3. Lower the physical throttle and center roll/pitch/yaw once so the existing FC neutral-input gate becomes ready.
4. Move the real transmitter sticks. The GUI automatically shows **PPM LIVE** and follows the received channels. No **Start sender · 50 Hz** or **ARM** action is required for monitoring.

| GUI display | Received PPM channels |
|---|---|
| Left stick, vertical / horizontal | Logical CH3 throttle / CH4 yaw after saved PPM mapping |
| Right stick, vertical / horizontal | Logical CH2 pitch / CH1 roll after saved PPM mapping |
| AUX indicators and channel bars | CH5–CH8 and all available channels |
| FC MODE and Armed status | Actual FC status telemetry |

In PPM mode the sticks, keyboard and AUX sliders are read-only. The display does not copy receiver values into the outgoing control array or start a digital sender. USB/AP mode keeps its existing mouse/keyboard controls. Selecting USB/AP and starting the sender begins with neutral values, not the physical transmitter's last throttle position. Explicit DISARM/STOP remains available as before.

The existing **group22/schema1** array is `[Roll, Pitch, Throttle, Yaw, CH5, CH6, CH7, CH8]`, using the FC's selected and accepted input. In PPM mode these are normalized logical controls after the saved receiver mapping/calibration. It is not an ungated raw PPM capture: before neutral readiness or after input loss, the FC reports its guarded values. The GUI waits for fresh, active, ready PPM status and a new channel array. Missing AUX channels show `—`; stale/lost input hides the stick position and shows **NO LIVE DATA**.

Group 22 is published nominally once every 150 ms, about 6.7 updates/second, subject to transport/backpressure. Setup uses the independent raw group 131, nominally 20 Hz while locked, so endpoint capture is not blocked by the neutral-input gate. The GUI follows each received sample; its repaint rate does not create extra receiver samples. This is a live receiver visualization, not a flight-physics simulation. The 250 Hz onboard flight-loop target and PID equations are unchanged. Kalman attitude now also updates while setup keeps flight outputs locked.

## USB/AP transmitter: mouse and keyboard

1. While disarmed, select USB or AP flight input, click **Save input**, and confirm the matching route is connected.
2. Click **Start sender · 50 Hz**. All eight channels reset to neutral, including throttle1000. The sender first waits for fresh FC neutral-input readiness.
3. After verified setup completion, with low throttle and centered sticks, click **ARM**. The FC remains the final authority and checks the persisted setup lock, input freshness, ownership, calibration and IMU readiness. Current Armed status is read after the command.
4. Drag the left gimbal for throttle/yaw and the right gimbal for pitch/roll. CH5–CH8 have auxiliary sliders. The channel monitor shows desired TX and received FC values.
5. Click **DISARM / STOP**, or press **Escape**. Space also stops while transmitting. Stop cancels pending ARM attempts before requesting DISARM, stops channel sending, clears controls and verifies current FC state when reachable.

The left throttle axis holds its value on release; yaw returns to center. Both right-stick axes return to center. Keyboard throttle ramps at500microseconds/second while held, then holds its position. Roll/pitch/yaw keys return to center on release. Only PPM uses low-throttle yaw gestures and idle auto-disarm. USB/AP use the ARM and DISARM commands; changing sticks alone never changes their arming state. Signal-loss and invalid-IMU stops still apply to every source.

| Channel | Function | Decrease / increase keys |
|---|---|---|
|1|Roll|Left / Right|
|2|Pitch|Down / Up|
|3|Throttle|S / W|
|4|Yaw|A / D|
|5|Aux; default flight mode|1 / 2|
|6|Aux|3 / 4|
|7|Aux|5 / 6|
|8|Aux|7 / 8|

**Configure keys** changes all sixteen bindings. **Reset to default keys**, then **Save**, restores the table above. Duplicates and reserved Stop keys are rejected. Preferences are saved in the OS app-config folder, not on the FC. After closing the dialog, focus returns to keyboard control. Text fields/combo boxes do not act as flight keys. Modifier shortcuts do not operate channels. AUX sliders are mouse controls; channel keys use the saved mapping. Held arrow-key repeats are consumed by the transmitter, so they cannot also move a focused CH7/CH8 slider. Unassigned arrows do not become implicit AUX controls.

Changing pages normally stops the digital sender and requests DISARM. The explicit **Secured tripod · enable live PID tuning** option allows only Flight Data ↔ PID & settings navigation to keep the established sender running; throttle holds and released roll/pitch/yaw controls return to neutral. Other pages, losing window/application focus, closing, or a UI stall over150ms still stop the sender and request DISARM. It never resumes automatically. Monitoring PPM without an active digital sender does not disarm PPM merely because the window loses focus. Explicit DISARM still works for the current owner while PPM is selected.

The UI clock targets20ms/50Hz and displays measured send rate. It skips missed slots instead of sending a burst of old samples. Commands run on a separate worker; that worker never keeps sending channels. OS scheduling and USB/Wi-Fi delays can lower the actual rate. The FC has an independent configurable digital-input timeout (default250ms). These are bench control tools, not flight qualification.

## Flight mode: settings and transmitter

Open **PID & settings → Receiver & flight → Flight mode & stick response**. While disarmed with the sender stopped:

1. Read FC, then choose **Flight mode channel** (default CH5).
2. Choose the mode for **Low · below 1500** and **High · 1500 and above**. The two choices must differ.
3. Click **Apply**, then **Save to FC**. Readback verifies both operations; Save keeps the mapping after a power cycle.

| Channel value | Default mode | Reversed mapping |
|---|---|---|
| Below 1500 | ANGLE | RATE / ACRO |
| 1500 and above | RATE / ACRO | ANGLE |

The Flight Data page shows **FC MODE** from fresh FC status. Its ANGLE and RATE/ACRO buttons request a mode through the selected USB/AP channel stream. They change only the configured AUX channel to 1000 or 2000, including when already armed. Choose **CH5–CH8** for these buttons; CH1–CH4 are stick/throttle axes. Start channels and wait for input readiness before selecting a mode. A highlighted button is the TX request; FC MODE confirms the received result. Stale status displays UNKNOWN / STALE.

With PPM selected, buttons are read-only and FC MODE follows the physical receiver switch. Settings apply to all three input sources. A midpoint of exactly 1500 selects High; the former 1400/1600 middle hold is replaced by the two-zone split.

Group7/schema3 contains six fields. On upgrade, valid previously saved schema2 mode channel and stick scales are preserved in RAM, with default Low=ANGLE and High=RATE/ACRO. Use Save to store the new schema. The flight PID/Kalman equations are retained. The new firmware setup lock now gates every arming path. A changed mapping invalidates the related setup checks; finish setup again before arming.

## IMU calibration

These controls appear on the standalone IMU Readings tab. For guided six-position ACC capture and the gyro-zero preview, open its Calibration tab or Setup wizard step 4.

The IMU page displays AccX/Y/Z in g, RateRoll/Pitch/Yaw in degrees/second, raw AngleRoll/Pitch and Kalman roll/pitch in degrees. The attitude display uses Kalman angles. Four graph tabs show recent samples. Stale/invalid IMU readings blank the gauges; old table values remain labelled STALE or OFFLINE.

Read the three offsets, edit them, **Apply**, then **Save to FC**. Offsets are additive:

```cpp
AccX = AccXLSB / 4096.0f + AccOffsetX;
AccY = AccYLSB / 4096.0f + AccOffsetY;
AccZ = AccZLSB / 4096.0f + AccOffsetZ;
```

Defaults remain **-0.10, +0.03, +0.12 g**. Each is limited to ±0.5g. Group6/schema2 is the existing offset section. Applying requires disarmed state, invalidates the prior IMU/input result and rebases attitude after the next valid sensor read. Gyro calibration is independent. This page provides manual offset editing, not an automatic calibration algorithm.

## PID and settings

Open **Configuration → PID / settings** or use the **PID settings** shortcut on Welcome. **Gain tuning** puts P, I and D in rows and the supported axes in columns.

| Controller | Axes | What the response graph compares |
| --- | --- | --- |
| Rate (inner loop) | Roll, pitch and yaw | Angular rate from the gyroscope and the FC's desired angular rate in °/s. |
| Attitude (outer loop) | Roll and pitch | Kalman angle and the desired angle in degrees while ANGLE mode is active. |

**Read FC** loads the controller's active gains. Edit an individual cell or select **Link roll/pitch** before changing a gain to update its partner locally. Hover over a highlighted field to see its active value. **Revert** restores the active values to that editor. **Apply to FC** sends the selected matrix. Each field you leave alone retains its FC precision.

The response graph shows ten seconds of received telemetry. Change the axis or loop to inspect the tracking response. A stale or unavailable signal is marked on the graph. **Stick response** previews the angle, roll/pitch rate or yaw rate requested by a simulated stick pulse. The slider moves locally. Wider windows show this same preview beside the tracking graph. The **Receiver & arming** tab retains the kit's receiver timeouts and arming settings.

The FC revision and the editor's unsent changes are shown separately. An **Apply unverified** message identifies the loop when a request or readback fails. Check its card for the reason. Reconnect to a kit with an uncertain connection and read its active and saved gains before deciding whether to apply again.

- **Disarmed:** validates the gains, applies them and verifies active plus stored readback. Wait for **SAVED** before disconnecting power. This dedicated action retains a previously verified setup after the save succeeds.
- **Armed, secured tripod:** explicitly enable **Aircraft secured on tripod · enable live PID tuning**. **Apply to FC** updates the active gains in RAM and verifies them. The status shows **APPLIED LIVE · Save pending until DISARM**. It does not write flash during the armed run. Use **DISARM / STOP** when done; the FC automatically commits and verifies the pending PID values. Keep the FC powered until **PID SAVED** appears. Power loss before that save loses the unsaved gains.
- **Read FC** shows active gains. **Read saved** shows the durable copy, which may differ while live tuning is pending. A lost response is an unknown outcome: reconnect and read current PID/save status before another change. A persistence failure is shown as an error and keeps ARM locked.

The live-tuning checkbox allows the established USB/AP sender to continue only between Transmitter and PID & settings. It does not start a sender, ARM the kit or bypass IMU, input, owner/session or setup checks. DISARM / STOP remains available on the PID page. Removing the checkbox while sending from that page stops the sender. PPM continues to use its physical transmitter and ordinary FC arming rules.

Other settings keep their explicit **Apply**, then **Save to FC** workflow. Apply changes RAM and verifies active readback; Save writes the active section and verifies its stored copy. Edited-but-unapplied values cannot be saved. Changed ACC, receiver, arming, flight-mode or timing settings can re-lock a completed kit and clear dependent setup checks; complete the wizard's final save when required. An ordinary SDK SET/SAVE of PID is also distinct from the dedicated tuning transaction.

PPM timeout accepts50–1000ms; digital USB/AP timeout100–500ms. The PPM library's independent diagnostic freshness can reject a signal sooner than the configured application timeout. This setting does not rewrite the external PPM library. Python keeps its150ms sender-stall guard, independent of FC timeout. ARM times are seconds. The low-level group 110 source selector remains RAM-only; the GUI's **Save input** also persists the boot source using the guarded action.

Motor pins/PWM, PPM pin, loop target and AP credentials remain fixed in the Arduino main. Reported wiring/PWM is shown read-only. The wizard adds a dedicated one-shot ESC calibration command and independent motor bench commands. Live pin rewiring, firmware flashing, GPS, battery telemetry and barometer features are not provided.

## Cockpit beside the joysticks

Each System Health tile has a full-color background, a short status and a tooltip. For example, with PPM selected and telemetry connected over USB, PPM shows receiver health, USB shows inactive and TELEMETRY shows the link status.

| Color | Meaning |
| --- | --- |
| Green | Healthy, with current telemetry confirming the state. |
| Orange | Waiting for a selected signal, stale data, or a pending check or save. |
| Red | A fault or invalid reading. The telemetry tile also reports link loss. |
| Gray | Inactive, including an unused flight input or disarmed arming indicator. |

INPUT and the selected receiver tile show what the controller reported about the input. The receiver timeout is checked against the frame age measured on the controller. Each input-status report remains current for up to 500 ms after it arrives. An explicit loss or invalid frame takes effect on the next displayed report. After 500 ms without an input-status report, the console shows a telemetry warning even if other packets keep arriving. The MODE tile keeps the FC-reported mode label while an input warning changes its color.

The motor strip shows the four pulse widths commanded by the FC, in microseconds. I²C / IMU reports sensor read status. LOOP shows the cadence from the controller’s reported interval. CONFIG and STORAGE show setup and persistence status when the controller reports them.

## Live data and diagnostics

Live Data includes all current registered value sections, stream graphs, packet-processing ages and an event log. Settings/device info are labelled READ SNAPSHOT; they are not continuous sensor samples. Output group23 displays PID correction outputs, four motor commands and desired angles/rates.

**Export CSV** saves the most recent5000 received telemetry packets. Graphs retain up to600 samples per field and show the last15seconds. **Copy diagnostics** includes the latest 32 receiver and flight-mode transitions in `receiver_health`. Each indicator transition includes the latest FC receiver-frame age and the elapsed time since the input-status report arrived. The history starts over with the next connection. The report also includes connection paths, FC/owner sessions, current values/ages and the last event. No password is included.

## Current protocol sections

The same `$<JSON-byte-length>:<JSON>*<CRC32>\n` frame remains on all paths. CONTROL group9 is eight integer1000..2000 values. ACTION group123/schema1 remains ARM/DISARM with owner/sequence validation.

| Group/schema | Contents | Access |
|---|---|---|
|2/1|9 Rate PID values|Read / Apply / Save|
|3/1|6 Angle PID values|Read / Apply / Save|
|4/2|ThrottleLow,YawRight,YawLeft,ThrottleMovement,ArmHoldTime,DisarmHoldTime,AutoDisarmTime|Read / Apply / Save|
|6/2|AccOffsetX,Y,Z|Read / Apply / Save|
|7/3|FlightModeChannel,AngleStickScale,RateStickScale,YawStickScale,FlightModeLow,FlightModeHigh|Read / Apply / Save|
|112/1|PpmTimeoutMs,DigitalTimeoutMs|Read / Apply / Save|
|110/1|Selected source0PPM/1AP/2USB|Read / Apply; no Save|
|21/1|10 IMU/angle values|Read / telemetry|
|22/1|8 selected receiver channels|Read / telemetry|
|23/2|InputRoll,InputPitch,InputYaw,MotorInput1..4,DesiredRateRoll/Pitch/Yaw,DesiredAngleRoll/Pitch|Read / telemetry|
|120/1|Existing10-field FC status|Read / telemetry|
|121/1|AP readiness/address,port,owner lease|Read|
|122/2|Existing9-field selected/active/freshness/owner status|Read / telemetry|
|125/1|FirmwareVersion,LoopTargetHz,PpmGPIO,Motor1..4GPIO,PwmHz,PwmBits,MinDuty,MaxDuty,ControlTargetHz|Read|
|130/1|Setup lock/completion, checks, ESC stage, bench outputs, revision/fault/kit ID|Read / telemetry|
|131/1|8 raw PPM pulses, channel count, freshness and age|Read / telemetry; independent of neutral gate|
|132/1|Min/Center/Max/Reverse for each of 8 receiver channels|Read / Apply / Save|
|134/1|Profile, boot source, axis mapping, deadband, four motor idle outputs|Read / Apply / Save|
|135/1|Setup lifecycle, RESET_ALL, INPUT_SAVE, ESC and independent motor-test actions|Command only|
|136/1|Pending, active PID revision, saved PID revision, error|Read / telemetry|
|137/1|PID group, secured-bench confirmation, nine float slots|Guarded PID action only|

The firmware publishes the existing streams in 25 ms slots: 120, 122, 21, 22, 21, 23. Setup status is also available, and raw PPM group 131 targets 20 Hz while setup is locked. Nominal IMU rate is about13Hz and the other streamed groups about6.7Hz, subject to loop/transport backpressure. The flight loop still targets250Hz; channel sending targets50Hz. These are three different rates.

## Checks

Run `python -m unittest discover -s tests -v`. GUI tests use Qt's offscreen platform and real Qt mouse/key events with an isolated test fixture. See VALIDATION.txt. Physical ESP32 upload, Mac GUI/hardware integration, PPM frequency and flight timing must be checked on the real setup. First bench verification must have propellers removed.

Qt references: [installation](https://doc.qt.io/qtforpython-6/gettingstarted.html), [timer accuracy](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimer.html).
