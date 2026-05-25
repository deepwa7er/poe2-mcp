#!/usr/bin/env python3
"""
Generate data/poe2_crafting.json from the RePoE-fork PoE2 data export.

RePoE-fork (https://repoe-fork.github.io/poe2/) publishes the game's mod and
base-item tables as JSON, extracted from the client. GGG provides no official
PoE2 data export and poe2db has no data API, so this community export is the
practical source for the affix pool. We fetch two files and slim them to just
what the craft advisor needs:

  * mods.json      → the rollable explicit affix pool. We keep only domain "item"
    prefixes/suffixes that can actually spawn (a positive spawn weight). Each kept
    mod records its type/group, prefix-vs-suffix, required level, display text, and
    its ordered spawn-weight list (which bases it rolls on, and at what weight).
  * base_items.json → base type → tags/class/level, so an item's base can be mapped
    to the tags the spawn weights are keyed on.

The ordered spawn-weight list is preserved verbatim because PoE resolves a mod's
weight on a base by taking the FIRST entry whose tag the base has (a 0 on a
specific tag excludes that base even if a broader later tag would match).

Run from the repo root:

    uv run python scripts/build_craft_data.py

This is a build-time tool — the only part of the project that fetches this data.
Re-run it to refresh the pool after a PoE2 patch; the result is vendored as JSON
so the server stays offline and fast at runtime (same approach as poe2_tree.json
and poe2_skills.json).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx

BASE = "https://repoe-fork.github.io/poe2"
OUT = Path(__file__).parent.parent / "data" / "poe2_crafting.json"

# Item classes a player equips and would craft on. Bases outside these (currency,
# maps, soul cores, …) are dropped to keep the base table small and lookups clean.
_EQUIP_CLASSES = {
    "amulet", "ring", "belt", "quiver", "focus", "shield", "buckler",
    "helmet", "body armour", "gloves", "boots",
    "wand", "sceptre", "staff", "warstaff", "quarterstaff",
    "bow", "crossbow", "claw", "dagger", "rune dagger",
    "one hand sword", "two hand sword", "thrusting one hand sword",
    "one hand axe", "two hand axe", "one hand mace", "two hand mace",
    "sword", "axe", "mace", "spear", "flail", "trap", "fishing rod",
    "jewel", "abyss jewel", "charm",
}

_BRACKET_PIPE = re.compile(r"\[[^\]|]*\|([^\]]*)\]")  # [Resistances|Cold Resistance] -> Cold Resistance
_BRACKET_PLAIN = re.compile(r"\[([^\]|]*)\]")          # [Life] -> Life


def clean_text(text: str) -> str:
    """Resolve RePoE display markup to the plain game-tooltip wording.

    RePoE wraps glossary terms as [display] or [link|display]; the player-facing
    text is the part after the pipe (or the whole token when there is no pipe).
    """
    text = _BRACKET_PIPE.sub(lambda m: m.group(1), text)
    text = _BRACKET_PLAIN.sub(lambda m: m.group(1), text)
    return text.strip()


def main() -> None:
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        print("fetching mods.json …")
        mods_raw = c.get(f"{BASE}/mods.json").raise_for_status().json()
        print("fetching base_items.json …")
        bases_raw = c.get(f"{BASE}/base_items.json").raise_for_status().json()

    mods: list[dict] = []
    for mid, m in mods_raw.items():
        if m.get("domain") != "item":
            continue
        gen = m.get("generation_type")
        if gen not in ("prefix", "suffix"):
            continue
        sw = [[w["tag"], w["weight"]] for w in m.get("spawn_weights", [])]
        if not any(w > 0 for _, w in sw):
            continue  # cannot roll anywhere — special/internal mod
        groups = m.get("groups") or []
        mods.append({
            "id": mid,
            "type": m.get("type", ""),
            "group": groups[0] if groups else "",
            "gen": gen,
            "name": m.get("name", ""),
            "lvl": m.get("required_level", 0),
            "text": clean_text(m.get("text") or ""),
            "sw": sw,
        })

    bases: dict[str, dict] = {}
    for b in bases_raw.values():
        cls = (b.get("item_class") or "").strip()
        if cls.lower() not in _EQUIP_CLASSES:
            continue
        name = (b.get("name") or "").strip()
        if not name:
            continue
        # First entry wins on duplicate names; bases sharing a name share tags.
        bases.setdefault(name.lower(), {
            "name": name,
            "cls": cls,
            "tags": b.get("tags", []),
            "lvl": b.get("drop_level", 0),
        })

    payload = {
        "meta": {
            "source": f"{BASE} (RePoE-fork PoE2 export)",
            "generated": date.today().isoformat(),
            "mod_count": len(mods),
            "base_count": len(bases),
            "note": "Slimmed to item-domain prefix/suffix mods with positive spawn "
                    "weight and equippable base types. Affix pool drifts per patch; "
                    "re-run scripts/build_craft_data.py to refresh.",
        },
        "mods": sorted(mods, key=lambda m: (m["type"], m["lvl"])),
        "bases": dict(sorted(bases.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    print(f"Wrote {len(mods)} mods + {len(bases)} bases to {OUT} "
          f"({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
