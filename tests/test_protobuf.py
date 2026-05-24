import struct

from poe2_mcp.community import protobuf as pb


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def tag(field: int, wt: int) -> bytes:
    return _varint(field << 3 | wt)


def test_read_varint_field():
    buf = tag(1, pb.WIRETYPE_VARINT) + _varint(300)
    assert pb.read_fields(buf) == [(1, pb.WIRETYPE_VARINT, 300)]


def test_read_length_delimited_text():
    payload = b"drubringer"
    buf = tag(2, pb.WIRETYPE_LEN) + _varint(len(payload)) + payload
    fields = pb.read_fields(buf)
    assert fields == [(2, pb.WIRETYPE_LEN, payload)]
    assert pb.as_text(fields[0][2]) == "drubringer"


def test_nested_message_roundtrip():
    inner = tag(1, pb.WIRETYPE_LEN) + _varint(3) + b"abc"
    outer = tag(5, pb.WIRETYPE_LEN) + _varint(len(inner)) + inner
    [(f, wt, v)] = pb.read_fields(outer)
    assert (f, wt) == (5, pb.WIRETYPE_LEN)
    assert pb.read_fields(v) == [(1, pb.WIRETYPE_LEN, b"abc")]


def test_fixed64_double():
    buf = tag(1, pb.WIRETYPE_I64) + struct.pack("<d", 29624.0)
    [(f, wt, v)] = pb.read_fields(buf)
    assert wt == pb.WIRETYPE_I64
    assert pb.as_double(v) == 29624.0


def test_scalar_dispatch():
    assert pb.scalar((1, pb.WIRETYPE_VARINT, 7)) == 7
    assert pb.scalar((1, pb.WIRETYPE_LEN, b"hi")) == "hi"
    assert pb.scalar((1, pb.WIRETYPE_I32, struct.pack("<f", 1.5))) == 1.5


def test_as_text_non_utf8_returns_none():
    assert pb.as_text(b"\xff\xfe") is None
