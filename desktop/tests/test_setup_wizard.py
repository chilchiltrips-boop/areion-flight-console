"""Initial wizard navigation, real Qt interactions, local persistence and command isolation."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from areion_gui.setup_wizard import SetupWizard
from areion_gui.wizard_model import DEFAULT_SELECTIONS, QUAD_X_MOTORS, save_draft, read_draft
from areion_gui.window import MainWindow


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'config'/'setup_wizard.json'

    def tearDown(self):self.temp.cleanup()

    def test_atomic_save_readback_and_explicit_incomplete_state(self):
        draft=save_draft(self.path,DEFAULT_SELECTIONS)
        self.assertEqual(read_draft(self.path),draft)
        self.assertFalse(draft['wizard_complete']);self.assertFalse(draft['hardware_applied'])
        self.assertNotIn('propellers_confirmed',draft)
        self.assertEqual(draft['motor_map'],[
            {'motor':'M1','position':'Front left','rotation':'CW'},
            {'motor':'M2','position':'Front right','rotation':'CCW'},
            {'motor':'M3','position':'Back right','rotation':'CW'},
            {'motor':'M4','position':'Back left','rotation':'CCW'}])
        self.assertEqual(list(self.path.parent.glob('*.tmp')),[])

    def test_replace_failure_preserves_existing_draft(self):
        before=save_draft(self.path,DEFAULT_SELECTIONS)
        with patch('areion_gui.wizard_model.os.replace',side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):save_draft(self.path,dict(DEFAULT_SELECTIONS,frame_layout='quad_h'))
        self.assertEqual(read_draft(self.path),before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')),[])

    def test_rejects_future_vehicle_schema_and_corrupt_motor_map(self):
        with self.assertRaises(ValueError):save_draft(self.path,dict(DEFAULT_SELECTIONS,vehicle_type='car'))
        for edit in ({'schema_version':True},{'schema_version':2},{'wizard_complete':True},
                     {'hardware_applied':True},{'motor_map':[]}):
            draft=save_draft(self.path,DEFAULT_SELECTIONS);draft.update(edit)
            self.path.write_text(json.dumps(draft))
            with self.assertRaises(ValueError):read_draft(self.path)

    def test_other_layouts_do_not_invent_motor_mapping(self):
        for layout in ('quad_plus','quad_h'):
            saved=save_draft(self.path,dict(DEFAULT_SELECTIONS,frame_layout=layout))
            self.assertEqual(saved['motor_map'],[])
            self.assertEqual(saved['motor_map_status'],'not_defined')
            self.assertFalse(saved['hardware_applied'])


class WizardQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'setup_wizard.json'
        self.w=SetupWizard(self.path);self.w.resize(1000,750);self.w.show();QTest.qWait(20)

    def tearDown(self):
        self.w.close();self.w.deleteLater();self.app.processEvents();self.temp.cleanup()

    def reach_layout(self):
        self.w.propeller_check.setChecked(True);self.w.advance()
        self.w.set_connection_state(connected=True,has_link=True,demo=True,disarmed=True)
        for _ in range(4):self.w.advance()
        self.assertEqual(self.w.step,5)

    def test_safety_gate_back_and_reentry_always_start_with_fresh_confirmation(self):
        self.assertEqual(self.w.step,0);self.assertFalse(self.w.back_button.isEnabled())
        self.assertFalse(self.w.next_button.isEnabled());self.w.advance();self.assertEqual(self.w.step,0)
        QTest.mouseClick(self.w.propeller_check,Qt.MouseButton.LeftButton,pos=QPoint(8,self.w.propeller_check.height()//2))
        self.assertTrue(self.w.next_button.isEnabled())
        QTest.mouseClick(self.w.next_button,Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.step,1);self.assertTrue(self.w.back_button.isEnabled())
        self.w.back();self.assertEqual(self.w.step,0)
        self.w.on_enter();self.assertFalse(self.w.propeller_check.isChecked())
        self.assertFalse(self.w.next_button.isEnabled())

    def test_usb_ap_and_disarmed_fresh_connection_gates(self):
        self.w.propeller_check.setChecked(True);self.w.advance()
        path={'name':'serial://TEST@115200','datagram':False,'active':True,'confirmed':True,'last_received_age':.1}
        def state(**kw):
            values=dict(connected=True,has_link=True,disarmed=True,paths=[path]);values.update(kw)
            self.w.set_connection_state(**values)
        state();self.assertTrue(self.w.next_button.isEnabled())
        for kw in ({'disarmed':False},{'busy':True},{'connected':False},{'paths':[dict(path,last_received_age=.6)]},
                   {'paths':[dict(path,confirmed=False)]},{'paths':[dict(path,last_received_age=None)]}):
            state(**kw);self.assertFalse(self.w.next_button.isEnabled(),kw)
        state();self.w.mode.setCurrentText('AP');self.assertFalse(self.w.next_button.isEnabled())
        state(paths=[dict(path,datagram=True)]);self.assertTrue(self.w.next_button.isEnabled())

    def test_connection_controls_emit_requested_parameters(self):
        requests=[];disconnects=[];self.w.connect_requested.connect(requests.append)
        self.w.disconnect_requested.connect(lambda:disconnects.append(True))
        self.w.set_connection_state()
        self.w.port.setCurrentText('/dev/test');self.w.baud.setValue(230400);self.w.startup_wait.setValue(5)
        self.w.connect_button.click()
        self.assertEqual((requests[-1]['mode'],requests[-1]['port'],requests[-1]['baud']),('USB','/dev/test',230400))
        self.w.mode.setCurrentText('AP');self.w.host.setText('192.168.4.1');self.w.udp_port.setValue(8081)
        self.w.connect_button.click();self.assertEqual(requests[-1]['mode'],'AP');self.assertEqual(requests[-1]['udp_port'],8081)
        self.w.set_connection_state(connecting=True);self.assertFalse(self.w.connect_button.isEnabled())
        self.w.disconnect_button.click();self.assertEqual(disconnects,[True])

    def test_erase_never_enabled_or_shows_fake_progress(self):
        for state in ({},{'connected':True,'has_link':True,'demo':True,'disarmed':True}):
            self.w.set_connection_state(**state);self.w.erase_button.click()
            self.assertFalse(self.w.erase_button.isEnabled());self.assertEqual(self.w.erase_progress.value(),0)
            self.assertIn('Unavailable',self.w.erase_status.text())

    def test_default_choices_and_disabled_future_types(self):
        self.assertEqual(self.w.selections,DEFAULT_SELECTIONS)
        for buttons,active in ((self.w.vehicle_buttons,'multirotor'),(self.w.profile_buttons,'f450_esc'),
                               (self.w.frame_buttons,'quadcopter')):
            self.assertTrue(buttons[active].isChecked())
            for name,b in buttons.items():
                if name!=active:
                    self.assertFalse(b.isEnabled());b.click();self.assertTrue(buttons[active].isChecked())

    def test_save_and_next_is_only_final_action_and_resumes_as_incomplete(self):
        self.reach_layout();self.assertEqual(self.w.next_button.text(),'Save && Next')
        self.w.layout_buttons['quad_h'].click();self.assertEqual(self.w.selections['frame_layout'],'quad_h')
        self.w.advance();self.assertEqual(self.w.step,6);self.assertFalse(self.w.next_button.isEnabled())
        self.assertTrue(self.w.back_button.isEnabled());self.assertFalse(self.w.last_saved['wizard_complete'])
        restored=SetupWizard(self.path)
        self.assertEqual(restored.selections['frame_layout'],'quad_h')
        self.assertEqual(restored.step,0);self.assertFalse(restored.propeller_check.isChecked());restored.deleteLater()
        self.w.back();self.assertEqual(self.w.next_button.text(),'Save && Next')
        self.w.back();self.assertEqual(self.w.next_button.text(),'Next')

    def test_save_error_stays_visible_across_status_refresh_and_allows_retry(self):
        self.reach_layout()
        with patch('areion_gui.setup_wizard.save_draft',side_effect=PermissionError('read only')):self.w.advance()
        self.assertEqual(self.w.step,5);self.assertIn('Could not save',self.w.footer_note.text())
        self.w.set_connection_state(connected=True,has_link=True,demo=True,disarmed=True)
        self.assertIn('read only',self.w.footer_note.text());self.w.advance();self.assertEqual(self.w.step,6)

    def test_invalid_saved_draft_does_not_skip_safety_or_claim_restored(self):
        self.path.write_text('{broken')
        other=SetupWizard(self.path)
        self.assertEqual(other.selections,DEFAULT_SELECTIONS);self.assertIn('could not be loaded',other.restore_note.text())
        self.assertFalse(other.next_button.isEnabled());other.deleteLater()


# Current Window integration coverage lives in test_wizard_v3.py.

if __name__=='__main__':unittest.main()
