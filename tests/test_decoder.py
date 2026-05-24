import base64
import zlib

import pytest

from poe2_mcp.pob.decoder import decode_build_code

SAMPLE_XML = "<PathOfBuilding><Build level='90' className='Monk'/></PathOfBuilding>"


def _urlsafe(raw: bytes) -> str:
    return base64.b64encode(raw).decode().replace("+", "-").replace("/", "_").rstrip("=")


def test_decode_raw_deflate_roundtrip():
    # PoB's actual format: raw DEFLATE (no zlib header), URL-safe base64.
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(SAMPLE_XML.encode()) + co.flush()
    code = _urlsafe(raw)
    assert decode_build_code(code) == SAMPLE_XML


def test_decode_zlib_wrapped_fallback():
    # Fallback path: standard zlib-wrapped stream.
    code = _urlsafe(zlib.compress(SAMPLE_XML.encode()))
    assert decode_build_code(code) == SAMPLE_XML


def test_decode_tolerates_whitespace_and_missing_padding():
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(SAMPLE_XML.encode()) + co.flush()
    code = "  " + _urlsafe(raw) + "\n"  # leading/trailing whitespace, no '=' padding
    assert decode_build_code(code) == SAMPLE_XML


def test_decode_garbage_raises():
    with pytest.raises(Exception):
        decode_build_code("not-a-valid-pob-code!!!")
