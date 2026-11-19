"""FC field order, draft precision and explicit local linked-axis editing."""
import os
import struct
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from zebjus_areion_link.schema import DRONE_GROUPS
from areion_gui.pid_matrix import PidMatrixCard


def f32(value):
    return struct.unpack('!f', struct.pack('!f', value))[0]


class PidMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def card(self, group, active=None):
        panel = PidMatrixCard(group)
        self.addCleanup(panel.close)
        panel.can_read = panel.allowed = True
        panel.finish('read', panel.defaults if active is None else active)
        return panel

    def test_wire_order_ranges_labels_and_independent_groups(self):
        for group, count, axes in ((2, 9, ('Roll', 'Pitch', 'Yaw')), (3, 6, ('Roll', 'Pitch'))):
            with self.subTest(group=group):
                panel = self.card(group)
                self.assertEqual(panel.axes, axes)
                self.assertEqual(len(panel.inputs), count)
                for field in DRONE_GROUPS[group]['fields']:
                    idx = field['index']
                    row, col = divmod(idx, len(axes))
                    cell = panel.gain_grid.itemAtPosition(row + 1, col + 1).widget()
                    self.assertIs(cell, panel.inputs[idx])
                    self.assertIn(axes[col], cell.accessibleName())
                    self.assertEqual((cell.minimum(), cell.maximum()), (field['min'], field['max']))
                    cell.setValue((idx + 1) / 10)
                sent = []
                panel.requested.connect(lambda g, cmd, vals: sent.append((g, cmd, vals)))
                panel.buttons['apply'].click()
                self.assertEqual(sent, [(group, 'apply', [(i + 1) / 10 for i in range(count)])])
                self.assertFalse(panel.revert_button.isEnabled())
                self.assertFalse(panel.link_check.isEnabled())

    def test_exact_untouched_gain_and_saved_copy_precision(self):
        baseline = [f32(.987654329), f32(.987654388), 3., 15., 15., 15., f32(.000000012345), .03, 0.]
        c = self.card(2, baseline)
        self.assertEqual(c.values(), baseline)
        self.assertFalse(any(w.property('changed') for w in c.inputs))
        c.inputs[5].setValue(24.)
        self.assertEqual(c.values(), baseline[:5] + [24.] + baseline[6:])
        saved = baseline[:]
        saved[6] = f32(.000000034567)
        c.finish('stored', saved)
        self.assertEqual(c.values(), saved)
        self.assertTrue(c.inputs[6].property('changed'))
        self.assertIn('not applied', c.note.text())
        self.assertEqual(c.active, baseline)
        c.revert_button.click()
        self.assertEqual(c.values(), baseline)
        self.assertFalse(c.inputs[6].property('changed'))
        self.assertFalse(c.revert_button.isEnabled())

    def test_link_pair_by_row_after_subsequent_edit_only(self):
        base = [.9, 1.1, 3., 12., 14., 15., .03, .04, .05]
        c = self.card(2, base)
        sent = []
        c.requested.connect(lambda *args: sent.append(args))
        c.link_check.setChecked(True)
        self.assertEqual(c.values(), base)
        c.inputs[4].setValue(16.5)
        self.assertEqual(c.values(), base[:3] + [16.5, 16.5] + base[5:])
        c.inputs[6].setValue(.125)
        self.assertEqual(c.values()[6:], [.125, .125, .05])
        c.inputs[2].setValue(4.)
        self.assertEqual(c.values()[:3], [.9, 1.1, 4.])
        c.link_check.setChecked(False)
        c.inputs[0].setValue(.8)
        self.assertEqual(c.values()[:3], [.8, 1.1, 4.])
        self.assertFalse(sent)
        c.revert_button.click()
        self.assertEqual(c.values(), base)
        self.assertFalse(sent)

    def test_stored_and_failed_commands_do_not_replace_active_baseline(self):
        c = self.card(3)
        c.inputs[0].setValue(3.1)
        draft = c.values()
        c.buttons['apply'].click()
        c.finish('apply', error='Stored readback differs.')
        self.assertEqual(c.note.text(), 'Stored readback differs.')
        self.assertEqual(c.values(), draft)
        self.assertEqual(c.active, c.defaults)
        self.assertTrue(c.inputs[0].property('changed'))
        c.finish('read', error='Link timed out.')
        self.assertEqual(c.values(), draft)
        c.link_check.setChecked(True)
        c.active, c.loaded, c.allowed, c.can_read = None, False, False, False
        c.refresh()
        self.assertFalse(c.link_check.isChecked())
        self.assertFalse(c.buttons['apply'].isEnabled())
        self.assertFalse(c.revert_button.isEnabled())
        self.assertEqual(c.values(), c.defaults)
        self.assertIn('defaults', c.note.text().lower())

    def test_saved_only_read_is_inspectable_and_clears_when_kit_leaves(self):
        panel = PidMatrixCard(3)
        self.addCleanup(panel.close)
        panel.can_read = True
        stored = [9.5] * 6
        panel.finish('stored', stored)
        panel.refresh()
        self.assertEqual(panel.values(), stored)
        self.assertIsNone(panel.active)
        self.assertFalse(panel.buttons['apply'].isEnabled())
        panel.can_read = False
        panel.refresh()
        self.assertEqual(panel.values(), panel.defaults)
        self.assertIn('defaults', panel.note.text().lower())

    def test_keyboard_commit_and_local_revert_do_not_write_fc(self):
        c = self.card(3)
        c.show()
        QTest.qWait(10)
        sent = []
        c.requested.connect(lambda *args: sent.append(args))
        c.link_check.setChecked(True)
        item = c.inputs[1]
        item.setFocus()
        item.selectAll()
        QTest.keyClicks(item, '4.125')
        QTest.keyClick(item, Qt.Key.Key_Return)
        self.assertEqual(c.values()[:2], [4.125, 4.125])
        self.assertEqual(c.note.text(), '2 edited gains')
        c.revert_button.click()
        self.assertEqual(c.values(), c.defaults)
        self.assertFalse(sent)


if __name__ == '__main__':
    unittest.main()
