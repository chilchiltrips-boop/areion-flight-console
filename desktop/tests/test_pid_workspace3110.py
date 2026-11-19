"""Exercise native tuning controls through the normal desktop route and FC jobs."""
import os
import struct
import tempfile
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox

from fc_fixture import make_test_window
from setup_fixtures import complete_demo_window


class PidWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        with patch('areion_gui.window.QStandardPaths.writableLocation', return_value=self.folder.name):
            self.w = make_test_window()
        self.addCleanup(self.close)
        self.w.resize(1280, 800)
        self.w.show()
        self.wait(lambda: all(c.loaded and not c.busy for c in self.w.cards.values()))
        complete_demo_window(self.w)
        self.w.render_status(time.monotonic())
        self.w.navigate(7)
        self.click(self.w.welcome.pid_button)
        self.assertEqual(self.w.pages.currentIndex(), 2)
        self.workspace = self.w.pid_workspace
        self.rate, self.angle = self.w.cards[2], self.w.cards[3]
        self.link = self.w.link

    def close(self):
        self.w.close()
        QTest.qWait(75)

    def wait(self, predicate):
        deadline = time.monotonic() + 3.
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), getattr(self.w, 'last_notice', 'Request timed out'))

    def click(self, widget):
        self.assertTrue(widget.isEnabled(), widget.text())
        point = QPoint(8, widget.height() // 2) if isinstance(widget, QCheckBox) else widget.rect().center()
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()

    def tab(self, bar, index):
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
        self.app.processEvents()
        self.assertEqual(bar.currentIndex(), index)

    def apply(self, card):
        self.wait(card.buttons['apply'].isEnabled)
        self.click(card.buttons['apply'])
        self.wait(lambda: not self.w.command_busy and not card.busy)

    def test_three_tabs_fit_and_reveal_firmware_groups(self):
        scroll = self.w.pages.widget(2)
        expected = ((2, 3), (7,), (112, 4))
        for size in ((900, 700), (1280, 800)):
            self.w.resize(*size)
            for index, groups in enumerate(expected):
                with self.subTest(size=size, tab=index):
                    self.tab(self.workspace.tabs, index)
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    visible = {group for group in (2,3,7,112,4) if self.w.cards[group].isVisibleTo(self.workspace)}
                    self.assertEqual(visible, set(groups))
                    self.assertEqual(self.workspace.response.isVisibleTo(self.workspace), index == 0)

    def test_edits_selectors_and_preview_do_not_write_or_reset_other_drafts(self):
        rate_before = self.link.read_group(2)
        angle_before = self.link.read_group(3)
        with ExitStack() as guards:
            writes = [guards.enter_context(patch.object(self.link, name, wraps=getattr(self.link, name)))
                      for name in ('action', 'set_group', 'save_group', 'send_control', 'arm', 'disarm')]
            self.click(self.rate.link_check)
            self.assertEqual(self.rate.values(), rate_before)
            self.rate.inputs[6].setValue(.0421)
            self.assertEqual(self.rate.values()[6:8], [.0421, .0421])
            self.angle.inputs[2].setValue(.371)
            self.tab(self.workspace.response.axis_tabs, 1)
            self.tab(self.workspace.response.loop_tabs, 1)
            self.tab(self.workspace.tabs, 1)
            self.workspace.stick_curve.pulse.setValue(1870)
            self.tab(self.workspace.tabs, 2)
            self.tab(self.workspace.tabs, 0)
            self.assertEqual(self.rate.values()[6:8], [.0421, .0421])
            self.assertTrue(self.angle.inputs[2].property('changed'))
            self.click(self.rate.revert_button)
            self.assertEqual(self.rate.values(), rate_before)
            self.assertNotEqual(self.angle.values(), angle_before)
            self.assertFalse(any(call.called for call in writes))
        self.assertEqual(self.link.read_group(2), rate_before)
        self.assertEqual(self.link.read_group(3), angle_before)

    def test_one_explicit_apply_preserves_precision_and_unrelated_groups(self):
        actual = self.link.read_group(2)
        actual[8] = .000003456789
        self.link.values[2] = list(actual)
        self.click(self.rate.buttons['read'])
        self.wait(lambda: not self.rate.busy)
        self.assertEqual(self.rate.values(), actual)
        angle = self.link.saved[3][:]
        self.angle.inputs[0].setValue(2.314)
        self.rate.inputs[1].setValue(1.326)
        with patch.object(self.link, 'action', wraps=self.link.action) as action:
            self.apply(self.rate)
        payload = action.call_args.args
        self.assertEqual(action.call_count, 1)
        self.assertEqual((payload[0], payload[1][:2]), (137, [2, False]))
        expected = list(actual)
        expected[1] = 1.326
        self.assertEqual(payload[1][2:], expected)
        self.assertEqual(self.link.saved[2], expected)
        self.assertEqual(self.link.saved[3], angle)
        self.assertTrue(self.angle.inputs[0].property('changed'))
        self.assertIn('SAVED', self.rate.note.text())
        self.assertFalse(any(item.property('changed') for item in self.rate.inputs))

    def test_changing_flight_input_keeps_existing_setup_and_local_gain_draft(self):
        active = self.link.read_group(3)
        self.angle.inputs[2].setValue(.251)
        self.w.navigate(0)
        self.w._select_source_value(2)
        self.click(self.w.source_apply)
        self.wait(lambda: self.link.source == 2 and not self.w.command_busy)
        self.assertEqual(self.link.saved[134][1], 2)
        self.w.navigate(2)
        self.assertTrue(self.angle.inputs[2].property('changed'))
        self.assertEqual(self.angle.values()[2], .251)
        self.assertEqual(self.angle.active, active)
        self.assertEqual(self.link.saved[3], active)
        self.assertEqual(self.link.read_group(130)[:2], [False, True])
        self.assertFalse(self.w._running())

    def test_mismatched_stored_readback_is_unverified_until_same_group_reapplied(self):
        read = self.link.read_group
        def wrong_saved(group, schema=1, saved=False, **kwargs):
            result = read(group, schema, saved, **kwargs)
            if group == 2 and saved:
                bits = struct.unpack('!I', struct.pack('!f', result[0]))[0]
                result[0] = struct.unpack('!f', struct.pack('!I', bits + 1))[0]
            return result
        self.rate.inputs[0].setValue(1.402)
        with patch.object(self.link, 'read_group', side_effect=wrong_saved):
            self.apply(self.rate)
        self.w.render_status(time.monotonic())
        self.assertIn('differs', self.rate.note.text().lower())
        self.assertIn('unverified', self.w.pid_state.text().lower())
        self.assertIn('rate', self.w.pid_state.text().lower())
        self.assertTrue(self.rate.inputs[0].property('changed'))
        self.angle.inputs[0].setValue(3.31)
        self.apply(self.angle)
        self.assertIn('unverified', self.w.pid_state.text().lower())
        self.apply(self.rate)
        self.assertNotIn('unverified', self.w.pid_state.text().lower())
        self.assertIn('SAVED', self.rate.note.text())
        self.assertEqual(self.link.saved[2][0], 1.402)

    def test_explicit_bench_angle_apply_defers_storage_until_disarm(self):
        self.w.navigate(0)
        self.click(self.w.pid_live_confirm)
        self.assertTrue(self.w.pid_live_confirm.isChecked())
        self.w.start_stream()
        self.wait(lambda: self.w.session.ready)
        self.w.arm()
        self.wait(lambda: self.link.armed and not self.w.command_busy)
        self.w.navigate(2)
        self.wait(lambda: self.angle.buttons['apply'].isEnabled())
        previous = self.link.saved[3][:]
        self.angle.inputs[5].setValue(.1567)
        self.apply(self.angle)
        self.assertTrue(self.link.armed, self.w.log_view.toPlainText())
        self.assertEqual(self.link.saved[3], previous)
        self.assertIn('pending', self.angle.note.text().lower())
        self.assertEqual(self.link.values[3][5], .1567)
        self.w.stop('Test stop')
        self.wait(lambda: not self.link.armed and self.link.saved[3][5] == .1567)
        self.wait(lambda: 'SAVED' in self.angle.note.text())
        self.assertNotIn('pending', self.angle.note.text().lower())
