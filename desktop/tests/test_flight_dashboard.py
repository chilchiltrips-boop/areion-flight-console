"""Dashboard renders reported data and never invents unavailable instruments."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from areion_gui.flight_dashboard import FlightDashboard


def data():
    return {
        21:[0.,0.,10.,0.,0.,1.,5.,3.,5.,3.],
        23:[0.,0.,0.,1000.,1100.,1200.,1300.,0.,0.,0.,0.,0.],
        120:[False,True,True,8,.004,2000,1000,True,True,True],
        122:[0,1,True,False,True,8,1,42,False],
        125:['3.1.0',250,18,0,1,2,21,250,12,1024,2048,50],
        130:[False,True,0,5,15,True,True,False,False,1000,1000,1000,1000,1,'','KIT'],
        134:[0,0,1,2,3,4,5,1180,1180,1180,1180],
    }


class FlightDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=FlightDashboard();self.w.resize(430,530);self.w.show()
        self.w.horizon.animation.stop();self.app.processEvents()
    def tearDown(self):
        self.w.close();self.w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
    def test_compact_dashboard_renders_reported_instruments(self):
        now=time.monotonic();self.w.update_state(data(),now,now,'kit-A',True)
        self.assertLessEqual(self.w.minimumSizeHint().height(),540)
        self.assertLessEqual(self.w.minimumSizeHint().width(),430)
        self.assertEqual(self.w.motor_readback.values,(1000.,1100.,1200.,1300.))
        self.assertEqual(self.w.horizon.roll,5.);self.assertEqual(self.w.horizon.pitch,3.)
        self.assertTrue(self.w.zero_button.isEnabled());self.assertFalse(self.w.grab().isNull())
        self.assertNotIn('GPS',self.w.tiles);self.assertNotIn('ALTITUDE',self.w.tiles)
    def test_disconnect_clears_gauges_commands_and_all_green_tiles(self):
        now=time.monotonic();self.w.update_state(data(),now,now,'kit',True)
        self.w.update_state(data(),now,now+.1,'kit',False)
        self.assertIsNone(self.w.motor_readback.values);self.assertIsNone(self.w.horizon.roll)
        self.assertFalse(self.w.zero_button.isEnabled())
        self.assertFalse(any(x.state=='green' for x in self.w.last_health.values()))
    def test_stale_or_bad_imu_does_not_animate_or_claim_reference(self):
        now=time.monotonic();groups=data();self.w.update_state(groups,now-1,now,'kit',True)
        self.assertIsNone(self.w.horizon.roll);self.assertFalse(self.w.zero_button.isEnabled())
        self.assertNotEqual(self.w.last_health['IMU'].state,'green')
        groups[120][2]=False;self.w.update_state(groups,now,now,'kit',True)
        self.assertIsNone(self.w.horizon.pitch)
    def test_yaw_reset_changes_display_only_and_new_session_resets_reference(self):
        now=time.monotonic();groups=data();self.w.update_state(groups,now,now,'kit-A',True)
        self.w.update_state(groups,now+.1,now+.1,'kit-A',True)
        self.assertGreater(self.w.horizon.yaw,0.)
        before={g:list(v) for g,v in groups.items()}
        self.w.zero_button.click();self.assertEqual(self.w.horizon.yaw,0.)
        self.assertEqual(groups,before)
        self.w.update_state(groups,now+.2,now+.2,'kit-A',True)
        self.w.update_state(groups,now+.3,now+.3,'kit-B',True)
        self.assertEqual(self.w.horizon.yaw,0.)
    def test_instruments_consume_only_validated_group_readbacks(self):
        groups = data()
        now = time.monotonic()
        groups[120][7] = 'malformed'
        groups[23] = groups[23][:7]
        self.w.update_state(groups, now, now, 'kit', True)
        self.assertFalse(self.w.horizon.model.valid)
        self.assertIsNone(self.w.motor_readback.values)
        self.assertNotEqual(self.w.last_health['IMU'].state, 'green')
        self.assertEqual(self.w.last_health['OUTPUT'].state, 'red')

    def test_invalid_motor_values_are_blank_not_clamped_into_good_readback(self):
        groups=data();groups[23][3]=float('nan');now=time.monotonic()
        self.w.update_state(groups,now,now,'kit',True)
        self.assertIsNone(self.w.motor_readback.values)

    def test_arm_badge_requires_authoritative_fc_readback(self):
        now = time.monotonic()
        groups = data()
        display = self.w.horizon
        for armed in (True, False):
            groups[120][0] = armed
            # The IMU stream timed out, but the independent status is fresh.
            self.w.update_state(groups, now - 1., now, 'kit', True)
            self.assertIs(display.armed, armed)
            self.assertIsNone(display.tilt)
        groups[120][0] = 0  # A numeric zero cannot confirm disarm.
        self.w.update_state(groups, now, now, 'kit', True)
        self.assertIsNone(display.armed)
        groups[120][0] = True
        self.w.update_state(groups, now, now, 'kit', False)
        self.assertIsNone(display.armed)

    def test_prearm_message_reports_input_recovery_and_setup_lock(self):
        groups = data()
        now = time.monotonic()
        groups[122][1] = 0
        groups[122][2] = False
        groups[122][4] = False
        self.w.update_state(groups, now, now, 'kit', True)
        waiting = self.w.horizon.reason.lower()
        self.assertIn('ppm', waiting)
        self.assertTrue(any(word in waiting for word in ('wait', 'signal', 'lost')))
        groups[130][0] = True
        groups[130][1] = False
        self.w.update_state(groups, now, now, 'kit', True)
        self.assertIn('setup', self.w.horizon.reason.lower())
        self.assertIs(self.w.horizon.armed, False)

    def test_expanding_health_enlarges_the_board_and_restores_instruments(self):
        size = self.w.size()
        board_height = self.w.health_board.height()
        self.assertTrue(self.w.horizon.isVisibleTo(self.w))
        self.assertTrue(self.w.tiles['STORAGE'].isVisibleTo(self.w))
        self.w.details_button.click()
        self.app.processEvents()
        self.assertFalse(self.w.horizon.isVisibleTo(self.w))
        self.assertTrue(self.w.pose.isVisibleTo(self.w))
        self.assertGreater(self.w.health_board.height(), board_height)
        self.assertTrue(self.w.tiles['STORAGE'].isVisibleTo(self.w))
        self.w.details_button.click()
        self.app.processEvents()
        self.assertEqual(self.w.size(), size)
        self.assertTrue(self.w.horizon.isVisibleTo(self.w))
        self.assertTrue(self.w.tiles['STORAGE'].isVisibleTo(self.w))


if __name__=='__main__':unittest.main()
