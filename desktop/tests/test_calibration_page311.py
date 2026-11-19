"""Direct calibration pages use firmware locking/persistence without a wizard."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from fc_fixture import make_test_window
from areion_gui.backend import apply_pid
from setup_fixtures import complete_demo_window

class DirectCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.temp.name):
            self.w=make_test_window()
        self.w.resize(1120,760);self.w.show();QTest.qWait(220)
        complete_demo_window(self.w,1);self.w.render_status(time.monotonic())

    def tearDown(self):
        self.w.close();QTest.qWait(200);self.temp.cleanup()

    def open(self,scope):
        if scope=='imu':self.w.navigate(1);self.w.imu_tabs.setCurrentIndex(1)
        else:self.w.navigate(6)
        QTest.qWait(100)
        return self.w._maintenance[scope]

    def begin(self,scope):
        page=self.open(scope);page.propeller_check.setChecked(True);QTest.qWait(60)
        self.assertTrue(page.begin_button.isEnabled(),page.last_message)
        page.begin_button.click();QTest.qWait(250)
        self.assertTrue(page._ready(),page.last_message)
        self.assertEqual(self.w.link.read_group(130)[:2],[True,False]);return page

    def test_opening_direct_pages_is_read_only_and_transmitter_is_dark(self):
        with patch.object(self.w.link,'action',wraps=self.w.link.action) as action:
            self.open('imu');self.open('esc');QTest.qWait(100)
            action.assert_not_called()
        self.assertIsNone(self.w._setup_wizard)
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])
        self.assertFalse(self.w.left_stick.light);self.assertFalse(self.w.right_stick.light)
        self.assertEqual(self.w.pages.count(),12)
        for panel in self.w._maintenance.values():
            self.assertTrue(panel.step_label.isHidden())
            self.assertTrue(all(button.isHidden() for button in panel.step_buttons))

    def test_imu_save_and_finish_preserve_unrelated_pid_and_input(self):
        page=self.begin('imu');prior={g:self.w.link.saved[g][:] for g in (2,3,4,7,112,132,134)}
        self.assertFalse(self.w._setup_arm_allowed())
        page.sensor_panel.offsets[0].setValue(-.11);page.orientation_check.setChecked(True)
        QTest.qWait(60);page.sensor_save.click();QTest.qWait(220)
        self.assertEqual(self.w.link.saved[6][0],-.11);self.assertTrue(page._finish_ready())
        # Changing PID elsewhere must not be reverted by a hidden profile draft.
        changed=self.w.link.values[2][:];changed[0]=1.23;apply_pid(self.w.link,2,changed)
        prior[2]=changed
        with patch.object(self.w.link,'set_group',wraps=self.w.link.set_group) as set_group:
            page.save_ack.setChecked(True);page.next_button.click();QTest.qWait(220)
            set_group.assert_not_called()
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True]);self.assertFalse(self.w._calibration_guard)
        self.assertFalse(self.w.link.armed)
        for group,values in prior.items():self.assertEqual(self.w.link.saved[group],values)
        self.w.link.demo_restart();self.assertEqual(self.w.link.values[6][0],-.11)

    def test_imu_capture_stays_in_place_and_leaving_cancels_capture(self):
        page=self.begin('imu');panel=page.sensor_panel;panel.stationary.setChecked(True)
        QTest.qWait(100);self.assertTrue(panel.capture_button.isEnabled())
        bar=page.scrolls[3].verticalScrollBar();bar.setValue(0)
        QTest.mouseClick(panel.capture_button,Qt.MouseButton.LeftButton);QTest.qWait(100)
        self.assertTrue(panel.active);self.assertEqual(bar.value(),0)
        self.w.imu_tabs.setCurrentIndex(0);QTest.qWait(60)
        self.assertFalse(panel.active);self.assertTrue(self.w.link.read_group(130)[0])
        self.assertIsNone(self.w._setup_wizard)

    def test_unsaved_offset_edit_blocks_finish(self):
        page=self.begin('imu');page.sensor_panel.offsets[0].setValue(-.12)
        page.save_ack.setChecked(True);QTest.qWait(100)
        self.assertFalse(page.next_button.isEnabled());page._finish_calibration()
        self.assertTrue(self.w.link.read_group(130)[0])

    def test_incomplete_setup_cannot_be_unlocked_by_direct_imu_finish(self):
        self.w.link._setup[4]=0
        page=self.begin('imu');page.save_ack.setChecked(True);QTest.qWait(70)
        self.assertFalse(page.next_button.isEnabled());page._finish_calibration()
        self.assertTrue(self.w.link.read_group(130)[0])

    def test_esc_restart_resume_verify_motors_and_finish(self):
        page=self.begin('esc');page.esc_compatible.setChecked(True)
        page.esc_schedule.click();QTest.qWait(150)
        self.assertEqual(self.w.link.read_group(130)[3],1)
        self.w.link.demo_restart();QTest.qWait(150)
        shift=[6.1];self.w.link._clock=lambda:time.monotonic()+shift[0]
        QTest.qWait(80);shift[0]+=3.6;QTest.qWait(150)
        self.assertEqual(self.w.link.read_group(130)[3],3,page.last_message)
        self.assertFalse(page.begin_confirmed)
        self.assertTrue(page.begin_button.isEnabled(),page.last_message)
        page.begin_button.click();QTest.qWait(220)
        page.esc_response.setChecked(True);page.esc_verify.click();QTest.qWait(150)
        self.assertEqual(self.w.link.read_group(130)[3],4)
        self.assertEqual(self.w.link.read_group(130)[4],0)
        self.assertFalse(page._finish_ready())
        page._show_step(6);page.output_prop_check.setChecked(True);page.battery_check.setChecked(True)
        page.motor_choice.setCurrentIndex(4);QTest.qWait(60);page.motor_start.click();QTest.qWait(120)
        self.assertTrue(page.motor_running,page.last_message)
        page.motor_slider.setValue(1120);QTest.qWait(220)
        page.motor_stop.click();QTest.qWait(150)
        self.assertFalse(page.motor_running)
        page.motor_verified_check.setChecked(True);page.motor_confirm.click();QTest.qWait(220)
        self.assertEqual(self.w.link.read_group(130)[4],15,page.last_message)
        page.save_ack.setChecked(True);page.next_button.click();QTest.qWait(250)
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True],page.last_message)
        self.assertFalse(self.w.link.armed)

    def test_disconnect_preserves_scheduled_esc_request(self):
        page=self.begin('esc');page.esc_compatible.setChecked(True);page.esc_schedule.click();QTest.qWait(160)
        link=self.w.link
        with patch.object(link,'disarm',wraps=link.disarm) as disarm:
            self.w.disconnect();QTest.qWait(150);disarm.assert_not_called()
        self.assertEqual(link._setup[3],1);self.assertTrue(page.reconnect_waiting)
        self.assertFalse(page.motor_running)

    def test_late_motor_start_is_cancelled_on_focus_loss(self):
        page=self.begin('esc');page._show_step(6)
        page.output_prop_check.setChecked(True);page.battery_check.setChecked(True)
        entered=threading.Event();original=self.w.link.action
        def delayed(group,data,**kwargs):
            if group==135 and data[0]=='MOTOR_START':entered.set();time.sleep(.15)
            return original(group,data,**kwargs)
        with patch.object(self.w.link,'action',side_effect=delayed):
            page.motor_start.click();QTest.qWait(30);self.assertTrue(entered.is_set())
            QApplication.sendEvent(self.w,QEvent(QEvent.Type.WindowDeactivate));QTest.qWait(250)
        self.assertFalse(self.w.link.read_group(130)[8]);self.assertFalse(page.motor_running)

    def test_withdrawing_props_confirmation_stops_motor_test(self):
        page=self.begin('esc');page._show_step(6)
        page.output_prop_check.setChecked(True);page.battery_check.setChecked(True)
        page.motor_start.click();QTest.qWait(120);self.assertTrue(page.motor_running)
        page.propeller_check.setChecked(False);QTest.qWait(170)
        self.assertFalse(page.motor_running);self.assertFalse(self.w.link.read_group(130)[8])

    def test_lazy_page_order_remains_stable(self):
        esc=self.open('esc');self.w.navigate(5);QTest.qWait(100)
        self.assertIs(self.w.pages.widget(5),self.w.setup_wizard)
        self.assertIs(self.w.pages.widget(6),esc)
        self.assertIs(self.w.pages.widget(1),self.w.imu_tabs)
        self.assertEqual(self.w.pages.count(),12)

    def test_read_current_result_does_not_acquire_calibration_lock(self):
        page=self.open('esc')
        with patch.object(self.w.link,'action',wraps=self.w.link.action) as action:
            page.esc_read_status.click();QTest.qWait(180)
            action.assert_not_called()
        self.assertFalse(page.last_error,page.last_message)
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])
        self.assertFalse(self.w._calibration_guard)

    def test_failed_offset_save_cannot_finish_or_report_success(self):
        page=self.begin('imu');old=self.w.link.saved[6][:]
        page.sensor_panel.offsets[0].setValue(-.14);page.orientation_check.setChecked(True)
        with patch.object(self.w.link,'save_group',side_effect=RuntimeError('storage unavailable')):
            page.sensor_save.click();QTest.qWait(200)
        self.assertIn('storage unavailable',page.last_error)
        self.assertEqual(self.w.link.saved[6],old)
        page.save_ack.setChecked(True);self.assertFalse(page._finish_ready())
        self.assertEqual(self.w.link.read_group(130)[:2],[True,False])

    def test_result_read_focus_loss_and_navigation_preserve_scheduled_esc(self):
        # Reopened app: the durable request exists before a local Begin/Resume.
        self.w.link._setup[:2]=[True,False];self.w.link._setup[3]=1
        page=self.open('esc');entered=threading.Event()
        from areion_gui.setup_backend import run_setup_action
        def delayed(link,action,payload,cancelled):
            if action=='read':entered.set();time.sleep(.15)
            return run_setup_action(link,action,payload,cancelled)
        with patch('areion_gui.window.run_setup_action',side_effect=delayed), \
             patch.object(self.w.link,'disarm',wraps=self.w.link.disarm) as disarm:
            page.esc_read_status.click();QTest.qWait(30);self.assertTrue(entered.is_set())
            QApplication.sendEvent(self.w,QEvent(QEvent.Type.WindowDeactivate))
            self.w.navigate(0);QTest.qWait(250)
            disarm.assert_not_called()
        self.assertEqual(self.w.link.read_group(130)[3],1)
        self.assertFalse(self.w._calibration_guard)

if __name__=='__main__':unittest.main()
