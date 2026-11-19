"""Integration checks for the flight workspace and its read-only map view."""
from contextlib import ExitStack
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from areion_gui.model import NEUTRAL
from areion_gui.window import MainWindow
from fc_fixture import make_test_window
from setup_fixtures import complete_demo_window


def bounds_in(widget, ancestor):
    return QRect(widget.mapTo(ancestor, QPoint()), widget.size())


class FlightWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def open(self, with_kit=False):
        w = make_test_window() if with_kit else MainWindow()
        self.addCleanup(lambda: QTest.qWait(100))
        self.addCleanup(w.close)
        w.show()
        if not with_kit:
            QTest.mouseClick(w.welcome.flight_button, Qt.MouseButton.LeftButton)
        QTest.qWait(50)
        self.assertEqual(w.pages.currentIndex(), 0)
        return w

    def wait_for(self, condition):
        deadline = time.monotonic() + 2.5
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(15)
        self.assertTrue(condition())

    def test_main_panel_controls_and_instruments_fit_desktop_sizes(self):
        w = self.open()
        page = w.pages.currentWidget()
        self.assertNotIsInstance(page, QScrollArea)
        self.assertEqual(w.tx_stack.currentIndex(), 0)
        for width, height in ((900, 700), (1280, 800), (1660, 1000)):
            with self.subTest(window=(width, height)):
                w.resize(width, height)
                self.app.processEvents()
                self.assertEqual(w.size().toTuple(), (width, height))
                self.assertTrue(w.rect().contains(bounds_in(page, w)))
                targets = (
                    w.left_stick, w.right_stick, w.map_view_button, w.start_button,
                    w.arm_button, w.flight_dashboard.horizon, w.flight_dashboard.motor_readback,
                    w.flight_dashboard.pose, w.flight_dashboard.health_board,
                )
                for widget in targets:
                    self.assertTrue(widget.isVisibleTo(page))
                    self.assertTrue(page.rect().contains(bounds_in(widget, page)))
                    self.assertFalse(bounds_in(widget, page).isEmpty())
                stick_left = bounds_in(w.left_stick, page)
                stick_right = bounds_in(w.right_stick, page)
                instruments = bounds_in(w.flight_dashboard, page)
                self.assertLess(stick_left.right(), stick_right.left())
                self.assertLess(stick_right.right(), instruments.left())
                self.assertGreaterEqual(min(stick_left.width(), stick_right.width()), 105)
                self.assertGreater(instruments.width(), page.width() * .57)
                horizon = w.flight_dashboard.horizon
                self.assertGreater(horizon.width(), instruments.width() * .89)
                self.assertGreaterEqual(horizon.height(), 191)
                self.assertGreater(horizon.height(), instruments.height() * .4)
                health = w.flight_dashboard.health_board
                self.assertLess(bounds_in(horizon, page).bottom(), bounds_in(health, page).top())
                for scroll in page.findChildren(QScrollArea):
                    if scroll.isVisibleTo(page):
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                w.map_view_button.click()
                self.app.processEvents()
                self.assertTrue(w.gps_map.isVisibleTo(page))
                self.assertTrue(page.rect().contains(bounds_in(w.gps_map, page)))
                self.assertTrue(w.flight_dashboard.horizon.isVisibleTo(page))
                self.assertFalse(w.left_stick.isVisibleTo(page))
                w.tx_view_button.click()
                self.app.processEvents()

    def test_expired_arm_telemetry_on_real_flight_page(self):
        window = self.open(with_kit=True)
        window.timer.stop()
        now = time.monotonic()
        status = list(window.link.read_group(120))
        status[0] = True
        self.assertTrue(window.data.put(120, 1, status, now))
        window.render_status(now)
        display = window.flight_dashboard.horizon
        self.assertIs(display.armed, True)
        later = now + .7
        self.assertTrue(window.data.put(21, 1, window.link.read_group(21), later))
        window.render_status(later)
        self.assertIsNone(display.armed)

    def test_return_to_flight_data_reflects_latest_arm_state_immediately(self):
        window = self.open(with_kit=True)
        window.timer.stop()
        display = window.flight_dashboard.horizon
        self.assertIs(display.armed, False)
        window.navigate(1)
        status = list(window.link.read_group(120))
        status[0] = True
        self.assertTrue(window.data.put(120, 1, status))
        window.navigate(0)
        self.assertIs(display.armed, True)
        window._connection_became_stale()
        self.assertIsNone(display.armed)
        self.assertIsNone(display.tilt)

    def test_gyro_reference_tracks_samples_while_flight_data_is_hidden(self):
        window = self.open(with_kit=True)
        window.timer.stop()
        window.navigate(1)
        display = window.flight_dashboard.horizon
        self.assertFalse(display.isVisible())
        read_group = window.link.read_group

        def read(group, *args, **kwargs):
            if group == 21:
                return [0., 0., 40., 0., 0., 1., 0., 0., 0., 0.]
            return read_group(group, *args, **kwargs)

        with patch.object(window.link, "read_group", side_effect=read):
            window.link.last_emit = 0.
            window.tick()
            display.reset_yaw()
            self.assertEqual(display.yaw, 0.)
            QTest.qWait(80)
            window.tick()
            self.assertGreater(display.yaw, 1.)
            last_yaw = display.yaw
            window.navigate(0)
            self.assertEqual(display.yaw, last_yaw)

    def test_map_is_read_only_despite_existing_digital_source_and_completed_setup(self):
        w = self.open(with_kit=True)
        complete_demo_window(w, 2)
        w.render_status(time.monotonic())
        self.assertTrue(w.start_button.isEnabled())
        w.keyboard.setChecked(True)
        with ExitStack() as guards:
            pending = guards.enter_context(patch.object(w, "_linked"))
            writes = [guards.enter_context(patch.object(w.link, name))
                      for name in ("action", "set_group", "save_group", "send_control", "arm", "disarm")]
            w.map_view_button.setFocus()
            QTest.keyClick(w.map_view_button, Qt.Key.Key_Space)
            w.render_status(time.monotonic())
            self.assertEqual(w.tx_stack.currentIndex(), 1)
            self.assertFalse(w.start_button.isEnabled())
            self.assertFalse(w.arm_button.isEnabled())
            w.setFocus()
            QTest.keyPress(w, Qt.Key.Key_W)
            QTest.qWait(65)
            QTest.keyRelease(w, Qt.Key.Key_W)
            QTest.keyClick(w, Qt.Key.Key_8)
            w._stick_input(False, 1., -1., True)
            w._aux(7, 2000)
            w.start_stream()
            w.arm()
            QTest.qWait(85)
            self.assertFalse(w.session.running)
            self.assertFalse(w.controls.pressed)
            self.assertEqual(w.controls.values, NEUTRAL)
            self.assertEqual(w.link.source, 2)
            w.tx_view_button.click()
            w.render_status(time.monotonic())
            self.assertTrue(w.start_button.isEnabled())
            pending.assert_not_called()
            for method in writes:
                method.assert_not_called()

    def test_pending_running_and_stopping_sender_owns_transmitter_view(self):
        w = self.open(with_kit=True)
        complete_demo_window(w, 1)
        w.start_stream()
        self.assertTrue(w.command_busy)
        w._set_flight_view(1)
        self.assertEqual(w.tx_stack.currentIndex(), 0)
        self.wait_for(lambda: w.session.running and w.session.ready)
        self.assertFalse(w.map_view_button.isEnabled())
        QTest.mouseClick(w.map_view_button, Qt.MouseButton.LeftButton)
        w._set_flight_view(1)
        self.assertEqual(w.tx_stack.currentIndex(), 0)
        self.assertTrue(w.session.running)
        w.stop("End workspace test")
        w._set_flight_view(1)
        self.assertEqual(w.tx_stack.currentIndex(), 0)
        self.wait_for(lambda: not w.stopping and not w.session.running and w.map_view_button.isEnabled())
        w.map_view_button.click()
        self.assertEqual(w.tx_stack.currentIndex(), 1)
        self.assertFalse(w.link.armed)

    def test_ppm_on_map_updates_received_channels_without_echo(self):
        w = self.open(with_kit=True)
        complete_demo_window(w, 0)
        w.render_status(time.monotonic())
        with patch.object(w.link, "send_control") as send:
            w.map_view_button.click()
            values = [1670, 1330, 1000, 1500, 1000, 1000, 2000, 1000]
            w.link.demo_set_receiver(values)
            self.wait_for(lambda: w.channel_labels[0].text() == "1670")
            self.assertEqual(w.tx_stack.currentIndex(), 1)
            self.assertEqual(w.controls.values, NEUTRAL)
            w.tx_view_button.click()
            self.assertAlmostEqual(w.right_stick.x, .34)
            self.assertFalse(w.start_button.isEnabled())
            self.assertEqual(w.link.source, 0)
            send.assert_not_called()
