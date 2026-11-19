"""Real offscreen Qt events plus control/settings tests; no physical hardware."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from areion_gui.model import Controls, Telemetry, NEUTRAL, DEFAULT_KEYS, validate_values
from fc_fixture import DemoLink, make_test_window
from areion_gui.backend import apply_section, save_section, open_link
from setup_fixtures import complete_demo_setup, complete_demo_window

class ModelTests(unittest.TestCase):
    def test_transmitter_spring_return_and_throttle_hold(self):
        c=Controls();c.stick(True,1,.5,True)
        self.assertEqual(c.values[2:4],[1750,2000]);c.stick(True,0,.5,False)
        self.assertEqual(c.values[2:4],[1750,1500])
        c.stick(False,1,-1,True);self.assertEqual(c.values[:2],[2000,1000])
        c.stick(False,0,0,False);self.assertEqual(c.values[:2],[1500,1500])

    def test_held_keys_step_throttle_and_spring_axes(self):
        c=Controls();c.key('W',True);c.key('Right',True)
        for _ in range(10):c.step(.02,True)
        self.assertEqual(c.values[2],1100);self.assertEqual(c.values[0],2000)
        c.key('W',False);c.key('Right',False);c.step(.02,True)
        self.assertEqual(c.values[2],1100);self.assertEqual(c.values[0],1500)
        c.key('8',True);self.assertEqual(c.values[7],2000)

    def test_key_mapping_rejects_duplicates_reserved_and_bad_shape(self):
        c=Controls()
        for keys in ([('A','D')]*8, DEFAULT_KEYS[:-1], [('Escape','W')]+DEFAULT_KEYS[1:]):
            with self.assertRaises(ValueError):c.set_bindings(keys)
        keys=list(DEFAULT_KEYS);keys[2]=('X','Z');c.set_bindings(keys)
        c.key('Z',True);c.step(.02,True);self.assertEqual(c.values[2],1010)

    def test_telemetry_rejects_invalid_layout_nan_and_stale(self):
        t=Telemetry();self.assertFalse(t.put(21,1,[0]*9,10))
        self.assertFalse(t.put(21,1,[float('nan')]+[0]*9,10))
        self.assertTrue(t.put(21,1,[0]*10,10))
        self.assertIsNone(t.values(21,.5,11));self.assertEqual(t.values(21)[0],0)
        for i in range(700):t.put(21,1,[i]*10,i)
        self.assertEqual(len(t.history[(21,0)]),600)

    def test_settings_types_ranges_and_disarmed_guard(self):
        link=DemoLink()
        with self.assertRaises(ValueError):apply_section(link,112,[True,250])
        with self.assertRaises(ValueError):apply_section(link,112,[49,250])
        complete_demo_setup(link)
        link.send_control(NEUTRAL,datagram_only=True);link.arm()
        with self.assertRaises(ValueError):apply_section(link,6,[-.1,.03,.12])

    def test_save_verifies_active_and_stored_copy(self):
        link=DemoLink();values=[-.11,.02,.13]
        apply_section(link,6,values)
        self.assertNotEqual(link.saved[6],values)
        self.assertEqual(save_section(link,6,values),values)
        with self.assertRaises(RuntimeError):save_section(link,6,[0,0,0])
        with patch.object(link,'save_group',return_value=['SAVED']):
            apply_section(link,6,[-.2,.02,.13])
            with self.assertRaises(RuntimeError):save_section(link,6,[-.2,.02,.13])

    def test_usb_failure_does_not_open_unrequested_ap(self):
        options={'mode':'USB','port':'COM_FAKE','baud':115200,'startup_wait':0,'ssid':'aerion drone','host':'192.168.4.1','udp_port':8080}
        with patch('areion_gui.backend.SerialTransport',side_effect=OSError('missing')),patch('areion_gui.backend.UDP') as udp:
            with self.assertRaises(RuntimeError):open_link(options,threading.Event())
            udp.assert_not_called()

    def test_connection_requires_setup_lock_firmware_version(self):
        options={'mode':'AP','ssid':'aerion drone','host':'192.168.4.1','udp_port':8080}
        for version in ('2.5.0','3.0.2','3.1.0','3.2.0','3.2.1','4.0.0','3.2.0 DEMO'):
            demo=DemoLink()
            def read(group, schema=1):
                values=demo.read_group(group,schema)
                if group==125:values[0]=version
                return values
            link=Mock(read_group=Mock(side_effect=read))
            with patch('areion_gui.backend.UDP',return_value=Mock(datagram=True)), \
                 patch('areion_gui.backend.check_wifi',return_value=None), \
                 patch('areion_gui.backend.Link',return_value=link):
                if version not in ('3.1.0','3.2.0'):
                    with self.assertRaisesRegex(RuntimeError,'setup ARM lock'):open_link(options,threading.Event())
                    link.close.assert_called_once()
                else:
                    self.assertIs(open_link(options,threading.Event())[0],link)
                    link.close.assert_not_called()
                link.send_control.assert_not_called()
                link.arm.assert_not_called()

class OfflineStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_link_until_connect_and_no_fallback_on_failure(self):
        from areion_gui.window import MainWindow

        with patch('areion_gui.window.open_link', side_effect=OSError('Kit unplugged')) as opened:
            window = MainWindow()
            try:
                window.show()
                QTest.qWait(50)
                opened.assert_not_called()
                self.assertEqual(window.pages.currentIndex(), 7)
                self.assertIsNone(window.link)
                window.select_usb_port('')
                window.connect_fc()
                opened.assert_not_called()
                self.assertIn('Choose a USB port', window.last_notice)
                window.select_usb_port('/dev/test-kit')
                window.connect_fc()
                deadline = time.monotonic() + 2
                while window.connecting and time.monotonic() < deadline:
                    QTest.qWait(15)
                opened.assert_called_once()
                self.assertFalse(window.connecting)
                self.assertIn('Kit unplugged', window.last_notice)
                self.assertIsNone(window.link)
                self.assertIsNone(window.session)
                self.assertIsNone(window.data.values(120))
            finally:
                window.close()
                QTest.qWait(50)


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');cls.app.setOrganizationName('ZebjusTest');cls.app.setApplicationName('AreionTest')

    def setUp(self):
        self.w=make_test_window();self.w.show();QTest.qWait(250)

    def tearDown(self):
        self.w.close();QTest.qWait(250)

    def ready(self):
        complete_demo_window(self.w)
        self.w.navigate(0);self.w.start_stream();QTest.qWait(450)
        self.assertTrue(self.w.session.running,self.w.last_notice)
        self.assertTrue(self.w.session.ready,self.w.last_notice)

    def test_neutral_start_arm_mouse_control_and_stop(self):
        self.ready();self.w.arm();QTest.qWait(150);self.assertTrue(self.w.link.armed)
        stick=self.w.right_stick;c,r=stick.geometry_values()
        QTest.mousePress(stick,Qt.MouseButton.LeftButton,pos=QPoint(round(c.x()+r*.7),round(c.y())))
        QTest.qWait(35);self.assertGreater(self.w.link.channels[0],1900)
        QTest.mouseRelease(stick,Qt.MouseButton.LeftButton,pos=QPoint(round(c.x()),round(c.y())))
        QTest.qWait(35);self.assertEqual(self.w.link.channels[0],1500)
        self.w.stop('test');QTest.qWait(150)
        self.assertFalse(self.w.link.armed);self.assertFalse(self.w.session.running)
        self.assertEqual(self.w.controls.values,NEUTRAL)

    def test_keyboard_changes_channels_and_escape_stops(self):
        self.ready();self.w.setFocus()
        QTest.keyPress(self.w,Qt.Key.Key_W);QTest.qWait(100);QTest.keyRelease(self.w,Qt.Key.Key_W)
        self.assertGreater(self.w.controls.values[2],1000)
        QTest.keyClick(self.w,Qt.Key.Key_Escape);QTest.qWait(120)
        self.assertFalse(self.w.session.running);self.assertEqual(self.w.controls.values,NEUTRAL)

    def test_popup_arrows_select_without_transmitter_input(self):
        self.w.navigate(0)
        self.w.keyboard.setChecked(True)
        self.w.source_box.setCurrentIndex(self.w.source_box.findData(2))
        self.w.source_box.setEnabled(True)
        self.w.source_box.showPopup()
        self.app.processEvents()
        view = self.w.source_box.view()
        self.assertIsNotNone(self.app.activePopupWidget())
        row = view.currentIndex().row()
        with patch.object(self.w.controls, 'key', wraps=self.w.controls.key) as send_key:
            QTest.keyClick(view, Qt.Key.Key_Down)
            self.assertEqual(view.currentIndex().row(), row + 1)
            self.assertNotIn(('Down', True), [call.args for call in send_key.call_args_list])
        QTest.keyClick(view, Qt.Key.Key_Escape)
        self.assertFalse(view.isVisible())

    def test_editing_port_does_not_act_as_keyboard_transmitter(self):
        self.w.port.setFocus();self.w.port.lineEdit().setFocus()
        QTest.keyPress(self.w.port.lineEdit(),Qt.Key.Key_W);QTest.qWait(60);QTest.keyRelease(self.w.port.lineEdit(),Qt.Key.Key_W)
        self.assertEqual(self.w.controls.values,NEUTRAL)

    def test_focus_loss_and_page_change_stop_without_resume(self):
        self.ready();token=self.w.session.cancel_arm
        QApplication.sendEvent(self.w,QEvent(QEvent.Type.WindowDeactivate));QTest.qWait(150)
        self.assertFalse(self.w.session.running);self.assertTrue(token.is_set())
        self.w._application_state(Qt.ApplicationState.ApplicationActive);QTest.qWait(100)
        self.assertFalse(self.w.session.running)
        self.ready();self.w.navigate(1);QTest.qWait(150);self.assertFalse(self.w.session.running)

    def test_ppm_selected_does_not_send_gui_channels(self):
        self.w._select_source_value(0);self.w.select_source();QTest.qWait(150)
        self.assertEqual(self.w.link.source,0);self.assertFalse(self.w.start_button.isEnabled())
        self.w.start_stream();QTest.qWait(150);self.assertFalse(self.w.session.running)

    def test_sender_stall_stops_before_resending(self):
        self.ready();time.sleep(.18);QTest.qWait(120)
        self.assertFalse(self.w.session.running);self.assertFalse(self.w.link.armed)

    def test_settings_read_apply_save_and_visible_text(self):
        card=self.w.cards[6];self.w.navigate(1);QTest.qWait(120)
        self.assertTrue(card.loaded);self.assertGreater(card.inputs[0].lineEdit().width(),20)
        card.inputs[0].setValue(-.15)
        self.assertFalse(card.buttons['save'].isEnabled())
        card._request('apply');QTest.qWait(150)
        self.assertEqual(self.w.link.values[6][0],-.15);self.assertNotEqual(self.w.link.saved[6][0],-.15)
        card._request('save');QTest.qWait(150);self.assertEqual(self.w.link.saved[6][0],-.15)
        self.assertIn('SAVED',card.note.text())

    def test_arm_uses_configured_fc_throttle_threshold(self):
        values=self.w.link.values[4][:];values[0]=1100
        self.w.settings_request(4,'apply',values);QTest.qWait(120)
        self.ready();self.w.controls.values[2]=1070;QTest.qWait(45)
        self.w.arm();QTest.qWait(150)
        self.assertTrue(self.w.link.armed,self.w.last_notice)
        self.w.stop('test');QTest.qWait(120)

    def test_cancel_inflight_arm_before_disarm(self):
        self.ready();entered=threading.Event()
        def delayed(cancel=None,**kwargs):
            entered.set();cancel.wait(.8)
            if cancel.is_set():raise RuntimeError('cancelled')
            self.w.link.armed=True;return ['ARMED']
        with patch.object(self.w.link,'arm',side_effect=delayed):
            self.w.arm();QTest.qWait(25);self.assertTrue(entered.is_set())
            self.w.stop('cancel ARM');QTest.qWait(180)
        self.assertFalse(self.w.link.armed);self.assertFalse(self.w.session.running)

    def test_stale_imu_gauges_blank_and_table_marks_stale(self):
        self.w.timer.stop();now=time.monotonic()
        values,_=self.w.data.latest[21];self.w.data.latest[21]=(values,now-1)
        self.w.render_status(now)
        self.assertEqual(self.w.imu_metrics[0].value.text(),'—')
        # Hidden live-table cells are intentionally deferred. Entering the
        # page must immediately label the same cached sample as stale.
        self.w.navigate(4)
        rows=[r for r,(group,_,_) in enumerate(self.w.table_rows) if group==21]
        self.assertTrue(all(self.w.table.item(r,4).text()=='STALE' for r in rows))

if __name__=='__main__':unittest.main()
