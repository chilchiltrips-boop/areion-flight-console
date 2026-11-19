import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import areion_usb as console
import live_control as live
import receiver_control as rc
from test_receiver_control import Clock, FakeFC


class LiveControlTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.fc = FakeFC(self.clock)
        self.control = live.ControlSession(self.fc)

    def start(self, source=1):
        self.fc.selected = source
        self.control.start(self.fc.read_group(120), self.fc.read_group(122), self.clock.now)

    def advance(self, until):
        while self.clock.now < until:
            self.control.tick(self.clock.now)
            self.clock.now += .005

    def test_both_sources_bootstrap_neutral_and_reach_fifty_hz(self):
        for source in (1, 2):
            self.setUp()
            self.start(source)
            self.advance(1.0)
            self.assertTrue(self.control.ready)
            self.assertGreaterEqual(len(self.fc.values), 49)
            self.assertLessEqual(len(self.fc.values), 51)
            self.assertTrue(all(entry[1] == rc.NEUTRAL_CHANNELS for entry in self.fc.values))
            self.assertTrue(all(entry[2] == (source == 1) and entry[3] == (source == 2) for entry in self.fc.values))

    def test_stop_cancels_arm_and_never_transmits_again(self):
        self.start()
        self.advance(.4)
        cancel = self.control.arm_arguments(self.clock.now)['cancel']
        count = len(self.fc.values)
        self.control.stop()
        self.assertTrue(cancel.is_set())
        self.advance(1)
        self.assertEqual(len(self.fc.values), count)

    def test_restart_neutralizes_previously_applied_throttle(self):
        self.start()
        self.advance(.4)
        self.control.apply([1500, 1500, 1200, 1500, 1000, 1000, 1000, 1000])
        self.control.stop()
        self.start()
        self.assertEqual(self.control.values, list(rc.NEUTRAL_CHANNELS))
        self.assertFalse(self.control.ready)

    def test_arm_needs_fresh_ready_and_neutral(self):
        self.start()
        with self.assertRaises(ValueError):
            self.control.arm_arguments(self.clock.now)
        self.advance(.4)
        self.assertTrue(self.control.arm_arguments(self.clock.now)['datagram_only'])
        self.control.apply([1500, 1500, 1200, 1500, 1000, 1000, 1000, 1000])
        with self.assertRaises(ValueError):
            self.control.arm_arguments(self.clock.now)
        self.control.apply(rc.NEUTRAL_CHANNELS)
        with self.assertRaises(ValueError):
            self.control.arm_arguments(self.clock.now + .5)

    def test_stall_stops_before_sending_a_delayed_sample(self):
        self.start()
        self.advance(.4)
        count = len(self.fc.values)
        with self.assertRaises(RuntimeError):
            self.control.tick(self.clock.now + .2)
        self.assertFalse(self.control.running)
        self.assertEqual(len(self.fc.values), count)

    def test_missing_path_or_changed_source_stops(self):
        for change in ('path', 'source'):
            self.setUp()
            self.start()
            self.advance(.4)
            if change == 'path':
                self.fc.stale_at = .4
            else:
                self.fc.events.append(SimpleNamespace(group=122, schema=2,
                    data=[0, 1, True, False, True, 8, 0, self.fc.session, False]))
            with self.assertRaises(RuntimeError):
                self.control.tick(self.clock.now)
            self.assertFalse(self.control.running)

    def test_fc_disarming_stops_held_controls_until_explicit_start(self):
        self.start()
        self.advance(.4)
        for armed in (True, False):
            self.fc.events.append(SimpleNamespace(group=120, schema=1,
                data=[armed, True, True, 8, .004, 2000, 100, True, False, False]))
            if armed:
                self.control.tick(self.clock.now)
                self.clock.now += .02
            else:
                with self.assertRaises(RuntimeError):
                    self.control.tick(self.clock.now)
        self.assertFalse(self.control.running)

    def test_not_ready_cannot_apply_requested_high_channels(self):
        self.start()
        with self.assertRaises(ValueError):
            self.control.apply([1500] * 8)

    def test_arm_ack_is_not_enough_for_disarm_status(self):
        link = SimpleNamespace(disarm=lambda: ['DISARMED'],
            read_group=lambda *a, **k: [True] + [False] * 9)
        with self.assertRaises(RuntimeError):
            live.disarm_and_read(link)
        link.read_group = lambda *a, **k: [False] * 10
        self.assertIn('FC DISARMED', live.disarm_and_read(link))

    def test_usb_burst_uses_serial_only(self):
        self.fc.selected = 2
        with patch.object(rc, 'time', self.clock), contextlib.redirect_stdout(io.StringIO()):
            rc.run_control_burst(self.fc, rc.NEUTRAL_CHANNELS, 1)
        self.assertTrue(all(v[3] and not v[2] for v in self.fc.values))


class OffsetFC:
    def __init__(self):
        self.offsets = [-.1, .03, .12]
        self.stored = self.offsets[:]
        self.armed = False
        self.calls = []
    def read_group(self, group, schema=1, saved=False):
        self.calls.append(('read', group, schema, saved))
        if group == 120:
            return [self.armed, True, True, 8, .004, 2000, 100, True, False, False]
        if group != 6 or schema != 2:
            raise AssertionError('offset group must reuse6 with schema2')
        return (self.stored if saved else self.offsets)[:]
    def set_group(self, group, values, schema):
        self.calls.append(('set', group, schema))
        self.offsets = values[:]
        return ['APPLIED_UNSAVED']
    def save_group(self, group, schema):
        self.calls.append(('save', group, schema))
        self.stored = self.offsets[:]
        return ['SAVED']


class OffsetTests(unittest.TestCase):
    def test_additive_signs_and_bounds(self):
        self.assertEqual(console.parse_offsets('-.10,+.03,+.12'), [-.1, .03, .12])
        for text in ('[true,0,0]', '[NaN,0,0]', '[0.5001,0,0]', '[-.5001,0,0]', '[0,0]'):
            with self.assertRaises(ValueError):
                console.parse_offsets(text)

    def test_edit_reads_back_ram_without_auto_save(self):
        fc = OffsetFC()
        with patch('builtins.input', return_value='-.11,.02,.13'), contextlib.redirect_stdout(io.StringIO()):
            console.edit_offsets(fc)
        self.assertEqual(fc.offsets, [-.11, .02, .13])
        self.assertEqual(fc.stored, [-.1, .03, .12])
        self.assertIn(('set', 6, 2), fc.calls)
        self.assertFalse(any(call[0] == 'save' for call in fc.calls))

    def test_save_uses_existing_imu_group6_schema2_and_stored_readback(self):
        fc = OffsetFC()
        fc.offsets = [-.11, .02, .13]
        with patch('builtins.input', return_value='6'), contextlib.redirect_stdout(io.StringIO()):
            console.save_pid(fc)
        self.assertEqual(fc.offsets, fc.stored)
        self.assertEqual(fc.calls[-2:], [('save', 6, 2), ('read', 6, 2, True)])

    def test_armed_during_typing_prevents_offset_set(self):
        fc = OffsetFC()
        def typed(_):
            fc.armed = True
            return '-.11,.02,.13'
        with patch('builtins.input', side_effect=typed), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            console.edit_offsets(fc)
        self.assertFalse(any(call[0] == 'set' for call in fc.calls))


if __name__ == '__main__':
    unittest.main()
