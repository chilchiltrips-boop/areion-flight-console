"""Welcome is a window-sized read-only view of the connected kit."""
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from PySide6.QtTest import QTest
from areion_gui.launcher_tile import LauncherTile
from areion_gui.window import MainWindow


class WelcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=self.temp.name):
            self.w = MainWindow()
        self.w.show()
        QTest.qWait(40)
        self.page = self.w.welcome

    def tearDown(self):
        self.w.close()
        QTest.qWait(20)
        self.temp.cleanup()

    def test_offline_start_opens_read_only_welcome(self):
        self.assertIs(self.w.pages.currentWidget(), self.page)
        self.assertIsNone(self.w.link)
        self.assertIsNone(self.w._setup_wizard)
        self.assertFalse(self.w._setup_guard)
        self.assertEqual(self.page.connection.text(), 'Offline')
        self.assertEqual([x.text() for x in self.page.values.values()], ['—'] * 4)
        self.assertFalse(any('demo' in b.text().lower() for b in self.w.findChildren(QPushButton)))

    def test_diagnostics_use_board_completion_before_wizard_is_opened(self):
        def report():
            self.w.copy_diagnostics()
            return json.loads(QApplication.clipboard().text())['setup_wizard']

        self.assertIsNone(report()['wizard_complete'])
        state = [False, True, 0, 4, 15, True, True, False, False,
                 1000, 1000, 1000, 1000, 17, '', 'kit-a']
        link = SimpleNamespace(connected=True, transport_status=[], fc_session=123)
        with patch.object(self.w, 'link', link):
            self.assertTrue(self.w.data.put(130, 1, state, time.monotonic()))
            current = report()
            self.assertEqual(current['stage'], 'not_opened')
            self.assertIs(current['wizard_complete'], True)
            self.assertIs(current['hardware_applied'], True)
            self.w.data.latest[130] = (state, time.monotonic() - 1)
            self.assertIsNone(report()['wizard_complete'])
        self.assertIsNone(self.w._setup_wizard)

    def test_fills_viewport_and_all_actions_fit_at_supported_sizes(self):
        self.w.log('Connection error ' + '/dev/cu.device-' * 30)
        for large_text in (False, True):
            if large_text:
                self.page.setStyleSheet(self.page.styleSheet() +
                                        'QPushButton, QLabel {font-size:18px;}')
            for width, height in ((900, 700), (1120, 760), (1700, 960)):
                with self.subTest(width=width, large_text=large_text):
                    self.w.resize(width, height)
                    QTest.qWait(15)
                    self.assertEqual(self.w.size().toTuple(), (width, height))
                    self.assertEqual(self.page.rect().size(), self.w.pages.contentsRect().size())
                    self.assertFalse(self.page.findChildren(QScrollArea))
                    rects = []
                    for item in self.page.findChildren(QPushButton):
                        bounds = QRect(item.mapTo(self.page, QPoint()), item.size())
                        self.assertTrue(item.isVisible())
                        self.assertTrue(self.page.rect().contains(bounds), (item.text(), bounds))
                        self.assertFalse(any(bounds.intersects(seen) for seen in rects))
                        rects.append(bounds)
                    tiles = self.page.findChildren(LauncherTile)
                    regular = [tile for tile in tiles if tile.icon_key != 'wizard']
                    self.assertEqual(len(regular), 6)
                    centers = [tile.mapTo(self.page, tile.rect().center()) for tile in regular]
                    self.assertEqual(len({point.x() for point in centers}), 3)
                    self.assertEqual(len({point.y() for point in centers}), 2)
                    brand = self.page.brand_mark.mapTo(self.page, self.page.brand_mark.rect().center())
                    wizard = self.page.setup_button.mapTo(self.page, self.page.setup_button.rect().center())
                    self.assertLess(brand.x(), min(point.x() for point in centers))
                    self.assertGreater(wizard.x(), max(point.x() for point in centers))

    def test_shortcuts_open_their_existing_routes_with_keyboard_or_mouse(self):
        expected = {'flight': 0, 'input': 10, 'imu': 1, 'esc': 6,
                    'pid': 2, 'scopes': 8, 'wizard': 5}
        tiles = {tile.icon_key: tile for tile in self.page.findChildren(LauncherTile)}
        self.assertEqual(tiles.keys(), expected.keys())
        for index, (key, route) in enumerate(expected.items()):
            with self.subTest(shortcut=key):
                self.w.navigate(7)
                tile = tiles[key]
                if index % 2:
                    tile.setFocus()
                    self.assertTrue(tile.hasFocus())
                    QTest.keyClick(tile, Qt.Key.Key_Return)
                else:
                    QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
                self.assertEqual(self.w.pages.currentIndex(), route)
                if key == 'imu':
                    self.assertEqual(self.w.imu_tabs.currentIndex(), 1)
                self.assertIsNone(self.w.link)
                self.assertFalse(self.w.connecting)

    def test_activity_shows_recent_console_events_and_opens_the_full_log(self):
        events = [f'Welcome event {number}' for number in range(4)]
        for event in events:
            self.w.log(event)
        self.app.processEvents()
        rows = [message.text() for _, message in self.page.event_rows]
        self.assertEqual(rows, list(reversed(events[1:])))
        self.assertFalse(self.page.empty_activity.isVisible())
        QTest.mouseClick(self.page.event_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.pages.currentIndex(), 4)
        self.assertIs(self.w.live_tabs.currentWidget(), self.w.log_view)
        for event in events:
            self.assertIn(event, self.w.log_view.toPlainText())
        self.assertIsNone(self.w._setup_wizard)

    def test_connection_shortcut_opens_settings_without_connecting(self):
        QTest.mouseClick(self.page.settings_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self.w.connection_dialog.isVisible())
        self.assertFalse(self.w.connecting)
        self.assertIsNone(self.w.link)
        self.w.connection_dialog.close()

    def test_reports_transport_independently_of_fc_configured_source_and_setup(self):
        now = time.monotonic()
        config = [0, 0, 1, 2, 3, 4, 5, 1180, 1180, 1180, 1180]
        self.assertTrue(self.w.data.put(134, 1, config, now))
        path = dict(name='udp', datagram=True, confirmed=True, active=True, last_received_age=.01)
        link = SimpleNamespace(transport_status=[path], fc_session=123)
        with patch.object(self.w, 'link', link):
            self.w._render_console(now, True, None, [False, True])
            self.assertEqual(self.page.connection.text(), 'Connected')
            self.assertEqual(self.page.values['Telemetry link'].text(), 'AP')
            self.assertEqual(self.page.values['Configured input'].text(), 'PPM')
            self.assertEqual(self.page.values['Setup'].text(), 'Saved')
            self.assertEqual(self.page.setup_button.text(), 'Edit setup')
            self.w._render_console(now, True, None, None)
            self.assertEqual(self.page.values['Setup'].text(), '—')
            path['last_received_age'] = 2
            self.w._render_console(now, True, None, [False, True])
            self.assertEqual(self.page.connection.text(), 'Link stale')
            self.assertEqual([x.text() for x in self.page.values.values()], ['—'] * 4)
        self.w._render_console(now, False, None, None)
        self.assertEqual(self.page.connection.text(), 'Offline')
        self.assertIn('setup wizard', self.page.setup_button.text().casefold())


if __name__ == '__main__':
    unittest.main()
