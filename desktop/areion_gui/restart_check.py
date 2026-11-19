"""Read-only comparison of a verified setup with the same kit on a later boot."""
import json
from datetime import datetime, timezone

from zebjus_areion_link import RemoteError
from zebjus_areion_link.schema import DRONE_GROUPS

from .backend import read_section
from .model import validate_values
from .setup_changes import SETTINGS_GROUPS, setting_changes, settings_snapshot
from .wizard_model import write_json_atomic

SOURCE_NAMES = ('PPM', 'AP', 'USB')
EVIDENCE = ((0, 'Setup lock'), (1, 'Setup complete'), (3, 'ESC check'),
            (4, 'Verified motor mask'), (5, 'Sensor check'), (6, 'Receiver check'),
            (7, 'Legacy failsafe check'))


def validated_receipt(data):
    if not isinstance(data, dict) or data.get('format') != 1:
        raise ValueError('Unknown restart receipt format.')
    status = validate_values(130, data.get('setup'))
    kit_id = status[15]
    boot = data.get('fc_session')
    if (not kit_id.strip() or kit_id != data.get('kit_id') or status[:2] != [False, True]
            or status[8] or type(boot) is not int or not 0 < boot <= 0xffffffff
            or type(data.get('demo')) is not bool or not isinstance(data.get('saved_at'), str)):
        raise ValueError('Incomplete verified setup receipt.')
    return {**data, 'setup': status, 'settings': settings_snapshot(data.get('settings'))}


def make_receipt(status, fc_session, verified, demo):
    return validated_receipt({
        'format': 1, 'kit_id': status[15], 'fc_session': fc_session, 'setup': status,
        'settings': verified, 'demo': bool(demo),
        'saved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })


def save_receipt(path, receipt):
    write_json_atomic(path, validated_receipt(receipt))


def load_receipt(path):
    try:
        return validated_receipt(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _result(state, message, changes=()):
    return {'state': state, 'message': message, 'changes': list(changes)}


def verify_restart(link, receipt, cancelled):
    """Use addressed GET / READ_SAVED RPC replies for every comparison."""
    receipt = validated_receipt(receipt)
    boot = link.fc_session

    def guard():
        if cancelled() or not link.connected or link.fc_session != boot:
            raise RuntimeError('Connection changed. Reconnect and run the check again.')

    def read(group, *, saved=False):
        guard()
        try:
            values = read_section(link, group, saved=saved, cancel=cancelled)
        except RemoteError as error:
            guard()
            if saved and error.code == 'NOT_SAVED':
                return None
            raise RuntimeError(f"{DRONE_GROUPS[group]['name']} read failed: {error}") from error
        guard()
        return values

    before = read(130)
    if before[15] != receipt['kit_id'] or bool(getattr(link, 'demo', False)) != receipt['demo']:
        return _result('wrong_kit', 'Connect the kit used for the final save.')
    if type(boot) is not int or not 0 < boot <= 0xffffffff:
        raise RuntimeError('Kit boot identity is unavailable. Reconnect and try again.')
    if boot == receipt['fc_session']:
        return _result('same_boot', 'Kit connected · restart not verified.')
    if not read(120)[7]:
        raise RuntimeError('Kit storage is unavailable. Restore storage and retry.')

    active = {}
    stored = {}
    for group in SETTINGS_GROUPS:
        active[group] = read(group)
        stored[group] = read(group, saved=True)
    selected_source = read(110)[0]
    after = read(130)
    if before != after:
        raise RuntimeError('Kit setup changed during the check. Hold the settings steady and retry.')
    if not read(120)[7]:
        raise RuntimeError('Kit storage became unavailable. Retry when storage is ready.')
    guard()

    rows = []
    for group, value in stored.items():
        if value is None:
            name = DRONE_GROUPS[group]['name'].replace('_', ' ').title()
            rows.append((f'{name} · Stored', 'Verified at final save', 'No saved copy'))
    # Missing stored groups have a single explicit row instead of invented per-field values.
    available_stored = {g: values if values is not None else receipt['settings'][g]
                        for g, values in stored.items()}
    for label, snapshot in (('Active', active), ('Stored', available_stored)):
        for change in setting_changes(receipt['settings'], snapshot):
            rows.append((f'{change.label} · {label}', change.before, change.after))
    for i, label in EVIDENCE:
        if receipt['setup'][i] != after[i]:
            rows.append((label, str(receipt['setup'][i]), str(after[i])))
    expected_source = receipt['settings'][134][1]
    if selected_source != expected_source:
        rows.append(('Current flight input', SOURCE_NAMES[expected_source], SOURCE_NAMES[selected_source]))
    if rows:
        return _result('mismatch', 'The kit restarted with differences from the final save.', rows)
    return _result('verified', 'Same kit, new boot. Settings and setup checks match the final save.')
