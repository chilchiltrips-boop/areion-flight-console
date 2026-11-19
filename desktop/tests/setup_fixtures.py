"""Explicit completed setup fixtures for tests of post-setup flight behavior.

These helpers exercise the public setup API. They never clear the production
lock directly or change the default state of a new DemoLink.
"""
from areion_gui.model import NEUTRAL
from areion_gui.setup_backend import run_setup_action, SETUP_SETTINGS
from zebjus_areion_link.schema import DRONE_GROUPS


def complete_demo_setup(link, source=1):
    if not getattr(link, 'demo', False):
        raise AssertionError('Setup test fixtures may operate only on DemoLink')
    status = link.read_group(130)
    if not status[0] and status[1] and link.source == source and link.values[134][1] == source:
        return status

    def action(name, payload=None):
        result = run_setup_action(link, name, payload or {}, lambda: False)
        if result.get('complete') is False:
            raise AssertionError(result)
        return result

    def command(name, args=None):
        return action('command', {'command': name, 'args': [1, 0, 0, 0] if args is None else args})

    action('begin', {'props_removed': True})
    groups = {group: link.values[group][:] for group in SETUP_SETTINGS}
    groups[134][1] = source
    action('apply_save', {'groups': groups})
    command('SENSOR_OK')
    if source == 0:
        link.demo_set_receiver(NEUTRAL)
        command('RX_OK')
    command('ESC_SKIP')
    command('MOTOR_START', [15, 1, 0, 0])
    command('MOTOR_SET', [15, 1120, 0, 0])
    command('MOTOR_STOP', [0, 0, 0, 0])
    command('MOTOR_OK', [15, 1, 0, 0])
    result = action('finalize', {'groups': {group: link.values[group][:] for group in SETUP_SETTINGS}})
    status = result['values'][130]
    if status[:2] != [False, True] or link.armed:
        raise AssertionError('Fixture must complete setup without arming')
    return status


def complete_demo_window(window, source=1):
    """Complete the simulated FC and refresh the same telemetry used by the UI."""
    complete_demo_setup(window.link, source)
    for group in (*SETUP_SETTINGS, 110, 120, 122, 130, 131):
        schema = DRONE_GROUPS[group]['schema']
        window.data.put(group, schema, window.link.read_group(group, schema), received=False)
    window._select_source_value(source)
