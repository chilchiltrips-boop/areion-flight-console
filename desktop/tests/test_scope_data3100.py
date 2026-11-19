"""Packet timing, receiver validity and spectral scaling at the desktop boundary."""
import math
import unittest

from areion_gui.model import Telemetry
from areion_gui.scope_data import (MAX_ROWS, accepted_input, frozen_telemetry,
                                    group_state, imu_spectra, time_series)


def imu(t, gyro=0., acc=0., data=None):
    data.put(21, 1, [gyro, 0., 0., 3.5 + acc, 0., 1., 0., 0., 0., 0.], now=t)


def status(data, t, valid):
    data.put(120, 1, [False, True, valid, 8, .004, 2000, 50, True, True, True], now=t)


class ScopeDataTests(unittest.TestCase):
    def setUp(self):
        self.data = Telemetry()

    def test_fft_peak_and_units_uniform_dc_and_nyquist(self):
        fs, count = 16, 128
        for i in range(count):
            t = i / fs
            imu(t, gyro=16.*math.sin(2*math.pi*2.*t), acc=.4*math.cos(math.pi*i), data=self.data)
        spectrum = imu_spectra(self.data, t, 30)
        self.assertEqual(spectrum.message, '')
        self.assertEqual((spectrum.sample_rate, spectrum.nyquist, spectrum.count, spectrum.resolution),
                         (16., 8., 128, .125))
        peak = max(spectrum.gyro['Roll'], key=lambda p: p[1])
        self.assertEqual(peak[0], 2.)
        self.assertAlmostEqual(peak[1], 16., places=9)
        freq, amplitude = spectrum.acc['X'][-1]
        self.assertEqual(freq, 8.)
        self.assertAlmostEqual(amplitude, .4, places=10)
        self.assertTrue(all(f > 0 and a == 0 for f, a in spectrum.gyro['Yaw']))
        self.assertFalse(any(a > 1e-12 for _, a in spectrum.acc['Z']))

    def test_real_fc_stagger_uses_measured_receipt_rate_and_correct_bins(self):
        for i in range(256):
            t = .15 * (i//2) + (i%2)*.05
            imu(t, gyro=5.*math.sin(2*math.pi*(5/3)*t),
                acc=.2*math.sin(2*math.pi*(5/6)*t), data=self.data)
        spectrum = imu_spectra(self.data, t, 30)
        self.assertEqual(spectrum.message, '')
        self.assertAlmostEqual(spectrum.sample_rate, 40/3, delta=.05)
        self.assertTrue(6.6 < spectrum.nyquist < 6.8)
        for trace, frequency in ((spectrum.gyro['Roll'], 5/3), (spectrum.acc['X'], 5/6)):
            self.assertAlmostEqual(max(trace,key=lambda p:p[1])[0], frequency,
                                   delta=spectrum.resolution)
        self.assertTrue(.15 < max(a for _,a in spectrum.acc['X']) < .21)
        self.assertEqual(imu_spectra(self.data, t, 5).count, 64)

    def test_slower_native_cadence_measures_reduced_bandwidth(self):
        for i in range(96):
            t = .30 * (i//2) + .10 * (i%2)
            if i % 2 == 0:
                status(self.data,t,True)
            imu(t,gyro=8*math.cos(2*math.pi*.8*t),data=self.data)
        spectrum = imu_spectra(self.data,t,30)
        self.assertFalse(spectrum.message)
        self.assertAlmostEqual(spectrum.sample_rate, 20/3, delta=.10)
        self.assertAlmostEqual(spectrum.nyquist, 10/3, delta=.05)
        self.assertAlmostEqual(max(spectrum.gyro['Roll'],key=lambda p:p[1])[0], .8,
                               delta=spectrum.resolution)

    def test_timing_gaps_bursts_and_stale_samples_have_no_spectrum(self):
        for i in range(64):
            imu(i*.075, data=self.data)
        t = 6.
        imu(t, data=self.data)
        self.assertFalse(imu_spectra(self.data,t,30).acc)
        for i in range(1,34):
            imu(t+i*.075, data=self.data)
        end = t+33*.075
        self.assertEqual(imu_spectra(self.data,end,30).count, 32)
        self.assertEqual(group_state(self.data,21,end+.51), 'Stale')
        self.assertFalse(imu_spectra(self.data,end+.51,30).gyro)
        frame = [0.] * 10
        self.data.put(21,1,frame,now=end+.55,received=False)
        self.assertFalse(imu_spectra(self.data,end+.55,30).gyro)
        for i in range(65):
            imu(t+i*.075+4, data=self.data)
        imu(t+65*.075+4.15, data=self.data)  # missing two regular frame intervals
        self.assertIn('Irregular', imu_spectra(self.data,t+65*.075+4.15,30).message)

    def test_usb_queue_burst_cannot_claim_higher_bandwidth_on_current_kit(self):
        self.data.put(125,1,['3.2.0',250,18,0,1,2,21,250,12,1024,2048,50],now=0,received=False)
        for i in range(80):
            imu(i*.005, data=self.data)
        self.assertIn('Bursty', imu_spectra(self.data,79*.005,30).message)
        # Identical host times occur when USB delivers many frames as one read.
        for i in range(40):
            imu(2.,data=self.data)
        self.assertFalse(imu_spectra(self.data,2.,30).acc)

    def test_invalid_imu_samples_and_large_gaps_are_not_joined(self):
        status(self.data,1.,True)
        for t in (1.,1.07,1.14):
            imu(t, gyro=2., data=self.data)
        status(self.data,1.18,False)
        imu(1.20,gyro=7.,data=self.data)
        self.assertEqual(group_state(self.data,21,1.2), 'Invalid')
        status(self.data,1.30,True)
        self.assertEqual(group_state(self.data,21,1.30), 'Invalid')
        imu(1.36,gyro=3.,data=self.data)
        status(self.data,2.,True)
        imu(2.01,gyro=4.,data=self.data)
        points = time_series(self.data,21,{'Roll':0},2.01,15)['Roll']
        self.assertIn((1.2, None),points)
        self.assertNotIn((1.2,7.),points)
        self.assertTrue(any(x > 1.36 and x < 2.01 and a is None for x,a in points))

    def test_accepted_channels_require_received_status_and_respect_gate_transitions(self):
        p = [0,1,True,False,True,4,15,42,False]
        raw = [1450]*8
        self.data.put(122,2,p,now=1,received=False)
        self.data.put(22,1,raw,now=1)
        self.assertEqual(group_state(self.data,22,1), 'Waiting')
        self.data.put(122,2,p,now=1)
        self.assertEqual(group_state(self.data,22,1), 'Invalid')
        self.data.put(22,1,raw,now=1.1)
        self.assertEqual(group_state(self.data,22,1.2), 'Live')
        a = [1,2,False,True,True,8,10,42,False]
        self.data.put(122,2,a,now=1.2)
        self.assertEqual(group_state(self.data,22,1.2), 'Invalid')
        self.data.put(22,1,raw,now=1.21)
        points = time_series(self.data,22,{'Roll':0,'CH6':5},1.21,5)
        self.assertIn((1.1,None), points['CH6'])
        self.assertEqual(points['CH6'][-1],(1.21,1450))
        self.assertTrue(any(1.1<x<1.21 and y is None for x,y in points['Roll']))
        a[5]=6
        self.assertIsNone(accepted_input(a))
        a[5],a[7]=8,0
        self.assertIsNone(accepted_input(a))

    def test_frozen_session_and_received_only_caps(self):
        for i in range(MAX_ROWS+14):
            imu(i*.05, gyro=i, data=self.data)
        old = self.data.scopes.rows[21][0]
        self.assertEqual((len(self.data.scopes.rows[21]),len(self.data.scopes.imu_ok)),(MAX_ROWS,MAX_ROWS))
        end = self.data.scopes.latest(21)[0]
        frozen = frozen_telemetry(self.data,end)
        self.data.put(21,1,[0]*10,now=end+.01,received=False)
        self.assertEqual(self.data.scopes.latest(21),frozen.scopes.latest(21))
        imu(end+.05,gyro=22,data=self.data)
        self.assertEqual(frozen.scopes.rows[21][0],old)
        self.assertNotEqual(self.data.scopes.latest(21),frozen.scopes.latest(21))
        self.assertEqual(frozen.age(21),0.)
        self.assertIsNotNone(frozen.values(21,.5))
        self.assertIsNone(frozen.values(21,.5,end+1))
        self.assertEqual(Telemetry().scopes.rows[21].maxlen,MAX_ROWS)

    def test_configured_input_timeout_and_status_report_expiry_are_independent(self):
        self.data.put(112,1,[70,140],now=.8,received=False)
        ppm = [0,1,True,False,True,4,50,0,False]
        pulses = [1500]*8
        self.data.put(122,2,ppm,now=1.)
        self.data.put(22,1,pulses,now=1.01)
        self.assertEqual(group_state(self.data,22,1.015),'Live')
        self.assertEqual(group_state(self.data,22,1.021),'Live')
        self.data.put(22,1,pulses,now=1.025)
        self.assertEqual(time_series(self.data,22,{'CH1':0},1.03,1)['CH1'][-1],(1.025,1500))
        expired = list(ppm)
        expired[6] = 70
        self.data.put(122,2,expired,now=1.03)
        self.assertEqual(group_state(self.data,22,1.03),'Stale')
        self.data.put(22,1,pulses,now=1.035)
        self.assertEqual(time_series(self.data,22,{'CH1':0},1.036,1)['CH1'][-1],(1.035,None))
        self.data.put(122,2,ppm,now=1.04)
        self.assertEqual(group_state(self.data,22,1.041),'Invalid')
        ap = [1,2,False,True,True,8,50,42,False]
        self.data.put(122,2,ap,now=2.)
        self.data.put(22,1,pulses,now=2.04)
        self.assertEqual(group_state(self.data,22,2.07),'Live')
        self.assertEqual(group_state(self.data,22,2.10),'Live')
        self.data.put(22,1,pulses,now=2.49)
        self.assertEqual(group_state(self.data,22,2.51),'Stale')
        self.data.put(122,2,ap,now=2.55)
        self.data.put(22,1,[2200]+pulses[1:],now=2.56)
        self.assertEqual(group_state(self.data,22,2.565),'Invalid')
        self.assertEqual(time_series(self.data,22,{'CH2':1},2.565,1)['CH2'][-1],(2.56,None))

    def test_raw_ppm_rejects_absent_channels_and_respects_frozen_timeout(self):
        self.data.put(112,1,[70,200],now=.8,received=False)
        good = [1490]*4+[0]*4+[4,True,20]
        self.data.put(131,1,good,now=1.)
        self.assertEqual(group_state(self.data,131,1.03),'Live')
        self.assertEqual(group_state(self.data,131,1.051),'Live')
        self.assertEqual(group_state(self.data,131,1.501),'Stale')
        held = frozen_telemetry(self.data,1.06)
        self.data.put(112,1,[50,200],now=1.07,received=False)
        self.assertEqual(held.scopes.input_timeouts, (70,200))
        self.assertEqual(self.data.scopes.input_timeouts, (50,200))
        self.assertEqual(group_state(held,131,1.09),'Live')
        self.assertEqual(group_state(self.data,131,1.09),'Live')
        bad = list(good)
        bad[7] = 1200
        self.data.put(131,1,bad,now=1.1)
        self.assertEqual(group_state(self.data,131,1.11),'Invalid')
        self.assertEqual(time_series(self.data,131,{'CH1':0},1.11,1)['CH1'][-1],(1.1,None))
        bad = list(good)
        bad[-1] = 205
        self.data.put(131,1,bad,now=1.12)
        self.assertEqual(group_state(self.data,131,1.12),'Stale')
        self.assertEqual(time_series(self.data,131,{'CH1':0},1.12,1)['CH1'][-1],(1.12,None))
