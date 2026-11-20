"""Actual calibration poses, capture progress and reconnect status in the new view."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from areion_gui.calibration_panel import CalibrationPanel
from areion_gui.setup_config import default_configuration


class ImuVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 321.
        timer = patch('areion_gui.calibration_panel.time.monotonic', side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.panel = CalibrationPanel(default_configuration()['imu'])
        self.addCleanup(self.panel.deleteLater)

    def sample(self, acc=(0., 0., 1.), gyro=(0., 0., 0.), angle=(0., 0.), stamp=None, safe=True):
        values = {
            6: [0., 0., 0.], 120: [False, True, True, 8, .004, 2000, 0, True, True, False],
            21: [*gyro, *acc, 0., 0., *angle],
        }
        self.panel.update_telemetry(values, self.now if stamp is None else stamp, self.now, 1, False, safe)

    def test_guide_is_independent_of_measured_3d_pose_including_inverted(self):
        self.assertEqual(self.panel.pose_title.text(), 'Flat / level')
        self.assertIsNone(self.panel.live_angles)
        self.sample(acc=(0., 0., -1.))
        self.assertAlmostEqual(abs(self.panel.live_angles[0]), 180.)
        self.assertIsNone(self.panel.live_angles[2])
        self.sample(acc=(-1., 0., 0.))
        self.assertAlmostEqual(self.panel.live_angles[1], 90.)
        self.assertIn('R —', self.panel.live_status.text())
        self.assertEqual(self.panel.pose_key, 'level')

    def test_live_gyro_uses_filtered_roll_pitch_and_relative_yaw(self):
        self.panel.tabs.setCurrentIndex(1)
        self.sample(gyro=(0., 0., 15.), angle=(12., 3.))
        self.now += .1
        self.sample(gyro=(0., 0., 15.), angle=(12., 3.))
        self.assertEqual(self.panel.live_angles[:2], (12., 3.))
        self.assertGreater(self.panel.live_angles[2], 0.)
        self.panel.zero_yaw.click()
        self.assertEqual(self.panel.live_angles[2], 0.)
        self.now += 1.
        self.panel._expire_readings()
        self.assertIsNone(self.panel.live_angles)
        self.assertEqual(self.panel.live_status.text(), 'Waiting for live IMU')

    def test_detected_pose_uses_fresh_samples_and_prompts_automatically(self):
        self.sample()
        self.panel.capture_button.click()
        self.now += .1
        self.sample(acc=(1., 0., 0.))
        self.assertEqual(self.panel.pose_title.text(), 'Nose down')
        self.assertEqual(self.panel.pose_tiles['nose_down'].property('mark'), 'detected')
        self.now += .1
        self.sample(gyro=(30.,0.,0.))
        self.assertTrue(self.panel.active)
        self.assertFalse(self.panel.bank.faces)
        self.now += .1
        self.sample()
        stamp = self.now
        self.now += .2
        self.sample(stamp=stamp)
        self.assertEqual(self.panel.acc_progress.value(), 0)
        self.assertIn('1 sample', self.panel.acc_status.text())
        for _ in range(32):
            self.now += .1
            self.sample()
        self.assertEqual(self.panel.acc_status.state, 'done')
        self.assertEqual(self.panel.face_count.text(), '1 / 6')
        self.assertEqual(self.panel.pose_key, 'nose_up')
        self.assertEqual(self.panel.pose_tiles['level'].property('mark'), 'done')
        self.assertTrue(self.panel.active)
