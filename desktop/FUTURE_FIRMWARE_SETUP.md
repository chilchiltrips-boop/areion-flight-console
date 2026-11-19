# Areion FC A1 setup contract and remaining limits

This filename is retained for existing links. The setup lifecycle described
below is **implemented in the matching 3.1.0 firmware, Arduino library and
Python release**. It is no longer a future motor/receiver API. Protocol framing
remains version 2. Existing settings schemas are retained; new setup groups use
schema 1. Install all three matching components and all firmware helper headers.

## Persistent lock and verified completion

A fresh kit without a valid completion record starts locked. Existing valid
3.0.x stored setup is restored and verified on 3.1.0. BEGIN locks a completed configuration
durably before acknowledging and retains current settings and still-valid
physical confirmations for review. RESET_ALL explicitly clears them. Repeated
BEGIN while already locked resumes the current setup. Closing the wizard,
disconnecting, restarting or rebooting does not grant ARM permission.

FINALIZE requires a disarmed kit, no active/pending ESC or motor test, verified
sensors, verified receiver when PPM is selected, verified or explicitly skipped
ESC calibration, all four motor checks, and matching
active/stored copies of groups 2/3/4/6/7/112/132/134. The private completion record
is saved and verified last; only then is the setup lock cleared. Completion
never arms and resets the neutral-input gate. Normal IMU, freshness, ownership
and explicit PPM gesture/AP/USB ARM checks still apply.

Ordinary changed configuration durably re-locks a completed kit before accepting
the change. Dedicated PID and INPUT_SAVE transactions have the verified
persistence/eligibility paths described below and can retain prior completion.
For ordinary changes, relevant evidence is cleared: ACC changes invalidate sensor checks;
source/mapping/receiver/timing changes invalidate dependent receiver/failsafe
checks; profile changes invalidate physical checks; changed motor-idle values
invalidate those motors' confirmation. Identical settings do not clear valid
evidence. No ordinary SET or SAVE can write the private completion record.

Python verifies each requested section before and after applying/saving. A
later failure does not undo earlier saved sections. Read active and stored
values after an unknown timeout/disconnect result. A local JSON receipt is a
historical backup, never authority to unlock the FC.
An operation error is not proof that no durable write occurred. After recovery,
read the actual setup status: a verified complete record may be recognized by a
later normal boot even when the previous host transaction was unconfirmed.

## New array definitions

| Group | Ordered fields | Access |
| --- | --- | --- |
| 130 SETUP_STATUS | Locked, Complete, Stage, EscState, MotorVerifiedMask, SensorVerified, ReceiverVerified, FailsafeVerified, MotorTestActive, TestM1Us, TestM2Us, TestM3Us, TestM4Us, Revision, Fault, KitId | Read-only |
| 131 RAW_PPM | RawCH1 … RawCH8, ChannelCount, Fresh, AgeMs | Read-only |
| 132 RX_CALIBRATION | `[Min,Center,Max,Reverse]` repeated eight times, in physical-channel order | Writable/persistent |
| 134 SETUP_CONFIG | Profile, BootSource, RollChannel, PitchChannel, ThrottleChannel, YawChannel, DeadbandUs, MotorIdle1 … MotorIdle4 | Writable/persistent |
| 135 SETUP_ACTION | Command string followed by exactly four integer arguments | Command-only |
| 136 PID_TUNING_STATUS | Pending, Revision, SavedRevision, Error | Read-only |
| 137 PID_TUNING_ACTION | PID group, explicit Boolean bench confirmation, nine float slots | Command-only |

Group 130 stages: 0 idle, 1 setup, 2 ESC pending restart, 3 ESC high, 4 ESC low,
5 ESC sequence complete, 6 motor test, 7 interrupted. ESC states: 0 unchecked,
1 pending, 2 running, 3 sequence completed, 4 operator verified, 5 calibration
not required, 6 interrupted/failed. Motor mask bits 1/2/4/8 correspond to M1–M4.
The four test values are bench commands in the range 1000–1500 µs, not measured
rotor speeds. Group 23 reports actual commanded output, including 2000 µs during
the dedicated ESC high phase.

Raw PPM is independent of the guarded/normalized group 22. Missing or stale raw
pulses are zero. Group 131 targets 20 Hz while setup is locked. Channel count
and freshness/age must be checked before consuming values.

Group 132 defaults to `[1000,1500,2000,0]` for each channel. Min is 900–1500,
Center 900–2100, Max 1500–2100 and Reverse 0/1. Each channel needs at least a
400 µs span with its center at least 100 µs from either end. Throttle
normalization uses its endpoints, not its stored center.

Group 134 defaults to `[0,0,1,2,3,4,5,1180,1180,1180,1180]`. Profile IDs are
0 Areion 450, 1 Areion 250, 2 Areion Quad X, 3 Generic Quad X. BootSource IDs
are 0 PPM, 1 AP, 2 USB. Axis channels are four unique values from 1–8; the
flight-mode channel cannot overlap them. Deadband is 0–50 µs, and each motor
idle output is 1000–1500 µs. Firmware normalizes mapped PPM into logical
Roll/Pitch/Throttle/Yaw before neutral/gesture/control processing. AUX values
are retained. Group 110 remains the immediate RAM source selector; saved group
134 determines the next startup's source.
The RAM-only group-110 selector cannot bypass the saved-source qualification.
The dedicated INPUT_SAVE action can change both current and saved source,
including returning to PPM after AP/USB when its receiver check is still valid.
An unverified receiver must be configured and checked in the wizard first. AP/USB require flight mode on
CH5–CH8, since digital logical CH1–CH4 are the stick axes. Rejected SETs report
`INVALID_VALUES`; an incompatible digital ARM reports `SETUP_INPUT_NOT_VERIFIED`.

Group 130 index 7 (`FailsafeVerified`) and `FAILSAFE_OK` are retained only for optional legacy clients. They are not required for completion, completion restore, PPM selection or arming in 3.1.0. Runtime signal-loss handling is unchanged. The desktop wizard no longer sends this action.

## Setup actions

All actions have exactly five values: `[Command,Arg0,Arg1,Arg2,Arg3]`. All unused
arguments are zero. Firmware validates count, type, phase, owner/session and
disarmed state. Command acknowledgement is followed by fresh status readback.

| Command | Four arguments | Purpose |
| --- | --- | --- |
| BEGIN | `[0,0,0,0]` or `[1,0,0,0]` | 0 requests immediate lock; 1 also acknowledges props removed. Retains current settings and valid checks; does not fabricate a propeller confirmation. |
| RESET_ALL | `[1,0,0,0]` | With confirmed setup lock, props removed and explicit consent, restore configuration defaults, clear checks/pending ESC request, verify persistence and keep ARM locked. Blocked during active motor/ESC operations. |
| INPUT_SAVE | `[source,0,0,0]` | While disarmed, save and activate 0 PPM / 1 AP / 2 USB. Check eligibility and stored readback; reset neutral readiness. |
| STOP | `[0,0,0,0]` | Stop bench/ESC output and request durable cancellation of pending ESC calibration; keep lock. A storage failure returns `ESC_CANCEL_NOT_PERSISTED`. Existing DISARM action 123 has the same cancellation behavior. |
| SENSOR_OK | `[1,0,0,0]` | Record explicit orientation/ACC review with fresh valid IMU and active/stored ACC match. |
| RX_OK | `[1,0,0,0]` | PPM-only verification with saved calibration/mapping, fresh raw channels and neutral normalized input. |
| FAILSAFE_OK | `[1,0,0,0]` | Record operator-confirmed source-loss/recovery. PPM also requires an observed fresh-to-lost transition during setup. |
| ESC_SCHEDULE | `[1,0,0,0]` | Save one next-startup request after sensor and, for PPM, receiver checks. No high pulse during scheduling. |
| ESC_VERIFY | `[1,0,0,0]` | After the sequence and automatic IMU startup, record the operator's confirmation of ESC tones/result. Fresh ready sensors are required. |
| ESC_SKIP | `[1,0,0,0]` | Explicitly record that this ESC does not require endpoint calibration. Motor checks remain required. |
| MOTOR_START | `[mask,1,0,0]` | Acknowledge props/battery; start selected motors at 1000 µs only after ESC verified/skipped. |
| MOTOR_SET | `[mask,us,0,0]` | Update the same active mask, 1000–1500 µs, and refresh its watchdog. Cannot start an inactive session. |
| MOTOR_STOP | `[0,0,0,0]` | Stop bench outputs; retain valid evidence, never unlock. |
| MOTOR_OK | `[mask,1,0,0]` | After a stopped test, record operator-confirmed position, direction and reliable start for those motors. |
| FINALIZE | `[0,0,0,0]` | Verify all settings/checks and commit completion last; release lock without arming. |

The wizard exposes connection options and explicit Reconnect on every page.
Stale USB/AP handles are replaced without replaying control or settings. The
same KitId resumes its saved progress/current step; a new kit cannot inherit
physical confirmations. Offline retained values are clearly last-confirmed,
not current readback. The Arduino library separates ownership release/recovery
from the settings write guard, allowing reconnect while calibration blocks writes.

Opening/resuming the desktop wizard first reads current setup/status. It does
not send an unconditional DISARM when reconnecting to an already locked
pending/running ESC sequence, because DISARM is an explicit cancel operation.
If pending-request cancellation cannot be persisted, current outputs still stop,
but the old durable request may remain. Keep ESC power disconnected until
storage recovers, explicitly clear the pending request and verify readback.
Repeated STOP cannot turn an unresolved persistence failure into success.

## PID application and saved input

Group 137 carries `[group, bench_confirmed, value1, ..., value9]`. Group is
integer 2 or 3; confirmation is Boolean. Rate PID uses nine finite float gains.
Angle PID uses six gains and three `0.0` padding slots. Gain validation and
fresh owner/session checks still apply; active ESC/motor calibration blocks
this action. Armed application requires explicit secured-tripod confirmation,
completed setup and ready IMU/input. It applies gains in RAM without a flash
write. Disarmed application, including the next DISARM after live tuning,
saves the pending gains and verifies persistence. Until group 136 Pending is
false, Revision equals SavedRevision and Error is empty, the change must not
be labelled durable. Keep power connected until that result is confirmed.

The save temporarily establishes a durable lock before changing stored PID,
then restores a previously completed configuration only after the stored
settings and retained physical checks verify. An error keeps the kit locked.
It never grants completion to a kit that was incomplete beforehand. Ordinary
PID SET/SAVE is a separate path and still invalidates configuration readiness.

INPUT_SAVE is disarmed-only. It saves group 134's boot source, selects group
110 and verifies the stored copy. PPM requires a valid retained receiver check;
AP/USB require an AUX flight-mode channel. A completed kit retains completion
only after settings/evidence checks pass. Input is neutralized and requires
fresh neutral recovery; no sender or ARM is started. Wizard changes to axis
mapping or receiver calibration still require the affected checks again.

RESET_ALL restores every supported settings section to its compiled default
and clears physical checks and pending calibration. Python compares both active
and stored values to those defaults before displaying success. It never releases
the setup lock. A failed reset is potentially partial; read current kit settings
before continuing. Reset does not change fixed pins, PWM or firmware.

## ESC and motor execution

The ESC request is consumed and recorded as running **before the first maximum
PWM output** on its dedicated calibration boot. MAX is the first commanded pulse,
before AP initialization. The nonblocking sequence uses three seconds high, then
three seconds low, then minimum. AP startup is deferred until LOW; AP telemetry
may therefore first show the low phase or a persisted result. It is locally
bounded even if the host disappears. Reset or power interruption while running
yields an interrupted state and no automatic retry. A normal startup without a
pending request does not run calibration.

After the sequence, firmware performs nonblocking IMU startup automatically in
the same boot while holding outputs at minimum. Normal sensor readiness typically
takes about 3.5 seconds after the sequence. Sensor failure keeps setup locked and
reports the fault; motor tests and confirmation cannot bypass readiness. Repeated
scheduling while calibration or sensor recovery is in progress is rejected.

The physical flow is: schedule, disconnect both USB and LiPo, follow the ESC
maker's power-up procedure for the calibration boot, wait for the sequence and
stationary IMU startup, reconnect through USB/AP, read the result, confirm the
ESC response, then perform motor testing. No second power cycle is required.
USB-only power does not calibrate ESCs that have no battery supply. Reconnecting
reads progress instead of scheduling the operation again.

Power-up order, compatible signal and calibration tones depend on the ESC
model. Three-second pulse stages are the implemented FC sequence, not a
universal ESC acceptance guarantee. The operator must verify the model's
procedure/result or explicitly confirm calibration is not needed. Profiles
do not enable 50 Hz, OneShot or DShot output: fixed output remains 250 Hz,
12-bit, 1000–2000 µs and duty limits 1024–2048.

Independent motor testing does not use flight ARM or the flight mixer. Every
new session starts at 1000 µs; unselected motors remain at minimum. Firmware
limits output to 1000–1500 µs, requires refresh within 350 ms and stops a
session after 30 seconds. Owner/session loss and STOP/DISARM stop outputs.
There is no background resume/replay and no flash write for each slider update.
Motor minima and number/direction confirmations are physical operator
observations. The software reports commands, not measured RPM or rotation.

## Sensor and local-data scope

ACC telemetry already contains the active additive correction. Python preview
subtracts that correction before adding the draft value. SixFaceCalibration
estimates opposing-face additive offsets; only those offsets, within ±0.5 g,
can be saved in group 6. Scale/fit and off-axis information are diagnostic,
not an applied full scale/misalignment calibration.

GyroCalibration measures residual rates after the existing boot calibration.
Its zero correction affects only the Python preview. There is no FC gyro-bias
write, remote gyro recalibration or hardware reboot command. Fresh, finite,
stationary sensor samples and session/provenance checks remain required.
Historical captures and demo estimates never become new hardware observations.

Locked setup continues updating roll/pitch attitude, fixing the old early-return
freeze of group 21 Kalman fields. The Python horizon smoothly paints those angles
and integrates fresh gyro rates for relative yaw. Relative yaw has no magnetic
reference, may drift and is display-only; it resets on session change/data gaps
and stops when data is stale. Near-vertical pitch makes its yaw estimate
unavailable. The user can explicitly reset the relative reference.

Local schema 4 stores fixed board settings, profile identities, captures and
provenance, receiver settings, motor observations and an optional final FC
receipt. Verified completion can be recorded locally; `hardware_applied` is
false in demo. Physical acknowledgements are never restored as permission.
Local saves are atomic and read back; their failure is distinct from the FC's
actual completion status.

## Fixed board and remaining unsupported operations

A1 wiring is fixed: outputs D0/D1/D2/D3 (GPIO 0/1/2/21), PPM D10 (GPIO 18),
SDA D4 (GPIO 22), SCL D5 (GPIO 23). The GUI provides a 2D signal map, not
editable pin assignments or a hardware 3D viewer. Supported airframe is Quad X
with brushless ESCs; aircraft pictures share the stable PID baseline. Manual
PID editing remains on PID & settings; the dedicated PID action preserves
previously completed readiness only after its verified save succeeds.

STA, other vehicle types/frame mixers, new ESC output protocols,
ACC scale/misalignment writes, gyro-bias writes, hardware reboot/flashing and
automatic rotor-speed/direction measurement remain unsupported. These limits
are not bypassed by changing a version string or selecting a profile image.
