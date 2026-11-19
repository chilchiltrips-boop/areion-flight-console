"""Native Flight Data indicators with independently paced receiver and IMU reports."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui.window import MainWindow
from test_actions_sdk import connected_link
from zebjus_areion_link import Message
from zebjus_areion_link.schema import DRONE_GROUPS


class PeriodicPpmReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=config.name):
            self.window = MainWindow()
        self.addCleanup(self.close)
        self.window.timer.stop()
        self.window.show()
        self.window.welcome.flight_button.click()
        self.window.link, self.usb, self.ap = connected_link()
        self.start = time.monotonic()
        self.seq = 0
        self.board = self.window.flight_dashboard
        self.send(0, 110, [0])
        self.send(0, 112, [250, 250])
        self.send(0, 7, [5, .1, .15, .15, 0, 1])

    def close(self):
        self.window.link = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def send(self, elapsed, group, values):
        link = self.window.link
        self.seq += 1
        report = Message('DATA', group, DRONE_GROUPS[group]['schema'], link.fc_session,
                         self.seq, tuple(values))
        link._handle(link._paths[0], report, self.start + elapsed)

    def receive(self, elapsed, *, angle=False, armed=False):
        # Other streams, including normalized channel values, continue even if
        # this cycle's input-health report is missing. Raw 131 is never sent.
        self.send(elapsed, 120, [armed, angle, True, 8, .004, 2000, 1000, True, True, True])
        self.send(elapsed, 21, [0., 0., 0., 0., 0., 1., 0., 0., 0., 0.])
        self.send(elapsed, 130, [False, True, 0, 5, 15, True, True, False, False,
                                 1000, 1000, 1000, 1000, 1, '', 'TEST'])
        self.send(elapsed, 22, [1500, 1500, 1000, 1500, 1000 if angle else 2000, 1000, 1500, 1500])
        now = self.start + elapsed
        with patch('time.monotonic', return_value=now):
            self.window.tick()
            self.window.render_status(now)
        self.assertEqual(self.usb.sent, [])
        self.assertEqual(self.ap.sent, [])
        self.assertIsNone(self.window.session)

    def ppm(self, elapsed, ready=True, age=8):
        self.send(elapsed, 122, [0, 1 if ready else 0, ready, False, ready, 8 if ready else 0,
                                 age, self.window.link.session, False])

    def lights(self):
        return tuple(self.board.tiles[key].health.state for key in ('PPM', 'INPUT', 'MODE'))

    def test_one_missed_input_report_keeps_accepted_mode_until_next_report(self):
        # A 250 Hz FC with six telemetry slots can report group 122 every 168 ms.
        # Drop the 168 ms report and repaint before the following 336 ms report.
        self.ppm(0)
        for elapsed in (0, .124, .240, .253, .330):
            with self.subTest(elapsed=elapsed):
                self.receive(elapsed)
                self.assertEqual(self.lights(), ('green', 'green', 'green'))
                self.assertEqual(self.board.horizon.mode, 'RATE')
        self.ppm(.336)
        self.receive(.336, angle=True)
        self.assertEqual(self.lights(), ('green', 'green', 'green'))
        self.assertEqual(self.board.horizon.mode, 'ANGLE')

    def test_report_expiry_then_real_loss_and_recovery(self):
        self.ppm(0)
        self.receive(0)
        self.assertEqual(self.lights(), ('green', 'green', 'green'))
        self.receive(.65)
        self.assertEqual(self.lights(), ('amber', 'amber', 'amber'))
        self.assertEqual(self.board.horizon.mode, 'RATE')
        self.ppm(.67)
        self.receive(.67)
        self.assertEqual(self.lights(), ('green', 'green', 'green'))
        self.ppm(.69, ready=False, age=350)
        self.receive(.69)
        self.assertEqual(self.lights(), ('amber', 'amber', 'amber'))
        # The latest arm status may still be armed when a lost-input report arrives.
        self.receive(.70, armed=True)
        self.assertEqual(self.lights(), ('red', 'red', 'amber'))
        self.assertEqual(self.board.horizon.mode, 'RATE')
        self.ppm(.72)
        self.receive(.72)
        self.assertEqual(self.lights(), ('green', 'green', 'green'))
        self.assertIsNone(self.window.data.values(131))
