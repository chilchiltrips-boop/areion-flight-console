"""Zebjus Areion Link v2 framing; no transport or third-party dependency."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import zlib

MAX_PAYLOAD = 1536
MAX_VALUES = 32
MAX_STRING_BYTES = 128
MAX_FRAME = 1 + 4 + 1 + MAX_PAYLOAD + 1 + 8 + 1
MIN_INTEGER = -(2**31)
MAX_INTEGER = 2**32 - 1
TYPES = frozenset(("HELLO", "READ", "DATA", "SET", "SAVE", "ACK", "ERROR", "CONTROL", "PING", "RELEASE", "ACTION"))
KEYS = frozenset(("v", "type", "group", "schema", "session", "seq", "data"))
Scalar = int | float | bool | str


class ProtocolError(ValueError):
    """Malformed, oversized, or unsupported wire message."""


@dataclass(frozen=True)
class Message:
    type: str
    group: int = 0
    schema: int = 1
    session: int = 1
    seq: int = 1
    data: tuple[Scalar, ...] = ()
    v: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.data, (tuple, list)):
            raise ProtocolError("data must be a flat array")
        object.__setattr__(self, "data", tuple(self.data))
        validate_message(self)


def _integer(value: object, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(f"{name} must be an integer in {low}..{high}")


def validate_values(values: tuple[Scalar, ...] | list[Scalar]) -> None:
    if len(values) > MAX_VALUES:
        raise ProtocolError(f"at most {MAX_VALUES} values per group")
    for value in values:
        kind = type(value)
        if kind is bool:
            continue
        if kind is int:
            _integer(value, MIN_INTEGER, MAX_INTEGER, "data integer")
        elif kind is float:
            if not math.isfinite(value):
                raise ProtocolError("non-finite float")
        elif kind is str:
            try:
                length = len(value.encode("utf-8", errors="strict"))
            except UnicodeError as error:
                raise ProtocolError("invalid Unicode string") from error
            if length > MAX_STRING_BYTES:
                raise ProtocolError(f"string exceeds {MAX_STRING_BYTES} UTF-8 bytes")
        else:
            raise ProtocolError("data supports only int, float, bool, and string")


def validate_message(message: Message) -> None:
    _integer(message.v, 2, 2, "v")
    if type(message.type) is not str or message.type not in TYPES:
        raise ProtocolError("unknown message type")
    _integer(message.group, 0, 65535, "group")
    _integer(message.schema, 1, 65535, "schema")
    _integer(message.session, 1, MAX_INTEGER, "session")
    _integer(message.seq, 1, MAX_INTEGER, "seq")
    validate_values(message.data)


def encode_frame(message: Message) -> bytes:
    validate_message(message)
    payload = json.dumps({"v": message.v, "type": message.type,
                          "group": message.group, "schema": message.schema,
                          "session": message.session, "seq": message.seq,
                          "data": message.data}, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload exceeds {MAX_PAYLOAD} bytes")
    return (b"$" + str(len(payload)).encode("ascii") + b":" + payload
            + b"*" + f"{zlib.crc32(payload):08X}".encode("ascii") + b"\n")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_float(value: str) -> float:
    number = float(value)
    mantissa = value.lower().split("e", 1)[0]
    if not math.isfinite(number) or (number == 0.0 and any(c in "123456789" for c in mantissa)):
        raise ProtocolError("float overflow or underflow")
    return number


def _bad_constant(value: str) -> None:
    raise ProtocolError(f"invalid JSON number: {value}")


def decode_frame(frame: bytes) -> Message:
    if not isinstance(frame, bytes):
        frame = bytes(frame)
    if len(frame) > MAX_FRAME or not frame.startswith(b"$"):
        raise ProtocolError("invalid frame boundary or length")
    colon = frame.find(b":", 1, 6)
    if colon < 2:
        raise ProtocolError("missing length header")
    digits = frame[1:colon]
    if not digits.isdigit() or digits.startswith(b"0"):
        raise ProtocolError("invalid decimal byte length")
    size = int(digits)
    if not 1 <= size <= MAX_PAYLOAD:
        raise ProtocolError("payload length out of range")
    end = colon + 1 + size
    if len(frame) != end + 10 or frame[end:end + 1] != b"*" or frame[-1:] != b"\n":
        raise ProtocolError("frame length/terminator mismatch")
    crc = frame[end + 1:end + 9]
    if re.fullmatch(b"[0-9A-F]{8}", crc) is None:
        raise ProtocolError("invalid CRC text")
    payload = frame[colon + 1:end]
    if int(crc, 16) != zlib.crc32(payload):
        raise ProtocolError("CRC mismatch")
    try:
        obj = json.loads(payload.decode("utf-8", errors="strict"),
                         object_pairs_hook=_pairs, parse_constant=_bad_constant, parse_float=_parse_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProtocolError(f"invalid JSON: {error}") from error
    if type(obj) is not dict or set(obj) != KEYS:
        raise ProtocolError("missing or unknown envelope key")
    if type(obj["data"]) is not list:
        raise ProtocolError("data must be an array")
    return Message(**obj)


class Decoder:
    """Incremental bounded decoder for byte streams, including noisy Serial logs.

    A '$' inside a valid payload is ordinary string content. A truncated frame
    cannot block a later valid frame: candidates are checked at each literal
    newline. Memory remains bounded by MAX_FRAME even with endless noise.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.rejected = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[Message]:
        messages: list[Message] = []
        for byte in data:
            if not self._buffer and byte != 36:
                continue
            self._buffer.append(byte)
            if len(self._buffer) > MAX_FRAME:
                del self._buffer[0]
                self.rejected += 1
            if byte != 10:
                continue
            # A complete frame ends in a literal LF. Inside JSON strings a LF
            # must be escaped, so trying '$' candidates does not split strings.
            start = self._buffer.find(b"$")
            while start >= 0:
                try:
                    message = decode_frame(bytes(self._buffer[start:]))
                except ProtocolError:
                    start = self._buffer.find(b"$", start + 1)
                else:
                    messages.append(message)
                    self._buffer.clear()
                    break
            else:
                self.rejected += 1
        return messages


def newer(sequence: int, previous: int) -> bool:
    """uint32 half-range ordering, valid across wrap; zero is never sent."""
    delta = (sequence - previous) & MAX_INTEGER
    return 0 < delta < 0x80000000
