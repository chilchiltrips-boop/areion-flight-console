"""Exercise Flight Data health and orientation via the desktop SDK receive queue."""
import math
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.window import MainWindow
from test_actions_sdk import connected_link
from zebjus_areion_link import Message
from zebjus_areion_link.schema import DRONE_GROUPS


def imu(roll, pitch, yaw_rate=0.):
    # The accelerometer-only angles intentionally differ from the Kalman angles.
    return [0., 0., yaw_rate, .1, -.08, 1., roll + 1., pitch - 2., roll, pitch]


def status(*, sensor=True, storage=True):
    return [False, True, sensor, 8, .004, 2000, 1000, storage, True, True]


def bounds(widget, ancestor):
    return QRect(widget.mapTo(ancestor, QPoint()), widget.size())


class HealthWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=folder.name):
            self.win = MainWindow()
        self.addCleanup(self.close)
        self.win.timer.stop()
        self.win.resize(1280, 800)
        self.win.show()
        self.app.processEvents()
        QTest.mouseClick(self.win.welcome.flight_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.win.pages.currentIndex(), 0)
        self.board = self.win.flight_dashboard
        self.pose = self.board.pose
        self.connect_fixture()
        self.seq = 0

    def connect_fixture(self):
        self.win.link, self.usb, self.ap = connected_link()
        self.win.link.health_timeout = 30.

    def close(self):
        self.win.link = self.win.session = None
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def packet(self, group, values, stamp):
        self.seq += 1
        link = self.win.link
        frame = Message('DATA', group, DRONE_GROUPS[group]['schema'],
                        link.fc_session, self.seq, tuple(values))
        link._handle(link._paths[0], frame, stamp)

    def flush(self, stamp):
        self.win.tick()
        self.win.render_status(stamp)
        self.app.processEvents()

    def no_commands(self):
        self.assertEqual(self.usb.sent, [])
        self.assertEqual(self.ap.sent, [])

    def check_pose_clear(self):
        self.assertFalse(self.pose.scene.valid)
        for label in self.pose.readouts.values():
            self.assertEqual(label.text(), '—')

    def test_selected_signal_fault_waiting_and_inactive_on_open_flight_page(self):
        now = time.monotonic() - .12
        self.packet(120, status(storage=False), now)
        self.packet(21, imu(15., -8.), now + .01)
        self.packet(122, [1, 2, True, True, True, 8, 2, self.win.link.session, False], now + .02)
        self.flush(now + .05)
        self.assertTrue(self.board.health_board.isVisible())
        self.assertTrue(self.pose.scene.valid)
        for key, condition in (('STORAGE', 'red'), ('OUTPUT', 'amber'), ('INPUT', 'green'),
                               ('IMU', 'green'), ('AP', 'green'), ('PPM', 'gray'), ('USB', 'gray')):
            with self.subTest(indicator=key):
                self.assertEqual(self.board.last_health[key].state, condition)
                tile = self.board.tiles[key]
                self.assertEqual(tile.health, self.board.last_health[key])
                self.assertTrue(tile.isVisibleTo(self.board))
                self.assertTrue(tile.accessibleName())
                self.assertTrue(tile.toolTip())

        self.packet(122, [1, 0, True, False, False, 0, 500, 0, False], now + .08)
        self.flush(now + .09)
        self.assertEqual(self.board.last_health['INPUT'].state, 'amber')
        self.assertEqual(self.board.last_health['PPM'].state, 'gray')
        self.no_commands()

    def test_pose_matches_filtered_attitude_and_heading_reference_across_navigation(self):
        start = time.monotonic() - .25
        self.packet(120, status(), start)
        self.packet(21, imu(18., -12., 70.), start)
        self.flush(start)
        self.assertEqual(self.pose.readouts['roll'].text(), '+18.0°')
        self.assertEqual(self.pose.readouts['pitch'].text(), '-12.0°')
        self.win.navigate(4)
        self.assertFalse(self.pose.isVisible())
        self.packet(21, imu(18., -12., 70.), start + .12)
        self.flush(start + .12)
        self.win.navigate(0)
        expected = .12 * 70. * math.cos(math.radians(18.)) / math.cos(math.radians(-12.))
        self.assertAlmostEqual(self.board.horizon.yaw, expected, places=4)
        self.assertEqual(self.pose.readouts['yaw'].text(), f'{expected:+.1f}°')
        self.board.zero_button.click()
        self.app.processEvents()
        self.assertEqual(self.board.horizon.yaw, 0.)
        self.assertEqual(float(self.pose.readouts['yaw'].text().removesuffix('°')), 0.)

        self.packet(21, imu(-15., 82., 70.), start + .24)
        self.flush(start + .24)
        self.assertTrue(self.pose.scene.valid)
        self.assertEqual(self.pose.readouts['yaw'].text(), '—')
        self.assertEqual(self.pose.readouts['pitch'].text(), '+82.0°')
        self.assertFalse(self.board.zero_button.isEnabled())
        self.no_commands()

    def test_fault_recovery_needs_new_sensor_sample_and_expired_pose_clears(self):
        start = time.monotonic() - .22
        self.packet(120, status(), start)
        self.packet(21, imu(12., 8.), start)
        self.flush(start)
        self.assertTrue(self.pose.scene.valid)
        self.packet(120, status(sensor=False), start + .04)
        self.flush(start + .04)
        self.assertEqual(self.board.last_health['IMU'].state, 'red')
        self.check_pose_clear()
        self.packet(120, status(), start + .08)
        self.flush(start + .08)
        self.assertNotEqual(self.board.last_health['IMU'].state, 'green')
        self.check_pose_clear()
        self.packet(21, imu(-10., 1.), start + .14)
        self.flush(start + .14)
        self.assertEqual(self.pose.readouts['roll'].text(), '-10.0°')
        self.assertEqual(self.board.last_health['IMU'].state, 'green')
        self.win.render_status(start + 1.)
        self.check_pose_clear()
        self.assertNotEqual(self.board.last_health['IMU'].state, 'green')
        self.win._connection_became_stale()
        self.check_pose_clear()
        self.assertFalse(any(item.state == 'green' for item in self.board.last_health.values()))
        self.no_commands()

    def test_health_and_imu_are_visible_on_tx_and_map_and_expand_locally(self):
        for width, height in ((900,700), (1280,800)):
            self.win.resize(width, height)
            self.app.processEvents()
            self.assertEqual(self.win.size().toTuple(), (width,height))
            for show_map in (True, False):
                with self.subTest(width=width, map=show_map):
                    (self.win.map_view_button if show_map else self.win.tx_view_button).click()
                    self.app.processEvents()
                    page = self.win.pages.currentWidget()
                    self.assertTrue((self.win.gps_map if show_map else self.win.left_stick).isVisibleTo(page))
                    self.assertTrue(self.board.horizon.isVisibleTo(page))
                    for panel in (self.pose, self.board.health_board, *self.board.tiles.values()):
                        self.assertTrue(panel.isVisibleTo(page))
                        self.assertTrue(page.rect().contains(bounds(panel, page)))
                    self.assertFalse(bounds(self.pose, page).intersects(bounds(self.board.health_board, page)))
                    tile = self.board.tiles['INPUT']
                    height_before = tile.height()
                    self.assertGreaterEqual(height_before, 39)
                    self.board.details_button.click()
                    self.app.processEvents()
                    self.assertTrue(self.board.details_button.isChecked())
                    self.assertGreater(self.board.health_board.height(), 0)
                    self.assertGreaterEqual(tile.height(), height_before)
                    self.assertTrue(self.pose.isVisibleTo(page))
                    QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
                    self.board.details_button.click()
                    self.app.processEvents()
                    self.assertFalse(self.board.details_button.isChecked())
        self.no_commands()
