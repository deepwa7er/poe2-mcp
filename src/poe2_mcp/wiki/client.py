"""
poe2wiki.net provider — live, current-patch lookups the vendored data can't cover.

The offline data (tree / gems / affixes) and explain_mechanic are durable but
patch-stamped and bounded to what we vendored. This is the complement: a thin,
deterministic client over the community wiki's MediaWiki API, which exposes
structured Cargo tables (items, skills, mods, …) and clean page text as JSON — so
the server can answer "what does this unique do", "stats of this base", and "what
do the current patch notes say about Shock" without scraping HTML or guessing.

One network entry point (`_api`) keeps it cached and easy to stub in tests. All
text from the wiki arrives HTML-entity-encoded with `<br>` line breaks and
`[[wiki|links]]`; `_clean` normalises it to plain lines. Everything degrades
gracefully: a network/parse failure returns an `{"error": …}` dict, never raises.
"""

from __future__ import annotations

import html
import re

import httpx

from ..community.cache import TTLCache

_API = "https://www.poe2wiki.net/w/api.php"
_UA = "poe2-mcp build-analysis (https://github.com/deepwa7er/poe2-mcp)"
_SOURCE = "poe2wiki.net"
# Wiki content changes slowly (per patch), so cache for an hour — fast and polite.
_cache = TTLCache(ttl=3600.0)
_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": _UA}, timeout=20, follow_redirects=True)
    return _client


def _api(params: dict):
    """The single network call: GET api.php with format=json, cached by params.
    Returns the decoded JSON (dict or list). Tests stub this."""
    params = {**params, "format": "json"}
    key = tuple(sorted(params.items()))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    r = _http().get(_API, params=params)
    r.raise_for_status()
    data = r.json()
    _cache.set(key, data)
    return data


# ---------------------------------------------------------------------------
# Text cleanup: wiki markup -> plain lines.
# ---------------------------------------------------------------------------

_WIKILINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]")
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str | None) -> str:
    """Normalise wiki/Cargo text to plain lines: unescape entities, turn <br> into
    newlines, resolve [[Page|Label]] to its label, and strip remaining tags."""
    if not s:
        return ""
    s = html.unescape(s)                       # &lt;br&gt; -> <br>, &quot; -> "
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _WIKILINK.sub(r"\1", s)                # [[A|B]] -> B, [[A]] -> A
    s = _TAG.sub("", s)                        # drop any other span/em/big tags
    s = html.unescape(s)                       # a second pass for nested entities
    s = re.sub(r"[ \t]+", " ", s)
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def _lines(s: str | None) -> list[str]:
    """Cleaned text split into non-empty lines (for multi-line stat blocks)."""
    return [ln for ln in _clean(s).split("\n") if ln]


def _esc(value: str) -> str:
    """Escape a value for a Cargo `where` clause (SQL-like): double single quotes."""
    return value.replace("'", "''")


# ---------------------------------------------------------------------------
# Low-level API wrappers.
# ---------------------------------------------------------------------------

def cargo_query(table: str, fields: str, where: str, limit: int = 5) -> list[dict]:
    """Run a Cargo query and return the rows as dicts with underscored keys
    (Cargo hands back keys with spaces, e.g. 'base item')."""
    data = _api({"action": "cargoquery", "tables": table, "fields": fields,
                 "where": where, "limit": str(limit)})
    rows = data.get("cargoquery", []) if isinstance(data, dict) else []
    return [{k.replace(" ", "_"): v for k, v in row.get("title", {}).items()} for row in rows]


def search(query: str, limit: int = 5) -> list[str]:
    """Resolve a free-text name to wiki page titles via OpenSearch."""
    data = _api({"action": "opensearch", "search": query, "limit": str(limit)})
    # OpenSearch returns [query, [titles], [descriptions], [urls]].
    return data[1] if isinstance(data, list) and len(data) > 1 else []


def page_extract(title: str, max_chars: int = 3000) -> str:
    """Plain-text extract of a wiki page (following redirects), truncated."""
    data = _api({"action": "query", "prop": "extracts", "explaintext": "1",
                 "redirects": "1", "titles": title})
    pages = data.get("query", {}).get("pages", {}) if isinstance(data, dict) else {}
    for page in pages.values():
        text = page.get("extract")
        if text:
            text = text.strip()
            if len(text) > max_chars:
                text = text[:max_chars].rstrip() + " …[truncated]"
            return text
    return ""


# ---------------------------------------------------------------------------
# High-level lookups (used by the tools). Each returns a result dict or an
# {"error": …} dict — never raises, so a flaky network can't break a tool.
# ---------------------------------------------------------------------------

def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return {"error": f"{_SOURCE} request failed: {type(e).__name__}: {e}",
                "source": _SOURCE}


def lookup_item(name: str) -> dict:
    """Look a unique or base item up in the wiki's `items` Cargo table."""
    def run():
        rows = cargo_query(
            "items",
            "name,rarity,class,base_item,required_level,implicit_stat_text,"
            "explicit_stat_text,flavour_text",
            f"items.name='{_esc(name)}'", limit=1)
        if not rows:
            return {"error": f"No item named {name!r} on {_SOURCE}.",
                    "did_you_mean": search(name), "source": _SOURCE}
        r = rows[0]
        return {
            "name": r.get("name"),
            "rarity": r.get("rarity"),
            "class": r.get("class"),
            "base_item": r.get("base_item") or None,
            "required_level": r.get("required_level") or None,
            "implicit": _lines(r.get("implicit_stat_text")),
            "explicit": _lines(r.get("explicit_stat_text")),
            "flavour": _clean(r.get("flavour_text")) or None,
            "source": _SOURCE,
            "note": "Live wiki data (current patch). Unique ranges are min–max rolls.",
        }
    return _guard(run)


def lookup_skill(name: str) -> dict:
    """Look an active skill up in the wiki's `skill` Cargo table."""
    def run():
        rows = cargo_query(
            "skill",
            "active_skill_name,cast_time,max_level,stat_text,description",
            f"skill.active_skill_name='{_esc(name)}'", limit=1)
        if not rows:
            return {"error": f"No skill named {name!r} on {_SOURCE}.",
                    "did_you_mean": search(name), "source": _SOURCE}
        r = rows[0]
        return {
            "name": r.get("active_skill_name"),
            "cast_time": r.get("cast_time") or None,
            "max_level": r.get("max_level") or None,
            "description": _clean(r.get("description")) or None,
            "stats": _lines(r.get("stat_text")),
            "source": _SOURCE,
            "note": "Live wiki data (current patch). For the build's own computed "
                    "numbers use get_skill_details / the recompute engine instead.",
        }
    return _guard(run)


def lookup_mechanic(query: str) -> dict:
    """Fetch the wiki's plain-text page for a game mechanic/keyword. Complements
    explain_mechanic (the offline, curated PoE1-trap model) with the live page —
    use it to verify or refresh patch-sensitive numbers."""
    def run():
        text = page_extract(query)
        title = query
        related: list[str] = []
        if not text:
            hits = search(query)
            if not hits:
                return {"error": f"No wiki page found for {query!r} on {_SOURCE}.",
                        "source": _SOURCE}
            title = hits[0]
            text = page_extract(title)
            related = hits[1:]
        if not text:
            return {"error": f"No extract available for {title!r} on {_SOURCE}.",
                    "did_you_mean": search(query), "source": _SOURCE}
        return {
            "title": title,
            "text": text,
            "related": related,
            "source": _SOURCE,
            "note": "Live wiki prose (current patch). Pair with explain_mechanic, "
                    "which gives the durable PoE1-vs-PoE2 corrections offline.",
        }
    return _guard(run)


def wiki_search(query: str, limit: int = 8) -> dict:
    """Resolve a free-text query to candidate wiki page titles (name disambiguation)."""
    def run():
        return {"query": query, "results": search(query, limit), "source": _SOURCE}
    return _guard(run)
