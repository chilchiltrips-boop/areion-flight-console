"""Manual USB connections, device discovery and remembered port on the desktop."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from contextlib import ExitStack
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.window import MainWindow
from fc_fixture import DemoLink
from zebjus_areion_link.schema import DRONE_GROUPS


FIRST = '/dev/cu.usbmodem1001'
LAST = '/dev/cu.usbmodem2101'
EXTRA = '/dev/cu.usbmodem3001'


def path_status(name, datagram=False, confirmed=True):
    return dict(name=name, datagram=datagram, active=True, confirmed=confirmed,
                healthy=confirmed, last_received_age=.01 if confirmed else None,
                error=None, sent_frames=4, received_frames=3 if confirmed else 0)


class VerifiedLink(DemoLink):
    """Fixture for the result returned by open_link after its handshake and reads."""
    demo = False

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    @property
    def transport_status(self):
        return self.paths

    def connection_result(self):
        values = {g: self.read_group(g, DRONE_GROUPS[g]['schema'])
                  for g in (125, 120, 122, 121, 110, 130, 132, 134, 136)}
        return self, values, None, []


class PortWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        directory = self.resources.enter_context(tempfile.TemporaryDirectory())
        self.resources.enter_context(patch('areion_gui.window.QStandardPaths.writableLocation',
                                           return_value=directory))
        self.devices = [FIRST, LAST]
        self.scan_threads = []
        self.resources.enter_context(patch('serial.tools.list_ports.comports', self.enumerate_devices))
        self.open_serial = self.resources.enter_context(patch('serial.Serial.open',
            side_effect=AssertionError('Passive discovery attempted to open a serial port.')))
        self.open_link = self.resources.enter_context(patch('areion_gui.window.open_link'))
        self.w = None
        self.addCleanup(self.close_window)
        self.launch_window()

    def enumerate_devices(self):
        self.scan_threads.append(threading.get_ident())
        return [SimpleNamespace(device=path, description='USB test device') for path in self.devices]

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(10)
        self.fail(message)

    def launch_window(self):
        self.w = MainWindow()
        self.w.show()
        self.wait_for(lambda: self.w.port.findText(FIRST) >= 0, 'Initial USB enumeration did not finish')

    def close_window(self):
        if self.w is not None:
            self.w.close()
            self.wait_for(lambda: self.w.close_ready, 'Window did not close')
            self.w.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.w = None

    def restart(self):
        self.close_window()
        self.launch_window()

    def connect_to(self, port, mode='USB', *, paths=None, failure=None):
        self.w.transport.setCurrentText(mode)
        self.w.port.setCurrentText(port)
        self.open_link.side_effect = failure
        if failure is None:
            if paths is None:
                paths = [path_status(f'serial://{port}@115200')]
            self.open_link.return_value = VerifiedLink(paths).connection_result()
        prior = self.open_link.call_count
        self.w.connect_button.click()
        self.wait_for(lambda: self.open_link.call_count > prior and not self.w.connecting,
                      'Explicit connection did not finish')
        self.assertEqual(self.open_link.call_args.args[0]['port'], port)
        self.assertEqual(self.open_link.call_args.args[0]['mode'], mode)

    def test_confirmed_port_returns_as_default_without_opening_it(self):
        self.connect_to(LAST)
        self.assertIsNotNone(self.w.link)
        self.restart()
        self.assertEqual(self.w.port.currentText(), LAST)
        self.assertIsNone(self.w.link)
        self.assertFalse(self.w.connecting)
        self.assertEqual(self.open_link.call_count, 1)
        self.open_serial.assert_not_called()

    def test_busy_and_failed_protocol_do_not_replace_last_confirmed_device(self):
        self.connect_to(LAST)
        for failure in (OSError('Resource busy'), TimeoutError('HELLO not confirmed')):
            with self.subTest(failure=type(failure).__name__):
                self.restart()
                self.connect_to(FIRST, failure=failure)
                self.assertIsNone(self.w.link)
        self.restart()
        self.assertEqual(self.w.port.currentText(), LAST)

    def test_ap_only_and_unconfirmed_usb_in_dual_mode_do_not_save_usb_port(self):
        self.connect_to(LAST)
        ap = path_status('udp://192.168.4.1:8080', datagram=True)
        unconfirmed = path_status(f'serial://{FIRST}@115200', confirmed=False)
        for mode, paths in [('AP', [ap]), ('USB + AP', [unconfirmed, ap])]:
            with self.subTest(mode=mode):
                self.restart()
                self.connect_to(FIRST, mode, paths=paths)
                self.assertIsNotNone(self.w.link)
        self.restart()
        self.assertEqual(self.w.port.currentText(), LAST)

    def test_periodic_hotplug_updates_existing_and_lazily_opened_pickers(self):
        self.w.port_scan_timer.setInterval(60)
        self.w.port.setCurrentText(LAST)
        wizard = self.w.setup_wizard
        self.devices.append(EXTRA)
        self.wait_for(lambda: wizard.port.findText(EXTRA) >= 0, 'Wizard missed device arrival')
        self.assertGreaterEqual(self.w.port.findText(EXTRA), 0)
        calibration = self.w.calibration_page('imu')
        self.assertGreaterEqual(calibration.port.findText(EXTRA), 0)
        self.devices.remove(FIRST)
        self.wait_for(lambda: all(combo.findText(FIRST) < 0 for combo in
                                  [self.w.port, wizard.port, calibration.port]),
                      'Removed port still listed in a selector')
        self.assertEqual(self.w.port.currentText(), LAST)
        self.assertNotIn(threading.get_ident(), self.scan_threads)
        self.open_link.assert_not_called()
        self.open_serial.assert_not_called()

    def test_missing_remembered_port_returns_without_falling_back_or_connecting(self):
        self.connect_to(LAST)
        self.devices.remove(LAST)
        self.restart()
        self.assertEqual(self.w.port.currentText(), LAST)
        self.assertIsNone(self.w.link)
        self.devices.append(LAST)
        self.w.refresh_ports()
        self.wait_for(lambda: self.w.port.findText(LAST) >= 0, 'Remembered device did not reappear')
        self.assertEqual(self.w.port.currentText(), LAST)
        self.assertEqual(self.open_link.call_count, 1)
        self.open_serial.assert_not_called()

    def test_scan_during_an_open_list_preserves_highlight_and_keyboard_selection(self):
        self.w.show_connection_settings()
        selector = self.w.port
        selector.setCurrentIndex(selector.findText(LAST))
        selector.showPopup()
        popup = selector.view()
        self.assertTrue(popup.isVisible())
        popup.setCurrentIndex(selector.model().index(selector.findText(FIRST), 0))
        initial_scan_count = len(self.scan_threads)
        self.devices.insert(0, '/dev/cu.usbmodem0001')
        self.w.refresh_ports()
        self.wait_for(lambda: len(self.scan_threads) > initial_scan_count, 'Hotplug scan did not run')
        # Wait for the worker result to reach the Qt event loop while the picker is open.
        QTest.qWait(80)
        self.assertTrue(popup.isVisible())
        self.assertEqual(popup.currentIndex().data(), FIRST)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        self.assertEqual(selector.currentText(), FIRST)
        self.open_link.assert_not_called()

    def test_editable_popup_updates_on_plug_and_unplug_without_reopening(self):
        self.w.show_connection_settings()
        self.w.port_scan_timer.stop()
        selector = self.w.port
        selector.setCurrentIndex(selector.findText(FIRST))
        selector.showPopup()
        popup = selector.view()
        model = selector.model()
        initial_row = selector.findText(FIRST)
        highlighted = model.index(selector.findText(LAST), 0)
        popup.setCurrentIndex(highlighted)
        initial_y = popup.visualRect(highlighted).top()

        def enabled(row):
            return bool(model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsEnabled)

        # Let the regular discovery timer detect the first change while the menu
        # is already open, then check each additional scan deterministically.
        self.devices[:] = [EXTRA, LAST]
        self.w.port_scan_timer.start(100)
        self.wait_for(lambda: selector.findText(EXTRA) >= 0, 'Open USB picker missed a newly plugged port')
        self.w.port_scan_timer.stop()
        self.wait_for(lambda: not self.w._port_scan_poll.isActive(), 'Completed scan kept polling')
        self.assertTrue(popup.isVisible())
        self.assertFalse(enabled(initial_row))
        self.assertEqual(popup.currentIndex().data(), LAST)
        self.assertEqual(popup.visualRect(popup.currentIndex()).top(), initial_y)
        self.assertEqual(selector.currentText(), FIRST)
        self.assertTrue(enabled(selector.findText(EXTRA)))

        self.devices.append(FIRST)
        self.w.refresh_ports()
        self.wait_for(lambda: enabled(initial_row), 'Replugged item remained disabled in the open list')
        self.assertEqual(selector.findText(FIRST), initial_row)
        self.devices.remove(FIRST)
        self.w.refresh_ports()
        self.wait_for(lambda: not enabled(initial_row), 'Second unplug was not reflected')
        self.assertTrue(popup.isVisible())
        QTest.keyClick(popup, Qt.Key.Key_End)
        self.assertEqual(popup.currentIndex().data(), EXTRA)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        self.assertEqual(selector.currentText(), EXTRA)
        self.assertFalse(popup.isVisible())

        self.wait_for(lambda: selector.findText(FIRST) < 0, 'Closed picker retained a removed device')
        self.assertEqual([selector.itemText(i) for i in range(selector.count())], [LAST, EXTRA])
        self.assertFalse(self.w._port_scan_poll.isActive())
        self.open_link.assert_not_called()
        self.open_serial.assert_not_called()

    def test_open_header_menu_keeps_the_same_keyboard_target_during_hotplug(self):
        self.w.port_scan_timer.setInterval(60)
        self.w.port.setCurrentText(FIRST)
        menu = self.w.endpoint_button.menu()
        self.assertIsNotNone(menu)
        menu.popup(self.w.endpoint_button.mapToGlobal(QPoint(0, self.w.endpoint_button.height())))
        self.wait_for(menu.isVisible, 'Header port menu did not open')
        paths = {action.data(): action for action in menu.actions() if action.data()}
        target = paths[LAST]
        menu.setActiveAction(target)
        original = menu.actionGeometry(target)
        self.devices[:] = [EXTRA, LAST]
        self.wait_for(lambda: any(action.data() == EXTRA for action in menu.actions()),
                      'Open header menu missed a newly added port')
        self.assertFalse(paths[FIRST].isEnabled())
        self.assertIs(menu.activeAction(), target)
        self.assertEqual(menu.actionGeometry(target).top(), original.top())
        QTest.keyClick(menu, Qt.Key.Key_Return)
        self.assertEqual(self.w.port.currentText(), LAST)
        self.assertIn(LAST, self.w.endpoint_button.text())
        self.open_link.assert_not_called()
        self.open_serial.assert_not_called()

    def test_new_ports_do_not_override_an_edited_manual_path(self):
        self.w.show_connection_settings()
        selector = self.w.port
        selector.lineEdit().selectAll()
        manual = '/dev/custom-board'
        QTest.keyClicks(selector.lineEdit(), manual)
        self.devices.append(EXTRA)
        self.w.refresh_ports()
        self.wait_for(lambda: selector.findText(EXTRA) >= 0, 'New device omitted')
        self.assertEqual(selector.currentText(), manual)
        self.open_link.assert_not_called()


if __name__ == '__main__':
    unittest.main()
