#!/usr/bin/env python3
"""
Generate data/poe2_runes.json from Path of Building 2's ModRunes.lua.

Runes and Soul Cores grant a fixed modifier when socketed, and the granted line
depends on the item class (a Desert Rune adds Fire damage to a weapon but +Fire
Resistance to armour). The RePoE crafting export carries none of these values, so
craft_advisor could previously only NAME a rune. PoB2's ModRunes.lua has them, as
already-rendered English keyed by rune name → item class → mod lines, e.g.

    ["Desert Rune"] = {
        ["armour"] = { type="Rune", "+14% to Fire Resistance",
                       "Bonded: +20 to maximum Life", rank={15}, ... },
        ["weapon"] = { type="Rune", "Adds 7 to 11 Fire Damage", ... },
    }

We parse it (reusing the Lua-table parser from skills/statdesc.py), keep the mod
lines, type, and rank per class, and split off the conditional "Bonded:" lines.
The result is vendored so the runtime stays offline.

Run from the repo root:

    uv run python scripts/build_rune_data.py

Build-time only; re-run after a PoB2 data update.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from poe2_mcp.skills.statdesc import _LuaTableParser  # noqa: E402

REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
REF = "dev"
URL = f"https://raw.githubusercontent.com/{REPO}/{REF}/src/Data/ModRunes.lua"
OUT = Path(__file__).parent.parent / "data" / "poe2_runes.json"

_BONDED = "Bonded:"


def _class_entry(spec: dict) -> dict:
    """Pull the mod lines (positional strings), type, and rank from one class spec,
    splitting the conditional 'Bonded:' lines from the unconditional grants."""
    mods, bonded = [], []
    for k in sorted(k for k in spec if isinstance(k, int)):
        line = spec[k]
        if not isinstance(line, str):
            continue
        if line.startswith(_BONDED):
            bonded.append(line[len(_BONDED):].strip())
        else:
            mods.append(line)
    rank = None
    if isinstance(spec.get("rank"), dict):
        vals = [spec["rank"][k] for k in sorted(k for k in spec["rank"] if isinstance(k, int))]
        rank = vals[0] if vals else None
    out = {"type": spec.get("type", "Rune"), "mods": mods}
    if bonded:
        out["bonded"] = bonded
    if rank is not None:
        out["rank"] = rank
    return out


def main() -> None:
    text = httpx.get(URL, timeout=60, follow_redirects=True).raise_for_status().text
    root = _LuaTableParser(text).parse_return()

    runes: dict[str, dict] = {}
    for name, by_class in root.items():
        if not isinstance(by_class, dict):
            continue
        classes = {}
        for cls, spec in by_class.items():
            if isinstance(spec, dict):
                entry = _class_entry(spec)
                if entry["mods"] or entry.get("bonded"):
                    classes[cls] = entry
        if classes:
            runes[name] = classes

    payload = {
        "meta": {
            "source": f"{REPO}@{REF}/src/Data/ModRunes.lua",
            "generated": date.today().isoformat(),
            "rune_count": len(runes),
            "note": "Rune/Soul Core granted mods per item class, already rendered to "
                    "English by PoB. 'bonded' lines apply only when the rune is bonded "
                    "to a matching item. Re-run scripts/build_rune_data.py to refresh.",
        },
        "runes": dict(sorted(runes.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    print(f"Wrote {len(runes)} runes to {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
