"""Receiver endpoints and normalized previews use raw, fresh locked telemetry."""
import math
import json
import unittest
from areion_gui.receiver_calibration import ReceiverCapture, normalize_channels

BASE = [1000, 1500, 2000, 0]*8
MAPPING = [1, 2, 3, 4]
IDENTITY = ('kit-A1', 123)


def raw(channels=None, count=8, fresh=True, age=5):
    if channels is None:
        channels = [1500, 1500, 1000, 1500, 1000, 1500, 1500, 1500]
    return list(channels)+[count, fresh, age]


class CaptureTests(unittest.TestCase):
    def sweep(self, baseline=None, mapping=None, count=8):
        c = ReceiverCapture(baseline or BASE, mapping or MAPPING, 100., IDENTITY)
        for i in range(13):
            channels = [1050 if i%2 == 0 else 1950]*4 + [1000,1500,1500,1500]
            channels[count:] = [0]*(8-count)
            stamp=100.+i*.2
            self.assertEqual(c.add(raw(channels, count), stamp, stamp, IDENTITY, True), 'collecting')
        return c

    def test_capture_endpoints_and_center_with_low_throttle(self):
        c=self.sweep()
        r=c.finish(raw([1490,1510,1050,1505,1000,1500,1500,1500]), 102.5,102.5,IDENTITY)
        self.assertEqual(r['values'][:16],[1050,1490,1950,0,1050,1510,1950,0,
                                         1050,1500,1950,0,1050,1505,1950,0])
        self.assertEqual(r['values'][16:], BASE[16:])
        self.assertEqual(r['samples'],13);self.assertGreaterEqual(r['duration_s'],2.)
        self.assertFalse(r['applied_to_fc']);self.assertEqual(c.progress,1.)
        self.assertEqual(json.loads(json.dumps(r)),r)
        r['values'][0]=1;self.assertEqual(c.result['values'][0],1050)

    def test_throttle_center_is_midpoint_and_reverse_changes_low_end(self):
        b=BASE[:];b[11]=1;c=self.sweep(b)
        with self.assertRaisesRegex(ValueError,'Lower the throttle'):
            c.finish(raw([1500,1500,1050,1500,1000,1500,1500,1500]),102.5,102.5,IDENTITY)
        r=c.finish(raw([1500,1500,1950,1500,1000,1500,1500,1500]),102.6,102.6,IDENTITY)
        self.assertEqual(r['values'][8:12],[1050,1500,1950,1])
        self.assertFalse(c.error)

    def test_four_channel_receiver_preserves_absent_aux_defaults(self):
        c=self.sweep(count=4)
        r=c.finish(raw([1500,1500,1050,1500,0,0,0,0],4),102.5,102.5,IDENTITY)
        self.assertEqual(r['values'][16:], BASE[16:])

    def test_aux_switch_capture_gets_midpoint_but_unmoved_aux_is_retained(self):
        c=ReceiverCapture(BASE,MAPPING,100.,IDENTITY)
        for i in range(12):
            v=1100 if i%2 else 1900
            c.add(raw([v,v,v,v,v,1500,1500,1500]),100+i*.2,100+i*.2,IDENTITY,True)
        r=c.finish(raw([1500,1500,1100,1500,1900,1500,1500,1500]),102.3,102.3,IDENTITY)
        self.assertEqual(r['values'][16:20],[1100,1500,1900,0])
        self.assertEqual(r['values'][20:], BASE[20:])

    def test_insufficient_span_can_continue_and_retry(self):
        c=ReceiverCapture(BASE,MAPPING,100.,IDENTITY)
        for i in range(12):c.add(raw(),100+i*.2,100+i*.2,IDENTITY,True)
        with self.assertRaisesRegex(ValueError,'insufficient travel'):c.finish(raw(),102.3,102.3,IDENTITY)
        self.assertFalse(c.error)
        for i,vs in enumerate(([1050]*4,[1950]*4)):
            c.add(raw(vs+[1000]*4),102.4+i*.2,102.4+i*.2,IDENTITY,True)
        self.assertIsInstance(c.finish(raw(),102.7,102.7,IDENTITY),dict)

    def test_distinct_samples_and_duration_are_both_required(self):
        c=ReceiverCapture(BASE,MAPPING,100.,IDENTITY)
        for _ in range(20):c.add(raw(),100.,100.,IDENTITY,True)
        self.assertEqual(c.samples,1)
        with self.assertRaisesRegex(ValueError,'ten fresh frames'):c.finish(raw(),100.1,100.1,IDENTITY)
        # A cached pre-click frame and reordering do not count as new frames.
        self.assertEqual(c.add(raw(),99.9,100.1,IDENTITY,True),'ignored')
        self.assertEqual(c.samples,1)

    def test_stale_unsafe_changed_identity_and_invalid_payload_abort_permanently(self):
        cases=[(raw(),100.,100.6,IDENTITY,True),
               (raw(),100.1,100.,IDENTITY,True),
               (raw(),100.,100.,IDENTITY,False),
               (raw(),100.,100.,('kit-B',123),True),
               (raw(fresh=False),100.,100.,IDENTITY,True),
               (raw(age=251),100.,100.,IDENTITY,True),
               (raw([float('nan')]+[1500]*7),100.,100.,IDENTITY,True),
               (raw([1500]*4+[0]*4,3),100.,100.,IDENTITY,True)]
        for args in cases:
            with self.subTest(args=args):
                c=ReceiverCapture(BASE,MAPPING,100.,IDENTITY)
                self.assertEqual(c.add(*args),'error');self.assertTrue(c.error)
                self.assertEqual(c.add(raw(),101.,101.,IDENTITY,True),'error')
                with self.assertRaises(ValueError):c.finish(raw(),101.,101.,IDENTITY)

    def test_unassigned_active_channel_invalid_pulse_rejects_entire_frame(self):
        c=ReceiverCapture(BASE,MAPPING,100.,IDENTITY)
        self.assertEqual(c.add(raw([1500]*7+[2200]),100.,100.,IDENTITY,True),'error')

    def test_mapping_and_baseline_validation(self):
        for mapping in ([1,1,3,4],[1,2,3,9],[1,2,3],['1',2,3,4]):
            with self.assertRaises(ValueError):ReceiverCapture(BASE,mapping,100.,IDENTITY)
        for b in ([1000]*32,BASE[:-1], [True]+BASE[1:]):
            with self.assertRaises(ValueError):ReceiverCapture(b,MAPPING,100.,IDENTITY)
        with self.assertRaises(ValueError):ReceiverCapture(BASE,MAPPING,math.nan,IDENTITY)
        with self.assertRaises(ValueError):ReceiverCapture(BASE,MAPPING,100.,None)

    def test_mapping_needs_available_raw_channels_and_centering(self):
        c=ReceiverCapture(BASE,[1,2,3,8],100.,IDENTITY)
        self.assertEqual(c.add(raw([1500]*4+[0]*4,4),100.,100.,IDENTITY,True),'error')
        c=self.sweep()
        with self.assertRaisesRegex(ValueError,'centre'):
            c.finish(raw([1080,1500,1050,1500,1000,1500,1500,1500]),102.5,102.5,IDENTITY)

    def test_historical_result_cannot_be_returned_for_changed_connection(self):
        c=self.sweep();c.finish(raw(),102.5,102.5,IDENTITY)
        with self.assertRaisesRegex(ValueError,'connection changed'):
            c.finish(raw(),102.6,102.6,('new',123))


class NormalizeTests(unittest.TestCase):
    def test_endpoints_deadband_and_aux_passthrough(self):
        self.assertEqual(normalize_channels([1000,2000,1000,1504,1100,1700,1800,1900],BASE,MAPPING),
                         [1000,2000,1000,1500,1100,1700,1800,1900])

    def test_asymmetric_center_and_reverse(self):
        b=BASE[:];b[:4]=[1000,1400,2000,1]
        self.assertEqual(normalize_channels([1200,1500,2000,1500,1000,1000,1000,1000],b,MAPPING)[0],1750)
        self.assertEqual(normalize_channels([1700,1500,2000,1500,1000,1000,1000,1000],b,MAPPING)[0],1250)
        b[11]=1
        self.assertEqual(normalize_channels([1400,1500,2000,1500,1000,1000,1000,1000],b,MAPPING)[2],1000)

    def test_mapping_swaps_roles_without_changing_aux_or_source(self):
        original=[1000,1200,1400,1600,1800,2000,1100,1300]
        result=normalize_channels(original,BASE,[4,2,1,3],0)
        self.assertEqual(result,[1600,1200,1000,1400,1800,2000,1100,1300])
        self.assertEqual(original,[1000,1200,1400,1600,1800,2000,1100,1300])

    def test_missing_axis_or_invalid_deadband_rejected_and_absent_aux_allowed(self):
        self.assertEqual(normalize_channels([1500,1500,1000,1500,0,0,0,0],BASE,MAPPING)[4:],[0]*4)
        with self.assertRaises(ValueError):normalize_channels([0]*8,BASE,MAPPING)
        for db in (-1,51,True,float('nan')):
            with self.assertRaises(ValueError):normalize_channels([1500]*8,BASE,MAPPING,db)


if __name__=='__main__':unittest.main()
