"""One logical controller, identical frames on every attached transport."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import secrets
import threading
import time

from .protocol import Decoder, Message, ProtocolError, decode_frame, encode_frame, newer
from .registry import Field, SchemaRegistry
from .transports import Transport, TransientTransportError


class LinkError(RuntimeError):
    pass


class _TransientSend(LinkError):
    """No packet sent on this attempt; keep bounded RPC retries possible."""


class RemoteError(LinkError):
    def __init__(self, message: Message) -> None:
        self.message = message
        self.code = str(message.data[0]) if message.data else "UNKNOWN_ERROR"
        super().__init__(self.code)


@dataclass
class _Path:
    transport: Transport
    decoder: Decoder = field(default_factory=Decoder)
    active: bool = True
    confirmed: bool = False
    error: str | None = None
    frames: int = 0
    sent_frames: int = 0
    rejected: int = 0
    transient_errors: int = 0
    fc_session: int | None = None
    last_received: float | None = None


class Link:
    """Thread-safe SDK. One serialized command RPC; control has its own sequence.

    No automatic reconnect, automatic control replay, or automatic arming.
    All attached transports must terminate at the SAME flight controller.
    A timeout means an operation's outcome is unknown: read back before making
    a new mutation request. SAVE is a separate explicit call from SET.
    """

    def __init__(self, *transports: Transport, request_timeout: float = 0.5,
                 retries: int = 3, event_capacity: int = 128,
                 session: int | None = None, heartbeat_interval: float = 1.0,
                 busy_wait: float = 6.0, health_timeout: float = 5.0) -> None:
        if not transports:
            raise ValueError("attach at least one transport")
        if request_timeout <= 0 or retries < 1 or event_capacity < 1:
            raise ValueError("timeouts, retries, and capacity must be positive")
        if not 0 < heartbeat_interval < health_timeout or busy_wait < 0:
            raise ValueError("heartbeat must be positive and below health timeout; busy_wait nonnegative")
        self.heartbeat_interval = heartbeat_interval
        self.busy_wait = busy_wait
        self.health_timeout = health_timeout
        self.release_confirmed = False
        self.release_error: str | None = None
        self._last_owner_response = 0.0
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._closing = False
        self.session = session if session is not None else secrets.randbelow(0xFFFFFFFF) + 1
        Message("HELLO", session=self.session)  # validate injected test/session value
        self.fc_session: int | None = None
        self.request_timeout = request_timeout
        self.retries = retries
        self.registry = SchemaRegistry()
        self._paths = [_Path(t) for t in transports]
        self._events: deque[tuple[Message, float]] = deque(maxlen=event_capacity)
        self.event_drops = 0
        self._condition = threading.Condition(threading.RLock())
        self._rpc_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._pending: Message | None = None
        self._response: Message | None = None
        self._sequence = 0
        self._control_sequence = 0
        # FC event IDs are global, but ordering is per group: delayed STATUS
        # must not be discarded merely because a newer IMU arrived first.
        self._event_sequences: dict[tuple[int, int], int] = {}
        self._connected = False
        self._closed = False
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        with self._condition:
            return (self._connected and not self._closed
                    and time.monotonic() - self._last_owner_response < self.health_timeout
                    and any(p.active and p.confirmed for p in self._paths))

    @property
    def transport_status(self) -> list[dict]:
        with self._condition:
            now = time.monotonic()
            return [{"name": p.transport.name, "datagram": p.transport.datagram, "active": p.active,
                     "confirmed": p.confirmed, "error": p.error,
                     "healthy": bool(p.active and p.confirmed and p.last_received is not None
                                     and now - p.last_received < self.health_timeout),
                     "last_received_age": None if p.last_received is None else now - p.last_received,
                     "received_frames": p.frames, "sent_frames": p.sent_frames,
                     "rejected_frames": p.rejected, "transient_errors": p.transient_errors}
                    for p in self._paths]

    def register_group(self, group: int, schema: int, fields: list[Field]) -> None:
        with self._condition:
            self.registry.register(group, schema, fields)

    def _next(self, control: bool = False) -> int:
        with self._condition:
            attr = "_control_sequence" if control else "_sequence"
            seq = (getattr(self, attr) + 1) & 0xFFFFFFFF
            seq = seq or 1
            setattr(self, attr, seq)
            return seq

    def _fail_path(self, path: _Path, error: Exception) -> None:
        with self._condition:
            path.active = False
            path.error = str(error)
            self._condition.notify_all()

    def _transient_path(self, path: _Path, error: Exception) -> None:
        with self._condition:
            path.transient_errors += 1
            path.error = str(error)
            # Do not refresh last_received or the owner lease. Silence still
            # fails health checks, and a CONTROL error stops its sender.

    @staticmethod
    def _received(path: _Path) -> None:
        path.last_received = time.monotonic()
        path.error = None

    @staticmethod
    def _route_options(datagram_only: bool, serial_only: bool) -> None:
        if type(datagram_only) is not bool or type(serial_only) is not bool:
            raise ValueError("route filters must be boolean")
        if datagram_only and serial_only:
            raise ValueError("choose either datagram_only or serial_only")

    @staticmethod
    def _check_cancel(cancel) -> None:
        if cancel is not None:
            stopped = cancel() if callable(cancel) else cancel.is_set()
            if stopped:
                raise LinkError("ACTION cancelled; an already sent action may have applied. Verify FC status")

    def _broadcast(self, frame: bytes, handshake: bool = False,
                   datagram_only: bool = False, serial_only: bool = False,
                   cancel=None, control_deadline: float | None = None) -> None:
        self._route_options(datagram_only, serial_only)
        sent = 0
        temporary = False
        with self._send_lock:
            for path in self._paths:
                self._check_cancel(cancel)
                if control_deadline is not None and time.monotonic() >= control_deadline:
                    raise LinkError("CONTROL send delayed over150ms; stale values were not replayed")
                if not path.active or (not handshake and not path.confirmed):
                    continue
                if datagram_only and not path.transport.datagram:
                    continue
                if serial_only and path.transport.datagram:
                    continue
                if (datagram_only or serial_only) and (path.last_received is None
                        or time.monotonic() - path.last_received >= 0.5):
                    continue
                try:
                    path.transport.send(frame)
                    with self._condition:
                        path.sent_frames += 1
                    sent += 1
                except TransientTransportError as error:
                    self._transient_path(path, error)
                    temporary = True
                except Exception as error:
                    self._fail_path(path, error)
        if not sent:
            if temporary:
                raise _TransientSend("UDP temporarily unavailable; no packet sent on this attempt")
            raise LinkError("no usable transport; inspect transport_status")

    def connect(self) -> "Link":
        with self._condition:
            if self._closed:
                raise LinkError("Link is closed; create a new instance to reconnect")
            if self._connected:
                if self.connected:
                    return self
                raise LinkError("session is stale; close and create a new Link to reconnect")
            if self._thread is None:
                self._thread = threading.Thread(target=self._reader, daemon=True,
                                                name="areion-link-reader")
                self._thread.start()
        deadline = time.monotonic() + self.busy_wait
        while True:
            try:
                response = self._rpc("HELLO", 0, (), 1, handshake=True)
                break
            except RemoteError as error:
                if error.code != "BUSY" or time.monotonic() >= deadline:
                    raise
                # Only HELLO retries while an abandoned disarmed-owner lease
                # runs out. A live controller's heartbeat keeps BUSY in force.
                if self._stop.wait(min(0.25, max(0.0, deadline - time.monotonic()))):
                    raise LinkError("closed during connection")
        if (response.type != "ACK" or len(response.data) != 2
                or response.data[0] != "HELLO" or type(response.data[1]) is not int
                or not 1 <= response.data[1] <= 0xFFFFFFFF
                or response.data[1] == self.session):
            raise LinkError("invalid HELLO reply or session collision")
        with self._condition:
            self.fc_session = response.data[1]
            # Allow other path ACKs to arrive so each destination is identified
            # before mutations can use it. Unconfirmed paths remain read-only.
            deadline = time.monotonic() + min(self.request_timeout, 0.15)
            while any(p.active and not p.confirmed for p in self._paths):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            for path in self._paths:
                if path.fc_session is not None and path.fc_session != self.fc_session:
                    path.active = False
                    path.error = "HELLO identifies a different FC; route disabled"
            self._connected = True
            self._last_owner_response = time.monotonic()
            self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True,
                                                       name="areion-link-heartbeat")
            self._heartbeat_thread.start()
        return self

    def _require_connected(self) -> None:
        if not self.connected:
            raise LinkError("call connect() first; no confirmed active path")

    def _rpc(self, kind: str, group: int, values: tuple | list, schema: int,
             handshake: bool = False, *, datagram_only: bool = False,
             serial_only: bool = False, cancel=None, timeout: float | None = None) -> Message:
        self._route_options(datagram_only, serial_only)
        with self._rpc_lock:
            self._check_cancel(cancel)  # A queued ARM cannot outlive a local Stop.
            if self._closing:
                raise LinkError("Link is closing")
            return self._rpc_locked(kind, group, values, schema, handshake,
                                    datagram_only=datagram_only,
                                    serial_only=serial_only, cancel=cancel, timeout=timeout)

    def _rpc_locked(self, kind: str, group: int, values: tuple | list, schema: int,
                    handshake: bool = False, timeout: float | None = None,
                    retries: int | None = None, *, datagram_only: bool = False,
                    serial_only: bool = False, cancel=None) -> Message:
        # Caller holds _rpc_lock. Background heartbeats cannot overtake a SET
        # retry and invalidate the FC's single cached command reply.
        self._route_options(datagram_only, serial_only)
        self._check_cancel(cancel)
        if not handshake:
            self._require_connected()
        request = Message(kind, group, schema, self.session, self._next(), tuple(values))
        frame = encode_frame(request)
        with self._condition:
            self._pending = request
            self._response = None
        try:
            for _ in range(self.retries if retries is None else retries):
                self._check_cancel(cancel)
                try:
                    self._broadcast(frame, handshake=handshake, datagram_only=datagram_only,
                                    serial_only=serial_only, cancel=cancel)
                except _TransientSend:
                    # Keep the exact identity/frame and the existing retry
                    # budget. No new mutation or reconnect is introduced.
                    pass
                deadline = time.monotonic() + (self.request_timeout if timeout is None else timeout)
                with self._condition:
                    while self._response is None and not self._closed:
                        self._check_cancel(cancel)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not any(p.active for p in self._paths):
                            break
                        self._condition.wait(min(remaining, 0.05) if cancel is not None else remaining)
                    self._check_cancel(cancel)
                    if self._response is not None:
                        response = self._response
                        if response.type == "ERROR":
                            raise RemoteError(response)
                        return response
                    if self._closed:
                        raise LinkError("closed during request")
            raise TimeoutError(f"{kind} group {group} timed out; outcome may be unknown")
        finally:
            with self._condition:
                self._pending = None
                self._response = None

    def _heartbeat(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval):
            # Skip a busy foreground RPC: its replies refresh the same lease.
            if not self._rpc_lock.acquire(blocking=False):
                continue
            try:
                if not self._closing:
                    self._rpc_locked("PING", 0, [], 1, timeout=min(self.request_timeout, 0.4), retries=1)
            except (LinkError, TimeoutError):
                pass  # No automatic takeover, reconnect, or mutation replay.
            finally:
                self._rpc_lock.release()

    def read_group(self, group: int, schema: int = 1, saved: bool = False, *, cancel=None) -> list:
        """Read a group; optional cancellation releases an outstanding read for Stop."""
        response = self._rpc("READ", group, ["saved"] if saved else [], schema, cancel=cancel)
        if response.type != "DATA":
            raise LinkError("READ expected DATA response")
        with self._condition:
            self.registry.validate(group, schema, response.data)
        return list(response.data)

    def set_group(self, group: int, values: list | tuple, schema: int = 1) -> list:
        if not isinstance(values, (list, tuple)):
            raise ProtocolError("SET values must be a list or tuple")
        with self._condition:
            self.registry.validate(group, schema, values)
        response = self._rpc("SET", group, values, schema)
        if response.type != "ACK" or response.data != ("APPLIED_UNSAVED",):
            raise LinkError("unexpected SET reply")
        return list(response.data)

    def save_group(self, group: int, schema: int = 1) -> list:
        # Flash commit/readback can briefly delay an AP reply. This bounded
        # storage wait does not change telemetry/control freshness or ARM waits.
        response = self._rpc("SAVE", group, [], schema,
                             timeout=max(self.request_timeout, 1.25))
        if response.type != "ACK" or response.data != ("SAVED",):
            raise LinkError("unexpected SAVE reply")
        return list(response.data)

    def ping(self) -> None:
        response = self._rpc("PING", 0, [], 1)
        if response.type != "ACK" or response.data != ("PONG",):
            raise LinkError("unexpected PING reply")

    def action(self, group: int, values: list | tuple, schema: int = 1, *,
               datagram_only: bool = False, serial_only: bool = False,
               cancel=None) -> list:
        """Invoke a registered FC action, keeping identity, sequence and exact retry.

        cancel may be threading.Event or a no-argument callable returning true
        after Stop. Cancellation cannot undo a frame already sent; use DISARM
        and a fresh status read to confirm the resulting state.
        """
        if not isinstance(values, (list, tuple)):
            raise ProtocolError("ACTION values must be a list or tuple")
        response = self._rpc("ACTION", group, values, schema,
                             datagram_only=datagram_only,
                             serial_only=serial_only, cancel=cancel)
        if (response.type != "ACK" or len(response.data) != 1
                or type(response.data[0]) is not str or not response.data[0]):
            raise LinkError("unexpected ACTION reply")
        return list(response.data)

    def arm(self, *, datagram_only: bool = False, serial_only: bool = False,
            cancel=None) -> list:
        """Explicit guarded ARM. A successful ACK is historical; read status.

        Select the matching source and continuously send fresh neutral channels
        first. Use the route filter matching that selected flight input.
        """
        result = self.action(123, ["ARM"], datagram_only=datagram_only,
                             serial_only=serial_only, cancel=cancel)
        if result != ["ARMED"]:
            raise LinkError("unexpected ARM reply")
        return result

    def disarm(self) -> list:
        """Explicit DISARM on all confirmed paths, including a surviving backup."""
        result = self.action(123, ["DISARM"])
        if result != ["DISARMED"]:
            raise LinkError("unexpected DISARM reply")
        return result

    def send_control(self, values: list[int] | tuple[int, ...], *,
                     datagram_only: bool = False, serial_only: bool = False) -> None:
        """Send one fresh RC frame; caller must schedule current values explicitly.

        datagram_only=True restricts AP control to a confirmed UDP route with a
        packet received in the last 500 ms. serial_only=True likewise restricts
        USB control to fresh confirmed serial paths. They never fall back to
        another transport and cannot both be true. Waiting on a busy writer for
        150 ms rejects this frame rather than replaying captured stale values.
        """
        self._require_connected()
        if self._closing:
            raise LinkError("Link is closing")
        self._route_options(datagram_only, serial_only)
        if (not isinstance(values, (list, tuple)) or len(values) != 8
                or any(type(v) is not int or not 1000 <= v <= 2000 for v in values)):
            raise ProtocolError("CONTROL requires 8 integer channels in 1000..2000")
        request = Message("CONTROL", 9, 1, self.session, self._next(True), tuple(values))
        self._broadcast(encode_frame(request), datagram_only=datagram_only,
                        serial_only=serial_only, control_deadline=time.monotonic() + 0.15)

    def poll(self, timeout: float = 0.0) -> Message | None:
        event = self.poll_timed(timeout)
        return event[0] if event is not None else None

    def poll_timed(self, timeout: float = 0.0) -> tuple[Message, float] | None:
        """Take the next event and its host monotonic transport receipt time."""
        if timeout < 0:
            raise ValueError("timeout must be nonnegative")
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._events and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._events.popleft() if self._events else None

    def _handle(self, path: _Path, message: Message, received_at: float | None = None) -> None:
        if received_at is None:
            received_at = time.monotonic()
        with self._condition:
            path.frames += 1
            hello_ack = (message.type == "ACK" and message.session == self.session
                    and message.group == 0 and message.schema == 1
                    and len(message.data) == 2 and message.data[0] == "HELLO"
                    and type(message.data[1]) is int
                    and 1 <= message.data[1] <= 0xFFFFFFFF
                    and message.data[1] != self.session)
            if hello_ack:
                self._received(path)
                path.fc_session = message.data[1]
                path.confirmed = True
                if self.fc_session is not None and path.fc_session != self.fc_session:
                    path.active = False
                    path.error = "HELLO identifies a different FC; route disabled"
                    return
                self._condition.notify_all()
            pending = self._pending
            if (pending is not None and self._response is None
                    and message.session == pending.session and message.seq == pending.seq
                    and message.group == pending.group and message.schema == pending.schema):
                expected_ack = {"SET": ("APPLIED_UNSAVED",), "SAVE": ("SAVED",), "PING": ("PONG",), "RELEASE": ("RELEASED",)}
                valid = (message.type == "ERROR" and len(message.data) == 1
                         and type(message.data[0]) is str)
                valid = valid or (pending.type == "READ" and message.type == "DATA")
                valid = valid or (pending.type == "HELLO" and hello_ack)
                valid = valid or (pending.type == "ACTION" and message.type == "ACK"
                                  and len(message.data) == 1
                                  and type(message.data[0]) is str and bool(message.data[0]))
                valid = valid or (message.type == "ACK" and pending.type in expected_ack
                                  and message.data == expected_ack[pending.type])
                if valid and (pending.type == "HELLO" or path.confirmed):
                    self._received(path)
                    if message.type != "ERROR":
                        self._last_owner_response = path.last_received
                    elif message.data[0] in ("NOT_OWNER", "SESSION_EXPIRED", "SESSION_RETIRED"):
                        self._connected = False
                    self._response = message
                    self._condition.notify_all()
                else:
                    path.rejected += 1
                return
            # A second path may deliver the same current reply after the first
            # already completed the RPC. Count route health without reapplying it.
            if (path.confirmed and message.session == self.session and message.seq == self._sequence
                    and message.type == "ACK" and message.data in (("PONG",), ("RELEASED",),
                                                                  ("SAVED",), ("APPLIED_UNSAVED",),
                                                                  ("ARMED",), ("DISARMED",))):
                self._received(path)
            if message.type != "DATA" or message.session != self.fc_session or not path.confirmed:
                return
            self._received(path)
            key = message.group, message.schema
            previous = self._event_sequences.get(key)
            if previous is not None and not newer(message.seq, previous):
                return
            try:
                self.registry.validate(message.group, message.schema, message.data)
            except ProtocolError:
                path.rejected += 1
                return
            if key not in self._event_sequences and len(self._event_sequences) >= 64:
                # Engine supports24 groups;64 accommodates schema changes while
                # retaining bounded state even from an unregistered publisher.
                path.rejected += 1
                return
            self._event_sequences[key] = message.seq
            if len(self._events) == self._events.maxlen:
                self.event_drops += 1
            self._events.append((message, received_at))
            self._condition.notify_all()

    def _reader(self) -> None:
        while not self._stop.is_set():
            for path in self._paths:
                if not path.active:
                    continue
                try:
                    data = path.transport.receive()
                except TransientTransportError as error:
                    self._transient_path(path, error)
                    continue
                except Exception as error:
                    self._fail_path(path, error)
                    continue
                if not data:
                    continue
                received_at = time.monotonic()
                if path.transport.datagram:
                    try:
                        messages = [decode_frame(data)]
                    except ProtocolError:
                        path.rejected += 1
                        continue
                else:
                    before = path.decoder.rejected
                    messages = path.decoder.feed(data)
                    path.rejected += path.decoder.rejected - before
                for message in messages:
                    self._handle(path, message, received_at)
            self._stop.wait(0.002)

    def close(self) -> None:
        """Try guarded RELEASE, then always close local resources (no board reset).

        RELEASE is bounded to two 250ms waits. If another foreground operation
        is still running, do not interrupt/reorder it; let the FC lease recover
        once disarmed. Custom transport.send() must itself have bounded latency.
        """
        with self._condition:
            if self._closed or self._closing:
                return
            self._closing = True
        self._heartbeat_stop.set()
        acquired = self._rpc_lock.acquire(timeout=0.5)
        try:
            if acquired and self.connected:
                try:
                    response = self._rpc_locked("RELEASE", 0, [], 1, timeout=0.25, retries=2)
                    self.release_confirmed = response.data == ("RELEASED",)
                except (LinkError, TimeoutError) as error:
                    self.release_error = str(error)
            elif self._connected:
                self.release_error = "No fresh confirmed path or command still in progress; release unconfirmed"
        finally:
            if acquired:
                self._rpc_lock.release()
            with self._condition:
                self._closed = True
                self._connected = False
                self._condition.notify_all()
            self._stop.set()
            for thread in (self._heartbeat_thread, self._thread):
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=0.6)
            for path in self._paths:
                try:
                    path.transport.close()
                except Exception:
                    pass

    def __enter__(self) -> "Link":
        try:
            return self.connect()
        except Exception:
            self.close()
            raise

    def __exit__(self, *args: object) -> None:
        self.close()
