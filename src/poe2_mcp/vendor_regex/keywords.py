"""
Vendor-regex fragments and per-slot allowlists.

A *fragment* is a short case-insensitive regex snippet that, when found inside the
text the vendor screen shows for an item, identifies a useful mod. The vendor
search bar matches against the item's displayed text (name, base, and mod lines)
— so fragments are substrings of the in-game tooltip wording, not the templated
mod text from the export.

Fragments were chosen by running candidate strings against `data/poe2_crafting.json`
to confirm they hit the intended mods and avoid obvious collateral; tradeoffs are
called out per entry. Each one is a *fragment*, not a full regex — `build_regex`
joins them with `|`.

The per-slot allowlist (`SLOT_ALLOWED`) is a curated set of fragment keys that
make sense to surface for items in that slot. It prunes nonsense (movement speed
on a helmet, attack speed on a focus) without depending on the full affix pool
intersection — vendor regex is a coarse tool and a small static table is the right
level of fidelity.
"""

from __future__ import annotations

# fragment_key -> compact regex snippet (case-insensitive when compiled).
# Length matters: every char counts against the vendor search-bar budget (~50).
FRAGMENTS: dict[str, str] = {
    # Resistances
    "fire_res":      "Fire Res",
    "cold_res":      "Cold Res",
    "lightning_res": "Light.*Res",      # shorter than the literal word
    "chaos_res":     "Chaos Res",
    "all_res":       "all El",          # "+X% to all Elemental Resistances"
    "any_res":       "Res",             # broad catch-all when 3+ resists needed

    # Life / ES / Mana / Spirit
    "life":          "Life",            # matches +flat and %inc maximum life
    "es":            "Shield",          # "Energy Shield"; tighter than "Ene"
    "mana":          "Mana",
    "spirit":        "Spirit",

    # Damage scaling
    "phys_dmg":      "Phys.*Dam",
    "fire_dmg":      "Fire Dam",
    "cold_dmg":      "Cold Dam",
    "lightning_dmg": "Light.*Dam",
    "ele_dmg":       "lemental Dam",    # "added/increased Elemental Damage"
    "spell_dmg":     "Spell Dam",
    "minion":        "Minion",          # minion damage, life, level — broad

    # Speed / cast / crit
    "attack_speed":  "tta.*Sp",
    "cast_speed":    "ast.*Sp",
    "movement":      "Move",
    "crit_chance":   "rit.*Cha",        # "Critical Hit Chance"
    "crit_dmg":      "rit.*Bon",        # "Critical Damage Bonus"

    # Utility
    "accuracy":      "Accur",
    "strength":      "Stren",
    "dexterity":     "Dexter",
    "intelligence":  "Intel",
    "all_attrs":     "all Att",

    # Local defences (mostly armour pieces / shields)
    "armour_pct":    "d Arm",
    "evasion_pct":   "d Evas",
    "block":         "Block",
}

# Slot key -> set of fragment keys that can plausibly roll there.
# Slot keys are lower-cased and trimmed; see `slot_key()` for how raw slot
# strings ("Ring 1", "Body Armour", "Weapon 2") map onto them.
_DEFENSIVE: set[str] = {
    "life", "es", "mana",
    "fire_res", "cold_res", "lightning_res", "chaos_res", "any_res",
    "strength", "dexterity", "intelligence",
}

SLOT_ALLOWED: dict[str, set[str]] = {
    "helmet":      _DEFENSIVE | {"armour_pct", "evasion_pct", "accuracy"},
    "body armour": _DEFENSIVE | {"armour_pct", "evasion_pct", "spirit"},
    "gloves":      _DEFENSIVE | {"armour_pct", "evasion_pct",
                                 "attack_speed", "accuracy", "crit_chance",
                                 "phys_dmg", "fire_dmg", "cold_dmg",
                                 "lightning_dmg", "ele_dmg"},
    "boots":       _DEFENSIVE | {"armour_pct", "evasion_pct", "movement"},
    "belt":        _DEFENSIVE | {"all_attrs"},
    "amulet":      _DEFENSIVE | {"all_res", "all_attrs", "spirit",
                                 "crit_chance", "crit_dmg", "cast_speed",
                                 "minion", "spell_dmg", "ele_dmg",
                                 "fire_dmg", "cold_dmg", "lightning_dmg"},
    "ring":        _DEFENSIVE | {"all_res", "all_attrs",
                                 "fire_dmg", "cold_dmg", "lightning_dmg",
                                 "ele_dmg", "accuracy", "mana"},
    "weapon":      {"attack_speed", "cast_speed", "crit_chance", "crit_dmg",
                    "accuracy", "phys_dmg", "fire_dmg", "cold_dmg",
                    "lightning_dmg", "ele_dmg", "spell_dmg"},
    "shield":      _DEFENSIVE | {"armour_pct", "evasion_pct", "block", "spirit"},
    "focus":       _DEFENSIVE | {"spell_dmg", "cast_speed", "crit_chance",
                                 "crit_dmg", "spirit", "mana", "ele_dmg"},
    "quiver":      {"life", "mana", "accuracy", "attack_speed", "crit_chance",
                    "crit_dmg", "phys_dmg", "fire_dmg", "cold_dmg",
                    "lightning_dmg", "ele_dmg"},
}


def slot_key(raw: str) -> str | None:
    """Normalise an item slot ("Ring 1", "Body Armour", "Weapon 2") to a key.

    Returns None for unrecognised slots; the caller should treat that as "no
    per-slot filtering" rather than erroring, so unusual slots still produce
    some regex output.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    # Stable substring matches in a deterministic order.
    for k in ("body armour", "helmet", "gloves", "boots", "belt", "amulet",
             "ring", "weapon", "shield", "focus", "quiver"):
        if k in s:
            return k
    return None
