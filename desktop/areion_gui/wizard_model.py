"""Local setup draft only. This module never sends commands to a flight controller."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

DEFAULT_SELECTIONS = {
    'vehicle_type': 'multirotor',
    'drone_profile': 'f450_esc',
    'frame_class': 'quadcopter',
    'frame_layout': 'quad_x',
}
LAYOUTS = {'quad_x': 'Quad X', 'quad_plus': 'Quad +', 'quad_h': 'Quad H'}
# Top view, with FRONT at the top. Only the user's confirmed Quad X map is defined.
QUAD_X_MOTORS = (
    ('M1', 'Front left', 'CW'),
    ('M2', 'Front right', 'CCW'),
    ('M3', 'Back right', 'CW'),
    ('M4', 'Back left', 'CCW'),
)


def validate_selections(values):
    if not isinstance(values, dict):
        raise ValueError('Setup selections must be an object.')
    result = {}
    for key, default in DEFAULT_SELECTIONS.items():
        value = values.get(key)
        allowed = LAYOUTS if key == 'frame_layout' else (default,)
        if value not in allowed:
            raise ValueError(f'Unsupported {key}: {value!r}')
        result[key] = value
    return result


def make_draft(selections, configuration=None, stage='initial_selections', receipt=None):
    choices = validate_selections(selections)
    draft = {
        'schema_version': 1,
        'stage': 'initial_selections',
        'wizard_complete': False,
        'hardware_applied': False,
        'saved_at_utc': datetime.now(timezone.utc).isoformat(),
        'selections': choices,
        'motor_map': [dict(motor=m, position=p, rotation=r) for m, p, r in QUAD_X_MOTORS]
                     if choices['frame_layout'] == 'quad_x' else [],
        'motor_map_status': 'quad_x_reference' if choices['frame_layout'] == 'quad_x' else 'not_defined',
    }
    if configuration is not None:
        from .setup_config import validate_configuration
        if stage not in ('initial_selections','configuration_saved'):raise ValueError('Invalid draft stage.')
        draft.update(schema_version=4,stage=stage,configuration=validate_configuration(configuration),
                     pending_steps=['Complete and save hardware setup'],receipt=None)
        if receipt is not None:
            from .model import validate_values
            if not isinstance(receipt,dict) or type(receipt.get('demo')) is not bool:
                raise ValueError('Invalid setup save receipt.')
            state=validate_values(130,receipt.get('setup_status'))
            complete=bool(state[1] and not state[0])
            draft['receipt']={'setup_status':state,'demo':receipt['demo']}
            draft['wizard_complete']=complete
            draft['hardware_applied']=complete and not receipt['demo']
            draft['pending_steps']=[] if complete else ['Complete and save hardware setup']
    return draft


def read_draft(path):
    draft = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(draft, dict) or type(draft.get('schema_version')) is not int or draft['schema_version'] not in (1,2,3,4):
        raise ValueError('Unsupported setup draft format.')
    if draft.get('stage') not in ('initial_selections','configuration_saved'):
        raise ValueError('Invalid setup draft stage.')
    if draft['schema_version']<4 and (draft.get('wizard_complete') is not False or draft.get('hardware_applied') is not False):
        raise ValueError('Legacy drafts cannot prove completed hardware setup.')
    draft['selections'] = validate_selections(draft.get('selections'))
    expected = make_draft(draft['selections'])
    if draft.get('motor_map') != expected['motor_map'] or draft.get('motor_map_status') != expected['motor_map_status']:
        raise ValueError('Setup motor map does not match the selected layout.')
    if draft['schema_version'] in (2,3,4):
        from .setup_config import validate_configuration,migrate_configuration
        if draft['schema_version']<4:
            draft['configuration']=migrate_configuration(draft.get('configuration'))
        draft['configuration']=validate_configuration(draft.get('configuration'))
    if draft['schema_version']==4:
        expected=make_draft(draft['selections'],draft['configuration'],draft['stage'],draft.get('receipt'))
        for field in ('wizard_complete','hardware_applied','pending_steps'):
            if draft.get(field)!=expected[field]:raise ValueError('Local receipt does not match setup status.')
    return draft


def save_draft(path, selections, configuration=None, stage='initial_selections', receipt=None):
    """Write a complete draft atomically, then verify the file that was saved."""
    draft = make_draft(selections, configuration, stage, receipt)
    write_json_atomic(path, draft)
    if read_draft(path) != draft:
        raise OSError('Setup draft readback verification failed.')
    return draft


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
