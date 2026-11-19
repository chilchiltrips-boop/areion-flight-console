"""Streaming data presentation stays bounded without blocking page navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication,QStyledItemDelegate
from fc_fixture import DemoLink
from areion_gui.window import MainWindow
from zebjus_areion_link.schema import DRONE_GROUPS


class CountingDelegate(QStyledItemDelegate):
    def __init__(self,parent):super().__init__(parent);self.calls=0
    def sizeHint(self,option,index):
        self.calls+=1;return super().sizeHint(option,index)


class LiveViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.tmp.name),patch.object(MainWindow,'refresh_ports'):
            self.w=MainWindow()
        self.w.timer.stop();self.link=DemoLink();self.w.link=self.link
        self.now=time.monotonic()
        for group in (2,3,4,6,7,112,21,22,23,110,120,121,122,125,130,131,132,134):
            self.put(group,self.link.read_group(group,DRONE_GROUPS[group]['schema']))
        self.w.show();self.app.processEvents()

    def tearDown(self):
        self.w.link=None;self.link.close();self.w.close();self.w.deleteLater()
        self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents();self.tmp.cleanup()

    def put(self,group,values):
        self.assertTrue(self.w.data.put(group,DRONE_GROUPS[group]['schema'],values,self.now))

    def row(self,group,index):
        return next(r for r,(g,i,_) in enumerate(self.w.table_rows) if (g,i)==(group,index))

    def text(self,group,index,column=2):return self.w.table.item(self.row(group,index),column).text()

    def test_hidden_table_waits_and_navigation_uses_cached_data_without_rpc(self):
        changed=[];self.w.table.model().dataChanged.connect(lambda *args:changed.append(args))
        self.w.render_status(self.now)
        self.assertEqual(changed,[]);self.assertEqual(self.text(21,0),'—')
        with patch.object(self.link,'read_group',side_effect=AssertionError('Navigation must not block on FC read')):
            self.w.navigate(4)
        self.assertNotEqual(self.text(21,0),'—');self.assertEqual(self.text(21,0,4),'LIVE')

    def test_unchanged_frame_does_not_rewrite_cells(self):
        self.w.navigate(4);self.w._render_live_data(self.now,True)
        changed=[];self.w.table.model().dataChanged.connect(lambda *args:changed.append(args))
        self.w._render_live_data(self.now,True)
        self.assertEqual(changed,[])

    def test_changed_field_updates_in_place_without_losing_selection_or_scroll(self):
        self.w.navigate(4);self.w._render_live_data(self.now,True);self.app.processEvents()
        row=self.row(21,0);self.w.table.setCurrentCell(row,2)
        self.w.table.verticalScrollBar().setValue(30);position=self.w.table.verticalScrollBar().value()
        changed=[];self.w.table.model().dataChanged.connect(lambda first,last,*args:changed.append((first.row(),first.column(),last.row(),last.column())))
        values=list(self.w.data.values(21));values[0]=12.25;self.put(21,values)
        self.w._render_live_data(self.now,True)
        self.assertEqual(self.text(21,0),'12.25');self.assertEqual(changed,[(row,2,row,2)])
        self.assertEqual(self.w.table.currentRow(),row);self.assertEqual(self.w.table.currentColumn(),2)
        self.assertEqual(self.w.table.verticalScrollBar().value(),position)

    def test_stale_offline_and_static_states_refresh_without_new_packets(self):
        self.w.navigate(4);self.w._render_live_data(self.now+.6,True)
        self.assertEqual(self.text(21,0,4),'STALE');self.assertEqual(self.text(2,0,4),'READ SNAPSHOT')
        self.w._render_live_data(self.now+.7,False)
        self.assertEqual(self.text(21,0,4),'OFFLINE');self.assertEqual(self.text(2,0,4),'OFFLINE')
        self.assertEqual(self.text(21,0,3),'0.7s')

    def test_event_log_defers_hidden_table_then_refreshes_latest_values(self):
        self.w.navigate(4);before=self.text(21,0);self.w.live_tabs.setCurrentIndex(1)
        values=list(self.w.data.values(21));values[0]=19.5;self.put(21,values)
        changed=[];self.w.table.model().dataChanged.connect(lambda *args:changed.append(args))
        self.w._render_live_data(self.now,True)
        self.assertEqual(changed,[]);self.assertEqual(self.text(21,0),before)
        self.w.live_tabs.setCurrentIndex(0)
        self.assertEqual(self.text(21,0),'19.5')

    def test_streaming_changes_do_not_trigger_full_table_size_scans(self):
        delegate=CountingDelegate(self.w.table);self.w.table.setItemDelegate(delegate)
        self.w.navigate(4);self.app.processEvents();delegate.calls=0
        widths=[self.w.table.columnWidth(c) for c in (0,2,3,4)]
        for n in range(20):
            values=list(self.w.data.values(21));values[0]=float(n);self.put(21,values)
            status=list(self.w.data.values(130));status[14]='SENSOR_DETAIL_'+'x'*(n+20);self.put(130,status)
            self.w._render_live_data(self.now+n*.1,True);self.app.processEvents()
        self.assertEqual(delegate.calls,0)
        self.assertEqual([self.w.table.columnWidth(c) for c in (0,2,3,4)],widths)
        self.assertEqual(self.text(21,0),'19')

    def test_hidden_plot_pages_are_not_rebuilt_but_history_is_collected(self):
        with patch.object(self.w.scopes_page,'refresh') as live,patch.object(self.w.imu_plots[0][0],'set_series') as imu:
            self.w.render_status(self.now);live.assert_not_called();imu.assert_not_called()
            values=list(self.w.data.values(21));values[0]=4.0;self.put(21,values)
            self.assertEqual(self.w.data.history[(21,0)][-1][1],4.0)
            self.w.navigate(4);live.assert_not_called();imu.assert_not_called()
            self.w.navigate(8);live.assert_called_once();imu.assert_not_called()
            self.w.navigate(1);self.w.render_status(self.now);imu.assert_called_once()


if __name__=='__main__':unittest.main()
