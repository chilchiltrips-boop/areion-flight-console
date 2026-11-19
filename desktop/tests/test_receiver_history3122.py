"""Bounded, passive diagnostic evidence for intermittent receiver warnings."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from areion_gui.model import Telemetry
from areion_gui.window import MainWindow
from test_actions_sdk import connected_link


STATUS = [False, False, True, 8, .004, 2000, 1000, True, True, True]
RX = [0, 1, True, False, True, 8, 8, 1, False]
LOST = [0, 0, False, False, False, 0, 285, 1, False]


class ReceiverHistoryTests(unittest.TestCase):
    def test_packets_between_renders_and_age_jitter(self):
        data = Telemetry()
        data.put(120, 1, STATUS, 5., received=False)
        data.put(122, 2, RX, 5.01)
        data.put(122, 2, [*RX[:6], 12, 1, False], 5.1)
        data.put(122, 2, LOST, 5.2)
        data.put(122, 2, RX, 5.21)
        result = data.receiver_health.snapshot(data, 5.4)
        self.assertEqual(result['input_report_age_ms'], 190.)
        self.assertEqual(result['fc_input_frame_age_ms'], 8)
        events = result['recent_transitions']
        self.assertEqual([row['event'] for row in events], ['fc_mode', 'fc_input', 'fc_input', 'fc_input'])
        self.assertEqual(events[0]['mode'], 'RATE')
        self.assertEqual(events[2]['active'], 'NONE')
        self.assertFalse(events[2]['signal'])
        self.assertTrue(events[3]['ready'])

    def test_history_is_session_scoped_and_bounded(self):
        data = Telemetry()
        for i in range(80):
            data.put(122, 2, LOST if i % 2 else RX, 8. + i * .1)
        result = data.receiver_health.snapshot(data, 18.)
        self.assertEqual(len(result['recent_transitions']), 32)
        fresh = Telemetry()
        self.assertEqual(fresh.receiver_health.snapshot(fresh, 18.), {
            'fc_input_frame_age_ms': None, 'input_report_age_ms': None, 'recent_transitions': [],
        })

    def test_copy_on_other_page_includes_same_stale_and_recovery_as_cockpit(self):
        app = QApplication.instance() or QApplication([])
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=folder.name):
            window = MainWindow()
        window.timer.stop()
        link, _, _ = connected_link()
        window.link = link
        link.health_timeout = 30.
        try:
            self.assertNotEqual(window.pages.currentIndex(), 0)
            now = time.monotonic()
            window.data.put(120, 1, STATUS, now)
            window.data.put(122, 2, RX, now-.51)
            window.render_status(now)
            window.render_status(now+.01)
            window.data.put(122, 2, RX, now+.02)
            window.render_status(now+.02)
            window.copy_diagnostics()
            health = json.loads(QApplication.clipboard().text())['receiver_health']
            changes = [row for row in health['recent_transitions'] if row['event'] == 'indicators']
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[0]['input']['state'], 'amber')
            self.assertIn('stale', changes[0]['input']['reason'].lower())
            self.assertEqual(changes[0]['input_report_age_ms'], 510.)
            self.assertEqual(changes[0]['fc_input_frame_age_ms'], 8)
            self.assertEqual(changes[1]['ppm']['state'], 'green')
            self.assertEqual(changes[1]['mode']['label'], 'RATE')
            self.assertEqual(window.pages.currentWidget(), window.welcome)
        finally:
            window.link = None
            window.close()
            window.deleteLater()
            app.processEvents()
