"""Real Qt wheel events must scroll pages without editing any values."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDoubleSpinBox, QLabel, QScrollArea,
    QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)
from areion_gui.scroll_guard import focus_page, install_scroll_guard, remove_scroll_guard


class ScrollGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        self.page = QWidget()
        self.form = QVBoxLayout(self.page)
        self.controls = [QSpinBox(), QDoubleSpinBox(), QComboBox(), QSlider(Qt.Orientation.Horizontal)]
        for widget in self.controls:
            if isinstance(widget, QComboBox):
                widget.addItems([str(i) for i in range(60)])
                widget.setCurrentIndex(20)
            else:
                widget.setRange(0, 100)
                widget.setValue(20)
            self.form.addWidget(widget)
        spacer = QLabel('Long page')
        spacer.setMinimumHeight(1200)
        self.form.addWidget(spacer)
        self.scroll.setWidget(self.page)
        self.guard = install_scroll_guard(self.window)
        self.window.resize(420, 340)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def value(self, widget):
        return widget.currentIndex() if isinstance(widget, QComboBox) else widget.value()

    def wheel(self, widget, *, angle=-120, pixels=0):
        point = widget.rect().center()
        event = QWheelEvent(
            QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(0, pixels),
            QPoint(0, angle), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(widget, event)
        self.app.processEvents()
        return event

    def test_wheel_never_edits_focused_or_unfocused_controls_and_scrolls_page(self):
        for widget in self.controls:
            for focused in (False, True):
                with self.subTest(widget=type(widget).__name__, focused=focused):
                    self.scroll.verticalScrollBar().setValue(0)
                    (widget if focused else self.window).setFocus()
                    before = self.value(widget)
                    self.wheel(widget)
                    self.assertEqual(self.value(widget), before)
                    self.assertGreater(self.scroll.verticalScrollBar().value(), 0)

    def test_embedded_line_edit_and_trackpad_pixels_do_not_change_spin_value(self):
        spin = self.controls[1]
        spin.lineEdit().setFocus()
        self.wheel(spin.lineEdit(), pixels=-60, angle=0)
        self.assertEqual(spin.value(), 20)
        self.assertGreater(self.scroll.verticalScrollBar().value(), 0)

    def test_typing_arrow_keys_spin_buttons_and_slider_drag_still_edit(self):
        spin, double, combo, slider = self.controls
        spin.setFocus()
        QTest.keyClick(spin, Qt.Key.Key_Up)
        self.assertEqual(spin.value(), 21)
        double.lineEdit().setFocus()
        QTest.keyClick(double.lineEdit(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(double.lineEdit(), '36.5')
        QTest.keyClick(double.lineEdit(), Qt.Key.Key_Return)
        self.assertEqual(double.value(), 36.5)
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Down)
        self.assertEqual(combo.currentIndex(), 21)
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=QPoint(spin.width()-8, 5))
        self.assertGreater(spin.value(), 21)
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//5, slider.height()//2))
        QTest.mouseMove(slider, QPoint(slider.width()*4//5, slider.height()//2))
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()*4//5, slider.height()//2))
        self.assertGreater(slider.value(), 20)

    def test_dynamic_owned_dialog_is_guarded_without_a_scroll_parent(self):
        dialog = QDialog(self.window)
        layout = QVBoxLayout(dialog)
        spin = QSpinBox()
        spin.setValue(25)
        layout.addWidget(spin)
        dialog.show()
        self.app.processEvents()
        spin.setFocus()
        self.wheel(spin)
        self.assertEqual(spin.value(), 25)
        dialog.close()

    def test_combo_popup_can_scroll_without_committing_a_different_choice(self):
        combo = self.controls[2]
        combo.setMaxVisibleItems(6)
        combo.showPopup()
        self.app.processEvents()
        view = combo.view()
        before = combo.currentIndex()
        view.verticalScrollBar().setValue(0)
        self.wheel(view.viewport())
        self.assertEqual(combo.currentIndex(), before)
        self.assertGreater(view.verticalScrollBar().value(), 0)
        combo.hidePopup()

    def test_page_entry_focus_is_container_and_tab_navigation_remains_available(self):
        spin = self.controls[0]
        spin.setFocus()
        focus_page(self.scroll)
        self.assertFalse(spin.hasFocus())
        self.assertTrue(self.scroll.hasFocus() or self.scroll.viewport().hasFocus())
        QTest.keyClick(self.scroll, Qt.Key.Key_Tab)
        self.assertTrue(spin.hasFocus())
        self.assertEqual(spin.value(), 20)

    def test_install_is_idempotent_and_unrelated_window_is_unaffected(self):
        self.assertIs(install_scroll_guard(self.window), self.guard)
        other = QSpinBox()
        other.setValue(25)
        other.show()
        other.setFocus()
        self.wheel(other)
        self.assertNotEqual(other.value(), 25)
        other.close()
        other.deleteLater()

    def test_removed_guard_has_no_event_callbacks_and_can_be_reinstalled(self):
        calls = []
        original = self.guard.eventFilter
        self.guard.eventFilter = lambda watched, event: (calls.append(event.type()), original(watched, event))[1]
        QApplication.sendEvent(self.window, QEvent(QEvent.Type.User))
        self.assertIn(QEvent.Type.User, calls)
        remove_scroll_guard(self.window)
        calls.clear()
        QApplication.sendEvent(self.window, QEvent(QEvent.Type.User))
        self.assertEqual(calls, [])
        self.assertIs(install_scroll_guard(self.window), self.guard)
        spin = self.controls[0]
        self.wheel(spin)
        self.assertEqual(spin.value(), 20)

    def test_main_window_and_lazy_wizard_protect_every_numeric_choice_and_slider(self):
        from areion_gui.window import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=directory):
                window = MainWindow()
            window.show()
            self.app.processEvents()
            window.timer.stop()
            seen = set()
            try:
                for page_index in range(6):
                    window.navigate(page_index)
                    if page_index == 5:
                        window.setup_wizard.timer.stop()
                    self.app.processEvents()
                    page = window.pages.currentWidget()
                    focus = QApplication.focusWidget()
                    self.assertNotIsInstance(focus, (QSpinBox, QDoubleSpinBox, QComboBox, QSlider))
                    for widget in page.findChildren(QWidget):
                        if not isinstance(widget, (QSpinBox, QDoubleSpinBox, QComboBox, QSlider)):
                            continue
                        with self.subTest(page=page_index, widget=type(widget).__name__):
                            widget.setEnabled(True)
                            before = self.value(widget)
                            self.wheel(widget)
                            self.assertEqual(self.value(widget), before)
                            seen.add(id(widget))
                self.assertGreater(len(seen), 50)
            finally:
                window.close()
                for _ in range(100):
                    if window.close_ready:
                        break
                    QTest.qWait(10)
                self.assertTrue(window.close_ready)
                closed_calls = []
                original = window._scroll_guard.eventFilter
                window._scroll_guard.eventFilter = lambda watched, event: (closed_calls.append(event.type()), original(watched, event))[1]
                QApplication.sendEvent(self.window, QEvent(QEvent.Type.User))
                self.assertEqual(closed_calls, [])
                window.show()
                self.app.processEvents()
                before = window.baud.value()
                self.wheel(window.baud)
                self.assertEqual(window.baud.value(), before)
                self.assertTrue(window._scroll_guard._installed)
                window.close()
                self.assertFalse(window._scroll_guard._installed)
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
