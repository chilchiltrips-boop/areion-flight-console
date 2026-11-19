"""Exercise the desktop Scopes page with real SDK receive queues and Qt controls."""
import csv
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.window import MainWindow
from fc_fixture import DemoLink
from test_actions_sdk import connected_link
from zebjus_areion_link import Message
from zebjus_areion_link.schema import DRONE_GROUPS


class ScopesWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=folder.name):
            self.w = MainWindow()
        self.w.timer.stop()
        self.w.resize(1280, 800)
        self.w.show()
        self.app.processEvents()
        self.link, self.usb, self.ap = connected_link()
        self.link.health_timeout = 30
        self.w.link = self.link
        self.p = self.w.scopes_page
        self.seq = 0
        self.addCleanup(self.close)

    def close(self):
        self.w.link = self.w.session = None
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def click_nav(self, index):
        button = self.w.nav[self.w.nav_routes.index(index)]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.pages.currentIndex(), index)

    def select_view(self, view):
        tabs = self.p.view_tabs
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(view).center())
        self.assertEqual(tabs.currentIndex(), view)

    def packet(self, group, values, when):
        self.seq += 1
        event = Message('DATA', group, DRONE_GROUPS[group]['schema'], self.link.fc_session, self.seq, tuple(values))
        self.link._handle(self.link._paths[0], event, when)

    def feed_motion(self, *, end, count=128, frequency=5/3):
        # Firmware 3.2 emits IMU in slots 2 and 4 of six 25 ms slots.
        stamps = [0.]
        for i in range(1, count):
            stamps.append(stamps[-1] + (.05 if i % 2 else .10))
        latest = stamps[-1]
        self.packet(120, [False,True,True,8,.004,2000,100,True,True,True], end)
        for offset in stamps:
            wave = math.sin(2 * math.pi * frequency * offset)
            self.packet(21, [23.*wave, 2.*wave, -8.*wave, .21*wave, .04*wave, 1., 2.*wave, -2.*wave, wave, -wave],
                        end - latest + offset)
        # Each tick drains a bounded number of SDK events.
        for _ in range(count // 64 + 2):
            self.w.tick()

    def refresh(self, when):
        self.w.render_status(when)
        self.app.processEvents()

    def active_names(self):
        return {name for name, plot in self.p.plots.items() if plot.isVisibleTo(self.w)}

    def test_layouts_open_from_top_navigation_and_fit_small_desktop(self):
        self.click_nav(8)
        for size in ((900,700), (1280,800)):
            self.w.resize(*size)
            for view, expected in enumerate(({'gyro','acc','roll','pitch'},
                                             {'rate_roll','rate_pitch','rate_yaw','motors'},
                                             {'spectrum_acc','spectrum_gyro'}, set())):
                with self.subTest(size=size, view=view):
                    self.select_view(view)
                    self.app.processEvents()
                    self.assertEqual(self.active_names(), expected)
                    widgets = [self.p.view_tabs, self.p.freeze_button, self.p.window_combo,
                               *(self.p.plots[key] for key in expected)]
                    if view == 3:
                        widgets.append(self.p.receiver)
                    for widget in widgets:
                        if not widget.isVisibleTo(self.w):
                            continue
                        bounds = QRect(widget.mapTo(self.w,QPoint()), widget.size())
                        self.assertTrue(self.w.rect().contains(bounds), (widget, bounds, size))

    def test_fft_uses_received_imu_rate_and_excludes_the_control_loop_rate(self):
        now = time.monotonic()
        self.feed_motion(end=now)
        self.click_nav(8)
        self.select_view(2)
        self.refresh(now + .09)
        for key in ('spectrum_gyro','spectrum_acc'):
            plot = self.p.plots[key]
            with self.subTest(key=key):
                self.assertGreater(len(plot.traces), 1, (plot.state, plot.detail))
                self.assertAlmostEqual(plot.x_range[1], 6.667, delta=.3)
                peaks = [t.peak for t in plot.traces if t.peak]
                self.assertTrue(any(abs(hz-5/3) < .18 for hz,_ in peaks), peaks)
        self.assertFalse(self.usb.sent or self.ap.sent)

    def test_frozen_trace_and_time_hold_but_new_samples_are_retained(self):
        now = time.monotonic()
        self.feed_motion(end=now, count=65)
        self.click_nav(8)
        self.refresh(now)
        self.assertTrue(self.p.freeze_button.isEnabled())
        self.p.freeze_button.click()
        self.assertTrue(self.p.frozen)
        captured_at = self.p.display_time
        before = [list(trace.runs[-1]) for trace in self.p.plots['gyro'].traces if trace.runs]
        self.assertTrue(before)
        next_stamp = max(now,captured_at) + .12
        self.packet(21,[76.,2.,3.,0.,0.,1.,0.,0.,0.,0.],next_stamp)
        self.w.tick()
        self.refresh(next_stamp + .02)
        self.assertEqual(self.p.display_time,captured_at)
        self.assertEqual([list(t.runs[-1]) for t in self.p.plots['gyro'].traces if t.runs],before)
        self.p.freeze_button.click()
        self.refresh(next_stamp + .14)
        self.assertFalse(self.p.frozen)
        self.assertTrue(any(t.runs and t.runs[-1][-1][1] == 76. for t in self.p.plots['gyro'].traces))

    def test_receiver_accepted_and_raw_are_independent_and_expire(self):
        self.click_nav(8)
        self.select_view(3)
        now = time.monotonic()
        self.packet(122,[0,1,True,False,True,4,10,42,False], now-.06)
        self.packet(22,[1510,1490,1001,1501,2000,1000,1780,1130], now-.04)
        self.packet(131,[1600,1400,1000,1540,1770,0,0,0,5,True,5], now)
        self.w.tick()
        self.refresh(now + .09)
        rx = self.p.receiver
        self.assertEqual([b.value for b in rx.bars], [1510,1490,1001,1501,None,None,None,None])
        rx.raw_button.click()
        self.refresh(now + .15)
        self.assertEqual([b.value for b in rx.bars], [1600,1400,1000,1540,1770,None,None,None])
        self.refresh(now + 2)
        self.assertTrue(all(b.value is None for b in rx.bars))
        self.assertFalse(self.usb.sent or self.ap.sent)

    def test_control_curves_and_session_export_keep_distinct_received_values(self):
        now = time.monotonic()
        self.click_nav(8)
        self.select_view(1)
        self.packet(120, [False, True, True, 8, .004, 2000, 100, True, True, True], now - .08)
        self.packet(21, [13., -8., 7., .1, 0., 1., 4., -3., 2., -1.], now - .05)
        control = [2., 3., 4., 1100., 1200., 1300., 1400., 41., -29., 17., .1, -.2]
        self.packet(23, control, now - .02)
        self.w.tick()
        self.refresh(now)
        def values(panel):
            return {trace.name: trace.runs[-1][-1][1] for trace in self.p.plots[panel].traces if trace.runs}
        for panel, measured, target in (('rate_roll', 13., 41.), ('rate_pitch', -8., -29.), ('rate_yaw', 7., 17.)):
            self.assertEqual(values(panel), {'Measured': measured, 'Target': target})
        self.assertEqual(values('motors'), {'M1': 1100., 'M2': 1200., 'M3': 1300., 'M4': 1400.})
        self.p.freeze_button.click()
        control[3] = 1175.
        self.packet(23, control, now + .06)
        self.w.tick()
        self.refresh(now + .12)
        self.assertEqual(values('motors')['M1'], 1100.)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'scope.csv')
            with patch('areion_gui.window.QFileDialog.getSaveFileName', return_value=(str(path), 'CSV')):
                self.p.export_button.click()
            with path.open(encoding='utf-8', newline='') as stream:
                rows = [row for row in csv.DictReader(stream) if row['group'] == '23']
        self.assertEqual([json.loads(row['values_json'])[3] for row in rows], [1100., 1175.])
        self.assertFalse(self.usb.sent or self.ap.sent)

    def test_plot_inspection_is_local_and_active_sender_uses_existing_navigation_stop(self):
        self.feed_motion(end=time.monotonic(), count=65)
        self.click_nav(8)
        self.refresh(time.monotonic())
        plot = self.p.plots['gyro']
        visible = next(iter(plot.buttons.values()))
        visible.click()
        self.assertFalse(visible.isChecked())
        QTest.mouseMove(plot.canvas,plot.canvas.rect().center())
        self.p.window_combo.setCurrentIndex(self.p.window_combo.findData(5))
        self.p.freeze_button.click(); self.p.freeze_button.click()
        self.select_view(2); self.select_view(3)
        self.assertFalse(self.usb.sent or self.ap.sent)
        # The top route retains the same stop operation as leaving Flight Data
        # for any other page during active transmission.
        self.click_nav(0)
        with patch.object(self.w,'_running',return_value=True), patch.object(self.w,'stop') as stop:
            self.click_nav(8)
            stop.assert_called_once()

    def test_connection_discard_does_not_show_previous_receiver_or_spectrum(self):
        self.feed_motion(end=time.monotonic(), count=128)
        self.click_nav(8)
        self.p.freeze_button.click()
        self.assertTrue(self.p.frozen)
        self.w.disconnect()
        self.w.render_status(time.monotonic())
        # New USB/AP connections install a fresh Telemetry instance.
        self.link, _, _ = connected_link()
        self.link.fc_session = 875123
        kit = DemoLink()
        groups = (120,122,121,125,110,130,131,132,134,136)
        with patch.object(self.w,'settings_request'):
            self.w.install_link(self.link,{g:kit.read_group(g, DRONE_GROUPS[g]['schema']) for g in groups})
        self.select_view(2)
        self.refresh(time.monotonic())
        self.assertFalse(self.p.frozen)
        for key in ('spectrum_acc','spectrum_gyro'):
            self.assertFalse(any(t.runs for t in self.p.plots[key].traces))
        self.assertFalse(self.w.data.history.get((21,0)))


if __name__ == '__main__':
    unittest.main()
