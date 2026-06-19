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


def test_decode_from_file_path(tmp_path):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(SAMPLE_XML.encode()) + co.flush()
    f = tmp_path / "pob_code.txt"
    f.write_text(_urlsafe(raw) + "\n")
    assert decode_build_code(str(f)) == SAMPLE_XML


def test_decode_tolerates_internal_whitespace():
    # A line-wrapped paste: newlines in the middle of the base64 token.
    code = _urlsafe(zlib.compress(SAMPLE_XML.encode()))
    wrapped = "\n".join(code[i : i + 40] for i in range(0, len(code), 40))
    assert decode_build_code(wrapped) == SAMPLE_XML


def test_truncated_code_raises_clear_value_error():
    code = _urlsafe(zlib.compress(SAMPLE_XML.encode()))
    with pytest.raises(ValueError, match="truncated or corrupted"):
        decode_build_code(code[:-12])


def test_non_base64_raises_clear_value_error():
    with pytest.raises(ValueError, match="not valid base64"):
        decode_build_code("@@@ this is clearly not base64 @@@")
