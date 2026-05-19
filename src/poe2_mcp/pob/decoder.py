import base64
import zlib
import re
import httpx


def decode_build_code(code_or_url: str) -> str:
    """
    Accept a raw PoB export code or a pobb.in URL and return the build XML.
    """
    code_or_url = code_or_url.strip()

    if _looks_like_url(code_or_url):
        code = _fetch_from_pobb_in(code_or_url)
    else:
        code = code_or_url

    return _decode_pob_code(code)


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _fetch_from_pobb_in(url: str) -> str:
    """
    Fetch the raw PoB export code from a pobb.in share link.

    pobb.in share links are of the form https://pobb.in/<id>.
    The raw export code is available at https://pobb.in/<id>/raw.
    """
    # Normalise: strip trailing slashes, strip /raw if already present
    url = url.rstrip("/")
    if url.endswith("/raw"):
        raw_url = url
    else:
        raw_url = url + "/raw"

    response = httpx.get(raw_url, follow_redirects=True, timeout=10)
    response.raise_for_status()
    return response.text.strip()


def _decode_pob_code(code: str) -> str:
    """
    Decode a PoB export code into XML.

    PoB encodes builds as: URL-safe base64( zlib-deflate( XML ) )
    The URL-safe substitution replaces + with - and / with _.
    PoB uses raw DEFLATE (no zlib header), so wbits=-15.
    """
    # Reverse URL-safe base64 substitutions and add padding
    standard_b64 = code.replace("-", "+").replace("_", "/")
    # base64 strings must be a multiple of 4 characters
    padding = (4 - len(standard_b64) % 4) % 4
    standard_b64 += "=" * padding

    compressed = base64.b64decode(standard_b64)

    # Try raw deflate first (what PoB actually uses), then zlib-wrapped as fallback
    try:
        xml_bytes = zlib.decompress(compressed, wbits=-15)
    except zlib.error:
        xml_bytes = zlib.decompress(compressed)

    return xml_bytes.decode("utf-8")
