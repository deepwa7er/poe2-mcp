"""
Derive a prioritised list of vendor-regex needs from a loaded build.

The profile answers "for THIS build, which mods should the vendor regex highlight?"
by combining three signals:

* defensive state — uncapped elemental resistances become high-priority; capped
  ones are dropped. Life is always-on unless the export is missing it.
* damage scaling — the active skill's tags from the gem database (Fire/Cold/Lightning/
  Physical, Attack vs Spell, Minion) drive which damage-type and speed mods matter.
* slot intent — boots get movement speed, weapons get attack/cast speed and
  weapon damage, etc.

The result is a list of `Priority(key, weight, label, reason)` items sorted by
weight descending. The compiler maps each key to a fragment via
`keywords.FRAGMENTS` and packs them under the character budget.

Heuristics are deliberately coarse. Vendor regex is a coarse tool, and a
slightly noisy regex is better than missing a useful base. The `label`/`reason`
fields are preserved on the output so the user can see why each fragment was
included.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..diagnostics import DEFAULT_MAX_RESIST
from ..pob.models import Build
from .keywords import FRAGMENTS, SLOT_ALLOWED, slot_key


@dataclass
class Priority:
    key: str        # fragment key (matches FRAGMENTS)
    weight: int     # higher = more important
    label: str      # short human label, e.g. "Cold Resistance"
    reason: str     # why included, surfaced to the user


def _collect_damage_tags(build: Build, gems) -> set[str]:
    """Lowercased skill_types of every enabled active skill, via the gem database.

    Tags like "Fire"/"Cold"/"Lightning"/"Physical"/"Attack"/"Spell"/"Minion" drive
    which damage-type and speed fragments are surfaced. Returns an empty set if
    the gem database isn't available — callers degrade gracefully.
    """
    tags: set[str] = set()
    if gems is None:
        return tags
    for group in build.socket_groups:
        if not group.enabled:
            continue
        for gem in group.gems:
            if not gem.is_active or not gem.enabled:
                continue
            data = gems.get(gem.skill_id or gem.name)
            if not data:
                continue
            for t in data.get("skill_types") or []:
                tags.add(t.lower())
    return tags


def _resist_priorities(build: Build) -> list[Priority]:
    """Per-element resistance priorities; capped resists are dropped.

    Weight rises with the gap below the cap so the biggest hole goes in first.
    Chaos resistance is included only when noticeably negative — chaos res is
    routinely negative in PoE2 and not always worth chasing on every slot.
    """
    out: list[Priority] = []
    for label, key, name, max_name in (
        ("Fire",      "fire_res",      "FireResist",      "FireResistMax"),
        ("Cold",      "cold_res",      "ColdResist",      "ColdResistMax"),
        ("Lightning", "lightning_res", "LightningResist", "LightningResistMax"),
    ):
        val = build.stat_float(name)
        cap = build.stat_float(max_name) or DEFAULT_MAX_RESIST
        if val is not None and val >= cap:
            continue  # already capped — skip
        gap = cap if val is None else (cap - val)
        out.append(Priority(
            key=key, weight=80 + int(gap), label=f"{label} Resistance",
            reason=(f"short {gap:g}% of {cap:g}% cap"
                    if val is not None else "not present in export"),
        ))
    chaos = build.stat_float("ChaosResist")
    if chaos is not None and chaos < -30:
        out.append(Priority(
            key="chaos_res", weight=55, label="Chaos Resistance",
            reason=f"chaos res at {chaos:g}%",
        ))
    return out


def _damage_priorities(tags: set[str]) -> list[Priority]:
    """Damage-type and speed fragments based on the build's active skill tags.

    Picks at most one elemental damage type (the first one the skill has — most
    builds focus on one), plus a spell/attack speed fragment matching the skill
    family. Minion builds get their own dedicated fragment because minion damage
    rolls under its own template, not the player's damage-type templates.
    """
    out: list[Priority] = []
    for elem, key in (("fire", "fire_dmg"), ("cold", "cold_dmg"),
                      ("lightning", "lightning_dmg")):
        if elem in tags:
            out.append(Priority(
                key=key, weight=70, label=f"{elem.title()} Damage",
                reason=f"active skill scales {elem} damage",
            ))
            break  # one elemental flavour is plenty
    if "physical" in tags and "fire" not in tags and "cold" not in tags and "lightning" not in tags:
        out.append(Priority(
            key="phys_dmg", weight=65, label="Physical Damage",
            reason="active skill scales physical damage",
        ))
    if "attack" in tags or "melee" in tags or "rangedattack" in tags:
        out.append(Priority(
            key="attack_speed", weight=60, label="Attack Speed",
            reason="attack-based skills scale with attack speed",
        ))
    if "spell" in tags:
        out.append(Priority(
            key="cast_speed", weight=60, label="Cast Speed",
            reason="spell-based skills scale with cast speed",
        ))
        out.append(Priority(
            key="spell_dmg", weight=55, label="Spell Damage",
            reason="spell-based skills scale with spell damage",
        ))
    if "minion" in tags:
        out.append(Priority(
            key="minion", weight=70, label="Minion mods",
            reason="active skill is a minion skill",
        ))
    return out


def _defensive_priorities(build: Build) -> list[Priority]:
    """Always-on defensive fragments. Life is core; ES is added for ES-leaning builds."""
    out: list[Priority] = []
    life = build.stat_float("Life") or 0
    es = build.stat_float("EnergyShield") or 0
    out.append(Priority(
        key="life", weight=100, label="Life",
        reason=f"current Life {life:g}",
    ))
    if es > 0 and es > life * 0.4:
        out.append(Priority(
            key="es", weight=85, label="Energy Shield",
            reason=f"ES {es:g} is a meaningful share of the pool",
        ))
    return out


def _slot_priorities(slot: str) -> list[Priority]:
    """Slot-intent fragments — movement on boots is the canonical example."""
    out: list[Priority] = []
    sk = slot_key(slot) or ""
    if sk == "boots":
        out.append(Priority(
            key="movement", weight=90, label="Movement Speed",
            reason="boots are the main movement-speed source",
        ))
    return out


def derive_priorities(
    build: Build,
    slot: str,
    gems=None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[Priority]:
    """Produce the prioritised need list for one item slot.

    `include` adds fragment keys at high weight (treated as user override —
    bypasses the slot allowlist so unusual asks like "match Fire damage on
    boots" still work). `exclude` drops keys after derivation. Unknown keys in
    either list are ignored silently — callers can re-check against
    FRAGMENTS if they need to surface typos.
    """
    sk = slot_key(slot)
    allowed = SLOT_ALLOWED.get(sk, set(FRAGMENTS.keys())) if sk else set(FRAGMENTS.keys())
    tags = _collect_damage_tags(build, gems)

    derived: list[Priority] = (
        _defensive_priorities(build)
        + _resist_priorities(build)
        + _damage_priorities(tags)
        + _slot_priorities(slot)
    )

    # Optional resistance compression: if 3 elements are uncapped, the broad "Res"
    # fragment is shorter than three "Fire/Cold/Lightning Res" entries combined.
    res_keys = {"fire_res", "cold_res", "lightning_res"}
    res_present = [p for p in derived if p.key in res_keys]
    if len(res_present) >= 3:
        derived = [p for p in derived if p.key not in res_keys]
        derived.append(Priority(
            key="any_res", weight=max(p.weight for p in res_present),
            label="Any Resistance",
            reason="3+ elements uncapped — broad 'Res' catches them all",
        ))

    # User overrides win.
    excluded = set(exclude or [])
    if excluded:
        derived = [p for p in derived if p.key not in excluded]
    for k in include or []:
        if k in FRAGMENTS and not any(p.key == k for p in derived):
            derived.append(Priority(
                key=k, weight=120, label=k.replace("_", " ").title(),
                reason="user-requested",
            ))
            allowed = allowed | {k}

    # Filter to slot, but keep user-includes (already added to `allowed`).
    derived = [p for p in derived if p.key in allowed]

    derived.sort(key=lambda p: -p.weight)
    return derived
