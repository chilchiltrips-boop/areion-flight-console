"""Wizard feedback must leave controls, focus and verified progress intact."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from areion_gui.calibration_page import CalibrationPage
from areion_gui.wizard_extended import ExtendedSetupWizard
from areion_gui.wizard_chrome import PressWave, StepButton, install_action_feedback


class WizardChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pressed_animation_is_local_and_does_not_replay_the_click(self):
        page = QWidget()
        box = QVBoxLayout(page)
        button = QPushButton('Capture', page)
        box.addWidget(button)
        install_action_feedback(page)
        page.show()
        self.app.processEvents()
        calls = []
        button.clicked.connect(lambda: calls.append(True))
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        wave = button.findChild(PressWave)
        self.assertIsNotNone(wave)
        self.assertTrue(wave.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertEqual(wave.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(calls, [])
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        QTest.qWait(300)
        self.assertIsNone(button.findChild(PressWave))
        self.assertEqual(calls, [True])
        page.close()
        page.deleteLater()

    def test_navigation_distinguishes_visited_verified_skipped_and_error(self):
        receiver = StepButton(4, 'PPM receiver')
        receiver.setChecked(True)
        self.assertEqual(receiver.state, 'pending')
        receiver.set_step_state(True, False, False)
        self.assertEqual(receiver.state, 'verified')
        receiver.set_step_state(True, True, False)
        self.assertEqual(receiver.state, 'skipped')
        receiver.set_step_state(False, False, True)
        self.assertEqual(receiver.state, 'error')
        self.assertTrue(receiver.isChecked())
        receiver.deleteLater()


    def test_final_save_confirmation_does_not_latch_disarmed(self):
        with TemporaryDirectory() as folder:
            for direct in (False, True):
                path = Path(folder) / 'test.json'
                page = CalibrationPage(path, 'imu') if direct else ExtendedSetupWizard(path)
                page.timer.stop()
                page.connected = page.finalized_this_visit = True
                page.live[130] = [False, True, 0, 4, 15, True, True, False, False,
                                  1000, 1000, 1000, 1000, 1, '', 'TEST']
                for state, expected in ((False, 'DISARMED'), (True, 'ARMED'), (None, '')):
                    if state is None:
                        page.live.pop(120)
                    else:
                        page.live[120] = [state, True, True, 8, .004, 2000, 4000, True, False, False]
                    page._update_navigation()
                    header = page.lock_note.text()
                    self.assertTrue(header.endswith(expected) if expected else 'ARMED' not in header)
                    self.assertNotIn('DISARMED', header if state is not False else '')
                    self.assertIn('saved', page.footer_note.text().lower())
                    if state is None:
                        self.assertNotIn('ARMED', page.footer_note.text())
                page.close()
                page.deleteLater()
