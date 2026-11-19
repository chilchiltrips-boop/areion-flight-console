"""Firmware lifecycle API model: setup lock, one-shot ESC and bounded bench output."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import unittest
from unittest.mock import Mock, patch
from fc_fixture import DemoLink
from areion_gui.backend import open_link
from areion_gui.setup_backend import run_setup_action, SETUP_SETTINGS
from areion_gui.model import NEUTRAL


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class SetupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.link = DemoLink(clock=self.clock)

    def run_action(self, name, payload=None):
        return run_setup_action(self.link, name, payload or {}, lambda: False)

    def command(self, name, args=None):
        return self.run_action('command', {'command': name, 'args': [1, 0, 0, 0] if args is None else args})

    def prepare(self, digital=False):
        self.run_action('begin')
        if digital:
            values = self.link.values[134][:]
            values[1] = 1
            self.assertTrue(self.run_action('apply_save', {'groups': {134: values}})['complete'])
        self.command('SENSOR_OK')
        if not digital:
            self.command('RX_OK')
        self.command('ESC_SKIP')

    def motor_checks(self):
        self.command('MOTOR_START', [15, 1, 0, 0])
        self.command('MOTOR_SET', [15, 1120, 0, 0])
        self.command('MOTOR_STOP', [0, 0, 0, 0])
        self.command('MOTOR_OK', [15, 1, 0, 0])

    def complete(self, digital=False):
        self.prepare(digital)
        self.motor_checks()
        return self.run_action('finalize', {'groups': {g: self.link.values[g][:] for g in SETUP_SETTINGS}})

    def test_completion_and_reboot_do_not_require_optional_loss_attestation(self):
        result=self.complete()
        self.assertTrue(result['complete'])
        self.assertFalse(self.link.read_group(130)[7])
        self.assertFalse(self.link._ppm_loss_seen)
        self.link.demo_restart()
        state=self.link.read_group(130)
        self.assertEqual(state[:2],[False,True])
        self.assertFalse(state[7]);self.assertFalse(self.link.armed)
        self.link.set_group(110,[0])

    def test_default_locked_and_direct_arm_cannot_bypass(self):
        self.assertTrue(self.link.read_group(130)[0])
        with self.assertRaisesRegex(ValueError, 'SETUP_LOCKED'):
            self.link.action(123, ['ARM'])
        with self.assertRaisesRegex(ValueError, 'SETUP_NOT_ACTIVE'):
            self.link.action(135, ['FINALIZE', 0, 0, 0, 0])

    def test_begin_is_confirmed_before_any_settings_or_outputs(self):
        with patch.object(self.link, 'disarm', wraps=self.link.disarm) as disarm:
            result = self.run_action('begin')
        disarm.assert_called_once()
        self.assertTrue(result['values'][130][0])
        self.assertFalse(result['values'][130][1])
        self.assertEqual(result['values'][130][9:13], [1000] * 4)

    def test_apply_save_is_not_finalization(self):
        self.run_action('begin')
        result = self.run_action('apply_save', {'groups': {4: self.link.values[4][:]}})
        self.assertTrue(result['complete'])
        self.assertTrue(result['values'][130][0])
        self.assertFalse(result['values'][130][1])
        with self.assertRaises(ValueError): self.run_action('finalize')

    def test_final_save_unlocks_but_never_arms(self):
        result = self.complete(digital=True)
        self.assertTrue(result['complete'])
        self.assertEqual(result['values'][130][:2], [False, True])
        self.assertFalse(self.link.armed)
        with self.assertRaisesRegex(ValueError, 'fresh neutral'):
            self.link.arm()
        self.link.send_control(NEUTRAL, datagram_only=True)
        self.link.arm()
        self.assertTrue(self.link.armed)

    def test_noop_final_save_preserves_all_evidence(self):
        self.prepare(); self.motor_checks()
        with patch.object(self.link, 'set_group', wraps=self.link.set_group) as setting:
            result = self.run_action('finalize', {'groups': {g: self.link.values[g][:] for g in SETUP_SETTINGS}})
        self.assertTrue(result['complete']); setting.assert_not_called()

    def test_entering_again_locks_and_preserves_valid_checks(self):
        self.complete()
        checks = self.link.read_group(130)[3:8]
        result = self.run_action('begin')
        self.assertEqual(result['values'][130][:2], [True, False])
        self.assertEqual(result['values'][130][3:8], checks)
        self.link.demo_restart()
        self.assertTrue(self.link.read_group(130)[0])
        self.assertEqual(self.link.read_group(130)[3:8], checks)

    def test_save_failure_cannot_unlock_and_reports_partial_section(self):
        self.prepare(); self.motor_checks()
        values = self.link.values[2][:]; values[0] += .1
        with patch.object(self.link, 'save_group', side_effect=RuntimeError('NVS rejected')):
            result = self.run_action('finalize', {'groups': {2: values}})
        self.assertFalse(result['complete'])
        self.assertEqual(result['sections'][2]['stage'], 'save_sent')
        self.assertIn('NVS rejected', result['error'])
        self.assertTrue(self.link.read_group(130)[0])

    def test_cancellation_between_set_and_save_does_not_finalize(self):
        self.run_action('begin')
        flag = [False]
        setting = self.link.set_group
        def cancelled_set(*args, **kwargs):
            result = setting(*args, **kwargs); flag[0] = True; return result
        values = self.link.values[2][:]; values[0] += .1
        with patch.object(self.link, 'set_group', side_effect=cancelled_set), patch.object(self.link, 'save_group') as save:
            result = run_setup_action(self.link, 'finalize', {'groups': {2: values}}, lambda: flag[0])
        self.assertFalse(result['complete']); save.assert_not_called()
        self.assertTrue(self.link.read_group(130)[0])

    def test_esc_waits_for_restart_then_is_consumed_once(self):
        self.prepare()
        self.command('ESC_SCHEDULE')
        self.assertEqual(self.link.read_group(130)[3], 1)
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[3], 2)
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [2000.] * 4)
        self.clock.advance(3.1)
        self.assertEqual(self.link.read_group(130)[2], 4)
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.clock.advance(3)
        self.assertEqual(self.link.read_group(130)[3], 3)
        self.assertFalse(self.link.read_group(120)[2])
        with self.assertRaisesRegex(ValueError, 'CALIBRATION_BUSY'):
            self.command('ESC_VERIFY')
        self.clock.advance(3.6)
        self.assertTrue(self.link.read_group(120)[2])
        self.command('ESC_VERIFY')
        self.assertEqual(self.link.read_group(130)[3], 4)
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.assertTrue(self.link.read_group(130)[0])

    def test_stop_waits_for_automatic_imu_recovery_without_replaying_high(self):
        self.prepare(); self.command('ESC_SCHEDULE'); self.link.demo_restart()
        self.command('STOP', [0, 0, 0, 0])
        for name,args in [('ESC_SKIP',[1,0,0,0]),('MOTOR_START',[1,1,0,0]),('ESC_SCHEDULE',[1,0,0,0])]:
            with self.assertRaisesRegex(ValueError,'CALIBRATION_BUSY'):self.command(name,args)
        self.assertEqual(self.link.read_group(23,schema=2)[3:7],[1000.]*4)
        self.clock.advance(3.6)
        self.assertTrue(self.link.read_group(120)[2])
        self.assertEqual(self.link.read_group(130)[3],6)
        self.command('ESC_SKIP');self.command('MOTOR_START',[1,1,0,0])
        self.assertTrue(self.link.read_group(130)[0])

    def test_late_motor_set_and_reschedule_do_not_change_calibration_output(self):
        self.prepare();self.command('ESC_SCHEDULE');self.link.demo_restart()
        for name,args in [('MOTOR_SET',[1,1200,0,0]),('ESC_SCHEDULE',[1,0,0,0]),('ESC_SKIP',[1,0,0,0])]:
            with self.assertRaisesRegex(ValueError,'CALIBRATION_BUSY'):self.command(name,args)
            self.assertEqual(self.link.read_group(130)[3],2)
            self.assertEqual(self.link.read_group(23,schema=2)[3:7],[2000.]*4)
        self.clock.advance(6.1);self.link.read_group(130)
        with self.assertRaisesRegex(ValueError,'CALIBRATION_BUSY'):self.command('ESC_SCHEDULE')
        self.clock.advance(1.5)
        status=self.link.read_group(120)
        self.assertFalse(status[2]);self.assertGreater(status[5],0)
        self.assertEqual(self.link.read_group(23,schema=2)[3:7],[1000.]*4)

    def test_failed_begin_cannot_be_mistaken_for_persisted_lock_on_resume(self):
        self.complete(digital=True)
        original = self.link._persist
        def failed_persist():
            self.link.storage_available = False
            return original()
        with patch.object(self.link, '_persist', side_effect=failed_persist):
            with self.assertRaisesRegex(RuntimeError, 'STORAGE_FAILURE'):
                self.run_action('begin')
        self.link.storage_available = True
        self.assertTrue(self.link.read_group(130)[0])
        self.assertFalse(self.link.read_group(120)[7])
        with self.assertRaisesRegex(RuntimeError, 'cannot be confirmed'):
            self.run_action('begin')
        self.link.demo_restart()
        self.assertTrue(self.run_action('begin')['complete'])

    def test_generic_timeout_fault_does_not_prevent_healthy_lock_resume(self):
        self.prepare(); self.command('MOTOR_START', [1, 1, 0, 0])
        self.clock.advance(.351)
        self.assertIn('TIMEOUT', self.link.read_group(130)[14])
        self.assertTrue(self.run_action('begin')['resumed'])

    def test_reconnect_begin_does_not_cancel_pending_or_running_esc(self):
        self.prepare(); self.command('ESC_SCHEDULE')
        for restart in (False, True):
            if restart: self.link.demo_restart()
            before = self.link.read_group(130)[3]
            with patch.object(self.link, 'disarm', wraps=self.link.disarm) as disarm:
                result = self.run_action('begin')
            disarm.assert_not_called(); self.assertTrue(result['resumed'])
            self.assertEqual(result['values'][130][3], before)

    def test_interrupted_esc_never_replays_maximum(self):
        self.prepare(); self.command('ESC_SCHEDULE'); self.link.demo_restart()
        self.clock.advance(1); self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[3], 6)
        self.assertIn('INTERRUPTED', self.link.read_group(130)[14])
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.link.demo_restart()
        self.assertEqual(self.link.read_group(130)[3], 6)

    def test_esc_consume_storage_failure_prevents_high_output(self):
        self.prepare(); self.command('ESC_SCHEDULE'); self.link.storage_available = False
        with self.assertRaisesRegex(RuntimeError, 'STORAGE_FAILURE'): self.link.demo_restart()
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.assertTrue(self.link.read_group(130)[0])

    def test_explicit_disarm_cancels_esc_and_keeps_lock(self):
        self.prepare(); self.command('ESC_SCHEDULE'); self.link.demo_restart()
        self.link.disarm()
        self.assertEqual(self.link.read_group(130)[3], 6)
        self.assertEqual(self.link.read_group(23, schema=2)[3:7], [1000.] * 4)
        self.assertTrue(self.link.read_group(130)[0])

    def test_motor_watchdog_and_owner_change_stop_output(self):
        self.prepare()
        self.command('MOTOR_START', [1, 1, 0, 0]); self.command('MOTOR_SET', [1, 1200, 0, 0])
        self.assertEqual(self.link.read_group(130)[9:13], [1200, 1000, 1000, 1000])
        self.clock.advance(.351)
        self.assertFalse(self.link.read_group(130)[8])
        with self.assertRaises(ValueError): self.command('MOTOR_SET', [1, 1200, 0, 0])
        self.command('MOTOR_START', [15, 1, 0, 0]); self.link.session += 1
        self.assertFalse(self.link.read_group(130)[8])

    def test_motor_absolute_timeout_despite_heartbeats(self):
        self.prepare(); self.command('MOTOR_START', [15, 1, 0, 0])
        for _ in range(149):
            self.clock.advance(.2); self.command('MOTOR_SET', [15, 1200, 0, 0])
        self.clock.advance(.21)
        self.assertFalse(self.link.read_group(130)[8])

    def test_motor_verification_requires_real_test_session_and_stop(self):
        self.prepare()
        with self.assertRaises(ValueError): self.command('MOTOR_OK', [15, 1, 0, 0])
        self.command('MOTOR_START', [1, 1, 0, 0]); self.command('MOTOR_SET', [1, 1150, 0, 0])
        with self.assertRaises(ValueError): self.command('MOTOR_OK', [1, 1, 0, 0])
        self.command('MOTOR_STOP', [0, 0, 0, 0]); self.command('MOTOR_OK', [1, 1, 0, 0])
        self.assertEqual(self.link.read_group(130)[4], 1)
        with self.assertRaises(ValueError): self.run_action('finalize')

    def test_close_and_disarm_stop_motor_without_unlock(self):
        self.prepare(); self.command('MOTOR_START', [15, 1, 0, 0]); self.command('MOTOR_SET', [15, 1200, 0, 0])
        self.link.close()
        self.assertFalse(self.link.read_group(130)[8]); self.assertTrue(self.link.read_group(130)[0])

    def test_raw_receiver_visible_before_neutral_and_reversal_normalizes(self):
        self.run_action('begin')
        self.link.demo_set_receiver([1500, 1500, 2000, 2000, 1000, 1000, 1000, 1000])
        self.assertEqual(self.link.read_group(131)[:4], [1500, 1500, 2000, 2000])
        with self.assertRaisesRegex(ValueError, 'NEUTRAL'): self.command('RX_OK')
        calibration = self.link.values[132][:]; calibration[3] = 1
        self.run_action('apply_save', {'groups': {132: calibration}})
        self.link.demo_set_receiver([2000, 1500, 1000, 1500, 1000, 1000, 1000, 1000])
        self.assertEqual(self.link.read_group(22)[0], 1000)
        self.link.demo_set_receiver(fresh=False)
        self.assertEqual(self.link.read_group(131)[:8], [0] * 8)

    def test_failsafe_confirmation_requires_observed_ppm_loss(self):
        self.run_action('begin')
        with self.assertRaisesRegex(ValueError, 'LOSS_NOT_OBSERVED'): self.command('FAILSAFE_OK')
        self.link.demo_set_receiver(fresh=False); self.link.demo_set_receiver(fresh=True)
        self.command('FAILSAFE_OK'); self.assertTrue(self.link.read_group(130)[7])

    def test_changed_offsets_and_receiver_clear_dependent_proofs(self):
        self.prepare(); self.motor_checks()
        values = self.link.values[6][:]; values[0] += .01
        self.run_action('apply_save', {'groups': {6: values}})
        self.assertFalse(self.link.read_group(130)[5])
        calibration = self.link.values[132][:]; calibration[0] = 990
        self.run_action('apply_save', {'groups': {132: calibration}})
        self.assertEqual(self.link.read_group(130)[6:8], [False, False])

    def test_changed_motor_idle_requires_confirmation_but_retains_stopped_test(self):
        self.prepare(); self.motor_checks()
        config = self.link.values[134][:]; config[8] = 1150
        self.run_action('apply_save', {'groups': {134: config}})
        self.assertEqual(self.link.read_group(130)[4], 13)
        self.command('MOTOR_OK', [2, 1, 0, 0])
        self.assertEqual(self.link.read_group(130)[4], 15)

    def test_runtime_input_change_preserves_completion_but_requires_fresh_neutral(self):
        self.complete(digital=True)
        self.link.send_control(NEUTRAL, datagram_only=True)
        self.link.set_group(110, [2])
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        with self.assertRaisesRegex(ValueError, 'fresh neutral'):
            self.link.arm()
        self.link.send_control(NEUTRAL, serial_only=True); self.link.arm()
        self.assertTrue(self.link.armed)

    def test_demo_results_and_restart_never_accepted_as_real(self):
        self.run_action('begin'); self.link.demo = False
        with self.assertRaisesRegex(ValueError, 'Demo-derived'):
            self.run_action('apply_save', {'groups': {6: self.link.values[6][:]}, 'acc_origin': 'demo_candidate'})
        with self.assertRaises(RuntimeError): self.run_action('demo_restart')

    def test_command_validation_rejects_bool_and_finalize_shortcut(self):
        self.run_action('begin')
        with self.assertRaises(ValueError): self.command('MOTOR_SET', [1, True, 0, 0])
        with self.assertRaises(ValueError): self.command('FINALIZE', [0, 0, 0, 0])

    def test_mutating_settings_after_completion_relocks(self):
        self.complete(digital=True)
        values = self.link.values[4][:]; values[4] = 6
        self.link.set_group(4, values, schema=2)
        self.assertTrue(self.link.read_group(130)[0]); self.assertFalse(self.link.read_group(130)[1])
        self.link.demo_restart(); self.assertTrue(self.link.read_group(130)[0])

    def test_open_link_rejects_old_firmware_and_reads_setup(self):
        options = {'mode': 'AP', 'ssid': 'aerion drone', 'host': '192.168.4.1', 'udp_port': 8080}
        for version in ('2.5.0', '3.1.0'):
            demo = self.link
            def read(group, schema=1):
                values = demo.read_group(group, schema)
                if group == 125: values[0] = version
                return values
            link = Mock(read_group=Mock(side_effect=read))
            with patch('areion_gui.backend.UDP', return_value=Mock(datagram=True)), patch('areion_gui.backend.check_wifi', return_value=None), patch('areion_gui.backend.Link', return_value=link):
                if version == '2.5.0':
                    with self.assertRaisesRegex(RuntimeError, 'setup ARM lock'): open_link(options, threading.Event())
                else:
                    result = open_link(options, threading.Event())
                    self.assertIn(130, result[1]); self.assertIn(132, result[1]); self.assertIn(134, result[1])
                link.arm.assert_not_called(); link.set_group.assert_not_called()


if __name__ == '__main__': unittest.main()
