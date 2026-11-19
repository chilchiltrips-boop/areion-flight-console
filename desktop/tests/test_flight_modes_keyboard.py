"""Real Qt key-repeat/focus events, flight-mode routing and saved mapping."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QLineEdit
from areion_gui.model import DEFAULT_KEYS, flight_mode_for_value, validate_values
from fc_fixture import make_test_window
from setup_fixtures import complete_demo_window


class FlightModeModelTests(unittest.TestCase):
    def test_midpoint_and_reversed_mapping(self):
        for low in (0, 1):
            settings=[5,.1,.15,.15,low,1-low]
            for value in (1000,1499,1500,1501,2000):
                self.assertEqual(flight_mode_for_value(settings,value),low if value<1500 else 1-low)
        with self.assertRaisesRegex(ValueError,'different'):
            validate_values(7,[5,.1,.15,.15,0,0])


class FlightModeKeyboardQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setOrganizationName('ZebjusTest')
        cls.app.setApplicationName('AreionModeTest')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.w=make_test_window()
        self.w.config_path=Path(self.temp.name)/'controls.json'
        self.w.controls.set_bindings(DEFAULT_KEYS)
        self.w.show();QTest.qWait(200)
        complete_demo_window(self.w);QTest.qWait(80)

    def tearDown(self):
        self.w.close();QTest.qWait(200);self.temp.cleanup()

    def wait_for(self,condition):
        deadline=time.monotonic()+2.0
        while not condition() and time.monotonic()<deadline:QTest.qWait(20)
        self.assertTrue(condition(),self.w.last_notice)

    def select_and_start(self,source=1):
        self.w.navigate(0)
        self.w._select_source_value(source);self.w.select_source()
        self.wait_for(lambda:self.w.link.source==source and not self.w.command_busy)
        complete_demo_window(self.w, source)
        self.w.start_stream()
        self.wait_for(lambda:self.w.session.running and self.w.session.ready)

    def save_modes(self,values):
        self.w.navigate(2);card=self.w.cards[7]
        self.wait_for(lambda:card.loaded)
        for field,value in zip(card.inputs,values):field.setValue(value)
        card._request('apply');self.wait_for(lambda:not card.busy)
        self.assertEqual(self.w.link.values[7],values)
        self.assertNotEqual(self.w.link.saved[7],values)
        card._request('save');self.wait_for(lambda:not card.busy)
        self.assertEqual(self.w.link.saved[7],values)
        self.assertIn('SAVED',card.note.text())

    def key(self,target,kind,key,repeat=False):
        self.app.sendEvent(target,QKeyEvent(kind,key,Qt.KeyboardModifier.NoModifier,'',repeat,1))
        self.w.controls.step(.02,True)

    def test_held_arrows_do_not_change_focused_ch7_or_ch8(self):
        self.w.timer.stop()
        for index in (2,3):
            slider=self.w.aux[index];slider.setValue(1500);slider.setFocus();self.app.processEvents()
            for key,channel,value in ((Qt.Key.Key_Left,0,1000),(Qt.Key.Key_Right,0,2000),
                                      (Qt.Key.Key_Up,1,2000),(Qt.Key.Key_Down,1,1000)):
                before=self.w.controls.values[4:]
                self.key(slider,QEvent.Type.KeyPress,key)
                for _ in range(5):
                    self.key(slider,QEvent.Type.KeyRelease,key,True)
                    self.key(slider,QEvent.Type.KeyPress,key,True)
                self.assertEqual(self.w.controls.values[channel],value)
                self.assertEqual(self.w.controls.values[4:],before)
                self.key(slider,QEvent.Type.KeyRelease,key)
                self.assertEqual(self.w.controls.values[channel],1500)

    def test_saved_custom_keys_and_unassigned_arrows_do_not_leak_to_aux(self):
        def edit():
            dialog=QApplication.activeModalWidget()
            combos=dialog.findChildren(QComboBox)
            for item,key in zip(combos[:4],('J','L','K','I')):item.setCurrentText(key)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(40,edit);self.w.configure_keys()
        saved=json.loads(self.w.config_path.read_text())['keys']
        self.assertEqual(saved[:2],[['J','L'],['K','I']])
        self.assertEqual(self.w.controls.keys[:2],[('J','L'),('K','I')])
        self.w.timer.stop();slider=self.w.aux[3];slider.setFocus();self.app.processEvents()
        before=self.w.controls.values[4:]
        self.key(slider,QEvent.Type.KeyPress,Qt.Key.Key_L)
        self.key(slider,QEvent.Type.KeyPress,Qt.Key.Key_L,True)
        self.assertEqual(self.w.controls.values[0],2000)
        self.key(slider,QEvent.Type.KeyRelease,Qt.Key.Key_L)
        for key in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            self.key(slider,QEvent.Type.KeyPress,key)
            self.key(slider,QEvent.Type.KeyPress,key,True)
            self.key(slider,QEvent.Type.KeyRelease,key)
        self.assertEqual(self.w.controls.values[:2],[1500,1500])
        self.assertEqual(self.w.controls.values[4:],before)

    def test_other_window_keys_do_not_operate_the_transmitter(self):
        self.w.timer.stop();editor=QLineEdit();editor.show();editor.setFocus();self.app.processEvents()
        before=self.w.controls.values[:]
        self.key(editor,QEvent.Type.KeyPress,Qt.Key.Key_W)
        self.assertEqual(self.w.controls.values,before)
        self.assertNotIn('W',self.w.controls.pressed)
        editor.close()

    def test_ap_mode_buttons_send_only_configured_channel_and_confirm_telemetry(self):
        self.select_and_start(1)
        self.wait_for(lambda:'ANGLE' in self.w.mode_actual.text())
        self.w.timer.stop();before=self.w.controls.values[:]
        self.w.choose_flight_mode(1)
        self.assertEqual(self.w.controls.values[4],2000)
        self.assertEqual(self.w.controls.values[:4],before[:4])
        self.assertEqual(self.w.controls.values[5:],before[5:])
        self.assertIn('ANGLE',self.w.mode_actual.text())  # No optimistic FC claim.
        self.assertIn('RATE / ACRO',self.w.mode_note.text())
        self.w.timer.start()
        self.wait_for(lambda:self.w.link.channels[4]==2000 and 'RATE / ACRO' in self.w.mode_actual.text())
        self.w.choose_flight_mode(0)
        self.wait_for(lambda:self.w.link.channels[4]==1000 and 'ANGLE' in self.w.mode_actual.text())

    def test_saved_reversed_ch8_mapping_controls_usb_even_while_armed(self):
        values=[8,.1,.15,.15,1,0];self.save_modes(values)
        self.select_and_start(2)
        self.wait_for(lambda:'RATE / ACRO' in self.w.mode_actual.text())
        self.w.arm();self.wait_for(lambda:self.w.link.armed and not self.w.command_busy)
        before=self.w.controls.values[:]
        self.w.choose_flight_mode(0)
        self.wait_for(lambda:self.w.link.channels[7]==2000 and 'ANGLE' in self.w.mode_actual.text())
        self.assertEqual(self.w.controls.values[:7],before[:7]);self.assertTrue(self.w.link.armed)
        self.w.choose_flight_mode(1)
        self.wait_for(lambda:self.w.link.channels[7]==1000 and 'RATE / ACRO' in self.w.mode_actual.text())

    def test_ppm_mode_display_is_read_only_and_stale_status_is_unknown(self):
        complete_demo_window(self.w,source=0)
        self.w._select_source_value(0);self.w.select_source()
        self.wait_for(lambda:self.w.link.source==0 and not self.w.command_busy)
        channels=self.w.link.raw_channels[:];channels[4]=2000
        self.w.link.demo_set_receiver(channels)
        self.wait_for(lambda:'RATE / ACRO' in self.w.mode_actual.text())
        self.assertTrue(all(not b.isEnabled() for b in self.w.mode_buttons.values()))
        before=self.w.controls.values[:];self.w.choose_flight_mode(0)
        self.assertEqual(self.w.controls.values,before)
        self.w.timer.stop();now=time.monotonic()
        values,_=self.w.data.latest[120];self.w.data.latest[120]=(values,now-1)
        self.w.render_status(now)
        self.assertIn('UNKNOWN / STALE',self.w.mode_actual.text())

    def test_mode_buttons_never_drive_a_stick_or_throttle_channel(self):
        self.select_and_start(1)
        # Incompatible telemetry must not let the GUI drive throttle, even
        # though current firmware rejects saving an overlapping mode channel.
        self.w.timer.stop();self.w.data.put(7,3,[3,.1,.15,.15,0,1])
        self.w.render_status(time.monotonic())
        self.assertTrue(all(not b.isEnabled() for b in self.w.mode_buttons.values()))
        before=self.w.controls.values[:];self.w.choose_flight_mode(1)
        self.assertEqual(self.w.controls.values,before)
        self.assertEqual(self.w.controls.values[2],1000)


if __name__=='__main__':unittest.main()
