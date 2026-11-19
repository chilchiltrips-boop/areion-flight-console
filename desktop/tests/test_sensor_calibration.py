"""Synthetic reference data verifies six-face math and failure boundaries."""
import math
import unittest

from areion_gui.sensor_calibration import (POSES,POSE_BY_KEY,SixFaceCalibration,
    GyroCalibration,corrected_acc_preview,corrected_gyro_preview)


def feed_face(cal,key,started,bias=(.12,-.04,.08),gain=(1.04,.97,1.02),gyro=(.1,-.1,.2),noise=0.):
    cal.start_pose(key,started)
    target=POSE_BY_KEY[key]['target']
    status=None
    for i in range(36):
        stamp=started+(i+1)*.1
        raw=[target[j]/gain[j]+bias[j]+noise*(-1)**i for j in range(3)]
        values=list(gyro)+[raw[j]+cal.baseline[j] for j in range(3)]+[0.]*4
        status=cal.add(values,stamp,stamp,True)
        if cal.current is None:break
    return status


class SixFaceTests(unittest.TestCase):
    def calibrate(self,demo=False):
        c=SixFaceCalibration([-.10,.03,.12],demo)
        for i,p in enumerate(POSES):status=feed_face(c,p['key'],i*5.)
        self.assertEqual(status,'complete',c.error)
        return c

    def test_opposing_faces_recover_raw_bias_and_scale(self):
        c=self.calibrate();r=c.result
        for actual,expected in zip(r['candidate_offsets'],(-.12,.04,-.08)):self.assertAlmostEqual(actual,expected)
        for actual,expected in zip(r['required_scale'],(1.04,.97,1.02)):self.assertAlmostEqual(actual,expected)
        self.assertEqual(len(r['faces']),6);self.assertGreaterEqual(r['samples'],120)
        self.assertEqual(r['method'],'six_face');self.assertEqual(r['kind'],'live_candidate')
        self.assertFalse(r['applied_to_fc']);self.assertFalse(r['full_calibration_applied_to_fc'])
        self.assertEqual(r['fc_supported_correction'],'additive_offsets_only')

    def test_results_retain_demo_provenance(self):
        self.assertEqual(self.calibrate(True).result['kind'],'demo_candidate')

    def test_nonzero_existing_offsets_are_removed_exactly_once(self):
        c=SixFaceCalibration([.2,-.15,.1])
        for i,p in enumerate(POSES):feed_face(c,p['key'],i*5,bias=(.02,.03,-.04),gain=(1.,1.,1.))
        self.assertIsNotNone(c.result,c.error)
        for got,want in zip(c.result['candidate_offsets'],(-.02,-.03,.04)):self.assertAlmostEqual(got,want)

    def test_no_candidate_before_all_six_unique_faces(self):
        c=SixFaceCalibration([0.,0.,0.]);feed_face(c,'level',0)
        self.assertIsNone(c.result);self.assertEqual(set(c.faces),{'level'})
        with self.assertRaises(ValueError):c.start_pose('level',5)
        with self.assertRaises(ValueError):c.start_pose('nonexistent',5)
        c.start_pose('nose_up',5)
        with self.assertRaises(ValueError):c.start_pose('nose_down',5)

    def test_wrong_pose_and_cross_axis_fail_without_recording(self):
        for acc in ([0.,0.,1.],[-.8,.5,0.]):
            c=SixFaceCalibration([0.,0.,0.]);c.start_pose('nose_up',0)
            status=c.add([0.,0.,0.]+acc+[0.]*4,.1,.1,True)
            self.assertEqual(status,'error');self.assertIn('orientation',c.error);self.assertFalse(c.faces)

    def test_duplicate_and_out_of_order_samples_do_not_count(self):
        c=SixFaceCalibration([0.,0.,0.]);c.start_pose('level',0)
        v=[0.,0.,0.,0.,0.,1.]+[0.]*4
        for _ in range(30):c.add(v,.1,.1,True)
        c.add(v,.09,.1,True)
        self.assertEqual(len(c.current.samples),1);self.assertEqual(c.current.progress,0.)

    def test_stale_future_unsafe_and_nonfinite_samples_abort(self):
        v=[0.,0.,0.,0.,0.,1.]+[0.]*4
        cases=[(v,.1,.7,True),(v,.2,.1,True),(v,.1,.1,False),
               ([math.nan]+v[1:],.1,.1,True),(v,math.nan,.1,True)]
        for values,stamp,now,safe in cases:
            c=SixFaceCalibration([0.,0.,0.]);c.start_pose('level',0)
            self.assertEqual(c.add(values,stamp,now,safe),'error')
            self.assertIsNone(c.result);self.assertFalse(c.faces)

    def test_too_few_samples_time_out_and_cancellation_preserves_completed_face(self):
        c=SixFaceCalibration([0.,0.,0.]);feed_face(c,'level',0)
        c.start_pose('nose_up',5);c.add([0.,0.,0.,-1.,0.,0.]+[0.]*4,17.1,17.1,True)
        self.assertIn('timed out',c.error);self.assertEqual(set(c.faces),{'level'})
        c.start_pose('nose_up',20);c.cancel_capture('operator cancelled')
        self.assertIsNone(c.current);self.assertEqual(set(c.faces),{'level'});self.assertIn('operator',c.error)
        c.reset();self.assertFalse(c.faces);self.assertFalse(c.error);self.assertIsNone(c.result)

    def test_capture_duration_uses_actual_sample_span(self):
        c=SixFaceCalibration([0.,0.,0.]);c.start_pose('level',0)
        for i in range(21):c.add([0.,0.,0.,0.,0.,1.]+[0.]*4,3+i*.01,3+i*.01,True)
        self.assertIsNotNone(c.current);self.assertIsNone(c.result);self.assertFalse(c.faces)

    def test_vibration_rejected(self):
        c=SixFaceCalibration([0.,0.,0.]);status=feed_face(c,'level',0,bias=(0.,0.,0.),gain=(1.,1.,1.),noise=.04)
        self.assertEqual(status,'error');self.assertIn('stationary',c.error)

    def test_implausible_scale_rejected_after_distinct_faces(self):
        c=SixFaceCalibration([0.,0.,0.])
        for i,p in enumerate(POSES):status=feed_face(c,p['key'],i*5,bias=(0.,0.,0.),gain=(1.3,1.,1.))
        self.assertEqual(status,'error');self.assertIsNone(c.result);self.assertIn('scale',c.error)

    def test_final_offset_out_of_fc_range_rejected(self):
        c=SixFaceCalibration([-.5,0.,0.])
        for i,p in enumerate(POSES):status=feed_face(c,p['key'],i*5,bias=(.51,0.,0.),gain=(1.,1.,1.))
        self.assertEqual(status,'error');self.assertIsNone(c.result);self.assertIn('AccelOffsetX',c.error)

    def test_inconsistent_opposite_pose_alignment_rejected(self):
        c=SixFaceCalibration([0.,0.,0.])
        for i,p in enumerate(POSES):
            if p['key']=='level':
                c.start_pose('level',i*5)
                for n in range(36):
                    t=i*5+(n+1)*.1
                    status=c.add([0.,0.,0.,.3,0.,1.]+[0.]*4,t,t,True)
                    if c.current is None:break
            else:status=feed_face(c,p['key'],i*5,bias=(0.,0.,0.),gain=(1.,1.,1.))
        self.assertEqual(status,'error');self.assertIsNone(c.result);self.assertIn('inconsistent',c.error)


class PreviewAndGyroTests(unittest.TestCase):
    def test_acc_preview_uses_additive_correction_without_mutation(self):
        values=[0.,0.,0.,.15,-.2,1.2]+[0.]*4;original=values[:]
        result=corrected_acc_preview(values,[-.1,.03,.12],[-.25,.23,-.08])
        for actual,expected in zip(result,[0.,0.,1.]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(values,original)
        self.assertEqual(corrected_acc_preview([1.,2.,3.],[0,0,0],[0,0,0]),[1.,2.,3.])
        with self.assertRaises(ValueError):corrected_acc_preview([math.nan,0,1],[0,0,0],[0,0,0])

    def test_gyro_residual_is_only_a_python_correction(self):
        c=GyroCalibration(0,demo=False)
        for i in range(40):
            t=.1+i*.1;c.add([.3,-.2,.1,0.,0.,1.]+[0.]*4,t,t,True)
        r=c.result;self.assertIsNotNone(r,c.error)
        self.assertEqual(r['residual_bias_dps'],[.3,-.2,.1])
        self.assertEqual(r['preview_correction_dps'],[-.3,.2,-.1])
        self.assertEqual(r['kind'],'live_gyro_candidate');self.assertFalse(r['applied_to_fc'])
        self.assertEqual(r['correction_scope'],'python_preview_only')
        for val in corrected_gyro_preview([.3,-.2,.1],r):self.assertAlmostEqual(val,0.)

    def test_gyro_drift_above_one_dps_is_not_marked_good(self):
        c=GyroCalibration(0,True)
        for i in range(40):
            t=.1+i*.1;c.add([1.2,0.,0.,0.,0.,1.]+[0.]*4,t,t,True)
        self.assertEqual(c.result['kind'],'demo_gyro_candidate')
        self.assertFalse(c.result['residual_within_1dps'])
        self.assertFalse(c.result['applied_to_fc'])

    def test_moving_gyro_cannot_calibrate(self):
        c=GyroCalibration(0)
        c.add([6.,0.,0.,0.,0.,1.]+[0.]*4,.1,.1,True)
        self.assertTrue(c.error);self.assertIsNone(c.result)
        with self.assertRaises(ValueError):corrected_gyro_preview([0.,0.,0.],{})


if __name__=='__main__':unittest.main()
