"""Measured three-axis pose, session boundaries and health gating in Flight Data."""
import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from areion_gui.attitude_model import AttitudeModel
from areion_gui.drone_scene import _basis
from areion_gui.flight_pose import FlightPose
from areion_gui.flight_status import Health


LIVE = Health('green', 'READING', 'Fresh IMU')


class FlightPoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = FlightPose()
        self.view.resize(240,200)
        self.view.show()
        self.app.processEvents()
        self.model = AttitudeModel()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def sample(self, stamp, roll=0., pitch=0., gyro_z=0., session='kit-1'):
        imu = [0.,0.,gyro_z,0.,0.,1.,roll,pitch,roll,pitch]
        self.model.update(imu,stamp,stamp,session)
        self.view.set_attitude(self.model,LIVE)

    def test_orientation_reproduces_front_right_and_up_in_three_dimensions(self):
        roll, pitch, heading = map(math.radians, (17.,-10.,45.))
        rate = 180. * math.cos(pitch)/math.cos(roll)
        self.sample(1.,17.,-10.,rate)
        self.sample(1.25,17.,-10.,rate)
        self.assertEqual(self.view.status.text(),'LIVE')
        self.assertEqual([self.view.readouts[k].text() for k in ('roll','pitch','yaw')],
                         ['+17.0°','-10.0°','+45.0°'])
        self.assertTrue(self.view.scene._show_yaw_reference)
        matrix = _basis(self.view.scene._target)
        # Positive yaw turns the aircraft's +Y nose to +X. Positive pitch lifts the
        # nose and positive roll lowers the right (+X) motor pair.
        for row, expected in zip(matrix, (math.sin(heading)*math.cos(pitch),
                                         math.cos(heading)*math.cos(pitch), math.sin(pitch))):
            self.assertAlmostEqual(row[1], expected)
        self.assertAlmostEqual(matrix[2][0], -math.sin(roll)*math.cos(pitch))
        for _ in range(4):
            self.view.set_attitude(self.model,LIVE)
        self.assertEqual(self.view.readouts['yaw'].text(),'+45.0°')
        self.assertEqual(self.model.stamp,1.25)

    def test_waiting_fault_offline_and_expired_samples_remove_the_pose(self):
        for state, label in [('amber','WAITING'),('red','NO READ'),('gray','OFFLINE')]:
            with self.subTest(state=state):
                self.sample(1.)
                self.sample(1.1,20.,0.,37.)
                self.view.set_attitude(self.model,Health(state,label,'input health'))
                self.assertEqual(self.view.status.text(),label)
                self.assertFalse(self.view.scene.valid)
                self.assertFalse(self.view.scene.animation.isActive())
                self.assertFalse(self.view.scene._show_yaw_reference)
                self.assertTrue(all(v.text() == '—' for v in self.view.readouts.values()))
                self.model = AttitudeModel()
        self.sample(2.,10.)
        self.model.update([0.]*10,2.,2.6,'kit-1')
        self.view.set_attitude(self.model,LIVE)
        self.assertEqual(self.view.status.text(),'WAITING')
        self.assertFalse(self.view.scene.valid)

    def test_near_vertical_shows_tilt_and_holds_the_last_orientation_reference(self):
        self.sample(1.,0.,0.,100.)
        self.sample(1.3,0.,0.,100.)
        self.sample(1.45,5.,83.)
        self.assertEqual(self.view.status.text(),'TILT ONLY')
        self.assertEqual(self.view.readouts['pitch'].text(),'+83.0°')
        self.assertEqual(self.view.readouts['yaw'].text(),'—')
        self.assertFalse(self.view.scene._show_yaw_reference)
        matrix = _basis(self.view.scene._target)
        held_heading = math.degrees(math.atan2(matrix[0][1],matrix[1][1]))
        self.assertAlmostEqual(held_heading,30.)
        self.sample(1.6,5.,10.)
        self.assertEqual(self.view.readouts['yaw'].text(),'+0.0°')
        self.assertEqual(self.view.scene._pose,self.view.scene._target)
        self.assertTrue(self.view.scene._show_yaw_reference)

    def test_zero_session_change_and_packet_gap_do_not_animate_fictitious_turns(self):
        self.sample(1.,gyro_z=150.)
        self.sample(1.25,gyro_z=150.)
        self.assertTrue(self.view.scene.animation.isActive())
        self.model.reset_yaw()
        self.view.set_attitude(self.model,LIVE)
        self.assertEqual(self.view.readouts['yaw'].text(),'+0.0°')
        self.assertFalse(self.view.scene.animation.isActive())
        self.sample(1.40,10.,-15.,90.,session='kit-2')
        self.assertEqual(self.view.scene._pose,self.view.scene._target)
        self.assertEqual(self.view.readouts['yaw'].text(),'+0.0°')
        self.sample(1.55,10.,-15.,90.,session='kit-2')
        self.assertTrue(self.view.scene.animation.isActive())
        self.sample(2.30,-50.,15.,0.,session='kit-2')
        self.assertFalse(self.view.scene.animation.isActive())
        self.assertEqual(self.view.scene._pose,self.view.scene._target)

    def test_hidden_view_has_no_animation_and_each_axis_changes_mesh_pixels(self):
        self.view.hide()
        pictures = set()
        for roll, pitch, yaw_rate in ((0.,0.,0.),(30.,0.,0.),(0.,-30.,0.),(0.,0.,120.)):
            self.model = AttitudeModel()
            session = str((roll,pitch,yaw_rate))
            self.sample(1.,roll,pitch,yaw_rate,session)
            self.sample(1.3,roll,pitch,yaw_rate,session)
            self.assertFalse(self.view.scene.animation.isActive())
            image = self.view.scene.grab().toImage()
            pictures.add(bytes(image.constBits()))
        self.assertEqual(len(pictures),4)
