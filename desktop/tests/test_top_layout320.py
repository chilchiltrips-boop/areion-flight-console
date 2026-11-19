"""Top navigation preserves control guards, shared connection state and honest rates."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,unittest
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from fc_fixture import make_test_window
from areion_gui.link_activity import ActivityRates
from setup_fixtures import complete_demo_window
from test_actions_sdk import connected_link


class ActivityTests(unittest.TestCase):
    def path(self,tx,rx,age=.01):
        return {'name':'USB','sent_frames':tx,'received_frames':rx,'active':True,'confirmed':True,'last_received_age':age,'rejected_frames':0}

    def test_rates_use_counter_deltas_and_reset_on_session_change(self):
        meter=ActivityRates();meter.update([self.path(500,1000)],'kit-a',0,True)
        state=meter.update([self.path(525,1050)],'kit-a',.5,True)
        self.assertEqual((state['tx'],state['rx']),(50,100));self.assertTrue(state['fresh'])
        state=meter.update([self.path(1,2)],'kit-b',1,True)
        self.assertEqual((state['tx'],state['rx']),(0,0))

    def test_idle_offline_stale_and_demo_are_not_signal_strength(self):
        meter=ActivityRates();meter.update([self.path(1,5)],'a',0,True)
        self.assertEqual(meter.update([self.path(1,5)],'a',1,True)['tx'],0)
        self.assertFalse(meter.update([self.path(1,5,2)],'a',2,True)['fresh'])
        self.assertIsNone(meter.update([self.path(1,5)],'a',3,False)['rx'])
        self.assertIsNone(meter.update([self.path(10,20)],'a',4,True,True)['rx'])

    def test_sdk_counts_successful_writes_on_selected_paths(self):
        link,usb,ap=connected_link();link.arm(serial_only=True)
        self.assertEqual([p['sent_frames'] for p in link.transport_status],[1,0])
        link.disarm();self.assertEqual([p['sent_frames'] for p in link.transport_status],[2,1])

    def test_sdk_retry_counts_traffic_without_changing_command_identity(self):
        link,usb,ap=connected_link();usb.reply_after=2;link.arm(serial_only=True)
        self.assertEqual(link.transport_status[0]['sent_frames'],2)
        self.assertEqual(usb.sent[0],usb.sent[1])

    def test_failed_write_does_not_increment_counter(self):
        link,usb,ap=connected_link()
        with patch.object(usb,'send',side_effect=OSError('unplugged')):link.disarm()
        self.assertEqual([p['sent_frames'] for p in link.transport_status],[0,1])
        self.assertFalse(link.transport_status[0]['active'])


class TopLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.temp.name):self.w=make_test_window()
        self.w.resize(1120,760);self.w.show();QTest.qWait(200)
        complete_demo_window(self.w,source=1);self.w.render_status(time.monotonic())

    def tearDown(self):
        self.w.close();QTest.qWait(200);self.temp.cleanup()

    def test_firmware_page_matches_connection_qualification_and_labels_demo(self):
        self.w.navigate(9)
        now=time.monotonic()
        self.w._render_console(now,True,None,None)
        self.assertIn('Simulated firmware',self.w.firmware_info.text())
        self.assertNotIn('Version mismatch',self.w.firmware_info.text())
        for version,expected in [('3.1.0','Compatible'),('3.2.0','Compatible'),('4.0.0','Version mismatch')]:
            values=self.w.link.read_group(125);values[0]=version
            self.w.data.put(125,1,values,now)
            with patch.object(self.w.link,'demo',False):
                self.w._render_console(now,True,None,None)
            self.assertIn(expected,self.w.firmware_info.text())

    def test_compact_top_navigation_fits_minimum_window_and_stays_visible(self):
        self.assertEqual(self.w.navigation_bar.height(),44)
        self.assertLess(self.w.navigation_bar.mapTo(self.w,QPoint()).y(),90)
        for index in (7,0,2,4,8,9,1,6,10,11):
            self.w.navigate(index);QTest.qWait(30)
            self.assertTrue(self.w.stop_button.isVisible());self.assertTrue(self.w.connect_button.isVisible())
            for control in self.w.nav+[self.w.link_activity,self.w.transport,self.w.endpoint_button,self.w.disconnect_button]:
                self.assertGreaterEqual(control.x(),0)
                self.assertLessEqual(control.x()+control.width(),self.w.navigation_bar.width())
        self.assertFalse(self.w.nav[5].isEnabled());self.assertFalse(self.w.flash_button.isEnabled())
        self.assertIsNone(self.w._setup_wizard)

    def test_inspection_navigation_never_sends_setup_or_actuator_commands(self):
        with patch.object(self.w.link,'action',wraps=self.w.link.action) as action:
            for index in (7,9,8,4,3,10):self.w.navigate(index);QTest.qWait(35)
            action.assert_not_called()
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])

    def test_top_configuration_keeps_confirmed_pid_tuning_sender(self):
        self.w.pid_live_confirm.setChecked(True);self.w.start_stream();QTest.qWait(250)
        self.assertTrue(self.w.session.running)
        self.w.nav[2].click();QTest.qWait(60)
        self.assertEqual(self.w.pages.currentIndex(),2);self.assertTrue(self.w.session.running)
        self.w.nav[4].click();QTest.qWait(150)
        self.assertFalse(self.w.session.running)

    def test_connection_edits_are_shared_and_do_not_change_flight_input(self):
        self.w.navigate(6);saved=self.w.link.saved[134][1]
        with patch.object(self.w.link,'action',wraps=self.w.link.action) as action:
            self.w.show_connection_settings();QTest.qWait(40)
            self.w.transport.setCurrentText('AP');self.w.host.setText('192.168.4.2');self.w.port.setEditText('/dev/kit')
            self.w.connection_dialog.accept();QTest.qWait(40)
            action.assert_not_called()
        options=self.w._connection_options()
        self.assertEqual(options['mode'],'AP');self.assertEqual(options['host'],'192.168.4.2')
        self.assertEqual(self.w.link.saved[134][1],saved);self.assertEqual(self.w.pages.currentIndex(),6)
        with patch('areion_gui.window.open_link',side_effect=RuntimeError('test connection attempt')) as connect:
            self.w.connect_button.click();QTest.qWait(200)
            self.assertEqual(connect.call_args[0][0]['host'],'192.168.4.2')
        self.assertEqual(self.w.pages.currentIndex(),6)

    def test_header_mode_and_dialog_values_ignore_mouse_wheel(self):
        self.w.show_connection_settings();QTest.qWait(40)
        for widget in (self.w.transport,self.w.baud,self.w.port):
            before=widget.currentIndex() if hasattr(widget,'currentIndex') else widget.value()
            point=widget.rect().center()
            event=QWheelEvent(QPointF(point),QPointF(widget.mapToGlobal(point)),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            QApplication.sendEvent(widget,event)
            after=widget.currentIndex() if hasattr(widget,'currentIndex') else widget.value()
            self.assertEqual(before,after)
        self.w.connection_dialog.accept()

    def test_wizard_compact_step_picker_retains_gates(self):
        self.w.resize(1280,800);self.w.navigate(5);QTest.qWait(200);wizard=self.w.setup_wizard
        self.assertTrue(wizard.connection_card.isHidden())
        self.assertTrue(all(button.isVisible() for button in wizard.step_buttons))
        self.assertTrue(wizard.step_picker.isHidden())
        self.assertFalse(wizard.step_buttons[3].isEnabled())
        self.w.resize(900,700);QTest.qWait(20)
        self.assertTrue(all(button.isHidden() for button in wizard.step_buttons))
        self.assertTrue(wizard.step_picker.isVisible())
        self.assertFalse(wizard.step_picker.model().item(3).isEnabled())
        wizard._pick_step(3)
        self.assertEqual(wizard.step, 0)
        wizard.propeller_check.setChecked(True);QTest.qWait(50)
        self.assertTrue(wizard.step_picker.model().item(3).isEnabled())
        wizard.step_picker.activated.emit(3);QTest.qWait(30)
        self.assertEqual(wizard.step,3);self.assertEqual(wizard.step_progress.value(),4)
        self.w.resize(1280,800);QTest.qWait(20)
        self.assertTrue(wizard.step_buttons[3].isChecked())
        wizard._set_message('Check sensor connection', error=True)
        wizard._update_navigation()
        self.assertEqual(wizard.step_buttons[3].state, 'error')
        wizard._set_message('Sensor readings available');wizard._update_navigation()
        self.assertNotEqual(wizard.step_buttons[3].state, 'error')

    def test_receiver_page_requires_ppm_and_unsaved_edits_block_finish(self):
        self.w.navigate(11);QTest.qWait(100);panel=self.w._maintenance['receiver']
        panel.propeller_check.setChecked(True);QTest.qWait(50)
        self.assertFalse(panel.begin_button.isEnabled())
        complete_demo_window(self.w,source=0);QTest.qWait(120)
        self.assertTrue(panel.begin_button.isEnabled());panel.begin_button.click();QTest.qWait(220)
        self.assertTrue(panel._ready(),panel.last_error)
        self.assertTrue(panel._finish_ready())
        panel.rx_reverse[0].setChecked(True);QTest.qWait(50)
        self.assertFalse(panel._finish_ready());self.assertTrue(self.w.link.read_group(130)[0])

    def test_receiver_capture_is_cancelled_on_navigation(self):
        complete_demo_window(self.w,source=0);self.w.navigate(11);QTest.qWait(100)
        panel=self.w._maintenance['receiver'];panel.propeller_check.setChecked(True);panel.begin_button.click();QTest.qWait(220)
        self.assertTrue(panel.rx_start.isEnabled(),panel.last_error);panel.rx_start.click()
        self.assertIsNotNone(panel.rx_capture);self.assertFalse(panel._finish_ready())
        self.w.nav[0].click();QTest.qWait(50)
        self.assertIsNone(panel.rx_capture);self.assertTrue(self.w.link.read_group(130)[0])

if __name__=='__main__':unittest.main()
