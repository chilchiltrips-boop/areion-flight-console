"""Regressions for native dropdown text and first-open row geometry."""
import os
import unittest
from collections import Counter

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from areion_gui.combo_box import ConsoleComboBox
from areion_gui.flight_workspace import FLIGHT_STYLE
from areion_gui.window import STYLE


def contrast(a, b):
    def luminance(color):
        r, g, b, _ = color.getRgbF()
        def linear(x):
            return x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4
        return .2126 * linear(r) + .7152 * linear(g) + .0722 * linear(b)
    dark, light = sorted((luminance(a), luminance(b)))
    return (light + .05) / (dark + .05)


class ComboContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.window = QWidget()
        box = QVBoxLayout(self.window)
        self.source = ConsoleComboBox(light=True, objectName='flightSource')
        self.source.addItems(['PPM receiver', 'USB channels', 'AP Wi-Fi channels'])
        self.port = ConsoleComboBox()
        self.port.setEditable(True)
        self.port.addItems(['/dev/cu.usbmodem1101', '/dev/cu.usbmodem2101', '/dev/cu.usbserial'])
        for widget in (self.source, self.port):
            box.addWidget(widget)
        # Production applies its final stylesheet after building the window.
        self.window.setStyleSheet(STYLE + FLIGHT_STYLE)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def assert_rows(self, combo, selected, disabled):
        view = combo.view()
        shot = view.viewport().grab().toImage()
        ratio = shot.devicePixelRatio()
        previous_bottom = -1
        for i in range(3):
            row = view.visualRect(combo.model().index(i, 0))
            self.assertGreater(row.top(), previous_bottom)
            self.assertGreaterEqual(row.height(), view.fontMetrics().height())
            self.assertTrue(view.viewport().rect().contains(row))
            previous_bottom = row.bottom()
            pixels = Counter(shot.pixel(x, y)
                             for x in range(round(row.left() * ratio), round((row.right() + 1) * ratio))
                             for y in range(round(row.top() * ratio), round((row.bottom() + 1) * ratio)))
            role = QPalette.ColorRole.HighlightedText if i == selected else QPalette.ColorRole.Text
            group = QPalette.ColorGroup.Disabled if i == disabled else QPalette.ColorGroup.Active
            ink = view.palette().color(group, role)
            background = QColor.fromRgb(pixels.most_common(1)[0][0])
            # Disabled items have their own stylesheet pseudo-state. Inspect
            # actual glyph pixels as the default menu delegate used a different
            # ink than the view palette reported.
            if i == disabled:
                ink = QColor('#51635d' if combo is self.source else '#adbbc5')
            self.assertGreaterEqual(contrast(ink, background), 4.5)
            self.assertTrue(any(count >= 3 and
                                max(abs(a - b) for a, b in zip(QColor.fromRgb(pixel).getRgb()[:3], ink.getRgb()[:3])) <= 12
                                for pixel, count in pixels.items()), (i, ink.name(), background.name()))

    def test_light_source_popup_and_hover_have_readable_nonoverlapping_rows(self):
        combo = self.source
        combo.model().item(2).setEnabled(False)
        combo.setCurrentIndex(1)
        combo.showPopup()
        self.app.processEvents()
        self.assert_rows(combo, 1, 2)
        view = combo.view()
        point = view.visualRect(combo.model().index(0, 0)).center()
        QTest.mouseMove(view.viewport(), point)
        self.app.processEvents()
        self.assert_rows(combo, 0, 2)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(combo.currentText(), 'PPM receiver')

    def test_editable_dark_port_and_disabled_closed_values_stay_readable(self):
        combo = self.port
        combo.model().item(2).setEnabled(False)
        combo.setCurrentIndex(0)
        combo.showPopup()
        self.app.processEvents()
        self.assert_rows(combo, 0, 2)
        combo.hidePopup()
        for combo in (self.port, self.source):
            for enabled in (True, False):
                combo.setEnabled(enabled)
                editor = combo.lineEdit() if combo.isEditable() else combo
                palette = editor.palette()
                group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
                self.assertGreaterEqual(contrast(palette.color(group, QPalette.ColorRole.Text),
                                                 palette.color(group, QPalette.ColorRole.Base)), 4.5)
