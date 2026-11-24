# Zebjus Areion Link 3.12.3

Install this project's SDK into a Python 3.10+ environment. Scripts can use the
array/command API without the Qt GUI. Use **desktop/SDK 3.12.3 + firmware 3.4.0 +
ZebjusAreionLink Arduino library 3.4.0** together. Firmware 3.1.0, 3.2.0 and 3.3.0 remain supported. The runtime rejects mismatched
firmware. Existing wire framing remains protocol 2 and existing group schemas
are retained, including setup groups 130/131/132/134/135 introduced in 3.0.0.
Release 3.1.0 added PID status/action groups 136/137 and guarded RESET_ALL/INPUT_SAVE actions.

The flight calculations, fixed A1 pins and PWM configuration remain onboard.
The setup lifecycle includes persistent locking, raw PPM normalization,
one-time next-startup ESC calibration and independent guarded motor testing.
Release 3.1.0 adds verified settings reset, saved source switching and PID
tuning with disarmed persistence.
The existing Python control/transports remain available, subject to the setup
lock and normal freshness/neutral/ownership checks. Owner release/recovery
during calibration remains supported without allowing ordinary settings writes.
Updating only the desktop cannot add the new firmware transactions.

From this extracted project folder:

```sh
python -m pip install .
```

For the desktop GUI, Run `install_requirements.py` with the same PyCharm
interpreter, then Run `main.py`. Alternatively run
`python -m pip install -r requirements.txt` from this project folder;
it installs the local SDK too.
The desktop and SDK support FC firmware 3.1.0, 3.2.0, 3.3.0 and 3.4.0. The web console Firmware page supplies the current sketch and its two matching Arduino libraries.

## Responsibilities

Python sends eight channel setpoints and explicit commands. The Arduino main
reads the MPU6050, computes Kalman/Angle PID/Rate PID, mixes motors, drives ESCs,
and returns sensor/status/output arrays. Python does not send sensor readings,
computed PID corrections or telemetry acknowledgements back into the flight loop.
HELLO/PING/session management and command replies remain part of the link.

PPM alone uses the original yaw/throttle hold gestures and idle auto-disarm.
USB/AP channels never arm or disarm: use `link.arm()` and `link.disarm()`. Low
throttle by itself does not disarm USB/AP, even after the PPM idle timer elapses.
Selected-input loss and invalid IMU still stop motors in every source; commands
do not bypass those guards or the new persistent setup ARM lock. The shared ThrottleLow threshold still guards ARM.
An explicit DISARM remains available to the current owner even in PPM mode.

## Setup lifecycle and compatibility

Fresh firmware without a valid saved completion record starts locked. Existing
valid 3.0.x stored setup remains readable. Read group 130 before treating ARM as
available: `Locked` must be false and `Complete` true. Successful setup saving
does not arm; a new explicit arm request/gesture and neutral readiness are still
required. Entering setup durably re-locks completed kits while retaining
current settings and still-valid checks. RESET_ALL clears those settings/checks
only after explicit confirmation. Exit, reboot and disconnect cannot release
the setup lock. Ordinary changed settings invalidate readiness; copying a local
wizard JSON or calling an ordinary SAVE cannot fabricate completion. Dedicated
PID and INPUT_SAVE transactions can preserve previously verified completion
after their persistence and eligibility checks succeed.

The desktop's `areion_gui.setup_backend.run_setup_action` implements verified
read/apply/save and finalization for the GUI. It checks active/stored copies and
records partial failures. The standalone SDK exposes the same underlying
`Link` operations; callers are responsible for sequencing physical checks and
readback. `link.action(135, [command, arg0, arg1, arg2, arg3], schema=1)` submits
a setup action. Use fresh group 130 readback to confirm its result. Do not use
ARM, channel throttle or a CONTROL frame as a substitute for a motor-test action.

| Group/schema | Contents | Access |
| --- | --- | --- |
| 130/1 | Lock/completion, stage, ESC state, motor/sensor/RX checks and optional legacy loss-test flag, bench state/output, revision, fault, kit ID | Read/telemetry |
| 131/1 | Eight raw PPM pulses, count, freshness, age | Read/telemetry |
| 132/1 | `[Min,Center,Max,Reverse]` repeated for eight physical channels | Read/SET/SAVE |
| 134/1 | Profile, boot source, four axis channels, deadband, four motor idle values | Read/SET/SAVE |
| 135/1 | `[Command,Arg0,Arg1,Arg2,Arg3]`, including RESET_ALL and INPUT_SAVE | ACTION only |
| 136/1 | Pending, Revision, SavedRevision, Error | Read/telemetry |
| 137/1 | Group, BenchConfirmed, Value1 … Value9 | PID ACTION only |

The low-level group 110 selector still changes active input in RAM only.
Group 134 stores boot source (0 PPM, 1 AP, 2 USB). The GUI uses INPUT_SAVE to
change both with verified persistence and fresh neutral recovery; see below.
A previously qualified PPM receiver can be selected after AP/USB operation.
Unverified PPM requires wizard receiver checks first. AP/USB flight-mode
selection must use CH5–CH8, because logical CH1–CH4 carry the four stick axes.
Ordinary group-134 SET/SAVE operations still invalidate dependent receiver
checks. Profiles do not enable another frame mixer or ESC waveform. See
[FUTURE_FIRMWARE_SETUP.md](FUTURE_FIRMWARE_SETUP.md) for exact fields, actions,
verification requirements and unsupported features.

The ESC action is an explicitly requested, single-use next-boot sequence. Its
request is consumed before the high pulse; interrupted execution is not retried
automatically. Operator confirmation of the specific ESC's result is required
afterward. MAX is emitted before AP initialization; AP starts during LOW. After
the high/low sequence, a nonblocking IMU startup runs automatically in the same
boot, with outputs at minimum and flight locked. Keep the kit still, reconnect,
read groups 120/130 and wait for fresh valid group 21 before confirming the ESC
response and testing motors. No second power cycle is required. A completed
signal sequence is not proof that the ESC accepted calibration. IMU startup
failure leaves outputs at minimum and does not permit motor testing. The motor bench API stays separate
from flight ARM and enforces a
350 ms command watchdog, 30-second maximum session, owner/session binding and
1000–1500 µs test range. Animation/output readback is not RPM feedback.

STOP/DISARM stops current output immediately. If cancellation cannot be stored,
the operation returns `ESC_CANCEL_NOT_PERSISTED`; repeated STOP must not be
treated as proof that the old next-startup request was erased. Keep ESC power
disconnected until storage recovers and the pending state is explicitly cleared
and read back. A failed or timed-out save can have an unknown durable outcome:
read current setup status after recovery. Boot may recognize a fully committed
completion record even if the preceding host call did not receive confirmation.

## Explicit reconnect and live attitude

The GUI connection bar can replace a stale USB/AP connection from any wizard
step. It reads the same kit’s authoritative saved state before resuming; it does
not replay settings, motor targets, CONTROL or ARM. A completed sensor or receiver
check stored on the FC does not need to be recreated merely because the transport
changed. Incomplete captures stop and must be repeated. SDK applications should
close the old Link, construct a new Link for the selected transport and read back
state after reconnecting. A low-level Link never silently reopens a closed device.

The desktop artificial horizon uses group 21 Kalman roll/pitch and fresh gyro
rates to animate relative yaw. There is no absolute heading sensor. This Python
yaw reference can drift, resets after a new session/gap, and can be reset explicitly
by the user. It is display-only and is never transmitted into the flight loop.

## Saved input, reset and PID transactions

These actions are available with firmware 3.1.0 and 3.2.0. Confirm the result by reading it back from the kit. A timeout leaves the result unknown.

For **saved input selection**, stop any sender and require DISARMED, then issue
`link.action(135, ["INPUT_SAVE", source, 0, 0, 0], schema=1)`. Read group 110
and active/stored group 134 to confirm the source and stored copy match. The
transaction changes only the boot input in group 134. It preserves the saved
profile, axis mapping, motor idle values, PID and calibrations. The FC renews
an existing completion record after verification. Source 0 requires a verified
PPM receiver. AP and USB require a mode channel on CH5–CH8. Every switch
requires fresh neutral input. The desktop helper
`areion_gui.backend.save_input` handles the transaction and readback.

For **reset**, enter the persistent setup lock with BEGIN, require DISARMED,
props removed and explicit reset consent, then issue
`link.action(135, ["RESET_ALL", 1, 0, 0, 0], schema=1)`. Active motor/ESC operations
block it. Reset restores groups 2/3/4/6/7/112/132/134 to defaults, clears setup
checks and pending ESC requests, and keeps ARM locked. Verify every active and
stored section plus group 130 before reporting success. A partial/error result
requires readback before continuing. The wizard handles this through
`run_setup_action(..., "reset_all", ...)` and does not use a local-file deletion
as a substitute for resetting the FC.

For **PID**, use ACTION group 137/schema 1 with exactly 11 fields:
`[group, bench_confirmed, value1, ..., value9]`. `group` is integer 2 (nine Rate
PID gains) or 3 (six Angle PID gains followed by three zero padding slots),
`bench_confirmed` is an explicit Boolean, and all nine gain slots are finite
floats validated against the registered PID fields. Disarmed application saves
and verifies immediately. While armed, the explicit secured-bench confirmation
is required and gains apply in RAM only; the FC automatically saves pending
PID after DISARM. Keep power connected until group 136 reports Pending=false,
matching Revision/SavedRevision and no Error. Verify active/stored PID readback
when reporting a durable result. Loss of power before the pending save loses
those unsaved gains.

The desktop helper `areion_gui.backend.apply_pid` sends this transaction and
verifies its active/saved result. It does not ARM/DISARM or send ordinary
SET/SAVE. Standalone SDK clients use `Link.action` and `read_group` directly.
A successful dedicated PID transaction can preserve prior verified setup;
a storage failure locks ARM. An ordinary `set_group(2/3)` still follows the
configuration-invalidation rules and is not live tuning. No call bypasses
input, IMU, ownership, calibration-busy or setup guards.

## Existing array API

| Call | Meaning |
|---|---|
| `Link(UDP("192.168.4.1", 8080)).connect()` | Connect through AP; join the drone Wi-Fi first |
| `Link(SerialTransport(port)).connect()` | Connect through USB; allow startup/calibration after opening serial |
| `link.set_group(110, [1])` | Select AP flight input while disarmed; 0=PPM, 1=AP, 2=USB |
| `link.send_control(channels, datagram_only=True)` | Send one AP frame: exactly eight integers, each 1000..2000 |
| `link.send_control(channels, serial_only=True)` | Send one USB frame; no automatic route fallback |
| `link.arm(datagram_only=True)` | Send ACTION `["ARM"]` through AP; use serial_only for USB |
| `link.disarm()` | Send ACTION `["DISARM"]` through confirmed paths |
| `link.read_group(21)` | Read the ten IMU/rate/angle values as a Python list |
| `link.poll(timeout=0)` | Receive the next telemetry message, or None; `list(message.data)` is its array |
| `link.poll_timed(timeout=0)` | Receive the next `(message, received_at)` pair, or `None`. `received_at` is the host monotonic time when the transport received the bytes. Both poll methods consume the same queue. |
| `link.set_group(6, [-0.10, 0.03, 0.12], schema=2)` | Apply accelerometer offsets while disarmed |
| `link.save_group(6, schema=2)` | Explicitly save that group; no implicit save |

ARM/DISARM are one-time commands with replies, not an extra Boolean appended to
the channel array. After verified setup completion, the digital eight-channel mapping stays:

```python
channels = [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000]
#           roll  pitch throttle yaw   mode  aux6  aux7  aux8
```

IMU group 21 returns this order:

```python
[RateRoll, RatePitch, RateYaw, AccX, AccY, AccZ,
 AngleRoll, AnglePitch, KalmanAngleRoll, KalmanAnglePitch]
```

Other arrays use registered group/schema definitions in
`zebjus_areion_link/schema.py`. The protocol supports finite floats, integers,
Booleans and strings, within each group's schema. It does not treat arbitrary
text or unregistered arrays as motor commands. To extend your own sketch, bind
a new group on Arduino and use `read_group`/`set_group` on Python.

## Receiving PPM arrays

With PPM selected on the FC, group22/schema1 returns its accepted CH1..CH8 array:
`[Roll, Pitch, Throttle, Yaw, CH5, CH6, CH7, CH8]`. The first four values are
normalized logical controls after the saved PPM calibration/mapping, not
necessarily physical channels 1–4. Group122/schema2 identifies
selected source (index0:0=PPM), active source (index1:1=PPM), PPM freshness
(index2), input readiness (index4) and available channel count (index5).

Use `link.poll(0)` to consume the existing stream and inspect `message.group`
and `list(message.data)`. For a one-time read use `link.read_group(22, schema=1)`.
Keep source/status and channel timestamps fresh before labelling values live;
do not interpret missing auxiliary channels as physical readings. The FC
neutral-input gate must first become ready. Monitoring does not need
`send_control`, `arm`, or a ControlSession. The connection heartbeat remains.

For calibration independent of that gate, read **group 131/schema 1**:
`[RawCH1, ..., RawCH8, ChannelCount, Fresh, AgeMs]`. Missing/stale pulses are
zero; do not display them as live input. This group targets 20 Hz while setup is
locked. It reports physical PPM pulses before normalization and does not require
ARM or a sender. Persist endpoint calibration in group 132 and mapping in 134;
normal monitoring continues to use accepted logical group 22.

Accepted channel telemetry is nominally 6.7 Hz; it is separate from the
250 Hz flight-loop target. The GUI's PPM monitor is an example of receiving and
displaying these arrays without sending them back as control input.

## Saved flight-mode mapping

Group7/schema3 is `[channel, angle_scale, rate_scale, yaw_scale, low_mode, high_mode]`.
Mode IDs are 0=ANGLE, 1=RATE/ACRO; Low and High must differ. Below 1500 selects Low,
and 1500 or above selects High for the configured channel on PPM, USB or AP.
Defaults are `[5, 0.10, 0.15, 0.15, 0, 1]`. Preserve the other current values when editing:

```python
# Disarmed, sender stopped; uses an already connected Link.
settings = link.read_group(7, schema=3)
settings[0] = 5                     # CH5
settings[4:6] = [0, 1]             # Low ANGLE, High RATE/ACRO
link.set_group(7, settings, schema=3)
active = link.read_group(7, schema=3)
link.save_group(7, schema=3)
saved = link.read_group(7, saved=True, schema=3)
```

During an established USB/AP control session, set `channels[settings[0]-1]` to
1000 for Low or 2000 for High and pass the complete array to `session.apply`.
Keep ticking the session normally. Use an AUX channel (CH5–CH8) for digital control and ensure the physical PPM
mode channel does not overlap any saved receiver-axis assignment. Status group120 index1 is `AngleMode`:
true=ANGLE, false=RATE/ACRO. Confirm with fresh telemetry, not the requested value.
Valid old schema2 channel/scales migrate into RAM on boot; explicit Save upgrades
that stored group to schema3. PID/offset sections retain their previous schemas. Ordinary changed settings
re-lock a completed configuration and invalidate dependent setup checks; the
dedicated PID transaction described above has its own verified persistence path. A section SAVE
does not release that lock; finish the guarded setup flow again.

## Runnable examples

After installing the SDK, run from this project or copy the example into another project:

```sh
python examples/read_arrays.py --ap 192.168.4.1
python examples/read_arrays.py --usb /dev/cu.usbmodemYOURPORT
python examples/control_arrays.py --ap 192.168.4.1 --seconds 5
python examples/control_arrays.py --usb /dev/cu.usbmodemYOURPORT --seconds 5
```

For an AP app or PyCharm, save the kit gains while disarmed and select **AP Wi-Fi** in Flight Data. Disconnect the web console so Python can own the link. For USB, select **USB** and release its port before starting the example. The 3.x sample uses the input already saved on the kit.

The read example receives telemetry. The control example sends eight neutral channels at 50 Hz and disarms on exit. With setup complete, the optional `--arm` flag requests ARM at neutral throttle and verifies the reply. On a physical PPM receiver, use the configured radio gestures. The browser joystick and keyboard are available in Flight Data when the browser is the USB or AP sender.

For applications that generate current channel values, import
`ControlSession` and `NEUTRAL_CHANNELS` from `zebjus_areion_link`. Start using fresh
FC/input/setup status, then call `session.tick(time.monotonic())` in your application
loop and `session.apply(channels)` when ready. `tick` targets one transmission
every 20 ms, without catch-up bursts. Stop the session before a DISARM request.
The control example shows nonblocking RPC use, ARM cancellation, readback and
cleanup. Your program must keep the active control loop responsive; a pause
over 150 ms stops the scheduler. There is no background control replay after Stop.

The three rates differ: FC flight-loop target 250 Hz, Python channel-send target
50 Hz, and received IMU telemetry nominally about 13 Hz (other streamed groups
about 6.7 Hz). Python/USB/Wi-Fi are not hard real-time; these rates are not measured
minimum guarantees on the physical board. PID/Kalman remain onboard even when a
Python project uses the returned data for plots, analysis or higher-level inputs.

## Transport activity in 3.2.0

`Link.transport_status` now includes a monotonically increasing `sent_frames`
counter for each path. It increments after a successful transport write, including
handshake, retries, requests, heartbeat and control frames. Failed writes and
filtered-out paths do not increment it. This is not proof of a remote ACK or
RF signal strength. Existing `received_frames` / `rejected_frames` remain available.
Frame encoding, protocol schemas, retries and control routing are unchanged.

## Transport recovery in 3.3.0

Temporary UDP operating-system errors preserve the existing socket. A command retry reuses its exact frame and sequence within the configured retry budget. CONTROL errors propagate immediately; controls are never replayed automatically. No error extends receive freshness or the ownership health timer. Permanent errors still disable the path. Diagnostics include `transient_errors`; a valid received frame clears the last temporary error message.

`save_group` waits at least 1.25 seconds per configured attempt for the storage ACK (the GUI uses two attempts). Other RPC, telemetry and input freshness deadlines are unchanged. SAVE timeout means the result is unknown: read back before another mutation. GUI saves still require verified stored values. These changes do not implement automatic reconnect, re-arm or motor restart.
