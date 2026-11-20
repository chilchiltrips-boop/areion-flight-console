"""Six actual one-gravity poses and the boundaries of a live calibration."""
import unittest

from areion_gui.sensor_calibration import AutomaticSixFaceCalibration, POSES


class AutomaticFacesTests(unittest.TestCase):
    def setUp(self):
        self.time=0.
        self.baseline=[-.11,.02,.12]
        self.bank=AutomaticSixFaceCalibration(self.baseline,started=0.)

    def feed(self,acc,gyro=(.04,.06,-.02),count=1):
        for _ in range(count):
            self.time+=.1
            row=[*gyro,*acc,0.,0.,0.,0.]
            result=self.bank.add(row,self.time,self.time,True)
        return result

    def test_any_order_reports_firmware_correctable_residual_and_offsets(self):
        bias=[.06,-.03,.05]
        for face in reversed(POSES):
            acc=[a+b+c for a,b,c in zip(face['target'],self.baseline,bias)]
            state=self.feed(acc,count=34)
        self.assertEqual(state,'complete',self.bank.error)
        self.assertEqual(len(self.bank.faces),6)
        self.assertLess(self.bank.result['max_additive_residual_g'],1e-6)
        for got,want in zip(self.bank.result['candidate_offsets'],bias):
            self.assertAlmostEqual(got,-want)

    def test_motion_and_duplicate_poses_preserve_progress(self):
        self.feed((0,0,1),count=34)
        self.feed((0,0,1),count=34)
        self.assertEqual(list(self.bank.faces),['level'])
        self.feed((0,1,0),count=12)
        self.assertEqual(self.feed((0,1,0),(0.,12.,0.)),'waiting')
        self.assertIsNone(self.bank.current)
        self.feed((0,1,0),count=34)
        self.assertEqual(set(self.bank.faces),{'level','right_side'})

    def test_duplicate_reads_and_data_loss(self):
        self.feed((0,0,1))
        for _ in range(80):
            self.bank.add([0.,0.,0.,0.,0.,1.,0.,0.,0.,0.],self.time,self.time,True)
        self.assertEqual(len(self.bank.current.samples),1)
        self.time+=.7
        self.assertEqual(self.feed((0,0,1)),'error')
        self.assertFalse(self.bank.running)
        self.assertIsNone(self.bank.result)

    def test_sensor_range_and_gyro_drift_block_verification(self):
        for p in POSES:
            self.feed([v*1.14 for v in p['target']],count=34)
        self.assertIn('residual',self.bank.error)
        self.assertIsNone(self.bank.result)
        self.bank=AutomaticSixFaceCalibration([0,0,0],started=self.time)
        self.feed((0,0,1),(1.5,.2,0),count=34)
        self.assertIn('Gyro drift',self.bank.error)
        self.assertIsNone(self.bank.result)
