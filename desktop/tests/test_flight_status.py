import math
import unittest

from areion_gui.flight_status import flight_status, KEYS


def readings():
    return {
        120: [False, True, True, 8, .004, 2000, 100, True, True, True],
        122: [0, 1, True, False, True, 8, 0, 1, False],
        125: ['3.1.0', 250, 18, 0, 1, 2, 21, 250, 12, 1024, 2048, 50],
        130: [False, True, 0, 5, 15, True, True, False, False, 1000, 1000, 1000, 1000, 1, '', 'test'],
        21: [0., 0., 0., 0., 0., 1., 0., 0., 0., 0.],
        23: [0., 0., 0., 1000., 1000., 1000., 1000., 0., 0., 0., 0., 0.],
        110: [0],
    }


class FlightStatusTests(unittest.TestCase):
    def test_fresh_signals_and_commands_have_distinct_qualified_labels(self):
        tiles = flight_status(readings(), True)
        self.assertEqual(tuple(tiles), KEYS)
        for key in ('TELEMETRY', 'INPUT', 'PPM', 'IMU', 'OUTPUT', 'CONFIG', 'LOOP', 'MODE', 'STORAGE'):
            self.assertEqual(tiles[key].state, 'green', key)
        self.assertEqual(tiles['OUTPUT'].label, 'MINIMUM')
        self.assertIn('does not measure rotation', tiles['OUTPUT'].detail)
        self.assertIn('electrical bus integrity is not measured', tiles['IMU'].detail)
        self.assertEqual(tiles['ARM'].label, 'DISARMED')
        self.assertEqual(tiles['AP'].state, 'gray')

    def test_selected_missing_signal_and_neutral_gate_are_amber(self):
        groups = readings();groups[122] = [1, 0, False, False, False, 0, 999, 1, False]
        tiles = flight_status(groups, True)
        self.assertEqual(tiles['INPUT'].state, 'amber')
        self.assertEqual(tiles['AP'].state, 'amber')
        groups[122] = [1, 0, False, True, False, 8, 5, 1, False]
        self.assertEqual(flight_status(groups, True)['INPUT'].label, 'NEUTRAL')
        self.assertEqual(flight_status(groups, True)['AP'].state, 'green')

    def test_usb_signal_uses_its_own_freshness_and_active_id(self):
        groups = readings();groups[122] = [2, 3, False, False, True, 8, 0, 1, True]
        tiles = flight_status(groups, True)
        self.assertEqual(tiles['USB'].state, 'green')
        self.assertEqual(tiles['INPUT'].label, 'USB LIVE')
        groups[122][1] = 2
        self.assertEqual(flight_status(groups, True)['INPUT'].state, 'red')
        self.assertEqual(flight_status(groups, True)['MODE'].state, 'amber')

    def test_offline_cannot_reuse_any_green_telemetry(self):
        tiles = flight_status(readings(), False)
        self.assertFalse(any(item.state == 'green' for item in tiles.values()))
        self.assertEqual(tiles['TELEMETRY'].state, 'red')
        self.assertEqual(tiles['PPM'].state, 'amber')

    def test_stale_groups_are_waiting_even_with_cached_configuration(self):
        groups = readings()
        for group in (120, 122, 21, 23): groups[group] = None
        tiles = flight_status(groups, True)
        for key in ('TELEMETRY', 'INPUT', 'PPM', 'IMU', 'OUTPUT', 'LOOP'):
            self.assertEqual(tiles[key].state, 'amber', key)
        self.assertEqual(tiles['OUTPUT'].label, 'READY')
        self.assertEqual(tiles['ARM'].state, 'amber')

    def test_malformed_input_and_nonfinite_values_are_not_green(self):
        groups = readings();groups[122][0] = True
        self.assertEqual(flight_status(groups, True)['INPUT'].state, 'red')
        groups = readings();groups[21][3] = math.nan
        self.assertEqual(flight_status(groups, True)['IMU'].state, 'red')
        groups = readings();groups[23][4] = math.inf
        self.assertEqual(flight_status(groups, True)['OUTPUT'].state, 'red')
        groups = readings();groups[120][4] = math.nan
        self.assertEqual(flight_status(groups, True)['TELEMETRY'].state, 'red')
        self.assertEqual(flight_status(groups, True)['ARM'].state, 'red')

    def test_sensor_read_fault_and_storage_fault_remain_red(self):
        groups = readings();groups[120][2] = False;groups[120][7] = False
        tiles = flight_status(groups, True)
        self.assertEqual(tiles['IMU'].state, 'red')
        self.assertEqual(tiles['STORAGE'].state, 'red')

    def test_loop_target_and_reported_interval_are_not_cpu_load(self):
        groups = readings();groups[120][4] = .006
        self.assertEqual(flight_status(groups, True)['LOOP'].state, 'amber')
        groups[120][4] = .02
        self.assertEqual(flight_status(groups, True)['LOOP'].state, 'red')
        groups[120][4] = .004;groups[125] = None
        self.assertEqual(flight_status(groups, True)['LOOP'].state, 'amber')
        self.assertIn('not CPU load', flight_status(groups, True)['LOOP'].detail)

    def test_setup_pending_fault_and_locked_state(self):
        groups = readings();groups[130][:2] = [True, False]
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'amber')
        groups[130][14] = 'STORAGE_FAILED'
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'red')
        groups = readings();groups[130][:2] = [True, True]
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'amber')
        self.assertEqual(flight_status(groups, True)['MODE'].state, 'amber')

    def test_pending_pid_is_not_reported_as_saved(self):
        groups = readings();groups[136] = [True, 4, 3, '']
        self.assertEqual(flight_status(groups, True)['CONFIG'].label, 'PID UNSAVED')
        groups[136] = [False, 4, 4, '']
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'green')
        groups[136][3] = 'SAVE_FAILED'
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'red')

    def test_spare_radio_signal_is_inactive_while_digital_input_is_used(self):
        groups = readings()
        groups[122] = [1, 2, True, True, True, 8, 5, 42, False]
        tiles = flight_status(groups, True)
        self.assertEqual(tiles['INPUT'].label, 'AP LIVE')
        self.assertEqual(tiles['PPM'].state, 'gray')
        self.assertEqual(tiles['PPM'].label, 'INACTIVE')
        self.assertEqual(tiles['USB'].state, 'gray')
        self.assertEqual(tiles['ARM'].state, 'gray')
        groups[122][7] = 0
        self.assertEqual(flight_status(groups, True)['AP'].state, 'red')

    def test_fc_frame_timeout_and_host_status_expiry_are_independent(self):
        groups = readings()
        groups[112] = [100, 450]
        groups[122][6] = 99
        self.assertEqual(flight_status(groups, True, input_age_s=.4)['PPM'].state, 'green')
        groups[122][6] = 100
        self.assertEqual(flight_status(groups, True)['INPUT'].label, 'STALE')
        groups[122] = [2, 3, True, False, True, 8, 449, 42, True]
        self.assertEqual(flight_status(groups, True, input_age_s=.5)['USB'].state, 'green')
        groups[122][6] = 450
        self.assertEqual(flight_status(groups, True)['USB'].label, 'STALE')
        groups[122][6] = 1
        for elapsed in (.501, -.05, float('nan'), float('inf'), None, True):
            with self.subTest(elapsed=elapsed):
                self.assertEqual(flight_status(groups, True, input_age_s=elapsed)['INPUT'].label, 'STALE')

    def test_armed_report_and_explicit_source_loss_are_a_fault(self):
        groups = readings()
        groups[120][0] = True
        groups[122] = [0, 0, False, False, False, 0, 0xffffffff, 1, False]
        tiles = flight_status(groups, True)
        self.assertEqual(tiles['INPUT'].state, 'red')
        self.assertEqual(tiles['PPM'].label, 'LOST')
        groups[120][0] = False
        self.assertEqual(flight_status(groups, True)['INPUT'].state, 'amber')
        groups[122][2] = True
        self.assertEqual(flight_status(groups, True)['INPUT'].label, 'CHANNELS')

    def test_calibration_and_reported_startup_fault_have_distinct_severity(self):
        groups = readings()
        groups[120][2] = False
        groups[120][5] = 0
        groups[21] = None
        self.assertEqual(flight_status(groups, True)['IMU'].state, 'amber')
        groups[130][14] = 'IMU_STARTUP_FAILED'
        self.assertEqual(flight_status(groups, True)['IMU'].state, 'red')

    def test_mode_keeps_reported_name_during_sensor_and_output_faults(self):
        groups = readings()
        groups[120][2] = False
        mode = flight_status(groups, True)['MODE']
        self.assertEqual((mode.state, mode.label), ('amber', 'ANGLE'))
        self.assertIn('IMU NO READ', mode.detail)
        groups[120][2] = True
        groups[21] = None
        self.assertIn('IMU WAITING', flight_status(groups, True)['MODE'].detail)
        groups = readings()
        groups[120][1] = False
        groups[23][4] = 2500
        mode = flight_status(groups, True)['MODE']
        self.assertEqual((mode.state, mode.label), ('amber', 'RATE'))
        self.assertIn('OUTPUT INVALID', mode.detail)
        groups[23][4] = 1000
        self.assertEqual(flight_status(groups, True)['MODE'].state, 'green')

    def test_failed_pwm_and_unconfirmed_save_are_not_healthy(self):
        groups = readings()
        groups[130][14] = 'MOTOR_OUTPUT_FAILED'
        self.assertEqual(flight_status(groups, True)['OUTPUT'].state, 'red')
        groups[130][14] = ''
        groups[136] = [False, 4, 3, '']
        self.assertEqual(flight_status(groups, True)['CONFIG'].state, 'amber')
        groups[120][7] = False
        groups[136] = [False, 4, 4, '']
        self.assertEqual(flight_status(groups, True)['CONFIG'].label, 'STORAGE')

    def test_unsupported_information_is_never_invented(self):
        tiles = flight_status({}, True)
        self.assertFalse(any(item.state == 'green' for item in tiles.values()))
        self.assertFalse({'GPS', 'BATTERY', 'ALTITUDE', 'CPU', 'RPM'} & tiles.keys())
        self.assertEqual(flight_status(None, False)['TELEMETRY'].label, 'OFFLINE')


if __name__ == '__main__':
    unittest.main()
