"""End-to-end Qt checks for persistent inputs and deliberately enabled PID tuning."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import struct
from unittest.mock import patch
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from fc_fixture import make_test_window
from areion_gui.model import NEUTRAL
from setup_fixtures import complete_demo_window

class Console310Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setOrganizationName('ZebjusTest');cls.app.setApplicationName('AreionTest')

    def setUp(self):
        self.w=make_test_window();self.w.resize(1120,760);self.w.show();QTest.qWait(160)
        for _ in range(50):
            if all(card.loaded and not card.busy for card in self.w.cards.values()):break
            QTest.qWait(20)

    def tearDown(self):
        self.w.close();QTest.qWait(160)

    def prepare(self,source=1):
        complete_demo_window(self.w,source)
        self.w.render_status(time.monotonic())

    def arm(self,bench=True):
        self.prepare();self.w.pid_live_confirm.setChecked(bench)
        self.w.start_stream();QTest.qWait(450)
        self.assertTrue(self.w.session.running,self.w.last_notice)
        self.w.arm();QTest.qWait(120)
        self.assertTrue(self.w.link.armed,self.w.last_notice)

    def test_pid_single_apply_saves_and_preserves_completed_setup(self):
        self.prepare();self.w.navigate(2);QTest.qWait(60)
        card=self.w.cards[2];card.inputs[0].setValue(1.23)
        self.assertNotIn('save',card.buttons)
        QTest.mouseClick(card.buttons['apply'],Qt.MouseButton.LeftButton);QTest.qWait(160)
        self.assertEqual(self.w.link.values[2][0],1.23)
        self.assertEqual(self.w.link.saved[2][0],1.23)
        self.assertIn('SAVED',card.note.text())
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])
        self.w.link.demo_restart();self.assertEqual(self.w.link.values[2][0],1.23)

    def test_live_pid_keeps_stream_and_throttle_then_saves_on_stop(self):
        self.arm();self.w.controls.values[2]=1200;QTest.qWait(45)
        self.w.controls.pressed.add('W');self.w.navigate(2);QTest.qWait(45)
        self.assertTrue(self.w._running());self.assertTrue(self.w.link.armed)
        self.assertFalse(self.w.controls.pressed);self.assertEqual(self.w.controls.values[2],1200)
        self.assertEqual([self.w.controls.values[i] for i in (0,1,3)],[1500]*3)
        card=self.w.cards[2];old=self.w.link.saved[2][:]
        card.inputs[0].setValue(1.27);QTest.mouseClick(card.buttons['apply'],Qt.MouseButton.LeftButton);QTest.qWait(160)
        self.assertTrue(self.w._running());self.assertTrue(self.w.link.armed)
        self.assertEqual(self.w.link.values[2][0],1.27);self.assertEqual(self.w.link.saved[2],old)
        self.assertTrue(self.w.link.read_group(136)[0]);self.assertIn('pending',self.w.pid_state.text())
        self.w.stop('Test stop');QTest.qWait(190)
        self.assertFalse(self.w.link.armed);self.assertFalse(self.w.link.read_group(136)[0])
        self.assertEqual(self.w.link.saved[2][0],1.27);self.assertIn('SAVED',self.w.pid_state.text())
        self.assertEqual(self.w.link.read_group(130)[:2],[False,True])

    def test_other_navigation_and_unchecking_still_stop(self):
        self.arm();self.w.navigate(2);QTest.qWait(30)
        self.w.pid_bench_confirm.setChecked(False);QTest.qWait(130)
        self.assertFalse(self.w.pid_live_confirm.isChecked());self.assertFalse(self.w._running())
        self.assertFalse(self.w.link.armed)
        self.w.navigate(0);self.w.pid_live_confirm.setChecked(True);self.w.start_stream();QTest.qWait(230)
        self.w.navigate(4);QTest.qWait(120)
        self.assertFalse(self.w._running())

    def test_unconfirmed_direct_live_apply_is_rejected(self):
        self.arm(bench=False);old=self.w.link.values[2][:]
        values=old[:];values[0]=1.31;self.w.settings_request(2,'apply',values);QTest.qWait(60)
        self.assertEqual(self.w.link.values[2],old);self.assertIn('tripod',self.w.cards[2].note.text())

    def test_source_switch_saved_with_completed_checks_and_no_autostart(self):
        self.prepare(0);old=self.w.link.read_group(130)
        for source in (1,2,0):
            self.w._select_source_value(source);self.w.select_source();QTest.qWait(140)
            self.assertEqual(self.w.link.source,source,self.w.last_notice)
            self.assertEqual(self.w.link.saved[134][1],source)
            state=self.w.link.read_group(130)
            self.assertEqual(state[:2],[False,True]);self.assertEqual(state[3:7],old[3:7])
            self.assertFalse(self.w._running());self.assertFalse(self.w.link.armed)
        self.w.link.demo_restart();self.assertEqual(self.w.link.source,0)

    def test_unqualified_ppm_switch_is_not_reported_saved(self):
        self.prepare(1);self.w._select_source_value(0);self.w.select_source();QTest.qWait(140)
        self.assertEqual(self.w.link.source,1);self.assertEqual(self.w.link.saved[134][1],1)
        self.assertNotIn('SAVED input:',self.w.last_notice)

    def test_dashboard_at_minimum_window_and_no_stale_green(self):
        self.w.render_status(time.monotonic())
        self.assertNotIsInstance(self.w.pages.widget(0), QScrollArea)
        self.assertFalse(self.w.left_stick.light)
        self.assertEqual(self.w.flight_dashboard.last_health['TELEMETRY'].state,'green')
        self.w._connection_became_stale();self.w.render_status(time.monotonic())
        self.assertEqual(self.w.flight_dashboard.last_health['TELEMETRY'].state,'red')
        self.assertIsNone(self.w.flight_dashboard.motor_readback.values)
        self.assertFalse(self.w.flight_dashboard.horizon.model.valid)

    def test_pid_apply_does_not_scroll_to_next_card(self):
        self.prepare();self.w.navigate(2);QTest.qWait(60)
        scroll=self.w.pages.widget(2);bar=scroll.verticalScrollBar();bar.setValue(0)
        card=self.w.cards[2];card.inputs[0].setValue(1.29)
        QTest.mouseClick(card.buttons['apply'],Qt.MouseButton.LeftButton);QTest.qWait(120)
        self.assertEqual(bar.value(),0)

    def test_pending_note_accepts_float32_readback_and_never_claims_boot_saved(self):
        self.w.data.put(136,1,[False,0,0,''],received=False)
        self.w._render_pid_state(time.monotonic())
        self.assertNotIn('SAVED',self.w.pid_state.text())
        card=self.w.cards[2];applied=[struct.unpack('f',struct.pack('f',x))[0] for x in card.values()]
        self.w._pid_pending_cards[2]=(1,applied)
        card.note.setText('APPLIED LIVE · Save pending until DISARM.')
        self.w.data.put(136,1,[False,1,1,''],received=False);self.w._render_pid_state(time.monotonic())
        self.assertIn('SAVED after DISARM',card.note.text())
        self.w.data.put(136,1,[False,2,1,''],received=False);self.w._render_pid_state(time.monotonic())
        self.assertIn('unconfirmed',self.w.pid_state.text())
        self.w.data.put(136,1,[True,2,1,'PID_SAVE_FAILED'],received=False);self.w._render_pid_state(time.monotonic())
        self.assertIn('FAILED',self.w.pid_state.text());self.assertNotIn('SAVED',self.w.pid_state.text())

    def test_queued_pid_cannot_apply_after_fc_session_changes(self):
        self.prepare();calls=[]
        with patch.object(self.w,'_linked',side_effect=lambda work,done,*args:calls.append((work,done))):
            values=self.w.cards[2].values();values[0]=1.39
            self.w.settings_request(2,'apply',values)
        self.w.link.fc_session+=1
        with self.assertRaisesRegex(RuntimeError,'cancel|Cancel'):
            calls[0][0](self.w.link)
        self.assertNotEqual(self.w.link.values[2][0],1.39)
        calls[0][1](None,RuntimeError('Request cancelled'))
        self.assertFalse(self.w.command_busy)

if __name__=='__main__':unittest.main()
