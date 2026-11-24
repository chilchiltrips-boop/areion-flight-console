"""Bounded background requests. Channels are sent only by the GUI clock."""
from __future__ import annotations
import itertools
import queue
import threading
from PySide6.QtCore import QObject, Signal
from zebjus_areion_link import Link, RemoteError, SerialTransport, UDP
from zebjus_areion_link.schema import DRONE_GROUPS, SUPPORTED_FIRMWARE
from wifi_check import check_wifi
from .model import validate_values, equal_values, matching_pid_gains


class Jobs(QObject):
    finished = Signal(str, object, object)

    def __init__(self):
        super().__init__()
        self.queue = queue.PriorityQueue()
        self.serial = itertools.count()
        self.thread = threading.Thread(target=self._run, daemon=True, name='areion-gui-requests')
        self.thread.start()

    def submit(self, tag, function, priority=10):
        self.queue.put((priority, next(self.serial), tag, function))

    def _run(self):
        while True:
            _, _, tag, function = self.queue.get()
            try:
                result = function()
                self.finished.emit(tag, result, None)
            except Exception as error:
                self.finished.emit(tag, None, error)

def open_link(options, cancel):
    transports, warnings = [], []
    link = None
    wifi = None
    try:
        if options['mode'] in ('AP', 'USB + AP'):
            wifi = check_wifi(options['ssid'])
            try:
                transports.append(UDP(options['host'], options['udp_port']))
            except Exception as error:
                warnings.append(f'AP: {error}')
        if options['mode'] in ('USB', 'USB + AP'):
            try:
                if not options['port'].strip():
                    raise ValueError('Select a USB serial port')
                transports.append(SerialTransport(options['port'], options['baud']))
            except Exception as error:
                warnings.append(f'USB: {error}')
        if not transports:
            raise RuntimeError('; '.join(warnings) or 'No transport opened')
        if any(not transport.datagram for transport in transports):
            if cancel.wait(options['startup_wait']):
                raise RuntimeError('Connection cancelled')
        if cancel.is_set():
            raise RuntimeError('Connection cancelled')
        link = Link(*transports, request_timeout=.5, retries=2)
        link.connect()
        if cancel.is_set():
            raise RuntimeError('Connection cancelled')
        link.ping()
        values = {}
        for group in (125, 120, 122, 121, 110, 130, 132, 134, 136):
            if cancel.is_set():
                raise RuntimeError('Connection cancelled')
            try:
                values[group] = validate_values(group, link.read_group(group, schema=DRONE_GROUPS[group]['schema']))
            except Exception as error:
                raise RuntimeError(f'Group {group}: {error}. Upload the matching Areion firmware and library.') from error
            if group == 125 and values[125][0] not in SUPPORTED_FIRMWARE:
                raise RuntimeError('Upload the matching Areion firmware and library for the firmware setup ARM lock. '
                                   'Supported firmware: 3.1.0, 3.2.0 or 3.3.0. '
                                   f'Connected firmware reports {values[125][0]}.')
        return link, values, wifi, warnings
    except BaseException:
        if link is not None:
            link.close()
        else:
            for transport in transports:
                transport.close()
        raise

def read_section(link, group, saved=False, cancel=None):
    schema = DRONE_GROUPS[group]['schema']
    options = {'cancel': cancel} if cancel is not None else {}
    return validate_values(group, link.read_group(group, schema=schema, saved=saved, **options))

def require_disarmed(link):
    status = read_section(link, 120)
    if status[0]:
        raise ValueError('FC is armed. Disarm before changing settings or input.')
    return status

def apply_section(link, group, values):
    validate_values(group, values)
    require_disarmed(link)
    link.set_group(group, values, schema=DRONE_GROUPS[group]['schema'])
    actual = read_section(link, group)
    if not equal_values(values, actual):
        raise RuntimeError('Applied value readback differs; read the FC before another change')
    return actual

def save_section(link, group, expected):
    if not require_disarmed(link)[7]:
        raise RuntimeError('FC storage unavailable; nothing was saved')
    active = read_section(link, group)
    if not equal_values(active, expected):
        raise RuntimeError('FC values changed. Read the section again before saving.')
    link.save_group(group, schema=DRONE_GROUPS[group]['schema'])
    saved = read_section(link, group, saved=True)
    if not equal_values(active, saved):
        raise RuntimeError('Stored readback differs; save could not be verified')
    return saved

def _request_guard(link, cancel=None, expected_session=None):
    cancelled = cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel())
    if cancelled or not link.connected:
        raise RuntimeError('Request cancelled or connection lost. Read the kit before retrying an uncertain change.')
    if expected_session is not None and expected_session != (
            getattr(link, 'session', None), getattr(link, 'fc_session', None)):
        raise RuntimeError('Kit session changed. Read the kit before retrying an uncertain change.')


def apply_pid(link, group, values, bench_confirmed=False, cancel=None):
    """Apply one PID section, verifying active values and honest durability.

    The FC queues persistence while armed and commits automatically after
    disarming. This helper never sends ordinary SET/SAVE or ARM/DISARM.
    """
    if type(group) is not int or group not in (2, 3):
        raise ValueError('Choose Rate PID or Angle PID.')
    if type(bench_confirmed) is not bool:
        raise ValueError('Bench confirmation must be explicit.')
    requested = validate_values(group, values)
    session = (getattr(link, 'session', None), getattr(link, 'fc_session', None))
    def guard():
        _request_guard(link, cancel, session)
    def read(group, saved=False):
        guard()
        result = read_section(link, group, saved=saved, cancel=cancel)
        guard()
        return result
    state = read(120)
    if state[0] and not bench_confirmed:
        raise ValueError('Confirm the secured tuning setup before applying PID while armed.')
    if not state[7]:
        raise RuntimeError('FC storage unavailable; PID persistence cannot be confirmed.')
    payload = [group, bench_confirmed] + [float(value) for value in requested]
    if group == 3:
        payload += [0.0] * 3
    guard()
    ack = link.action(137, payload, schema=1, cancel=cancel)
    active = read(group)
    status = read(136)
    setup = read(130)
    if not matching_pid_gains(requested, active):
        raise RuntimeError('PID active readback differs. Read the kit before another change.')
    if status[3]:
        raise RuntimeError('PID persistence failed: ' + status[3])
    result = {'action': 'pid_apply', 'group': group, 'ack': ack,
              'values': {group: active, 136: status, 130: setup},
              'pending': bool(status[0]), 'saved': False, 'complete': True}
    if not status[0]:
        stored = read(group, saved=True)
        if not matching_pid_gains(active, stored) or status[1] != status[2]:
            raise RuntimeError('Stored PID readback differs; the save could not be verified.')
        result.update(saved=True, stored=stored)
    return result


def save_input(link, source, cancel=None, *, in_wizard=False):
    """Change only the source, preserving the kit's configuration and checks."""
    if type(source) is not int or source not in (0, 1, 2):
        raise ValueError('Choose PPM, AP or USB.')
    session = (getattr(link, 'session', None), getattr(link, 'fc_session', None))
    def guard():
        _request_guard(link, cancel, session)
    def read(group, saved=False):
        guard()
        result = read_section(link, group, saved=saved, cancel=cancel)
        guard()
        return result
    state = read(120)
    if state[0]:
        raise ValueError('FC is armed. Disarm before changing settings or input.')
    if not state[7]:
        raise RuntimeError('FC storage unavailable; input cannot be saved.')
    setup = read(130)
    if in_wizard and (not setup[0] or setup[1] or setup[2] == 0):
        raise RuntimeError('Confirm the setup lock before selecting an input in the wizard.')
    before = read(134)
    expected = before.copy()
    expected[1] = source
    stored_before = None
    if setup[0]:
        try:
            stored_before = read(134, saved=True)
        except RemoteError as error:
            if error.code != 'NOT_SAVED':
                raise
        if stored_before is not None and (stored_before[0] != expected[0]
                                          or stored_before[2:] != expected[2:]):
            raise RuntimeError('The kit has unsaved configuration changes. Save or reload them before switching input.')

    # Only the locked wizard may stage PPM for its first physical receiver check.
    # An established receiver uses INPUT_SAVE, which preserves its calibration proof.
    first_ppm = in_wizard and source == 0 and not setup[6]
    if first_ppm:
        if setup[8] or setup[3] in (1, 2):
            raise RuntimeError('Finish calibration before switching input.')
        if read(110) != [0] or before != expected:
            if read(134) != before:
                raise RuntimeError('Kit settings changed during selection. Reload before saving PPM.')
            guard()
            link.set_group(134, expected, schema=1)
        if read(134) != expected:
            raise RuntimeError('The kit did not confirm PPM selection.')
        if stored_before != expected:
            guard()
            link.save_group(134, schema=1)
        ack = None
    else:
        guard()
        ack = link.action(135, ['INPUT_SAVE', source, 0, 0, 0], schema=1, cancel=cancel)
        if ack != ['INPUT_SAVED']:
            raise RuntimeError('Input save was not acknowledged. Read the kit before retrying.')
    active, config = read(110), read(134)
    stored = read(134, saved=True)
    verified = read(130)
    if active != [source] or config != expected or stored != expected:
        raise RuntimeError('Active/stored flight input did not match. Read the kit before retrying.')
    # A never-qualified PPM input may invalidate a previous optional loss check.
    evidence_end = 7 if first_ppm else 8
    if verified[:2] != setup[:2] or verified[3:evidence_end] != setup[3:evidence_end]:
        raise RuntimeError('Setup status or calibration checks changed. Read the kit before continuing.')
    return {'action': 'input_save', 'ack': ack, 'complete': True, 'stored': stored,
            'values': {110: active, 134: config, 122: read(122),
                       130: verified, 136: read(136)}}
