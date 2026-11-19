"""Existing-kit review, verified reset, and actual Qt action-focus regressions."""
import unittest
import time
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QTabWidget
from PySide6.QtTest import QTest

from fc_fixture import DemoLink
from areion_gui.scroll_guard import install_scroll_guard
from areion_gui.setup_backend import run_setup_action
from areion_gui.wizard_model import read_draft
from zebjus_areion_link.schema import DRONE_GROUPS
import test_wizard_v3 as fixtures

setup_status=fixtures.setup_status


class WizardResetScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    setUp=fixtures.WizardV3Tests.setUp
    tearDown=fixtures.WizardV3Tests.tearDown
    ready=fixtures.WizardV3Tests.ready
    reply=fixtures.WizardV3Tests.reply

    def verified_values(self):
        return self.ready(setup_status(sensor=True,receiver=True,esc=5,motor_mask=15))

    def defaults(self):
        link=DemoLink()
        values={g:link.read_group(g,DRONE_GROUPS[g]['schema']) for g in self.w.SETTINGS_GROUPS}
        values[130]=setup_status()
        return values

    def click_visible(self,control):
        scroll=self.w.scrolls[self.w.step]
        self.app.processEvents();scroll.ensureWidgetVisible(control);self.app.processEvents()
        before=scroll.verticalScrollBar().value()
        QTest.mouseClick(control,Qt.MouseButton.LeftButton);self.app.processEvents()
        return before,scroll.verticalScrollBar().value()

    def test_existing_kit_review_retains_tuned_pid_and_physical_checks(self):
        values=self.verified_values();values[2][0]=1.37
        self.w.live.update(values);self.w._load_fc_values(values)
        self.assertEqual(self.w.next_button.text(),'Use current settings')
        self.w.advance();self.assertEqual(self.w.step,1)
        key=self.w.configuration['pid']['selected']
        QTest.mouseClick(self.w.pid_buttons[key],Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.configuration['pid']['profiles'][key]['rate'][0],1.37)
        for step in (1,2,3,4,5,6,7):
            self.w._show_step(step)
            self.assertTrue(self.w.next_button.isEnabled(),self.w.STEP_TITLES[step])
        self.assertEqual(self.requests,[])
        self.assertEqual(self.w.status[3:7],[5,15,True,True])

    def test_real_demo_review_finalize_and_reset_persist_across_restart(self):
        link=DemoLink();tuned=link.read_group(2);tuned[0]=1.37
        link.set_group(2,tuned);link.save_group(2)
        fixtures.complete_demo_setup(link,source=0)

        def handle(action,payload):
            self.w.action_finished(run_setup_action(link,action,payload,lambda:False),None)

        self.w.action_requested.connect(handle)

        def enter():
            self.w.on_enter();self.w.set_connection_state(connected=True,disarmed=True,demo=True)
            values={g:link.read_group(g,DRONE_GROUPS[g]['schema']) for g in (*self.w.SETTINGS_GROUPS,21,120,130,131)}
            now=time.monotonic();self.w.receive_telemetry(values,now,now,'demo-review')
            self.w._tick();self.w.propeller_check.setChecked(True)

        enter();self.assertTrue(self.w.begin_confirmed)
        self.assertEqual(self.w.status[3:7],[5,15,True,True])
        self.w.advance();self.assertEqual(self.w.step,1)
        self.w.pid_buttons[self.w.configuration['pid']['selected']].click()
        self.w._show_step(8);self.w.save_ack.setChecked(True);self.w.advance()
        self.assertTrue(self.w.finalized_this_visit)
        self.assertAlmostEqual(link.read_group(2)[0],1.37,places=5)
        self.assertAlmostEqual(link.read_group(2,saved=True)[0],1.37,places=5)
        self.assertEqual(link.read_group(130)[:2],[False,True])

        enter();self.w.reset_confirm.setChecked(True);self.w.reset_button.click()
        self.assertEqual(self.w.reset_progress.value(),100)
        self.assertFalse(self.w.reset_unverified)
        link.demo_restart()
        self.assertEqual(link.read_group(130)[:2],[True,False])
        self.assertEqual(link.read_group(130)[3:7],[0,0,False,False])
        for group in self.w.SETTINGS_GROUPS:
            defaults=[field['default'] for field in DRONE_GROUPS[group]['fields']]
            self.assertEqual(link.read_group(group,DRONE_GROUPS[group]['schema']),defaults)

    def test_reset_requires_both_confirmations_and_verified_readback(self):
        self.verified_values();self.w.motor_candidate=[1200]*4
        self.assertFalse(self.w.reset_button.isEnabled())
        self.w.reset_confirm.setChecked(True);self.w.propeller_check.setChecked(False)
        self.assertFalse(self.w.reset_button.isEnabled())
        self.w.propeller_check.setChecked(True)
        self.click_visible(self.w.reset_button)
        self.assertEqual(self.requests[-1],('reset_all',{'props_removed':True,'confirmed':True}))
        self.assertEqual(self.w.reset_progress.maximum(),0)
        self.assertFalse(self.w.next_button.isEnabled())
        self.reply(self.defaults())
        self.assertEqual(self.w.reset_progress.value(),100)
        self.assertFalse(self.w.reset_confirm.isChecked())
        self.assertEqual(self.w.motor_candidate,[None]*4)
        self.assertTrue(self.w.status[0]);self.assertFalse(self.w.status[1])
        self.assertEqual(self.w.status[3:7],[0,0,False,False])
        stored=read_draft(self.path)
        self.assertFalse(stored['wizard_complete'])
        self.assertEqual(stored['configuration']['checks']['resume']['status'][3:7],[0,0,False,False])
        self.w.advance();self.assertEqual(self.w.step,1)
        self.w._show_step(8);self.w.save_ack.setChecked(True)
        self.assertFalse(self.w.next_button.isEnabled())

    def test_failed_or_partial_reset_keeps_draft_until_full_reload(self):
        values=self.verified_values();self.w.motor_candidate=[1200]*4
        self.w.configuration['motors']['candidate_min_us']=[1200]*4
        for partial in (False,True):
            self.w._show_step(0);self.w.reset_confirm.setChecked(True);self.w.reset_button.click()
            if partial:self.reply({130:setup_status()})
            else:self.w.action_finished(None,RuntimeError('readback timeout'))
            self.assertTrue(self.w.reset_unverified)
            self.assertEqual(self.w.motor_candidate,[1200]*4)
            self.assertEqual(self.w.reset_progress.value(),0)
            self.assertFalse(self.w.next_button.isEnabled())
            self.w.read_current_button.click();self.assertEqual(self.requests[-1][0],'read')
            self.reply(values)
            self.assertFalse(self.w.reset_unverified)
            self.assertTrue(self.w.next_button.isEnabled())

    def test_reset_can_cancel_pending_esc_but_never_running_outputs(self):
        self.ready(setup_status(esc=1,stage=2,sensor=True,receiver=True))
        self.w.reset_confirm.setChecked(True);self.assertTrue(self.w.reset_button.isEnabled())
        self.w.live[130]=setup_status(esc=2,stage=3);self.w._update_navigation()
        self.assertFalse(self.w.reset_button.isEnabled())
        self.w.live[130]=setup_status(esc=5,active=True);self.w._update_navigation()
        self.assertFalse(self.w.reset_button.isEnabled())

    def test_capture_click_and_async_completion_keep_page_position(self):
        values=self.verified_values();self.w.resize(1100,760);self.w._show_step(3)
        panel=self.w.sensor_panel;panel.stationary.setChecked(True)
        before,after=self.click_visible(panel.capture_button)
        self.assertTrue(panel.active);self.assertEqual(after,before)
        scroll=self.w.scrolls[3];bar=scroll.verticalScrollBar()
        # Scrolling during capture remains usable and is not overwritten by ticks.
        chosen=min(80,bar.maximum());bar.setValue(chosen)
        started=panel.bank.current.started
        for index in range(35):
            now=started+.1*(index+1)
            with patch('time.monotonic',return_value=now):
                self.w.receive_telemetry(values,now,now,'session-1')
                self.w._tick();self.app.processEvents()
            self.assertEqual(bar.value(),chosen)
        self.assertIn('level',panel.bank.faces)
        self.assertEqual(panel.pose_key,'nose_up')

    def test_gyro_keyboard_activation_does_not_scroll_to_lower_fields(self):
        self.verified_values();self.w.resize(1100,760);self.w._show_step(3)
        panel=self.w.sensor_panel;panel.findChild(QTabWidget).setCurrentIndex(1)
        panel.stationary.setChecked(True);self.app.processEvents()
        panel.gyro_button.setFocus();self.app.processEvents()
        scroll=self.w.scrolls[3];before=scroll.verticalScrollBar().value()
        QTest.keyClick(panel.gyro_button,Qt.Key.Key_Space);self.app.processEvents()
        self.assertTrue(panel.active)
        self.assertEqual(scroll.verticalScrollBar().value(),before)

    def test_motor_start_ack_and_stop_keep_scroll_and_manual_slider_works(self):
        self.verified_values();self.w.resize(1100,760);self.w._show_step(6)
        self.w.output_prop_check.setChecked(True);self.w.battery_check.setChecked(True)
        before,after=self.click_visible(self.w.motor_start)
        self.assertEqual(after,before)
        self.reply({130:setup_status(esc=5,sensor=True,receiver=True,motor_mask=15,active=True)})
        self.app.processEvents();self.assertTrue(self.w.motor_running)
        self.assertEqual(self.w.scrolls[6].verticalScrollBar().value(),before)
        QTest.keyClick(self.w.motor_slider,Qt.Key.Key_Right)
        self.assertGreater(self.w.motor_slider.value(),1000)
        self.click_visible(self.w.record_min)
        self.assertEqual(self.w.motor_candidate[0],self.w.motor_slider.value())
        before,after=self.click_visible(self.w.motor_stop)
        self.assertEqual(after,before)
        self.assertFalse(self.w.motor_running);self.assertEqual(self.w.motor_slider.value(),1000)
        self.assertEqual(self.requests[-1][1]['command'],'MOTOR_STOP')

    def test_other_page_save_and_wheel_still_scroll_without_editing(self):
        self.verified_values();self.w.resize(1100,760);self.w._show_step(7)
        before,after=self.click_visible(self.w.arming_save)
        self.assertEqual(after,before);self.assertEqual(self.requests[-1][0],'apply_save')
        self.reply(self.requests[-1][1]['groups'])
        install_scroll_guard(self.w)
        for widget in self.w.advanced_arming:widget.show()
        scroll = self.w.scrolls[7]
        # Exercise scrolling even when the entire compact timing form fits the window.
        scroll.setMaximumHeight(200)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        editor=self.w.arming_fields[4]
        scroll.verticalScrollBar().setValue(0);value=editor.value()
        pos=editor.rect().center();global_pos=editor.mapToGlobal(pos)
        event=QWheelEvent(QPointF(pos),QPointF(global_pos),QPoint(0,-30),QPoint(),
                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,
                          Qt.ScrollPhase.ScrollUpdate,False)
        self.app.sendEvent(editor,event);self.app.processEvents()
        self.assertEqual(editor.value(),value)
        self.assertGreater(scroll.verticalScrollBar().value(),0)


if __name__=='__main__':unittest.main()
