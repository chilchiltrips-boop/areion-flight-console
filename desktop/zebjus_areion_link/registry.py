"""Optional local group schemas; the FC remains authoritative on writes."""
from __future__ import annotations

from dataclasses import dataclass
import math
from .protocol import ProtocolError, MAX_VALUES, MAX_STRING_BYTES, validate_values


@dataclass(frozen=True)
class Field:
    name: str
    kind: type
    minimum: int | float | None = None
    maximum: int | float | None = None
    max_bytes: int = MAX_STRING_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("field name must be a nonempty string")
        if self.kind not in (int, float, bool, str):
            raise ValueError("field kind must be int, float, bool, or str")
        if type(self.max_bytes) is not int or not 0 <= self.max_bytes <= MAX_STRING_BYTES:
            raise ValueError("max_bytes must be an integer in 0..128")
        for bound in (self.minimum, self.maximum):
            if bound is not None and (type(bound) not in (int, float) or not math.isfinite(bound)):
                raise ValueError("numeric bounds must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")

    def validate(self, value: object) -> None:
        kind = type(value)
        if self.kind is float:
            valid = kind in (float, int) and math.isfinite(value)
        else:
            valid = kind is self.kind
        if not valid:
            raise ProtocolError(f"{self.name}: expected {self.kind.__name__}")
        if self.kind in (int, float):
            if self.minimum is not None and value < self.minimum:
                raise ProtocolError(f"{self.name}: below minimum")
            if self.maximum is not None and value > self.maximum:
                raise ProtocolError(f"{self.name}: above maximum")
        elif self.kind is str and len(value.encode("utf-8")) > self.max_bytes:
            raise ProtocolError(f"{self.name}: string too long")


class SchemaRegistry:
    def __init__(self) -> None:
        self.groups: dict[tuple[int, int], tuple[Field, ...]] = {}

    def register(self, group: int, schema: int, fields: list[Field] | tuple[Field, ...]) -> None:
        if type(group) is not int or not 1 <= group <= 65535:
            raise ValueError("group must be 1..65535")
        if type(schema) is not int or not 1 <= schema <= 65535:
            raise ValueError("schema must be 1..65535")
        if not 1 <= len(fields) <= MAX_VALUES:
            raise ValueError("group must contain 1..32 fields")
        for field in fields:
            if not isinstance(field, Field) or field.kind not in (int, float, bool, str):
                raise ValueError("fields must describe int, float, bool, or str")
            if not 0 <= field.max_bytes <= MAX_STRING_BYTES:
                raise ValueError("max_bytes must be 0..128")
        key = group, schema
        if key in self.groups:
            raise ValueError("group/schema already registered; bump schema for changes")
        self.groups[key] = tuple(fields)

    def validate(self, group: int, schema: int, values: list | tuple) -> None:
        validate_values(values)
        fields = self.groups.get((group, schema))
        if fields is None:
            if any(g == group for g, _ in self.groups):
                raise ProtocolError("registered group schema mismatch")
            return
        if len(values) != len(fields):
            raise ProtocolError(f"group {group}: expected {len(fields)} values")
        for field, value in zip(fields, values):
            field.validate(value)
