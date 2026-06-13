"""Wiki client tests — the network call (_api) is stubbed, so these are hermetic."""

import httpx
import pytest

from poe2_mcp.wiki import client


@pytest.fixture(autouse=True)
def _clear_cache():
    client._cache.clear()
    yield
    client._cache.clear()


def _stub(monkeypatch, handler):
    """Replace the single network entry point with a params -> json handler."""
    monkeypatch.setattr(client, "_api", handler)


# -- text cleanup ------------------------------------------------------------

def test_clean_unescapes_strips_tags_and_resolves_wikilinks():
    raw = "&lt;span class=&quot;x&quot;&gt;+(40-60) to maximum [[Life]]&lt;br&gt;[[Strength|Str]] up&lt;/span&gt;"
    assert client._clean(raw) == "+(40-60) to maximum Life\nStr up"


def test_lines_splits_nonempty():
    assert client._lines("a&lt;br&gt;&lt;br&gt;b") == ["a", "b"]


def test_esc_doubles_single_quotes():
    assert client._esc("Kaom's Heart") == "Kaom''s Heart"


# -- cargo / search / extract wrappers ---------------------------------------

def test_cargo_query_underscores_keys(monkeypatch):
    _stub(monkeypatch, lambda p: {"cargoquery": [
        {"title": {"name": "Headhunter", "base item": "Heavy Belt"}}]})
    rows = client.cargo_query("items", "name,base_item", "x", 1)
    assert rows == [{"name": "Headhunter", "base_item": "Heavy Belt"}]


def test_search_reads_opensearch_shape(monkeypatch):
    _stub(monkeypatch, lambda p: ["hh", ["Headhunter", "Headhunter (old)"], [], []])
    assert client.search("hh") == ["Headhunter", "Headhunter (old)"]


def test_page_extract_truncates(monkeypatch):
    _stub(monkeypatch, lambda p: {"query": {"pages": {"1": {"extract": "x" * 50}}}})
    out = client.page_extract("Shock", max_chars=10)
    assert out.startswith("x" * 10) and out.endswith("[truncated]")


# -- high-level lookups ------------------------------------------------------

def test_lookup_item_shapes_result(monkeypatch):
    _stub(monkeypatch, lambda p: {"cargoquery": [{"title": {
        "name": "Headhunter", "rarity": "Unique", "class": "Belt",
        "base item": "Heavy Belt", "required level": "50",
        "implicit stat text": "(20-30)% increased [[Stun Threshold]]",
        "explicit stat text": "+(40-60) to maximum [[Life]]&lt;br&gt;+(20-40) to [[Strength]]",
        "flavour text": "The head is where the Man is.",
    }}]})
    r = client.lookup_item("Headhunter")
    assert r["rarity"] == "Unique" and r["base_item"] == "Heavy Belt"
    assert r["implicit"] == ["(20-30)% increased Stun Threshold"]
    assert r["explicit"] == ["+(40-60) to maximum Life", "+(20-40) to Strength"]
    assert r["source"] == "poe2wiki.net"


def test_lookup_item_not_found_offers_suggestions(monkeypatch):
    def handler(p):
        if p["action"] == "cargoquery":
            return {"cargoquery": []}
        return ["x", ["Headhunter"], [], []]   # opensearch fallback
    _stub(monkeypatch, handler)
    r = client.lookup_item("headhunt")
    assert "error" in r and r["did_you_mean"] == ["Headhunter"]


def test_lookup_mechanic_falls_back_to_search(monkeypatch):
    calls = {"n": 0}
    def handler(p):
        if p["action"] == "query":  # extracts
            calls["n"] += 1
            # first title has no page; the searched title does
            if p["titles"] == "shok":
                return {"query": {"pages": {"-1": {"missing": ""}}}}
            return {"query": {"pages": {"1": {"extract": "Shock increases damage taken."}}}}
        if p["action"] == "opensearch":
            return ["shok", ["Shock", "Shock Nova"], [], []]
        return {}
    _stub(monkeypatch, handler)
    r = client.lookup_mechanic("shok")
    assert r["title"] == "Shock"
    assert "increases damage taken" in r["text"]
    assert r["related"] == ["Shock Nova"]


def test_guard_returns_error_on_network_failure(monkeypatch):
    def boom(p):
        raise httpx.ConnectError("down")
    _stub(monkeypatch, boom)
    r = client.lookup_item("Headhunter")
    assert "error" in r and r["source"] == "poe2wiki.net"
