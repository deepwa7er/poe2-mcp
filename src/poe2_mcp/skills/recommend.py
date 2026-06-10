"""
Build-aware support-gem classification and recommendation.

This is the scoring layer between the raw gem database (gemdata.GemData) and the
recommend_supports / get_skills / discover_skills tools: given a skill's tags and
a build's config, bucket every compatible support by what it actually does
(penetration / unconditional more / conditional / utility) and decide whether its
payload applies to this skill at all.

Pure functions over GemData + domain models — no MCP, no globals — so the
heuristics are unit-testable in isolation (see tests/test_skills.py).
"""

from __future__ import annotations

from .gemdata import GemData

# Damage-type tokens that can appear in a support's "..._+%_final" stat id, mapped
# to the skill dimension that must be present for the multiplier to actually apply.
# A fire spell scales 'spell'/'area'/'elemental'/'fire'/generic, so a Brutality
# ("physical_damage_+%_final") does nothing on it — that is what makes this build-aware.
DAMAGE_TOKENS = ("spell", "attack", "melee", "projectile", "area",
                 "fire", "cold", "lightning", "physical", "chaos", "elemental",
                 "minion", "over_time")
# Damage-scope tags a support can require; if the skill has none of these but the
# support requires one, its "damage" is scoped to a domain this skill doesn't use
# (e.g. Hourglass requires DamageOverTime — useless on a pure-hit spell).
SCOPE_TAGS = {"DamageOverTime", "DegenOnlySpellDamage", "Minion"}
# Ailment tokens → the element that must be dealt for the ailment to land at all.
AILMENT_ELEMENT = {
    "ignit": "fire", "scorch": "fire", "burn": "fire",
    "freeze": "cold", "chill": "cold",
    "shock": "lightning",
    "bleed": "physical", "bleeding": "physical",
    "poison": "chaos",
}
RESIST_KEYS = {"fire": "enemyFireResist", "cold": "enemyColdResist",
               "lightning": "enemyLightningResist", "chaos": "enemyChaosResist"}


def skill_damage_dims(tags: set[str]) -> set[str]:
    """The damage dimensions a skill scales, derived from its skill_types — used to
    decide which '..._+%_final' multipliers actually do anything for it."""
    dims = {"generic"}  # plain damage / hit_damage / all_damage always apply
    for t in ("Spell", "Attack", "Melee", "Projectile", "Area"):
        if t in tags:
            dims.add(t.lower())
    for el in ("Fire", "Cold", "Lightning"):
        if el in tags:
            dims.add(el.lower())
            dims.add("elemental")
    if "Physical" in tags:
        dims.add("physical")
    if "Chaos" in tags:
        dims.add("chaos")
    if "Minion" in tags:
        dims.add("minion")
    if {"DamageOverTime", "DegenOnlySpellDamage"} & tags:
        dims.add("over_time")
    return dims


def classify_support(gem: dict, dims: set[str], elements: set[str], tags: set[str]) -> dict:
    """Bucket a support and score it for a skill with the given damage dims/elements.

    Returns {bucket, score, applicable, key_stats, note}. Buckets:
      penetration  — base_reduce_enemy_*_resistance_% (matched to an element dealt)
      generic_more — an unconditional '..._+%_final' to damage the skill deals
      conditional  — a '_final' gated on an ailment/stun/low-life/charge/etc.
      utility      — AoE, duration, speed, or no damage payload
    """
    stats = gem.get("stats") or []
    key_stats = [(s["id"], s["value"]) for s in stats
                 if s["id"].endswith("_final")
                 or ("resistance" in s["id"] and ("reduce_enemy" in s["id"] or "ignore" in s["id"]))]

    # Penetration: resistance reduction OR outright ignore, matched to an element
    # the skill deals. An "ignore" flag (value True) zeroes the resistance entirely,
    # so it scores above any percentage reduction.
    for s in stats:
        sid = s["id"]
        is_reduce = "reduce_enemy" in sid and "resistance" in sid
        is_ignore = "ignore" in sid and "resistance" in sid
        if is_reduce or is_ignore:
            el = next((e for e in ("fire", "cold", "lightning", "chaos") if e in sid), None)
            applicable = el in elements if el else False
            if is_ignore:
                score, kind = 999.0, f"hits IGNORE enemy {el} resistance entirely"
            else:
                score, kind = float(s["value"]), f"penetrates enemy {el} resistance"
            note = kind if applicable else f"{el} penetration — this skill deals no {el} damage"
            return {"bucket": "penetration", "score": score,
                    "applicable": applicable, "key_stats": key_stats, "note": note}

    best = None  # (score, note, applicable, bucket) for the strongest damage payload
    for s in stats:
        sid, val = s["id"], s["value"]
        if not sid.endswith("_final"):
            continue
        ail = next((a for a in AILMENT_ELEMENT if a in sid), None)

        if ail and any(k in sid for k in ("damage", "effect", "magnitude",
                                          "chance", "multiplier")):
            # An ailment payload (chance/effect/magnitude). Only pays out if the
            # skill deals the matching element AND you scale that ailment.
            el = AILMENT_ELEMENT[ail]
            applicable = el in elements
            note = (f"only adds damage if you scale {ail.rstrip('e')} ({el}) ailments"
                    if applicable else f"{ail}-based — this skill deals no {el} damage")
            cand = (float(val), note, applicable, "conditional")
        elif "damage" not in sid:
            # speed / AoE / duration / knockback / armour-break — not a hit-damage
            # multiplier; let it fall through to the utility bucket.
            continue
        elif any(k in sid for k in ("stun", "low_life", "full_life", "broken_armour",
                                    "consume", "charge", "enrag", "rage", "pin",
                                    "executioner", "ruthless", "critical", "fully_broken")):
            cand = (float(val), "situational — needs the gated condition met",
                    False, "conditional")
        else:
            toks = [t for t in DAMAGE_TOKENS if t in sid]
            if toks:  # typed multiplier — applies only if the skill deals that type
                applicable = any(t in dims for t in toks)
                note = ("more " + "/".join(toks) + " damage" if applicable
                        else "/".join(toks) + " — not a damage type this skill deals")
            else:  # untyped "damage" — applies unless the support is scoped to a
                # domain (DoT/minion) the skill doesn't use, per its `requires`.
                scope = SCOPE_TAGS & set(gem.get("requires") or [])
                if scope and not (scope & tags):
                    applicable = False
                    note = f"{'/'.join(sorted(scope))}-scoped — not a hit-damage multiplier here"
                else:
                    applicable, note = True, "more damage"
            cand = (float(val), note, applicable, "generic_more")

        if best is None or cand[0] > best[0]:
            best = cand

    if best is None:
        return {"bucket": "utility", "score": 0.0, "applicable": True,
                "key_stats": key_stats, "note": "AoE / duration / speed — no hit-damage payload"}
    score, note, applicable, bucket = best
    # A "more" whose only damage final is a downside (e.g. -35% for movement) isn't
    # a damage support — file it under utility so it doesn't top the generic bucket.
    if bucket == "generic_more" and score <= 0:
        bucket, note = "utility", "no positive damage multiplier — " + note
    return {"bucket": bucket, "score": score, "applicable": applicable,
            "key_stats": key_stats, "note": note}


def recommend_for_group(gems: GemData | None, build, group,
                        include_inapplicable: bool = False) -> dict | None:
    """Bucketed support recommendations for an already-resolved socket group, or None
    if the gem database is absent or the group's active gem isn't in it. Shared by
    recommend_supports (full output) and get_skills (a short hint per group)."""
    if gems is None:
        return None
    active = next((g for g in group.gems if g.is_active), None)
    if active is None:
        return None
    info = gems.get(active.skill_id or active.name)
    if info is None:
        return None

    tags = set(info.get("skill_types") or [])
    dims = skill_damage_dims(tags)
    elements = {e for e in ("fire", "cold", "lightning", "chaos") if e in dims}
    equipped = {g.name.lower() for g in group.gems if not g.is_active}
    enemy_cfg = (build.config or {}).get("placeholders", {})

    # Collapse a support family to its best (highest-score) tier so we suggest the
    # upgrade target once, not "Fire Penetration I" and "II" as separate lines.
    by_family: dict[str, dict] = {}
    singles: list[dict] = []
    for gem in gems.supports_for(tags):
        cls = classify_support(gem, dims, elements, tags)
        entry = {
            "name": gem["name"],
            "score": cls["score"],
            "bucket": cls["bucket"],
            "applicable": cls["applicable"],
            "mana_multiplier": gem.get("mana_multiplier"),
            "key_stats": cls["key_stats"],
            "note": cls["note"],
            "already_equipped": gem["name"].lower() in equipped,
        }
        if cls["bucket"] == "penetration" and cls["applicable"]:
            el = next((e for e in elements if e in str(cls["key_stats"])), None)
            res = enemy_cfg.get(RESIST_KEYS.get(el, ""))
            if res is not None:
                entry["note"] += f" (enemy at {res}% in this build's Config)"
        fams = gem.get("gem_family") or []
        if fams:
            key = fams[0]
            cur = by_family.get(key)
            if cur is None or entry["score"] > cur["score"]:
                if cur is not None:
                    entry["tier_of"] = key
                by_family[key] = entry
        else:
            singles.append(entry)

    rows = list(by_family.values()) + singles
    buckets: dict[str, list[dict]] = {
        "penetration": [], "generic_more": [], "conditional": [], "utility": []}
    for r in rows:
        if not r["applicable"] and not include_inapplicable:
            continue
        buckets[r["bucket"]].append(r)
    for b in buckets.values():
        b.sort(key=lambda r: (r["already_equipped"], -r["score"]))

    return {
        "skill": group.active_skill,
        "skill_types": sorted(tags),
        "scales": sorted(dims),
        "equipped_supports": sorted(equipped),
        "open_slots_hint": "PoE2 skills take up to 5 supports; compare against equipped_supports",
        "buckets": buckets,
        "note": "Compare by `note`/`key_stats`, not raw `score`: a conditional bucket's "
                "large number only pays out if the build scales that ailment/condition. "
                "Set include_inapplicable=true to see gems that do nothing here. "
                "Supports trade clear for single-target — e.g. Concentrated Area boosts "
                "single-target but shrinks clear AoE. Note that tradeoff when recommending: "
                "don't push a single-target support without flagging its clear cost, or a "
                "clear/AoE support without flagging weaker bossing.",
    }


def top_support_hint(rec: dict, limit: int = 3) -> list[str]:
    """A short 'why' list of the strongest *not-yet-socketed* damage supports — the
    penetration and generic_more buckets only — for inline display in get_skills."""
    picks = [r for b in ("penetration", "generic_more")
             for r in rec["buckets"][b] if not r["already_equipped"]]
    picks.sort(key=lambda r: (r["bucket"] != "penetration", -r["score"]))
    return [f"{r['name']} — {r['note']}" for r in picks[:limit]]


def derive_skill_tags(skill_types) -> list[str]:
    """Reduce a skill's full skill_types to the discovery-relevant subset: its damage
    element(s) plus its delivery (Spell/Attack). Using every tag would over-constrain
    a match=all search (few skills are Fire AND Projectile AND Area AND Duration); the
    element + delivery is the pool that reuses the build's existing damage scaling."""
    tags = set(skill_types or [])
    out = [el for el in ("Fire", "Cold", "Lightning", "Chaos", "Physical") if el in tags]
    delivery = "Spell" if "Spell" in tags else ("Attack" if "Attack" in tags else None)
    if delivery:
        out.append(delivery)
    return out
