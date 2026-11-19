"""Local, read-only verification of what a PPM receiver emits on RF loss."""
from dataclasses import dataclass
from hashlib import sha256
from itertools import islice
import json
from pathlib import Path
from statistics import median

from .scope_data import FRESH_SECONDS
from .wizard_model import write_json_atomic


LEVEL_TOLERANCE = 75  # µs around a learned marker level
MIN_SEPARATION = 300
SAMPLE_COUNT = 3


def _fresh(stamp, now):
    return stamp is not None and 0 <= now - stamp <= FRESH_SECONDS


def _recent(rows):
    return tuple(reversed(tuple(islice(reversed(rows), SAMPLE_COUNT))))


def _pulse(status, timeout):
    if not status or status[0] != 0 or status[1] not in (0, 1):
        return None
    if status[2] is False:
        if status[1] == 0 and not status[4]:
            return False
    elif (status[2] is True and 4 <= status[5] <= 8 and 0 <= status[6] < timeout
          and status[4] == (status[1] == 1)):
        return True
    return None


@dataclass(frozen=True)
class Observation:
    now: float
    session: object
    kit_id: str
    connected: bool
    source: int | None
    armed: bool | None
    pulse: bool | None
    channel_count: int
    mapping: tuple
    mode_channel: int | None
    input_samples: tuple
    channel_samples: tuple

    def marker(self, channel):
        if channel in spare_channels(self) and self.pulse is True and self.channel_samples:
            return self.channel_samples[-1][1][channel - 1]
        return None


def observe(data, now, connected=True):
    """Use the current session and its accepted-frame epochs; never request a packet."""
    setup = data.values(130)
    kit = setup[15] if setup and isinstance(setup[15], str) else ''
    config = data.values(134)
    mapping = tuple(config[2:6]) if config else ()
    flight = data.values(7)
    mode = flight[0] if flight else None
    source, source_stamp = data.latest.get(110, (None, None))
    report, stamp = data.latest.get(122, (None, None))
    selected = report[0] if report else (source[0] if source else None)
    # A new source readback may predate the first report for that source.
    if source and source_stamp is not None and (stamp is None or source_stamp > stamp):
        selected = source[0]
    status, status_stamp = data.latest.get(120, (None, None))
    armed = status[0] if connected and status and _fresh(status_stamp, now) else None
    scopes = data.scopes
    timeout = scopes.input_timeouts[0]
    usable = connected and selected == 0 and report and _fresh(stamp, now)
    pulse = _pulse(report, timeout) if usable else None
    count = report[5] if usable and report[0] == 0 else 0
    if pulse is True and source_stamp is not None and source_stamp > stamp:
        pulse = None  # Wait for the first receiver report following a source readback.
    if (pulse is True and report[4] and status and _fresh(status_stamp, now)
            and status_stamp > stamp and status[3] != count):
        # Group 120 reports accepted channels. A new zero can mean gate loss
        # or waiting for neutral. It cannot independently identify RF loss.
        pulse = None

    inputs = ()
    channels = ()
    if pulse is not None:
        inputs = tuple((t, _pulse(row, timeout), row[5])
                       for t, row in _recent(scopes.rows[122]))
    if pulse is True and report[4] and report[1] == 1:
        latest_mark = (scopes.receiver_epoch, count)
        # A gate closure can first arrive in the independently paced FC status stream.
        invalidated = max((t for t, row in _recent(scopes.rows[120]) if row[3] != count),
                          default=float('-inf'))
        for entry, mark in zip(_recent(scopes.rows[22]), _recent(scopes.receiver_marks)):
            t, row = entry
            if mark != latest_mark or t <= invalidated or (source_stamp is not None and t < source_stamp):
                channels = ()
            else:
                channels += ((t, row),)
        if channels and not _fresh(channels[-1][0], now):
            channels = ()
    return Observation(now, data, kit if connected else '', bool(connected), selected, armed, pulse,
                       count, mapping, mode, inputs, channels)


def spare_channels(obs):
    if len(obs.mapping) != 4 or obs.mode_channel is None:
        return ()
    return tuple(ch for ch in range(5, min(obs.channel_count, 8) + 1)
                 if ch not in obs.mapping and ch != obs.mode_channel)


@dataclass(frozen=True)
class TxStatus:
    code: str
    state: str
    label: str
    detail: str


def _valid_profile(profile):
    if not isinstance(profile, dict) or profile.get('version') != 1:
        return False
    kit = profile.get('kit_id')
    mapping = profile.get('mapping')
    mode, count = profile.get('mode_channel'), profile.get('channel_count')
    if (not isinstance(kit, str) or not kit.strip()
            or not isinstance(mapping, (tuple, list)) or len(mapping) != 4
            or any(type(v) is not int or not 1 <= v <= 8 for v in mapping) or len(set(mapping)) != 4
            or type(mode) is not int or not 1 <= mode <= 8
            or type(count) is not int or not 4 <= count <= 8):
        return False
    channel = profile.get('channel')
    if profile.get('kind') == 'pulse':
        return channel is None
    levels = (profile.get('on_us'), profile.get('off_us'))
    return (profile.get('kind') == 'marker' and type(channel) is int and 5 <= channel <= count
            and max(mode, *mapping) <= count and channel != mode and channel not in mapping
            and all(type(v) is int and 900 <= v <= 2100 for v in levels)
            and abs(levels[0] - levels[1]) >= MIN_SEPARATION)


def classify(obs, profile=None):
    if not obs.connected or obs.source in (1, 2):
        return TxStatus('inactive', 'gray', 'INACTIVE', 'PPM transmitter monitoring is inactive.')
    if obs.source != 0 or obs.pulse is None:
        return TxStatus('waiting', 'amber', 'WAITING', 'Waiting for current PPM status from the kit.')
    if obs.pulse is False:
        return TxStatus('off', 'amber', 'NO PPM', 'The kit reports no fresh PPM signal.')
    if not (_valid_profile(profile) and profile['kit_id'] == obs.kit_id
            and tuple(profile['mapping']) == obs.mapping and profile['mode_channel'] == obs.mode_channel
            and profile['channel_count'] == obs.channel_count):
        return TxStatus('unverified', 'amber', 'UNVERIFIED', 'PPM pulses are present. Verify the receiver’s transmitter-off behavior in Input.')
    if profile['kind'] == 'pulse':
        return TxStatus('on', 'green', 'TX ON', 'PPM is present. This receiver stopped its pulses in the saved TX-off check.')
    channel = profile['channel']
    value = obs.marker(channel)
    if value is None:
        return TxStatus('waiting', 'amber', 'WAITING', f'Waiting for a fresh accepted CH{channel} value.')
    # A source/gate change can publish one neutral AUX value before live data.
    # Confirm the same band on two distinct accepted frames in the current epoch.
    samples = obs.channel_samples
    if len(samples) < 2 or not 0 < samples[-1][0] - samples[-2][0] <= FRESH_SECONDS:
        return TxStatus('waiting', 'amber', 'CHECKING', f'Confirming the CH{channel} marker on a second frame.')
    previous = samples[-2][1][channel - 1]
    if abs(value - profile['off_us']) <= LEVEL_TOLERANCE and abs(previous - profile['off_us']) <= LEVEL_TOLERANCE:
        return TxStatus('off', 'amber', 'TX OFF', f'CH{channel} matches the receiver’s verified loss value ({profile["off_us"]} µs).')
    if abs(value - profile['on_us']) <= LEVEL_TOLERANCE and abs(previous - profile['on_us']) <= LEVEL_TOLERANCE:
        return TxStatus('on', 'green', 'TX ON', f'CH{channel} matches the verified on value ({profile["on_us"]} µs).')
    if min(abs(value - profile['on_us']), abs(value - profile['off_us'])) <= LEVEL_TOLERANCE:
        return TxStatus('waiting', 'amber', 'CHECKING', f'CH{channel} changed. Waiting for confirmation.')
    return TxStatus('unverified', 'amber', 'UNKNOWN', f'CH{channel} is outside both verified ranges.')


def _stable_times(rows, after, now):
    if len(rows) < SAMPLE_COUNT or rows[0][0] <= after or not _fresh(rows[-1][0], now):
        return False
    return all(0 < b[0] - a[0] <= FRESH_SECONDS for a, b in zip(rows, rows[1:]))


class Verification:
    """Three witnessed observations, with fresh independent frames for each stage."""
    def __init__(self, channel=None):
        self.channel = channel
        self.step = 0
        self._session = None
        self._settings = None
        self._count = 0
        self._levels = []
        self._after = float('-inf')

    def capture(self, obs):
        if self.step >= 3:
            raise ValueError('This check is complete.')
        if not obs.connected or obs.source != 0 or obs.armed is not False:
            raise ValueError('Connect the disarmed kit and select PPM.')
        settings = (obs.kit_id, obs.mapping, obs.mode_channel)
        if not obs.kit_id.strip() or len(obs.mapping) != 4 or obs.mode_channel is None:
            raise ValueError('Waiting for kit identity and receiver settings.')
        if self.step and (self._session is not obs.session or self._settings != settings):
            raise ValueError('The kit or channel mapping changed. Restart the check.')
        rows = obs.input_samples
        if (obs.pulse is None or not _stable_times(rows, self._after, obs.now)
                or any(pulse is not obs.pulse for _, pulse, _ in rows)):
            raise ValueError('Hold this state for one second, then capture again.')
        if self.step != 1 and obs.pulse is not True:
            raise ValueError('Switch the transmitter on and wait for PPM.')
        level = None
        if obs.pulse:
            if any(n != obs.channel_count for _, _, n in rows) or (self.step and obs.channel_count != self._count):
                raise ValueError('Channel count changed. Check the receiver and retry.')
            if self.channel is not None and not (self.step == 2 and self._levels[1] is None):
                if self.channel not in spare_channels(obs):
                    raise ValueError('Choose a received AUX channel unused by sticks and flight mode.')
                values = obs.channel_samples
                if obs.marker(self.channel) is None or not _stable_times(values, self._after, obs.now):
                    raise ValueError('Waiting for fresh channel samples. Return sticks to neutral.')
                pulses = [r[self.channel - 1] for _, r in values]
                if max(pulses) - min(pulses) > 40:
                    raise ValueError('Keep the dedicated AUX channel steady and retry.')
                level = round(median(pulses))
            if self.step == 1 and (level is None or abs(level - self._levels[0]) < MIN_SEPARATION):
                raise ValueError('PPM is still present. Set a distinct receiver failsafe on a spare AUX channel and restart the check.')
            if self.step == 2 and self._levels[1] is not None and abs(level - self._levels[0]) > LEVEL_TOLERANCE:
                raise ValueError('Restore the original transmitter-on AUX value and retry.')
        if not self.step:
            self._session, self._settings, self._count = obs.session, settings, obs.channel_count
        self._after = obs.now
        self._levels.append(level)
        self.step += 1
        if self.step != 3:
            return None
        marker = self._levels[1] is not None
        return {'version': 1, 'kind': 'marker' if marker else 'pulse', 'kit_id': obs.kit_id,
                'mapping': list(obs.mapping), 'mode_channel': obs.mode_channel, 'channel_count': self._count,
                'channel': self.channel if marker else None, 'on_us': self._levels[0] if marker else None,
                'off_us': self._levels[1]}


def _path(directory, kit_id):
    key = sha256(kit_id.encode('utf-8')).hexdigest()
    return Path(directory) / 'ppm_tx_link' / f'{key}.json'


def load_profile(directory, kit_id):
    if not kit_id:
        return None
    try:
        profile = json.loads(_path(directory, kit_id).read_text(encoding='utf-8'))
        return profile if _valid_profile(profile) and profile['kit_id'] == kit_id else None
    except (OSError, ValueError, TypeError):
        return None


def save_profile(directory, profile):
    if not _valid_profile(profile):
        raise ValueError('Invalid transmitter check. Verify the receiver again.')
    write_json_atomic(_path(directory, profile['kit_id']), profile)


def remove_profile(directory, kit_id):
    if kit_id:
        _path(directory, kit_id).unlink(missing_ok=True)
