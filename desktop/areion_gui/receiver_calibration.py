"""Raw PPM endpoint capture and local channel preview; no FC commands.

Capture consumes group 131 before the firmware's neutral/arming gate. The caller
must supply a fresh FC setup-lock/disarmed decision for every accepted sample.
Only an explicit finish with centered axes and low throttle creates a candidate.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math

MIN_DURATION_S = 2.0
MIN_SAMPLES = 10
MAX_TELEMETRY_AGE_S = 0.5
MAX_RECEIVER_AGE_MS = 250


def _time(value):
    return type(value) in (int, float) and math.isfinite(value)


def _mapping(values):
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError('Choose four receiver channel assignments.')
    if any(type(v) is not int or not 1 <= v <= 8 for v in values) or len(set(values)) != 4:
        raise ValueError('Roll, pitch, throttle and yaw need four different channels from CH1–CH8.')
    return list(values)


def _calibration(values):
    if not isinstance(values, (list, tuple)) or len(values) != 32:
        raise ValueError('Receiver calibration needs four values for each of eight channels.')
    result = list(values)
    if any(type(v) is not int for v in result):
        raise ValueError('Receiver calibration values must be integers.')
    for i in range(8):
        low, center, high, reverse = result[i*4:i*4+4]
        if not (900 <= low <= 1500 and 900 <= center <= 2100 and
                1500 <= high <= 2100 and reverse in (0, 1) and
                low < center < high and high-low >= 400 and
                center-low >= 100 and high-center >= 100):
            raise ValueError(f'CH{i+1}: invalid minimum, centre, maximum or direction.')
    return result


def raw_channels(raw, required_count, max_age_ms=MAX_RECEIVER_AGE_MS):
    """Validate group 131 and return its physical pulse slots and channel count."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 11:
        raise ValueError('Waiting for the raw receiver telemetry array.')
    count, fresh, age = raw[8:]
    if type(count) is not int or not required_count <= count <= 8:
        raise ValueError('The receiver does not provide all assigned channels.')
    if fresh is not True or type(age) is not int or not 0 <= age <= max_age_ms:
        raise ValueError('Raw receiver signal is stale or unavailable.')
    if any(type(v) is not int for v in raw[:8]):
        raise ValueError('Invalid raw receiver pulse.')
    if any(not 900 <= v <= 2100 for v in raw[:count]):
        raise ValueError('Raw receiver pulse is outside 900–2100 µs.')
    if any(v != 0 for v in raw[count:8]):
        raise ValueError('Absent receiver channels must report zero.')
    return list(raw[:8]), count


class ReceiverCapture:
    """Collect min/max from distinct fresh frames while outputs remain locked.

    ``add`` returns collecting, ignored or error. Stale data, a changed device
    identity or loss of the caller's safe decision permanently aborts this
    capture. ``finish`` raises ValueError when completion is not yet possible;
    insufficient travel or an uncentered stick can be corrected and retried.
    """
    def __init__(self, baseline32, mapping4, started, identity):
        self.baseline = _calibration(baseline32)
        self.mapping = _mapping(mapping4)
        if not _time(started) or identity is None:
            raise ValueError('A current receiver connection and capture time are required.')
        try:
            self.saved_identity = json.loads(json.dumps(identity, allow_nan=False))
        except (TypeError, ValueError):
            raise ValueError('Receiver connection identity must be serializable.') from None
        self.started = float(started)
        self.identity = deepcopy(identity)
        self.minimum = [None] * 8
        self.maximum = [None] * 8
        self.samples = 0
        self.first_stamp = None
        self.last_stamp = None
        self.last_count = 0
        self.last_safe = False
        self.error = ''
        self.result = None

    @property
    def progress(self):
        if self.result is not None:
            return 1.0
        duration = 0.0 if self.first_stamp is None else self.last_stamp-self.first_stamp
        return min(1.0, duration/MIN_DURATION_S, self.samples/MIN_SAMPLES)

    def _check(self, raw, stamp, now, identity):
        if self.error:
            raise ValueError(self.error)
        if identity != self.identity:
            self.error = 'Capture stopped: receiver connection changed. Start a new capture.'
        elif not all(_time(t) for t in (stamp, now)) or stamp > now or now-stamp > MAX_TELEMETRY_AGE_S:
            self.error = 'Capture stopped: fresh raw receiver telemetry was lost.'
        if self.error:
            raise ValueError(self.error)
        try:
            return raw_channels(raw, max(self.mapping))
        except ValueError as error:
            self.error = 'Capture stopped: ' + str(error)
            raise ValueError(self.error) from None

    def add(self, raw, stamp, now, identity, safe):
        if self.error:
            return 'error'
        self.last_safe = safe is True
        if not self.last_safe:
            self.error = 'Capture stopped: setup lock or disarmed status was lost.'
            return 'error'
        try:
            channels, count = self._check(raw, stamp, now, identity)
        except ValueError:
            return 'error'
        if self.result is not None or stamp < self.started:
            return 'ignored'
        if self.last_stamp is not None and stamp <= self.last_stamp:
            return 'ignored'
        if self.first_stamp is None:
            self.first_stamp = float(stamp)
        self.last_stamp = float(stamp)
        self.last_count = count
        self.samples += 1
        for i in range(count):
            value = channels[i]
            self.minimum[i] = value if self.minimum[i] is None else min(value, self.minimum[i])
            self.maximum[i] = value if self.maximum[i] is None else max(value, self.maximum[i])
        return 'collecting'

    def finish(self, raw, stamp, now, identity):
        if not self.last_safe:
            self.error = self.error or 'Capture stopped: setup lock or disarmed status was lost.'
            raise ValueError(self.error)
        channels, count = self._check(raw, stamp, now, identity)
        if self.result is not None:
            return deepcopy(self.result)
        if self.last_stamp is not None and stamp < self.last_stamp:
            raise ValueError('Use the latest receiver frame to capture centres.')
        if self.progress < 1.0:
            raise ValueError('Move all four sticks fully for at least two seconds and ten fresh frames.')
        values = list(self.baseline)
        required = {ch-1 for ch in self.mapping}
        throttle = self.mapping[2]-1
        for i in range(count):
            low, high = self.minimum[i], self.maximum[i]
            if low is None or high-low < 400:
                if i in required:
                    raise ValueError(f'CH{i+1}: insufficient travel; move the assigned stick to both ends.')
                continue
            reverse = self.baseline[i*4+3]
            if i == throttle:
                width = high-low
                if (not reverse and channels[i] > low + width*.1) or (reverse and channels[i] < high-width*.1):
                    raise ValueError('Lower the throttle fully before finishing receiver calibration.')
                center = round((low+high)/2)
            elif i in required:
                center = channels[i]
                if center-low < 100 or high-center < 100:
                    raise ValueError(f'CH{i+1}: centre the roll, pitch and yaw sticks before finishing.')
            else:
                center = round((low+high)/2)
            values[i*4:i*4+4] = [low, center, high, reverse]
        values = _calibration(values)
        self.result = {
            'values': values, 'samples': self.samples,
            'duration_s': self.last_stamp-self.first_stamp,
            'minimum': list(self.minimum), 'maximum': list(self.maximum),
            'mapping': list(self.mapping), 'identity': deepcopy(self.saved_identity),
            'captured_at_utc': datetime.now(timezone.utc).isoformat(),
            'applied_to_fc': False,
        }
        return deepcopy(self.result)


def normalize_channels(rawvalues, values32, mapping4, deadband=5):
    """Preview logical CH1–CH4; remaining physical AUX channels pass through.

    Spring axes use separate slopes around their measured centre. Throttle is
    linear over its endpoints; its centre field is intentionally ignored.
    """
    calibration = _calibration(values32)
    mapping = _mapping(mapping4)
    if type(deadband) is not int or not 0 <= deadband <= 50:
        raise ValueError('Receiver deadband must be 0–50 µs.')
    if not isinstance(rawvalues, (list, tuple)) or len(rawvalues) != 8:
        raise ValueError('Eight raw channel slots are required.')
    if any(type(v) is not int or (v != 0 and not 900 <= v <= 2100) for v in rawvalues):
        raise ValueError('Invalid raw channel value.')
    if any(rawvalues[ch-1] == 0 for ch in mapping):
        raise ValueError('An assigned receiver channel is unavailable.')
    result = list(rawvalues)
    for axis, channel in enumerate(mapping):
        index = channel-1
        low, center, high, reverse = calibration[index*4:index*4+4]
        measured = min(high, max(low, rawvalues[index]))
        if axis == 2:
            value = 1000.0 + 1000.0*(measured-low)/(high-low)
        elif abs(measured-center) <= deadband:
            value = 1500.0
        elif measured < center:
            value = 1500.0 + 500.0*(measured-center)/(center-low)
        else:
            value = 1500.0 + 500.0*(measured-center)/(high-center)
        if reverse:
            value = 3000.0-value
        result[axis] = int(round(min(2000.0, max(1000.0, value))))
    return result
