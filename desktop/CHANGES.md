# Desktop / Python SDK 3.12.3

- Added a PPM transmitter link indicator and a per-kit receiver check under Configuration → Input.
- Receivers that continue sending pulses after transmitter shutdown can report radio loss on a dedicated auxiliary channel. A verified loss changes the Flight Data indication to orange, even while ordinary PPM frames still arrive.
- The indicator distinguishes an unverified receiver, missing telemetry, radio loss and link recovery using incoming FC reports.

# Desktop / Python SDK 3.12.2

- Fixed a false PPM, INPUT and MODE warning between valid receiver-status reports. The Flight Data panel and receiver plots distinguish receiver frame age measured by the FC from time since the report reached the desktop.
- Added receiver and flight-mode transitions to Copy diagnostics to help distinguish a receiver loss, delayed telemetry or an actual flight-mode change.

# Desktop / Python SDK 3.12.1

- Improved text contrast in the Flight Data input selector and its list, including the highlighted row.
- The header displays the USB device path and opens a port list directly. USB port discovery updates in the background. Clicking Connect or Reconnect opens the selected connection.
- The desktop remembers the last verified USB port across restarts. Failed attempts and AP-only connections preserve the saved preference.

# Desktop / Python SDK 3.12.0

- Flight Data now shows all twelve System Health tiles beside the moving Quad X. Expand health enlarges both panels.
- Full-tile colors and short state labels distinguish faults, warnings, current signals and unused inputs. Flight-input health follows the selected source and its reported timeout independently of the telemetry connection.
- The Quad X, horizon and degree readouts share one attitude estimate. Zero yaw resets their relative reference together. The view clears on sensor failure or link loss and resumes on fresh IMU telemetry.

# Desktop / Python SDK 3.11.0

- Reworked Configuration → PID / settings around two gain matrices and a measured-versus-target response graph. The inner rate loop has three axes. The outer attitude loop has roll and pitch.
- Added optional local roll/pitch linking, per-cell change highlighting, a local revert and a stick-to-target preview using the firmware's response scales.
- Retained untouched gains at controller precision. PID apply now compares active and stored gains at float32 precision and reports an unverified readback for the affected loop.

# Desktop / Python SDK 3.10.0

- Replaced the single Scopes plot with four views for motion, control response, IMU frequency spectra and receiver channels.
- Added per-trace legends and sample inspection, independent gyro and accelerometer frequency plots, a display freeze and access to the session CSV from Scopes.
- Receiver monitoring distinguishes physical PPM pulses from the channels accepted by the FC. Link, IMU, input and output freshness are shown alongside each view.
- The desktop uses receipt timestamps, draws gaps across signal loss and discards previous kit captures on reconnect. The existing 3.2.0 firmware and Arduino library support this release.

# Desktop / Python SDK 3.9.0

- Added a live PPM flight-mode switch check to the arming page.
- Added an original-versus-current settings comparison on the final review page.
- Added optional read-only verification of saved setup after the same kit restarts.

# Desktop / Python SDK 3.8.0

- Redesigned the nine setup pages with a shared progress indicator and step-specific visuals.
- Added two locally rendered Quad X models. The sensor step pairs the requested pose with the measured pose and reports capture progress and errors.
- Added live read-only PPM sticks to receiver calibration and retained access to physical channel readings, mapping and reversal.
- ESC calibration and motor output visuals use kit status and motor command readback. Final save continues to verify the kit before releasing the setup lock.

# Desktop / Python SDK 3.7.0

- Flight Data gives the primary flight display more room beside a compact two-stick transmitter. The display remains visible when switching to the GPS map.
- Added a moving horizon with labeled bank and pitch scales, a relative yaw tape, and degree readouts for roll, pitch and combined tilt.
- The instrument shows the controller’s arming state independently of attitude, including when a live status or sensor reading becomes unavailable.
- Added receipt timestamps to queued telemetry. Flight Data checks their age after a desktop stall and keeps the relative yaw reference across page switches while samples continue to arrive.

# Desktop / Python SDK 3.6.0

- Redesigned Flight Data with two dark gimbals on the left and a live attitude, relative yaw, motor command and health panel on the right.
- Added an offline geographic map alongside Joystick TX. Validated position updates from a future GPS telemetry decoder can center a location marker. Current firmware has no position message.
- Kept the transmitter accessible while sending. Switching to the map with the sender stopped releases local joystick and keyboard input.
- Required a valid FC output record for motor readouts, including the case where a partial record contained all four pulse widths.

# Desktop / Python SDK 3.5.0

- Redesigned Welcome with an original Areion emblem, six illustrated shortcuts and a dedicated Setup Wizard tile. Each tile supports mouse and keyboard feedback.
- Moved kit status and recent session activity below the launcher in a full-window layout.

# Desktop / Python SDK 3.4.0

- Welcome fills the window and displays the connected kit’s setup status and configured input. Offline startup leaves the link closed. The desktop no longer offers a Demo session.
- In Setup wizard, saving the flight input uses the kit configuration and changes only the source. On a completed kit, **Configuration → Input → Save input** and **Flight Data → Save & use input** preserve other saved settings and verified setup. Returning to a previously calibrated PPM receiver retains its qualification.
- Install the desktop with FC firmware 3.1.0 or 3.2.0. The release pairing is firmware and Arduino library 3.2.0.

# Desktop / Python SDK 3.3.0 — compact interface and reliable actions

- Fixed two competing enable-state updates on Read FC offsets and removed duplicate calibration telemetry rendering; read-only capture cannot briefly enable.
- Kept buttons at content width, removed repetitive guidance and shortened labels throughout current console pages. Added responsive top connection controls and plain IMU tab labels.
- Avoided unchanged TX/RX repaint/tooltips on every refresh.
- Recoverable UDP OS errors no longer permanently retire a path. RPC retries preserve frame/session/sequence; CONTROL is not replayed. Genuine loss, permanent errors and freshness limits still stop controls.
- Allowed bounded SAVE acknowledgement delay without weakening saved readback. Missing acknowledgement remains an unknown outcome.
- Made keyboard mapping saves atomic and applied live keys only after successful persistence.
- Added regression tests for held clicks through telemetry, capture permissions, delayed SAVE via localhost UDP, transient/permanent errors, header scaling, compact actions and failed keyboard saves.

# Desktop / Python SDK 3.2.1 — FC main and Arduino library 3.2.0

- Accepts qualified firmware 3.1.0 and 3.2.0, with required schema checks and connection cleanup retained. Unknown versions and missing setup/PID groups still reject connection.
- Uses the same version compatibility check on the Firmware page; Demo explicitly identifies simulated firmware.
- Includes the complete top-navigation desktop and all modules/assets from 3.2.0. No flight-control, calibration, settings-save or input logic changes in this desktop patch.
- Use this ZIP with the supplied Arduino 3.2.0 release. The original Python 3.2.0 ZIP accepted only firmware 3.1.0.

# Desktop / Python SDK 3.2.0 — firmware and Arduino library remain 3.1.0

- Moves navigation to a compact fixed top bar with icons, TX/RX activity and shared USB/AP connection controls. Removes the sidebar and duplicate page-level connection bars. Keeps DISARM / STOP in a persistent status strip.
- Groups calibration, input and PID under Configuration; adds a useful Welcome screen, separate Scopes and honest firmware-version information. HITL and flashing remain unavailable rather than simulated as working features.
- Keeps the dark transmitter and gives telemetry more width. Existing control-source save, live PID persistence, arming locks and calibration state machines are retained.
- Replaces the wizard's left step list with a gated step selector/progress strip. Preserves scroll position and pinned Back/Next/Finish controls, including setup-lock retry.
- Exposes the existing receiver capture engine as direct PPM recalibration. Unsaved receiver edits or an active capture cannot release the calibration lock. First-time PPM configuration still uses Setup wizard.
- Adds successful per-path transmit counters to the Python SDK for measured frame rates. No wire-format/schema or firmware changes; Demo meters explicitly show SIM.
- Extends startup checks for new modules and all navigation icons. Extract the complete release into a new folder.

# Python desktop 3.1.1 — firmware/SDK/Arduino library remain 3.1.0

- Restores the dark transmitter card, gimbals and controls while retaining the flight telemetry dashboard.
- Adds direct IMU calibration under IMU calibration → Calibrate & save, plus a dedicated ESC calibration sidebar page with endpoint and motor-verification tabs.
- Reuses the existing firmware calibration lock, readback, one-shot ESC request and motor watchdog. Page opening is read-only; explicit Begin/Resume is required, and Finish verifies the current stored settings without overwriting unrelated PID/profile values.
- Preserves capture/button scroll stability, cancellation on focus/navigation/connection loss, pending ESC state over reconnect, and failed-save ARM locking. A delayed motor-start request is cancelled if focus or the propeller-removal confirmation is lost.
- Reading an ESC result before Resume remains read-only across focus/navigation changes; it cannot accidentally send DISARM and cancel the scheduled request.
- Documents the existing PWM output's lack of custom ESC tone commands. No motor pulses or flight-control code were changed to synthesize sound.
- Separates GUI and SDK version checks so the complete 3.1.1 desktop uses the unchanged 3.1.0 protocol packages. Startup preflight requires calibration_page.py.

# Firmware / Arduino library / Python desktop / SDK 3.1.0

- Adds optional **Reset all settings** on wizard step 1, with explicit confirmation, progress and verified active/stored readback. Reset restores configuration defaults, clears setup evidence and pending ESC requests, and retains the ARM lock. Continue/reload uses the current kit settings instead; entering setup retains still-valid checks for review rather than forcing every calibration again.
- Fixes wizard scroll jumps when capture, motor-test or save controls become disabled. Mouse-wheel value protection and deliberate keyboard editing remain available.
- Adds **Apply to FC** PID transactions: disarmed changes save and verify in one action. Explicit secured-tripod tuning applies gains live in RAM while armed, then saves automatically after DISARM. Pending/saved/error status is visible; power must remain connected until saving is confirmed. Successful dedicated PID saves retain previously completed setup; ordinary setting writes still invalidate relevant checks.
- Adds persistent **Save & use input** on Transmitter for PPM/AP/USB, with active/stored verification and neutral recovery. Qualified PPM can be selected again after digital operation; unverified PPM still requires wizard calibration. AP/USB require a CH5–CH8 mode channel. Input selection never starts sending or arms.
- Combines a light joystick panel with an adjacent cockpit: current health tiles, animated attitude, relative gyro yaw, rates/ACC and commanded motor pulses. Missing/stale/offline data does not remain green. No compass, RPM, GPS, battery or CPU measurement is fabricated.
- Allows Transmitter ↔ PID navigation to retain the established sender only with explicit secured-tripod tuning enabled. Other navigation, focus loss, Stop and stall protections remain active.
- Adds PID status/action groups 136/137 and RESET_ALL/INPUT_SAVE actions. Requires matching 3.1.0 firmware, Arduino library and desktop/SDK. Fixed A1 wiring, PWM and flight PID/Kalman equations remain unchanged.
- Software/demo verification does not establish target-board, ESC, sensor, receiver or flight validation. See VALIDATION.txt for the performed checks. Older entries below describe their historical releases; current behavior is documented in README.md.

# Firmware / Arduino library / Python desktop / SDK 3.0.2

- Removes the required wizard transmitter-off / PPM loss-and-recovery check. Step 8 is Arming & flight modes. The legacy result stays unmodified; final save, reboot restore and PPM eligibility no longer require it. Runtime PPM/USB/AP input-loss stops and neutral recovery remain active.
- Fixes offline window closing and detaches scroll filters when a window closes, avoiding accumulated UI overhead.
- Prevents wheel and trackpad gestures from changing numeric, combo or slider values throughout pages and owned dialogs. Page entry focuses the container; deliberate typing, keys, clicks and dragging still work.
- Removes repeated Live data whole-table autosizing, batches changed cell updates and renders charts/table only on the visible page. Incoming telemetry and safety processing continue.
- Retains setup ARM locking, receiver calibration, sensor and motor checks, verified persistence, ESC one-shot recovery, fixed pins/PWM and the existing flight PID equations.

# Firmware / Arduino library / Python desktop / SDK 3.0.1

- Cancels the owned close timer after shutdown; late worker replies and final hide events cannot touch deleted Qt controls.
- Requires all three matching 3.0.1 components. The Arduino library fixes ownership release/recovery while ESC calibration blocks ordinary settings writes; the firmware and desktop changes depend on that behavior.
- Adds a connection bar on every wizard step. Explicit Reconnect replaces a stale USB/AP link without a separate Connections-page disconnect, keeps the current step and reads saved same-kit progress. Offline values are labelled as last confirmed. Different kits do not inherit confirmations; incomplete captures and motor tests do not resume.
- Fixes frozen setup attitude: firmware updates Kalman roll/pitch while setup keeps flight outputs locked. Adds a smooth artificial horizon with bank scale, pitch ladder and relative gyro-yaw tape. Yaw can drift, has no absolute heading reference, resets on gaps/session changes and has an explicit reset control.
- Emits the first ESC MAX pulse before AP initialization; AP becomes available in LOW. The one-shot high/low sequence is followed by automatic, nonblocking IMU startup in the same boot with minimum outputs. A second power cycle is no longer required. Repeated scheduling during calibration/recovery is blocked.
- Adds explicit Read calibration result and sensor-startup progress. Reconnect reads the saved result rather than repeating calibration or erasing prior checks. ESC tones/result still require operator confirmation; a signal sequence is not proof of ESC acceptance.
- IMU recovery failure keeps outputs at minimum and setup locked. No real kit, ESC compatibility or flight test is claimed; see VALIDATION.txt for performed checks.
- Fixed A1 pins, PWM settings and PID equations remain unchanged. The 3.0.0 entries below describe historical behavior and are superseded where this release changes reconnect or ESC recovery.

# Firmware / Arduino library / Python desktop / SDK 3.0.0

- Requires all three matching 3.0.0 components. Install the Arduino library and the complete firmware sketch with both helper headers, then extract the full Python package into a fresh folder. Existing protocol-2 framing and previous group schemas remain compatible; setup adds groups 130/131/132/134/135.
- Replaces the 15-page wizard with nine pages: safety/connection, aircraft, input/wiring, sensors, PPM receiver, ESC calibration, motor outputs, arming/failsafe and final review/save. Consolidates repeated choices and keeps fixed pins, illustrated profiles and 2D wiring. No wizard PID gain editors or hardware 3D view.
- Adds a firmware-owned persistent ARM lock. Fresh/upgraded firmware starts locked; reopening setup re-locks completed kits. Exit, disconnect and reboot do not unlock. Completion requires verified settings and physical checks, saves its private completion record last and never auto-arms. Changed settings invalidate readiness and dependent checks.
- Adds raw PPM group 131 independent of the neutral gate, endpoint/center/reverse capture in persistent group 132 and saved physical-channel mapping/deadband in group 134. PPM is normalized before the existing logical receiver/gesture/control path. AP/USB skip PPM-specific verification.
- Persists selected boot source and individual motor idle outputs in group 134. The immediate group-110 source selector remains RAM-only. Fixed A1 pins, 250 Hz/12-bit PWM configuration and PID/Kalman equations are retained.
- Runtime source switching cannot reuse digital-only completion to arm unverified PPM. AP/USB flight-mode channels are restricted to CH5–CH8 to avoid their four logical stick axes. Changed arming/flight-mode/timeout settings clear dependent receiver/failsafe checks.
- Adds explicit, one-time next-startup ESC endpoint calibration. The request is consumed before the first maximum PWM output; its dedicated boot skips normal IMU initialization and runs a bounded nonblocking high/low sequence. A normal power cycle is then required before motor testing. Interrupted sequences do not retry automatically, and operator verification or an explicit calibration-not-required confirmation remains necessary.
- Adds independent single/all-motor bench testing at 1000–1500 µs without flight ARM. Firmware enforces owner/session binding, a 350 ms refresh watchdog and 30-second maximum session. Recorded minima/order/direction remain physical operator observations, not measured RPM.
- Adds adjustable PPM arming/disarming/idle timing with existing 5/1/15-second defaults, low/high flight-mode mapping, timeout controls and source-loss/recovery confirmation. PPM failsafe confirmation additionally requires firmware-observed loss during setup.
- Adds verified final active/stored readback for groups 2/3/4/6/7/112/132/134 and schema-4 local backup/receipt handling. Partial/unknown outcomes are reported; local/demo files cannot grant real ARM permission.
- Reports unresolved ESC cancellation persistence as an error while stopping current output. Repeated STOP does not falsely confirm durable cancellation; recovery requires readback with ESC power disconnected. Unknown final-write outcomes are resolved from actual FC state after recovery.
- Retains six-position additive ACC calibration and corrected g preview. ACC scale remains diagnostic and gyro zero remains Python-only; neither is silently written to firmware.
- Erase/reset, STA, other airframes/mixers, alternate ESC waveforms and remote gyro-bias/reboot operations remain unsupported. See VALIDATION.txt for actual test results; no target-hardware or flight qualification is claimed by these release notes.

## Earlier releases

The entries below describe their historical release behavior; 3.0.0 supersedes their firmware/runtime and setup limitations.

# Python desktop / SDK 2.8.1

- Validates all bundled desktop files and icons before GUI startup; reports exact missing paths, including wizard_extended.py.
- Checks GUI package version and exact location along with the existing SDK checks. Setup report includes the actual GUI and wizard module paths.
- Complete ZIP extracts to a versioned folder to make PyCharm script selection explicit and reduce accidental merges with an old project.
- All v2.8.0 setup, calibration, fixed pins and profile features are retained. No flight control or firmware logic changes.

# Python desktop / SDK 2.8.0

- Uses Areion FC A1 consistently as the board name and replaces editable pin planning with a fixed read-only connection reference.
- Replaces the hardware 3D viewer with a 2D map showing OUT1–OUT4, PPM D10 and IMU SDA/SCL connections. Removes runtime mesh/CAD assets.
- Replaces ESC parameter editors with illustrated Standard 50 Hz, PWM 250 Hz and OneShot profile cards. Every selection retains the existing fixed 250 Hz/12-bit/1000–2000 µs output configuration; profile identity does not enable a different waveform.
- Shows corrected ACC g readings beside each additive offset, removing the active FC correction before applying the draft correction in Python.
- Adds six illustrated ACC positions, individual fresh/stationary captures, progress/results, additive-offset estimates and diagnostic scale checks. Only additive offsets can be saved to the existing FC.
- Adds stationary gyro-zero capture and corrected Python rate display. FC boot calibration remains unchanged; gyro bias is not written to the FC.
- Replaces wizard P/I/D editors with illustrated drone profiles and default PID loading. Later manual tuning remains on the existing PID & settings page.
- Migrates older local drafts to fixed board/output settings and wizard profile defaults. No automatic FC writes occur during migration or selection.
- Firmware/library remain 2.5.0. The 15-step flow, verified supported section saves and preview-only motor page remain; PPM receiver calibration is still the next pending stage.

# Python desktop / SDK 2.7.0

- Extends Setup Wizard from six to 15 steps, then a pending PPM receiver-calibration page.
- Adds input selection, pin plan, logical wiring, supplied PCB interactive 3D, ESC settings, guided ACC/gyro checks, output preparation, single/all-motor preview, PID profiles and configuration review/save.
- Adds fresh stationary-sample checks, additive ACC candidates with provenance, gyro residual display and no automatic sensor writes.
- Limits motor preview to 1000–1500 µs; real hardware Start is disabled. No ARM/CONTROL fallback. Preview candidates are unverified.
- Adds independently editable Aerion 450 and Aerion 250 profiles; 250 is explicitly an untuned stable-baseline template.
- Adds explicit supported ACC/Rate/Angle PID apply/save with readback, storage/disarmed checks and partial-failure reporting; source apply remains RAM-only.
- Adds schema-2 local draft saving, v1 migration, full setup diagnostics and an extension contract for future firmware integration.
- Corrects DemoLink's D3 GPIO readback from 3 to 21. Actual protocol/control/receiver behavior is unchanged.
- Firmware and Arduino library remain 2.5.0. Full hardware config, erase, STA, motor tests and PPM RX calibration remain pending.

# Python desktop / SDK 2.6.0

- New Setup wizard section: propeller confirmation, USB/AP connection and erase placeholder, vehicle type, drone profile, frame class and quad layout, each with 2D visuals.
- Every wizard visit starts at the propeller-removal warning; Next requires explicit confirmation. The first Back button remains visible and disabled.
- Connection reuses the console's existing session. The selected path must be fresh/confirmed and the FC disarmed to continue. Erase is disabled with 0% progress and an explicit unavailable status.
- Defaults: Multirotor, F450-style ESC, Quadcopter, Quad X. Future vehicle/profile/frame classes are disabled. Quad + and Quad H are local geometry drafts only.
- Quad X reference: M1 front left CW, M2 front right CCW, M3 back right CW, M4 back left CCW.
- Back/Next on the first five pages; Back/Save & Next on the layout page. Local draft saving is atomic, verified by readback, restored on launch, and does not restore the safety acknowledgement.
- Save & Next opens a pending-steps page. Setup stays incomplete; no firmware erase, apply/save, motor test, flight-ready flag or new control command is added.
- Copy diagnostics includes wizard selections and local/incomplete state. Existing control, telemetry, SDK and firmware behavior are retained. Firmware stays 2.5.0.

# Python desktop / SDK 2.5.2

- PPM mode displays physical receiver channels on both GUI sticks, AUX indicators and channel bars. Mode2 layout maps yaw/throttle left and roll/pitch right.
- PPM widgets are read-only. Incoming telemetry never becomes outgoing CONTROL values; monitoring does not start a sender or arm the FC.
- Freshness, active-source and neutral readiness are checked. Lost/stale input blanks the sticks; absent auxiliary channels show no value. Cached channel arrays preceding a source/readiness transition are not labelled as current PPM.
- USB/AP controls and the prior startup/install fix are retained. Firmware remains2.5.0; no firmware update is required from that version.

# Python desktop / SDK 2.5.1

- Requirements install the bundled SDK, including its control.py module, as well as PySide6 and pyserial.
- install_requirements.py runs pip using the selected interpreter and this project directory.
- Startup selects the complete bundled SDK before imports. It detects missing files, mixed local versions and an older SDK cached by a persistent Python Console.
- Error messages distinguish dependencies from incomplete/mixed project files. They report relevant interpreter and package paths.
- main.py --check verifies imports and prints diagnostics without opening serial or network connections.
- Firmware compatibility stays at 2.5.0. Flight-mode settings, keyboard routing, ControlSession, protocol, schemas, ARM/DISARM, PID and motor behavior are unchanged.

Use a fresh extraction of the whole ZIP, then Run install_requirements.py and main.py with the same PyCharm interpreter.
