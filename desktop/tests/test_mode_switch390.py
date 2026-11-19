"""Read-only raw PPM switch monitoring on the Arming & flight modes page."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from areion_gui.wizard_extended import ExtendedSetupWizard


class ModeSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wizard = ExtendedSetupWizard(Path(tmp.name) / 'wizard.json')
        self.wizard.timer.stop()
        self.addCleanup(self.wizard.close)
        self.commands = []
        self.wizard.action_requested.connect(lambda *args: self.commands.append(args))
        self.addCleanup(lambda: self.assertEqual(self.commands, []))
        self.wizard.set_connection_state(connected=True, disarmed=True)
        self.wizard._show_step(7)
        self.source = [0, 0, True, False, False, 8, 0, 1, False]
        self.flight = [5, .1, .15, .15, 0, 1]
        self.identity = (99, 7219)

    def feed(self, pulse, channel=5, count=8, age=0, stamp=None, timeout=250):
        now = time.monotonic()
        raw = [1500 if i < count else 0 for i in range(8)]
        if channel <= count:
            raw[channel - 1] = pulse
        values = {131:raw + [count, True, age], 122:self.source, 7:self.flight,
                  112:[timeout,250], '_raw_stamp':now if stamp is None else stamp}
        self.wizard.receive_telemetry(values, None, now, self.identity)

    @property
    def text(self):
        return self.wizard.mode_test.text()

    def test_raw_threshold_and_changed_assignments(self):
        self.wizard.rx_reverse[4].setChecked(True)
        self.feed(1499)
        self.assertIn('CH5 · 1499 µs · LOW → ANGLE', self.text)
        self.assertIn('Kit mapping · Switch to HIGH', self.text)
        self.feed(1500)
        self.assertEqual(self.wizard.mode_band.pulse, 1500)
        self.assertIn('HIGH → RATE / ACRO', self.text)
        self.assertIn('Both positions seen', self.text)
        self.wizard.mode_channel.setCurrentIndex(7)
        self.wizard.mode_low.setCurrentIndex(1)
        self.wizard.mode_high.setCurrentIndex(0)
        self.feed(2000, channel=8)
        self.assertIn('CH8 · 2000 µs · HIGH → ANGLE', self.text)
        self.assertIn('Draft mapping · Switch to LOW', self.text)
        self.wizard.mode_channel.setCurrentIndex(0)
        self.assertIn('assigned to a stick', self.text)
        self.assertIsNone(self.wizard.mode_band.pulse)

    def test_expired_missing_and_invalid_data_clear_the_marker(self):
        self.feed(1000)
        self.wizard._refresh_mode_test(self.wizard.rx_stamp + .3)
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.feed(1900)
        self.assertIn('Switch to LOW', self.text)
        self.feed(1900, count=4)
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.feed(800)
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.feed(1000, age=150, stamp=time.monotonic() - .15)
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.feed(1000, age=300, timeout=500)
        self.assertEqual(self.wizard.mode_band.pulse, 1000)
        self.feed(1000, stamp=time.monotonic() + 5)
        self.assertIsNone(self.wizard.mode_band.pulse)

    def test_new_kit_digital_source_and_disconnect_clear_observations(self):
        self.feed(1000)
        self.identity = (101, 4312)
        self.feed(2000)
        self.assertIn('Switch to LOW', self.text)
        self.source[0] = 1
        self.feed(1000)
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.wizard._choose_input('USB')
        self.assertIn('PPM input only', self.text)
        self.source[0] = 0
        self.wizard._choose_input('PPM')
        self.feed(1000)
        self.assertIn('Switch to HIGH', self.text)
        self.wizard.connection_lost()
        self.assertIsNone(self.wizard.mode_band.pulse)
        self.assertIn('offline', self.text)

    def test_mode_values_are_a_preview_even_with_flight_input_gate_closed(self):
        self.source[1:5] = [0, True, False, False]
        self.feed(1000)
        self.assertIn('LOW → ANGLE', self.text)
        self.source[2] = False
        self.feed(1000)
        self.assertIn('expired', self.text)
        self.assertIsNone(self.wizard.mode_band.pulse)
