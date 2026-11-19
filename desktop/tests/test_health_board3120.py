"""Native health lamps stay legible as instrument sizes and live states change."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QAbstractButton

from areion_gui.flight_status import Health, KEYS
from areion_gui.health_board import COLORS, SEVERITY, SystemHealthBoard


class HealthBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.board = SystemHealthBoard()
        self.board.resize(440, 225)
        self.board.show()
        self.app.processEvents()

    def tearDown(self):
        self.board.close()

    def test_one_read_only_lamp_per_signal(self):
        self.assertCountEqual(self.board.tiles, KEYS)
        self.assertEqual(len(set(self.board.tiles.values())), len(KEYS))
        self.assertFalse(self.board.findChildren(QAbstractButton))
        for tile in self.board.tiles.values():
            self.assertEqual(tile.focusPolicy(), Qt.FocusPolicy.NoFocus)
            self.assertTrue(tile.isVisibleTo(self.board))

    def test_complete_face_and_screen_reader_state_change_together(self):
        tile = self.board.tiles['IMU']
        color_set = set()
        for severity, reason, text in (('red', 'NO READ', 'IMU read failed'),
                                      ('amber', 'WAITING', 'Waiting for samples'),
                                      ('green', 'READING', 'Confirmed current reading'),
                                      ('gray', 'OFFLINE', 'Kit disconnected')):
            self.board.set_health({'IMU': Health(severity, reason, text)})
            self.app.processEvents()
            picture = tile.grab().toImage()
            face = QColor(COLORS[severity][0]).rgb()
            filled = sum(picture.pixel(x, y) == face for x in range(picture.width())
                         for y in range(picture.height()))
            self.assertGreater(filled, picture.width() * picture.height() * .5)
            self.assertIn(SEVERITY[severity], tile.accessibleName())
            self.assertIn(reason, tile.accessibleName())
            self.assertEqual(tile.toolTip(), text)
            self.assertEqual(tile.accessibleDescription(), text)
            color_set.add(face)
        self.assertEqual(len(color_set), 4)

    def test_live_values_do_not_shift_layout_or_leak_preceding_data(self):
        self.board.resize(320, 156)
        self.app.processEvents()
        before = {key: lamp.geometry() for key, lamp in self.board.tiles.items()}
        self.assertTrue(all(self.board.rect().contains(rect) for rect in before.values()))
        self.assertTrue(all(rect.height() >= 34 for rect in before.values()))
        self.board.set_health({'CONFIG': Health('amber', 'PID UNSAVED', 'Pending save.')})
        self.board.set_health({})
        self.app.processEvents()
        for key, lamp in self.board.tiles.items():
            self.assertEqual(lamp.health.state, 'gray')
            self.assertEqual(lamp.geometry(), before[key])
            self.assertTrue(lamp.isVisible())


if __name__ == '__main__':
    unittest.main()
