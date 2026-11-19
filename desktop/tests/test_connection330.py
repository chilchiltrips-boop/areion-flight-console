"""Real localhost UDP plus injected OS failures; no physical FC is simulated as tested."""
import errno
import socket
import threading
import time
import unittest
from unittest.mock import patch

from zebjus_areion_link import Link, LinkError, Message, decode_frame, encode_frame
from zebjus_areion_link.transports import UDP


class Peer:
    """Small protocol fixture with delayed SAVE and exactly-once cached replies."""
    def __init__(self, save_delay=0, drop_save_reply=False):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.settimeout(.03)
        self.port = self.socket.getsockname()[1]
        self.delay = save_delay
        self.drop_save_reply = drop_save_reply
        self.stop = threading.Event()
        self.requests = []
        self.commits = 0
        self.saved = None
        self.active = [-.1, .03, .12]
        self.cache = {}
        self.ready_at = {}
        self.save_wait = False
        self.ping_during_save = False
        self.pending = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            now = time.monotonic()
            for due, reply, addr in list(self.pending):
                if now >= due:
                    self.socket.sendto(reply, addr)
                    self.save_wait = False
                    self.pending.remove((due, reply, addr))
            try:
                raw, addr = self.socket.recvfrom(4096)
            except socket.timeout:
                continue
            request = decode_frame(raw)
            self.requests.append(request)
            key = request.session, request.seq
            if key in self.cache:
                if time.monotonic() < self.ready_at.get(key, 0):
                    continue
                if request.type != 'SAVE' or not self.drop_save_reply:
                    self.socket.sendto(self.cache[key], addr)
                continue
            reply_type = 'ACK'
            if request.type == 'HELLO':
                data = ('HELLO', 12345)
            elif request.type == 'PING':
                self.ping_during_save |= self.save_wait
                data = ('PONG',)
            elif request.type == 'SAVE':
                self.commits += 1
                self.saved = list(self.active)
                data = ('SAVED',)
            elif request.type == 'READ':
                reply_type = 'DATA'
                if request.group == 120:
                    data = (False, True, True, 8, .004, 2000, 1, True, True, True)
                else:
                    data = tuple(self.saved if request.data else self.active)
            elif request.type == 'RELEASE':
                data = ('RELEASED',)
            elif request.type == 'CONTROL':
                continue
            else:
                reply_type, data = 'ERROR', ('UNKNOWN',)
            reply = encode_frame(Message(reply_type, request.group, request.schema,
                                         request.session, request.seq, data))
            self.cache[key] = reply
            if request.type == 'SAVE':
                self.ready_at[key] = now + self.delay
                if not self.drop_save_reply:
                    self.save_wait = True
                    self.pending.append((now + self.delay, reply, addr))
            else:
                self.socket.sendto(reply, addr)

    def close(self):
        self.stop.set()
        self.thread.join(.3)
        self.socket.close()


class FaultSocket:
    def __init__(self, real, send_errno=None, recv_errno=None):
        self.real = real
        self.send_errno = send_errno
        self.recv_errno = recv_errno
        self.frames = []

    def send(self, frame):
        self.frames.append(frame)
        if self.send_errno is not None:
            number, self.send_errno = self.send_errno, None
            raise OSError(number, 'injected socket error')
        return self.real.send(frame)

    def recv(self, size):
        if self.recv_errno is not None:
            number, self.recv_errno = self.recv_errno, None
            raise OSError(number, 'injected socket error')
        return self.real.recv(size)

    def close(self):
        self.real.close()


class Connection330Tests(unittest.TestCase):
    def setUp(self):
        self.peers = []
        self.links = []

    def tearDown(self):
        for link in self.links:
            link.close()
        for peer in self.peers:
            peer.close()

    def connect(self, **peer_options):
        peer = Peer(**peer_options)
        self.peers.append(peer)
        udp = UDP('127.0.0.1', peer.port)
        link = Link(udp, request_timeout=.08, retries=2, heartbeat_interval=.2)
        self.links.append(link)
        link.connect()
        return peer, udp, link

    def test_temporary_send_retries_identical_rpc_without_retiring_path(self):
        peer, udp, link = self.connect()
        udp._socket = fault = FaultSocket(udp._socket, send_errno=errno.ENOBUFS)
        link.read_group(6, schema=2)
        self.assertEqual(fault.frames[0], fault.frames[1])
        self.assertTrue(link.connected)
        self.assertTrue(link.transport_status[0]['active'])
        self.assertEqual(link.transport_status[0]['transient_errors'], 1)
        self.assertIsNone(link.transport_status[0]['error'])

    def test_transient_receive_recovers_on_same_socket_without_new_hello(self):
        peer, udp, link = self.connect()
        udp._socket = FaultSocket(udp._socket, recv_errno=errno.ECONNREFUSED)
        link.read_group(6, schema=2)
        self.assertTrue(link.connected)
        self.assertEqual(link.transport_status[0]['transient_errors'], 1)
        self.assertEqual(sum(m.type == 'HELLO' for m in peer.requests), 1)

    def test_control_send_error_propagates_without_replaying_values(self):
        peer, udp, link = self.connect()
        udp._socket = fault = FaultSocket(udp._socket, send_errno=errno.ENETUNREACH)
        with self.assertRaises(LinkError):
            link.send_control((1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000), datagram_only=True)
        self.assertEqual(len(fault.frames), 1)
        self.assertFalse(any(m.type == 'CONTROL' for m in peer.requests))
        self.assertTrue(link.transport_status[0]['active'])

    def test_permanent_socket_error_disables_path(self):
        peer, udp, link = self.connect()
        udp._socket = FaultSocket(udp._socket, send_errno=errno.EBADF)
        with self.assertRaises(LinkError):
            link.read_group(6, schema=2)
        self.assertFalse(link.connected)
        self.assertFalse(link.transport_status[0]['active'])

    def test_transient_errors_do_not_refresh_owner_or_receive_freshness(self):
        peer, udp, link = self.connect()
        link._heartbeat_stop.set()
        link._heartbeat_thread.join(.3)
        before = link._paths[0].last_received
        link._transient_path(link._paths[0], OSError('temporary error'))
        self.assertEqual(link._paths[0].last_received, before)
        link._last_owner_response = time.monotonic() - link.health_timeout - .1
        link._paths[0].last_received = link._last_owner_response
        self.assertFalse(link.connected)
        self.assertFalse(link.transport_status[0]['healthy'])

    def test_delayed_save_ack_is_verified_without_heartbeat_overtaking(self):
        from areion_gui.backend import save_section
        peer, udp, link = self.connect(save_delay=1.05)
        self.assertEqual(save_section(link, 6, peer.active), peer.active)
        saves = [m for m in peer.requests if m.type == 'SAVE']
        self.assertEqual(len(saves), 1)
        self.assertEqual(peer.commits, 1)
        self.assertTrue(link.connected)
        # No PING may replace the SAVE's single cached reply while waiting.
        self.assertFalse(peer.ping_during_save)
        self.assertTrue(any(m.type == 'READ' and m.data == ('saved',) for m in peer.requests))

    def test_lost_save_ack_stays_unknown_and_does_not_reapply(self):
        peer, udp, link = self.connect(drop_save_reply=True)
        with self.assertRaisesRegex(TimeoutError, 'outcome may be unknown'):
            link.save_group(6, schema=2)
        saves = [m for m in peer.requests if m.type == 'SAVE']
        self.assertEqual(len(saves), 2)
        self.assertEqual(saves[0], saves[1])
        self.assertEqual(peer.commits, 1)
        self.assertTrue(link.connected)
        self.assertEqual(link.read_group(6, schema=2, saved=True), peer.active)


if __name__ == '__main__':
    unittest.main()
