"""Regression tests for the loopback host and its exclusive control lease."""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from browser_host.server import CONTROL_TIMEOUT, IDLE_TIMEOUT, Server, Session


class LocalBrowserHost(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.events = []
        self.resets = []
        self.session = Session(lambda gen, events: self.events.append((gen, events)), self.resets.append,
                               lambda: self.now)
        self.http = Server(0, self.session)
        threading.Thread(target=self.http.serve_forever, args=(.02,), daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        data = {'Content-Type': 'application/json', 'X-Areion-Token': self.session.token,
                'Origin': self.http.origin, **(headers or {})}
        if isinstance(body, dict):
            body = json.dumps(body)
        conn.request(method, path, body, headers=data)
        response = conn.getresponse()
        value = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return value

    def test_local_only_authentication_and_exclusive_control(self):
        for headers in ({'Host': 'attacker.test'}, {'Origin': 'https://example.org'},
                        {'X-Areion-Token':'wrong'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('POST', '/api/session', {}, headers)[0], 403)
        code, headers, data = self.request('POST', '/api/session', {})
        self.assertEqual(code, 200)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        client = {'X-Areion-Client': json.loads(data)['client']}
        self.assertEqual(self.request('POST', '/api/session', {})[0], 409)
        self.assertEqual(self.request('POST', '/api/ping', {}, client)[0], 204)
        self.assertEqual(self.request('POST', '/api/events', {'events': [{'type':'reset'}]}, client)[0], 200)
        self.assertEqual(self.events[-1][1], [{'type':'reset'}])
        self.assertEqual(self.request('POST', '/api/close', {}, client)[0], 204)
        self.assertEqual(len(self.resets), 1)
        self.assertEqual(self.request('POST', '/api/ping', {}, client)[0], 403)

    def test_stop_on_expired_browser_and_reject_queued_commands(self):
        client = self.session.acquire()['client']
        old = self.session.generation
        self.session.enqueue(client, [{'type':'down'}])
        self.session.active_controls = True
        self.now += CONTROL_TIMEOUT + .01
        self.assertFalse(self.session.consume(old, 1))
        self.assertEqual(len(self.resets), 1)
        new = self.session.acquire()['client']
        self.assertNotEqual(new, client)
        self.assertFalse(self.session.ping(client))
        self.assertFalse(self.session.consume(old, 1))
        self.now += IDLE_TIMEOUT + .01
        self.assertFalse(self.session.valid(new))

    def test_frames_and_liveness_are_independent(self):
        lease = self.session.acquire()['client']
        self.session.publish(b'jpeg', 1200, 750)
        code, headers, data = self.request('GET', '/api/frame?after=-1', headers={'X-Areion-Client':lease})
        self.assertEqual((code,data,headers['X-Frame-Width']), (200,b'jpeg','1200'))
        self.session.publish(b'jpeg', 1200, 750)
        self.assertEqual(self.session.frame_id, 1)
        self.now += IDLE_TIMEOUT + .01
        self.assertEqual(self.request('GET', '/api/frame?after=-1', headers={'X-Areion-Client':lease})[0],403)

    def test_local_entry_requires_a_same_origin_user_navigation(self):
        state = self.http.start_nonce
        body = 'nonce=' + state
        self.assertEqual(self.request('POST', '/start', body)[0],403)
        valid = {'Sec-Fetch-Site':'same-origin','Sec-Fetch-Mode':'navigate','Sec-Fetch-User':'?1'}
        self.assertEqual(self.request('POST','/start','nonce=wrong',valid)[0],403)
        status, headers, _ = self.request('POST','/start',body,valid)
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/#'+self.session.token)
        self.assertNotIn(self.session.token, self.request('GET','/start')[2].decode())


if __name__ == '__main__':
    unittest.main()
