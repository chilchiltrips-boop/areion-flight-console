"""Receiver scope tests use received telemetry and ordinary Qt button clicks."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from areion_gui.model import Telemetry
from areion_gui.scope_data import frozen_telemetry
from areion_gui.scope_receiver import ScopeReceiver
from zebjus_areion_link.schema import DRONE_GROUPS


def source_status(source=0, count=8, age=3, ready=True):
    return [source, source+1 if ready else 0, source==0, source==1, ready, count,
            age, 79, source==2]


class ReceiverScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.data = Telemetry()
        self.panel = ScopeReceiver()
        self.panel.resize(790, 330)
        self.panel.show()
        self.app.processEvents()
        self.addCleanup(self.panel.close)
        self.row = [1925, 1494, 1070, 1510, 1500, 1250, 1980, 2100]
        self.calibration = [980,1490,2010,0]*8
        self.calibration[3] = 1
        self.put(132, self.calibration, 4, False)
        self.put(134, [0,0,2,1,3,4,5,1110,1115,1120,1125], 4, False)
        self.put(7, [5,.1,.15,.15,0,1], 4, False)

    def put(self, group, values, at, received=True):
        self.assertTrue(self.data.put(group,DRONE_GROUPS[group]['schema'],values,
                                      now=at,received=received))

    def refresh(self, now, connected=True):
        self.panel.refresh(self.data,now,connected)

    def values(self):
        return [track.value for track in self.panel.bars]

    def test_ppm_physical_and_logical_views_and_absent_aux(self):
        self.put(122,source_status(count=6),10.)
        self.put(22,self.row,10.02)
        self.put(131,self.row[:6]+[0,0,6,True,4],10.02)
        self.refresh(10.04)
        self.assertIn('PPM',self.panel.source_label.text())
        self.assertEqual(self.values(),self.row[:6]+[None,None])
        self.assertEqual(self.panel.labels[0][1].text(),'Roll  ·  CH2')
        self.assertFalse(self.panel.headers[4].isVisible())
        QTest.mouseClick(self.panel.raw_button,Qt.MouseButton.LeftButton)
        self.assertEqual(self.panel.labels[0][1].text(),'Pitch')
        self.assertEqual(self.panel.labels[4][1].text(),'Mode · RATE / ACRO')
        self.assertEqual(self.panel.labels[0][7].text(),'Reversed')
        self.assertEqual(self.panel.bars[0].marks,(980,1490,2010))
        self.assertEqual(self.values()[-2:],[None,None])
        self.assertTrue(self.panel.headers[4].isVisible())
        self.assertLessEqual(self.panel.minimumSizeHint().height(),330)

    def test_readbacks_source_changes_and_loss_do_not_relabel_old_controls(self):
        self.put(122,source_status(),7.,False)
        self.put(22,self.row,7.,False)
        self.refresh(7.1)
        self.assertEqual(self.values(),[None]*8)
        self.put(122,source_status(),8.)
        self.put(22,self.row,8.02)
        self.refresh(8.04)
        self.assertEqual(self.values(), self.row)
        self.put(122,source_status(source=2),8.04)
        self.refresh(8.05)
        self.assertEqual(self.values(),[None]*8)
        self.put(22,self.row,8.06)
        self.refresh(8.07)
        self.assertEqual(self.values(), self.row)
        self.assertEqual(self.panel.labels[0][1].text(),'Roll')
        self.assertIn('USB',self.panel.source_label.text())
        self.put(122,source_status(source=2,ready=False),8.08)
        self.refresh(8.1)
        self.assertEqual(self.values(),[None]*8)
        self.put(122,source_status(source=1),8.12)
        self.refresh(8.13)
        self.assertEqual(self.values(),[None]*8)
        self.put(22,self.row,8.14)
        self.refresh(8.16)
        self.assertEqual(self.values(),self.row)
        self.assertIn('AP',self.panel.source_label.text())
        self.refresh(8.16,False)
        self.assertEqual(self.values(),[None]*8)

    def test_raw_frame_age_source_independence_and_frozen_values(self):
        self.put(122,source_status(source=1),5.)
        self.put(131,self.row+[8,True,200],5.01)
        self.refresh(5.02)
        self.panel.raw_button.click()
        self.assertEqual(self.values(),self.row)
        self.assertIn('AP',self.panel.source_label.text())
        hold=frozen_telemetry(self.data)
        self.refresh(5.07)
        self.assertEqual(self.values(),self.row)
        self.panel.refresh(hold,5.02,True,True)
        self.assertEqual(self.values(),self.row)
        self.assertIn('Held',self.panel.status_label.text())
        self.put(131,self.row+[8,False,220],5.07)
        self.refresh(5.08)
        self.assertEqual(self.values(),[None]*8)
        self.refresh(6.)
        self.assertIn('stale',self.panel.status_label.text())

    def test_read_only_tracks_respect_fc_age_and_desktop_status_expiry(self):
        self.put(122,source_status(age=200),10.)
        self.put(22,self.row,10.01)
        self.refresh(10.02)
        self.assertEqual(self.values(),self.row)
        for track in self.panel.bars:
            self.assertTrue(track.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.refresh(10.06)
        self.assertEqual(self.values(),self.row)
        self.put(122,source_status(age=250),10.07)
        self.refresh(10.07)
        self.assertEqual(self.values(),[None]*8)
        self.assertIn('expired',self.panel.status_label.text())
        self.put(122,source_status(age=8),10.15)
        self.put(22,self.row,10.16)
        self.refresh(10.45)
        self.assertEqual(self.values(),self.row)
        self.put(22,self.row,10.65)
        self.refresh(10.66)
        self.assertEqual(self.values(),[None]*8)
        self.assertIn('status stale',self.panel.status_label.text())


if __name__ == '__main__':
    unittest.main()
