"""Drive switch preview, change review and post-reboot verification in the console."""
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.model import NEUTRAL
from areion_gui.window import MainWindow
from fc_fixture import DemoLink
from setup_fixtures import complete_demo_setup
from zebjus_areion_link.schema import DRONE_GROUPS


class WizardVerificationFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        path = patch('areion_gui.window.QStandardPaths.writableLocation', return_value=self.folder.name)
        path.start()
        self.addCleanup(path.stop)
        self.window = MainWindow()
        self.addCleanup(lambda: QTest.qWait(180))
        self.addCleanup(self.window.close)
        self.window.show()
        self.link = DemoLink()
        complete_demo_setup(self.link, source=0)
        # Model a production transport using only the in-process test double.
        self.link.demo = False
        self.install(self.link)
        QTest.qWait(100)
        self.window.welcome.setup_button.click()
        self.wizard = self.window.setup_wizard
        self.wait_for(lambda: self.wizard._ready() and self.wizard.loaded_identity is not None)
        self.wizard.propeller_check.click()

    def wait_for(self, predicate, detail=''):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(12)
        self.fail(detail() if callable(detail) else detail or 'Timed out waiting for GUI')

    def install(self, link):
        link.connected = True
        groups = (120, 122, 121, 125, 110, 130, 131, 132, 134, 136)
        self.window.install_link(link, {g:link.read_group(g, DRONE_GROUPS[g]['schema']) for g in groups})

    def next_to(self, target):
        w = self.wizard
        while w.step < target:
            self.wait_for(w.next_button.isEnabled, lambda: f'Next unavailable at {w.step}: {w.last_message}')
            old = w.step
            QTest.mouseClick(w.next_button, Qt.MouseButton.LeftButton)
            self.assertGreater(w.step, old)
        self.assertEqual(w.step, target)

    def save(self):
        self.next_to(8)
        self.wizard.save_ack.click()
        self.assertTrue(self.wizard.next_button.isEnabled())
        self.wizard.next_button.click()
        self.wait_for(lambda: self.wizard.finalized_this_visit)
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        self.assertFalse(self.link.armed)
        self.wait_for(lambda: (self.wizard.restart_open_button.isVisible()
                               and self.wizard.restart_open_button.isEnabled()))

    def watch_writes(self, stack, link):
        # Log all control and setting calls. Background telemetry reads may proceed.
        names = ('action', 'set_group', 'save_group', 'send_control', 'arm', 'disarm')
        return [stack.enter_context(patch.object(link, name, wraps=getattr(link, name))) for name in names]

    def reconnect(self, link):
        old = self.window.link
        self.window.disconnect()
        self.wait_for(lambda: not old.connected)
        # Change the local owner identifier on reconnect, like a fresh USB/AP link.
        link.session += 17
        self.install(link)

    def wait_phase(self, phase):
        self.wait_for(lambda: self.wizard.restart_page.state == phase,
                      lambda: f'Expected {phase!r}, last status {self.wizard.restart_status.text()!r}')

    def test_switch_observation_and_single_input_change_through_real_pages(self):
        w = self.wizard
        self.next_to(7)
        for pulse, marker in ((1000, 'LOW'), (2000, 'HIGH')):
            channels = list(NEUTRAL)
            channels[4] = pulse
            self.link.demo_set_receiver(channels)
            self.wait_for(lambda: str(pulse) in w.mode_test.text() and marker in w.mode_test.text(),
                          lambda: w.mode_test.text())
        self.assertIn('Both positions', w.mode_test.text())
        self.assertEqual(self.link.read_group(130)[:2], [True, False])
        while w.step > 2:
            self.assertTrue(w.back_button.isEnabled())
            previous = w.step
            w.back_button.click()
            self.assertLess(w.step, previous)
        w.input_buttons['USB'].click()
        w.input_apply.click()
        self.wait_for(lambda: self.link.source == 2 and not w.operation_busy)
        self.next_to(8)
        self.assertIn('1', w.change_summary.text())
        self.assertIn('PPM', w.change_rows.text())
        self.assertIn('USB', w.change_rows.text())
        self.assertNotIn('PID', w.change_rows.text())
        self.save()
        self.assertEqual(self.link.saved[134][1], 2)
        with ExitStack() as stack:
            writes = self.watch_writes(stack, self.link)
            w.restart_open_button.click()
            self.wait_phase('same_boot')
            self.reconnect(self.link)
            self.wait_phase('same_boot')
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])
        self.assertTrue(w.restart_view_active, (w.step, w.restart_page.state, w.next_button.text()))
        self.assertTrue(w.next_button.isEnabled(), (w.step, w.last_message))
        w.next_button.click()
        self.wait_for(lambda: self.window.pages.currentWidget() is self.window.welcome, lambda: f'{w.step} {w.restart_view_active} {w.next_button.text()} {self.window.last_notice}')

    def test_reconnect_reboot_and_reread_are_distinct_and_read_only(self):
        w = self.wizard
        self.save()
        with ExitStack() as stack:
            writes = self.watch_writes(stack, self.link)
            self.assertTrue(w.restart_open_button.isEnabled())
            w.restart_open_button.click()
            self.assertTrue(w.restart_view_active)
            self.assertEqual(w.step, 9)
            self.wait_phase('same_boot')
            self.reconnect(self.link)
            self.wait_phase('same_boot')
            self.assertEqual(self.link.read_group(130)[:2], [False, True])
            self.assertFalse(self.window._setup_guard)

            # Reconnect can finish before an older settings-card read delivers
            # its queued Qt callback. The old generation cannot invalidate it.
            with patch.object(self.window, '_linked') as queued:
                self.window.settings_request(6, 'read', [])
            queued.assert_called_once()
            previous_read_finished = queued.call_args.args[1]
            self.link.demo_restart()
            self.reconnect(self.link)
            previous_read_finished(None, RuntimeError('Old link closed'))
            self.assertTrue(self.window._connected())
            self.wait_phase('verified')
            # The optional action and its navigation must remain visible at minimum size.
            self.window.resize(900, 700)
            self.app.processEvents()
            self.assertEqual(w.scrolls[9].horizontalScrollBar().maximum(), 0)
            for button in (w.next_button, w.restart_check_button):
                self.assertTrue(button.isVisibleTo(self.window))
                bounds = QRect(button.mapTo(self.window, QPoint()), button.size())
                self.assertTrue(self.window.rect().contains(bounds))
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])

            # A second physical board boot can load altered flash. Report the actual field.
            self.link.saved[6][0] = .25
            self.link.demo_restart()
            self.reconnect(self.link)
            self.wait_phase('mismatch')
            rows = [w.restart_table.item(r, c).text() for r in range(w.restart_table.rowCount())
                    for c in range(w.restart_table.columnCount()) if w.restart_table.item(r, c)]
            self.assertTrue(any('acc' in text.lower() or 'offset' in text.lower() for text in rows), rows)
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])
            self.assertFalse(self.link.armed)

    def test_focus_loss_during_background_restart_read_sends_no_stop(self):
        self.save()
        self.wizard.restart_open_button.click()
        self.wait_phase('same_boot')
        entered, release = threading.Event(), threading.Event()
        read = self.link.read_group

        def delayed_read(group, schema=1, saved=False, **kwargs):
            if saved and group == 2:
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Restart read was never released')
            return read(group, schema, saved, **kwargs)

        with ExitStack() as stack:
            writes = self.watch_writes(stack, self.link)
            stack.enter_context(patch.object(self.link, 'read_group', delayed_read))
            stack.callback(release.set)
            self.link.demo_restart()
            self.reconnect(self.link)
            self.wait_for(entered.is_set, lambda: self.wizard.restart_status.text())
            self.window._application_state(Qt.ApplicationState.ApplicationInactive)
            self.assertFalse(self.window._setup_guard)
            release.set()
            self.wait_phase('verified')
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])

    def test_navigating_away_then_choosing_setup_starts_a_guarded_edit_visit(self):
        w = self.wizard
        self.save()
        w.restart_open_button.click()
        self.wait_phase('same_boot')
        self.window.navigate(7)
        QTest.qWait(80)
        self.wait_for(lambda: self.window.pages.currentWidget() is self.window.welcome)
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        self.window.welcome.setup_button.click()
        self.wait_for(lambda: self.link.read_group(130)[:2] == [True, False],
                      lambda: f'{w.step} {w.restart_view_active} {self.window._setup_guard} {w.last_message}')
        self.assertEqual(w.step, 0)
        self.assertFalse(w.restart_view_active)
        self.assertTrue(self.window._setup_guard)
        self.assertFalse(w.next_button.isEnabled())

    def test_new_console_opens_saved_receipt_from_welcome_without_entering_setup(self):
        self.save()
        self.wizard.next_button.click()
        self.window.close()
        self.wait_for(lambda: not self.link.connected)
        self.link.demo_restart()
        self.window = MainWindow()
        self.addCleanup(lambda: QTest.qWait(180))
        self.addCleanup(self.window.close)
        self.window.show()
        with ExitStack() as stack:
            writes = self.watch_writes(stack, self.link)
            self.install(self.link)
            self.wait_for(lambda: (self.window.welcome.restart_button is not None
                                   and self.window.welcome.restart_button.isVisible()))
            self.window.welcome.restart_button.click()
            self.wizard = self.window.setup_wizard
            self.wait_phase('verified')
            self.assertEqual(self.window.pages.currentWidget(), self.wizard)
            self.assertFalse(self.window._setup_guard)
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])
            self.assertEqual(self.link.read_group(130)[:2], [False, True])

    def test_saved_receipt_against_another_kit_never_reports_verified(self):
        self.save()
        self.wizard.next_button.click()
        self.wait_for(lambda: self.window.pages.currentWidget() is self.window.welcome)
        other = DemoLink()
        complete_demo_setup(other, source=0)
        other.demo = False
        other._stored_setup[15] = 'ANOTHER-KIT'
        other.demo_restart()
        with ExitStack() as stack:
            writes = self.watch_writes(stack, other)
            self.reconnect(other)
            self.wait_for(lambda: (self.window.welcome.restart_button is not None
                                   and self.window.welcome.restart_button.isVisible()))
            self.window.welcome.restart_button.click()
            self.wait_phase('wrong_kit')
            self.assertFalse(self.window._setup_guard)
            self.assertTrue(all(call.call_count == 0 for call in writes), [x.mock_calls for x in writes])
            self.assertEqual(other.read_group(130)[:2], [False, True])


if __name__ == '__main__':
    unittest.main()
