"""Power-cycle setup retains evidence without treating cached state as live."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QHideEvent
from shiboken6 import delete
from fc_fixture import DemoLink
from areion_gui.wizard_extended import ExtendedSetupWizard
from areion_gui.wizard_model import read_draft
from zebjus_areion_link.schema import DRONE_GROUPS


class WizardResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'setup.json'
        self.w=ExtendedSetupWizard(self.path);self.w.timer.stop();self.w.show()
        self.requests=[];self.w.action_requested.connect(lambda a,p:self.requests.append((a,p)))
        link=DemoLink();self.values={g:link.read_group(g,DRONE_GROUPS[g]['schema']) for g in (2,3,4,6,7,112,120,130,131,132,134,21)}
        self.values[130]=[True,False,2,1,0,True,True,False,False,1000,1000,1000,1000,0,'','KIT-A']
        self.w.on_enter();self.w.set_connection_state(connected=True,disarmed=True,has_link=True,demo=True)
        self.feed();self.w.begin_requested=True;self.w.begin_confirmed=True;self.w.propeller_check.setChecked(True)
        self.w._load_fc_values(self.values);self.w._show_step(5)
    def tearDown(self):
        self.w.close();self.w.deleteLater();self.app.processEvents();self.tmp.cleanup()
    def feed(self,identity='session-A'):
        now=time.monotonic();self.values['_raw_stamp']=now
        self.w.receive_telemetry(self.values,now,now,identity)
    def test_connection_bar_available_on_esc_page_and_stale_link_reconnects(self):
        self.assertTrue(self.w.connection_card.isVisible());self.assertEqual(self.w.step,5)
        self.w.connection_lost('USB removed')
        self.w.set_connection_state(connected=False,has_link=True,connecting=False)
        self.assertTrue(self.w.connect_button.isEnabled());self.assertEqual(self.w.connect_button.text(),'Reconnect')
        sent=[];self.w.connect_requested.connect(sent.append);self.w.mode.setCurrentText('AP');self.w.connect_button.click()
        self.assertEqual(sent[0]['mode'],'AP');self.assertEqual(self.w.step,5)
    def test_checkpoint_is_incomplete_and_offline_evidence_never_enables_actions(self):
        self.w.connection_lost('Power cycle')
        stored=read_draft(self.path)
        self.assertFalse(stored['wizard_complete']);self.assertFalse(stored['hardware_applied']);self.assertIsNone(stored['receipt'])
        self.assertEqual(stored['configuration']['checks']['resume']['status'][5:7],[True,True])
        self.assertIn('✓',self.w.step_buttons[3].text());self.assertIn('OFFLINE',self.w.esc_status.text())
        self.assertFalse(self.w.next_button.isEnabled());self.assertFalse(self.w.esc_verify.isEnabled());self.assertFalse(self.w.motor_start.isEnabled())
        self.assertEqual(self.requests,[])
    def test_same_kit_reconnect_reads_saved_checks_without_reapplying(self):
        self.w.connection_lost('Power cycle');self.values[130][2:4]=[5,3]
        self.w.set_connection_state(connected=True,has_link=True,disarmed=True,demo=True);self.feed('session-B')
        self.w._tick();self.assertEqual(self.requests[-1][0],'begin')
        self.w.action_finished({'action':'begin','complete':True,'values':{130:self.values[130]}},None)
        self.assertEqual(self.requests[-1][0],'read')
        self.w.action_finished({'action':'read','complete':True,'values':self.values},None)
        self.assertEqual(self.w.step,5);self.assertEqual(self.w.status[5:7],[True,True])
        self.assertFalse(any(action in ('apply_save','finalize') for action,_ in self.requests))
        self.assertEqual(self.w._resume_target(),5)
    def test_different_kit_requires_new_safety_and_drops_old_progress(self):
        self.w.connection_lost('Changed kit');self.values[130]=[True,False,0,0,0,False,False,False,False,1000,1000,1000,1000,0,'','KIT-B']
        self.w.set_connection_state(connected=True,has_link=True,disarmed=True,demo=True);self.feed('session-B')
        self.assertEqual(self.w.step,0);self.assertFalse(self.w.propeller_check.isChecked());self.assertFalse(self.w.begin_confirmed)
        self.assertNotIn('✓',self.w.step_buttons[3].text());self.assertEqual(self.w.kit_id,'KIT-B')
    def test_terminal_imu_failure_is_not_displayed_as_waiting_progress(self):
        self.values[130][2:4]=[5,3];self.values[130][14]='IMU_STARTUP_FAILED';self.values[120][2]=False
        self.feed();self.assertIn('Sensor startup failed',self.w.esc_status.text())
        self.assertNotIn('waiting for automatic',self.w.esc_status.text());self.assertFalse(self.w.esc_verify.isEnabled())
    def test_begin_on_pending_sequence_does_not_reset_saved_page(self):
        self.w._show_step(0);self.w.advance();self.assertEqual(self.w.step,5)

    def test_shutdown_hide_does_not_touch_deleted_sensor_controls(self):
        delete(self.w.sensor_panel.offsets[0])
        self.w.hideEvent(QHideEvent())
        self.assertFalse(self.w.visit_active)


if __name__=='__main__':unittest.main()
