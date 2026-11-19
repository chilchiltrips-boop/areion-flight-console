"""Stable calibration button state during telemetry and read-only monitoring."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from areion_gui.calibration_page import CalibrationPage
from fc_fixture import DemoLink
from zebjus_areion_link.schema import DRONE_GROUPS


class EnableEvents(QObject):
    def __init__(self, button):
        super().__init__(button)
        self.states = []
        button.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.states.append(watched.isEnabled())
        return False


class CalibrationButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.page = CalibrationPage(Path(self.temp.name) / 'setup.json', 'imu')
        self.page.timer.stop()
        self.page.resize(1050, 800)
        self.page.show()
        self.page.on_enter()
        self.page.set_connection_state(connected=True, disarmed=True, demo=True, has_link=True)
        self.link = DemoLink()
        self.actions = []
        self.page.action_requested.connect(lambda action, payload: self.actions.append((action, payload)))
        self.push()
        self.events = EnableEvents(self.page.sensor_panel.read_button)
        self.capture_events = EnableEvents(self.page.sensor_panel.capture_button)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def push(self):
        now = time.monotonic()
        groups = (2, 3, 4, 6, 7, 21, 112, 120, 130, 132, 134)
        values = {g: self.link.read_group(g, DRONE_GROUPS[g]['schema']) for g in groups}
        self.page.receive_telemetry(values, now, now, ('demo', 1))
        self.page._tick()

    def test_read_button_does_not_toggle_during_read_only_telemetry(self):
        self.assertTrue(self.page.sensor_panel.read_button.isEnabled())
        for _ in range(30):
            self.push()
        self.assertEqual(self.events.states, [])
        self.assertEqual(self.actions, [])

    def test_monitoring_does_not_briefly_enable_capture(self):
        self.page.propeller_check.setChecked(True)
        self.page.sensor_panel.stationary.setChecked(True)
        self.capture_events.states.clear()
        for _ in range(30):
            self.push()
        self.assertFalse(self.page.sensor_panel.capture_button.isEnabled())
        self.assertEqual(self.capture_events.states, [])
        self.assertFalse(self.page.session_requested)
        self.assertEqual(self.actions, [])

    def test_held_read_click_survives_refresh_without_scroll_jump(self):
        self.page.sensor_panel.tabs.setCurrentIndex(2)
        button = self.page.sensor_panel.read_button
        scroll = self.page.scrolls[3]
        scroll.ensureWidgetVisible(button)
        self.app.processEvents()
        before = scroll.verticalScrollBar().value()
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        for _ in range(10):
            self.push()
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.actions, [('read', {'groups': [6]})])
        self.assertEqual(scroll.verticalScrollBar().value(), before)
        self.assertFalse(button.isEnabled())
        self.events.states.clear()
        for _ in range(10):
            self.push()
        self.assertEqual(self.events.states, [])
        self.assertFalse(button.isEnabled())

    def test_connection_and_operation_guards_still_disable_reads(self):
        for attr in ('external_busy', 'operation_busy'):
            setattr(self.page, attr, True)
            self.page._update_navigation()
            self.assertFalse(self.page.sensor_panel.read_button.isEnabled())
            self.push()
            self.assertFalse(self.page.sensor_panel.read_button.isEnabled())
            setattr(self.page, attr, False)
            self.page._update_navigation()
            self.assertTrue(self.page.sensor_panel.read_button.isEnabled())
        self.page.set_connection_state(connected=False, disarmed=False)
        self.assertFalse(self.page.sensor_panel.read_button.isEnabled())

    def test_locked_read_requires_disarmed_state_without_imu_age_gate(self):
        button = self.page.sensor_panel.read_button
        self.assertTrue(self.page.status[0])
        self.page.set_connection_state(connected=True, disarmed=False)
        self.assertFalse(button.isEnabled())
        button.click()
        self.assertEqual(self.actions, [])
        self.page.set_connection_state(connected=True, disarmed=True)
        self.page.imu_stamp = time.monotonic() - 10
        self.page._update_navigation()
        self.assertTrue(button.isEnabled())
        button.click()
        self.assertEqual(self.actions, [('read', {'groups': [6]})])

    def test_unlocked_monitoring_read_remains_allowed_while_armed(self):
        self.page.live[130][0] = False
        self.page.live[130][1] = True
        self.page.live[120][0] = True
        self.page.set_connection_state(connected=True, disarmed=False)
        button = self.page.sensor_panel.read_button
        self.assertTrue(button.isEnabled())
        button.click()
        self.assertEqual(self.actions, [('read', {'groups': [6]})])
        self.assertFalse(self.page.session_requested)
