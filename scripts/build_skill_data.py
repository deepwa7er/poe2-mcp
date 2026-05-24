#!/usr/bin/env python3
"""
Generate data/poe2_skills.json from Path of Building 2's Lua skill data.

PoB2's skill files (src/Data/Skills/*.lua) are the authoritative source PoB uses
for its own calculations, so they carry exactly the fields build advice needs:
skill tags, Spirit reservation, and the mechanic description. We fetch them from
the community repo, parse out the relevant fields (see skills/luaparse.py), and
vendor the result as JSON so the server stays offline and fast at runtime — the
same approach already used for data/poe2_tree.json.

Run from the repo root:

    uv run python scripts/build_skill_data.py

This is a build-time tool; it is the only part of the project that fetches the
Lua source. Re-run it to refresh the database after a PoB2 data update.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from poe2_mcp.skills.luaparse import parse_skills_lua  # noqa: E402

REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
REF = "dev"
BASE = f"https://raw.githubusercontent.com/{REPO}/{REF}/src/Data/Skills"
# Active skills (dex/int/str/other) and support gems. Minions/spectres omitted.
FILES = [
    "act_dex.lua", "act_int.lua", "act_str.lua", "other.lua",
    "sup_dex.lua", "sup_int.lua", "sup_str.lua",
]
OUT = Path(__file__).parent.parent / "data" / "poe2_skills.json"


def main() -> None:
    skills: dict[str, dict] = {}
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        for fn in FILES:
            r = c.get(f"{BASE}/{fn}")
            r.raise_for_status()
            parsed = parse_skills_lua(r.text)
            print(f"  {fn}: {len(parsed)} skills")
            skills.update(parsed)

    # Drop entries with no usable name (internal/helper skills).
    skills = {k: v for k, v in skills.items() if v.get("name")}

    payload = {
        "meta": {
            "source": f"{REPO}@{REF}/src/Data/Skills",
            "generated": date.today().isoformat(),
            "files": FILES,
            "count": len(skills),
        },
        "skills": dict(sorted(skills.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    print(f"Wrote {len(skills)} skills to {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
