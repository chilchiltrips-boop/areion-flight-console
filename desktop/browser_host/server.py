"""Loopback-only HTTP transport. Qt objects stay on the GUI thread."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).parent / 'static'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/client.js': ('client.js', 'text/javascript; charset=utf-8'),
          '/client.css': ('client.css', 'text/css; charset=utf-8')}
MAX_REQUEST = 32768
IDLE_TIMEOUT = 2.5
CONTROL_TIMEOUT = .35


class Session:
    def __init__(self, deliver, reset, clock=time.monotonic):
        self.deliver, self.reset, self.clock = deliver, reset, clock
        self.lock = threading.Condition()
        self.token = secrets.token_urlsafe(32)
        self.client = None
        self.last_seen = 0.
        self.width, self.height = 1280, 800
        self.frame = None
        self.frame_id = 0
        self.clipboard = ''
        self.pending = 0
        self.active_controls = False
        self.generation = 0

    def expired(self):
        limit = CONTROL_TIMEOUT if self.active_controls else IDLE_TIMEOUT
        return self.clock() - self.last_seen > limit

    def _drop(self):
        # Called with lock held. Reset is delivered on Qt's thread before
        # subsequent input from a new generation.
        self.client = None
        self.pending = 0
        self.active_controls = False
        self.generation += 1
        self.reset(self.generation)
        self.lock.notify_all()

    def acquire(self):
        with self.lock:
            if self.client and self.expired():
                self._drop()
            if self.client:
                return None
            self.client = secrets.token_urlsafe(24)
            self.frame = None
            self.last_seen = self.clock()
            self.generation += 1
            return dict(client=self.client, width=self.width, height=self.height)

    def valid(self, client):
        with self.lock:
            if self.client and self.expired():
                self._drop()
            return bool(client and self.client and hmac.compare_digest(client, self.client))

    def ping(self, client):
        with self.lock:
            if not self.valid(client):
                return False
            self.last_seen = self.clock()
            return True

    def close(self, client):
        with self.lock:
            if self.valid(client):
                self._drop()

    def enqueue(self, client, events):
        with self.lock:
            if not self.valid(client):
                return 403
            if self.pending + len(events) > 96:
                self._drop()
                return 429
            self.pending += len(events)
            self.deliver(self.generation, events)
            return 200

    def consume(self, generation, count):
        with self.lock:
            if self.client is None or generation != self.generation or self.expired():
                if self.client and self.expired():
                    self._drop()
                return False
            self.pending = max(0, self.pending - count)
            return True

    def snapshot(self, client, after):
        with self.lock:
            self.lock.wait_for(lambda: (self.frame is not None and self.frame_id > after) or self.client != client, timeout=.85)
            if not self.valid(client):
                return 403, None
            if self.frame is None or self.frame_id <= after:
                return 204, None
            return 200, (self.frame, self.frame_id, self.width, self.height)

    def publish(self, image, width, height):
        with self.lock:
            if image != self.frame:
                self.frame, self.width, self.height = image, width, height
                self.frame_id += 1
                self.lock.notify_all()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, session):
        self.session = session
        super().__init__(('127.0.0.1', port), Handler)
        self.authority = '127.0.0.1:' + str(self.server_port)
        self.origin = 'http://' + self.authority
        self.start_nonce = secrets.token_urlsafe(32)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(4)
        return sock, addr


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, body=b'', mime='application/json', headers=None):
        self.send_response(code)
        for k, v in {
            'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY', 'Cross-Origin-Resource-Policy': 'same-origin',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
            **(headers or {})
        }.items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (ConnectionError, TimeoutError):
                pass

    def json(self, status, obj):
        self.reply(status, json.dumps(obj).encode())

    def trusted(self, api=False):
        if self.headers.get('Host') != self.server.authority:
            return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            return False
        if api:
            supplied = self.headers.get('X-Areion-Token', '')
            return (self.headers.get('Sec-Fetch-Site') not in ('cross-site', 'same-site')
                    and supplied.isascii() and hmac.compare_digest(supplied, self.server.session.token))
        return True

    def do_GET(self):
        url = urlsplit(self.path)
        if not self.trusted():
            return self.reply(403)
        if url.path in ASSETS:
            filename, mime = ASSETS[url.path]
            return self.reply(200, (STATIC / filename).read_bytes(), mime)
        if url.path == '/start':
            nonce = self.server.start_nonce
            html = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
                    'content="width=device-width,initial-scale=1"><title>Areion Flight Console</title>'
                    '<style>body{background:#101923;color:#e8f1f8;font:17px system-ui;'
                    'max-width:32rem;margin:16vh auto;padding:2rem}button{border:0;border-radius:.6rem;'
                    'padding:.8rem 1.2rem;background:#79dfd4;font:inherit;color:#101923}</style>'
                    '<main><h1>Areion Flight Console</h1><p>Open the console running on this computer.</p>'
                    '<form action="/start" method="post"><input type="hidden" name="nonce" value="'
                    + nonce + '"><button>Open full console</button></form></main></html>')
            return self.reply(200, html.encode(), 'text/html; charset=utf-8')
        if not self.trusted(True):
            return self.reply(403)
        client = self.headers.get('X-Areion-Client', '')
        session = self.server.session
        if not client.isascii() or not session.valid(client):
            return self.reply(403)
        if url.path == '/api/clipboard':
            return self.json(200, {'text': session.clipboard})
        if url.path == '/api/frame':
            try:
                after = int(parse_qs(url.query).get('after', ['-1'])[0])
            except ValueError:
                return self.reply(400)
            status, result = session.snapshot(client, after)
            if result is None:
                return self.reply(status)
            image, seq, w, h = result
            return self.reply(200, image, 'image/jpeg', {'X-Frame-Id': str(seq),
                               'X-Frame-Width': str(w), 'X-Frame-Height': str(h)})
        self.reply(404)

    def do_POST(self):
        if not self.trusted():
            return self.reply(403)
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if not 0 <= length <= MAX_REQUEST:
                return self.reply(413)
            raw = self.rfile.read(length)
        except (ValueError, TimeoutError):
            return self.reply(400)
        if self.path == '/start':
            # Cross-site embeds and scripted submissions cannot open a new
            # controlling session. The local launcher also provides a private URL.
            nonce = parse_qs(raw.decode('ascii', errors='ignore')).get('nonce', [''])[0]
            if (self.headers.get('Origin') != self.server.origin or
                self.headers.get('Sec-Fetch-Site') != 'same-origin' or
                self.headers.get('Sec-Fetch-Mode') != 'navigate' or
                self.headers.get('Sec-Fetch-User') != '?1' or
                not nonce.isascii() or not hmac.compare_digest(nonce, self.server.start_nonce)):
                return self.reply(403)
            return self.reply(303, headers={'Location': '/#' + self.server.session.token})
        if not self.trusted(True):
            return self.reply(403)
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                return self.reply(400)
        except (UnicodeError, ValueError, RecursionError):
            return self.reply(400)
        session = self.server.session
        if self.path == '/api/session':
            details = session.acquire()
            return self.json(200, details) if details else self.reply(409)
        client = self.headers.get('X-Areion-Client', '')
        if not client.isascii() or not session.valid(client):
            return self.reply(403)
        if self.path == '/api/ping':
            return self.reply(204 if session.ping(client) else 403)
        if self.path == '/api/close':
            session.close(client)
            return self.reply(204)
        if self.path == '/api/events':
            events = body.get('events')
            if not isinstance(events, list) or not 1 <= len(events) <= 48 or not all(isinstance(e, dict) for e in events):
                return self.reply(400)
            return self.reply(session.enqueue(client, events))
        self.reply(404)
