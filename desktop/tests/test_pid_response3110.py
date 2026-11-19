import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui.model import Telemetry
from areion_gui.pid_response import PidResponse


class PidResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.data = Telemetry()
        self.panel = PidResponse()
        self.panel.resize(350, 210)
        self.panel.show()
        self.app.processEvents()
        self.addCleanup(self.panel.close)

    def status(self, t, angle, sensor=True):
        self.setup_state(t, locked=False)
        row = [False, angle, sensor, 8, .004, 2000, 40, True, True, True]
        self.assertTrue(self.data.put(120, 1, row, now=t))

    def setup_state(self, t, locked):
        row = [locked, not locked, 0, 0, 15, True, True, False, False, 1000, 1000, 1000, 1000, 1, '', 'Kit']
        self.assertTrue(self.data.put(130, 1, row, now=t))

    def observation(self, t):
        self.assertTrue(self.data.put(21, 1, [2., 3., 5., 0., 0., 1., 6., 7., 11., 13.], now=t))

    def command(self, t, delta=0):
        row = [0., 0., 0., 1000., 1000., 1000., 1000., 17., 19., 23., 29.+delta, 31.+delta]
        self.assertTrue(self.data.put(23, 2, row, now=t))

    def refresh(self, now, identity=1):
        self.panel.refresh(self.data, now, True, identity)

    def trace(self, name):
        return next(trace for trace in self.panel.plot.traces if trace.name == name)

    def test_independent_packet_times_and_all_rate_channels(self):
        self.status(10., True)
        self.observation(10.045)
        self.command(10.09)
        self.refresh(10.1)
        for idx, (observed, target) in enumerate(((2.,17.),(3.,19.),(5.,23.))):
            self.panel.axis_tabs.setCurrentIndex(idx)
            self.assertEqual(self.trace('Measured').runs[0][-1], (10.045, observed))
            self.assertEqual(self.trace('Target').runs[0][-1], (10.09, target))
            self.assertEqual(self.panel.plot.buttons['Target'].text(), f'Target  {target:+.1f}')
            self.assertEqual(self.panel.plot.unit, '°/s')

    def test_angle_fields_use_kalman_and_require_angle_at_target_time(self):
        self.status(1., True)
        self.observation(1.02)
        self.command(1.03)
        self.status(1.07, False)
        self.command(1.08, 100.)
        self.refresh(1.09)
        self.panel.axis_tabs.setCurrentIndex(2)
        self.panel.loop_tabs.setCurrentIndex(1)
        self.assertFalse(self.panel.axis_tabs.isTabEnabled(2))
        self.assertEqual(self.panel.axis_tabs.currentIndex(), 0)
        self.assertEqual(self.panel.plot.unit, '°')
        self.assertEqual(self.trace('Kalman').runs[0][-1], (1.02, 11.))
        self.assertEqual(self.trace('Target').runs[0][-1], (1.03, 29.))
        self.assertEqual(self.panel.plot.state, 'Rate mode')
        self.assertIn('—', self.panel.plot.buttons['Target'].text())
        self.status(1.17, True)
        self.refresh(1.18)
        self.assertEqual(self.panel.plot.state, 'Waiting')
        self.command(1.20, 1.)
        self.refresh(1.21)
        self.panel.axis_tabs.setCurrentIndex(1)
        self.assertEqual(self.trace('Kalman').runs[0][-1], (1.02, 13.))
        self.assertEqual([run[-1] for run in self.trace('Target').runs], [(1.03, 31.), (1.20, 32.)])
        self.assertEqual(self.panel.plot.state, 'Live')
        self.panel.loop_tabs.setCurrentIndex(0)
        self.assertTrue(self.panel.axis_tabs.isTabEnabled(2))

    def test_mode_exited_and_reentered_between_target_packets_breaks_trace(self):
        self.status(1., True)
        self.command(1.01)
        self.status(1.05, False)
        self.status(1.08, True)
        self.command(1.1, 20.)
        self.refresh(1.11)
        self.panel.loop_tabs.setCurrentIndex(1)
        self.assertEqual([len(run) for run in self.trace('Target').runs], [1, 1])

    def test_stale_imu_clears_live_value_without_losing_latest_target(self):
        self.status(10., True)
        self.observation(10.01)
        self.status(10.47, True)
        self.command(10.51)
        self.refresh(10.55)
        self.assertEqual(self.panel.plot.state, 'Stale')
        self.assertIn('—', self.panel.plot.buttons['Measured'].text())
        self.assertIn('+17.0', self.panel.plot.buttons['Target'].text())
        self.assertTrue(self.trace('Measured').runs)
        self.refresh(21.)
        self.assertFalse(self.trace('Target').runs)
        self.panel.refresh(self.data, 22., False)
        self.assertEqual(self.panel.plot.state, 'Offline')

    def test_inactive_workspace_skips_plot_generation_and_preserves_received_history(self):
        self.panel.hide()
        self.status(3., False)
        self.observation(3.)
        self.command(3.05)
        with patch.object(self.panel.plot, 'set_data', wraps=self.panel.plot.set_data) as write:
            self.refresh(3.1)
            self.panel.axis_tabs.setCurrentIndex(1)
            write.assert_not_called()
            self.panel.show()
            write.assert_called_once()
            self.refresh(3.12)
            self.assertEqual(write.call_count, 1)
        self.assertEqual(self.trace('Measured').runs[0][-1], (3., 3.))

    def test_new_session_clears_old_data_even_if_telemetry_instance_reused(self):
        self.status(7., False)
        self.observation(7.0)
        self.command(7.1)
        self.refresh(7.11)
        self.refresh(7.12, 2)
        self.assertFalse(any(trace.runs for trace in self.panel.plot.traces))
        self.status(7.125, True)
        self.observation(7.13)
        self.command(7.14)
        self.refresh(7.15, 2)
        self.assertEqual(self.trace('Target').runs[0], [(7.14, 17.)])

    def test_setup_lock_and_imu_fault_suppress_reported_targets_until_new_packet(self):
        self.status(20., True)
        self.observation(20.01)
        self.command(20.02)
        self.setup_state(20.04, True)
        self.command(20.06, 5.)
        self.refresh(20.08)
        self.assertEqual(self.panel.plot.state, 'Setup lock')
        self.assertEqual(self.trace('Target').runs, [[(20.02, 17.)]])
        self.assertEqual(self.trace('Measured').runs, [[(20.01, 2.)]])
        self.assertIn('—', self.panel.plot.buttons['Target'].text())
        self.setup_state(20.09, False)
        self.refresh(20.10)
        self.assertEqual(self.panel.plot.state, 'Waiting')
        self.status(20.12, True, sensor=False)
        self.command(20.14)
        self.refresh(20.16)
        self.assertEqual(self.panel.plot.state, 'Invalid')
        self.assertEqual(self.trace('Target').runs, [[(20.02, 17.)]])
        self.status(20.17, True)
        self.observation(20.19)
        self.command(20.2)
        self.refresh(20.22)
        self.assertEqual(self.panel.plot.state, 'Live')
        self.assertEqual(len(self.trace('Target').runs), 2)
