#!/usr/bin/env python3
"""
Generate data/poe2_stat_descriptions.json — the stat-id → in-game-line map.

PoB2 ships GGG's tooltip descriptions as machine-generated Lua under
src/Data/StatDescriptions/. We parse them (see skills/statdesc.py), keep the
single-stat lines (Phase 1; see docs/plain-english-stat-text.md), and vendor a
slim JSON the server uses at runtime to render raw stat ids like
`base_reduce_enemy_fire_resistance_% = 30` into "Penetrate 30% Fire Resistance".

Two scopes are kept, because wording depends on whether the gem is a support:
  * support — from gem_stat_descriptions.lua ("Supported Skills deal …").
  * skill   — from skill_stat_descriptions.lua over the master stat_descriptions.lua
              (plain "… increased …"), for an active skill's own stats.
The runtime tries the scope matching the gem first, then the other as a fallback.

The vendored file is SLIMMED to only the stat ids that data/poe2_skills.json
actually references, so build that first. Run from the repo root:

    uv run python scripts/build_skill_data.py    # produces poe2_skills.json
    uv run python scripts/build_stat_data.py

Build-time only; the runtime never fetches. Re-run after a PoB2 data update.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from poe2_mcp.skills.statdesc import parse_stat_descriptions  # noqa: E402

REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
REF = "dev"
BASE = f"https://raw.githubusercontent.com/{REPO}/{REF}/src/Data/StatDescriptions"
SKILLS = Path(__file__).parent.parent / "data" / "poe2_skills.json"
OUT = Path(__file__).parent.parent / "data" / "poe2_stat_descriptions.json"


def _referenced_ids(skills_path: Path) -> set[str]:
    """Every stat id the gem db actually uses — across stats, quality_stats, and
    family-tier stats — so we vendor only descriptions we can put to work."""
    data = json.loads(skills_path.read_text())
    ids: set[str] = set()
    for s in data.get("skills", {}).values():
        for blk in ("stats", "quality_stats"):
            for e in s.get(blk) or []:
                ids.add(e["id"])
        for t in s.get("family_tiers") or []:
            for e in t.get("stats") or []:
                ids.add(e["id"])
    return ids


def _slim(desc: dict, ids: set[str]) -> dict:
    return {k: v for k, v in desc.items() if k in ids}


def main() -> None:
    if not SKILLS.exists():
        sys.exit(f"{SKILLS} missing — run scripts/build_skill_data.py first.")
    ids = _referenced_ids(SKILLS)

    with httpx.Client(timeout=120, follow_redirects=True) as c:
        def fetch(name: str) -> str:
            r = c.get(f"{BASE}/{name}")
            r.raise_for_status()
            return r.text

        gem = parse_stat_descriptions(fetch("gem_stat_descriptions.lua"))
        skill = parse_stat_descriptions(fetch("skill_stat_descriptions.lua"))
        master = parse_stat_descriptions(fetch("stat_descriptions.lua"))

    # support scope: gem wording. skill scope: skill over master (skill wins).
    support_scope = gem
    skill_scope = {**master, **skill}

    support_slim = _slim(support_scope, ids)
    skill_slim = _slim(skill_scope, ids)
    covered = ids & (set(support_slim) | set(skill_slim))
    print(f"  referenced ids: {len(ids)}")
    print(f"  support-scope lines: {len(support_slim)}  skill-scope lines: {len(skill_slim)}")
    print(f"  ids with a rendered line: {len(covered)} ({100 * len(covered) // len(ids)}%)")

    payload = {
        "meta": {
            "source": f"{REPO}@{REF}/src/Data/StatDescriptions",
            "generated": date.today().isoformat(),
            "phase": "1 (single-stat lines; multi-stat fall back to the raw id)",
            "referenced_ids": len(ids),
            "covered_ids": len(covered),
        },
        "scopes": {
            "support": dict(sorted(support_slim.items())),
            "skill": dict(sorted(skill_slim.items())),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
