"""Nonblocking readers and bounded writers for UDP, USB, and UART radios."""
from __future__ import annotations

import errno
import socket
from typing import Protocol
from .protocol import MAX_FRAME


class TransientTransportError(OSError):
    """A UDP packet could not be transferred; the socket may still recover.

    Callers must not replay control values. RPC callers may retry the exact
    same request within their existing deadline; receive freshness still expires.
    """


_UDP_TRANSIENT = frozenset(getattr(errno, name) for name in (
    'EAGAIN', 'EWOULDBLOCK', 'EINTR', 'ENOBUFS', 'ENETDOWN', 'ENETUNREACH',
    'EHOSTUNREACH', 'EHOSTDOWN', 'ENETRESET', 'ECONNREFUSED', 'ECONNRESET') if hasattr(errno, name))


def _udp_error(error):
    if error.errno in _UDP_TRANSIENT:
        raise TransientTransportError(error.errno, str(error)) from error
    raise error


class Transport(Protocol):
    name: str
    datagram: bool

    def send(self, frame: bytes) -> None: ...
    def receive(self) -> bytes: ...
    def close(self) -> None: ...


class UDP:
    """One remote FC address; use two instances for simultaneous AP and STA.

    A connected UDP socket filters replies to the selected IP/port. No packet
    is sent by the constructor. Link.connect() performs the HELLO handshake.
    """

    datagram = True

    def __init__(self, host: str, port: int = 8080) -> None:
        self.name = f"udp://{host}:{port}"
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.connect((host, port))
            self._socket.setblocking(False)
        except Exception:
            self._socket.close()
            raise

    def send(self, frame: bytes) -> None:
        try:
            written = self._socket.send(frame)
        except OSError as error:
            _udp_error(error)
        if written != len(frame):
            raise OSError("partial UDP datagram send")

    def receive(self) -> bytes:
        try:
            # Oversize datagrams become invalid whole frames, never prefixes.
            return self._socket.recv(MAX_FRAME + 1)
        except BlockingIOError:
            return b""
        except OSError as error:
            _udp_error(error)

    def close(self) -> None:
        self._socket.close()


class SerialTransport:
    """USB CDC / serial UART adapter (optional `pip install pyserial`).

    DTR/RTS are configured inactive before opening, avoiding an intentional
    reset pulse when reconnecting to a running calibration. Some OS/USB drivers
    may still pulse the lines during open; allow firmware startup before the
    handshake. This class never waits for incoming bytes indefinitely.
    """

    datagram = False

    def __init__(self, port: str, baudrate: int = 115200,
                 write_timeout: float = 0.2) -> None:
        if write_timeout <= 0:
            raise ValueError("write_timeout must be positive")
        try:
            import serial
        except ImportError as error:
            raise ImportError("SerialTransport requires: python -m pip install pyserial") from error
        self.name = f"serial://{port}@{baudrate}"
        self._serial = serial.Serial(port=None, baudrate=baudrate, timeout=0,
                                     write_timeout=write_timeout)
        try:
            self._serial.dtr=False
            self._serial.rts=False
            self._serial.port=port
            self._serial.open()
        except BaseException:
            self._serial.close()
            raise

    def send(self, frame: bytes) -> None:
        # Link serializes whole-frame writes across its RPC and control callers.
        written = self._serial.write(frame)
        if written != len(frame):
            raise OSError("partial serial write; reconnect explicitly before reuse")

    def receive(self) -> bytes:
        return self._serial.read(min(max(self._serial.in_waiting, 1), MAX_FRAME))

    def close(self) -> None:
        self._serial.close()
