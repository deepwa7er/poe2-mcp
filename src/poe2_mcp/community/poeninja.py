"""
poe.ninja PoE2 builds provider (undocumented API — see project memory).

Endpoints used (base https://poe.ninja):
  GET /poe2/api/data/build-index-state            JSON  — meta: ascendancy popularity per league
  GET /poe2/api/data/index-state                  JSON  — catalog: current league version + snapshotName
  GET /poe2/api/builds/<version>/search?overview= protobuf — top ~100 builds (columnar, interned)
  GET /poe2/api/builds/dictionary/<hash>          protobuf — string table a column indexes into
  GET /poe2/api/builds/<version>/character?...     JSON  — one character; has pathOfBuildingExport

The search payload is columnar: each result column holds ~100 parallel values, and
string columns (class, skill, …) store integer indices into a per-dimension
dictionary whose hash is embedded in the payload. We decode only the fields the
build list needs; the full build is fetched as a standard PoB code via /character.
"""

from __future__ import annotations

import httpx

from . import protobuf as pb
from .cache import TTLCache

_BASE = "https://poe.ninja"
_UA = "poe2-mcp build-analysis (https://github.com/deepwa7er/poe2-mcp)"
_cache = TTLCache(ttl=900.0)


# ---------------------------------------------------------------------------
# HTTP (cached). Tests monkeypatch _get_json / _get_bytes to use fixtures.
# ---------------------------------------------------------------------------

def _key(path: str, params: dict | None) -> str:
    if not params:
        return path
    return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _get_json(path: str, params: dict | None = None) -> dict:
    ck = ("json", _key(path, params))
    hit = _cache.get(ck)
    if hit is not None:
        return hit
    with httpx.Client(base_url=_BASE, headers={"User-Agent": _UA}, timeout=20, follow_redirects=True) as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        data = r.json()
    _cache.set(ck, data)
    return data


def _get_bytes(path: str, params: dict | None = None) -> bytes:
    ck = ("bytes", _key(path, params))
    hit = _cache.get(ck)
    if hit is not None:
        return hit
    with httpx.Client(base_url=_BASE, headers={"User-Agent": _UA}, timeout=20, follow_redirects=True) as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        data = r.content
    _cache.set(ck, data)
    return data


# ---------------------------------------------------------------------------
# League / snapshot resolution
# ---------------------------------------------------------------------------

def _resolve_snapshot(league: str | None) -> dict:
    """Return the snapshotVersion dict for `league` (url or snapshotName), or the
    current indexed build league by default."""
    idx = _get_json("/poe2/api/data/index-state")
    snapshots = idx.get("snapshotVersions", [])
    if not snapshots:
        raise ValueError("poe.ninja index-state returned no snapshot versions")

    if league:
        for sv in snapshots:
            if league in (sv.get("url"), sv.get("snapshotName"), sv.get("name")):
                return sv
        raise ValueError(f"league {league!r} not found in poe.ninja snapshots")

    indexed = [bl["url"] for bl in idx.get("buildLeagues", []) if bl.get("indexed")]
    if indexed:
        for sv in snapshots:
            if sv.get("url") == indexed[0]:
                return sv
    return snapshots[0]


# ---------------------------------------------------------------------------
# Meta overview (JSON)
# ---------------------------------------------------------------------------

def get_meta_overview(league: str | None = None) -> dict:
    """Ascendancy popularity for a league (default: first listed)."""
    data = _get_json("/poe2/api/data/build-index-state")
    leagues = data.get("leagueBuilds", [])
    if not leagues:
        return {}
    if league:
        lb = next((l for l in leagues if league in (l.get("leagueUrl"), l.get("leagueName"))), None)
        if lb is None:
            raise ValueError(f"league {league!r} not found")
    else:
        lb = leagues[0]
    return {
        "league": lb.get("leagueName"),
        "total_characters": lb.get("total"),
        "ascendancies": [
            {"class": s.get("class"), "percentage": round(s.get("percentage", 0.0), 1), "trend": s.get("trend")}
            for s in lb.get("statistics", [])
        ],
    }


# ---------------------------------------------------------------------------
# Build list (protobuf, columnar)
# ---------------------------------------------------------------------------

def _col_name(subfields: list[pb.Field]) -> str | None:
    for f, wt, v in subfields:
        if f == 1 and wt == pb.WIRETYPE_LEN:
            return pb.as_text(v)
    return None


def _is_hash(s: str | None) -> bool:
    return bool(s) and len(s) == 40 and all(c in "0123456789abcdef" for c in s)


def _find_hash(subfields: list[pb.Field]) -> str | None:
    for f, wt, v in subfields:
        if wt == pb.WIRETYPE_LEN:
            t = pb.as_text(v)
            if _is_hash(t):
                return t
    return None


def _entry_scalar(entry: bytes) -> int | float | str | None:
    """A result-column value entry is a small message; pull its scalar payload."""
    for field in pb.read_fields(entry):
        s = pb.scalar(field)
        if s is not None:
            return s
    return None


def _decode_dictionary(raw: bytes) -> dict[str, list[str]]:
    """{category_name: [values...]} — field 1 starts a category, field 2 appends values."""
    cats: dict[str, list[str]] = {}
    current: str | None = None
    for f, wt, v in pb.read_fields(raw):
        if wt != pb.WIRETYPE_LEN:
            continue
        t = pb.as_text(v)
        if f == 1:
            current = t or ""
            cats.setdefault(current, [])
        elif f == 2 and current is not None and t is not None:
            cats[current].append(t)
    return cats


def list_top_builds(league: str | None = None, limit: int = 20) -> list[dict]:
    """Top builds for a league: rank, character, account, class, level, life, EHP, DPS."""
    sv = _resolve_snapshot(league)
    raw = _get_bytes(f"/poe2/api/builds/{sv['version']}/search", params={"overview": sv["snapshotName"]})

    top = pb.read_fields(raw)
    inner = next((v for f, wt, v in top if f == 1 and wt == pb.WIRETYPE_LEN), None)
    if inner is None:
        return []
    fields = pb.read_fields(inner)

    result_cols: dict[str, list[bytes]] = {}   # column name -> value-entry bytes
    dim_hashes: dict[str, str] = {}            # dimension name -> dictionary hash
    for f, wt, v in fields:
        if wt != pb.WIRETYPE_LEN:
            continue
        sub = pb.read_fields(v)
        name = _col_name(sub)
        if name is None:
            continue
        if f == 5:  # result columns (parallel arrays of displayed values)
            result_cols[name] = [sv2 for sf, sw, sv2 in sub if sf == 2 and sw == pb.WIRETYPE_LEN]
        else:       # dimension metadata may carry a dictionary hash
            h = _find_hash(sub)
            if h:
                dim_hashes[name] = h

    def col(name: str) -> list:
        return [_entry_scalar(e) for e in result_cols.get(name, [])]

    names = col("name")
    accounts = col("account")
    levels = col("level")
    lifes = col("life")
    es = col("energyshield")
    ehps = col("ehp")
    dpses = col("dps")

    # class column holds dictionary indices; index 0 is omitted by protobuf -> None.
    class_idx = col("class")
    class_names: list = [None] * len(class_idx)
    if "class" in dim_hashes:
        cats = _decode_dictionary(_get_bytes(f"/poe2/api/builds/dictionary/{dim_hashes['class']}"))
        values = cats.get("class") or (next(iter(cats.values()), []) if cats else [])
        class_names = []
        for idx in class_idx:
            i = 0 if idx is None else int(idx)
            class_names.append(values[i] if 0 <= i < len(values) else None)

    rows: list[dict] = []
    for i in range(len(names)):
        rows.append({
            "rank": i + 1,
            "character": names[i],
            "account": accounts[i] if i < len(accounts) else None,
            "class": class_names[i] if i < len(class_names) else None,
            "level": levels[i] if i < len(levels) else None,
            "life": lifes[i] if i < len(lifes) else None,
            "energy_shield": es[i] if i < len(es) else None,
            "ehp": ehps[i] if i < len(ehps) else None,
            "dps": dpses[i] if i < len(dpses) else None,
        })
    return rows[:limit]


# ---------------------------------------------------------------------------
# Individual build -> PoB export code (JSON)
# ---------------------------------------------------------------------------

def fetch_pob_export(account: str, name: str, league: str | None = None) -> str:
    """Return the PoB export code for a character from poe.ninja's /character endpoint."""
    sv = _resolve_snapshot(league)
    data = _get_json(
        f"/poe2/api/builds/{sv['version']}/character",
        params={"account": account, "name": name, "overview": sv["snapshotName"], "timeMachine": ""},
    )
    code = data.get("pathOfBuildingExport")
    if not code:
        raise ValueError(f"no PoB export found for {name} ({account}) on poe.ninja")
    return code


# ---------------------------------------------------------------------------
# A specific account's own characters (profile)
# ---------------------------------------------------------------------------

def _account_slug(account: str) -> str:
    """poe.ninja uses a lowercase, hyphenated slug: 'Name#1234' -> 'name-1234'."""
    return account.strip().lstrip("/").replace("#", "-").lower()


def list_characters(account: str) -> list[dict]:
    """List all of an account's characters across leagues (public profiles only)."""
    data = _get_json(f"/poe2/api/profile/characters/{_account_slug(account)}/0")
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for c in data:
        out.append({
            "name": c.get("name"),
            "class": c.get("className"),
            "level": c.get("level"),
            "league": c.get("league"),
            "league_url": c.get("leagueUrl"),
            "current": c.get("isCurrent", False),
            "updated": c.get("updated"),
            "skills": [s.get("name") for s in c.get("skills", []) if isinstance(s, dict) and s.get("name")],
        })
    return out


def fetch_character_export(account: str, name: str) -> str:
    """
    Return a PoB export code for one of an account's own characters.

    Looks the character up in the account's profile, resolves its league's build
    snapshot, and pulls the export. Raises a clear error if poe.ninja has not
    indexed that character (i.e. it is not on the current ladder).
    """
    slug = _account_slug(account)
    chars = _get_json(f"/poe2/api/profile/characters/{slug}/0")
    match = next((c for c in chars if c.get("name") == name), None) if isinstance(chars, list) else None
    if match is None:
        raise ValueError(f"no character named {name!r} found on account {account!r} (is the profile public?)")

    league = match.get("league") or match.get("leagueUrl")
    try:
        return fetch_pob_export(slug, name, league=league)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            raise ValueError(
                f"poe.ninja has no build snapshot for {name!r} (league {league!r}) — it is likely "
                "not on the current ladder. Export it from Path of Building to analyse this one."
            ) from e
        raise
