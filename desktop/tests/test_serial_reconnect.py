"""USB reopen avoids deliberately toggling reset-control lines."""
import sys
import types
import unittest
from unittest.mock import patch
from zebjus_areion_link.transports import SerialTransport


class SerialReconnectTests(unittest.TestCase):
    def make_serial(self,fail=False):
        events=[]
        class Port:
            def __init__(self,**kwargs):
                events.append(('create',kwargs))
                self.port=kwargs['port'];self.is_open=False
            def __setattr__(self,key,value):
                if key in ('dtr','rts','port'):events.append((key,value))
                object.__setattr__(self,key,value)
            def open(self):
                events.append(('open',self.port,self.dtr,self.rts))
                if fail:raise OSError('port unavailable')
                self.is_open=True
            def close(self):events.append(('close',));self.is_open=False
        return types.SimpleNamespace(Serial=Port),events

    def test_control_lines_are_inactive_before_open(self):
        serial,events=self.make_serial()
        with patch.dict(sys.modules,{'serial':serial}):transport=SerialTransport('/dev/tty-kit')
        self.assertIsNone(events[0][1]['port'])
        opened=events.index(('open','/dev/tty-kit',False,False))
        self.assertLess(events.index(('dtr',False)),opened)
        self.assertLess(events.index(('rts',False)),opened)
        self.assertEqual(events[0][1]['timeout'],0)
        self.assertEqual(transport.name,'serial:///dev/tty-kit@115200')
        transport.close();self.assertEqual(events[-1],('close',))

    def test_failed_open_closes_partial_port_before_retry(self):
        serial,events=self.make_serial(fail=True)
        with patch.dict(sys.modules,{'serial':serial}),self.assertRaises(OSError):
            SerialTransport('/dev/missing')
        self.assertEqual(events[-1],('close',))


if __name__=='__main__':unittest.main()
