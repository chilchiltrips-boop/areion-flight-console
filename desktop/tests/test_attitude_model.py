"""Fresh-sample relative attitude display; no hardware or control commands."""
import math
import unittest
from areion_gui.attitude_model import AttitudeModel, wrapped_angle


def sample(roll=0.,pitch=0.,p=0.,q=0.,r=0.):
    return [p,q,r,0.,0.,1.,roll,pitch,roll,pitch]


class AttitudeModelTests(unittest.TestCase):
    def test_integrates_relative_yaw_from_distinct_samples(self):
        model=AttitudeModel();model.update(sample(r=60.),10.,10.,'kit')
        self.assertEqual(model.yaw,0.)
        model.update(sample(r=60.),10.1,10.1,'kit')
        self.assertAlmostEqual(model.yaw,6.)
        model.update(sample(r=60.),10.2,10.2,'kit')
        self.assertAlmostEqual(model.yaw,12.)
        self.assertIn('not a compass',model.reason)

    def test_duplicate_render_does_not_integrate_twice(self):
        model=AttitudeModel();model.update(sample(r=100.),10.,10.,'kit')
        model.update(sample(r=100.),10.1,10.1,'kit');yaw=model.yaw
        for now in (10.11,10.15,10.2):
            model.update(sample(r=100.),10.1,now,'kit')
            self.assertEqual(model.yaw,yaw)

    def test_trapezoidal_rate_and_banked_yaw_kinematics(self):
        model=AttitudeModel();model.update(sample(roll=60.,q=20.,r=10.),1.,1.,'kit')
        model.update(sample(roll=60.,q=40.,r=10.),1.1,1.1,'kit')
        expected=(30.*math.sin(math.radians(60.))+10.*math.cos(math.radians(60.)))*.1
        self.assertAlmostEqual(model.yaw,expected)

    def test_pitch_singularity_disables_yaw_but_not_horizon(self):
        model=AttitudeModel();model.update(sample(pitch=85.,r=50.),1.,1.,'kit')
        self.assertTrue(model.valid);self.assertEqual(model.pitch,85.);self.assertIsNone(model.yaw)
        model.update(sample(pitch=0.,r=50.),1.1,1.1,'kit')
        self.assertEqual(model.yaw,0.)

    def test_gap_never_extrapolates_missing_rotation(self):
        model=AttitudeModel();model.update(sample(r=100.),1.,1.,'kit')
        model.update(sample(r=100.),1.1,1.1,'kit')
        model.update(sample(r=100.),3.,3.,'kit')
        self.assertEqual(model.yaw,0.)

    def test_disconnect_reboot_or_kit_change_resets_reference(self):
        model=AttitudeModel();model.update(sample(r=100.),1.,1.,('kit',1))
        model.update(sample(r=100.),1.1,1.1,('kit',1));self.assertGreater(model.yaw,0.)
        model.update(sample(r=100.),1.2,1.2,('kit',2));self.assertEqual(model.yaw,0.)
        model.update(None,None,1.3,None,valid=False);self.assertFalse(model.valid);self.assertIsNone(model.yaw)
        model.update(sample(r=100.),1.4,1.4,('kit',3));self.assertEqual(model.yaw,0.)

    def test_stale_invalid_status_and_nonfinite_data_clear_display(self):
        for imu,stamp,now,valid in [(sample(),1.,1.51,True),(sample(),1.,.9,True),
                                  (sample(),1.,1.,False),(sample(r=float('nan')),1.,1.,True),
                                  ([0.]*9,1.,1.,True)]:
            model=AttitudeModel();model.update(sample(r=100.),.9,.9,'kit')
            self.assertFalse(model.update(imu,stamp,now,'kit',valid))
            self.assertIsNone(model.roll);self.assertIsNone(model.yaw)

    def test_reset_reference_and_shortest_angle_wrap(self):
        model=AttitudeModel();model.update(sample(r=1000.),1.,1.,'kit')
        model.update(sample(r=1000.),1.2,1.2,'kit')
        self.assertAlmostEqual(model.yaw,-160.)
        model.reset_yaw();self.assertEqual(model.yaw,0.)
        self.assertEqual(wrapped_angle(-358.),2.)
        model.update(sample(r=1000.),1.3,1.3,'kit')
        self.assertAlmostEqual(model.yaw,100.)


if __name__=='__main__':unittest.main()
