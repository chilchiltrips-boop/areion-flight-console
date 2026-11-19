"""Read-only PPM radio indication using actual indexed telemetry history."""
import tempfile
import unittest

from areion_gui.model import Telemetry
from areion_gui.tx_link import Verification, classify, load_profile, observe, remove_profile, save_profile, spare_channels
from zebjus_areion_link.schema import DRONE_GROUPS


class TransmitterEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.data = Telemetry()
        self.put(130, 0., [False, True, 0, 5, 15, True, True, False, False,
                           1000, 1000, 1000, 1000, 1, '', 'A1-test'])
        self.defaults(7)
        self.defaults(134)

    def put(self, group, stamp, values):
        self.assertTrue(self.data.put(group, DRONE_GROUPS[group]['schema'], values, stamp))

    def defaults(self, group):
        self.put(group, 0., [field['default'] for field in DRONE_GROUPS[group]['fields']])

    def frame(self, t, marker, count=8, ready=True):
        present = marker is not None
        accepted = ready and present
        self.put(120, t, [False, True, True, count if accepted else 0, .004, 2000, 48000, True, False, False])
        self.put(122, t, [0, int(accepted), present, False, accepted, count if present else 0,
                          8 if present else 5000, 44, False])
        if present:
            self.put(22, t, [1500, 1500, 1000, 1500, 1000, marker, 1500, 1500])
        return observe(self.data, t)

    def samples(self, t, marker, count=8):
        for stamp in (t - .3, t - .15, t):
            obs = self.frame(stamp, marker, count)
        return obs

    def learn(self, off_marker=1100, count=8, channel=6):
        v = Verification(channel)
        v.capture(self.samples(1., 1800, count))
        v.capture(self.samples(2., off_marker, count))
        return v.capture(self.samples(3., 1810, count))

    def test_high_held_before_configuration_and_marker_loss_after_learning(self):
        self.assertEqual(classify(self.samples(.5, 1800)).code, 'unverified')
        profile = self.learn()
        self.assertEqual(classify(observe(self.data, 3.), profile).state, 'green')
        self.assertEqual(classify(self.frame(3.1, 1100), profile).label, 'CHECKING')
        self.assertEqual(classify(self.frame(3.2, 1100), profile).label, 'TX OFF')
        self.assertEqual(classify(self.samples(4., 1500), profile).state, 'amber')
        self.assertEqual(classify(self.frame(4.1, None), profile).label, 'NO PPM')
        self.assertEqual(classify(self.frame(4.2, 1100), profile).label, 'CHECKING')
        self.assertEqual(classify(self.frame(4.3, 1800), profile).label, 'CHECKING')
        self.assertEqual(classify(self.frame(4.4, 1800), profile).state, 'green')
        self.assertEqual(classify(observe(self.data, 5.), profile).state, 'amber')

    def test_explicit_loss_and_pulse_only_check_without_spare(self):
        self.assertEqual(spare_channels(self.samples(.4, 1800, count=4)), ())
        profile = self.learn(None, count=4, channel=None)
        self.assertEqual(profile['kind'], 'pulse')
        self.assertEqual(classify(observe(self.data, 3.), profile).state, 'green')
        self.assertEqual(classify(self.samples(4., None), profile).state, 'amber')

    def test_reread_same_frames_held_receiver_and_incorrect_restore_are_rejected(self):
        v = Verification(6)
        obs = self.samples(1., 1800)
        v.capture(obs)
        with self.assertRaises(ValueError):
            v.capture(obs)
        with self.assertRaises(ValueError):
            v.capture(self.samples(2., 1800))
        self.assertEqual(v.step, 1)
        v.capture(self.samples(3., 1100))
        with self.assertRaises(ValueError):
            v.capture(self.samples(4., 1100))
        self.assertEqual(v.step, 2)

    def test_identity_source_config_and_newer_gate_status(self):
        p = self.learn()
        with tempfile.TemporaryDirectory() as folder:
            save_profile(folder, p)
            self.assertEqual(load_profile(folder, 'A1-test'), p)
            self.assertIsNone(load_profile(folder, 'another-kit'))
            remove_profile(folder, 'A1-test')
            self.assertIsNone(load_profile(folder, 'A1-test'))
        self.put(120, 3.01, [False, True, True, 0, .004, 2000, 900, True, False, False])
        self.assertEqual(classify(observe(self.data, 3.02), p).state, 'amber')
        self.put(110, 3.03, [2])
        self.assertEqual(classify(observe(self.data, 3.04), p).code, 'inactive')
        self.put(7, 3.05, [6, .1, .15, .15, 0, 1])
        obs = self.samples(4., 1800)
        self.assertNotIn(6, spare_channels(obs))
        self.assertEqual(classify(obs, p).code, 'unverified')
        self.assertEqual(classify(observe(self.data, 4., connected=False), p).code, 'inactive')

    def test_witness_requires_recent_disarmed_status(self):
        self.samples(1., 1800)
        self.put(120, 1.01, [True, True, True, 8, .004, 2000, 900, True, False, False])
        with self.assertRaisesRegex(ValueError, 'disarmed'):
            Verification(6).capture(observe(self.data, 1.02))
