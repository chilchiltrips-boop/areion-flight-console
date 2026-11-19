"""Evidence-based cockpit indicators; colors never imply unreported sensors."""
from dataclasses import dataclass
import math

from .scope_data import FRESH_SECONDS


@dataclass(frozen=True)
class Health:
    state: str
    label: str
    detail: str

    @property
    def color(self):
        return self.state


SOURCES = ('PPM', 'AP', 'USB')
KEYS = ('TELEMETRY', 'INPUT', 'PPM', 'AP', 'USB', 'IMU', 'OUTPUT',
        'CONFIG', 'LOOP', 'MODE', 'ARM', 'STORAGE')


def _record(groups, group, length):
    value = groups.get(group)
    return value if isinstance(value, (list, tuple)) and len(value) == length else None


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _selected_source(groups, inputs):
    if inputs and _integer(inputs[0], 0, 2):
        return inputs[0]
    runtime = _record(groups, 110, 1)
    if runtime and _integer(runtime[0], 0, 2):
        return runtime[0]
    boot = _record(groups, 134, 11)
    return boot[1] if boot and _integer(boot[1], 0, 2) else None


def _input_health(groups, inputs, selected, elapsed, armed):
    # Link transport and the selected control input are independent. A spare
    # receiver can continue reporting pulses while a USB control input is used.
    by_source = {name: Health('gray', 'INACTIVE', f'{name} is not the selected flight input.')
                 for name in SOURCES}
    if selected is None:
        by_source = {name: Health('gray', 'UNKNOWN', 'Waiting for the FC to report its selected input.')
                     for name in SOURCES}
    source_name = SOURCES[selected] if selected is not None else None
    valid = (inputs and _integer(inputs[0], 0, 2) and _integer(inputs[1], 0, 3)
             and all(type(inputs[i]) is bool for i in (2, 3, 4, 8))
             and _integer(inputs[5], 0, 8) and _integer(inputs[6], 0, 0xffffffff)
             and _integer(inputs[7], 0, 0xffffffff))
    if groups.get(122) is None:
        health = Health('amber', 'WAITING', 'Waiting for the FC input status report.')
    elif not _number(elapsed) or not 0 <= elapsed <= FRESH_SECONDS:
        health = Health('amber', 'STALE', 'Input status telemetry is stale or its receipt time is unavailable.')
    elif not valid:
        health = Health('red', 'INVALID', 'The kit reported an invalid input status.')
    else:
        active = inputs[1]
        ready, count, age, owner = inputs[4:8]
        signal = inputs[(2, 3, 8)[selected]]
        counts_valid = count >= 4 if selected == 0 else count == 8
        timeout_settings = _record(groups, 112, 2)
        timeout_index = int(selected != 0)
        timeout = (timeout_settings[timeout_index] if timeout_settings
                   and _integer(timeout_settings[0], 50, 1000)
                   and _integer(timeout_settings[1], 100, 500) else 250)
        if (ready and (not signal or not counts_valid or active != selected + 1
                       or selected != 0 and not owner)) or (not ready and active != 0):
            health = Health('red', 'INVALID', 'Ready, active source, owner or channel count is inconsistent.')
        elif not signal:
            health = (Health('red', 'LOST', f'{source_name} signal is absent while the latest FC status is armed.')
                      if armed else Health('amber', 'WAITING', f'Waiting for a signal on the selected {source_name} input.'))
        elif not counts_valid:
            health = Health('amber', 'CHANNELS', 'Signal detected. Waiting for the configured input channels.')
        elif age >= timeout:
            health = Health('amber', 'STALE', f'The FC reported a {source_name} frame age of {age} ms (timeout {timeout} ms).')
        elif not ready:
            health = Health('amber', 'NEUTRAL', 'Signal is present. The FC is waiting for neutral sticks.')
            by_source[source_name] = Health('green', 'SIGNAL', f'The selected {source_name} has a fresh signal. The input gate is waiting for neutral.')
        else:
            health = Health('green', source_name + ' LIVE', 'Fresh control input accepted by the FC.')
            detail = ('The FC is receiving PPM pulses. See the TX indicator for transmitter status.'
                      if selected == 0 else f'The FC is receiving the selected {source_name} input.')
            by_source[source_name] = Health('green', 'SIGNAL', detail)
    if source_name and by_source[source_name].state == 'gray':
        by_source[source_name] = health
    return {'INPUT': health, **by_source}


def flight_status(groups, connected, *, input_age_s=0.0, tx_status=None):
    """Classify current FC evidence. The caller expires dynamic telemetry.

    input_age_s measures time since the last group 122 report. Its frame age
    measures time since the last input at the FC when it sampled that report.
    New input can arrive at the FC between successive reports.
    """
    groups = groups if hasattr(groups, 'get') else {}
    status = _record(groups, 120, 10)
    inputs = _record(groups, 122, 9)
    setup = _record(groups, 130, 16)
    selected = _selected_source(groups, inputs)

    if not connected:
        result = {key: Health('gray', 'OFFLINE', 'Current kit telemetry is unavailable.') for key in KEYS}
        result['TELEMETRY'] = Health('red', 'OFFLINE', 'No confirmed live connection to the flight controller.')
        for name in SOURCES:
            result[name] = Health('gray', 'INACTIVE', 'No active input on this connection.')
        if selected is not None:
            result['INPUT'] = Health('amber', SOURCES[selected], 'Last selected input; reconnect to confirm its current signal.')
            result[SOURCES[selected]] = Health('amber', 'SELECTED', 'Configured input; no current signal readback while offline.')
        return result

    result = {}
    valid_status = bool(status and all(type(status[i]) is bool for i in (0, 1, 2, 7, 8, 9))
                        and _number(status[4]) and _integer(status[3], 0, 8)
                        and _integer(status[5], 0, 0x7fffffff) and _integer(status[6], 0, 0xffffffff))
    if valid_status:
        result['TELEMETRY'] = Health('green', 'LIVE', 'Fresh flight-controller status is being received.')
    elif groups.get(120) is not None:
        result['TELEMETRY'] = Health('red', 'INVALID', 'The flight-controller status record is malformed or non-finite.')
    else:
        result['TELEMETRY'] = Health('amber', 'WAITING', 'Link connected; current flight-controller status has not arrived or is stale.')

    result.update(_input_health(groups, inputs, selected, input_age_s, valid_status and status[0]))
    if selected == 0 and tx_status is not None and tx_status.code == 'off':
        # A verified AUX loss marker can coexist with valid, accepted PPM.
        # Keep explicit FC input errors and armed signal-loss alarms intact.
        if tx_status.label == 'TX OFF' and result['INPUT'].state != 'red':
            result['INPUT'] = result['PPM'] = Health('amber', 'TX OFF', tx_status.detail)

    imu = _record(groups, 21, 10)
    imu_finite = bool(imu and all(_number(v) for v in imu))
    imu_note = 'I2C/IMU readback; electrical bus integrity is not measured.'
    if setup and setup[14] == 'IMU_STARTUP_FAILED':
        result['IMU'] = Health('red', 'STARTUP', 'The FC reported IMU startup failure.')
    elif valid_status and status[5] == 0:
        result['IMU'] = Health('amber', 'CALIBRATING', 'Waiting for a valid gyro calibration sample.')
    elif valid_status and not status[2]:
        result['IMU'] = Health('red', 'NO READ', 'The FC reports invalid IMU reads. ' + imu_note)
    elif groups.get(21) is not None and not imu_finite:
        result['IMU'] = Health('red', 'INVALID', 'IMU values are malformed or non-finite. ' + imu_note)
    elif valid_status and status[2] and imu_finite:
        result['IMU'] = Health('green', 'READING', 'Fresh finite sensor values and FC read-valid flag. ' + imu_note)
    else:
        result['IMU'] = Health('amber', 'WAITING', 'Waiting for fresh IMU values and FC read-valid status. ' + imu_note)

    outputs = _record(groups, 23, 12)
    output_ok = bool(outputs and all(_number(v) and 1000 <= v <= 2000 for v in outputs[3:7]))
    if setup and setup[14] == 'MOTOR_OUTPUT_FAILED':
        result['OUTPUT'] = Health('red', 'FAULT', 'The FC reported a motor-output write failure.')
    elif groups.get(23) is not None and not output_ok:
        result['OUTPUT'] = Health('red', 'INVALID', 'Motor command readback is malformed or outside 1000–2000 µs. RPM is not measured.')
    elif output_ok:
        label = 'MINIMUM' if max(outputs[3:7]) <= 1000 else 'COMMANDS'
        result['OUTPUT'] = Health('green', label, 'Fresh commanded PWM pulses are reported. This does not measure rotation, RPM or ESC acceptance.')
    else:
        ready = bool(setup and setup[4] == 15)
        result['OUTPUT'] = Health('amber', 'READY' if ready else 'WAITING',
                                  'Motor checks are recorded; waiting for current output commands. No RPM feedback.' if ready
                                  else 'No fresh motor-command readback. No RPM feedback is available.')

    setup_ok = bool(setup and all(type(setup[i]) is bool for i in (0, 1, 5, 6, 7, 8))
                    and _integer(setup[4], 0, 15) and type(setup[14]) is str)
    pid = _record(groups, 136, 4)
    pid_ok = bool(pid and type(pid[0]) is bool and _integer(pid[1], 0, 4294967295)
                  and _integer(pid[2], 0, 4294967295) and type(pid[3]) is str)
    if setup_ok and setup[14]:
        result['CONFIG'] = Health('red', 'FAULT', setup[14])
    elif pid_ok and pid[3]:
        result['CONFIG'] = Health('red', 'SAVE ERROR', pid[3])
    elif groups.get(130) is not None and not setup_ok:
        result['CONFIG'] = Health('red', 'INVALID', 'Setup status is malformed.')
    elif groups.get(136) is not None and not pid_ok:
        result['CONFIG'] = Health('red', 'INVALID', 'PID save status is malformed.')
    elif pid_ok and pid[0]:
        result['CONFIG'] = Health('amber', 'PID UNSAVED', 'PID changes are active in RAM; waiting for disarm to save.')
    elif pid_ok and pid[1] != pid[2]:
        result['CONFIG'] = Health('amber', 'UNVERIFIED', 'The active and saved PID revisions differ.')
    elif valid_status and not status[7]:
        result['CONFIG'] = Health('amber', 'STORAGE', 'Configuration storage is unavailable.')
    elif setup_ok and setup[1] and not setup[0]:
        result['CONFIG'] = Health('green', 'SAVED', 'The FC reports verified setup completion.')
    else:
        result['CONFIG'] = Health('amber', 'SETUP' if setup_ok else 'WAITING', 'Setup is incomplete or current completion status is unavailable.')

    device = _record(groups, 125, 12)
    target = device[1] if device and _number(device[1]) and device[1] > 0 else None
    dt = status[4] if valid_status else None
    if dt is None:
        result['LOOP'] = Health('amber', 'WAITING', 'No current control-loop interval. CPU usage is not measured.')
    elif not .001 <= dt <= .008:
        result['LOOP'] = Health('red', 'TIMING', 'Reported loop interval is outside 1–8 ms. CPU usage is not measured.')
    else:
        hz = 1. / dt
        normal = target is not None and .8 * target <= hz <= 1.2 * target
        result['LOOP'] = Health('green' if normal else 'amber', f'{hz:.0f} Hz',
                                f'Derived from the latest loop interval ({dt * 1000:.2f} ms); '
                                + (f'target {target:g} Hz. ' if target else 'target unavailable. ')
                                + 'This is not CPU load or a timing histogram.')
    if valid_status:
        mode = 'ANGLE' if status[1] else 'RATE'
        reasons = [f'{key} {result[key].label}' for key in ('INPUT', 'CONFIG', 'IMU')
                   if result[key].state != 'green']
        if result['OUTPUT'].state == 'red':
            reasons.append(f"OUTPUT {result['OUTPUT'].label}")
        detail = f'The FC reports {mode} mode.'
        if reasons:
            detail += ' Check ' + ', '.join(reasons) + '.'
        result['MODE'] = Health('amber' if reasons else 'green', mode, detail)
    else:
        result['MODE'] = Health('amber', 'WAITING', 'Waiting for the current FC mode.')
    if valid_status:
        result['ARM'] = Health('green' if status[0] else 'gray', 'ARMED' if status[0] else 'DISARMED',
                               'Current FC arm state. This indicator does not issue commands.')
    else:
        result['ARM'] = Health(result['TELEMETRY'].state, 'UNKNOWN', 'No valid, fresh FC arm-state confirmation.')
    result['STORAGE'] = Health('green' if status[7] else 'red', 'READY' if status[7] else 'FAULT',
                               'FC persistent-storage status; pending PID saves are shown under CONFIG.') if valid_status else Health('amber', 'WAITING', 'No current persistent-storage status.')
    return {key: result[key] for key in KEYS}
