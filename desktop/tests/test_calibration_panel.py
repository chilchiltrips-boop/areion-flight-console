"""Qt panel integration for sensor math, provenance and capture continuity."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy

from areion_gui.calibration_panel import CalibrationPanel
from areion_gui.setup_config import default_configuration,validate_configuration
from areion_gui.sensor_calibration import POSES,POSE_BY_KEY,GyroCalibration
from areion_gui.wizard_model import DEFAULT_SELECTIONS,save_draft,read_draft


class CalibrationPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock=100.
        self.clock_patch=patch('areion_gui.calibration_panel.time.monotonic',side_effect=lambda:self.clock)
        self.clock_patch.start()
        self.baseline=[-.10,.03,.12];self.identity=('board-a',10);self.demo=False
        self.p=CalibrationPanel(default_configuration()['imu'])
        self.reads=QSignalSpy(self.p.read_requested)
        self.push()
        self.p.stationary.setChecked(True)

    def tearDown(self):
        self.p.close();self.p.deleteLater();self.app.processEvents();self.clock_patch.stop()

    def telemetry(self,acc=(0.,0.,1.),gyro=(.1,-.1,.2),baseline=None,valid=True,armed=False):
        return {6:list(self.baseline if baseline is None else baseline),
                21:list(gyro)+list(acc)+[0.,0.,0.,0.],
                120:[armed,True,valid,8,.004,2000,0,True,True,True]}

    def push(self,values=None,stamp=None,identity=None,safe=True):
        values=self.telemetry() if values is None else values
        self.p.update_telemetry(values,self.clock if stamp is None else stamp,self.clock,
            self.identity if identity is None else identity,self.demo,safe)

    def face(self,key,bias=(.12,-.04,.08),gain=(1.04,.97,1.02)):
        if not self.p.active:
            self.push();self.p.capture_button.click()
        self.assertTrue(self.p.active,self.p.acc_status.text())
        start=self.clock;target=POSE_BY_KEY[key]['target']
        for i in range(36):
            self.clock=start+(i+1)*.1
            raw=[target[j]/gain[j]+bias[j] for j in range(3)]
            values=self.telemetry([raw[j]+self.baseline[j] for j in range(3)])
            self.push(values)
            if key in self.p.bank.faces:break
        self.assertIn(key,self.p.bank.faces,self.p.acc_status.text())
        self.clock+=.1

    def all_faces(self):
        for pose in reversed(POSES):self.face(pose['key'])
        self.assertIsNotNone(self.p.config['result'],self.p.acc_status.text())

    def gyro_capture(self,rates=(.3,-.2,.1)):
        self.push(self.telemetry(gyro=rates));self.p.start_gyro()
        self.assertIsNotNone(self.p.gyro,self.p.gyro_status.text())
        start=self.clock
        for i in range(36):
            self.clock=start+(i+1)*.1;self.push(self.telemetry(gyro=rates))
            if self.p.gyro is None:break
        self.assertIsNotNone(self.p.gyro_preview,self.p.gyro_status.text())

    def test_after_offset_g_updates_beside_each_editor(self):
        self.push(self.telemetry(acc=(.15,-.2,1.2)))
        for editor,value in zip(self.p.offsets,(-.25,.23,-.08)):editor.setValue(value)
        self.assertEqual([w.text() for w in self.p.corrected_labels],['+0.0000 g','+0.0000 g','+1.0000 g'])
        self.assertEqual(self.p.values[21][3:6],[.15,-.2,1.2])
        self.assertEqual(self.reads.count(),0)

    def test_manual_edit_does_not_relabel_a_stale_sample_as_live(self):
        self.clock+=1.
        self.p.offsets[0].setValue(-.2)
        self.assertEqual([w.text() for w in self.p.corrected_labels],['—']*3)
        self.assertFalse(self.p.capture_button.isEnabled())

    def test_complete_six_positions_loads_additive_candidate_without_fc_write(self):
        self.all_faces();result=self.p.snapshot()['result']
        self.assertEqual(result['method'],'six_face');self.assertEqual(result['kind'],'live_candidate')
        self.assertEqual(len(result['faces']),6);self.assertFalse(result['applied_to_fc'])
        self.assertFalse(result['full_calibration_applied_to_fc'])
        for actual,want in zip(self.p.snapshot()['offsets'],(-.12,.04,-.08)):self.assertAlmostEqual(actual,want,places=4)
        self.assertIn('6 / 6',self.p.acc_status.text());self.assertFalse(self.p.capture_button.isEnabled())
        self.assertEqual(self.reads.count(),0)

    def test_demo_acc_and_gyro_provenance_stay_explicit(self):
        self.demo=True;self.push();self.all_faces()
        self.assertEqual(self.p.snapshot()['result']['kind'],'demo_candidate')
        self.assertEqual(self.p.snapshot()['offsets_origin'],'demo_candidate');self.assertIn('DEMO',self.p.acc_status.text())
        self.gyro_capture()
        self.assertEqual(self.p.snapshot()['gyro_result']['kind'],'demo_gyro_candidate')
        self.assertIn('DEMO',self.p.gyro_status.text())

    def test_captured_sensor_results_round_trip_through_schema_four(self):
        self.all_faces();self.gyro_capture()
        snapshot=self.p.snapshot()
        configuration=default_configuration();configuration['imu']=snapshot
        validated=validate_configuration(configuration)
        self.assertEqual(validated['imu'],snapshot)
        with TemporaryDirectory() as directory:
            path=Path(directory)/'sensor-setup.json'
            saved=save_draft(path,DEFAULT_SELECTIONS,validated,stage='configuration_saved')
            restored=read_draft(path)
        self.assertEqual(restored,saved)
        self.assertEqual(restored['schema_version'],4)
        self.assertFalse(restored['hardware_applied'])
        imu=restored['configuration']['imu'];acc=imu['result'];gyro=imu['gyro_result']
        self.assertEqual(imu,snapshot)
        for actual,want in zip(acc['candidate_offsets'],(-.12,.04,-.08)):
            self.assertAlmostEqual(actual,want,places=10)
        for actual,want in zip(acc['required_scale'],(1.04,.97,1.02)):
            self.assertAlmostEqual(actual,want,places=10)
        self.assertEqual(set(acc['faces']),set(POSE_BY_KEY))
        self.assertFalse(acc['full_calibration_applied_to_fc'])
        self.assertEqual(acc['fc_supported_correction'],'additive_offsets_only')
        self.assertEqual(gyro['correction_scope'],'python_preview_only')
        self.assertFalse(gyro['applied_to_fc'])
        for actual,want in zip(gyro['residual_bias_dps'],(.3,-.2,.1)):
            self.assertAlmostEqual(actual,want,places=10)

    def test_stale_identity_baseline_armed_and_invalid_status_reset_partial_bank(self):
        for case in ('stale','identity','baseline','unsafe','armed','invalid'):
            with self.subTest(case=case):
                self.p.reset_acc();self.push();self.face('level')
                self.assertEqual(set(self.p.bank.faces),{'level'})
                self.clock+=.1
                if case=='stale':self.push(stamp=self.clock-1.)
                elif case=='identity':self.push(identity=('board-b',11))
                elif case=='baseline':self.push(self.telemetry(baseline=[-.11,.03,.12]))
                elif case=='unsafe':self.push(safe=False)
                elif case=='armed':self.push(self.telemetry(armed=True))
                else:self.push(self.telemetry(valid=False))
                self.assertIsNone(self.p.bank);self.assertEqual(self.p.acc_progress.value(),0)
                self.assertIn('reset',self.p.acc_status.text())

    def test_invalid_data_cancels_current_pose_and_preserves_no_fake_result(self):
        self.p.capture_button.click();self.assertTrue(self.p.active)
        self.clock+=.1;self.push(self.telemetry(valid=False))
        self.assertFalse(self.p.active);self.assertIsNone(self.p.config['result']);self.assertIsNone(self.p.bank)

    def test_one_start_needs_no_manual_confirmation_and_cancel_clears_all_faces(self):
        self.p.stationary.setChecked(False)
        self.face('nose_up')
        self.assertTrue(self.p.active)
        self.assertFalse(self.p.has_current_result)
        self.assertEqual(self.p.pose_tiles['nose_up'].property('mark'),'done')
        self.p.reset_button.click()
        self.assertFalse(self.p.active)
        self.assertIsNone(self.p.config['result'])
        self.assertEqual(self.p.face_count.text(),'0 / 6')
        self.assertTrue(self.p.capture_button.isEnabled())

    def test_completed_result_can_only_be_saved_on_original_live_kit_and_baseline(self):
        self.all_faces()
        self.assertTrue(self.p.has_current_result)
        self.push(identity=('new-kit',3))
        self.assertFalse(self.p.has_current_result)
        self.assertIsNone(self.p.bank)

    def test_verified_readback_presented_as_saved_and_never_offered_as_new_measurement(self):
        self.all_faces()
        offsets=self.p.snapshot()['offsets']
        self.p.mark_saved()
        values=self.telemetry(baseline=offsets)
        values[130]=[True,False,1,0,0,True]
        self.push(values)
        self.assertEqual(self.p.target_label.text(),'Calibration saved')
        self.assertEqual(self.p.face_count.text(),'6 / 6')
        self.assertFalse(self.p.has_current_result)
        self.push(identity=('different-kit',123))
        self.assertFalse(self.p.has_current_result)
        self.assertEqual(self.p.face_count.text(),'0 / 6')

    def test_gyro_zero_changes_only_python_display_and_retains_fc_rates(self):
        self.gyro_capture();r=self.p.snapshot()['gyro_result']
        self.assertEqual(r['method'],'gyro_residual');self.assertEqual(r['correction_scope'],'python_preview_only')
        self.assertFalse(r['applied_to_fc'])
        self.assertEqual([w.text() for w in self.p.gyro_live],['+0.300','-0.200','+0.100'])
        self.assertEqual([w.text() for w in self.p.gyro_corrected],['+0.000','+0.000','+0.000'])
        self.assertEqual(self.p.values[21][:3],[.3,-.2,.1]);self.assertEqual(self.reads.count(),0)

    def test_new_gyro_capture_clears_previous_zero_labels_immediately(self):
        self.gyro_capture();self.p.start_gyro()
        self.assertIsNotNone(self.p.gyro);self.assertIsNone(self.p.gyro_preview)
        self.assertEqual([w.text() for w in self.p.gyro_corrected],['—']*3)

    def test_new_session_does_not_reuse_completed_gyro_correction(self):
        self.gyro_capture();saved=deepcopy(self.p.snapshot()['gyro_result'])
        self.clock+=.1;self.push(self.telemetry(gyro=(.3,-.2,.1)),identity=('board-a',11))
        self.assertIsNone(self.p.gyro_preview);self.assertEqual([w.text() for w in self.p.gyro_corrected],['—']*3)
        self.assertEqual(self.p.snapshot()['gyro_result'],saved)
        self.assertTrue(any(word in self.p.gyro_status.text().lower() for word in ('historical','again')))

    def test_saved_gyro_result_is_not_activated_on_restore(self):
        self.gyro_capture();config=self.p.snapshot();other=CalibrationPanel(config)
        try:
            other.update_telemetry(self.telemetry(gyro=(.3,-.2,.1)),self.clock,self.clock,('new-board',2),False,True)
            self.assertIsNone(other.gyro_preview);self.assertEqual([w.text() for w in other.gyro_corrected],['—']*3)
            self.assertIn('historical',other.gyro_status.text())
        finally:other.close();other.deleteLater()

    def test_manual_acc_edit_invalidates_captured_result(self):
        self.all_faces();self.p.offsets[0].setValue(-.13)
        self.assertIsNone(self.p.bank);self.assertIsNone(self.p.config['result'])
        self.assertEqual(self.p.snapshot()['offsets_origin'],'manual');self.assertEqual(self.p.acc_progress.value(),0)
        self.assertIn('cleared',self.p.acc_status.text())

    def test_reset_and_new_visit_require_fresh_capture(self):
        self.all_faces();candidate=self.p.snapshot()['offsets']
        self.p.reset_acc()
        self.assertIsNone(self.p.bank);self.assertIsNone(self.p.config['result'])
        self.assertEqual(self.p.snapshot()['offsets'],candidate);self.assertEqual(self.p.pose_key,'level')
        self.assertTrue(self.p.capture_button.isEnabled())
        self.gyro_capture();self.p.new_visit()
        self.assertFalse(self.p.stationary.isChecked());self.assertIsNone(self.p.gyro_preview)
        self.assertEqual(self.p.gyro_progress.value(),0);self.assertFalse(self.p.gyro_button.isEnabled())
        self.p.clear_gyro();self.assertIsNone(self.p.config['gyro_result'])


if __name__=='__main__':unittest.main()
