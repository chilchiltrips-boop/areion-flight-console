"""PPM telemetry drives the display only, never the outgoing control array."""
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from areion_gui.model import NEUTRAL, PpmMonitor, Telemetry
from fc_fixture import make_test_window
from setup_fixtures import complete_demo_window


def status(count=8, ready=True, fresh=True):
    return [0, 1 if ready and fresh else 0, fresh, False, ready, count, 0, 7, False]


class PpmMonitorModelTests(unittest.TestCase):
    def test_requires_fresh_active_ppm_and_channel_array(self):
        data=Telemetry();monitor=PpmMonitor()
        data.put(122,2,status(),10);data.put(22,1,NEUTRAL,10)
        selected,values,note=monitor.view(data,True,10.1)
        self.assertTrue(selected);self.assertEqual(values,NEUTRAL);self.assertIn('PPM LIVE',note)
        self.assertIsNone(monitor.view(data,True,10.6)[1])
        self.assertIsNone(monitor.view(data,False,10.1)[1])

    def test_fc_frame_age_and_host_status_expire_separately(self):
        data = Telemetry()
        monitor = PpmMonitor()
        current = status()
        current[6] = 8
        data.put(122,2,current,10)
        data.put(22,1,NEUTRAL,10.02)
        self.assertEqual(monitor.view(data,True,10.30)[1],NEUTRAL)
        current[6] = 250
        data.put(122,2,current,10.31)
        self.assertIn('FRAME STALE',monitor.view(data,True,10.31)[2])
        current[6] = 8
        data.put(122,2,current,10.32)
        self.assertIsNone(monitor.view(data,True,10.32)[1])
        data.put(22,1,NEUTRAL,10.40)
        self.assertEqual(monitor.view(data,True,10.40)[1],NEUTRAL)
        data.put(22,1,NEUTRAL,10.8)
        self.assertIn('STATUS STALE',monitor.view(data,True,10.83)[2])

    def test_same_batch_old_usb_array_is_not_relabelled_as_ppm(self):
        data=Telemetry();monitor=PpmMonitor()
        data.put(22,1,[2000]*8,10)
        data.put(122,2,status(),10)  # Same receipt time, but newer status.
        self.assertIsNone(monitor.view(data,True,10)[1])
        data.put(22,1,NEUTRAL,10)
        self.assertEqual(monitor.view(data,True,10)[1],NEUTRAL)
        data.put(122,2,status(ready=False),10.1)
        self.assertIn('WAITING FOR NEUTRAL',monitor.view(data,True,10.1)[2])
        data.put(122,2,status(),10.2)
        self.assertIsNone(monitor.view(data,True,10.2)[1])
        data.put(22,1,NEUTRAL,10.2)
        self.assertEqual(monitor.view(data,True,10.2)[1],NEUTRAL)

    def test_missing_aux_channels_and_invalid_values_are_not_live_readings(self):
        data=Telemetry();monitor=PpmMonitor()
        data.put(122,2,status(4),10);data.put(22,1,NEUTRAL,10)
        self.assertEqual(monitor.view(data,True,10)[1],NEUTRAL[:4]+[None]*4)
        data.put(22,1,[-1]+NEUTRAL[1:],10)
        self.assertIsNone(monitor.view(data,True,10)[1])
        self.assertIn('INVALID',monitor.view(data,True,10)[2])


class PpmMonitorQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.w=make_test_window();self.w.show();QTest.qWait(200)
        self.w._select_source_value(0);self.w.select_source()
        self.wait_for(lambda:self.w.link.source==0 and not self.w.command_busy)
        self.wait_for(lambda:'PPM LIVE' in self.w.tx_view.text())

    def tearDown(self):
        self.w.close();QTest.qWait(150)

    def wait_for(self,condition):
        deadline=time.monotonic()+2
        while not condition() and time.monotonic()<deadline:QTest.qWait(20)
        self.assertTrue(condition(),self.w.last_notice)

    def test_physical_channels_mirror_both_sticks_aux_and_bars_without_echo(self):
        before=self.w.controls.values[:]
        with patch.object(self.w.link,'send_control') as send, \
             patch.object(self.w.link,'arm') as arm, patch.object(self.w.link,'disarm') as disarm:
            values=[1800,1200,1700,1100,2000,1250,1750,1000]
            self.w.link.demo_set_receiver(values)
            self.wait_for(lambda:self.w.channel_labels[0].text()=='1800')
            self.assertAlmostEqual(self.w.right_stick.x,.6);self.assertAlmostEqual(self.w.right_stick.y,-.6)
            self.assertAlmostEqual(self.w.left_stick.x,-.8);self.assertAlmostEqual(self.w.left_stick.y,.4)
            self.assertEqual([s.value() for s in self.w.aux],values[4:])
            self.assertEqual([b.value() for b in self.w.channel_bars],values)
            self.assertEqual(self.w.controls.values,before)
            self.assertFalse(self.w.session.running)
            send.assert_not_called();arm.assert_not_called();disarm.assert_not_called()

    def test_keyboard_and_mouse_do_not_modify_ppm_display_or_tx(self):
        self.w.link.demo_set_receiver([1700,1600,1400,1200,2000,1000,2000,1000])
        self.wait_for(lambda:self.w.channel_labels[0].text()=='1700')
        before=self.w.controls.values[:]
        self.w.setFocus()
        with patch.object(self.w.link,'send_control') as send:
            for key in (Qt.Key.Key_Left,Qt.Key.Key_Up,Qt.Key.Key_W,Qt.Key.Key_6):
                QTest.keyClick(self.w,key)
            QTest.mouseClick(self.w.right_stick,Qt.MouseButton.LeftButton,pos=QPoint(100,100))
            self.w._aux(6,1200);self.w._stick_input(True,1,1,True)
            QTest.qWait(100)
            self.assertEqual(self.w.controls.values,before)
            self.assertEqual(self.w.channel_labels[0].text(),'1700')
            self.assertFalse(self.w.left_stick.isEnabled());self.assertFalse(self.w.keyboard.isEnabled())
            self.assertTrue(all(not s.isEnabled() for s in self.w.aux))
            send.assert_not_called()

    def test_signal_loss_neutral_gate_and_disconnect_blank_the_display(self):
        self.w.timer.stop();now=time.monotonic()
        self.w.data.put(122,2,status(fresh=False,ready=False),now)
        self.w.render_status(now)
        self.assertIn('SIGNAL LOST',self.w.tx_view.text())
        self.assertFalse(self.w.left_stick.available)
        self.assertTrue(all(x.text()=='—' for x in self.w.channel_labels))
        self.w.data.put(122,2,status(ready=False),now)
        self.w.render_status(now);self.assertIn('WAITING FOR NEUTRAL',self.w.tx_view.text())
        self.w.data.put(122,2,status(),now)
        self.w.data.put(22,1,NEUTRAL,now)
        self.w.render_status(now);self.assertTrue(self.w.left_stick.available)
        self.w.link.connected=False;self.w.render_status(now)
        self.assertIn('OFFLINE',self.w.tx_view.text());self.assertFalse(self.w.right_stick.available)

    def test_channel_staleness_and_four_channel_receiver_do_not_show_fake_aux(self):
        self.w.timer.stop();now=time.monotonic()
        self.w.data.put(122,2,status(4),now);self.w.data.put(22,1,NEUTRAL,now)
        self.w.render_status(now)
        self.assertTrue(self.w.left_stick.available)
        self.assertTrue(all(x.text()=='—' for x in self.w.channel_labels[4:]))
        self.w.data.put(122,2,status(4),now+.6)
        self.w.render_status(now+.6)
        self.assertIn('CHANNELS STALE',self.w.tx_view.text())
        self.assertFalse(self.w.left_stick.available)

    def test_switch_back_to_usb_uses_neutral_tx_and_existing_control_behavior(self):
        self.w.link.demo_set_receiver([2000]*8)
        self.wait_for(lambda:self.w.channel_labels[2].text()=='2000')
        self.w._select_source_value(2);self.w.select_source()
        self.wait_for(lambda:self.w.link.source==2 and not self.w.command_busy)
        complete_demo_window(self.w,2)
        self.w.start_stream()
        self.wait_for(lambda:self.w.session.running and self.w.session.ready)
        self.assertEqual(self.w.link.channels,NEUTRAL)
        self.assertEqual(self.w.controls.values,NEUTRAL)
        self.assertTrue(self.w.left_stick.isEnabled());self.assertTrue(self.w.keyboard.isEnabled())
        self.assertIn('TX command',self.w.channels_caption.text())


if __name__=='__main__':unittest.main()
