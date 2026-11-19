"""Exercise the setup workspace through the console and its real navigation buttons."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fc_fixture import make_test_window
from setup_fixtures import complete_demo_window


class WizardWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def open_existing_ppm_setup(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=folder.name):
            window = make_test_window()
        self.addCleanup(lambda: QTest.qWait(160))
        self.addCleanup(window.close)
        window.show()
        QTest.qWait(120)
        complete_demo_window(window, source=0)
        window.navigate(5)
        wizard = window.setup_wizard
        self.wait_for(lambda: wizard.begin_confirmed and wizard.loaded_identity is not None
                      and wizard._ready())
        return window, wizard

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3.5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(15)
        self.assertTrue(predicate())

    def test_completed_kit_can_review_all_steps_and_finish_via_footer_without_arming(self):
        window, wizard = self.open_existing_ppm_setup()
        self.assertFalse(wizard.next_button.isEnabled())
        self.assertFalse(wizard.back_button.isEnabled())
        self.assertTrue(wizard.propeller_check.isEnabled())
        wizard.propeller_check.setChecked(True)
        for index in range(9):
            self.assertEqual(wizard.step, index)
            self.assertEqual(wizard.stack.currentIndex(), index)
            for width, height in ((900, 700), (1280, 800)):
                with self.subTest(step=index, width=width):
                    window.resize(width, height)
                    self.app.processEvents()
                    self.assertEqual(window.size().toTuple(), (width, height))
                    scroll = wizard.scrolls[index]
                    self.assertTrue(scroll.isVisibleTo(window))
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    for button in (wizard.next_button, wizard.back_button):
                        self.assertTrue(button.isVisibleTo(window))
                        bounds = QRect(button.mapTo(window, QPoint()), button.size())
                        self.assertTrue(window.rect().contains(bounds), bounds)
            if index == 4:
                QTest.mouseClick(wizard.back_button, Qt.MouseButton.LeftButton)
                self.assertEqual(wizard.step, 3)
                QTest.mouseClick(wizard.next_button, Qt.MouseButton.LeftButton)
                self.assertEqual(wizard.step, 4)
            if index == 8:
                self.assertFalse(wizard.next_button.isEnabled())
                wizard.save_ack.setChecked(True)
            self.assertFalse(window.link.armed)
            self.assertTrue(wizard.next_button.isEnabled(), (index, wizard.last_error))
            QTest.mouseClick(wizard.next_button, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: wizard.finalized_this_visit)
        self.assertEqual(window.link.read_group(130)[:2], [False, True])
        self.assertFalse(window.link.armed)
