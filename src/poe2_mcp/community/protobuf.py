"""
Minimal protobuf wire-format reader (no .proto schema needed).

poe.ninja serves its PoE2 build search and dictionary endpoints as
length-delimited protobuf with string interning. We don't have the schema, but
the wire format is self-describing enough to walk generically: every field
carries a number and a wire type. This module decodes a message into a flat list
of (field_number, wire_type, value) tuples; nested messages are returned as raw
bytes for the caller to decode again.

Reference: https://protobuf.dev/programming-guides/encoding/
"""

from __future__ import annotations

import struct

WIRETYPE_VARINT = 0
WIRETYPE_I64 = 1
WIRETYPE_LEN = 2
WIRETYPE_SGROUP = 3  # legacy start-group
WIRETYPE_EGROUP = 4  # legacy end-group
WIRETYPE_I32 = 5

Field = tuple[int, int, "int | bytes"]


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        try:
            b = buf[i]
        except IndexError:
            raise ValueError(f"truncated protobuf message: varint runs past byte {len(buf)}") from None
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def read_fields(buf: bytes) -> list[Field]:
    """
    Decode one protobuf message into a list of (field_number, wire_type, value).

    value is an int for varint, or raw bytes for length-delimited / fixed-width
    fields (fixed widths are returned as bytes so the caller can interpret them
    as float/double/int as appropriate). Repeated fields appear as repeated tuples.
    """
    out: list[Field] = []
    i = 0
    n = len(buf)
    while i < n:
        tag, i = _read_varint(buf, i)
        field = tag >> 3
        wt = tag & 0x07
        if wt == WIRETYPE_VARINT:
            val, i = _read_varint(buf, i)
            out.append((field, wt, val))
        elif wt == WIRETYPE_LEN:
            ln, i = _read_varint(buf, i)
            out.append((field, wt, buf[i:i + ln]))
            i += ln
        elif wt == WIRETYPE_I64:
            out.append((field, wt, buf[i:i + 8]))
            i += 8
        elif wt == WIRETYPE_I32:
            out.append((field, wt, buf[i:i + 4]))
            i += 4
        elif wt == WIRETYPE_SGROUP:
            # Legacy group: skip its contents (we never need group-encoded fields).
            i = _skip_group(buf, i)
        elif wt == WIRETYPE_EGROUP:
            break
        else:
            raise ValueError(f"unsupported protobuf wire type {wt} at byte {i}")
    return out


def _skip_group(buf: bytes, i: int) -> int:
    """Skip from just after a start-group tag to past its matching end-group."""
    depth = 1
    n = len(buf)
    while i < n and depth > 0:
        tag, i = _read_varint(buf, i)
        wt = tag & 0x07
        if wt == WIRETYPE_VARINT:
            _, i = _read_varint(buf, i)
        elif wt == WIRETYPE_LEN:
            ln, i = _read_varint(buf, i)
            i += ln
        elif wt == WIRETYPE_I64:
            i += 8
        elif wt == WIRETYPE_I32:
            i += 4
        elif wt == WIRETYPE_SGROUP:
            depth += 1
        elif wt == WIRETYPE_EGROUP:
            depth -= 1
        else:
            break
    return i


def as_text(b: bytes) -> str | None:
    """Decode bytes as UTF-8 text, or None if not valid UTF-8."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None


def as_double(b: bytes) -> float:
    return struct.unpack("<d", b)[0]


def as_float(b: bytes) -> float:
    return struct.unpack("<f", b)[0]


def scalar(field: Field) -> int | float | str | None:
    """Best-effort interpret a field's value as a scalar (text / number)."""
    _, wt, v = field
    if wt == WIRETYPE_LEN:
        return as_text(v)
    if wt == WIRETYPE_VARINT:
        return v
    if wt == WIRETYPE_I64:
        return as_double(v)
    if wt == WIRETYPE_I32:
        return as_float(v)
    return None
