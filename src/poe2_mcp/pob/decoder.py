import base64
import binascii
import os
import zlib
from urllib.parse import urlparse

import httpx


def decode_build_code(code_or_url: str) -> str:
    """
    Accept a raw PoB export code, a pobb.in URL, or a local file path and return
    the build XML.

    A raw export code is a single long base64 token; passing one through a tool
    argument is error-prone (a single altered character corrupts the stream), so
    a local file path is accepted as a safer alternative.
    """
    code_or_url = code_or_url.strip()

    if _looks_like_url(code_or_url):
        code = _fetch_from_pobb_in(code_or_url)
    elif _looks_like_file(code_or_url):
        code = _read_from_file(code_or_url)
    else:
        code = code_or_url

    return _decode_pob_code(code)


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _looks_like_file(value: str) -> bool:
    """
    True if value is the path of an existing file.

    A real PoB code is one long base64 token far longer than any path, and
    os.path.isfile returns False (never raises) for over-long or invalid paths,
    so an actual build code can't be mistaken for a file.
    """
    if len(value) > 4096 or "\n" in value:
        return False
    return os.path.isfile(os.path.expanduser(value))


def _read_from_file(path: str) -> str:
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return fh.read().strip()


def _fetch_from_pobb_in(url: str) -> str:
    """
    Fetch the raw PoB export code from a pobb.in share link.

    pobb.in share links are of the form https://pobb.in/<id>.
    The raw export code is available at https://pobb.in/<id>/raw.
    """
    host = (urlparse(url).hostname or "").lower()
    if host != "pobb.in" and not host.endswith(".pobb.in"):
        raise ValueError(
            f"Only pobb.in share links are supported, got {host or url!r}. "
            "For other sites, copy the raw PoB export code and pass that instead."
        )
    # Normalise: strip trailing slashes, strip /raw if already present
    url = url.rstrip("/")
    if url.endswith("/raw"):
        raw_url = url
    else:
        raw_url = url + "/raw"

    response = httpx.get(raw_url, follow_redirects=True, timeout=10)
    response.raise_for_status()
    return response.text.strip()


def _is_zlib_wrapped(data: bytes) -> bool:
    """
    True if data begins with a zlib header (RFC 1950).

    A zlib stream starts with two bytes (CMF, FLG): the compression method
    (low nibble of CMF) must be 8 (DEFLATE), and CMF*256+FLG must be a multiple
    of 31. Raw DEFLATE (RFC 1951, what PoB usually emits) has no such header.
    """
    if len(data) < 2:
        return False
    cmf, flg = data[0], data[1]
    return (cmf & 0x0F) == 8 and ((cmf << 8) | flg) % 31 == 0


def _decode_pob_code(code: str) -> str:
    """
    Decode a PoB export code into XML.

    PoB encodes builds as base64( DEFLATE( XML ) ), URL-safe (+ -> -, / -> _).
    The DEFLATE stream may be raw (RFC 1951) or zlib-wrapped (RFC 1950); we
    detect which from the header rather than guessing.
    """
    # Reverse URL-safe base64 substitutions and drop any stray whitespace
    # (line-wrapped pastes), then pad to a multiple of 4 characters.
    standard_b64 = "".join(code.split()).replace("-", "+").replace("_", "/")
    padding = (4 - len(standard_b64) % 4) % 4
    standard_b64 += "=" * padding

    try:
        compressed = base64.b64decode(standard_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "This does not look like a Path of Building export code: the text is "
            "not valid base64. Re-copy the full code (File > Share > Copy code), "
            "or pass a pobb.in link or a local file path instead."
        ) from exc

    # Decode with the framing the header indicates, falling back to the other in
    # case the heuristic was wrong.
    primary = 15 if _is_zlib_wrapped(compressed) else -15
    alternate = -15 if primary == 15 else 15
    try:
        xml_bytes = zlib.decompress(compressed, wbits=primary)
    except zlib.error:
        try:
            xml_bytes = zlib.decompress(compressed, wbits=alternate)
        except zlib.error as exc:
            raise ValueError(
                f"Could not decompress the build code — it looks truncated or "
                f"corrupted ({exc}). This usually means the code was cut off or "
                f"altered in transit; re-copy the full code, or pass a pobb.in "
                f"link or a local file path."
            ) from exc

    try:
        return xml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "The decoded build data is not valid UTF-8 XML — the code appears "
            "to be corrupted."
        ) from exc
