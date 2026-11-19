"""Explicit wizard reconnect after USB/AP loss; no command or setup replay."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from fc_fixture import DemoLink, make_test_window
from areion_gui.model import NEUTRAL
from areion_gui.setup_backend import run_setup_action
from zebjus_areion_link.schema import DRONE_GROUPS
from setup_fixtures import complete_demo_window


def initial_values(link):
    return {group:link.read_group(group,DRONE_GROUPS[group]['schema'])
            for group in (125,120,122,121,110,130,132,134)}


def reboot_copy(link):
    rebooted=DemoLink()
    rebooted.saved=copy.deepcopy(link.saved)
    rebooted._stored_setup=list(link._stored_setup)
    rebooted.fc_session=link.fc_session+1
    rebooted.demo_restart()
    return rebooted


class CalibrationResumeTests(unittest.TestCase):
    def test_pending_high_low_and_sensor_recovery_resume_are_read_only(self):
        now=[100.0];link=DemoLink(clock=lambda:now[0])
        run=lambda action,payload=None:run_setup_action(link,action,payload or {},lambda:False)
        run('begin')
        config=link.values[134][:];config[1]=1
        self.assertTrue(run('apply_save',{'groups':{134:config}})['complete'])
        link.action(135,['SENSOR_OK',1,0,0,0])
        link.action(135,['ESC_SCHEDULE',1,0,0,0])
        phases=[('pending',0,2,1),('high',0,3,2),('low',3.1,4,2),
                ('sensor startup',3.0,5,3),('gyro sampling',1.0,5,3),('ready',3.0,5,3)]
        for name,elapsed,stage,esc_state in phases:
            with self.subTest(phase=name):
                if name=='high':link.demo_restart()
                now[0]+=elapsed
                before=link.read_group(130)
                self.assertEqual(before[2:4],[stage,esc_state])
                with patch.object(link,'disarm',wraps=link.disarm) as disarm,patch.object(link,'action',wraps=link.action) as action:
                    result=run('begin')
                    disarm.assert_not_called();action.assert_not_called()
                self.assertTrue(result['resumed']);self.assertTrue(result['complete'])
                self.assertEqual(result['values'][130],before)


class WizardReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.tmp.name):
            self.w=make_test_window()
        self.w.show();QTest.qWait(180)

    def tearDown(self):
        if isValid(self.w):
            self.w.close();self.wait_for(lambda:self.w.close_ready)
            self.w.deleteLater();self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents();self.tmp.cleanup()

    def wait_for(self,predicate):
        for _ in range(200):
            if predicate():return
            QTest.qWait(10)
        self.fail(self.w.last_notice)

    def options(self,mode='USB'):
        return dict(mode=mode,port='/dev/cu.usbmodem-reconnected',baud=115200,
                    startup_wait=0,host='192.168.4.1',udp_port=8080,ssid='aerion drone')

    def pending_esc(self):
        self.w.navigate(5)
        wizard=self.w.setup_wizard
        self.wait_for(lambda:wizard.begin_confirmed and not wizard.operation_busy)
        link=self.w.link
        config=link.values[134][:];config[1]=1
        result=run_setup_action(link,'apply_save',{'groups':{134:config}},lambda:False)
        self.assertTrue(result['complete'])
        link.action(135,['SENSOR_OK',1,0,0,0])
        link.action(135,['ESC_SCHEDULE',1,0,0,0])
        for group,values in initial_values(link).items():
            self.w.data.put(group,DRONE_GROUPS[group]['schema'],values,received=False)
        self.w._update_wizard_connection(time.monotonic())
        wizard.propeller_check.setChecked(True);wizard._show_step(5)
        return link,wizard

    def test_stale_usb_object_can_reconnect_to_ap_inside_esc_step(self):
        old,wizard=self.pending_esc();rebooted=reboot_copy(old)
        old.connected=False;self.w.tick();self.w.render_status(time.monotonic())
        self.assertIs(self.w.link,old)
        self.assertTrue(wizard.connect_button.isEnabled())
        self.assertEqual(wizard.step,5)
        self.assertIsNone(self.w.data.values(120))
        close=Mock(wraps=old.close);old.close=close
        with patch.object(old,'disarm') as disarm,patch.object(rebooted,'set_group',wraps=rebooted.set_group) as change,patch('areion_gui.window.open_link',return_value=(rebooted,initial_values(rebooted),None,[])) as connect:
            self.w._wizard_connect(self.options('AP'))
            self.wait_for(lambda:self.w.link is rebooted and wizard.begin_confirmed and not wizard.operation_busy)
            close.assert_called_once();disarm.assert_not_called();change.assert_not_called()
            self.assertEqual(connect.call_args.args[0]['mode'],'AP')
        self.assertEqual(self.w.pages.currentIndex(),5);self.assertEqual(wizard.step,5)
        self.assertTrue(wizard.status[5]);self.assertTrue(wizard.status[0])
        self.assertFalse(self.w._running());self.assertFalse(self.w._setup_arm_allowed())

    def test_reconnect_preserves_stale_pending_esc_without_disarm(self):
        old,wizard=self.pending_esc();rebooted=reboot_copy(old)
        # A deliberate path change while the board is reachable also preserves
        # the one-shot. Aged cached setup is the last known state during reboot.
        for group in (120,130):
            self.w.data.latest[group]=(self.w.data.values(group),time.monotonic()-10)
        with patch.object(old,'disarm') as disarm,patch('areion_gui.window.open_link',return_value=(rebooted,initial_values(rebooted),None,[])):
            self.w._wizard_connect(self.options('USB'))
            self.wait_for(lambda:self.w.link is rebooted and not self.w.connecting)
            disarm.assert_not_called()
        self.assertEqual(old._stored_setup[3],1)
        self.assertEqual(wizard.step,5)

    def test_ordinary_digital_reconnect_disarms_but_never_restarts_sender(self):
        complete_demo_window(self.w,source=1);old=self.w.link
        self.w.start_stream();self.wait_for(lambda:self.w.session.running)
        replacement=DemoLink()
        with patch.object(old,'disarm',wraps=old.disarm) as disarm,patch.object(replacement,'send_control') as send,patch.object(replacement,'arm') as arm,patch('areion_gui.window.open_link',return_value=(replacement,initial_values(replacement),None,[])):
            self.w._wizard_connect(self.options())
            self.wait_for(lambda:self.w.link is replacement and not self.w.connecting)
            QTest.qWait(100)
            disarm.assert_called_once();send.assert_not_called();arm.assert_not_called()
        self.assertFalse(self.w.session.running);self.assertEqual(self.w.controls.values,NEUTRAL)

    def test_failed_reconnect_keeps_step_and_allows_retry(self):
        old,wizard=self.pending_esc();old.connected=False;self.w.tick()
        with patch('areion_gui.window.open_link',side_effect=OSError('USB cable absent')):
            self.w._wizard_connect(self.options());self.wait_for(lambda:not self.w.connecting)
        self.w.render_status(time.monotonic())
        self.assertIsNone(self.w.link);self.assertTrue(wizard.connect_button.isEnabled())
        self.assertEqual(wizard.step,5);self.assertTrue(wizard.last_status[5])

    def test_late_traffic_does_not_revive_a_stale_session(self):
        old,wizard=self.pending_esc()
        callbacks=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append((work,done))):
            callback=Mock()
            self.w._linked(lambda link:link.read_group(130,1),callback)
            old_done=callbacks[-1][1]
            old.connected=False;self.w.tick()
            old.connected=True
            old_done(old.read_group(130,1),None)
            with patch.object(wizard,'_request') as request:
                self.w.tick();self.w.render_status(time.monotonic())
                request.assert_not_called()
            callback.assert_not_called()
        self.assertFalse(self.w._connected());self.assertFalse(wizard.connected)
        self.assertIsNone(self.w.data.values(120))
        self.assertTrue(wizard.connect_button.isEnabled())
        self.assertEqual(self.w.route_pill.text(),'OFFLINE / STALE')

    def test_canceled_connection_callback_cannot_replace_a_new_attempt(self):
        self.w.disconnect();QTest.qWait(60)
        callbacks=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append((work,done))):
            self.w._wizard_connect(self.options());first_done=callbacks[-1][1]
            self.w.disconnect();self.w._wizard_connect(self.options('AP'))
            current_cancel=self.w.connect_cancel
            first_done(None,RuntimeError('old canceled attempt'))
            self.assertIs(self.w.connect_cancel,current_cancel);self.assertTrue(self.w.connecting)
            stale=DemoLink();first_done((stale,initial_values(stale),None,[]),None)
            self.assertIsNone(self.w.link);self.assertTrue(self.w.connecting)
            self.assertEqual(callbacks[-1][0],stale.close)
        self.w.connecting=False;self.w.connect_cancel.set()

    def test_close_completion_is_idempotent_after_window_deletion(self):
        callbacks=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append((work,done))):
            self.w.close()
        self.assertTrue(self.w._close_timer.isActive())
        work,finish=callbacks[-1];work();finish()
        self.assertTrue(self.w.close_ready);self.assertFalse(self.w._close_timer.isActive())
        finish()  # A timeout queued alongside the successful worker is safe.
        self.w.deleteLater();self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(self.w))
        finish()  # A late worker/timeout cannot use deleted Qt wrappers.

    def test_close_completion_handles_destruction_before_worker_reply(self):
        callbacks=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append((work,done))):
            self.w.close()
        work,finish=callbacks[-1]
        self.w.deleteLater();self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(self.w));self.assertFalse(self.w.close_ready)
        work();finish()


if __name__=='__main__':unittest.main()
