"""
Load the vendored skill-gem database and look gems up by id or name.

The database is generated from Path of Building 2's data by
scripts/build_skill_data.py (see that file for provenance) and shipped as
data/poe2_skills.json:

    { "skills": { "<skillId>": {name, base_type, description, skill_types,
                                spirit_reservation, cast_time} }, "meta": {...} }

The server works without it — get_skill_details just reports that no data is
loaded. Set SKILL_DATA_PATH to override the default location.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# The tag PoB sets on gems that hold a Spirit reservation while active. (The
# broader "Buff"/"Persistent" tags also cover activate-and-consume skills like
# Charged Staff that reserve nothing, so they would over-match here.)
_RESERVATION_TYPE = "HasReservation"

_default_path = Path(__file__).parent.parent.parent.parent / "data" / "poe2_skills.json"


class GemData:
    def __init__(self, skills: dict[str, dict], meta: dict | None = None):
        self._skills = skills
        self.meta = meta or {}
        # name → skillId, lowercased, for name-based lookup.
        self._by_name: dict[str, str] = {}
        for sid, s in skills.items():
            for label in (s.get("name"), s.get("base_type")):
                if label:
                    self._by_name.setdefault(label.lower(), sid)

    def get(self, query: str) -> dict | None:
        """Look a gem up by skillId (exact), then by display name (case-insensitive).

        Tolerates the export's `...Player` skillId suffix and `SkillGem`/`Support`
        gemId prefixes so ids straight from get_skills resolve."""
        if query in self._skills:
            return self._enrich(query)

        # Normalise common id shapes: strip a trailing "Player", strip metadata prefixes.
        candidates = [query]
        if query.endswith("Player"):
            candidates.append(query[: -len("Player")])
        tail = query.rsplit("/", 1)[-1]
        for pre in ("SkillGem", "SupportGem", "Support"):
            if tail.startswith(pre):
                candidates.append(tail[len(pre):])
        for c in candidates:
            if c in self._skills:
                return self._enrich(c)

        sid = self._by_name.get(query.lower())
        return self._enrich(sid) if sid else None

    def _enrich(self, skill_id: str) -> dict:
        s = dict(self._skills[skill_id])
        s["skill_id"] = skill_id
        types = set(s.get("skill_types", []))
        s["reserves_spirit"] = _RESERVATION_TYPE in types or s.get("spirit_reservation", 0) > 0
        s["generates_charges"] = "GeneratesCharges" in types
        # Charge consumption isn't a discrete tag; surface it from the mechanic text.
        # Stem "consum" covers consume/consumes/consuming.
        desc = (s.get("description") or "").lower()
        s["consumes_power_charges"] = "consum" in desc and "power charge" in desc
        return s


def load_gem_data(path: str | Path) -> GemData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GemData(data.get("skills", {}), data.get("meta", {}))


def load_default_gem_data() -> GemData | None:
    """Load the gem database from the default path, or None if not present."""
    env_path = os.environ.get("SKILL_DATA_PATH")
    path = Path(env_path) if env_path else _default_path
    if not path.exists():
        return None
    return load_gem_data(path)
