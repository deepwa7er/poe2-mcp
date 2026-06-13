"""
Rune / Soul Core granted-mod lookup for the craft advisor.

A rune grants a different mod depending on the item class it's socketed into (a
Desert Rune adds Fire damage to a weapon but +Fire Resistance to armour), so a
lookup needs the target item's class. The data is vendored by
scripts/build_rune_data.py from PoB2's ModRunes.lua as
{rune: {item_class: {type, mods, bonded?, rank?}}}, already rendered to English.

This replaces the old name-only `_RUNE_HINTS`: instead of "a Glacial Rune grants
cold resistance", the advisor can now say "+14% to Cold Resistance".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .._resources import resource_path

# The generic armour / weapon / caster keys a rune falls back to when it has no
# entry for the exact slot. Order matters: specific slot first, then the broad one.
_ARMOUR = {"helmet", "gloves", "boots", "body armour", "shield", "buckler"}
_CASTER = {"wand", "sceptre", "staff"}
_MARTIAL = {
    "bow", "crossbow", "quarterstaff", "warstaff", "spear", "claw", "dagger",
    "rune dagger", "flail", "one hand mace", "two hand mace", "one hand sword",
    "two hand sword", "thrusting one hand sword", "one hand axe", "two hand axe",
    "sword", "axe", "mace",
}


def _candidate_classes(item_class: str) -> list[str]:
    """Ordered ModRunes class keys to try for a craft item class — the exact slot
    first, then the broad category (armour / weapon / caster). Empty/uniquely-
    jewellery classes (rings, belts, …) have no rune sockets and yield nothing."""
    c = (item_class or "").strip().lower()
    out = [c]
    if c in _ARMOUR:
        out.append("armour")
    elif c in _CASTER:
        out += ["caster", "weapon"]
    elif c in _MARTIAL:
        out.append("weapon")
    elif c == "focus":
        out += ["focus", "caster", "armour"]
    elif c == "amulet":
        out.append("talisman")
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


class RuneData:
    """Vendored rune/soul-core grants, queryable by target stat + item class."""

    def __init__(self, runes: dict[str, dict], meta: dict | None = None):
        self._runes = runes
        self.meta = meta or {}

    def grants(self, keyword: str, item_class: str, limit: int = 5) -> list[dict]:
        """Runes/soul cores whose granted mod for `item_class` matches `keyword`.

        Matching requires every word of the keyword to appear in a granted line
        ("cold resistance" → "+14% to Cold Resistance"). Only the unconditional
        `mods` are matched; the conditional `bonded` lines ride along for context.
        Results are ranked by rune rank (higher = stronger tier) and capped."""
        words = keyword.lower().split()
        if not words:
            return []
        candidates = _candidate_classes(item_class)
        out: list[dict] = []
        for name, by_class in self._runes.items():
            entry = used = None
            for c in candidates:
                if c in by_class:
                    entry, used = by_class[c], c
                    break
            if not entry:
                continue
            matched = [m for m in entry["mods"] if all(w in m.lower() for w in words)]
            if matched:
                out.append({
                    "rune": name,
                    "type": entry.get("type", "Rune"),
                    "item_class": used,
                    "grants": matched,
                    "bonded": entry.get("bonded", []),
                    "rank": entry.get("rank"),
                })
        out.sort(key=lambda r: (-(r["rank"] or 0), r["rune"]))
        return out[:limit]


def load_rune_data(path: str | Path) -> RuneData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RuneData(data.get("runes", {}), data.get("meta", {}))


def load_default_rune_data() -> RuneData | None:
    """Load the vendored rune data, or None if absent (the advisor then simply
    omits rune options)."""
    env_path = os.environ.get("RUNE_DATA_PATH")
    path = Path(env_path) if env_path else resource_path("data", "poe2_runes.json")
    if not path.exists():
        return None
    return load_rune_data(path)
