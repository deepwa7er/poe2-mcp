"""
Build-aware item-fit analysis.

Given a loaded build, this places each equipped item's rolled mods on their tier
ladders (via CraftData.match_rolled_line) AND judges how well each mod serves THIS
build's scaling — its damage types/delivery (from the active skills), its defensive
base (life vs energy shield, from the computed stats) and its uncapped resistances.

The output is deliberately data-rich and lightly opinionated. It exists to drive a
review that obeys the server's principles:

  * Items are PACKAGES — you acquire a whole rare, you cannot cherry-pick one mod
    off it. So an off-build affix is NORMAL, not a defect, and the tool never says
    "remove mod X". Weak/low-tier mods become criteria for the NEXT item that fills
    the slot, weighted by how realistic that upgrade is at the character's level.
  * No single fit score is presented as a verdict. Per-mod relevance + tier/roll
    quality + open slots are the substance; the caller narrates from them.

The build profile is auto-derived but can be augmented with explicit `priorities`
(stat keywords the user cares about), which are added to the "wanted" set so their
mods always count as on-build.

Everything here is heuristic and patch-sensitive (the affix pool comes from the
vendored RePoE export). Unmatched mods are reported as such, never guessed.
"""

from __future__ import annotations

from .advisor import _slot_accounting
from .data import CraftData

# Default maximum resistance. Builds can raise it, but 75 is the near-universal cap
# and a value below it is the actionable signal ("this resist is leaking").
RES_CAP = 75

# Damage-scope tokens that can appear in a mod's wording, mapped to the build
# "dimension" they require to be useful. A mod whose scope tokens are all absent
# from the build's dimensions is scaling something this build doesn't do.
_SCOPE_TOKENS = {
    "spell": "spell", "cast speed": "spell",
    "attack": "attack", "attack speed": "attack", "accuracy": "attack",
    "melee": "melee",
    "projectile": "projectile", "arrow": "projectile", "bolt": "projectile",
    "minion": "minion",
    "fire": "fire", "ignite": "fire", "burning": "fire",
    "cold": "cold", "freeze": "cold", "chill": "cold",
    "lightning": "lightning", "shock": "lightning",
    "chaos": "chaos", "poison": "chaos",
    "physical": "physical",
    "area": "area",
}
_ELEMENTS = ("fire", "cold", "lightning", "chaos")


def _stat_map(build) -> dict[str, float]:
    """Stats as name -> float. PoB stat values arrive as strings; non-numeric ones
    are dropped (they're never the life/ES/resist scalars we read here)."""
    out: dict[str, float] = {}
    for s in build.stats:
        try:
            out[s.name] = float(s.value)
        except (TypeError, ValueError):
            continue
    return out


def derive_build_profile(build, gems, priorities: list[str] | None = None) -> dict:
    """Infer what stats this build wants, from its stats and active skills.

    Returns: defense ("energy shield"/"life"), caster (bool), dims (damage
    dimensions the build scales), elements (its damage elements), resist_gaps
    ({element: deficit} for uncapped resists), priorities (the caller's extra
    keywords, lower-cased), and a human `summary`.
    """
    stats = _stat_map(build)
    life = stats.get("Life", 0) or 0
    es = stats.get("EnergyShield", 0) or 0
    defense = "energy shield" if es > life else "life"

    # Damage dimensions: union over every enabled active skill in the kit.
    from ..skills.recommend import skill_damage_dims  # local import: avoid cycle
    dims: set[str] = set()
    skills_seen: list[str] = []
    for group in build.socket_groups:
        if not group.enabled:
            continue
        active = next((g for g in group.gems if g.is_active and g.enabled), None)
        if active is None or gems is None:
            continue
        info = gems.get(active.skill_id or active.name)
        if info is None:
            continue
        tags = set(info.get("skill_types") or [])
        dims |= skill_damage_dims(tags)
        skills_seen.append(group.active_skill)
    elements = {e for e in _ELEMENTS if e in dims}
    caster = "spell" in dims

    resist_gaps = {}
    for el in _ELEMENTS:
        key = el.capitalize() + "Resist"
        val = stats.get(key)
        if val is not None and val < RES_CAP:
            resist_gaps[el] = round(RES_CAP - val, 1)

    prio = [p.strip().lower() for p in (priorities or []) if p.strip()]

    bits = [f"{defense}-based"]
    if elements:
        bits.append("/".join(sorted(elements)))
    if caster:
        bits.append("caster")
    elif "attack" in dims:
        bits.append("attack")
    if "minion" in dims:
        bits.append("minions")
    summary = (
        f"{', '.join(bits)} build"
        + (f" ({', '.join(skills_seen[:4])})" if skills_seen else "")
        + (f"; resistance gaps: {', '.join(f'{k} -{v}%' for k, v in resist_gaps.items())}"
           if resist_gaps else "; resistances capped")
    )
    return {
        "defense": defense, "caster": caster, "dims": sorted(dims),
        "elements": sorted(elements), "resist_gaps": resist_gaps,
        "priorities": prio, "main_skills": skills_seen, "summary": summary,
    }


def _element_in(text: str) -> str | None:
    for el in _ELEMENTS:
        if el in text:
            return el
    return None


def _damage_scope(text: str) -> set[str] | None:
    """The build dimensions a damage/offense mod scales, or None if it isn't one.

    Returns an empty set for an unscoped damage mod ("increased Damage") — that
    helps everything, so it counts as on-build for any build.
    """
    if "resistance" in text:  # a defensive mod, handled elsewhere
        return None
    offense_markers = ("damage", "penetrat", "cast speed", "attack speed",
                       "critical", "level of all", "skill", "accuracy",
                       "exposure", "ailment", "ignite", "shock", "freeze")
    if not any(m in text for m in offense_markers):
        return None
    scope: set[str] = set()
    for token, dim in _SCOPE_TOKENS.items():
        if token in text:
            scope.add(dim)
    return scope


def classify_relevance(text: str, profile: dict) -> dict:
    """Bucket one mod line for this build: priority | fit | generic | off_build.

    priority   — fills a defensive hole the build currently has (an uncapped resist).
    fit        — scales this build's damage, or is its defensive base / caster mana.
    generic    — universally useful (life, capped resists, attributes, movement).
    off_build  — scaled to a dimension this build doesn't use. NORMAL, not a defect.
    """
    t = text.lower()
    dims = set(profile["dims"])

    # Caller-supplied priorities always count as on-build.
    if any(p in t for p in profile["priorities"]):
        return {"bucket": "fit", "why": "matches a stated priority"}

    if "resistance" in t:
        el = _element_in(t)
        if el and el in profile["resist_gaps"]:
            return {"bucket": "priority",
                    "why": f"fills {el} resistance gap (-{profile['resist_gaps'][el]}%)"}
        return {"bucket": "generic", "why": "resistance — defensive, universally useful"}

    if "maximum life" in t or ("life regen" in t) or "life regeneration" in t:
        return {"bucket": "generic", "why": "life — defensive, universally useful"}

    if "energy shield" in t:
        if profile["defense"] == "energy shield":
            return {"bucket": "fit", "why": "energy shield — this build's defensive base"}
        return {"bucket": "off_build", "why": "energy shield, but this build is life-based"}

    if "mana" in t and "maximum life" not in t:
        if profile["caster"]:
            return {"bucket": "fit", "why": "mana — fuels this caster"}
        return {"bucket": "generic", "why": "mana — minor unless casting-heavy"}

    if any(a in t for a in ("strength", "dexterity", "intelligence")) and "resist" not in t:
        return {"bucket": "generic", "why": "attribute — requirements / minor scaling"}

    if "movement speed" in t:
        return {"bucket": "generic", "why": "movement speed — universally valuable"}

    scope = _damage_scope(t)
    if scope is not None:
        if not scope:
            return {"bucket": "fit", "why": "scales damage generically"}
        if scope & dims:
            hit = sorted(scope & dims)
            return {"bucket": "fit", "why": f"scales this build's {', '.join(hit)}"}
        return {"bucket": "off_build",
                "why": f"scales {', '.join(sorted(scope))} — not used by this build"}

    return {"bucket": "generic", "why": "utility / situational"}


def analyze_item(item, craft: CraftData, profile: dict) -> dict:
    """Per-item fit analysis: each explicit mod's relevance + tier/roll quality,
    open affix slots, and the weak on-build rolls that become next-item criteria."""
    rec = craft.resolve_base(item.base_type)
    base_tags = set(rec["tags"]) if rec else None
    ilvl = item.item_level or 0

    explicit = item.mods[item.implicit_count:] if item.implicit_count else item.mods
    mods_out = []
    counts = {"priority": 0, "fit": 0, "generic": 0, "off_build": 0, "unmatched": 0}
    upgrade_criteria: list[str] = []

    for line in explicit:
        rel = classify_relevance(line, profile)
        match = craft.match_rolled_line(line, base_tags=base_tags, ilvl=ilvl)
        entry = {"text": line, "relevance": rel["bucket"], "why": rel["why"]}
        if match is None:
            entry["tier"] = None
            entry["note"] = "couldn't map to the craftable pool (unique/essence-only, " \
                            "hybrid, or ambiguous wording)"
            counts["unmatched"] += 1
        else:
            entry["tier"] = f"T{match['tier']} of {match['tier_count']}"
            entry["roll_pct"] = match["roll_pct"]
            entry["best_tier_at_ilvl"] = (
                f"T{match['best_tier_at_ilvl']}" if match["best_tier_at_ilvl"] else None
            )
            entry["at_best_tier_for_ilvl"] = match["at_best_for_ilvl"]
            entry["value_range"] = match["value_range"]
            # Weak on-build roll = relevant mod that is meaningfully below what this
            # item level already allows, or a poor roll within its tier. These are
            # the criteria for the NEXT item in the slot, not edits to this one.
            relevant = rel["bucket"] in ("priority", "fit")
            low_tier = (match["best_tier_at_ilvl"] is not None
                        and match["tier"] - match["best_tier_at_ilvl"] >= 2)
            low_roll = match["roll_pct"] is not None and match["roll_pct"] < 40
            if relevant and (low_tier or low_roll):
                reasons = []
                if low_tier:
                    reasons.append(f"only T{match['tier']} when T{match['best_tier_at_ilvl']} "
                                   "is reachable at this item level")
                if low_roll:
                    reasons.append(f"low roll ({match['roll_pct']}% of its tier)")
                upgrade_criteria.append(f"{line} — {'; '.join(reasons)}")
            counts[rel["bucket"]] += 1

        mods_out.append(entry)

    out = {
        "slot": item.slot,
        "name": item.name,
        "base_type": item.base_type,
        "rarity": item.rarity,
        "item_level": ilvl,
        "relevance_counts": counts,
        "mods": mods_out,
        "next_item_criteria": upgrade_criteria,
    }
    # Open affix slots only mean something on craftable rares/magics; a unique's
    # mods are fixed, so counting "open slots" on it would mislead.
    if (item.rarity or "").lower() in ("rare", "magic"):
        slots = _slot_accounting(item, craft)
        out["open_prefix"] = slots["open_prefix"]
        out["open_suffix"] = slots["open_suffix"]
    return out


def analyze_build_items(build, craft: CraftData, gems, priorities=None,
                        slot: str | None = None) -> dict:
    """Analyze how well every equipped item (or one `slot`) fits the build.

    Returns the derived build profile and a per-item breakdown. `priorities` is a
    list of stat keywords to force-count as on-build; `slot` restricts to one slot.
    """
    profile = derive_build_profile(build, gems, priorities)
    items = build.items
    if slot:
        sl = slot.lower()
        items = [it for it in items if sl in (it.slot or "").lower()]
        if not items:
            return {"error": f"No equipped item matches slot {slot!r}.",
                    "profile": profile}
    return {
        "profile": profile,
        "items": [analyze_item(it, craft, profile) for it in items],
        "caveats": [
            "Items are whole packages — you can't remove one mod off a rare. "
            "Off-build affixes are normal, not defects; weak rolls are criteria for "
            "the NEXT item in the slot, weighted by how realistic that upgrade is.",
            "The build profile is auto-derived (damage types from skills, defence "
            "and resist gaps from stats); pass `priorities` to augment it.",
            "Tier/roll data is from the vendored RePoE export and drifts per patch; "
            "unmatched mods are flagged, not guessed.",
        ],
    }
