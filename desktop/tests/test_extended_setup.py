"""Setup persistence, calibration provenance, no-output preview and supported writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QComboBox,QSpinBox,QDoubleSpinBox
from PySide6.QtTest import QTest
from areion_gui.setup_config import (default_configuration,validate_configuration,pin_errors,
    PIN_GPIO,PIN_DEFAULTS,ESC_PROFILES,esc_configuration,StationaryCapture,MotorPreview)
from areion_gui.wizard_model import DEFAULT_SELECTIONS,read_draft,save_draft
from areion_gui.setup_backend import run_setup_action,MotorTestAdapter,UnsupportedSetupFeature
from fc_fixture import DemoLink
from areion_gui.wizard_extended import ExtendedSetupWizard
from areion_gui.window import MainWindow
from zebjus_areion_link.schema import DRONE_GROUPS

class ConfigurationTests(unittest.TestCase):
    def test_fixed_board_pin_mapping(self):
        c=default_configuration();self.assertEqual(PIN_GPIO['D3'],21)
        c['pins']['ppm']='D0';self.assertTrue(pin_errors(c['pins']))
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_full_configuration_roundtrip_and_v1_migration(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'setup.json';old=save_draft(path,DEFAULT_SELECTIONS)
            self.assertEqual(old['schema_version'],1)
            c=default_configuration();c['input_source']='AP';c['motors']['candidate_min_us']=[1101,1102,1103,1104]
            saved=save_draft(path,DEFAULT_SELECTIONS,c,'configuration_saved')
            self.assertEqual(saved,read_draft(path));self.assertEqual(saved['schema_version'],4)
            self.assertFalse(saved['wizard_complete']);self.assertFalse(saved['hardware_applied'])
    def test_invalid_pwm_nan_sta_and_false_motor_verification(self):
        for change in ('period','nan','sta','verified','range','malformed'):
            c=default_configuration()
            if change=='period':c['esc']['frequency_hz']=500;c['esc']['max_us']=2200
            elif change=='nan':c['pid']['profiles']['aerion450']['rate'][0]=float('nan')
            elif change=='sta':c['input_source']='STA'
            elif change=='verified':c['motors']['physically_verified']=True
            elif change=='malformed':c['imu']=[]
            else:c['motors']['candidate_min_us'][0]=1501
            with self.assertRaises(ValueError):validate_configuration(c)
    def test_profiles_keep_edits_independent(self):
        c=default_configuration()
        self.assertEqual(c['pid']['profiles']['aerion250'],c['pid']['profiles']['aerion450'])
        c['pid']['profiles']['aerion250']['rate'][0]=.75
        self.assertEqual(c['pid']['profiles']['aerion450']['rate'][0],.9)
    def test_unknown_future_motor_api_cannot_send(self):
        adapter=MotorTestAdapter();self.assertFalse(adapter.available)
        with self.assertRaises(UnsupportedSetupFeature):adapter.start([1200]*4)
        with self.assertRaises(UnsupportedSetupFeature):adapter.update([1200]*4)

    def test_legacy_editable_pin_and_esc_values_migrate_to_fixed_board(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'setup.json';saved=save_draft(path,DEFAULT_SELECTIONS,default_configuration())
            saved['schema_version']=2;saved['configuration']['pins']['ppm']='D9'
            saved['configuration']['esc']={'profile':'custom_pwm','name':'Old','frequency_hz':50,'resolution_bits':11,'min_us':1100,'max_us':1900}
            path.write_text(json.dumps(saved));loaded=read_draft(path)['configuration']
            self.assertEqual(loaded['pins'],PIN_DEFAULTS);self.assertEqual(loaded['esc'],esc_configuration('pwm250'))

class CalibrationTests(unittest.TestCase):
    @staticmethod
    def collect(demo=False):
        c=StationaryCapture([-.10,.03,.12],100.,demo)
        for i in range(1,35):
            t=100+i*.16;c.add([.1,-.1,.2,.08,-.04,1.1,0.,0.,0.,0.],t,t,True)
        return c
    def test_additive_offset_math_and_live_residual(self):
        c=self.collect();self.assertFalse(c.error);r=c.result
        for actual,expected in zip(r['candidate_offsets'],[-.18,.07,.02]):self.assertAlmostEqual(actual,expected)
        self.assertTrue(r['gyro_residual_ok']);self.assertFalse(r['applied_to_fc'])
        self.assertGreaterEqual(r['samples'],25);self.assertEqual(r['kind'],'live_candidate')
    def test_demo_capture_retains_provenance(self):
        self.assertEqual(self.collect(True).result['kind'],'demo_candidate')
    def test_duplicate_stale_armed_and_motion_samples_do_not_calibrate(self):
        v=[0.,0.,0.,0.,0.,1.,0.,0.,0.,0.];c=StationaryCapture([0,0,0],0)
        for _ in range(30):c.add(v,.1,.2,True)
        self.assertEqual(len(c.samples),1);self.assertIsNone(c.result)
        c.add(v,.09,.2,True);self.assertEqual(len(c.samples),1)
        c.add(v,.1,.8,True);self.assertIn('lost',c.error)
        for values,safe in [(v,False),([6.,0.,0.,0.,0.,1.,0.,0.,0.,0.],True)]:
            c=StationaryCapture([0,0,0],0);c.add(values,.1,.1,safe)
            self.assertTrue(c.error);self.assertIsNone(c.result)
    def test_vibration_and_wrong_orientation_rejected(self):
        c=StationaryCapture([0,0,0],0)
        for i in range(1,35):c.add([0.,0.,0.,.06*(-1)**i,0.,1.,0.,0.,0.,0.],i*.16,i*.16,True)
        self.assertIn('stationary',c.error)
        c=StationaryCapture([0,0,0],0);c.add([0.,0.,0.,0.,0.,-1.,0.,0.,0.,0.],.1,.1,True)
        self.assertTrue(c.error)

class PreviewTests(unittest.TestCase):
    def test_single_all_bounds_and_stop_reset(self):
        m=MotorPreview()
        with self.assertRaises(ValueError):m.start(False)
        m.select(2);m.start(True);m.set_value(1150);self.assertEqual(m.outputs,[1000,1000,1150,1000])
        m.select(None);self.assertFalse(m.running);m.start(True);m.set_value(1200);self.assertEqual(m.outputs,[1200]*4)
        for value in (999,1501,1200.5,True):
            with self.assertRaises(ValueError):m.set_value(value)
        m.stop();self.assertEqual(m.outputs,[1000]*4)
        m.set_value(1400);m.start(True);self.assertEqual(m.value,1000)

class SupportedBackendTests(unittest.TestCase):
    def test_selected_input_verified_without_arm_or_channels(self):
        link=DemoLink()
        with patch.object(link,'arm') as arm,patch.object(link,'send_control') as control:
            with self.assertRaisesRegex(RuntimeError,'setup lock'):
                run_setup_action(link,'input',{'source':0},lambda:False)
            run_setup_action(link,'begin',{'props_removed':True},lambda:False)
            result=run_setup_action(link,'input',{'source':0},lambda:False)
            self.assertEqual(result['values'][110],[0]);arm.assert_not_called();control.assert_not_called()
    def test_apply_save_verifies_each_selected_group(self):
        link=DemoLink();c=default_configuration();groups={6:[-.12,.02,.11],2:c['pid']['profiles']['stable']['rate']}
        result=run_setup_action(link,'save_supported',{'groups':groups},lambda:False)
        self.assertTrue(result['complete'])
        for group,values in groups.items():
            self.assertEqual(link.saved[group],values);self.assertEqual(result['sections'][group]['state'],'saved_verified')
    def test_storage_unavailable_and_armed_prevent_all_writes(self):
        for armed in (False,True):
            link=DemoLink();original=link.read_group
            def read(group,*args,**kwargs):
                values=original(group,*args,**kwargs)
                if group==120:values[0]=armed;values[7]=False
                return values
            with patch.object(link,'read_group',side_effect=read),patch.object(link,'set_group') as write:
                with self.assertRaises((ValueError,RuntimeError)):run_setup_action(link,'save_supported',{'groups':{6:[0,0,0]}},lambda:False)
                write.assert_not_called()
    def test_invalid_later_section_prevents_earlier_write(self):
        link=DemoLink()
        with patch.object(link,'set_group') as write:
            with self.assertRaises(ValueError):run_setup_action(link,'save_supported',{'groups':{6:[0,0,0],2:[1]}},lambda:False)
            write.assert_not_called()
    def test_partial_failure_report_and_no_further_sections(self):
        link=DemoLink();original=link.set_group
        rate=link.values[2][:];rate[0]+=.1
        angle=link.values[3][:];angle[0]+=.1
        def write(group,*args,**kwargs):
            if group==3:raise RuntimeError('injected failure')
            return original(group,*args,**kwargs)
        with patch.object(link,'set_group',side_effect=write) as setter:
            result=run_setup_action(link,'save_supported',{'groups':{6:[0,0,0],2:rate,3:angle}},lambda:False)
        self.assertFalse(result['complete']);self.assertEqual(result['sections'][2]['state'],'saved_verified')
        self.assertEqual(result['sections'][3]['state'],'failed');self.assertNotIn(6,result['sections'])
        self.assertEqual([call.args[0] for call in setter.call_args_list],[2,3])
    def test_cancel_after_apply_does_not_save_or_continue(self):
        link=DemoLink();state={'cancel':False};original=link.set_group
        def write(*args,**kwargs):
            value=original(*args,**kwargs);state['cancel']=True;return value
        with patch.object(link,'set_group',side_effect=write),patch.object(link,'save_group') as save:
            result=run_setup_action(link,'save_supported',{'groups':{6:[0,0,0]}},lambda:state['cancel'])
        save.assert_not_called();self.assertFalse(result['complete']);self.assertEqual(result['sections'][6]['stage'],'apply_sent')
    def test_demo_acc_blocked_on_real_link(self):
        link=DemoLink();link.demo=False
        with patch.object(link,'set_group') as write:
            with self.assertRaises(ValueError):run_setup_action(link,'save_supported',{'groups':{6:[0,0,0]},'acc_origin':'demo_candidate'},lambda:False)
            write.assert_not_called()

# The current nine-step Qt and Window integration tests live in test_wizard_v3.py.

if __name__=='__main__':unittest.main()
