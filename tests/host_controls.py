"""Browser input and loss-of-control regressions using real offscreen Qt widgets."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout
from areion_gui.window import MainWindow
from browser_host.surface import Surface


class BrowserControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.settings.cleanup)
        os.environ['XDG_CONFIG_HOME'] = cls.settings.name
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setOrganizationName('AreionBrowserHostTests')

    def setUp(self):
        self.window = MainWindow()
        self.surface = Surface(self.window)
        self.window.timer.stop()
        self.window.port_scan_timer.stop()
        self.surface.tick.stop()
        self.app.processEvents()
        self.addCleanup(self.close)

    def close(self):
        self.window._setup_wizard = None
        self.window.session = None
        self.app.removeEventFilter(self.surface)
        self.window.close()
        self.app.processEvents()

    def test_navigation_and_unicode_text(self):
        for index, title in [(2,'Configuration'), (8,'Scopes'), (4,'System'), (0,'Flight Data'), (7,'Welcome')]:
            button = next(b for b in self.window.nav if b.text() == title)
            point = button.mapTo(self.window, button.rect().center())
            for event in ('down','up'):
                self.surface.handle(dict(type=event, x=point.x(), y=point.y(), button=0))
            self.app.processEvents()
            self.assertEqual(self.window.pages.currentIndex(), index)
        dialog = QDialog(self.window)
        entry = QLineEdit(dialog)
        QVBoxLayout(dialog).addWidget(entry)
        dialog.show()
        entry.setFocus()
        self.app.processEvents()
        self.surface.handle({'type':'text', 'text':'Areion μs'})
        self.assertEqual(entry.text(),'Areion μs')
        dialog.close()

    def test_blur_stops_provisional_motor_start_and_releases_controls(self):
        wizard = Mock()
        wizard.pending = ('command', {'command':'MOTOR_START'})
        wizard.connected = True
        self.window._setup_wizard = wizard
        self.window.session = Mock(running=True)
        self.window.left_stick.held = True
        self.window.controls.pressed.add('Left')
        self.surface.handle({'type':'reset'})
        wizard.action_requested.emit.assert_called_with('command', {'command':'MOTOR_STOP','args':[0,0,0,0]})
        self.window.session.stop.assert_called_once()
        self.assertFalse(self.window.left_stick.held)
        self.assertFalse(self.window.controls.pressed)

    def test_lost_lease_never_completes_a_half_click(self):
        status = self.window.pages.currentIndex()
        target = next(b for b in self.window.nav if b.text() == 'Scopes')
        point = target.mapTo(self.window, target.rect().center())
        self.surface.handle({'type':'down','x':point.x(),'y':point.y(),'button':0})
        self.surface.release(2)
        self.app.processEvents()
        self.assertEqual(status, self.window.pages.currentIndex())
        self.assertFalse(target.isDown())


if __name__ == '__main__':
    unittest.main()
