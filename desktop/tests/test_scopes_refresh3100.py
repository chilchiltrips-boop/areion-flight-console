import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui import scopes_page
from areion_gui.model import DRONE_GROUPS, Telemetry


class ScopesRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = scopes_page.ScopesPage()
        self.page.show()
        self.app.processEvents()
        self.addCleanup(self.page.close)
        self.data = Telemetry()

    def imu(self, index):
        self.assertTrue(self.data.put(21, DRONE_GROUPS[21]['schema'], [0.] * 10,
                                      now=10 + index * .075))

    def test_spectrum_waits_for_samples_and_reuses_bins_between_packets(self):
        self.imu(0)
        self.page.refresh(self.data, 10., True, (1, 1))
        self.page.view_tabs.setCurrentIndex(2)
        self.assertEqual(self.page.status_label.text(), 'WAITING')
        self.page.refresh(self.data, 10., True, (1, 1))
        self.assertEqual(self.page.status_label.text(), 'WAITING')
        for index in range(1, 64):
            self.imu(index)
        ts = 10 + 63 * .075
        self.page.refresh(self.data, ts, True, (1, 1))
        self.assertEqual(self.page.status_label.text(), 'LIVE')
        plot = self.page.plots['spectrum_acc']
        with patch.object(plot, 'set_data', wraps=plot.set_data) as draw:
            self.page.refresh(self.data, ts + .12, True, (1, 1))
            draw.assert_not_called()
            self.page.refresh(self.data, ts + 1., True, (1, 1))
            draw.assert_called_once()
        self.assertEqual(self.page.status_label.text(), 'STALE')
        self.assertFalse(any(series.runs for series in plot.traces))

    def test_hidden_view_postpones_analysis_until_shown(self):
        for i in range(64):
            self.imu(i)
        self.page.hide()
        with patch.object(scopes_page, 'imu_spectra', wraps=scopes_page.imu_spectra) as analyze:
            self.page.view_tabs.setCurrentIndex(2)
            self.page.refresh(self.data, 10 + 63 * .075, True, (1, 1))
            analyze.assert_not_called()
            self.page.show()
            self.app.processEvents()
            analyze.assert_called_once()
        self.assertEqual(self.page.status_label.text(), 'LIVE')

    def test_frozen_accessors_share_display_time_and_release_on_kit_switch(self):
        self.imu(0)
        self.page.refresh(self.data, 10.15, True, (1, 1))
        self.page.freeze_button.click()
        self.assertAlmostEqual(self.page.display_data.age(21), .15)
        self.assertEqual(self.page.display_data.now, self.page.display_time)
        self.page.refresh(self.data, 15., True, (1, 1))
        self.assertAlmostEqual(self.page.display_data.age(21), .15)
        self.page.refresh(Telemetry(), 15., True, (2, 1))
        self.assertFalse(self.page.frozen)
        self.assertFalse(self.page.freeze_button.isChecked())
        self.assertFalse(self.page.freeze_button.isEnabled())
        self.assertEqual(self.page.status_label.text(), 'WAITING')

    def test_freeze_includes_packet_received_after_last_display_refresh(self):
        self.imu(0)
        self.page.refresh(self.data, 10.01, True, (1, 1))
        self.imu(1)
        self.page.freeze_button.click()
        self.assertEqual(self.page.display_time, 10.075)
        self.assertEqual(self.page.display_data.age(21), 0.)
        self.assertEqual(self.page.indicators['IMU'].property('tone'), 'Live')
        trace = self.page.plots['gyro'].traces[0]
        self.assertEqual(trace.runs[-1][-1][0], 10.075)
