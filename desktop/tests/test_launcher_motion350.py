"""Keyboard and pointer interactions on Welcome's custom painted launch tiles."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from areion_gui.launcher_tile import LauncherTile


class LauncherMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        layout = QHBoxLayout(self.window)
        self.tile = LauncherTile('Flight Data', 'flight')
        self.feature = LauncherTile('Vehicle setup wizard', 'wizard', featured=True)
        for tile in (self.tile, self.feature):
            layout.addWidget(tile)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_pointer_animation_changes_pixels_without_moving_hit_areas(self):
        home = self.tile.geometry()
        neighbor = self.feature.geometry()
        clicked = QSignalSpy(self.tile.clicked)
        QTest.mouseMove(self.feature, self.feature.rect().center())
        QTest.mouseMove(self.tile, self.tile.rect().center())
        QTest.qWait(180)
        self.assertAlmostEqual(self.tile._motion, 1)
        raised = self.tile.grab().toImage()
        QTest.mousePress(self.tile, Qt.MouseButton.LeftButton)
        QTest.qWait(120)
        self.assertAlmostEqual(self.tile._motion, -1)
        self.assertNotEqual(raised, self.tile.grab().toImage())
        QTest.mouseRelease(self.tile, Qt.MouseButton.LeftButton)
        QTest.qWait(180)
        self.assertEqual(clicked.count(), 1)
        self.assertEqual((self.tile.geometry(), self.feature.geometry()), (home, neighbor))

    def test_keyboard_activates_once_per_press_on_both_tile_sizes(self):
        for tile in (self.tile, self.feature):
            tile.setFocus(Qt.FocusReason.TabFocusReason)
            spy = QSignalSpy(tile.clicked)
            for index, key in enumerate((Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)):
                with self.subTest(key=key, feature=tile.featured):
                    QTest.keyPress(tile, key)
                    self.assertTrue(tile.isDown())
                    for kind in (QEvent.Type.KeyRelease, QEvent.Type.KeyPress):
                        repeat = QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier, '', True)
                        self.app.sendEvent(tile, repeat)
                    self.assertEqual(spy.count(), index)
                    QTest.keyRelease(tile, key)
                    self.assertEqual(spy.count(), index + 1)

    def test_cancelled_or_disabled_press_does_not_navigate(self):
        clicked = QSignalSpy(self.tile.clicked)
        QTest.mousePress(self.tile, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(self.tile, Qt.MouseButton.LeftButton, pos=QPoint(-8, -8))
        self.assertEqual(clicked.count(), 0)
        self.tile.setEnabled(False)
        QTest.mouseClick(self.tile, Qt.MouseButton.LeftButton)
        QTest.keyClick(self.tile, Qt.Key.Key_Return)
        self.assertEqual(clicked.count(), 0)


if __name__ == '__main__':
    unittest.main()
