import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from areion_gui.widgets import Horizon


def sample(roll=0.,pitch=0.,yaw_rate=0.):
    return [0.,0.,yaw_rate,0.,0.,1.,roll,pitch,roll,pitch]


class AttitudeWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=Horizon();self.w.resize(470,315);self.w.show();self.app.processEvents()

    def tearDown(self):
        self.w.close();self.w.deleteLater();self.app.processEvents()

    def test_roll_pitch_and_yaw_change_instrument_render(self):
        now=time.monotonic();self.w.update_telemetry(sample(yaw_rate=50),now,now,'kit')
        first=self.w.grab().toImage();QTest.qWait(100)
        now=time.monotonic();self.w.update_telemetry(sample(roll=30,pitch=12,yaw_rate=50),now,now,'kit')
        self.assertAlmostEqual(self.w.roll,30.);self.assertAlmostEqual(self.w.pitch,12.)
        self.assertGreater(self.w.yaw,0.);self.assertLess(self.w.display_roll,30.)
        QTest.qWait(100)
        self.assertGreater(self.w.display_roll,10.);self.assertLess(self.w.display_roll,30.)
        self.assertNotEqual(first,self.w.grab().toImage())

    def test_stale_data_stops_animation_and_clears_live_values(self):
        now=time.monotonic();self.w.update_telemetry(sample(roll=20),now,now,'kit')
        self.w.model.stamp=now-.6;self.w._animate()
        self.assertIsNone(self.w.roll);self.assertIsNone(self.w.display_roll);self.assertIsNone(self.w.yaw)
        self.assertFalse(self.w.grab().isNull())

    def test_new_session_snaps_to_new_reference_without_fake_turn(self):
        now=time.monotonic();self.w.update_telemetry(sample(roll=45),now,now,'kit1')
        self.w.update_telemetry(sample(roll=-25),now,now,'kit2')
        self.assertEqual(self.w.display_roll,-25.);self.assertEqual(self.w.display_yaw,0.)

    def test_explicit_reset_and_legacy_angles_api(self):
        now=time.monotonic();self.w.update_telemetry(sample(yaw_rate=50),now-.1,now-.1,'kit')
        self.w.update_telemetry(sample(yaw_rate=50),now,now,'kit');self.assertGreater(self.w.yaw,0.)
        self.w.reset_yaw();self.assertEqual(self.w.yaw,0.);self.assertEqual(self.w.display_yaw,0.)
        self.w.set_angles(5.,-10.);self.assertEqual((self.w.roll,self.w.pitch),(5.,-10.));self.assertIsNone(self.w.yaw)
        self.w.set_angles(None,None);self.assertIsNone(self.w.roll)

    def test_minimum_size_paints_valid_and_vertical_pitch_states(self):
        self.w.resize(230,210)
        for pitch in (0.,85.,-85.):
            now=time.monotonic();self.w.update_telemetry(sample(pitch=pitch),now,now,('kit',pitch))
            self.assertFalse(self.w.grab().isNull())


if __name__=='__main__':unittest.main()
