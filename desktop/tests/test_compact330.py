"""Compact actions remain keyboard accessible without accidental dialog defaults."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout
from areion_gui.widgets import button


class CompactActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_action_uses_label_width_and_keyboard_activation(self):
        dialog=QDialog();layout=QVBoxLayout(dialog);calls=[]
        action=button('Read FC',lambda:calls.append('read'))
        layout.addWidget(action);dialog.resize(800,200);dialog.show();QTest.qWait(30)
        try:
            self.assertLess(action.width(),dialog.width()/2)
            self.assertFalse(action.autoDefault())
            action.setFocus();QTest.keyClick(action,Qt.Key.Key_Space)
            self.assertEqual(calls,['read'])
            action.setEnabled(False);QTest.keyClick(action,Qt.Key.Key_Space)
            self.assertEqual(calls,['read'])
        finally:
            dialog.close()
