"""Received, timestamped scope samples and low-bandwidth IMU spectra."""
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
import math
from statistics import median
import time

from .receiver_calibration import raw_channels


FRESH_SECONDS = .5
SCOPE_GROUPS = (21, 22, 23, 120, 122, 130, 131)
MAX_ROWS = 2048
ACC = {'X': 3, 'Y': 4, 'Z': 5}
GYRO = {'Roll': 0, 'Pitch': 1, 'Yaw': 2}


def accepted_input(status):
    """Identity of the live channel source reported by INPUT_STATUS."""
    if not status or len(status) != 9:
        return None
    selected, active, ppm_fresh, ap_fresh, ready, count, _, owner, usb_fresh = status
    if selected not in (0, 1, 2) or active != selected + 1 or not ready or not 4 <= count <= 8:
        return None
    if selected and (count != 8 or not owner):
        return None
    if not (ppm_fresh, ap_fresh, usb_fresh)[selected]:
        return None
    return selected, count, owner if selected else None


def input_frame_fresh(age_ms, receipt, now, timeout_ms):
    """Check the sampled FC frame age and the desktop report age independently.

    New receiver frames can arrive between reports. Only the FC can identify
    a receiver timeout during that interval.
    """
    return (type(age_ms) is int and type(timeout_ms) is int and 0 <= age_ms < timeout_ms
            and 0 <= now - receipt <= FRESH_SECONDS)


class ScopeHistory:
    """Bounded, per-connection event history. RPC reads never enter these rings."""
    def __init__(self):
        self.rows = {g: deque(maxlen=MAX_ROWS) for g in SCOPE_GROUPS}
        self.revisions = {g: 0 for g in SCOPE_GROUPS}
        # Remember validity at reception, including packet order inside a serial burst.
        self.imu_ok = deque(maxlen=MAX_ROWS)
        self.receiver_marks = deque(maxlen=MAX_ROWS)
        self.receiver_epoch = 0
        self.raw_counts = deque(maxlen=MAX_ROWS)
        self.input_timeouts = (250, 250)

    def latest(self, group):
        rows = self.rows.get(group)
        return rows[-1] if rows else None

    def _imu_state(self, at):
        status = self.latest(120)
        if status is None:
            # The current firmware publishes IMU packets only after sensor startup.
            return 'Live'
        if not 0 <= at - status[0] <= FRESH_SECONDS:
            return 'Stale'
        return 'Live' if status[1][2] and status[1][5] > 0 else 'Invalid'

    def _accepted_gate(self, status, now):
        if status:
            stamp, values = status
            gate = accepted_input(values)
            if gate and input_frame_fresh(values[6], stamp, now, self.input_timeouts[int(gate[0] != 0)]):
                return gate
        return None

    def append(self, group, stamp, values):
        if group not in self.rows or not math.isfinite(stamp):
            return
        previous = self.latest(group)
        if previous and previous[0] > stamp:
            return
        if group == 122:
            if self._accepted_gate(previous, stamp) != self._accepted_gate((stamp, values), stamp):
                self.receiver_epoch += 1
        if group == 22:
            gate = self._accepted_gate(self.latest(122), stamp)
            if gate and any(not 900 <= val <= 2100 for val in values[:gate[1]]):
                gate = None
            self.receiver_marks.append((self.receiver_epoch, gate[1]) if gate else None)
        if group == 131:
            timeout = self.input_timeouts[0]
            count = 0
            if input_frame_fresh(values[10], stamp, stamp, timeout):
                try:
                    _, count = raw_channels(values, 4, max_age_ms=timeout)
                except ValueError:
                    pass
            self.raw_counts.append(count)
        if group == 21:
            self.imu_ok.append(self._imu_state(stamp) == 'Live')
        self.rows[group].append((stamp, tuple(values)))
        self.revisions[group] += 1

    def snapshot(self):
        frozen = ScopeHistory()
        frozen.rows = {g: tuple(frames) for g, frames in self.rows.items()}
        frozen.imu_ok = tuple(self.imu_ok)
        frozen.receiver_marks = tuple(self.receiver_marks)
        frozen.receiver_epoch = self.receiver_epoch
        frozen.raw_counts = tuple(self.raw_counts)
        frozen.input_timeouts = self.input_timeouts
        frozen.revisions = self.revisions.copy()
        return frozen


class FrozenTelemetry:
    """The read interface of Telemetry at the instant the user paused Scopes."""
    def __init__(self, data, now):
        self.now = now
        self.latest = {g: (tuple(row), stamp) for g, (row, stamp) in data.latest.items()}
        self.revisions = data.revisions.copy()
        self.revision = data.revision
        self.scopes = data.scopes.snapshot()

    def values(self, group, max_age=None, now=None):
        if group not in self.latest:
            return None
        row, stamp = self.latest[group]
        if max_age is not None and (self.now if now is None else now) - stamp > max_age:
            return None
        return row

    def age(self, group, now=None):
        if group not in self.latest:
            return None
        return (self.now if now is None else now) - self.latest[group][1]


def frozen_telemetry(data, now=None):
    return FrozenTelemetry(data, time.monotonic() if now is None else now)


def group_state(data, group, now):
    """State of the latest *received* packet. Caller separately owns the link state."""
    scopes = data.scopes
    last = scopes.latest(group)
    if not last:
        return 'Waiting'
    stamp, values = last
    if not 0 <= now - stamp <= FRESH_SECONDS:
        return 'Stale'
    if group == 21:
        state = scopes._imu_state(now)
        return 'Invalid' if state == 'Live' and not scopes.imu_ok[-1] else state
    if group == 22:
        status = scopes.latest(122)
        if not status:
            return 'Waiting'
        if not 0 <= now - status[0] <= FRESH_SECONDS:
            return 'Stale'
        gate = accepted_input(status[1])
        if gate and not scopes._accepted_gate(status, now):
            return 'Stale'
        mark = scopes.receiver_marks[-1]
        if not gate or mark != (scopes.receiver_epoch, gate[1]):
            return 'Invalid'
    if group == 131:
        if not values[9]:
            return 'Invalid'
        if not input_frame_fresh(values[10], stamp, now, scopes.input_timeouts[0]):
            return 'Stale'
        if not scopes.raw_counts[-1]:
            return 'Invalid'
    return 'Live'


def time_series(data, group, channels, now, seconds):
    """Return like-unit traces with true arrival times and explicit breaks."""
    scopes = data.scopes
    frames = scopes.rows.get(group, ())
    points = {name: [] for name in channels}
    start = now - seconds
    selected = [(i, t, row) for i, (t, row) in enumerate(frames) if start <= t <= now]
    intervals = [b[1]-a[1] for a, b in zip(selected, selected[1:]) if b[1] > a[1]]
    gap = min(FRESH_SECONDS, max(.035, 3 * median(intervals))) if intervals else FRESH_SECONDS
    last_t = None
    last_epoch = None
    # Indexing a deque repeatedly in its middle is O(n). Copy the compact guard marks once.
    marks = tuple(scopes.receiver_marks) if group == 22 else ()
    imu_ok = tuple(scopes.imu_ok) if group == 21 else ()
    raw_counts = tuple(scopes.raw_counts) if group == 131 else ()
    for i, t, values in selected:
        count = len(values)
        epoch = None
        if group == 21 and not imu_ok[i]:
            count = 0
        elif group == 22:
            mark = marks[i]
            if mark:
                epoch, count = mark
            else:
                count = 0
        elif group == 131:
            count = raw_counts[i]
        if last_t is not None and (t - last_t > gap or epoch != last_epoch):
            split = (last_t + t) / 2.
            for trace in points.values():
                trace.append((split, None))
        for name, index in channels.items():
            value = values[index] if 0 <= index < count else None
            points[name].append((t, value))
        last_t, last_epoch = t, epoch
    return {name: tuple(trace) for name, trace in points.items()}


@dataclass(frozen=True)
class SpectrumSet:
    sample_rate: float | None
    nyquist: float | None
    count: int
    resolution: float | None
    message: str
    acc: dict
    gyro: dict


def _unavailable(message, count=0):
    return SpectrumSet(None, None, count, None, message, {}, {})


def _fft(samples):
    """Iterative radix-2 Cooley-Tukey transform, for 32 to 256 real samples."""
    count = len(samples)
    transformed = [complex(x) for x in samples]
    j = 0
    for i in range(1, count):
        bit = count >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            transformed[i], transformed[j] = transformed[j], transformed[i]
    size = 2
    while size <= count:
        angle = -2 * math.pi / size
        step = complex(math.cos(angle), math.sin(angle))
        half = size // 2
        for start in range(0, count, size):
            factor = 1.
            for i in range(start, start + half):
                left = transformed[i]
                right = factor * transformed[i + half]
                transformed[i] = left + right
                transformed[i + half] = left - right
                factor *= step
        size *= 2
    return transformed[:count // 2 + 1]


def imu_spectra(data, now, seconds):
    """Windowed one-sided *peak* amplitudes in g or °/s, estimated at the PC.

    Group 21 carries no acquisition timestamp. The FC's 25 ms publication slots
    put IMU events 50/100 ms apart under ideal conditions. Accept that modest
    stagger, resample onto a uniform receipt-time grid, and reject bursts or
    unusable timing rather than filling a dropout with synthetic cycles.
    """
    state = group_state(data, 21, now)
    if state != 'Live':
        return _unavailable({'Stale': 'IMU telemetry is stale', 'Invalid': 'IMU unavailable',
                             'Waiting': 'Waiting for IMU samples'}[state])
    samples = []
    for (t, row), ok in zip(reversed(data.scopes.rows[21]), reversed(data.scopes.imu_ok)):
        if t < now - seconds or not ok:
            break
        if samples and not 0 < samples[-1][0] - t <= FRESH_SECONDS:
            break
        samples.append((t, row))
        if len(samples) == 256:
            break
    samples.reverse()
    if len(samples) < 32:
        return _unavailable(f'Collecting IMU samples · {len(samples)}/32',len(samples))

    # A two-interval average accounts for the FC alternating short and long slots.
    cadence = median((samples[i][0] - samples[i-2][0]) / 2 for i in range(2, len(samples)))
    # Exclude everything up to the newest abnormal interval. Use the contiguous suffix.
    start = 0
    for i in range(1,len(samples)):
        delta = samples[i][0] - samples[i-1][0]
        if not .45 * cadence <= delta <= 1.65 * cadence:
            start = i
    if len(samples) - start < 32:
        return _unavailable('Irregular IMU timing · waiting for a continuous window',len(samples)-start)
    count = 1 << ((len(samples) - start).bit_length() - 1)
    samples = samples[-count:]
    times = [t for t, _ in samples]
    period = (times[-1] - times[0]) / (count - 1)
    # Even when all individual deltas look reasonable, clocks with clustered
    # runs of short/long intervals are poor evidence of a uniform sample rate.
    if max(abs(t - (times[0] + i * period)) for i, t in enumerate(times)) > .95 * period:
        return _unavailable('Irregular IMU timing · waiting for a continuous window',count)

    fs = 1. / period
    # These firmware versions publish two IMU groups per six 25 ms slots.
    # A regular, but much faster, USB queue drain is not a higher-rate sensor.
    info = data.values(125)
    if info and info[0] in ('3.1.0', '3.2.0', '3.3.0') and fs > (2 / .15) * 1.12:
        return _unavailable('Bursty IMU delivery · waiting for normal telemetry timing', count)
    resolution = fs / count
    grid = []
    for i in range(count):
        target = times[0] + i * period
        right = max(1, min(count - 1, bisect_left(times, target)))
        left = right - 1
        weight = max(0., min(1., (target-times[left]) / (times[right]-times[left])))
        grid.append((samples[left][1], samples[right][1], weight))
    window = [.5 - .5*math.cos(2*math.pi*i/count) for i in range(count)]
    weight_sum = sum(window)
    def transform(channels):
        spectra = {}
        for label, index in channels.items():
            trace = [lo[index] + mix * (hi[index]-lo[index]) for lo, hi, mix in grid]
            centre = sum(trace) / count
            bins = _fft([(v-centre)*w for v, w in zip(trace, window)])
            # Omit DC after de-meaning. Nyquist is unpaired and receives no doubling.
            spectra[label] = tuple((k*resolution, abs(bins[k]) * (1 if k==count//2 else 2) / weight_sum)
                                   for k in range(1,len(bins)))
        return spectra
    return SpectrumSet(fs, fs/2, count, resolution, '', transform(ACC), transform(GYRO))
