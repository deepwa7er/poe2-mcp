"""
Build-aware craft advice for a single equipped item.

Given an item and a target stat, work out whether the stat can roll on that base,
which tiers the item's level allows, how many prefix/suffix slots are already used,
and the lowest-risk way to add it — accounting for the fact that PoE2 crafting is
largely additive and random, so getting a new mod without sacrificing existing
ones is the actual constraint.

The advice is heuristic. Slot accounting depends on classifying the item's rolled
mods back to prefix/suffix from their wording; exotic or hybrid mods may not
classify, which lowers confidence (reported, not hidden). Essence/omen/currency
behaviour is game logic, not in the data, so methods are described in general terms.
"""

from __future__ import annotations

from .data import CraftData, MAX_AFFIXES
from .knowledge import acquisition_brief


def advise(item, target: str, craft: CraftData) -> dict:
    """Return structured craft advice for adding `target` to `item`.

    `item` is duck-typed: it needs rarity, base_type, item_level, mods (list of
    rolled lines, implicit-first) and implicit_count attributes — the shape of
    pob.models.Item / a get_items row.
    """
    rec = craft.resolve_base(item.base_type)
    if rec is None:
        return {
            "target": target,
            "error": f"Base type {item.base_type!r} isn't in the crafting data, so "
                     "the affix pool can't be resolved. (Magic items fold the base "
                     "into the name — this works best on Rare items.)",
            "acquisition": acquisition_brief(),
        }

    pool = craft.mods_for_base(item.base_type, keyword=target)
    target_groups = pool.get("groups", [])
    rune = craft.rune_hint(target)

    if not target_groups:
        out = {
            "base": rec["name"], "item_class": rec["cls"], "target": target,
            "can_roll": False,
            "summary": f"No rollable {target!r} affix exists for a {rec['name']} "
                       "(it may be implicit-only, unique-only, or essence/rune-only here).",
        }
        if rune:
            out["rune_option"] = (f"{rune} socketed into an open rune slot grants "
                                  f"{target} with no risk to existing mods.")
        out["acquisition"] = acquisition_brief()
        return out

    ilvl = item.item_level or 0
    target_types = {g["type"] for g in target_groups}
    target_gens = {g["gen"] for g in target_groups}

    # Per-group tier tables, flagging which tiers this item's level can roll.
    groups_out = []
    for g in target_groups:
        tiers = [
            {**t, "rollable_at_ilvl": t["lvl"] <= ilvl}
            for t in g["tiers"]
        ]
        best = max((t for t in tiers if t["rollable_at_ilvl"]), default=None,
                   key=lambda t: t["lvl"])
        groups_out.append({
            "type": g["type"], "gen": g["gen"], "spawn_weight": g["weight"],
            "best_tier_at_ilvl": best, "tiers": tiers,
        })

    slots = _slot_accounting(item, craft)
    present_types = slots.pop("_present_types")
    already_has = sorted(target_types & present_types)

    methods = _methods(
        craft, item, rec, ilvl, target, target_gens, target_types,
        present_types, already_has, slots, rune,
    )

    caveats = []
    if slots["unclassified"]:
        caveats.append(
            "Slot counts are inferred by matching rolled mods to the affix pool; "
            f"{slots['unclassified']} mod(s) couldn't be classified, so open-slot "
            "counts are approximate."
        )
    if slots["overflow"]:
        caveats.append(
            "Classified more prefixes or suffixes than the cap allows — a hybrid or "
            "exotic mod was likely miscategorised; treat the slot split as approximate "
            "(the item is clearly full, though)."
        )
    caveats.append("Affix pool drifts per patch; values are from the vendored "
                   "RePoE export, not live in-game.")

    return {
        "base": rec["name"], "item_class": rec["cls"], "item_level": ilvl,
        "rarity": item.rarity, "target": target, "can_roll": True,
        "target_affix_type": "/".join(sorted(target_gens)),
        "already_present": already_has,
        "slots": slots,
        "target_mods": groups_out,
        "methods": methods,
        "caveats": caveats,
        "acquisition": acquisition_brief(),
    }


def _slot_accounting(item, craft: CraftData) -> dict:
    """Count used/open prefix & suffix slots by classifying the item's explicit mods."""
    cap = MAX_AFFIXES.get((item.rarity or "").lower(), 3)
    explicit = item.mods[item.implicit_count:] if item.implicit_count else item.mods
    used = {"prefix": 0, "suffix": 0}
    unclassified = 0
    present_types: set[str] = set()
    for line in explicit:
        gen, typ = craft.classify_mod_line(line)
        if gen in used:
            used[gen] += 1
        else:
            unclassified += 1
        if typ:
            present_types.add(typ)
    return {
        "cap_per_type": cap,
        "used_prefix": used["prefix"],
        "used_suffix": used["suffix"],
        "open_prefix": max(cap - used["prefix"], 0),
        "open_suffix": max(cap - used["suffix"], 0),
        "explicit_total": len(explicit),
        "unclassified": unclassified,
        # More of one kind than the cap allows means a mod was miscategorised
        # (hybrid/exotic wording); slot counts are then only approximate.
        "overflow": used["prefix"] > cap or used["suffix"] > cap,
        "_present_types": present_types,
    }


def _exalt_odds(craft, base_type, gen, ilvl, present_types, target_types):
    """Approx chance an Exalted Orb (random add to an open slot) hits the target.

    Sums spawn weights of every `gen` mod group that is rollable at this item level
    and not already on the item; the target's share of that total is the estimate.
    Group-level weights are approximate (tiers can differ), hence 'approx'.
    """
    pool = craft.mods_for_base(base_type, kind=gen).get("groups", [])
    total = target = 0
    for g in pool:
        if g["type"] in present_types:
            continue
        if min(t["lvl"] for t in g["tiers"]) > ilvl:
            continue
        total += g["weight"]
        if g["type"] in target_types:
            target += g["weight"]
    if not total:
        return None
    return round(100 * target / total, 1)


def _methods(craft, item, rec, ilvl, target, target_gens, target_types,
             present_types, already_has, slots, rune) -> list[dict]:
    methods: list[dict] = []

    if already_has:
        methods.append({
            "method": "Divine Orb",
            "risk": "none",
            "detail": f"The item already has {', '.join(already_has)}. A Divine Orb "
                      "rerolls the numeric values of existing mods without changing "
                      "which mods are present — use it to push the roll higher. You "
                      "generally can't add a second mod from the same group.",
        })
        return methods

    open_for_target = any(slots[f"open_{g}"] > 0 for g in target_gens)
    gen_label = "/".join(sorted(target_gens))

    # Rune path — no risk to existing mods, surfaced first for stats a rune grants.
    if rune:
        methods.append({
            "method": f"{rune} in an open rune socket",
            "risk": "none",
            "detail": f"Socketing {rune} grants {target} without touching any rolled "
                      "mod — the cleanest fix if the item has a free rune socket. "
                      "(Socket availability isn't in the export; check the item.)",
        })

    if open_for_target:
        odds = _exalt_odds(craft, rec["name"], next(iter(target_gens)), ilvl,
                           present_types, target_types)
        odds_txt = f" Rough odds an Exalt hits {target}: ~{odds}% of open-{gen_label} outcomes." if odds is not None else ""
        side_omen = ("Omen of Sinistral Exaltation" if "prefix" in target_gens
                     else "Omen of Dextral Exaltation")
        methods.append({
            "method": "Exalted Orb (add to open slot)",
            "risk": "low",
            "detail": f"The item has a free {gen_label} slot, so adding a mod risks "
                      "nothing already on it (an Exalt only ADDS — it can't brick the "
                      f"item) — but it adds a RANDOM eligible mod, not necessarily "
                      f"{target}.{odds_txt} An {side_omen} forces the add onto the "
                      f"{gen_label} side, narrowing the pool but not picking the exact mod.",
        })
        methods.append({
            "method": "Essence on a fresh base (guaranteed)",
            "risk": "low",
            "detail": f"To GUARANTEE {target}, the targeted route is to rebuild: apply "
                      "the essence that grants this mod type to a clean base, then fill "
                      "the rest. You don't edit the finished item — you craft a new one. "
                      "Essence→mod mappings aren't in this dataset; verify in-game.",
        })
    else:
        methods.append({
            "method": f"Remove-and-add (Chaos Orb / Perfect Essence) — no open {gen_label} slot",
            "risk": "high",
            "detail": f"Every {gen_label} slot is used, so there's no room to add "
                      f"{target} without first removing a mod, and PoE2 has no targeted "
                      "single-mod swap. A Chaos Orb removes a RANDOM mod and adds a "
                      "RANDOM one; an Omen of Whittling (removes the lowest mod) or "
                      "Sinistral/Dextral Erasure (removes only a prefix/suffix) biases "
                      "WHICH side is hit but not the result. A Perfect Essence removes a "
                      "random mod and adds this one guaranteed. All can destroy a mod you "
                      "wanted to keep — the trap to avoid for a small gain.",
        })
        methods.append({
            "method": "Replace the item",
            "risk": "medium",
            "detail": f"Usually the realistic move: buy via trade, or craft a fresh "
                      f"{rec['name']} (essence-guarantee {target}, then Exalt/Regal the "
                      "rest) that rolls it alongside your other needed mods, rather than "
                      "risking the current one.",
        })

    return methods
