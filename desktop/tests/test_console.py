import contextlib
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import areion_usb as console


class FakeLink:
    def __init__(self, armed=False, storage=True):
        self.status=[armed,True,True,8,0.004,2000,1000,storage,False,False]
        self.pid=[0.9,0.9,3.0,15.0,15.0,15.0,0.03,0.03,0.0]
        self.saved=self.pid[:]
        self.calls=[]
    def read_group(self,g,schema=1,saved=False):
        self.calls.append(('read',g,saved))
        return self.status[:] if g==120 else (self.saved[:] if saved else self.pid[:])
    def set_group(self,g,values,schema=1):
        self.calls.append(('set',g)); self.pid=values[:]; return ['APPLIED_UNSAVED']
    def save_group(self,g,schema=1):
        self.calls.append(('save',g)); self.saved=self.pid[:]; return ['SAVED']


class ConsoleTests(unittest.TestCase):
    def test_saved_read_never_writes(self):
        link=FakeLink()
        with contextlib.redirect_stdout(io.StringIO()): console.read_saved_pid(link,2)
        self.assertEqual(link.calls,[('read',2,True)])
    def test_explicit_save_reads_back_storage(self):
        link=FakeLink()
        with patch('builtins.input',return_value='2'), contextlib.redirect_stdout(io.StringIO()):
            console.save_pid(link)
        self.assertEqual(link.calls,[('read',120,False),('read',2,False),('save',2),('read',2,True)])
    def test_armed_or_missing_storage_blocks_save(self):
        for armed,storage in [(True,True),(False,False)]:
            link=FakeLink(armed,storage)
            with patch('builtins.input',return_value='2'),self.assertRaises(ValueError): console.save_pid(link)
            self.assertFalse(any(c[0]=='save' for c in link.calls))
    def test_arm_change_while_typing_blocks_set(self):
        link=FakeLink()
        def enter(_):
            link.status[0]=True
            return '0.9,0.9,3,15,15,15,0.03,0.03,0'
        with patch('builtins.input',side_effect=enter),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
            console.edit_pid(link,2)
        self.assertFalse(any(c[0]=='set' for c in link.calls))
    def test_invalid_pid_arrays_rejected(self):
        for data in ['[true,0,0,0,0,0,0,0,0]','[NaN,0,0,0,0,0,0,0,0]','1,2','101,0,0,0,0,0,0,0,0']:
            with self.assertRaises(ValueError): console.parse_pid(data,2)
    def test_status_matches_delivered_firmware(self):
        self.assertEqual(len(console.FIELD_NAMES[120]),10)
        self.assertEqual(console.get_status(FakeLink())[3],8)

class TransportTests(unittest.TestCase):
    def setUp(self):
        patcher=patch.object(console,"report_wifi")
        patcher.start(); self.addCleanup(patcher.stop)
    def args(self, mode="both"):
        return SimpleNamespace(transport=mode,port="/dev/cu.usbmodem101",baud=115200,
                               host="192.168.4.1",udp_port=8080)
    def test_both_uses_one_collection_with_two_paths(self):
        usb, ap = object(), object()
        with contextlib.redirect_stdout(io.StringIO()):
            paths, opened = console.open_transports(self.args(), lambda *a:usb, lambda *a:ap)
        self.assertEqual(paths,[usb,ap])
        self.assertTrue(opened)
    def test_usb_open_failure_keeps_ap(self):
        ap = object()
        def broken(*a): raise OSError("device busy")
        with contextlib.redirect_stdout(io.StringIO()):
            paths, opened = console.open_transports(self.args(), broken, lambda *a:ap)
        self.assertEqual(paths,[ap])
        self.assertFalse(opened)
    def test_ap_open_failure_keeps_usb(self):
        usb = object()
        def broken(*a): raise OSError("no route")
        with contextlib.redirect_stdout(io.StringIO()):
            paths, opened = console.open_transports(self.args(), lambda *a:usb, broken)
        self.assertEqual(paths,[usb])
        self.assertTrue(opened)
    def test_ap_only_never_opens_usb(self):
        ap = object()
        with patch('builtins.print'), patch.object(console.time,'sleep') as sleep:
            def forbidden(*a): self.fail("USB must not be opened")
            paths, opened = console.open_transports(self.args("ap"), forbidden, lambda *a:ap)
        self.assertEqual(paths,[ap])
        self.assertFalse(opened)
        sleep.assert_not_called()
    def test_route_status_does_not_call_stale_route_ready(self):
        link = SimpleNamespace(transport_status=[{"name":"AP", "active":True,
            "confirmed":True,"error":None,"last_received_age":9.0}])
        output=io.StringIO()
        with contextlib.redirect_stdout(output): console.show_transport_status(link)
        self.assertIn("STALE",output.getvalue())
        self.assertNotIn("READY",output.getvalue())
    def test_link_status_unknown_group_is_nonfatal(self):
        class UnknownGroup(Exception): code="UNKNOWN_GROUP"
        link = SimpleNamespace(read_group=lambda *a,**k: (_ for _ in ()).throw(UnknownGroup()))
        with contextlib.redirect_stdout(io.StringIO()): console.show_fc_link_status(link)

class MainFlowTests(unittest.TestCase):
    def setUp(self):
        patcher=patch.object(console,"report_wifi")
        patcher.start(); self.addCleanup(patcher.stop)
    def sdk(self):
        usb, ap = Mock(name="usb"), Mock(name="ap")
        instance = SimpleNamespace(fc_session=123,connected=True,transport_status=[],
            release_confirmed=True,release_error=None,connect=Mock(),ping=Mock(),close=Mock(),
            read_group=Mock(side_effect=lambda group,**kwargs: {
                120:[False,True,True,8,.004,2000,1000,True,False,False],
                121:[True,"192.168.4.1",8080,5000],
                122:[0,1,True,False,True,8,1,42,False]}[group]))
        factory=Mock(return_value=instance)
        sdk=SimpleNamespace(Link=factory,SerialTransport=Mock(return_value=usb),
                            UDP=Mock(return_value=ap))
        return sdk,instance,usb,ap
    def test_main_both_passes_paths_to_one_link_then_closes(self):
        sdk,link,usb,ap=self.sdk()
        with patch.dict(sys.modules,{"zebjus_areion_link":sdk}), \
                patch('builtins.input',return_value='0'), \
                patch.object(console.time,'sleep') as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            result=console.main(['--transport','both','--port','/dev/cu.usbmodem101'])
        self.assertEqual(result,0)
        sdk.Link.assert_called_once_with(usb,ap,request_timeout=1.0,retries=3)
        sleep.assert_called_once_with(4.0)
        link.connect.assert_called_once()
        link.ping.assert_called_once()
        link.close.assert_called_once()
    def test_main_ap_has_no_usb_open_or_startup_wait(self):
        sdk,link,usb,ap=self.sdk()
        with patch.dict(sys.modules,{"zebjus_areion_link":sdk}), \
                patch('builtins.input',return_value='0'), \
                patch.object(console.time,'sleep') as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(console.main(['--transport','ap']),0)
        sdk.SerialTransport.assert_not_called()
        sdk.Link.assert_called_once_with(ap,request_timeout=1.0,retries=3)
        sleep.assert_not_called()
        link.close.assert_called_once()
    def test_release_failure_is_not_reported_as_confirmed(self):
        sdk,link,usb,ap=self.sdk()
        link.release_confirmed=False
        link.release_error='WRITE_LOCKED'
        output=io.StringIO()
        with patch.dict(sys.modules,{"zebjus_areion_link":sdk}), \
                patch('builtins.input',return_value='0'), contextlib.redirect_stdout(output):
            self.assertEqual(console.main(['--transport','ap']),0)
        self.assertIn('Ownership release not confirmed: WRITE_LOCKED',output.getvalue())
        self.assertNotIn('FC ownership released.',output.getvalue())


    def test_ping_failure_never_prints_fc_connected_or_opens_menu(self):
        sdk,link,usb,ap=self.sdk()
        link.ping.side_effect=TimeoutError("PING timeout")
        output=io.StringIO()
        with patch.dict(sys.modules,{"zebjus_areion_link":sdk}), \
                patch('builtins.input') as menu, contextlib.redirect_stdout(output):
            self.assertEqual(console.main(['--transport','ap']),1)
        menu.assert_not_called()
        self.assertNotIn('FC CONNECTED:',output.getvalue())
        link.close.assert_called_once()

    def test_invalid_status_never_prints_fc_connected(self):
        sdk,link,usb,ap=self.sdk()
        link.read_group.return_value=[]
        link.read_group.side_effect=None
        output=io.StringIO()
        with patch.dict(sys.modules,{"zebjus_areion_link":sdk}), \
                patch('builtins.input') as menu, contextlib.redirect_stdout(output):
            self.assertEqual(console.main(['--transport','ap']),1)
        menu.assert_not_called()
        self.assertNotIn('FC CONNECTED:',output.getvalue())

if __name__=='__main__':unittest.main()
