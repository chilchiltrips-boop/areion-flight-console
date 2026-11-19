"""Verify the final-save comparison tracks the original kit and actual save payload."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from areion_gui.setup_changes import SETTINGS_GROUPS, settings_snapshot, setting_changes
from areion_gui.wizard_extended import ExtendedSetupWizard
from test_wizard_v3 import setup_status
from zebjus_areion_link.schema import DRONE_GROUPS


def groups(kit='board-A', source=0):
    values = {group: [field['default'] for field in DRONE_GROUPS[group]['fields']]
              for group in SETTINGS_GROUPS}
    values[130] = setup_status(kit=kit, motor_mask=15, sensor=True, receiver=True, esc=4)
    values[134][1] = source
    return values


class SettingsSnapshotTests(unittest.TestCase):
    def test_validated_copy_and_protocol_tolerance(self):
        values = groups()
        baseline = settings_snapshot(json.loads(json.dumps(values)))
        values[2][0] += 1e-8
        after = settings_snapshot(values)
        self.assertEqual(setting_changes(baseline, after), [])
        values[134][1] = 2
        values[132][3] = 1
        rows = setting_changes(baseline, settings_snapshot(values))
        self.assertEqual([(r.label, r.before, r.after) for r in rows],
                         [('Flight input', 'PPM', 'USB'), ('CH1 reversal', 'Normal', 'Reversed')])
        values[134][1] = 100
        with self.assertRaises(ValueError):
            settings_snapshot(values)
        del values[134]
        with self.assertRaises(ValueError):
            settings_snapshot(values)


class ReviewChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'setup.json'
        self.w = ExtendedSetupWizard(self.path)
        self.w.timer.stop()
        self.addCleanup(self.w.close)
        self.enter('initial')

    def enter(self, session):
        self.w.fc_identity = session
        self.w.set_connection_state(connected=True, disarmed=True)
        self.w.begin_confirmed = True
        self.w.step = 8

    def read(self, values):
        self.w.action_finished({'action':'read', 'complete':True, 'values':values}, None)

    def test_requires_full_read_respects_reload_reconnect_and_change_of_kit(self):
        w = self.w
        self.read({130:groups()[130], 6:groups()[6]})
        self.assertIn('Waiting', w.change_summary.text())
        self.read(groups())
        self.assertIn('match', w.change_summary.text())
        self.read(groups(source=2))
        self.assertEqual(w.change_rows.text(), 'Flight input   PPM → USB')
        w.connection_lost()
        self.assertIn('Connect', w.change_summary.text())
        self.enter('reconnected')
        self.read({130:groups()[130]})
        self.assertIn('Waiting', w.change_summary.text())
        self.read(groups(source=2))
        self.assertIn('PPM → USB', w.change_rows.text())
        self.read(groups('board-B', 2))
        self.assertIn('match', w.change_summary.text())
        self.assertEqual(w.change_rows.text(), '')

    def test_initial_values_survive_resume_file_and_new_lock_discards_old_baseline(self):
        w = self.w
        self.read(groups())
        self.read(groups(source=1))
        restored = ExtendedSetupWizard(self.path)
        self.addCleanup(restored.close)
        self.assertEqual(restored.opening_settings[134][1], 0)
        w.action_finished({'action':'begin','values':{130:groups()[130]},'complete':True}, None)
        self.assertIsNone(w.opening_settings)
        self.read(groups(source=1))
        self.assertIn('match', w.change_summary.text())

    def test_compares_draft_and_final_payload_including_pending_offsets_and_idle(self):
        w = self.w
        values = groups()
        self.read(values)
        w.sensor_panel.offsets[0].setValue(0.1)
        w.idle_boxes[1].setValue(1123)
        w._update_navigation()
        self.assertIn('Motor 2 idle', w.change_rows.text())
        self.assertIn('Accelerometer X offset', w.change_rows.text())
        self.assertIn('2 settings changed', w.change_summary.text())
        self.assertEqual(w._final_groups()[134][8], 1123)
        self.assertEqual(w._final_groups()[6][0], 0.1)
        out = []
        w.action_requested.connect(lambda action, payload: out.append((action, payload)))
        w.save_ack.setChecked(True)
        w._finalize()
        self.assertEqual(out[-1][0], 'finalize')
        self.assertEqual(out[-1][1]['groups'], w._final_groups())

    def test_review_and_single_axis_edit_keep_untouched_fc_offset_precision(self):
        source = groups()
        source[6] = [-0.1000625, 0.0123456, 0.1200625]
        self.read(source)
        self.w._choose_input('USB')
        self.w._update_navigation()
        self.assertEqual(self.w.change_rows.text(), 'Flight input   PPM → USB')
        self.assertEqual(self.w._final_groups()[6], source[6])
        self.w.sensor_panel.offsets[1].setValue(0.0234)
        self.assertEqual(self.w._final_groups()[6], [source[6][0], 0.0234, source[6][2]])
        self.assertEqual(self.w._snapshot()['imu']['offsets'], self.w._final_groups()[6])

    def test_verified_reset_compares_defaults_with_pre_reset_flight_input(self):
        self.read(groups(source=2))
        defaults = groups()
        defaults[130] = setup_status(kit='board-A')
        self.w._accept_reset(defaults)
        self.w._update_navigation()
        self.assertIn('USB → PPM', self.w.change_rows.text())
        self.w.reset_unverified = True
        self.w._update_navigation()
        self.assertIn('Reload', self.w.change_summary.text())
        self.assertEqual(self.w.change_rows.text(), '')


if __name__ == '__main__':
    unittest.main()
