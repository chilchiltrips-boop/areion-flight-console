"""ACTION identity/retry/cancellation and exclusive RC transport regression tests."""
import threading
import time
import unittest

from zebjus_areion_link import Link, LinkError, Message, decode_frame, encode_frame
from zebjus_areion_link.schema import DRONE_GROUPS

CHANNELS = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)


class ReplyPath:
    def __init__(self, datagram):
        self.name = 'AP' if datagram else 'USB'
        self.datagram = datagram
        self.sent = []
        self.link = None
        self.path = None
        self.reply_arm = True
        self.reply_after = 1
        self.sent_event = threading.Event()
        self.bad_replies = []
        self.arm_code = 'ARMED'

    def send(self, frame):
        self.sent.append(frame)
        request = decode_frame(frame)
        self.sent_event.set()
        if request.type != 'ACTION':
            return
        if request.data == ('ARM',) and not self.reply_arm:
            return
        if len(self.sent) < self.reply_after:
            return
        for args in self.bad_replies:
            values = dict(type='ACK', group=request.group, schema=request.schema,
                          session=request.session, seq=request.seq, data=('ARMED',))
            values.update(args)
            self.link._handle(self.path, Message(**values))
        code = self.arm_code if request.data == ('ARM',) else 'DISARMED'
        self.link._handle(self.path, Message('ACK', request.group, request.schema,
                                           request.session, request.seq, (code,)))

    def receive(self):
        return b''

    def close(self):
        pass


def connected_link():
    usb, udp = ReplyPath(False), ReplyPath(True)
    link = Link(usb, udp, session=42, request_timeout=.08, retries=3)
    link._connected = True
    link.fc_session = 1234
    link._last_owner_response = time.monotonic()
    for transport, path in zip((usb, udp), link._paths):
        path.confirmed = True
        path.last_received = time.monotonic()
        transport.link, transport.path = link, path
    return link, usb, udp


class ActionSDKTests(unittest.TestCase):
    def test_action_wire_round_trip(self):
        request = Message('ACTION', 123, 1, 42, 7, ('ARM',))
        self.assertEqual(decode_frame(encode_frame(request)), request)

    def test_arm_on_serial_only_and_disarm_on_both(self):
        link, usb, udp = connected_link()
        self.assertEqual(link.arm(serial_only=True), ['ARMED'])
        self.assertEqual(udp.sent, [])
        self.assertEqual(decode_frame(usb.sent[0]).data, ('ARM',))
        self.assertEqual(link.disarm(), ['DISARMED'])
        self.assertEqual(decode_frame(udp.sent[0]).data, ('DISARM',))
        self.assertEqual(decode_frame(usb.sent[1]).seq, 2)
        self.assertEqual(usb.sent[1], udp.sent[0])

    def test_arm_datagram_only_does_not_use_usb(self):
        link, usb, udp = connected_link()
        self.assertEqual(link.arm(datagram_only=True), ['ARMED'])
        self.assertEqual(usb.sent, [])
        self.assertEqual(len(udp.sent), 1)

    def test_no_action_route_fallback(self):
        link, usb, udp = connected_link()
        link._paths[0].last_received -= 1
        with self.assertRaises(LinkError):
            link.arm(serial_only=True)
        self.assertEqual(usb.sent + udp.sent, [])

    def test_exact_retries_do_not_allocate_a_new_command(self):
        link, usb, udp = connected_link()
        usb.reply_after = 2
        self.assertEqual(link.arm(serial_only=True), ['ARMED'])
        self.assertEqual(len(usb.sent), 2)
        self.assertEqual(usb.sent[0], usb.sent[1])
        self.assertEqual(link._sequence, 1)
        self.assertEqual(udp.sent, [])

    def test_action_acks_require_current_identity_and_scalar_code(self):
        link, usb, _ = connected_link()
        usb.bad_replies = [dict(session=43), dict(seq=999), dict(group=122),
                           dict(schema=2), dict(data=()), dict(data=(True,)),
                           dict(data=('ARMED', 'extra')), dict(data=('',))]
        self.assertEqual(link.arm(serial_only=True), ['ARMED'])
        self.assertGreaterEqual(usb.path.rejected, 4)

    def test_convenience_arm_rejects_disarm_ack(self):
        link, usb, _ = connected_link()
        usb.arm_code = 'DISARMED'
        with self.assertRaisesRegex(LinkError, 'ARM reply'):
            link.arm(serial_only=True)

    def test_cancelled_queued_arm_does_not_run_after_disarm(self):
        link, usb, udp = connected_link()
        cancel = threading.Event()
        result = []
        started = threading.Event()
        link._rpc_lock.acquire()
        def arm():
            started.set()
            try:
                link.arm(serial_only=True, cancel=cancel)
            except LinkError as error:
                result.append(str(error))
        thread = threading.Thread(target=arm)
        thread.start()
        self.assertTrue(started.wait(.2))
        cancel.set()
        link._rpc_lock.release()
        self.assertEqual(link.disarm(), ['DISARMED'])
        thread.join(.5)
        self.assertFalse(thread.is_alive())
        self.assertIn('cancelled', result[0])
        self.assertTrue(all(decode_frame(frame).data == ('DISARM',)
                            for frame in usb.sent + udp.sent))
        self.assertEqual(link._sequence, 1)

    def test_cancel_interrupts_pending_wait_without_retries(self):
        link, usb, udp = connected_link()
        link.request_timeout = 2.0
        usb.reply_arm = False
        cancel = threading.Event()
        result = []
        def arm():
            try:
                link.arm(serial_only=True, cancel=cancel)
            except LinkError as error:
                result.append(str(error))
        thread = threading.Thread(target=arm)
        thread.start()
        self.assertTrue(usb.sent_event.wait(.2))
        stop_time = time.monotonic()
        cancel.set()
        thread.join(.25)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - stop_time, .25)
        self.assertEqual(len(usb.sent), 1)
        self.assertIn('cancelled', result[0])
        self.assertIsNone(link._pending)
        self.assertEqual(link.disarm(), ['DISARMED'])
        self.assertEqual(decode_frame(usb.sent[-1]).seq, 2)

    def test_callable_cancel_prevents_first_send(self):
        link, usb, udp = connected_link()
        with self.assertRaisesRegex(LinkError, 'cancelled'):
            link.arm(cancel=lambda: True)
        self.assertEqual(usb.sent + udp.sent, [])


class ControlRouteSDKTests(unittest.TestCase):
    def test_usb_only_frames_never_sent_on_ap(self):
        link, usb, udp = connected_link()
        link.send_control(CHANNELS, serial_only=True)
        self.assertEqual(udp.sent, [])
        message = decode_frame(usb.sent[0])
        self.assertEqual((message.type, message.data, message.seq), ('CONTROL', CHANNELS, 1))
        self.assertEqual(link._sequence, 0)
        link.send_control(CHANNELS, datagram_only=True)
        self.assertEqual(decode_frame(udp.sent[0]).seq, 2)

    def test_stale_usb_does_not_fall_back_to_ap(self):
        link, usb, udp = connected_link()
        link._paths[0].last_received -= 1
        with self.assertRaises(LinkError):
            link.send_control(CHANNELS, serial_only=True)
        self.assertEqual(usb.sent + udp.sent, [])

    def test_unconfirmed_usb_does_not_fall_back_to_ap(self):
        link, usb, udp = connected_link()
        link._paths[0].confirmed = False
        with self.assertRaises(LinkError):
            link.send_control(CHANNELS, serial_only=True)
        self.assertEqual(usb.sent + udp.sent, [])

    def test_bad_route_filters_are_rejected_before_sequence_allocation(self):
        link, usb, udp = connected_link()
        for kwargs in ({'serial_only': 1}, {'datagram_only': 1},
                       {'serial_only': True, 'datagram_only': True}):
            with self.assertRaises(ValueError):
                link.send_control(CHANNELS, **kwargs)
            with self.assertRaises(ValueError):
                link.arm(**kwargs)
        self.assertEqual(link._sequence, 0)
        self.assertEqual(link._control_sequence, 0)
        self.assertEqual(usb.sent + udp.sent, [])

    def test_captured_control_is_not_replayed_after_blocked_writer(self):
        link, usb, udp = connected_link()
        result = []
        link._send_lock.acquire()
        started = threading.Event()
        def send():
            started.set()
            try:
                link.send_control(CHANNELS, serial_only=True)
            except LinkError as error:
                result.append(str(error))
        thread = threading.Thread(target=send)
        thread.start()
        self.assertTrue(started.wait(.2))
        time.sleep(.18)
        link._send_lock.release()
        thread.join(.3)
        self.assertFalse(thread.is_alive())
        self.assertIn('stale', result[0])
        self.assertEqual(usb.sent + udp.sent, [])

    def test_reference_matches_registered_main_groups(self):
        self.assertEqual(set(DRONE_GROUPS), {2, 3, 4, 6, 7, 9, 21, 22, 23, 110, 112, 120, 121, 122, 123, 125, 130, 131, 132, 134, 135, 136, 137})
        self.assertEqual(DRONE_GROUPS[6]['name'], 'IMU_SETTINGS')
        self.assertEqual(DRONE_GROUPS[6]['schema'], 2)
        self.assertEqual([f['default'] for f in DRONE_GROUPS[6]['fields']], [-.1, .03, .12])
        self.assertEqual(DRONE_GROUPS[122]['schema'], 2)
        self.assertEqual(DRONE_GROUPS[122]['fields'][8]['name'], 'USBFresh')
        self.assertEqual(DRONE_GROUPS[123]['access'], 'action')
        for group,count in ((130,16),(131,11),(132,32),(134,11),(135,5),(136,4),(137,11)):
            self.assertEqual(DRONE_GROUPS[group]['schema'],1)
            self.assertEqual(len(DRONE_GROUPS[group]['fields']),count)
        self.assertTrue(DRONE_GROUPS[132]['persistent'])
        self.assertTrue(DRONE_GROUPS[134]['persistent'])
        self.assertEqual(DRONE_GROUPS[135]['access'],'action')


if __name__ == '__main__':
    unittest.main()
