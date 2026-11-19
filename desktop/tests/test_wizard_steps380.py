"""Presentation changes follow wizard state without issuing device commands."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication
from areion_gui.wizard_extended import ExtendedSetupWizard
from test_wizard_v3 import setup_status


class StepViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.w = ExtendedSetupWizard(Path(self.folder.name) / 'draft.json')
        self.w.timer.stop()
        self.calls = []
        self.w.action_requested.connect(lambda action, payload: self.calls.append((action, payload)))

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_model_selection_and_wire_inspection_are_read_only(self):
        self.w.pid_buttons['aerion250'].click()
        self.assertIn('Areion 250', self.w.profile_caption.text())
        self.w.wire_buttons[4].click()
        self.assertEqual(self.w.wiring_view.focus, 4)
        self.assertIn('GPIO 18', self.w.wire_detail.text())
        self.w.wire_buttons[5].click()
        self.assertIn('GPIO 22', self.w.wire_detail.text())
        self.assertIn('GPIO 23', self.w.wire_detail.text())
        self.w.motor_choice.setCurrentIndex(3)
        self.assertEqual(self.w.motor_view.selected_mask, 8)
        self.assertEqual(self.calls, [])

    def test_review_esc_and_motor_readbacks_distinguish_offline_from_done(self):
        w = self.w
        w.set_connection_state(connected=True, disarmed=True)
        w.live = {130:setup_status(esc=3, sensor=True, receiver=True, motor_mask=7, active=True,
                                  m1=1200, m2=1190, m3=1180, m4=1000)}
        w._update_navigation()
        self.assertEqual(w.motor_view.outputs, (1200,1190,1180,1000))
        self.assertFalse(w.motor_running)
        self.assertIn('Test active', w.motor_status.text())
        w.motor_running = True
        w.live[130][8] = False
        w._update_navigation()
        self.assertIn('Test inactive', w.motor_status.text())
        w.motor_running = False
        self.assertEqual(w.esc_sequence.mode, 'current')
        self.assertEqual(w.esc_sequence.stage, 3)
        self.assertEqual(w.review_tiles['Motors'].current, ('3 of 4 verified', 'pending'))
        self.assertEqual(w.review_tiles['Sensors'].current, ('Verified', 'done'))
        self.assertEqual(w.review_tiles['Storage'].current[1], 'pending')
        w.live[130][3] = 6
        w._update_navigation()
        self.assertEqual(w.esc_sequence.mode, 'error')
        self.assertEqual(w.review_tiles['ESC'].current[1], 'error')
        w.connection_lost()
        self.assertEqual(w.esc_sequence.mode, 'offline')
        self.assertIsNone(w.motor_view.outputs)
        self.assertEqual(w.review_tiles['Sensors'].current[1], 'unknown')
        self.assertEqual(self.calls, [])

    def test_arming_preview_follows_draft_immediately_and_does_not_write(self):
        self.w.mode_channel.setCurrentIndex(7)
        self.w.mode_low.setCurrentIndex(1)
        self.w.mode_high.setCurrentIndex(0)
        self.assertEqual(self.w.mode_band.mapping, ('CH8','RATE / ACRO','ANGLE'))
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
