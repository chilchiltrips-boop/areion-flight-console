"""Pure control and telemetry models. No UI, sockets or automatic arming."""
from collections import deque
import math
import re
import struct
import time
from zebjus_areion_link.schema import DRONE_GROUPS
from .receiver_history import ReceiverHistory
from .scope_data import FRESH_SECONDS, ScopeHistory, input_frame_fresh

NEUTRAL = [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000]
CHANNEL_NAMES = ['Roll', 'Pitch', 'Throttle', 'Yaw', 'AUX 5', 'AUX 6', 'AUX 7', 'AUX 8']
DEFAULT_KEYS = [('Left', 'Right'), ('Down', 'Up'), ('S', 'W'), ('A', 'D'),
                ('1', '2'), ('3', '4'), ('5', '6'), ('7', '8')]
KEY_CHOICES = ['Left', 'Right', 'Up', 'Down'] + list('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
SETTINGS = (2, 3, 4, 6, 7, 112)
FLIGHT_MODES = {0: 'ANGLE', 1: 'RATE / ACRO'}

def field_label(name):
    if name == 'PpmTimeoutMs':return 'PPM timeout (ms)'
    if name == 'DigitalTimeoutMs':return 'USB/AP timeout (ms)'
    if name.startswith(('PRate','IRate','DRate','PAngle','IAngle','DAngle')):
        return name[0]+' · '+name.replace(name[0]+'Rate','').replace(name[0]+'Angle','')
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name).replace('Ms', '(ms)').replace('Time', 'time (s)')

def validate_values(group, values):
    fields = DRONE_GROUPS[group]['fields']
    if not isinstance(values, (list, tuple)) or len(values) != len(fields):
        raise ValueError(f'Group {group}: incompatible field count; use matching firmware')
    for field, value in zip(fields, values):
        kind = field['type']
        valid = ((kind == 'float' and type(value) in (float, int) and math.isfinite(value))
                 or (kind == 'int' and type(value) is int)
                 or (kind == 'bool' and type(value) is bool)
                 or (kind == 'string' and type(value) is str))
        if not valid or ('min' in field and not field['min'] <= value <= field['max']):
            raise ValueError(f"Invalid {field['name']}: {value!r}")
    if group == 7 and values[4] == values[5]:
        raise ValueError('Choose different flight modes for Low and High')
    if group == 132:
        for index in range(0,32,4):
            low,center,high,reverse=values[index:index+4]
            if high-low<400 or center-low<100 or high-center<100:
                raise ValueError('Receiver endpoints need a valid span and centre.')
    if group == 134 and len(set(values[2:6]))!=4:
        raise ValueError('Roll, pitch, throttle and yaw need four different channels.')
    return list(values)

def flight_mode_for_value(settings, value):
    settings = validate_values(7, settings)
    return settings[4] if value < 1500 else settings[5]

def flight_mode_channel_value(settings, mode):
    settings = validate_values(7, settings)
    if type(mode) is not int or mode not in FLIGHT_MODES:
        raise ValueError('Choose ANGLE or RATE / ACRO')
    return 1000 if mode == settings[4] else 2000

def equal_values(first, second):
    return len(first) == len(second) and all(
        math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-8)
        if type(a) in (int, float) and type(b) in (int, float) else a == b
        for a, b in zip(first, second))


def pid_gain_word(value):
    """The FC stores each validated gain as float32 and treats both zeros equally."""
    return struct.pack('!f', value or 0.0)


def matching_pid_gains(first, second):
    return len(first) == len(second) and all(
        pid_gain_word(a) == pid_gain_word(b) for a, b in zip(first, second))

class Controls:
    def __init__(self):
        self.keys = list(DEFAULT_KEYS)
        self.reset()

    def reset(self):
        self.values = list(NEUTRAL)
        self.pressed = set()
        self.mouse_left = self.mouse_right = False

    def set_bindings(self, bindings):
        if len(bindings) != 8 or any(len(pair) != 2 for pair in bindings):
            raise ValueError('Choose two keys for each of the eight channels')
        flat = [key for pair in bindings for key in pair]
        if any(key not in KEY_CHOICES for key in flat) or len(set(flat)) != 16:
            raise ValueError('Use sixteen different keys. Escape and Space are reserved for Stop.')
        self.keys = [tuple(pair) for pair in bindings]
        self.pressed.clear()

    def key(self, key, down):
        if down:
            self.pressed.add(key)
            for channel in range(4, 8):
                if key in self.keys[channel]:
                    self.values[channel] = 1000 if key == self.keys[channel][0] else 2000
        else:
            self.pressed.discard(key)

    def step(self, seconds, keyboard_enabled):
        if not keyboard_enabled:
            self.pressed.clear()
            return
        for channel in range(4):
            if (channel in (2, 3) and self.mouse_left) or (channel in (0, 1) and self.mouse_right):
                continue
            minus, plus = self.keys[channel]
            direction = int(plus in self.pressed) - int(minus in self.pressed)
            if channel == 2:
                self.values[channel] = round(max(1000, min(2000, self.values[channel] + direction * min(.05, seconds) * 500)))
            else:
                self.values[channel] = 1500 + direction * 500

    def stick(self, left, x, y, held):
        x, y = max(-1, min(1, x)), max(-1, min(1, y))
        if left:
            self.mouse_left = held
            self.values[3] = round(1500 + 500 * x) if held else 1500
            if held:
                self.values[2] = round(1500 + 500 * y)
        else:
            self.mouse_right = held
            self.values[0] = round(1500 + 500 * x) if held else 1500
            self.values[1] = round(1500 + 500 * y) if held else 1500

class Telemetry:
    def __init__(self):
        self.latest = {}
        self.revisions = {}
        self.revision = 0
        self.history = {}
        self.scopes = ScopeHistory()
        self.receiver_health = ReceiverHistory()
        self._await_new_imu = False
        self.rows = deque(maxlen=5000)
        self.started = time.monotonic()

    def put(self, group, schema, values, now=None, received=True):
        if group not in DRONE_GROUPS or schema != DRONE_GROUPS[group]['schema']:
            return False
        try:
            values = validate_values(group, values)
        except ValueError:
            return False
        now = time.monotonic() if now is None else now
        self.latest[group] = (values, now)
        self.revision += 1
        self.revisions[group] = self.revision
        if ((group == 120 and (not values[2] or values[5] <= 0))
                or (group == 130 and values[14] == "IMU_STARTUP_FAILED")):
            self._await_new_imu = True
        elif group == 21 and self._await_new_imu and self._imu_ready(now):
            self._await_new_imu = False
        if group in (120, 122):
            self.receiver_health.report(group, values, now)
        if group == 112:
            self.scopes.input_timeouts = tuple(values)
        if received:
            self.scopes.append(group, now, values)
            for field, value in zip(DRONE_GROUPS[group]['fields'], values):
                if type(value) in (float, int):
                    key = (group, field['index'])
                    self.history.setdefault(key, deque(maxlen=600)).append((now, value))
            self.rows.append((now - self.started, group, schema, values))
        return True

    def values(self, group, max_age=None, now=None):
        if group not in self.latest:
            return None
        values, at = self.latest[group]
        if max_age is not None and (time.monotonic() if now is None else now) - at > max_age:
            return None
        return values

    def age(self, group, now=None):
        if group not in self.latest:
            return None
        return (time.monotonic() if now is None else now) - self.latest[group][1]

    def _imu_ready(self, now):
        age = self.age(120, now)
        status = self.values(120)
        setup = self.values(130)
        return (age is not None and 0 <= age <= .5 and status[2] and status[5] > 0
                and not (setup and setup[14] == "IMU_STARTUP_FAILED"))

    def flight_imu(self, now):
        """A fresh attitude sample, captured after the most recent reported fault."""
        age = self.age(21, now)
        if not self._await_new_imu and age is not None and 0 <= age <= .5 and self._imu_ready(now):
            return self.values(21)
        return None


class PpmMonitor:
    """Read accepted receiver channels without ever changing TX controls."""
    def __init__(self):
        self.ready_after = None

    def view(self, data, connected, now):
        latest = data.values(122)
        selected = bool(latest and latest[0] == 0)
        inputs = data.values(122, FRESH_SECONDS, now) if connected else None
        frame_fresh = bool(inputs and input_frame_fresh(
            inputs[6], data.latest[122][1], now, data.scopes.input_timeouts[0]))
        ready = bool(selected and inputs and inputs[1] == 1 and inputs[2]
                     and frame_fresh and inputs[4] and 4 <= inputs[5] <= 8)
        if not ready:
            self.ready_after = None
            if not connected:note = 'PPM OFFLINE · connect USB or AP to receive telemetry'
            elif not inputs:note = 'PPM STATUS STALE · waiting for fresh receiver status'
            elif not inputs[2]:note = 'PPM SIGNAL LOST · no live receiver data'
            elif not frame_fresh:note = 'PPM FRAME STALE · check receiver status'
            elif not inputs[4]:note = 'PPM WAITING FOR NEUTRAL · lower throttle and center roll / pitch / yaw'
            else:note = 'PPM WAITING · receiver input is not active'
            return selected, None, note
        if self.ready_after is None:
            self.ready_after = data.revisions[122]
        values = data.values(22, FRESH_SECONDS, now)
        # Do not relabel a cached USB/AP array as PPM after source selection
        # or reuse a packet from before a reported signal-loss/neutral gate.
        if values is None or data.revisions[22] <= self.ready_after:
            return True, None, 'PPM CHANNELS STALE / WAITING · no fresh channel array'
        count = inputs[5]
        if any(not 900 <= value <= 2100 for value in values[:count]):
            return True, None, 'PPM CHANNELS INVALID · no live receiver data'
        channels = values[:count] + [None] * (8 - count)
        age = max(0, data.age(22, now))
        return True, channels, f'PPM LIVE · {count} channels · received {age*1000:.0f} ms ago · read only'
