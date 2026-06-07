"""
Extract skill gem data from Path of Building 2's Lua skill files.

PoB2 stores its skill data as Lua source (src/Data/Skills/*.lua) — the same data
that drives its calculations — as a series of top-level assignments:

    skills["CombatFrenzyPlayer"] = {
        name = "Combat Frenzy",
        baseTypeName = "Combat Frenzy",
        description = "While active, grants you a Frenzy Charge ...",
        skillTypes = { [SkillType.HasReservation] = true, [SkillType.Buff] = true, ... },
        castTime = 1,
        levels = { [1] = { levelRequirement = 0, spiritReservationFlat = 30, }, ... },
    }

We don't need a full Lua interpreter — the structure is regular. We locate each
`skills["KEY"] = { ... }` block by brace-matching (string-aware so braces inside
descriptions don't throw off the count), then pull the handful of fields that
matter for build advice: tags, spirit reservation, and the mechanic description.
"""

from __future__ import annotations

import re

_KEY_RE = re.compile(r'skills\[\s*"([^"]+)"\s*\]\s*=\s*\{')
_SKILLTYPE_RE = re.compile(r"SkillType\.(\w+)")
_RESERVE_RE = re.compile(r"spiritReservationFlat\s*=\s*(\d+)")
# A flat numeric effect, e.g. { "base_reduce_enemy_fire_resistance_%", 30 }. These
# live in statSets[*].constantStats and are the gem's actual mechanical values —
# the difference between knowing a support "penetrates fire res" and "= 30% pen".
_STAT_PAIR_RE = re.compile(r'\{\s*"([^"]+)"\s*,\s*(-?\d+(?:\.\d+)?)\s*\}')
_MANA_MULT_RE = re.compile(r"manaMultiplier\s*=\s*(-?\d+(?:\.\d+)?)")


def parse_skills_lua(text: str) -> dict[str, dict]:
    """Parse one PoB2 skill Lua file into {skill_id: {fields...}}."""
    out: dict[str, dict] = {}
    for m in _KEY_RE.finditer(text):
        key = m.group(1)
        body = _match_braces(text, m.end() - 1)
        if body is not None:
            out[key] = _parse_block(key, body)
    return out


def _match_braces(text: str, open_idx: int) -> str | None:
    """Given the index of an opening '{', return the text between it and its
    matching '}', skipping over double-quoted strings (with \\-escapes)."""
    depth = 0
    in_str = False
    esc = False
    for i in range(open_idx, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i]
    return None


def _str_field(body: str, name: str) -> str:
    m = re.search(name + r'\s*=\s*"((?:[^"\\]|\\.)*)"', body)
    if not m:
        return ""
    return m.group(1).replace('\\"', '"').replace("\\\\", "\\").strip()


def _typelist(body: str, field: str) -> list[str]:
    """Return the SkillType.* names listed in `field = { ... }`, or []."""
    m = re.search(field + r"\s*=\s*\{", body)
    if not m:
        return []
    inner = _match_braces(body, m.end() - 1)
    return _SKILLTYPE_RE.findall(inner) if inner else []


def _names_in(body: str, field: str) -> list[str]:
    """Return the quoted strings listed in `field = { "a", "b" }`, or []."""
    m = re.search(field + r"\s*=\s*\{", body)
    if not m:
        return []
    inner = _match_braces(body, m.end() - 1)
    return re.findall(r'"([^"]+)"', inner) if inner else []


def _bracket_keys(body: str, field: str) -> list[str]:
    """Return the keys of a `field = { ["Staff"] = true, ... }` set, or []."""
    m = re.search(field + r"\s*=\s*\{", body)
    if not m:
        return []
    inner = _match_braces(body, m.end() - 1)
    return re.findall(r'\[\s*"([^"]+)"\s*\]', inner) if inner else []


def _flag(body: str, name: str) -> bool:
    return bool(re.search(rf"\b{name}\s*=\s*true\b", body))


def _stat_pairs(body: str, field: str) -> list[dict]:
    """Parse the `{ "id", num }` pairs inside every `field = { ... }` block in
    body (a gem can have several statSets) as {id, value}, deduped first-wins.

    Scoped to the named block — crucial so constantStats (flat effects) and
    qualityStats (per-quality-point effects, often fractional like number_of_chains
    = 0.1) don't get conflated."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(field + r"\s*=\s*\{", body):
        inner = _match_braces(body, m.end() - 1)
        if not inner:
            continue
        for sid, val in _STAT_PAIR_RE.findall(inner):
            if sid in seen:
                continue
            seen.add(sid)
            num = float(val)
            out.append({"id": sid, "value": int(num) if num.is_integer() else num})
    return out


def _flag_stats(body: str) -> list[str]:
    """Boolean stat ids from a statSet's `stats = { "id", ... }` list — flags with
    no numeric value (e.g. "hits_ignore_enemy_fire_resistance", "never_freeze").

    These live in a block named exactly `stats` (lowercase), distinct from the
    `constantStats`/`qualityStats` numeric blocks — the negative lookbehind keeps
    this from matching those (and the lowercase spelling won't match the capital-S
    `...Stats` names either). A flag is a bare quoted string; any `{ "id", num }`
    pair would belong to numeric extraction, so it is excluded."""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?<![A-Za-z])stats\s*=\s*\{", body):
        inner = _match_braces(body, m.end() - 1)
        if not inner:
            continue
        pairs = set(re.findall(r'\{\s*"([^"]+)"\s*,', inner))
        for sid in re.findall(r'"([^"]+)"', inner):
            if sid in pairs or sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
    return out


def _parse_block(skill_id: str, body: str) -> dict:
    skill_types: list[str] = []
    st = re.search(r"skillTypes\s*=\s*\{", body)
    if st:
        inner = _match_braces(body, st.end() - 1)
        if inner:
            skill_types = _SKILLTYPE_RE.findall(inner)

    reservations = [int(v) for v in _RESERVE_RE.findall(body)]
    spirit_reservation = max(reservations) if reservations else 0

    cast = re.search(r"castTime\s*=\s*([\d.]+)", body)
    cast_time = float(cast.group(1)) if cast else None

    mana_mult = _MANA_MULT_RE.search(body)
    mana_multiplier = float(mana_mult.group(1)) if mana_mult else None

    # Numeric flat effects plus boolean flag-stats, merged into one list. A flag
    # carries value True (it grants the mechanic outright, e.g. ignore a resistance);
    # a numeric pair already present wins, so flags never shadow a real number.
    numeric_stats = _stat_pairs(body, "constantStats")
    numeric_ids = {s["id"] for s in numeric_stats}
    stats = numeric_stats + [
        {"id": sid, "value": True} for sid in _flag_stats(body) if sid not in numeric_ids
    ]

    return {
        "name": _str_field(body, "name"),
        "base_type": _str_field(body, "baseTypeName"),
        "description": _str_field(body, "description"),
        "skill_types": skill_types,
        "spirit_reservation": spirit_reservation,
        "cast_time": cast_time,
        # Support-gem mechanics: what it does (numbers), what skills it attaches to
        # and how it reshapes them, its tier family, and its mana surcharge.
        "is_support": _flag(body, "support"),
        "gem_family": _names_in(body, "gemFamily"),
        "requires": _typelist(body, "requireSkillTypes"),      # supported skill must have these
        "adds_skill_types": _typelist(body, "addSkillTypes"),   # types the support grants (e.g. Triggered)
        "excludes_skill_types": _typelist(body, "excludeSkillTypes"),  # types that disqualify the skill
        "stats": stats,                                         # flat numeric + boolean flag effects
        "quality_stats": _stat_pairs(body, "qualityStats"),     # effect per point of gem quality
        "mana_multiplier": mana_multiplier,
        # Applicability / provenance flags worth honouring in advice.
        "weapon_types": _bracket_keys(body, "weaponTypes"),     # weapon a skill requires
        "minion_list": _names_in(body, "minionList"),           # what the skill summons
        "hidden": _flag(body, "hidden"),
        "legacy": _flag(body, "legacy"),
        "cannot_be_supported": _flag(body, "cannotBeSupported"),
        "from_item": _flag(body, "fromItem"),                   # granted by an item, not socketed
        "from_tree": _flag(body, "fromTree"),                   # granted by the passive tree
    }
