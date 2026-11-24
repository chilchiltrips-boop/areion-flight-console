"""Explicit, verified setup actions; only firmware FINALIZE can release ARM lock."""
import time

from .backend import read_section, save_input
from .model import validate_values, equal_values
from .setup_changes import SETTINGS_GROUPS as SETUP_SETTINGS
from zebjus_areion_link.schema import DRONE_GROUPS
from zebjus_areion_link import RemoteError

READ_GROUPS = SETUP_SETTINGS + (21, 22, 23, 110, 120, 121, 122, 125, 130, 131, 136)
SETUP_COMMANDS = {
    'BEGIN', 'STOP', 'SENSOR_OK', 'RX_OK', 'FAILSAFE_OK', 'ESC_SCHEDULE',
    'ESC_VERIFY', 'ESC_SKIP', 'MOTOR_START', 'MOTOR_SET', 'MOTOR_STOP',
    'MOTOR_OK', 'FINALIZE',
}

class UnsupportedSetupFeature(RuntimeError):
    pass


class MotorTestAdapter:
    """Legacy import compatibility; motor actions require an explicit Link."""
    available = False
    reason = 'Use the firmware setup action API for motor testing.'
    def start(self, *args, **kwargs):
        raise UnsupportedSetupFeature(self.reason)
    def update(self, *args, **kwargs):
        raise UnsupportedSetupFeature(self.reason)
    def stop(self):
        pass


def run_setup_action(link, action, payload, cancelled):
    def guard():
        if cancelled() or not link.connected:
            raise RuntimeError('Setup action cancelled or connection lost. ARM remains locked until a verified final save.')
        if action == 'save_calibration' and payload.get('identity') != (id(link), link.fc_session):
            raise RuntimeError('Kit session changed. Repeat calibration on the connected kit.')

    def read(group, saved=False):
        guard()
        result = read_section(link, group, saved=saved, cancel=cancelled)
        guard()
        return result

    def require_disarmed():
        status = read(120)
        if status[0]:
            raise ValueError('FC is armed. Disarm before changing settings or input.')
        return status

    def command(name, args=None):
        args = [0, 0, 0, 0] if args is None else list(args)
        if name not in SETUP_COMMANDS or len(args) != 4 or any(type(v) is not int for v in args):
            raise ValueError('Invalid setup command or arguments.')
        guard()
        if name not in ('STOP', 'MOTOR_STOP'):
            require_disarmed()
        guard()
        ack = link.action(135, [name] + args, schema=1, cancel=cancelled)
        guard()
        return ack, read(130)

    guard()
    if action == 'read':
        groups = payload['groups']
        if any(group not in READ_GROUPS for group in groups):
            raise ValueError('Unsupported setup read.')
        values = {group: read(group) for group in groups}
        if 130 not in values:
            values[130] = read(130)
        return {'action': action, 'values': values, 'complete': True}

    if action == 'begin':
        status = read(130)
        fc_status = read(120)
        persistence_fault = any(word in str(status[14]).upper() for word in ('STORAGE', 'PERSIST', 'NVS'))
        if not fc_status[7] or persistence_fault:
            raise RuntimeError('Persistent setup lock cannot be confirmed: ' +
                               (str(status[14]) or 'FC storage unavailable'))
        # Reconnecting to a pending/running calibration must not send DISARM:
        # that explicit stop would cancel the one-shot ESC operation.
        if status[0] and not status[1] and status[2] > 0 and not fc_status[0]:
            return {'action': action, 'ack': ['SETUP_LOCK_CONFIRMED'],
                    'values': {130: status}, 'complete': True, 'resumed': True}
        link.disarm()
        guard()
        ack, status = command('BEGIN', [int(bool(payload.get('props_removed', False))), 0, 0, 0])
        if not status[0] or status[1] or not read(120)[7]:
            raise RuntimeError('FC did not confirm the persistent setup ARM lock.')
        return {'action': action, 'ack': ack, 'values': {130: status}, 'complete': True}

    if action == 'reset_all':
        if payload.get('props_removed') is not True or payload.get('confirmed') is not True:
            raise ValueError('Confirm propellers removed and resetting all kit settings.')
        if not require_disarmed()[7]:
            raise RuntimeError('FC storage unavailable; reset cannot be verified.')
        status = read(130)
        if not status[0] or status[1] or status[2] == 0:
            raise RuntimeError('Confirm the firmware setup lock before resetting settings.')
        guard()
        ack = link.action(135, ['RESET_ALL', 1, 0, 0, 0], schema=1, cancel=cancelled)
        guard()
        values = {}
        for group in SETUP_SETTINGS:
            active, stored = read(group), read(group, saved=True)
            defaults = [field['default'] for field in DRONE_GROUPS[group]['fields']]
            if not equal_values(active, defaults) or not equal_values(stored, defaults):
                raise RuntimeError(f'Reset group {group} could not be verified; setup remains locked.')
            values[group] = active
        for group in (110, 120, 122, 130, 131, 136):
            values[group] = read(group)
        status = values[130]
        if not status[0] or status[1] or status[3:9] != [0, 0, False, False, False, False]:
            raise RuntimeError('Reset setup state could not be verified; read the kit before continuing.')
        return {'action': action, 'ack': ack, 'complete': True, 'values': values}

    if action == 'input_save':
        return save_input(link, payload['source'], cancelled)

    if action == 'command':
        name = payload['command']
        if name in ('BEGIN', 'FINALIZE'):
            raise ValueError('Use the guarded begin/finalize operation.')
        ack, status = command(name, payload.get('args'))
        if name == 'SENSOR_OK' and (ack != ['SETUP_UPDATED'] or not status[5] or not status[0] or status[1]):
            raise RuntimeError('Sensor verification was not confirmed by the kit.')
        return {'action': action, 'command': name, 'ack': ack,
                'values': {130: status}, 'complete': True}

    if action == 'input':
        result = save_input(link, payload['source'], cancelled, in_wizard=True)
        result['action'] = action
        return result

    # Keep the historical alias for SDK callers, but use the same 3.0 guards.
    if action not in ('apply_save', 'save_supported', 'finalize', 'save_calibration'):
        raise UnsupportedSetupFeature('Unsupported setup action.')
    requested = payload.get('groups', {})
    if not isinstance(requested, dict) or (not requested and action != 'finalize') or any(group not in SETUP_SETTINGS for group in requested):
        raise ValueError('Choose supported setup settings.')
    if 6 in requested and payload.get('acc_origin') == 'demo_candidate' and not getattr(link, 'demo', False):
        raise ValueError('Demo-derived ACC offsets cannot be applied to real hardware.')
    for group, values in requested.items():
        validate_values(group, values)
    if action == 'save_calibration':
        if set(requested) != {6}:
            raise ValueError('Calibration can save only accelerometer offsets.')
        baseline = validate_values(6, payload.get('baseline'))
    guard()
    if not require_disarmed()[7]:
        raise RuntimeError('FC storage unavailable; setup cannot be finalized.')
    status = read(130)
    if not status[0] or status[1]:
        raise RuntimeError('Enter setup and confirm the firmware ARM lock before saving setup sections.')
    if action == 'save_calibration' and (status[8] or status[3] in (1, 2)):
        raise RuntimeError('Stop motor testing and finish ESC calibration before saving the IMU.')
    result = {'action': action, 'sections': {}, 'values': {130: status},
              'complete': False, 'demo': bool(getattr(link, 'demo', False))}
    # Input/profile and calibration precede flight settings, so cross-validation
    # observes the intended receiver mapping. No-op SETs do not clear evidence.
    ordered = [group for group in (134, 132, 2, 3, 4, 6, 7, 112) if group in requested]
    for group in ordered:
        values = requested[group]
        stage = 'not_started'
        try:
            guard()
            require_disarmed()
            before = read(group)
            if action == 'save_calibration' and not equal_values(before, baseline):
                raise RuntimeError('Offsets changed during calibration. Read them and repeat the capture.')
            result['sections'][group] = {'before': before, 'requested': list(values), 'state': 'read'}
            if not equal_values(before, values):
                guard()
                stage = 'apply_sent'
                link.set_group(group, values, schema=DRONE_GROUPS[group]['schema'])
                actual = read(group)
                if not equal_values(values, actual):
                    raise RuntimeError('Applied value readback differs.')
                result['sections'][group]['state'] = 'applied_unsaved'
                stage = 'applied_unsaved'
            else:
                actual = before
            result['values'][group] = actual
            guard()
            require_disarmed()
            try:
                saved = read(group, saved=True)
            except RemoteError as error:
                if error.code != 'NOT_SAVED':
                    raise
                saved = None  # A fresh kit still needs its first durable write.
            if saved is None or not equal_values(saved, actual):
                guard()
                stage = 'save_sent'
                link.save_group(group, schema=DRONE_GROUPS[group]['schema'])
                saved = read(group, saved=True)
            active = read(group)
            if not equal_values(saved, actual) or not equal_values(active, actual):
                raise RuntimeError('Stored/active readback differs; setup remains locked.')
            result['sections'][group].update(state='saved_verified', stored=saved)
        except Exception as error:
            result['sections'].setdefault(group, {})
            result['sections'][group].update(state='failed', stage=stage, error=str(error))
            result['error'] = str(error)
            # A failed connection makes status unknown; never fabricate success.
            try:
                result['values'][130] = read(130)
            except Exception:
                pass
            return result
    if action == 'save_calibration':
        # Setting offsets invalidates the FC IMU flag until the next acquisition.
        deadline = time.monotonic() + 1.5
        while True:
            state = require_disarmed()
            if state[2] and state[5] > 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Offsets stored. IMU has not resumed. Read the kit before retrying.')
            time.sleep(.04)
        ack, setup = command('SENSOR_OK', [1, 0, 0, 0])
        if ack != ['SETUP_UPDATED'] or not setup[0] or setup[1] or not setup[5] or setup[8] or setup[3] in (1, 2):
            raise RuntimeError('Offsets stored. The kit did not confirm sensor verification.')
        result.update(ack=ack, complete=True)
        result['values'][130] = setup
        return result
    if 134 in requested:
        result['values'][110] = read(110)
    if action == 'finalize':
        # This complete FC readback also anchors an optional post-restart check.
        verified_settings = {}
        for group in SETUP_SETTINGS:
            active, saved = read(group), read(group, saved=True)
            if not equal_values(active, saved):
                result['error'] = f'Group {group} is not saved; ARM remains locked.'
                result['values'][130] = read(130)
                return result
            verified_settings[group] = list(active)
        ack, status = command('FINALIZE')
        result['ack'] = ack
        result['values'][130] = status
        if status[0] or not status[1] or status[8]:
            raise RuntimeError('Final setup save was not confirmed; read FC setup status before arming.')
        result['verified_settings'] = verified_settings
    else:
        result['values'][130] = read(130)
    result['complete'] = True
    return result
