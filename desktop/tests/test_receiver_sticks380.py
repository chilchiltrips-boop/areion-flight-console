"""PPM telemetry presentation, capture progress and stale signal handling."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from areion_gui.calibration_page import CalibrationPage
from areion_gui.receiver_calibration import ReceiverCapture
from areion_gui.wizard_extended import ExtendedSetupWizard


class ReceiverStickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self, direct=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'setup.json'
        w = CalibrationPage(path, 'receiver') if direct else ExtendedSetupWizard(path)
        w.timer.stop()
        w.resize(940, 720)
        w.connected = w.disarmed = True
        w.configuration['input_source'] = 'PPM'
        w._show_step(4)
        w.show()
        self.app.processEvents()
        self.addCleanup(w.close)
        return w

    def sample(self, w, channels=None, *, count=4, fresh=True, age=5, stamp=None, now=None):
        now = time.monotonic() if now is None else now
        raw = list(channels or [1500, 1500, 1000, 1500]) + [0] * (8-count)
        raw.extend((count, fresh, age))
        setup = [True, False, 1, 0, 0, False, False, False, False, 1000, 1000, 1000, 1000, 1, '', 'AREION']
        w.receive_telemetry({131: raw, 130: setup, '_raw_stamp': now if stamp is None else stamp},
                            None, now, 'KIT')

    def test_wizard_and_direct_use_mapped_reversed_readonly_gimbals(self):
        for direct in (False, True):
            with self.subTest(direct=direct):
                w = self.page(direct)
                calls = []
                w.action_requested.connect(lambda *event: calls.append(event))
                w.configuration['receiver']['values'] = [1100, 1440, 1900, 0] * 8
                # Roll ← CH4; yaw ← reversed CH1. Throttle is linear low to high.
                w.mapping_boxes[0].setCurrentIndex(3)
                w.mapping_boxes[3].setCurrentIndex(0)
                w.rx_reverse[0].setChecked(True)
                self.sample(w, [1100, 1440, 1300, 1900])
                self.assertEqual(w.rx_sticks.target, (2000,1500,1250,2000))
                self.assertEqual(w.rx_sticks.signal_label.text(), 'Live · 4 CH')
                self.assertEqual(w.rx_table.item(6,1).text(), '—')
                gimbal = w.rx_sticks.left
                before = (gimbal.x, gimbal.y)
                self.assertEqual(before, (1., -.5))
                QTest.mouseClick(gimbal, Qt.MouseButton.LeftButton)
                self.assertEqual(before, (gimbal.x, gimbal.y))
                self.assertEqual(calls, [])

    def test_reports_stale_missing_and_invalid_channels_without_neutral_values(self):
        w = self.page()
        self.sample(w)
        self.assertTrue(w.rx_sticks.left.available)
        self.sample(w, age=400)
        self.assertIsNone(w.rx_sticks.target)
        self.assertFalse(w.rx_sticks.left.available)
        self.assertEqual(w.rx_table.item(0,1).text(), '—')
        self.sample(w, stamp=time.monotonic()-2)
        self.assertIsNone(w.rx_sticks.target)
        self.assertFalse(w.rx_finish.isEnabled())
        self.sample(w)
        w.mapping_boxes[0].setCurrentIndex(6)
        self.assertEqual(w.rx_sticks.quality, 'error')
        self.assertIsNone(w.rx_sticks.target)
        self.assertEqual(w.rx_table.item(0,1).text(), '1500')
        w.connection_lost()
        self.assertEqual(w.rx_sticks.signal_label.text(), 'Offline')

    def test_propeller_lock_and_neutral_capture_are_independent_of_preview(self):
        w = self.page()
        self.sample(w)
        self.assertTrue(w.rx_sticks.left.available)
        self.assertFalse(w.rx_start.isEnabled())
        w.propeller_check.setChecked(True)
        now = time.monotonic()
        w.rx_capture = ReceiverCapture([1000,1500,2000,0]*8,[1,2,3,4],now-2.5,'KIT')
        for i in range(12):
            stamp = now-2.2 + .2*i
            self.sample(w,[1800 if i%2 else 1100,1500,1000,1500],stamp=stamp,now=stamp)
        self.assertLess(w.rx_progress.value(), 90)
        self.assertIn('1 / 4', w.rx_extent.text())
        self.sample(w,[1100]*4)
        self.sample(w,[1900]*4)
        self.sample(w)
        self.assertEqual(w.rx_progress.value(), 90)
        self.assertIn('4 / 4', w.rx_extent.text())
        w._finish_receiver()
        self.assertIsNone(w.rx_capture)
        self.assertEqual(w.rx_progress.value(), 100)
        self.assertIsNotNone(w.rx_result)

    def test_moves_between_received_samples_and_clears_immediately_on_loss(self):
        w = self.page()
        self.sample(w)
        self.sample(w,[2000,1000,2000,2000])
        self.assertTrue(w.rx_sticks.motion.isActive())
        QTest.qWait(72)
        self.assertGreater(w.rx_sticks.right.x, 0.)
        self.assertLessEqual(w.rx_sticks.right.x, 1.)
        self.sample(w, fresh=False)
        self.assertFalse(w.rx_sticks.motion.isActive())
        self.assertFalse(w.rx_sticks.right.available)

if __name__ == '__main__':
    unittest.main()
