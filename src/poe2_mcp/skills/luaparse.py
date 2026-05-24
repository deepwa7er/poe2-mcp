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

    return {
        "name": _str_field(body, "name"),
        "base_type": _str_field(body, "baseTypeName"),
        "description": _str_field(body, "description"),
        "skill_types": skill_types,
        "spirit_reservation": spirit_reservation,
        "cast_time": cast_time,
    }
