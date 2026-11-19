"""Current setup UI: firmware evidence, motor leases and explicit final save."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QSpinBox
from PySide6.QtTest import QTest
from areion_gui.wizard_extended import ExtendedSetupWizard
from areion_gui.setup_config import default_configuration, esc_configuration, PIN_DEFAULTS
from areion_gui.wizard_model import read_draft
from fc_fixture import DemoLink, make_test_window
from zebjus_areion_link.schema import DRONE_GROUPS
from setup_fixtures import complete_demo_setup, complete_demo_window


def setup_status(**changes):
    names=('locked','complete','stage','esc','motor_mask','sensor','receiver','failsafe',
           'active','m1','m2','m3','m4','revision','fault','kit')
    values=[True,False,1,0,0,False,False,False,False,1000,1000,1000,1000,1,'','test-kit']
    for name,value in changes.items():values[names.index(name)]=value
    return values


class WizardV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'setup.json'
        self.w=ExtendedSetupWizard(self.path);self.w.timer.stop();self.w.resize(1150,850);self.w.show()
        self.requests=[];self.w.action_requested.connect(lambda action,payload:self.requests.append((action,payload)))
        self.app.processEvents()

    def tearDown(self):
        self.w.close();self.w.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def ready(self,status=None):
        self.w.on_enter();self.w.set_connection_state(connected=True,disarmed=True,demo=True)
        self.w.begin_requested=True;self.w.begin_confirmed=True;self.w.propeller_check.setChecked(True)
        link=DemoLink();values={g:link.read_group(g,DRONE_GROUPS[g]['schema']) for g in (2,3,4,6,7,112,120,131,132,134)}
        values[130]=status or setup_status();values[21]=[0.,0.,0.,0.,0.,1.,0.,0.,0.,0.]
        now=time.monotonic();values['_raw_stamp']=now
        self.w.receive_telemetry(values,now,now,'session-1');self.w._load_fc_values(values)
        self.w._update_navigation();return values

    def reply(self,values=None,**extra):
        action,payload=self.requests[-1]
        result={'action':action,'values':values or {},'complete':True,**extra}
        if action=='command':result['command']=payload['command']
        self.w.action_finished(result,None)

    def test_setup_pages_and_optional_verifier_have_fixed_wiring_and_profile_controls(self):
        self.ready();self.assertEqual(self.w.stack.count(),10)
        for i in range(9):
            self.w._show_step(i);self.app.processEvents();self.assertFalse(self.w.grab().isNull())
        self.assertEqual(self.w.configuration['pins'],PIN_DEFAULTS)
        self.assertFalse(self.w.stack.widget(2).findChildren(QComboBox))
        self.assertFalse(self.w.stack.widget(1).findChildren(QDoubleSpinBox))
        self.assertFalse(self.w.stack.widget(5).findChildren(QSpinBox))
        for key,card in self.w.esc_buttons.items():
            card.click();self.assertEqual(self.w.configuration['esc'],esc_configuration(key))

    def test_diagnostic_state_with_no_loss_attestation_can_reach_final_save(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=5,motor_mask=15,failsafe=False))
        self.w._show_step(7)
        self.assertTrue(self.w.next_button.isEnabled())
        self.assertFalse(hasattr(self.w,'failsafe_check'))
        self.assertFalse(hasattr(self.w,'failsafe_save'))
        self.w.advance();self.assertEqual(self.w.step,8)
        self.w.save_ack.setChecked(True)
        self.assertTrue(self.w.next_button.isEnabled())
        self.w._finalize()
        self.assertEqual(self.requests[-1][0],'finalize')
        self.assertFalse(any(p.get('command')=='FAILSAFE_OK' for _,p in self.requests))

    def test_changed_arming_values_need_save_before_next(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=5,motor_mask=15))
        self.w._show_step(7);self.assertTrue(self.w.next_button.isEnabled())
        self.w.arming_fields[4].setValue(6)
        self.assertFalse(self.w.next_button.isEnabled())
        self.w.arming_save.click()
        action,payload=self.requests[-1];self.assertEqual(action,'apply_save')
        self.assertEqual(payload['groups'][4][4],6)
        self.reply(payload['groups'])
        self.assertTrue(self.w.next_button.isEnabled())

    def test_save_input_never_sends_drafts_from_other_pages(self):
        self.ready()
        self.w._show_step(2)
        self.w.idle_boxes[0].setValue(1245)
        self.w.mapping_boxes[0].setCurrentIndex(6)
        self.w._choose_input('USB')
        self.w.input_apply.click()
        self.assertEqual(self.requests[-1], ('input', {'source': 2}))

    def test_auto_begin_locks_before_propeller_confirmation_and_next_waits(self):
        self.w.on_enter();self.w.set_connection_state(connected=True,disarmed=True,demo=True)
        self.w._tick();self.assertEqual(self.requests,[('begin',{'props_removed':False})])
        self.assertFalse(self.w.next_button.isEnabled());self.assertFalse(self.w.back_button.isEnabled())
        self.reply({130:setup_status()});self.assertEqual(self.requests[-1][0],'read')
        self.reply();self.assertFalse(self.w.next_button.isEnabled())
        self.w.propeller_check.setChecked(True);self.assertTrue(self.w.next_button.isEnabled())
        self.assertFalse(any(p.get('command')=='ARM' for _,p in self.requests))

    def test_checkboxes_and_old_local_results_do_not_replace_fc_proof(self):
        self.ready();self.w.orientation_check.setChecked(True)
        self.w.motor_verified_check.setChecked(True);self.w.save_ack.setChecked(True);self.w._show_step(8)
        self.assertFalse(self.w.next_button.isEnabled());self.w._finalize();self.assertEqual(self.requests,[])
        self.assertFalse(self.w.diagnostic_snapshot()['wizard_complete'])

    def test_failed_begin_cannot_use_cached_lock_as_confirmation(self):
        self.ready();self.w.begin_confirmed=False;self.w.begin_requested=False;self.w._tick()
        self.w.action_finished(None,RuntimeError('Persistent lock write failed'))
        self.assertTrue(self.w.begin_requested);self.assertFalse(self.w.begin_confirmed)
        self.assertFalse(self.w._ready());self.assertFalse(self.w.next_button.isEnabled())
        self.assertFalse(self.w.step_buttons[1].isEnabled())

    def test_esc_pending_survives_step_navigation_and_hide(self):
        self.ready(setup_status(stage=2,esc=1,sensor=True,receiver=True));self.w._show_step(5)
        self.w._show_step(0);self.w.suspend('Window hidden')
        self.assertEqual(self.requests,[]);self.assertFalse(self.w.finalized_this_visit)
        self.assertIn('PENDING RESTART',self.w.esc_status.text())

    def test_motor_requires_reconfirmed_props_battery_esc_and_fresh_imu(self):
        values=self.ready(setup_status(sensor=True,receiver=True,esc=4));self.w._show_step(6)
        self.w._start_motor();self.assertEqual(self.requests,[])
        self.w.output_prop_check.setChecked(True);self.w.battery_check.setChecked(True)
        values[120][2]=False;now=time.monotonic();self.w.receive_telemetry(values,now,now,'session-1')
        self.w._start_motor();self.assertEqual(self.requests,[]);self.assertFalse(self.w.motor_start.isEnabled())
        values[120][2]=True;self.w.receive_telemetry(values,now,now,'session-1')
        self.w.motor_slider.setValue(1450);self.w._start_motor()
        self.assertEqual(self.requests[-1],('command',{'command':'MOTOR_START','args':[1,1,0,0]}))
        self.assertEqual(self.w.motor_slider.value(),1000)

    def test_esc_verify_waits_for_normal_sensor_startup(self):
        values=self.ready(setup_status(sensor=True,receiver=True,esc=3));self.w._show_step(5)
        self.w.esc_response.setChecked(True);values[120][2]=False
        now=time.monotonic();self.w.receive_telemetry(values,now,now,'session-1')
        self.assertFalse(self.w.esc_verify.isEnabled())
        values[120][2]=True;values[120][1]=False;self.w.receive_telemetry(values,now,now,'session-1')
        self.assertTrue(self.w.esc_verify.isEnabled())

    def test_motor_heartbeat_does_not_latch_busy_and_stop_bypasses_busy(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=4,active=True));self.w._show_step(6)
        self.requests.clear();self.w.motor_running=True;self.w.motor_last_mask=1;self.w.motor_slider.setValue(1180)
        self.w._tick();self.assertEqual(self.requests[-1],('command',{'command':'MOTOR_SET','args':[1,1180,0,0]}))
        self.assertFalse(self.w.operation_busy)
        self.w.operation_busy=True;self.w.external_busy=True;self.w._stop_motor()
        self.assertEqual(self.requests[-1][1]['command'],'MOTOR_STOP');self.assertEqual(self.w.motor_slider.value(),1000)
        self.assertFalse(self.w.motor_running)

    def test_late_heartbeat_response_does_not_consume_a_new_action(self):
        self.ready();self.w._request('read',{'groups':[130]});pending=self.w.pending
        self.w.action_finished({'action':'command','command':'MOTOR_SET','values':{}},RuntimeError('Cancelled heartbeat'))
        self.assertEqual(self.w.pending,pending);self.assertTrue(self.w.operation_busy)

    def test_idle_output_saved_before_motor_evidence(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=4));self.w._show_step(6)
        self.w.idle_boxes[0].setValue(1175);self.w.motor_verified_check.setChecked(True);self.w._confirm_motor()
        action,payload=self.requests[-1];self.assertEqual(action,'apply_save');self.assertEqual(payload['groups'][134][7],1175)
        self.reply({134:payload['groups'][134],130:setup_status(sensor=True,receiver=True,esc=4)})
        self.assertEqual(self.requests[-1],('command',{'command':'MOTOR_OK','args':[1,1,0,0]}))

    def test_raw_receiver_values_are_not_the_guarded_flight_channels(self):
        values=self.ready();values[22]=[1500,1500,1000,1500,1000,1000,1500,1500]
        values[131]=[1760,1260,1020,1510,1000,1000,1500,1500,8,True,1]
        now=time.monotonic();values['_raw_stamp']=now;self.w.receive_telemetry(values,now,now,'session-1')
        self.assertEqual(self.w.rx_table.item(0,1).text(),'1760');self.assertIn('Roll 1760',self.w.rx_preview.text())
        values[131]=None;self.w.receive_telemetry(values,now,now,'session-1')
        self.assertEqual(self.w.rx_table.item(0,1).text(),'—')

    def test_receiver_settings_save_precedes_firmware_neutral_check(self):
        self.ready(setup_status(receiver=True));self.w.rx_direction_check.setChecked(True);self.w._save_receiver()
        self.assertEqual(self.requests[-1][0],'apply_save');self.assertEqual(set(self.requests[-1][1]['groups']),{132,134})
        self.reply({130:setup_status()});self.assertEqual(self.requests[-1][1]['command'],'RX_OK')

    def test_current_arming_values_are_loaded_without_overwrite(self):
        self.ready();self.w._load_fc_values({4:[1060,1910,1090,25,7,2,30],7:[6,.1,.15,.15,1,0],112:[350,400]})
        self.assertEqual([w.value() for w in self.w.arming_fields],[1060,1910,1090,25,7,2,30])
        self.assertEqual(self.w.mode_channel.currentIndex(),5);self.assertEqual(self.w.ppm_timeout.value(),350)
        self.assertEqual(self.requests,[])

    def test_completed_esc_waits_for_automatic_sensors_without_reschedule(self):
        values=self.ready(setup_status(stage=5,esc=3,sensor=True,receiver=True))
        values[120][2]=False;values[120][5]=750
        now=time.monotonic();self.w.receive_telemetry(values,now,now,'session-1')
        self.w.esc_response.setChecked(True);self.w.esc_compatible.setChecked(True)
        self.w._show_step(5)
        self.assertFalse(hasattr(self.w,'demo_restart'));self.assertFalse(self.w.esc_schedule.isEnabled())
        self.assertFalse(self.w.esc_verify.isEnabled());self.assertIn('automatic sensor startup',self.w.esc_status.text())
        values[120][2]=True;values[120][5]=2000
        now=time.monotonic();self.w.receive_telemetry(values,now,now,'session-1')
        self.assertTrue(self.w.esc_verify.isEnabled())
        self.w.esc_verify.click();self.assertEqual(self.requests[-1][1]['command'],'ESC_VERIFY')

    def test_final_save_requires_all_evidence_and_only_then_writes_receipt(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=4,motor_mask=15,failsafe=True))
        self.w._show_step(8);self.assertFalse(self.w.next_button.isEnabled());self.w.save_ack.setChecked(True)
        self.assertTrue(self.w.next_button.isEnabled());self.w.advance()
        self.assertEqual(self.requests[-1][0],'finalize');self.assertFalse(read_draft(self.path)['wizard_complete']);self.assertIsNone(read_draft(self.path)['receipt'])
        self.assertEqual(set(self.requests[-1][1]['groups']),{2,3,4,6,7,112,132,134})
        self.reply({130:setup_status(locked=False,complete=True,stage=0,sensor=True,receiver=True,esc=4,motor_mask=15,failsafe=True)})
        self.assertTrue(self.w.finalized_this_visit);self.assertTrue(read_draft(self.path)['wizard_complete'])
        self.assertFalse(read_draft(self.path)['hardware_applied']);count=len(self.requests)
        self.assertEqual(self.w.next_button.text(), 'Done')
        self.assertTrue(self.w.next_button.isEnabled())
        exits = []
        self.w.finish_requested.connect(lambda: exits.append(True))
        self.w._tick();self.w.advance();self.assertEqual(len(self.requests),count)
        self.assertEqual(exits, [True])

    def test_failed_finalize_keeps_lock_and_does_not_write_completion(self):
        self.ready(setup_status(sensor=True,receiver=True,esc=4,motor_mask=15,failsafe=True));self.w.save_ack.setChecked(True)
        self.w._finalize();self.w.action_finished(None,RuntimeError('Stored readback mismatch'))
        self.assertFalse(self.w.finalized_this_visit);self.assertTrue(self.w.status[0]);self.assertFalse(self.path.exists())
        self.assertIn('Stored readback mismatch',self.w.last_error)


class WizardV3WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('areion_gui.window.QStandardPaths.writableLocation',return_value=self.temp.name):self.w=make_test_window()
        self.w.show();QTest.qWait(200)
    def tearDown(self):
        self.w.close();QTest.qWait(150);self.temp.cleanup()
    def wait_for(self,predicate):
        for _ in range(160):
            if predicate():return True
            QTest.qWait(15)
        return False
    def test_entry_locks_existing_session_before_safety_confirmation(self):
        link=self.w.link
        with patch.object(link,'arm') as arm:
            self.w.navigate(5);s=self.w.setup_wizard
            self.assertTrue(self.wait_for(lambda:s.begin_requested and not s.operation_busy and s.loaded_identity is not None),s.last_error)
            self.assertIs(self.w.link,link);self.assertTrue(s.status[0]);self.assertFalse(s.propeller_check.isChecked())
            self.assertFalse(self.w._setup_arm_allowed());self.w.navigate(0);self.assertFalse(self.w._setup_arm_allowed())
            arm.assert_not_called()
        self.w.navigate(5);self.assertEqual(s.step,0);self.assertFalse(s.propeller_check.isChecked())

    def test_immediate_enter_and_leave_still_locks_completed_ppm_kit(self):
        complete_demo_window(self.w,source=0)
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])
        self.w.navigate(5);self.w.navigate(0)
        self.assertTrue(self.wait_for(lambda:self.w.link.read_group(130)[:2]==[True,False]))
        self.assertTrue(self.wait_for(lambda:self.w.setup_wizard.begin_confirmed))
        self.assertFalse(self.w._setup_arm_allowed())

    def test_offline_enter_and_leave_locks_later_connected_ppm_kit(self):
        self.w.disconnect();QTest.qWait(100)
        self.w.navigate(5);self.w.navigate(0)
        link=DemoLink();complete_demo_setup(link,source=0)
        self.assertEqual(link.read_group(130)[:2],[False,True])
        values={g:link.read_group(g,DRONE_GROUPS[g]['schema']) for g in (120,122,121,125,110,130,131,132,134)}
        self.w.install_link(link,values)
        self.assertTrue(self.wait_for(lambda:link.read_group(130)[:2]==[True,False]))
        self.assertTrue(self.wait_for(lambda:self.w.setup_wizard.begin_confirmed))
        self.assertFalse(self.w._setup_arm_allowed())

    def test_urgent_stop_cannot_complete_cancelled_save_or_consume_new_request(self):
        self.w.navigate(5);wizard=self.w.setup_wizard
        self.assertTrue(self.wait_for(lambda:wizard.begin_confirmed and not wizard.operation_busy))
        callbacks=[];after=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append(done)):
            wizard._request('apply_save',{'groups':{6:[0.,0.,0.]}},lambda:after.append('saved'))
            old_done=callbacks[-1]
            self.w._wizard_action('command',{'command':'MOTOR_STOP','args':[0,0,0,0]})
            callbacks[-1]({'action':'command','command':'MOTOR_STOP','values':{130:self.w.link.read_group(130)},'complete':True},None)
            self.assertEqual(after,[]);self.assertIsNone(wizard.pending)
            wizard._request('read',{'groups':[130]});new_pending=wizard.pending
            old_done(None,RuntimeError('Cancelled old save'))
            self.assertIs(wizard.pending,new_pending);self.assertTrue(wizard.operation_busy)
            self.assertEqual(after,[])
        wizard.pending=None;wizard.after_action=None;wizard.operation_busy=False;self.w.command_busy=False

    def test_focus_loss_during_setup_read_does_not_send_global_stop(self):
        self.w.navigate(5);wizard=self.w.setup_wizard
        self.assertTrue(self.wait_for(lambda:wizard.begin_confirmed and not wizard.operation_busy))
        callbacks=[]
        with patch.object(self.w,'_submit',side_effect=lambda work,done,priority=10:callbacks.append(done)),patch.object(self.w,'stop') as stop:
            wizard._request('read',{'groups':[130]});pending=wizard.pending
            self.w._application_state(Qt.ApplicationState.ApplicationInactive)
            stop.assert_not_called();self.assertIs(wizard.pending,pending)
        wizard.pending=None;wizard.after_action=None;wizard.operation_busy=False;self.w.command_busy=False
    def test_connection_options_use_existing_handler(self):
        self.w.disconnect();QTest.qWait(100)
        options=dict(mode='AP',port='/dev/test',baud=115200,startup_wait=4,host='192.168.4.1',udp_port=8080,ssid='aerion drone')
        with patch.object(self.w,'connect_fc') as connect:self.w._wizard_connect(options);connect.assert_called_once()
        self.assertEqual(self.w._connection_options(),options)
    def test_diagnostics_report_firmware_lock_and_unfinished_setup(self):
        self.w.navigate(5);s=self.w.setup_wizard
        self.assertTrue(self.wait_for(lambda:s.status is not None and not s.operation_busy))
        self.w.copy_diagnostics();report=json.loads(QApplication.clipboard().text())['setup_wizard']
        self.assertFalse(report['wizard_complete']);self.assertFalse(report['hardware_applied'])
        self.assertEqual(report['step'],1);self.assertTrue(report['setup_status'][0]);self.assertTrue(report['demo'])


if __name__=='__main__':unittest.main()
