"""Verified reset, persistent input and armed/deferred PID transactions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch

from fc_fixture import DemoLink
from areion_gui.backend import apply_pid, save_input
from areion_gui.model import NEUTRAL
from areion_gui.setup_backend import SETUP_SETTINGS, run_setup_action
from zebjus_areion_link.schema import DRONE_GROUPS
from tests.setup_fixtures import complete_demo_setup
from tests.test_setup_lifecycle import Clock
from tests.test_actions_sdk import connected_link
from zebjus_areion_link import Message, RemoteError, decode_frame


class Configuration310Tests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.link = DemoLink(clock=self.clock)

    def action(self, name, payload=None):
        return run_setup_action(self.link, name, payload or {}, lambda: False)

    def complete(self, source=1):
        complete_demo_setup(self.link, source)

    def arm(self):
        self.link.send_control(NEUTRAL, datagram_only=self.link.source == 1,
                               serial_only=self.link.source == 2)
        self.link.arm()

    def gains(self, group=2, delta=.2):
        values = self.link.values[group][:]
        values[0] += delta
        return values

    def test_reset_requires_both_confirmations_and_setup_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'setup lock'):
            self.action('reset_all', {'props_removed': True, 'confirmed': True})
        self.action('begin')
        for payload in ({}, {'props_removed': True}, {'confirmed': True},
                        {'props_removed': 1, 'confirmed': True}):
            with self.assertRaisesRegex(ValueError, 'Confirm propellers'):
                self.action('reset_all', payload)

    def test_review_of_unchanged_saved_setup_has_no_redundant_settings_writes(self):
        self.complete(0)
        checks = self.link.read_group(130)[3:8]
        with patch.object(self.link, 'set_group', wraps=self.link.set_group) as setting, \
                patch.object(self.link, 'save_group', wraps=self.link.save_group) as saving:
            self.action('begin')
            groups = {group: self.link.values[group][:] for group in SETUP_SETTINGS}
            self.assertTrue(self.action('apply_save', {'groups': groups})['complete'])
            result = self.action('finalize', {'groups': groups})
            self.assertTrue(result['complete'])
            setting.assert_not_called()
            saving.assert_not_called()
        self.assertEqual(result['values'][130][:2], [False, True])
        self.assertEqual(result['values'][130][3:8], checks)

    def test_changed_setup_persists_only_changed_section(self):
        self.complete()
        self.action('begin')
        groups = {group: self.link.values[group][:] for group in SETUP_SETTINGS}
        groups[2][0] += .2
        with patch.object(self.link, 'set_group', wraps=self.link.set_group) as setting, \
                patch.object(self.link, 'save_group', wraps=self.link.save_group) as saving:
            self.assertTrue(self.action('finalize', {'groups': groups})['complete'])
            self.assertEqual([item.args[0] for item in setting.call_args_list], [2])
            self.assertEqual([item.args[0] for item in saving.call_args_list], [2])

    def test_first_setup_save_handles_only_missing_stored_group(self):
        self.action('begin')
        read = self.link.read_group
        missing = {2}
        def not_saved(group, schema=1, saved=False, **kwargs):
            if saved and group in missing:
                missing.remove(group)
                raise RemoteError(Message('ERROR', group, schema, 42, 1, ('NOT_SAVED',)))
            return read(group, schema, saved, **kwargs)
        with patch.object(self.link, 'read_group', side_effect=not_saved), \
                patch.object(self.link, 'set_group', wraps=self.link.set_group) as setting, \
                patch.object(self.link, 'save_group', wraps=self.link.save_group) as saving:
            result = self.action('apply_save', {'groups': {2: self.link.values[2][:]}})
            self.assertTrue(result['complete'])
            setting.assert_not_called()
            saving.assert_called_once_with(2, schema=1)
        def corrupt(group, schema=1, saved=False, **kwargs):
            if saved and group == 2:
                raise RemoteError(Message('ERROR', group, schema, 42, 2, ('STORAGE_CORRUPT',)))
            return read(group, schema, saved, **kwargs)
        with patch.object(self.link, 'read_group', side_effect=corrupt), \
                patch.object(self.link, 'save_group') as saving:
            result = self.action('apply_save', {'groups': {2: self.link.values[2][:]}})
            self.assertFalse(result['complete'])
            self.assertIn('STORAGE_CORRUPT', result['error'])
            saving.assert_not_called()

    def test_reset_restores_every_default_and_clears_all_physical_checks(self):
        self.complete(0)
        apply_pid(self.link, 2, self.gains())
        self.action('begin')
        result = self.action('reset_all', {'props_removed': True, 'confirmed': True})
        self.assertTrue(result['complete'])
        for group in SETUP_SETTINGS:
            expected = [field['default'] for field in DRONE_GROUPS[group]['fields']]
            self.assertEqual(result['values'][group], expected)
            self.assertEqual(self.link.saved[group], expected)
        self.assertEqual(result['values'][130][0:9],
                         [True, False, 1, 0, 0, False, False, False, False])
        self.assertEqual(result['values'][136], [False, 0, 0, ''])
        self.assertEqual(self.link.read_group(23, 2)[3:7], [1000.] * 4)
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[:2], [True, False])

    def test_reset_partial_storage_failure_stays_locked_after_restart(self):
        self.complete()
        self.action('begin')
        original = self.link._store_setting
        def broken(group, values):
            if group == 6:
                raise RuntimeError('NVS write rejected')
            original(group, values)
        with patch.object(self.link, '_store_setting', side_effect=broken):
            with self.assertRaisesRegex(RuntimeError, 'RESET_SAVE_FAILED'):
                self.action('reset_all', {'props_removed': True, 'confirmed': True})
        self.assertFalse(self.link.read_group(120)[7])
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[:2], [True, False])

    def test_reset_cancels_pending_esc_once_and_rejects_running_sequence(self):
        self.complete(0)
        self.action('begin')
        self.action('command', {'command': 'ESC_SCHEDULE', 'args': [1, 0, 0, 0]})
        self.action('reset_all', {'props_removed': True, 'confirmed': True})
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[3], 0)
        self.complete(0)
        self.action('begin')
        self.action('command', {'command': 'ESC_SCHEDULE', 'args': [1, 0, 0, 0]})
        self.link.demo_restart()
        with self.assertRaisesRegex(ValueError, 'CALIBRATION_BUSY'):
            self.action('reset_all', {'props_removed': True, 'confirmed': True})

    def test_pending_esc_reset_marker_failure_reports_uncertain_cancellation(self):
        self.complete(0)
        self.action('begin')
        self.action('command', {'command': 'ESC_SCHEDULE', 'args': [1, 0, 0, 0]})
        with patch.object(self.link, '_persist', side_effect=RuntimeError('NVS failed')):
            with self.assertRaisesRegex(RuntimeError, 'RESET_ESC_CANCEL_NOT_PERSISTED'):
                self.link.action(135, ['RESET_ALL', 1, 0, 0, 0])
        self.assertEqual(self.link.read_group(130)[3], 6)
        self.assertFalse(self.link.read_group(120)[7])
        self.assertTrue(self.link._esc_cancel_uncertain)

    def test_persistent_modes_retain_qualification_and_survive_restart(self):
        self.complete(0)
        checks = self.link.read_group(130)[3:8]
        for source in (1, 2, 0):
            result = save_input(self.link, source)
            self.assertTrue(result['complete'])
            self.assertEqual(result['values'][110], [source])
            self.assertEqual(result['values'][130][:2], [False, True])
            self.assertEqual(result['values'][130][3:8], checks)
            self.assertEqual(self.link.values[134], self.link.saved[134])
            self.link.demo_restart()
            self.assertEqual(self.link.source, source)
            self.assertEqual(self.link.read_group(130)[:2], [False, True])

    def test_wizard_input_keeps_qualification_and_saved_groups(self):
        self.complete(0)
        self.action('begin')
        proof = self.link.read_group(130)[3:8]
        previous = {group: values[:] for group, values in self.link.saved.items()}
        for source in (1, 2, 0):
            with patch.object(self.link, 'set_group', wraps=self.link.set_group) as setting:
                result = self.action('input', {'source': source})
                setting.assert_not_called()
            previous[134][1] = source
            self.assertEqual(self.link.saved, previous)
            self.assertEqual(result['values'][130][:2], [True, False])
            self.assertEqual(result['values'][130][3:8], proof)
        self.assertTrue(self.action('finalize', {'groups': {}})['complete'])

    def test_first_ppm_setup_keeps_existing_motor_and_sensor_checks(self):
        self.complete(1)
        self.action('begin')
        before = self.link.read_group(130)
        result = self.action('input', {'source': 0})
        self.assertTrue(result['complete'])
        self.assertEqual(result['values'][130][:2], [True, False])
        self.assertEqual(result['values'][130][3:6], before[3:6])
        self.assertFalse(result['values'][130][6])
        with self.assertRaisesRegex(ValueError, 'SETUP_INCOMPLETE'):
            self.action('finalize', {'groups': {}})
        self.link.demo_set_receiver(NEUTRAL)
        self.action('command', {'command': 'RX_OK', 'args': [1, 0, 0, 0]})
        self.assertTrue(self.action('finalize', {'groups': {}})['complete'])

    def test_input_refuses_to_persist_unrelated_pending_fc_edit(self):
        self.action('begin')
        changed = self.link.values[134][:]
        changed[7] += 25
        self.link.set_group(134, changed)
        for source in (0, 1, 2):
            with self.assertRaisesRegex(RuntimeError, 'unsaved configuration'):
                self.action('input', {'source': source})
        self.assertNotEqual(self.link.saved[134][7], changed[7])

    def test_input_rejects_unexpected_ack_or_loss_of_proof(self):
        self.complete(0)
        with patch.object(self.link, 'action', return_value=['UNRELATED_ACK']):
            with self.assertRaisesRegex(RuntimeError, 'not acknowledged'):
                save_input(self.link, 2)
        action = self.link.action
        def clear_proof(*args, **kwargs):
            response = action(*args, **kwargs)
            self.link._setup[6] = False
            return response
        with patch.object(self.link, 'action', side_effect=clear_proof):
            with self.assertRaisesRegex(RuntimeError, 'calibration checks changed'):
                save_input(self.link, 2)

    def test_input_rejects_unverified_ppm_armed_and_unsafe_mode_channel(self):
        self.complete()
        with self.assertRaisesRegex(ValueError, 'PPM_NOT_VERIFIED'):
            save_input(self.link, 0)
        self.arm()
        with self.assertRaisesRegex(ValueError, 'armed'):
            save_input(self.link, 2)
        self.link.disarm()
        self.link.values[7][0] = 4
        with self.assertRaisesRegex(ValueError, 'CH5'):
            save_input(self.link, 2)

    def test_input_failure_does_not_claim_completion(self):
        self.complete()
        with patch.object(self.link, '_store_setting', side_effect=RuntimeError('NVS failed')):
            with self.assertRaisesRegex(RuntimeError, 'INPUT_SAVE_FAILED'):
                save_input(self.link, 2)
        self.assertEqual(self.link.read_group(130)[:2], [True, False])
        self.link.demo_restart()
        self.assertEqual(self.link.source, 1)
        self.assertTrue(self.link.read_group(130)[0])

    def test_disarmed_pid_apply_verifies_saved_values_and_retains_completion(self):
        self.complete()
        for group in (2, 3):
            values = self.gains(group)
            result = apply_pid(self.link, group, values)
            self.assertTrue(result['saved'])
            self.assertFalse(result['pending'])
            self.assertEqual(result['stored'], values)
            self.assertEqual(result['values'][130][:2], [False, True])
        self.link.demo_restart()
        self.assertEqual(self.link.values[3], values)
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        self.assertEqual(self.link.read_group(136), [False, 0, 0, ''])

    def test_pid_during_wizard_does_not_finalize_setup(self):
        self.action('begin')
        result = apply_pid(self.link, 2, self.gains())
        self.assertTrue(result['saved'])
        self.assertEqual(result['values'][130][:2], [True, False])

    def test_armed_pid_requires_bench_and_never_writes_flash(self):
        self.complete()
        self.arm()
        with self.assertRaisesRegex(ValueError, 'Confirm the secured'):
            apply_pid(self.link, 2, self.gains())
        with patch.object(self.link, '_persist', wraps=self.link._persist) as persist, \
                patch.object(self.link, '_store_setting', wraps=self.link._store_setting) as store:
            result = apply_pid(self.link, 2, self.gains(), bench_confirmed=True)
            self.assertTrue(result['pending'])
            self.assertFalse(result['saved'])
            persist.assert_not_called()
            store.assert_not_called()
        self.assertTrue(self.link.armed)
        self.assertEqual(self.link.read_group(136), [True, 1, 0, ''])

    def test_latest_rate_and_angle_snapshots_persist_automatically_on_disarm(self):
        self.complete()
        self.arm()
        first = self.gains()
        apply_pid(self.link, 2, first, True)
        latest = self.gains(delta=.5)
        angle = self.gains(3)
        apply_pid(self.link, 2, latest, True)
        apply_pid(self.link, 3, angle, True)
        self.assertEqual(self.link.read_group(136), [True, 3, 0, ''])
        self.assertNotEqual(self.link.saved[2], latest)
        self.link.disarm()
        self.assertEqual(self.link.saved[2], latest)
        self.assertEqual(self.link.saved[3], angle)
        self.assertEqual(self.link.read_group(136), [False, 3, 3, ''])
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        self.link.demo_restart()
        self.assertEqual(self.link.values[2], latest)

    def test_input_timeout_disarm_flushes_pending_pid(self):
        self.complete()
        self.arm()
        values = self.gains()
        apply_pid(self.link, 2, values, True)
        self.clock.advance(.3)
        status = self.link.read_group(136)
        self.assertFalse(self.link.armed)
        self.assertEqual(status, [False, 1, 1, ''])
        self.assertEqual(self.link.saved[2], values)

    def test_power_loss_before_disarm_restores_previous_saved_pid(self):
        self.complete()
        saved = self.link.saved[2][:]
        self.arm()
        apply_pid(self.link, 2, self.gains(), True)
        self.link.demo_restart()
        self.assertEqual(self.link.values[2], saved)
        self.assertEqual(self.link.read_group(136), [False, 0, 0, ''])
        self.assertEqual(self.link.read_group(130)[:2], [False, True])

    def test_failed_flush_remains_pending_error_locked_and_is_not_retried(self):
        self.complete()
        self.arm()
        apply_pid(self.link, 2, self.gains(), True)
        with patch.object(self.link, '_store_setting', side_effect=RuntimeError('NVS rejected')) as store:
            self.link.disarm()
            state = self.link.read_group(136)
            self.assertEqual(state[:3], [True, 1, 0])
            self.assertIn('NVS rejected', state[3])
            self.link.poll()
            self.link.read_group(136)
            store.assert_called_once()
        self.assertEqual(self.link.read_group(130)[:2], [True, False])
        self.assertFalse(self.link.read_group(120)[7])
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[:2], [True, False])

    def test_pid_malformed_values_are_atomic_and_revision_exhaustion_rejects(self):
        old = self.link.values[2][:]
        for payload in ([2, True] + [1.] * 8,
                        [2, 1] + [1.] * 9,
                        [2, False] + [1] * 9,
                        [2, False] + [float('nan')] * 9,
                        [3, False] + [1.] * 9,
                        [2, False] + [-1.] * 9):
            with self.assertRaises(ValueError):
                self.link.action(137, payload)
            self.assertEqual(self.link.values[2], old)
        self.link._pid_revision = 0xffffffff
        with self.assertRaisesRegex(ValueError, 'REVISION_EXHAUSTED'):
            apply_pid(self.link, 2, self.gains())
        self.assertEqual(self.link.values[2], old)

    def test_helpers_honor_cancellation_before_commands_and_reject_bad_readback(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(self.link, 'action') as command:
            for call in (lambda: apply_pid(self.link, 2, self.gains(), cancel=cancelled),
                         lambda: save_input(self.link, 1, cancelled)):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    call()
            command.assert_not_called()
        self.complete()
        original = self.link.read_group
        def mismatched(group, schema=1, saved=False):
            result = original(group, schema, saved)
            if saved and group == 2:
                result[0] += 1.
            return result
        with patch.object(self.link, 'read_group', side_effect=mismatched):
            with self.assertRaisesRegex(RuntimeError, 'Stored PID readback differs'):
                apply_pid(self.link, 2, self.gains())

    def test_session_change_after_pid_action_rejects_success(self):
        self.complete()
        original = self.link.action
        def restarted(*args, **kwargs):
            result = original(*args, **kwargs)
            self.link.demo_restart()
            return result
        with patch.object(self.link, 'action', side_effect=restarted):
            with self.assertRaisesRegex(RuntimeError, 'session changed'):
                apply_pid(self.link, 2, self.gains())

    def test_stop_cancels_delayed_post_pid_read_and_disarms_without_waiting_for_retries(self):
        link, usb, udp = connected_link()
        link.request_timeout = 2.0
        cancel = threading.Event()
        delayed_read = threading.Event()
        calls, errors = [], []
        def send(transport, frame):
            request = decode_frame(frame)
            calls.append(request)
            if request.type == 'READ' and request.group == 2:
                delayed_read.set()
                return  # Simulate a lost post-ACTION response; normal timeout is 6 seconds.
            if request.type == 'READ' and request.group == 120:
                reply_type = 'DATA'
                data = (True, True, True, 8, .004, 2000, 100, True, True, True)
            elif request.type == 'ACTION':
                reply_type = 'ACK'
                data = ('PID_APPLIED_PENDING_SAVE',) if request.group == 137 else ('DISARMED',)
            else:
                return
            link._handle(transport.path, Message(reply_type, request.group, request.schema,
                                                request.session, request.seq, data))
        usb.send = lambda frame: send(usb, frame)
        udp.send = lambda frame: send(udp, frame)
        def worker():
            try:
                apply_pid(link, 2, self.gains(), True, cancel)
            except Exception as error:
                errors.append(str(error))
            # Same worker then services the queued priority Stop job.
            link.disarm()
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(delayed_read.wait(.5))
        stopped_at = time.monotonic()
        cancel.set()
        thread.join(.35)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - stopped_at, .35)
        self.assertIn('cancelled', errors[0])
        ids = [(item.type, item.group) for item in calls]
        self.assertNotIn(('READ', 136), ids)
        self.assertNotIn(('READ', 130), ids)
        unique_reads = {item.seq for item in calls if item.type == 'READ' and item.group == 2}
        self.assertEqual(len(unique_reads), 1)
        self.assertEqual(calls[-1].data, ('DISARM',))


if __name__ == '__main__':
    unittest.main()
