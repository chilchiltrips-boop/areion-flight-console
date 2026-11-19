"""Top navigation remains reachable when width or text metrics change."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QRect
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from fc_fixture import make_test_window
from areion_gui.link_activity import LinkActivity


class HeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.temp.name):
            self.w=make_test_window()
        self.w.resize(1120,760);self.w.show();QTest.qWait(100)

    def tearDown(self):
        self.w.close();QTest.qWait(100);self.temp.cleanup()

    def assert_controls_fit(self):
        bar=self.w.navigation_bar
        controls=self.w.nav+[self.w.link_activity,self.w.transport,self.w.endpoint_button,
                            self.w.connect_button,self.w.disconnect_button]
        rectangles=[]
        for control in controls:
            self.assertTrue(control.isVisible())
            rect=QRect(control.mapTo(bar,QPoint()),control.size())
            self.assertTrue(bar.rect().contains(rect),str(rect))
            for other in rectangles:
                self.assertFalse(rect.intersects(other),(rect,other))
            rectangles.append(rect)
        self.assertTrue(self.w.stop_button.isVisible())

    def test_standard_header_keeps_single_row_and_all_controls(self):
        self.assertEqual(self.w.width(),1120)
        self.assertEqual(self.w.navigation_bar.height(),44)
        self.assert_controls_fit()

    def test_connection_group_wraps_when_text_needs_more_space(self):
        self.w.navigation_routes.setStyleSheet('QPushButton {font-size:18px;}')
        QTest.qWait(100)
        self.assertGreater(self.w.navigation_bar.height(),44)
        self.assertGreater(self.w.connection_controls.y(),self.w.navigation_routes.y())
        self.assert_controls_fit()
        # Enlarged labels still perform the original route action.
        self.w.nav[6].click();QTest.qWait(30)
        self.assertEqual(self.w.pages.currentIndex(),9)

    def test_narrow_header_wraps_without_widening_window(self):
        self.w.resize(900,760);QTest.qWait(100)
        self.assertEqual(self.w.width(),900)
        self.assertGreater(self.w.navigation_bar.height(),44)
        self.assert_controls_fit()

    def test_activity_does_not_repaint_identical_state_each_ui_tick(self):
        meter=LinkActivity()
        path=dict(name='AP',sent_frames=10,received_frames=20,active=True,
                  confirmed=True,last_received_age=.01,rejected_frames=0)
        meter.refresh([path],'kit',0,True)
        with patch.object(meter,'update') as repaint,patch.object(meter,'setToolTip') as tip:
            for tick in range(1,10):meter.refresh([path],'kit',tick*.02,True)
            repaint.assert_not_called();tip.assert_not_called()
        meter.close()
