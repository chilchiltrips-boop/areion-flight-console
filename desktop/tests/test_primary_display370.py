"""Visual instrument regressions using deterministic IMU and FC telemetry."""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from areion_gui.primary_display import PrimaryFlightDisplay, tilt_degrees


class PrimaryFlightDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.display = PrimaryFlightDisplay()
        self.display.resize(480, 320)
        self.display.show()
        self.app.processEvents()
        self.display.animation.stop()

    def tearDown(self):
        self.display.close()
        self.display.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_tilt_is_the_total_inclination_from_level(self):
        for roll, pitch, expected in (
                (0., 0., 0.), (-30., 0., 30.), (0., 40., 40.),
                (45., 45., 60.), (-45., -45., 60.),
                (90., 10., 90.), (120., 0., 120.), (180., 0., 180.)):
            with self.subTest(roll=roll, pitch=pitch):
                self.assertAlmostEqual(tilt_degrees(roll, pitch), expected)
                self.display.set_angles(roll, pitch)
                self.assertAlmostEqual(self.display.tilt, expected)
        self.display.set_angles(None, None)
        self.assertIsNone(self.display.tilt)

    def test_center_field_animates_a_new_attitude(self):
        display = self.display
        display.set_angles(0., 0.)
        display.set_angles(34., 12.)
        # Crop out badges, the yaw tape and numerical values. The central
        # instrument itself must change between successive animation frames.
        def field_image():
            return display.grab().toImage().copy(112, 112, 256, 105)
        first = field_image()
        display._frame_at = time.monotonic() - .05
        display._animate()
        self.assertGreater(display.display_roll, 0.)
        self.assertLess(display.display_roll, 34.)
        self.assertGreater(display.display_pitch, 0.)
        self.assertNotEqual(first, field_image())

    def test_bank_crosses_the_180_degree_seam_on_the_short_arc(self):
        display = self.display
        display.set_angles(177., 6.)
        display.set_angles(-176., 6.)
        display._frame_at = time.monotonic() - .05
        display._animate()
        self.assertGreater(abs(display.display_roll), 175.)
        self.assertGreater(display.tilt, 170.)

    def test_stale_attitude_erases_previous_angles_even_if_fc_stays_armed(self):
        display = self.display
        display.set_flight_state(True, "ANGLE", "")
        display.set_angles(20., -3.)
        active = display.grab().toImage()
        display.model.stamp = time.monotonic() - 1.
        display._animate()
        self.assertIs(display.armed, True)
        self.assertIsNone(display.tilt)
        self.assertIsNone(display.display_roll)
        self.assertIsNone(display.display_yaw)
        self.assertNotEqual(active, display.grab().toImage())

    def test_near_vertical_pitch_keeps_tilt_when_relative_yaw_is_unavailable(self):
        now = time.monotonic()
        imu = [0., 0., 10., 0., 0., 1., 0., 89., 0., 89.]
        self.display.update_telemetry(imu, now, now, 'kit')
        self.assertEqual(self.display.pitch, 89.)
        self.assertAlmostEqual(self.display.tilt, 89.)
        self.assertIsNone(self.display.display_yaw)
        self.assertFalse(self.display.grab().isNull())
