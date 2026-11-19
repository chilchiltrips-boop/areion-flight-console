"""Check the displayed yaw against timed packets, including a burst in one GUI poll."""
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui.model import Telemetry
from areion_gui.window import MainWindow
from test_actions_sdk import connected_link
from zebjus_areion_link import Message


STATUS = [False, True, True, 8, .004, 2000, 5000, True, False, False]


def sample(rate):
    return [0., 0., rate, 0., 0., 1., 0., 0., 0., 0.]


class FlightPosePacketTests(unittest.TestCase):
    def test_yaw_uses_middle_sample_even_when_all_arrive_before_one_gui_tick(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.timer.stop()
        link, _, _ = connected_link()
        window.link = link
        try:
            base = time.monotonic() - .30
            packets = [(0., 120, STATUS), (.03, 21, sample(0.)),
                       (.13, 21, sample(120.)), (.23, 21, sample(0.))]
            for seq, (offset, group, values) in enumerate(packets, start=1):
                frame = Message('DATA', group, 1, link.fc_session, seq, tuple(values))
                link._handle(link._paths[0], frame, base + offset)
            window.tick()
            # Integrating the triangular rate pulse gives 12°, even on the Welcome page.
            model = window.flight_dashboard.horizon.model
            self.assertAlmostEqual(model.yaw, 12., places=5)
            window.navigate(0)
            window._refresh_flight_instruments(time.monotonic(), True)
            self.assertAlmostEqual(model.yaw, 12., places=5)
        finally:
            window.link = None
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_recovery_requires_a_sample_after_a_healthy_status(self):
        data = Telemetry()
        data.put(120, 1, STATUS, 8.)
        data.put(21, 1, sample(3.), 8.01)
        self.assertIsNotNone(data.flight_imu(8.02))
        bad = STATUS.copy()
        bad[2] = False
        data.put(120, 1, bad, 8.03)
        data.put(21, 1, sample(2.), 8.04)
        data.put(120, 1, STATUS, 8.05, received=False)
        self.assertIsNone(data.flight_imu(8.06))
        self.assertIsNotNone(data.values(21))  # Preserve raw telemetry for diagnostics.
        data.put(21, 1, sample(2.), 8.07)
        self.assertEqual(data.flight_imu(8.08), sample(2.))
        self.assertIsNone(data.flight_imu(8.6))

    def test_startup_fault_suppresses_pose_until_new_healthy_sample(self):
        data = Telemetry()
        setup = [True, False, 0, 0, 0, False, False, False, False,
                 1000, 1000, 1000, 1000, 0, 'IMU_STARTUP_FAILED', 'TEST']
        data.put(120, 1, STATUS, 2.)
        self.assertTrue(data.put(130, 1, setup, 2.01))
        data.put(21, 1, sample(0.), 2.02)
        self.assertIsNone(data.flight_imu(2.03))
        setup[14] = ''
        data.put(130, 1, setup, 2.04)
        self.assertIsNone(data.flight_imu(2.05))
        data.put(21, 1, sample(0.), 2.06)
        self.assertEqual(data.flight_imu(2.07), sample(0.))
