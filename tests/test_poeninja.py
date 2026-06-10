import json
from pathlib import Path

import pytest

from poe2_mcp.community import poeninja

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(path: str, params=None) -> dict:
    if "build-index-state" in path:
        return json.loads((FIXTURES / "poeninja_build_index_state.json").read_text())
    if "index-state" in path:
        return json.loads((FIXTURES / "poeninja_index_state.json").read_text())
    if "/profile/characters/" in path:
        return json.loads((FIXTURES / "poeninja_profile_characters.json").read_text())
    if "/character" in path:
        return json.loads((FIXTURES / "poeninja_character.json").read_text())
    raise AssertionError(f"unexpected json path {path}")


def _fixture_bytes(path: str, params=None) -> bytes:
    if "/dictionary/" in path:
        return (FIXTURES / "poeninja_dictionary.pb").read_bytes()
    if "/search" in path:
        return (FIXTURES / "poeninja_search.pb").read_bytes()
    raise AssertionError(f"unexpected bytes path {path}")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Serve every poe.ninja request from saved fixtures; never hit the network."""
    poeninja._cache.clear()
    monkeypatch.setattr(poeninja, "_get_json", _fixture_json)
    monkeypatch.setattr(poeninja, "_get_bytes", _fixture_bytes)
    yield
    poeninja._cache.clear()


def test_meta_overview():
    meta = poeninja.get_meta_overview()
    assert meta["league"] == "Fate of the Vaal"
    assert meta["total_characters"] == 124085
    top = meta["ascendancies"][0]
    assert top["class"] == "Blood Mage"
    assert top["percentage"] == 17.0
    assert top["trend"] in (-1, 0, 1)


def test_resolve_snapshot_defaults_to_indexed_league():
    sv = poeninja._resolve_snapshot(None)
    assert sv["url"] == "vaal"
    assert sv["snapshotName"] == "fate-of-the-vaal"
    assert sv["version"] == "1941-20260524-52647"


def test_list_top_builds_decodes_columns():
    builds = poeninja.list_top_builds(limit=5)
    assert len(builds) == 5
    first = builds[0]
    assert first["rank"] == 1
    assert first["character"] == "drubringer"
    assert first["account"] == "methanman-2640"
    assert first["class"] == "Titan"        # resolved via the dictionary fixture
    assert first["level"] == 100
    # display-formatted headline stats survive decoding
    assert isinstance(first["ehp"], str) and first["ehp"]
    assert isinstance(first["dps"], str) and first["dps"]


def test_list_top_builds_respects_limit():
    assert len(poeninja.list_top_builds(limit=3)) == 3


def test_fetch_pob_export_returns_decodable_code():
    code = poeninja.fetch_pob_export("methanman-2640", "drubringer")
    assert len(code) > 1000
    # round-trips through the existing decode/parse pipeline
    from poe2_mcp.pob import decode_build_code, parse_build_xml
    build = parse_build_xml(decode_build_code(code))
    assert build.class_name == "Warrior"
    assert build.ascendancy == "Titan"
    assert build.level == 100


def test_account_slug():
    assert poeninja._account_slug("Methanman#2640") == "methanman-2640"
    assert poeninja._account_slug("  methanman-2640 ") == "methanman-2640"


def test_list_characters():
    chars = poeninja.list_characters("methanman#2640")
    assert len(chars) == 3
    first = chars[0]
    assert first["name"] == "drubringer"
    assert first["class"] == "Titan"
    assert first["league"] == "Fate of the Vaal"
    assert first["current"] is True
    assert "Furious Slam" in first["skills"]
    # a non-current character is also listed
    assert any(c["league"] == "Standard" and not c["current"] for c in chars)


def test_fetch_character_export_indexed():
    code = poeninja.fetch_character_export("methanman#2640", "drubringer")
    assert len(code) > 1000


def test_fetch_character_export_unknown_name():
    with pytest.raises(ValueError, match="no character named"):
        poeninja.fetch_character_export("methanman#2640", "ghost")


def test_fetch_character_export_not_indexed(monkeypatch):
    # A character on the profile that poe.ninja has no build snapshot for -> friendly error.
    import httpx

    def _raise_404(account, name, league=None):
        req = httpx.Request("GET", "https://poe.ninja/x")
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("not found", request=req, response=resp)

    monkeypatch.setattr(poeninja, "fetch_pob_export", _raise_404)
    with pytest.raises(ValueError, match="passes a level threshold"):
        poeninja.fetch_character_export("methanman#2640", "pingkong")


def test_ttl_cache_sweeps_expired_on_set(monkeypatch):
    from poe2_mcp.community.cache import TTLCache
    import time as _time

    now = [1000.0]
    monkeypatch.setattr(_time, "monotonic", lambda: now[0])
    cache = TTLCache(ttl=10.0)
    cache.set("a", "old")
    now[0] += 11  # "a" expires
    cache.set("b", "new")  # write sweeps the dead entry
    assert "a" not in cache._store and cache.get("b") == "new"
