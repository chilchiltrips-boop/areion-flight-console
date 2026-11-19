import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import receiver_control as rc
from zebjus_areion_link import Link, LinkError, decode_frame


class Clock:
    def __init__(self): self.now=0.0; self.stall=False
    def monotonic(self): return self.now
    def sleep(self, seconds):
        self.now+=seconds
        if self.stall and self.now>0.4:
            self.now+=0.2; self.stall=False


class FakeFC:
    session=42
    connected=True
    def __init__(self,clock):
        self.clock=clock; self.values=[]; self.events=[]; self.selected=1
        self.ready=True; self.armed=False; self.stale_at=None; self.change_at=None
        self.interrupt_at=None;self.set_calls=[];self.saved=False
    @property
    def transport_status(self):
        age=1 if self.stale_at is not None and self.clock.now>=self.stale_at else 0
        return [{'name':'udp','datagram':self.selected!=2,'active':True,'confirmed':True,'last_received_age':age}]
    def read_group(self,group,**kwargs):
        if group==120:return [self.armed,True,True,8,.004,2000,100,True,False,False]
        if group==110:return [self.selected]
        return [self.selected,0,False,False,False,0,0xFFFFFFFF,self.session,False]
    def set_group(self,group,values,**kwargs):
        self.set_calls.append((group,values[:]))
        self.selected=values[0];return ['APPLIED_UNSAVED']
    def save_group(self,*args,**kwargs):self.saved=True
    def send_control(self,values,*,datagram_only=False,serial_only=False):
        if self.interrupt_at is not None and len(self.values)>=self.interrupt_at:raise KeyboardInterrupt()
        self.values.append((self.clock.now,tuple(values),datagram_only,serial_only))
        if len(self.values)%5==0:
            source=0 if self.change_at is not None and self.clock.now>=self.change_at else self.selected
            self.events.append(SimpleNamespace(group=122,schema=2,data=[source,self.selected+1,False,self.selected==1,self.ready,8,0,self.session,self.selected==2]))
    def poll(self,timeout=0):return self.events.pop(0) if self.events else None


class ReceiverTests(unittest.TestCase):
    target=[1600,1400,1100,1500,1000,1000,1000,1000]
    def setUp(self):
        self.clock=Clock();self.fc=FakeFC(self.clock)
        self.patch=patch.object(rc,'time',self.clock);self.patch.start();self.addCleanup(self.patch.stop)
    def test_channel_types_bounds_count(self):
        for text in ('[true,1500,1000,1500,1000,1000,1000,1000]','1500,1500','1500,1500,999,1500,1000,1000,1000,1000','1500.0,1500,1000,1500,1000,1000,1000,1000'):
            with self.assertRaises(ValueError):rc.parse_channels(text)
        self.assertEqual(rc.parse_channels('1500,1500,1000,1500,1000,1000,1000,1000'),list(rc.NEUTRAL_CHANNELS))
    def test_source_atomic_selection_no_save(self):
        with patch('builtins.input',return_value='0'),contextlib.redirect_stdout(io.StringIO()):rc.choose_input(self.fc)
        self.assertEqual(self.fc.set_calls,[(110,[0])]);self.assertFalse(self.fc.saved)
    def test_arming_while_typing_blocks_source_change(self):
        def typed(_):self.fc.armed=True;return '0'
        with patch('builtins.input',side_effect=typed),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):rc.choose_input(self.fc)
        self.assertEqual(self.fc.set_calls,[])
    def test_neutral_bootstrap_then_bounded_target_and_no_worker(self):
        with contextlib.redirect_stdout(io.StringIO()):count=rc.run_control_burst(self.fc,self.target,1)
        target=[entry for entry in self.fc.values if entry[1]==tuple(self.target)]
        self.assertTrue(target);self.assertGreaterEqual(target[0][0],.25)
        self.assertTrue(all(entry[2] for entry in self.fc.values))
        self.assertLess(self.clock.now,1.5)
        self.clock.sleep(10)
        self.assertEqual(len(self.fc.values),count)
    def test_never_ready_never_sends_target(self):
        self.fc.ready=False
        with self.assertRaises(RuntimeError):rc.run_control_burst(self.fc,self.target,1)
        self.assertTrue(all(v[1]==rc.NEUTRAL_CHANNELS for v in self.fc.values))
    def test_ppm_selection_prevents_ap_burst(self):
        self.fc.selected=0
        with self.assertRaises(ValueError):rc.run_control_burst(self.fc,self.target,1)
        self.assertEqual(self.fc.values,[])
    def test_armed_start_prevents_burst(self):
        self.fc.armed=True
        with self.assertRaises(ValueError):rc.run_control_burst(self.fc,self.target,1)
        self.assertEqual(self.fc.values,[])
    def test_stale_ap_stops_even_with_connected_usb(self):
        self.fc.stale_at=.5
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):rc.run_control_burst(self.fc,self.target,1)
        self.assertLessEqual(self.fc.values[-1][0],.5)
    def test_source_change_stops_burst(self):
        self.fc.change_at=.5
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):rc.run_control_burst(self.fc,self.target,1)
        self.assertLess(self.clock.now,.7)
    def test_keyboard_interrupt_stops_without_resume(self):
        self.fc.interrupt_at=20
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(KeyboardInterrupt):rc.run_control_burst(self.fc,self.target,1)
        self.assertEqual(len(self.fc.values),20)
    def test_scheduler_pause_does_not_replay_stale_input(self):
        self.clock.stall=True
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):rc.run_control_burst(self.fc,self.target,1)
        self.assertLess(self.fc.values[-1][0],.5)
    def test_invalid_duration_or_status(self):
        for n in (0,31,float('nan'),True):
            with self.assertRaises(ValueError):rc.run_control_burst(self.fc,self.target,n)
        for values in ([0], [2,0,False,False,False,0,0,42],[0,1,1,False,False,8,0,42]):
            with self.assertRaises(ValueError):rc.validate_input_status(values)


class Capture:
    def __init__(self,datagram):self.datagram=datagram;self.name='ap' if datagram else 'usb';self.sent=[]
    def send(self,frame):self.sent.append(frame)
    def close(self):pass


class SDKControlPathTests(unittest.TestCase):
    def link(self):
        import time
        usb,udp=Capture(False),Capture(True)
        link=Link(usb,udp,session=42)
        link._connected=True;link._last_owner_response=time.monotonic()
        for p in link._paths:p.confirmed=True;p.last_received=time.monotonic()
        return link,usb,udp
    def test_udp_only_control_never_sends_serial(self):
        link,usb,udp=self.link();link.send_control(rc.NEUTRAL_CHANNELS,datagram_only=True)
        self.assertEqual(usb.sent,[]);self.assertEqual(len(udp.sent),1)
        self.assertEqual(decode_frame(udp.sent[0]).type,'CONTROL')
    def test_stale_udp_no_usb_fallback(self):
        link,usb,udp=self.link();link._paths[1].last_received-=1
        with self.assertRaises(LinkError):link.send_control(rc.NEUTRAL_CHANNELS,datagram_only=True)
        self.assertEqual(usb.sent,[]);self.assertEqual(udp.sent,[])
    def test_legacy_control_default_still_broadcasts(self):
        link,usb,udp=self.link();link.send_control(rc.NEUTRAL_CHANNELS)
        self.assertEqual(usb.sent,udp.sent);self.assertEqual(len(usb.sent),1)
    def test_closing_link_rejects_control(self):
        link,usb,udp=self.link();link._closing=True
        with self.assertRaises(LinkError):link.send_control(rc.NEUTRAL_CHANNELS,datagram_only=True)
        self.assertEqual(usb.sent,[]);self.assertEqual(udp.sent,[])

if __name__=='__main__':unittest.main()
