"""In-process FC used only by the regression suite."""
import math
import queue
import time

from areion_gui.model import NEUTRAL, validate_values, equal_values, flight_mode_for_value
from areion_gui.setup_backend import SETUP_SETTINGS
from zebjus_areion_link import Message
from zebjus_areion_link.schema import DRONE_GROUPS


def make_test_window():
    from areion_gui.window import MainWindow

    window = MainWindow()
    link = DemoLink()
    groups = (120, 122, 121, 125, 110, 130, 131, 132, 134, 136)
    window.install_link(link, {g: link.read_group(g, DRONE_GROUPS[g]['schema']) for g in groups})
    window.navigate(0)
    return window



class DemoLink:
    """Offline model of the firmware lifecycle. It never opens hardware.

    Simulated storage is per instance. A restart restores it, but no DEMO result
    is transferable as proof that a real kit was calibrated.
    """
    demo = True
    session = 424242
    fc_session = 300000
    event_drops = 0

    def __init__(self, clock=None):
        self._clock = time.monotonic if clock is None else clock
        self.connected = True
        self.storage_available = True
        self.imu_valid = True
        self.values = {group: [field['default'] for field in DRONE_GROUPS[group]['fields']]
                       for group in SETUP_SETTINGS}
        self.saved = {group: values[:] for group, values in self.values.items()}
        self.source = self.values[134][1]
        self.channels = list(NEUTRAL)
        self.raw_channels = list(NEUTRAL)
        self.raw_count = 8
        self.raw_enabled = True
        self.raw_updated = self._clock()
        self._ppm_was_fresh = False
        self._ppm_loss_seen = False
        self.armed = False
        self.last_control = None
        self.last_emit = 0
        self.events = queue.Queue()
        self.seq = 0
        self.started = self._clock()
        self._setup = [True, False, 0, 0, 0, False, False, False, False,
                       1000, 1000, 1000, 1000, 0, '', 'DEMO-AREION-FC-A1']
        self._stored_setup = self._setup[:]
        self._motor_mask = 0
        self._motor_tested = 0
        self._motor_moved = 0
        self._motor_last = self._motor_started = None
        self._motor_owner = None
        self._esc_started = None
        self._esc_boot = False
        self._imu_recover_at = None
        self.calibration_samples = 2000
        self._esc_cancel_uncertain = False
        self._setup_store_healthy = True
        self._pid_pending = False
        self._pid_revision = self._pid_saved_revision = 0
        self._pid_error = ''
        self._pid_snapshot = {}
        self._pid_restore_complete = False

    @property
    def transport_status(self):
        return [{'name': 'DEMO ' + name, 'active': self.connected, 'confirmed': self.connected,
                 'datagram': udp, 'last_received_age': 0.01, 'healthy': self.connected,
                 'error': '', 'rejected': 0} for name, udp in [('USB', False), ('AP', True)]]

    def _fresh(self):
        return self.last_control is not None and self._clock() - self.last_control < self.values[112][1] / 1000

    def _stop_motor(self, verified_stop=False):
        if self._setup[8] and verified_stop:
            self._motor_tested |= self._motor_moved
        self._setup[8] = False
        self._setup[9:13] = [1000] * 4
        self._motor_mask = self._motor_moved = 0
        self._motor_last = self._motor_started = self._motor_owner = None
        if self._setup[2] == 6:
            self._setup[2] = 1

    def _persist(self):
        if not self.storage_available or not self._setup_store_healthy:
            self._setup_store_healthy = False
            self._setup[0:2] = [True, False]
            self._setup[14] = 'DEMO_STORAGE_FAILURE'
            self._stop_motor()
            self.armed = False
            raise RuntimeError('STORAGE_FAILURE')
        self._stored_setup = self._setup[:]
        # Output leases never survive restart.
        self._stored_setup[8:13] = [False, 1000, 1000, 1000, 1000]

    def _store_setting(self, group, values):
        """Simulated NVS boundary, also used to inject durable-write failures."""
        if not self.storage_available or not self._setup_store_healthy:
            raise RuntimeError('STORAGE_FAILURE')
        self.saved[group] = list(values)

    def _storage_fault(self, message):
        self._setup_store_healthy = False
        self._setup[0:3] = [True, False, 1]
        self._setup[14] = str(message)
        self.armed = False
        self.last_control = None
        self._stop_motor()

    def _flush_pid(self):
        if not self._pid_pending or self.armed or not self._setup_store_healthy:
            return
        try:
            self._setup[0:3] = [True, False, 1]
            self.last_control = None
            self.channels = list(NEUTRAL)
            self._persist()  # A power loss from this point cannot restore ARM eligibility.
            for group in (2, 3):
                self._store_setting(group, self._pid_snapshot[group])
                if not equal_values(self.saved[group], self._pid_snapshot[group]):
                    raise RuntimeError('PID_READBACK_FAILED')
            if self._pid_restore_complete:
                if not self._settings_saved(SETUP_SETTINGS) or not self._physical_checks_valid():
                    raise RuntimeError('PID_CONFIG_NOT_VERIFIED')
                self._setup[0:3] = [False, True, 0]
                self._setup[13] += 1
            self._setup[14] = ''
            self._persist()
            self._pid_saved_revision = self._pid_revision
            self._pid_pending = False
            self._pid_restore_complete = False
            self._pid_error = ''
        except Exception as error:
            self._pid_error = str(error)
            self._storage_fault('PID_SAVE_FAILED: ' + str(error))
            raise RuntimeError('PID_SAVE_FAILED: ' + str(error)) from error

    def _pid_apply(self, payload):
        if not isinstance(payload, (list, tuple)) or len(payload) != 11:
            raise ValueError('ACTION_DATA')
        group, bench, *values = payload
        if type(group) is not int or group not in (2, 3) or type(bench) is not bool:
            raise ValueError('ACTION_DATA')
        if any(type(value) is not float or not math.isfinite(value) for value in values):
            raise ValueError('ACTION_DATA')
        if group == 3 and values[6:] != [0, 0, 0]:
            raise ValueError('PID_ANGLE_PADDING')
        requested = validate_values(group, values[:9 if group == 2 else 6])
        if not self.storage_available or not self._setup_store_healthy:
            raise RuntimeError('SETUP_STORAGE_LOCKED')
        if self._esc_boot or self._setup[8] or self._setup[3] in (1, 2):
            raise ValueError('CALIBRATION_BUSY')
        if self.armed:
            if not bench:
                raise ValueError('PID_BENCH_CONFIRM_REQUIRED')
            fresh = self.raw_enabled and self.raw_count >= 4 if self.source == 0 else self._fresh()
            if self._setup[0] or not self._setup[1] or not fresh or not self.imu_valid:
                raise ValueError('PID_TUNING_NOT_READY')
        changed = not equal_values(self.values[group], requested)
        if changed and self._pid_revision == 0xffffffff:
            raise ValueError('PID_REVISION_EXHAUSTED')
        if changed or not self._settings_saved((group,)):
            if not self._pid_pending:
                self._pid_restore_complete = not self._setup[0] and self._setup[1]
            if changed:
                self._pid_revision += 1
            self.values[group] = list(requested)
            self._pid_snapshot = {item: self.values[item][:] for item in (2, 3)}
            self._pid_pending = True
            self._pid_error = ''
        if self._pid_pending and not self.armed:
            self._flush_pid()
        return ['PID_APPLIED_PENDING_SAVE' if self._pid_pending else 'PID_SAVED']

    def _reset_all(self, args):
        if args != [1, 0, 0, 0]:
            raise ValueError('CONFIRM_REQUIRED')
        if not self._setup[0] or self._setup[1] or self._setup[2] == 0:
            raise ValueError('SETUP_NOT_ACTIVE')
        if self._setup[8] or self._setup[3] == 2:
            raise ValueError('CALIBRATION_BUSY')
        pending_esc = self._setup[3] == 1
        self._setup[0:9] = [True, False, 1, 0, 0, False, False, False, False]
        self._setup[14] = ''
        self._stop_motor()
        self._motor_tested = 0
        self._ppm_loss_seen = False
        self.last_control = None
        self.channels = list(NEUTRAL)
        try:
            self._persist()
        except Exception as error:
            if pending_esc:
                self._esc_cancel_uncertain = True
                self._setup[3] = 6
                self._storage_fault('RESET_ESC_CANCEL_NOT_PERSISTED')
                raise RuntimeError('RESET_ESC_CANCEL_NOT_PERSISTED') from error
            self._storage_fault('RESET_SAVE_FAILED')
            raise
        try:
            for group in SETUP_SETTINGS:
                defaults = [field['default'] for field in DRONE_GROUPS[group]['fields']]
                self.values[group] = defaults
                self._store_setting(group, defaults)
                if not equal_values(defaults, self.saved[group]):
                    raise RuntimeError('RESET_READBACK_FAILED')
            self.source = self.values[134][1]
            self._pid_pending = False
            self._pid_revision = self._pid_saved_revision = 0
            self._pid_error = ''
            self._pid_snapshot = {}
            self._pid_restore_complete = False
            self._persist()
        except Exception as error:
            self._storage_fault('RESET_SAVE_FAILED')
            raise RuntimeError('RESET_SAVE_FAILED') from error
        return ['RESET_DEFAULTS_SAVED']

    def _input_save(self, args):
        source = args[0]
        if source not in (0, 1, 2) or args[1:] != [0, 0, 0]:
            raise ValueError('ACTION_DATA')
        if self._setup[8] or self._setup[3] in (1, 2) or self._pid_pending:
            raise ValueError('CALIBRATION_BUSY')
        if source == 0 and (not self._setup[6] or len(set(self.values[134][2:6])) != 4 or
                            self.values[7][0] in self.values[134][2:6]):
            raise ValueError('INPUT_PPM_NOT_VERIFIED')
        if source in (1, 2) and self.values[7][0] < 5:
            raise ValueError('INVALID_VALUES: digital flight mode needs CH5–CH8')
        complete = not self._setup[0] and self._setup[1]
        if complete and not self._settings_saved(SETUP_SETTINGS):
            self._setup[0:3] = [True, False, 1]
            self._persist()
            self._storage_fault('INPUT_CONFIG_NOT_VERIFIED')
            raise RuntimeError('INPUT_SAVE_FAILED')
        try:
            self._setup[0:3] = [True, False, 1]
            self._persist()
            changed = self.values[134][:]
            changed[1] = source
            self.values[134] = changed
            self._store_setting(134, changed)
            if not equal_values(changed, self.saved[134]):
                raise RuntimeError('INPUT_READBACK_FAILED')
            self.source = source
            self.last_control = None
            self.channels = list(NEUTRAL)
            if complete:
                if not self._physical_checks_valid():
                    raise RuntimeError('SETTINGS_NOT_SAVED_OR_MISMATCH')
                self._setup[0:3] = [False, True, 0]
                self._setup[13] += 1
            self._setup[14] = ''
            self._persist()
        except Exception as error:
            self._storage_fault('INPUT_SAVE_FAILED')
            raise RuntimeError('INPUT_SAVE_FAILED') from error
        return ['INPUT_SAVED']

    def _invalidate(self, group, previous, changed):
        if equal_values(previous, changed):
            return
        self._setup[0:2] = [True, False]
        self._setup[2] = 1
        self._setup[14] = ''
        self.armed = False
        self.last_control = None
        self._stop_motor()
        if group == 6:
            self._setup[5] = False
        if group in (4, 7, 112, 132):
            self._setup[6:8] = [False, False]
            self._ppm_loss_seen = False
        if group == 134:
            if previous[0] != changed[0]:
                self._setup[3:8] = [0, 0, False, False, False]
                self._motor_tested = 0
            elif previous[1:7] != changed[1:7]:
                self._setup[6:8] = [False, False]
                self._ppm_loss_seen = False
            for i, (old_idle, new_idle) in enumerate(zip(previous[7:11], changed[7:11])):
                if old_idle != new_idle:
                    self._setup[4] &= ~(1 << i)
        self._persist()

    def _tick(self):
        now = self._clock()
        ppm = self.connected and self.raw_enabled and self.raw_count >= 4
        if ppm:
            self.raw_updated = now
        if self._ppm_was_fresh and not ppm and self._setup[0]:
            self._ppm_loss_seen = True
        self._ppm_was_fresh = ppm
        if self._setup[8] and (not self.connected or self._motor_owner != self.session or
                self._motor_last is None or now - self._motor_last >= .350 or
                now - self._motor_started >= 30):
            self._stop_motor()
            self._setup[14] = 'MOTOR_TEST_TIMEOUT'
        if self._setup[8]:
            # This tick represents the simulated output write, rather than
            # treating receipt of a target as evidence that a motor was driven.
            for i, pulse in enumerate(self._setup[9:13]):
                if pulse > 1000:
                    self._motor_moved |= 1 << i
        if self._esc_started is not None:
            elapsed = now - self._esc_started
            if elapsed >= 6:
                self._esc_started = None
                self._setup[2:4] = [5, 3]
                self._persist()
                self._imu_recover_at = now
            elif elapsed >= 3:
                self._setup[2] = 4
        if self._imu_recover_at is not None:
            elapsed = now - self._imu_recover_at
            self.calibration_samples = min(2000, max(0, int((elapsed - .45) * 1000)))
            if elapsed >= 3.5:
                self._imu_recover_at = None
                self._esc_boot = False
                self.imu_valid = True
                self.calibration_samples = 2000
        if not self._fresh() and self.source != 0:
            self.armed = False
        if self.source == 0 and not ppm:
            self.armed = False
        if self._setup[0]:
            self.armed = False
        if self._pid_pending and not self.armed and self._setup_store_healthy:
            try:
                self._flush_pid()
            except RuntimeError:
                pass  # Telemetry must remain available to report a failed commit.

    def demo_set_receiver(self, values=None, fresh=True):
        """Explicit test/showroom receiver input; never a hardware command."""
        if values is not None:
            if not isinstance(values, (list, tuple)) or not 4 <= len(values) <= 8 or any(
                    type(v) is not int or not 900 <= v <= 2100 for v in values):
                raise ValueError('Demo PPM needs 4–8 integer channels within 900–2100 us.')
            self.raw_count = len(values)
            self.raw_channels = list(values) + [1000] * (8 - len(values))
        self.raw_enabled = bool(fresh)
        self._tick()

    def _normalized_ppm(self):
        output = []
        config, calibration = self.values[134], self.values[132]
        throttle_channel = config[4] - 1
        for i, value in enumerate(self.raw_channels):
            minimum, center, maximum, reverse = calibration[i * 4:i * 4 + 4]
            if i == throttle_channel:
                normalized = 1000 + (value - minimum) * 1000 / (maximum - minimum)
                if reverse:
                    normalized = 3000 - normalized
            else:
                delta = value - center
                normalized = 1500 if abs(delta) <= config[6] else (
                    1500 + delta * 500 / ((maximum - center) if delta >= 0 else (center - minimum)))
                if reverse:
                    normalized = 3000 - normalized
            output.append(round(max(1000, min(2000, normalized))))
        mapped = output[:]
        for role, channel in enumerate(config[2:6]):
            mapped[role] = output[channel - 1]
        return mapped

    def _neutral(self, values):
        return values[2] < self.values[4][0] and all(1400 <= values[i] <= 1600 for i in (0, 1, 3))

    def _settings_saved(self, groups):
        return all(equal_values(self.values[group], self.saved[group]) for group in groups)

    def _physical_checks_valid(self):
        config = self.values[134]
        return (self._setup[5] and (config[1] != 0 or self._setup[6]) and
                self._setup[4] == 15 and self._setup[3] in (4, 5) and
                len(set(config[2:6])) == 4 and self.values[7][0] not in config[2:6] and
                (config[1] == 0 or self.values[7][0] >= 5))

    def read_group(self, group, schema=1, saved=False, *, cancel=None):
        if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
            raise RuntimeError('READ_CANCELLED')
        if schema != DRONE_GROUPS[group]['schema']:
            raise ValueError('DEMO schema mismatch')
        self._tick()
        if saved:
            return self.saved[group][:]
        if group in self.values:
            return self.values[group][:]
        now = self._clock()
        t = now - self.started
        fresh = self.connected and ((self.raw_enabled and self.raw_count >= 4) if self.source == 0 else self._fresh())
        channels = self._normalized_ppm() if self.source == 0 and fresh else self.channels[:]
        ax = .04 * math.sin(t / 3) + self.values[6][0] + .10
        ay = .07 * math.cos(t / 4) + self.values[6][1] - .03
        az = 1. + self.values[6][2] - .12
        roll = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
        pitch = -math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
        if group == 21:
            return [2.3 * math.cos(t / 3), -math.sin(t / 4), .2 * math.sin(t),
                    ax, ay, az, roll, pitch, roll * .96, pitch * .96]
        if group == 22:
            return channels if fresh else list(NEUTRAL)
        if group == 23:
            motors = self._setup[9:13] if self._setup[8] else [channels[2] if self.armed and fresh else 1000] * 4
            if self._esc_started is not None:
                motors = [2000 if self._setup[2] == 3 else 1000] * 4
            return [0., 0., 0.] + [float(v) for v in motors] + [0.] * 5
        if group == 110:
            return [self.source]
        if group == 120:
            return [self.armed, flight_mode_for_value(self.values[7], channels[self.values[7][0] - 1]) == 0,
                    self.imu_valid, 8 if fresh else 0, .004, self.calibration_samples, int(t * 1000),
                    self.storage_available and self._setup_store_healthy, True, True]
        if group == 121:
            return [True, '192.168.4.1', 8080, 5000]
        if group == 122:
            age = int((now - self.last_control) * 1000) if self._fresh() else 4294967295
            return [self.source, self.source + 1 if fresh else 0, self.raw_enabled,
                    self.source == 1 and fresh, fresh, self.raw_count if self.source == 0 else (8 if fresh else 0),
                    0 if self.source == 0 and fresh else age, self.session, self.source == 2 and fresh]
        if group == 125:
            return ['3.2.0 DEMO', 250, 18, 0, 1, 2, 21, 250, 12, 1024, 2048, 50]
        if group == 130:
            return self._setup[:]
        if group == 131:
            ppm = self.connected and self.raw_enabled and self.raw_count >= 4
            raw = self.raw_channels[:self.raw_count] + [0] * (8 - self.raw_count)
            return (raw if ppm else [0] * 8) + [self.raw_count if ppm else 0, ppm,
                     0 if ppm else min(4294967295, int((now - self.raw_updated) * 1000))]
        if group == 136:
            return [self._pid_pending, self._pid_revision, self._pid_saved_revision, self._pid_error]
        raise ValueError('Unknown DEMO group')

    def set_group(self, group, values, schema=1):
        self._tick()
        if self.armed:
            raise ValueError('WRITE_LOCKED')
        validate_values(group, values)
        if schema != DRONE_GROUPS[group]['schema']:
            raise ValueError('SCHEMA_MISMATCH')
        if self._esc_boot or self._setup[8] or self._setup[3] in (1, 2):
            raise ValueError('CALIBRATION_BUSY')
        if group == 110:
            if values[0] == 0 and not self._setup[0] and (
                    self.values[134][1] != 0 or not self._setup[6]):
                raise ValueError('INVALID_VALUES: set up and verify PPM input first')
            if values[0] in (1, 2) and self.values[7][0] < 5:
                raise ValueError('INVALID_VALUES: digital flight mode needs CH5–CH8')
            self.source = values[0]
            self.last_control = None
            self.channels = list(NEUTRAL)
        elif group in SETUP_SETTINGS:
            if group == 132:
                for i in range(8):
                    lo, center, hi, _ = values[i * 4:i * 4 + 4]
                    if hi - lo < 400 or center - lo < 100 or hi - center < 100:
                        raise ValueError('RX_CALIBRATION_RANGE')
            if group == 134 and (len(set(values[2:6])) != 4 or self.values[7][0] in values[2:6]):
                raise ValueError('RECEIVER_MAPPING')
            if group == 134 and values[1] in (1, 2) and self.values[7][0] < 5:
                raise ValueError('INVALID_VALUES: digital flight mode needs CH5–CH8')
            if group == 7 and values[0] in self.values[134][2:6]:
                raise ValueError('FLIGHT_MODE_CHANNEL')
            if group == 7 and values[0] < 5 and (self.source in (1, 2) or self.values[134][1] in (1, 2)):
                raise ValueError('INVALID_VALUES: digital flight mode needs CH5–CH8')
            self._invalidate(group, self.values[group], values)
            self.values[group] = list(values)
            if group == 134:
                self.source = values[1]
        else:
            raise ValueError('READ_ONLY')
        return ['APPLIED_UNSAVED']

    def save_group(self, group, schema=1):
        self._tick()
        if self.armed:
            raise ValueError('WRITE_LOCKED')
        if self._esc_boot or self._setup[8] or self._setup[3] in (1, 2):
            raise ValueError('CALIBRATION_BUSY')
        if not self.storage_available or not self._setup_store_healthy:
            raise RuntimeError('STORAGE_FAILURE')
        if group not in SETUP_SETTINGS or schema != DRONE_GROUPS[group]['schema']:
            raise ValueError('Invalid DEMO save')
        self._store_setting(group, self.values[group])
        return ['SAVED']

    def action(self, group, values, schema=1, cancel=None, **kwargs):
        if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
            raise RuntimeError('ACTION_CANCELLED')
        self._tick()
        if not self.connected:
            raise RuntimeError('DISCONNECTED')
        if group == 123 and schema == 1 and values in (['ARM'], ['DISARM']):
            return self.arm(cancel=cancel) if values[0] == 'ARM' else self.disarm()
        if group == 137 and schema == 1:
            return self._pid_apply(values)
        if group != 135 or schema != 1 or not isinstance(values, (list, tuple)) or len(values) != 5:
            raise ValueError('ACTION_DATA')
        cmd, *args = values
        if type(cmd) is not str or any(type(v) is not int for v in args):
            raise ValueError('ACTION_DATA')
        if not self.connected:
            raise RuntimeError('DISCONNECTED')
        if cmd in ('STOP', 'MOTOR_STOP'):
            if args != [0] * 4:
                raise ValueError('ACTION_DATA')
            if cmd == 'MOTOR_STOP' and self._setup[3] == 2:
                raise ValueError('CALIBRATION_BUSY')
            if cmd == 'STOP':
                return self.disarm()
            self._stop_motor(verified_stop=True)
            return ['MOTOR_STOPPED']
        if self.armed:
            raise ValueError('ARMED')
        if not self.storage_available or not self._setup_store_healthy:
            raise RuntimeError('SETUP_STORAGE_LOCKED')
        if self._esc_boot:
            raise ValueError('CALIBRATION_BUSY')
        if self._pid_pending:
            raise ValueError('PID_SAVE_PENDING')
        if cmd == 'RESET_ALL':
            return self._reset_all(args)
        if cmd == 'INPUT_SAVE':
            return self._input_save(args)
        if cmd == 'BEGIN':
            if args not in ([0, 0, 0, 0], [1, 0, 0, 0]):
                raise ValueError('ACTION_DATA')
            if self._setup[8] or self._setup[3] == 2:
                raise ValueError('CALIBRATION_BUSY')
            self._setup[0:2] = [True, False]
            if self._setup[3] not in (1, 2):
                self._setup[2] = 1
            self._stop_motor()
            self._persist()
            return ['SETUP_LOCKED']
        if not self._setup[0] or self._setup[1] or self._setup[2] == 0:
            raise ValueError('SETUP_NOT_ACTIVE')
        confirm_commands = ('SENSOR_OK', 'RX_OK', 'FAILSAFE_OK', 'ESC_SCHEDULE', 'ESC_VERIFY', 'ESC_SKIP')
        if cmd in confirm_commands and args != [1, 0, 0, 0]:
            raise ValueError('CONFIRM_REQUIRED')
        if cmd not in ('MOTOR_SET',) and (self._setup[8] or self._setup[3] == 2):
            raise ValueError('CALIBRATION_BUSY')
        if cmd == 'SENSOR_OK':
            if not self.imu_valid or not self._settings_saved((6,)):
                raise ValueError('SENSOR_NOT_SAVED')
            self._setup[5] = True
        elif cmd == 'RX_OK':
            if self.values[134][1] != 0 or not self.raw_enabled or max(self.values[134][2:6] + [self.values[7][0]]) > self.raw_count:
                raise ValueError('PPM_NOT_READY')
            if not self._settings_saved((132, 134)) or not self._neutral(self._normalized_ppm()):
                raise ValueError('RX_NOT_SAVED_OR_NEUTRAL')
            self._setup[6] = True
        elif cmd == 'FAILSAFE_OK':
            if self.values[134][1] == 0 and (not self._ppm_loss_seen or not self.raw_enabled):
                raise ValueError('PPM_LOSS_NOT_OBSERVED')
            self._setup[7] = True
        elif cmd in ('ESC_SCHEDULE', 'ESC_SKIP'):
            if not self._setup[5] or (self.values[134][1] == 0 and not self._setup[6]):
                raise ValueError('SENSOR_RECEIVER_REQUIRED')
            self._setup[3] = 1 if cmd == 'ESC_SCHEDULE' else 5
            self._setup[2] = 2 if cmd == 'ESC_SCHEDULE' else 1
            self._setup[4] = 0
            self._motor_tested = 0
        elif cmd == 'ESC_VERIFY':
            if self._setup[3] != 3:
                raise ValueError('ESC_SEQUENCE_REQUIRED')
            self._setup[3] = 4
            self._setup[2] = 1
        elif cmd == 'MOTOR_START':
            if not 1 <= args[0] <= 15 or args[1:] != [1, 0, 0]:
                raise ValueError('ACTION_DATA')
            if self._setup[3] not in (4, 5):
                raise ValueError('ESC_VERIFICATION_REQUIRED')
            if not self._setup[5] or not self.imu_valid:
                raise ValueError('IMU_NOT_READY')
            self._motor_mask = args[0]
            self._motor_moved = 0
            self._motor_tested &= ~args[0]
            self._setup[4] &= ~args[0]
            self._setup[2] = 6
            self._setup[8] = True
            self._setup[9:13] = [1000] * 4
            self._motor_owner = self.session
            self._motor_started = self._motor_last = self._clock()
            self._persist()
            return ['MOTOR_TEST_STARTED']
        elif cmd == 'MOTOR_SET':
            if args[2:] != [0, 0] or not 1000 <= args[1] <= 1500 or not self._setup[8] or args[0] != self._motor_mask or self._motor_owner != self.session:
                raise ValueError('MOTOR_SESSION_INVALID')
            self._motor_last = self._clock()
            self._setup[9:13] = [args[1] if args[0] & (1 << i) else 1000 for i in range(4)]
            return ['MOTOR_TEST_UPDATED']
        elif cmd == 'MOTOR_OK':
            if not 1 <= args[0] <= 15 or args[1:] != [1, 0, 0] or self._motor_tested & args[0] != args[0]:
                raise ValueError('MOTOR_TEST_REQUIRED')
            self._setup[4] |= args[0]
        elif cmd == 'FINALIZE':
            if args != [0] * 4 or self._setup[3] not in (4, 5) or self._setup[4] != 15 or not self._setup[5] or (self.values[134][1] == 0 and not self._setup[6]):
                raise ValueError('SETUP_INCOMPLETE')
            if not self._settings_saved(SETUP_SETTINGS) or self.source != self.values[134][1]:
                raise ValueError('SETTINGS_NOT_SAVED')
            if not self.storage_available:
                raise RuntimeError('STORAGE_FAILURE')
            self._setup[0:3] = [False, True, 0]
            self._setup[13] += 1
            self._setup[14] = ''
            self.last_control = None
            self.channels = list(NEUTRAL)
            self.armed = False
        else:
            raise ValueError('ACTION_UNKNOWN')
        self._setup[14] = ''
        self._persist()
        return ['SETUP_SAVED' if cmd == 'FINALIZE' else 'SETUP_UPDATED']

    def demo_restart(self):
        """Explicit DEMO power-cycle, including single-use ESC request handling."""
        self.armed = False
        self.last_control = None
        self._stop_motor()
        self.fc_session += 1
        self.events = queue.Queue()
        self.values = {group: values[:] for group, values in self.saved.items()}
        self.source = self.values[134][1]
        self._setup = self._stored_setup[:]
        self._setup[14] = ''
        self._setup[8:13] = [False, 1000, 1000, 1000, 1000]
        self._motor_tested = self._motor_moved = 0
        self._esc_started = None
        self._esc_boot = False
        self._imu_recover_at = None
        self.calibration_samples = 2000
        self._esc_cancel_uncertain = False
        self.imu_valid = True
        self._setup_store_healthy = self.storage_available
        self._pid_pending = False
        self._pid_revision = self._pid_saved_revision = 0
        self._pid_error = ''
        self._pid_snapshot = {}
        self._pid_restore_complete = False
        if self._setup[2] == 6:
            self._setup[2] = 1
        if self._setup[3] == 1:
            self._setup[0:4] = [True, False, 3, 2]
            self._persist()  # Consume before presenting a high output.
            self._esc_boot = True
            self.imu_valid = False
            self.calibration_samples = 0
            self._esc_started = self._clock()
        elif self._setup[3] == 2:
            self._setup[0:4] = [True, False, 7, 6]
            self._setup[14] = 'ESC_INTERRUPTED'
            self._persist()
        return ['DEMO_RESTARTED']

    def send_control(self, values, datagram_only=False, serial_only=False):
        if not self.connected or not ((self.source == 1 and datagram_only) or (self.source == 2 and serial_only)):
            raise RuntimeError('Wrong or disconnected DEMO route')
        validate_values(9, values)
        self.channels = list(values)
        self.last_control = self._clock()

    def arm(self, cancel=None, **kwargs):
        if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
            raise RuntimeError('ARM cancelled')
        self._tick()
        if self._setup[0] or not self._setup[1]:
            raise ValueError('SETUP_LOCKED')
        if self.source in (1, 2) and self.values[7][0] < 5:
            raise ValueError('SETUP_INPUT_NOT_VERIFIED')
        if self.source == 0 or not self._fresh() or not self._neutral(self.channels) or not self.imu_valid:
            raise ValueError('DEMO ARM requires fresh neutral digital input and valid IMU')
        self.armed = True
        return ['ARMED']

    def disarm(self):
        self.armed = False
        self.last_control = None
        self._stop_motor()
        if self._setup[3] in (1, 2):
            self._esc_started = None
            self._setup[0:4] = [True, False, 7, 6]
            self._setup[14] = 'ESC_CANCELLED'
            if self._esc_boot:self._imu_recover_at = self._clock()
            try:
                self._persist()
            except RuntimeError as error:
                self._esc_cancel_uncertain = True
                raise RuntimeError('ESC_CANCEL_NOT_PERSISTED') from error
        if self._esc_cancel_uncertain:
            raise RuntimeError('ESC_CANCEL_NOT_PERSISTED')
        if self._pid_pending:
            try:
                self._flush_pid()
            except RuntimeError:
                pass
        return ['DISARMED']

    def ping(self):
        self._tick()
        return ['PONG']

    def poll(self, timeout=0):
        self._tick()
        now = self._clock()
        if now - self.last_emit >= .05:
            self.last_emit = now
            for group in (120, 122, 21, 22, 23, 130, 131, 136):
                self.seq += 1
                self.events.put(Message('DATA', group, DRONE_GROUPS[group]['schema'], self.fc_session,
                                        self.seq, tuple(self.read_group(group, DRONE_GROUPS[group]['schema']))))
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self._stop_motor()
        self.connected = False
        self.armed = False
