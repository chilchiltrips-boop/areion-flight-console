"""Field-by-field comparison of complete, firmware-validated setup settings."""
from dataclasses import dataclass

from zebjus_areion_link.schema import DRONE_GROUPS
from .model import equal_values, FLIGHT_MODES, validate_values
from .setup_config import PROFILE_NAMES, SOURCE_IDS

SETTINGS_GROUPS = (2, 3, 4, 6, 7, 112, 132, 134)
PROFILE_KEYS = ('aerion450', 'aerion250', 'stable', 'custom')
INPUT_NAMES = {value: name for name, value in SOURCE_IDS.items()}

LABELS = {
    4: ('Low throttle', 'Yaw right', 'Yaw left', 'Throttle movement',
        'ARM hold', 'DISARM hold', 'Idle auto-disarm'),
    6: ('Accelerometer X offset', 'Accelerometer Y offset', 'Accelerometer Z offset'),
    7: ('Flight mode channel', 'Angle stick scale', 'Rate stick scale', 'Yaw stick scale',
        'Low switch mode', 'High switch mode'),
    112: ('PPM loss timeout', 'AP / USB loss timeout'),
    134: ('Aircraft profile', 'Flight input', 'Roll channel', 'Pitch channel', 'Throttle channel',
          'Yaw channel', 'Stick deadband', 'Motor 1 idle', 'Motor 2 idle', 'Motor 3 idle',
          'Motor 4 idle'),
}

@dataclass(frozen=True)
class SettingChange:
    group: int
    index: int
    label: str
    before: str
    after: str


def settings_snapshot(groups):
    """Copy all eight settings groups. JSON checkpoints use decimal string keys."""
    if not isinstance(groups, dict):
        raise ValueError('A complete set of kit settings is required.')
    return {group: validate_values(group, groups.get(group, groups.get(str(group))))
            for group in SETTINGS_GROUPS}


def _setting_label(group, index):
    if group in LABELS:
        return LABELS[group][index]
    if group == 132:
        field = ('minimum', 'centre', 'maximum', 'reversal')[index % 4]
        return f'CH{index // 4 + 1} {field}'
    name = DRONE_GROUPS[group]['fields'][index]['name']
    loop = 'Rate' if group == 2 else 'Angle'
    axis = name[len(loop) + 1:]
    return f'{loop} PID · {axis} {name[0]}'


def _display_value(group, index, value):
    if group == 134 and index == 0:
        return PROFILE_NAMES[PROFILE_KEYS[value]]
    if group == 134 and index == 1:
        return INPUT_NAMES[value]
    if group == 7 and index in (4, 5):
        return FLIGHT_MODES[value]
    if (group == 134 and 2 <= index <= 5) or (group == 7 and index == 0):
        return f'CH{value}'
    if group == 132 and index % 4 == 3:
        return 'Reversed' if value else 'Normal'
    if group == 6:
        return f'{value:+.8g} g'
    if group == 112:
        return f'{value} ms'
    if group == 4 and index >= 4:
        return f'{value} s'
    if group == 132 or group == 4 or (group == 134 and index >= 6):
        return f'{value} µs'
    return f'{value:.8g}'


def setting_changes(before, after):
    """Compare validated snapshots using the same tolerance as firmware readback."""
    differences = []
    for group in (134, 2, 3, 6, 132, 4, 7, 112):
        for index, (old, new) in enumerate(zip(before[group], after[group])):
            if not equal_values((old,), (new,)):
                differences.append(SettingChange(group, index, _setting_label(group, index),
                                                 _display_value(group, index, old),
                                                 _display_value(group, index, new)))
    return differences
