"""Cockpit/clipboard status and connection-scoped local receiver profiles."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui import tx_link
from areion_gui.model import Telemetry
from areion_gui.window import MainWindow
from test_actions_sdk import connected_link
from zebjus_areion_link.schema import DRONE_GROUPS


class TransmitterWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=directory.name):
            self.window = MainWindow()
        self.window.timer.stop()
        self.addCleanup(self.close_window)
        self.window.link, self.usb, self.ap = connected_link()
        self.now = time.monotonic()
        self.kit('A')

    def close_window(self):
        self.window.link = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def put(self, group, values, elapsed=0):
        self.assertTrue(self.window.data.put(group, DRONE_GROUPS[group]['schema'], values, self.now + elapsed))

    def kit(self, kit_id):
        self.window.data = Telemetry()
        for group in (7, 134):
            self.put(group, [field['default'] for field in DRONE_GROUPS[group]['fields']])
        self.put(130, [False, True, 0, 5, 15, True, True, False, False, 1000, 1000, 1000, 1000, 1, '', kit_id])

    def frame(self, marker=1800, elapsed=0, armed=False):
        present = marker is not None
        self.put(120, [armed, False, True, 8 if present else 0, .004, 2000, 100, True, False, False], elapsed)
        self.put(122, [0, int(present), present, False, present, 8 if present else 0,
                       8 if present else 400, 42, False], elapsed)
        if present:
            self.put(22, [1500, 1500, 1000, 1500, 1000, marker, 1500, 1500], elapsed)

    def render(self, elapsed):
        self.window._refresh_flight_instruments(self.now + elapsed, True)
        badge = self.window.tx_link_badge
        return badge.text(), badge.property('state')

    def test_cached_only_for_the_current_kit_and_session(self):
        w = self.window
        self.frame(elapsed=-.1)
        self.frame()
        profile = {'version': 1, 'kind': 'marker', 'kit_id': 'A', 'mapping': [1, 2, 3, 4],
                   'mode_channel': 5, 'channel_count': 8, 'channel': 6, 'on_us': 1800, 'off_us': 1100}
        with patch.object(tx_link, 'load_profile', wraps=tx_link.load_profile) as reads:
            self.assertEqual(self.render(0), ('TX UNVERIFIED', 'amber'))
            self.assertEqual(self.render(.01), ('TX UNVERIFIED', 'amber'))
            self.assertEqual(reads.call_count, 1)
            with patch('time.monotonic', return_value=self.now):
                w.save_tx_link_profile(profile)
            self.assertEqual(self.render(.02), ('TX ON', 'green'))
            self.frame(1100, .03)
            self.frame(1100, .04)
            self.assertEqual(self.render(.04), ('TX OFF', 'amber'))
            health = w.flight_dashboard.last_health
            self.assertEqual([health[k].label for k in ('PPM', 'INPUT', 'MODE')], ['TX OFF', 'TX OFF', 'RATE'])
            self.assertEqual([health[k].state for k in ('PPM', 'INPUT', 'MODE')], ['amber'] * 3)
            with patch('time.monotonic', return_value=self.now + .04):
                w.copy_diagnostics()
            state = json.loads(self.app.clipboard().text())['tx_link']
            self.assertEqual((state['code'], state['channel'], state['channel_us']), ('off', 6, 1100))
            self.assertEqual(reads.call_count, 1)
            self.kit('B')
            self.frame(elapsed=-.1)
            self.frame()
            self.assertEqual(self.render(0), ('TX UNVERIFIED', 'amber'))
            with self.assertRaises(ValueError):
                w.clear_tx_link_profile('A')
            self.kit('A')
            self.frame(elapsed=-.1)
            self.frame()
            self.assertEqual(self.render(0), ('TX ON', 'green'))
            with patch('time.monotonic', return_value=self.now):
                w.clear_tx_link_profile('A')
            self.assertEqual(self.render(0), ('TX UNVERIFIED', 'amber'))
            self.assertEqual(reads.call_count, 3)
        self.assertIsNone(tx_link.load_profile(w.config_path.parent, 'A'))
        self.assertEqual(self.usb.sent + self.ap.sent, [])

    def test_no_ppm_stale_and_source_switch_have_distinct_meanings(self):
        self.frame(None)
        self.assertEqual(self.render(0), ('TX · NO PPM', 'amber'))
        self.frame(None, .01, armed=True)
        self.assertEqual(self.render(.01), ('TX · NO PPM', 'amber'))
        self.assertEqual(self.window.flight_dashboard.last_health['INPUT'].state, 'red')
        self.assertEqual(self.render(.6), ('TX WAITING', 'amber'))
        self.put(110, [2], .61)
        self.assertEqual(self.render(.61), ('TX INACTIVE', 'gray'))
        self.assertEqual(self.usb.sent + self.ap.sent, [])
