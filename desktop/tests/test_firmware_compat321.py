"""Connection qualification must retain required-schema and cleanup checks."""
import threading
import unittest
from unittest.mock import Mock, patch

from fc_fixture import DemoLink
from areion_gui.backend import open_link


class FirmwareCompatibilityTests(unittest.TestCase):
    def test_new_version_does_not_bypass_required_groups(self):
        options = dict(mode='AP', ssid='aerion drone', host='192.168.4.1', udp_port=8080)
        for missing in (130, 132, 134, 136):
            with self.subTest(group=missing):
                demo = DemoLink()

                def read(group, schema=1):
                    if group == missing:
                        raise RuntimeError('GROUP_NOT_FOUND')
                    values = demo.read_group(group, schema)
                    if group == 125:
                        values[0] = '3.2.0'
                    return values

                link = Mock(read_group=Mock(side_effect=read))
                with patch('areion_gui.backend.UDP', return_value=Mock(datagram=True)), \
                     patch('areion_gui.backend.check_wifi', return_value=None), \
                     patch('areion_gui.backend.Link', return_value=link):
                    with self.assertRaisesRegex(RuntimeError, f'Group {missing}'):
                        open_link(options, threading.Event())
                link.close.assert_called_once()
                link.send_control.assert_not_called()
                link.arm.assert_not_called()
