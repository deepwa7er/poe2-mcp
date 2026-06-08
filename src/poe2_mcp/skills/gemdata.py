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
import re
from pathlib import Path

# The tag PoB sets on gems that hold a Spirit reservation while active. (The
# broader "Buff"/"Persistent" tags also cover activate-and-consume skills like
# Charged Staff that reserve nothing, so they would over-match here.)
_RESERVATION_TYPE = "HasReservation"

# Trailing tier numeral on a support's display name ("Fire Penetration I",
# "Magnified Area II"). Stripped so a bare name from a model resolves to a tier.
_TIER_SUFFIX = re.compile(r"\s+(?:I{1,3}|IV|VI{0,3}|IX|XI{0,2}|X)$")

_default_path = Path(__file__).parent.parent.parent.parent / "data" / "poe2_skills.json"


class GemData:
    def __init__(self, skills: dict[str, dict], meta: dict | None = None):
        self._skills = skills
        self.meta = meta or {}
        # name → skillId, lowercased, for name-based lookup.
        self._by_name: dict[str, str] = {}
        # gemFamily → [skillId, ...], so a gem can list its sibling tiers.
        self._by_family: dict[str, list[str]] = {}
        for sid, s in skills.items():
            for label in (s.get("name"), s.get("base_type")):
                if not label:
                    continue
                self._by_name.setdefault(label.lower(), sid)
                # Also register the tier-stripped name ("Fire Penetration" →
                # the lowest tier) so "Minion Pact" resolves to "Minion Pact I".
                base = _TIER_SUFFIX.sub("", label).strip().lower()
                if base != label.lower():
                    self._by_name.setdefault(base, sid)
            for fam in s.get("gem_family") or []:
                self._by_family.setdefault(fam, []).append(sid)

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

    def supports_for(self, skill_types) -> list[dict]:
        """Every socketable support gem compatible with a skill that has the given
        skill_types, enriched. Compatibility = the support's `requires` tags
        intersect the skill's tags (OR-semantics — a Damage-tagged spell satisfies
        a support that requires "Damage"/"Attack"/"CrossbowAmmoSkill"), and none of
        its `excludes_skill_types` do. Drops gems you can't socket from a vendor
        (hidden/legacy/from_item/from_tree/cannot_be_supported)."""
        tags = set(skill_types)
        out: list[dict] = []
        for sid, s in self._skills.items():
            if not s.get("is_support"):
                continue
            if any(s.get(k) for k in
                   ("hidden", "legacy", "cannot_be_supported", "from_item", "from_tree")):
                continue
            # `requires`/`excludes` may carry "AND"/"OR" operator tokens, not types.
            req = [r for r in (s.get("requires") or []) if r not in ("AND", "OR")]
            if req and not (set(req) & tags):
                continue
            excl = [e for e in (s.get("excludes_skill_types") or []) if e not in ("AND", "OR")]
            if set(excl) & tags:
                continue
            out.append(self._enrich(sid))
        return out

    def active_skills_for(self, tags, match: str = "all") -> list[dict]:
        """Every socketable ACTIVE (non-support) skill whose skill_types match `tags`,
        enriched. match="all" (default) requires every tag (e.g. {"Fire","Spell"} →
        fire spells); "any" requires at least one. Drops supports and gems you cannot
        obtain as a socketable gem (hidden/legacy/from_item/from_tree).

        This is the discovery path for skills a build does NOT currently use — the
        active skill itself is an upgrade lever, not just its supports. supports_for is
        the support-gem counterpart; this is the active-skill one."""
        want = set(tags)
        out: list[dict] = []
        for sid, s in self._skills.items():
            if s.get("is_support"):
                continue
            if any(s.get(k) for k in ("hidden", "legacy", "from_item", "from_tree")):
                continue
            types = set(s.get("skill_types") or [])
            if match == "any":
                if not (want & types):
                    continue
            elif not want <= types:
                continue
            out.append(self._enrich(sid))
        return out

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
        s["family_tiers"] = self._family_tiers(skill_id, s.get("gem_family") or [])
        return s

    def _family_tiers(self, skill_id: str, families: list[str]) -> list[dict]:
        """Sibling gems sharing this gem's family (its other tiers), with their
        numeric effects — so advice can compare e.g. Fire Penetration I/II/III
        without a lookup per tier. Excludes the gem itself; empty for actives."""
        sibling_ids: list[str] = []
        seen = {skill_id}
        for fam in families:
            for sid in self._by_family.get(fam, []):
                if sid not in seen:
                    seen.add(sid)
                    sibling_ids.append(sid)
        tiers = [
            {
                "skill_id": sid,
                "name": self._skills[sid].get("name"),
                "stats": self._skills[sid].get("stats") or [],
                "mana_multiplier": self._skills[sid].get("mana_multiplier"),
            }
            for sid in sibling_ids
        ]
        tiers.sort(key=lambda t: t["name"] or "")
        return tiers


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
