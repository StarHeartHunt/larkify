"""The protobuf frame of the long connection, without a protobuf dependency.

```proto
message Header {
  required string key = 1;
  required string value = 2;
}

message Frame {
  required uint64 SeqID = 1;
  required uint64 LogID = 2;
  required int32 service = 3;
  required int32 method = 4;
  repeated Header headers = 5;
  optional string payload_encoding = 6;
  optional string payload_type = 7;
  optional bytes payload = 8;
  optional string LogIDNew = 9;
}
```
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_VARINT = 0
_FIXED64 = 1
_LENGTH_DELIMITED = 2
_FIXED32 = 5

METHOD_CONTROL = 0
METHOD_DATA = 1


def _encode_varint(value: int) -> bytes:
    if value < 0:
        # Negative int32 values are sign extended to ten bytes.
        value += 1 << 64
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError("malformed varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _as_uint64(value: Any) -> int:
    if not isinstance(value, int):
        raise TypeError("numeric field is not a varint")
    return value


def _as_int32(value: Any) -> int:
    value = _as_uint64(value)
    return value - (1 << 64) if value >= 1 << 63 else value


def _read_fields(data: bytes) -> Iterator[tuple[int, Any]]:
    pos = 0
    while pos < len(data):
        tag, pos = _decode_varint(data, pos)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == _VARINT:
            value, pos = _decode_varint(data, pos)
        elif wire_type == _LENGTH_DELIMITED:
            length, pos = _decode_varint(data, pos)
            if pos + length > len(data):
                raise ValueError("truncated field")
            value, pos = data[pos : pos + length], pos + length
        elif wire_type == _FIXED64:
            value, pos = data[pos : pos + 8], pos + 8
        elif wire_type == _FIXED32:
            value, pos = data[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        yield number, value


def _varint_field(number: int, value: int) -> bytes:
    return _encode_varint(number << 3 | _VARINT) + _encode_varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return (
        _encode_varint(number << 3 | _LENGTH_DELIMITED)
        + _encode_varint(len(value))
        + value
    )


@dataclass
class Frame:
    seq_id: int = 0
    log_id: int = 0
    service: int = 0
    method: int = METHOD_CONTROL
    headers: list[tuple[str, str]] = field(default_factory=list)
    payload_encoding: str | None = None
    payload_type: str | None = None
    payload: bytes | None = None
    log_id_new: str | None = None

    def header(self, key: str) -> str | None:
        for name, value in self.headers:
            if name == key:
                return value
        return None

    def encode(self) -> bytes:
        parts = [
            _varint_field(1, self.seq_id),
            _varint_field(2, self.log_id),
            _varint_field(3, self.service),
            _varint_field(4, self.method),
        ]
        for key, value in self.headers:
            header = _bytes_field(1, key.encode()) + _bytes_field(2, value.encode())
            parts.append(_bytes_field(5, header))
        if self.payload_encoding is not None:
            parts.append(_bytes_field(6, self.payload_encoding.encode()))
        if self.payload_type is not None:
            parts.append(_bytes_field(7, self.payload_type.encode()))
        if self.payload is not None:
            parts.append(_bytes_field(8, self.payload))
        if self.log_id_new is not None:
            parts.append(_bytes_field(9, self.log_id_new.encode()))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> "Frame":
        """Parse a frame, raising `ValueError` if it is malformed."""
        try:
            return cls._decode(data)
        except (TypeError, AttributeError) as e:
            # A field arrived with another wire type than its declared one.
            raise ValueError(f"malformed frame: {e}") from e

    @classmethod
    def _decode(cls, data: bytes) -> "Frame":
        frame = cls()
        for number, value in _read_fields(data):
            if number == 1:
                frame.seq_id = _as_uint64(value)
            elif number == 2:
                frame.log_id = _as_uint64(value)
            elif number == 3:
                frame.service = _as_int32(value)
            elif number == 4:
                frame.method = _as_int32(value)
            elif number == 5:
                entry = dict(_read_fields(value))
                frame.headers.append(
                    (entry.get(1, b"").decode(), entry.get(2, b"").decode())
                )
            elif number == 6:
                frame.payload_encoding = value.decode()
            elif number == 7:
                frame.payload_type = value.decode()
            elif number == 8:
                frame.payload = value
            elif number == 9:
                frame.log_id_new = value.decode()
        return frame
