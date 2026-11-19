"""The optional verifier has no path to setup writes or motor commands."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from areion_gui.wizard_extended import ExtendedSetupWizard


class RestartPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.w = ExtendedSetupWizard(Path(self.temp.name) / 'setup.json')
        self.w.timer.stop()
        self.writes = []
        self.exits = []
        self.reads = []
        self.w.action_requested.connect(lambda *args: self.writes.append(args))
        self.w.finish_requested.connect(lambda: self.exits.append(True))
        self.w.restart_check_requested.connect(lambda: self.reads.append(True))
        self.receipt = {'kit_id': 'FC-A', 'fc_session': 10}

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_read_only_mode_isolated_from_setup_and_esc_commands(self):
        self.w.set_restart_context(self.receipt, False, None, None, False)
        self.assertTrue(self.w.show_restart_check())
        self.w.on_enter()
        self.w.set_connection_state(connected=True, disarmed=True)
        self.w._tick()
        self.w._show_step(0)
        self.assertEqual(self.w.step, 9)
        self.assertTrue(self.w.restart_view_active)
        self.assertFalse(self.w._request('begin', {}))
        self.assertFalse(self.w._request('command', {'command': 'MOTOR_START'}))
        self.w.connection_lost()
        self.w.receive_telemetry({}, None, 0., ('other', 23))
        self.assertFalse(self.w.restart_check_button.isEnabled())
        self.w.back()
        self.assertEqual(self.exits, [True])
        self.assertFalse(self.w.restart_view_active)
        self.assertEqual(self.reads, [])
        self.assertEqual(self.writes, [])

    def test_context_scoping_and_actual_mismatch_detail(self):
        self.w.show_restart_check()
        page = self.w.restart_page
        self.w.set_restart_context(self.receipt, True, 10, 'FC-A', False)
        self.assertEqual(page.state, 'same_boot')
        self.assertFalse(self.w.restart_check_button.isEnabled())
        self.w.set_restart_context(self.receipt, True, 12, 'FC-B', False)
        self.assertEqual(page.state, 'wrong_kit')
        self.w.set_restart_context(self.receipt, True, 12, 'FC-A', False)
        self.assertEqual(page.state, 'ready')
        self.w.restart_check_button.click()
        self.assertEqual(self.reads, [True])
        changes = [('Boot input', 'PPM', 'USB')]
        self.w.set_restart_result({'state':'mismatch','message':'One setting differs.', 'changes':changes})
        self.assertEqual(page.state, 'mismatch')
        self.assertEqual(self.w.restart_table.item(0, 2).text(), 'USB')
        self.w.set_restart_context(self.receipt, True, 12, None, False)
        self.assertEqual(page.state, 'waiting')
        self.assertTrue(self.w.restart_table.isHidden())
        self.w.set_restart_context(self.receipt, True, 12, 'FC-A', False)
        self.assertEqual(page.state, 'mismatch')
        self.w.set_restart_context(self.receipt, True, 14, 'FC-A', False)
        self.assertEqual(page.state, 'ready')
        self.assertEqual(self.w.restart_table.rowCount(), 0)
        self.assertEqual(self.writes, [])

    def test_footer_stays_read_only_and_exitable_in_every_phase(self):
        self.w.show_restart_check()
        for connected, boot, kit in ((False, None, None), (True, 10, 'FC-A'), (True, 13, 'FC-B'),
                                     (True, 13, None), (True, 13, 'FC-A')):
            self.w.set_restart_context(self.receipt, connected, boot, kit, False)
            self.assertEqual(self.w.next_button.text(), 'Done')
            self.assertTrue(self.w.next_button.isEnabled())
            self.assertEqual(self.w.lock_note.text(), 'Read-only check')
            self.assertFalse(self.w.step_buttons[0].isEnabled())
        for state in ('reading', 'error', 'mismatch', 'verified'):
            self.w.set_restart_result({'state': state, 'message': state, 'changes': []})
            self.assertTrue(self.w.next_button.isEnabled())
            self.assertEqual(self.w.next_button.text(), 'Done')
            self.assertTrue(self.w.message.isHidden())
        self.w.next_button.click()
        self.assertEqual(self.exits, [True])
        self.assertEqual(self.writes, [])

    def test_verified_finish_can_leave_or_open_optional_check(self):
        self.w._show_step(8)
        self.w.finalized_this_visit = True
        self.w.set_restart_context(self.receipt, True, 10, 'FC-A', False)
        self.assertEqual(self.w.next_button.text(), 'Done')
        self.assertTrue(self.w.restart_open_button.isEnabled())
        self.w.restart_open_button.click()
        self.assertEqual(self.w.step, 9)
        self.w.back()
        self.assertEqual(self.w.step, 8)
        self.assertEqual(self.exits, [])
        self.w.next_button.click()
        self.assertEqual(self.exits, [True])
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
