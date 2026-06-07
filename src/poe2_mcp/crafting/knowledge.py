"""
Durable model of how PoE2 item acquisition and crafting actually works.

This is "tool memory": the crafting tools return it on every call and a dedicated
MCP tool (how_crafting_works) exposes the full version, so any model reading the
output reasons about items the way PoE2 actually behaves instead of assuming
PoE1-style deterministic crafting.

The one hard truth a caller must internalise:

    You CANNOT drop one chosen modifier and add another chosen modifier. PoE2 has
    no Orb of Scouring, no crafting bench, and no metamods. Almost every currency
    adds or removes a RANDOM mod, is one-way, and can brick the item. "Targeted"
    crafting only ever means guaranteeing ONE mod (an essence) or biasing a
    CATEGORY — prefix / suffix / lowest (an omen). You never pick the exact
    before-and-after pair.

Because of that, craft advice must be framed as expected cost and brick risk —
"the realistic way to end up with this mod" — not as a deterministic edit.

Patch-sensitive: written for 0.5 (Runes of Aldur). Recombinators were removed in
0.5. Affix pools, essence/omen rosters, and currency behaviour shift per patch —
verify against the live game before quoting specifics.
"""

from __future__ import annotations

PATCH = "0.5 (Runes of Aldur)"

CORE_PRINCIPLE = (
    "PoE2 has no way to drop one chosen mod and add another chosen mod. There is "
    "no Orb of Scouring, no crafting bench, and no metamods. Almost every currency "
    "adds or removes a RANDOM modifier, is one-way, and can brick the item. "
    "'Targeted' crafting only ever means guaranteeing ONE mod (an essence) or "
    "biasing a CATEGORY — prefix / suffix / lowest (an omen). You never pick the "
    "exact before-and-after pair, so advice is about expected cost and brick risk, "
    "not a deterministic edit. The realistic move for a specific mod is usually to "
    "rebuild a fresh base or buy the item, not to surgically alter a finished one."
)

# Each currency: what it does, whether the outcome is random / a reroll / targeted,
# and the risk it poses to mods already on the item.
CURRENCIES = [
    {"name": "Orb of Transmutation", "mode": "random",
     "effect": "Normal -> Magic, adds 1 random mod"},
    {"name": "Orb of Augmentation", "mode": "random",
     "effect": "adds 1 random mod to a Magic item (Magic caps at 1 prefix + 1 suffix)"},
    {"name": "Regal Orb", "mode": "random",
     "effect": "Magic -> Rare, keeps existing mods and adds 1 random mod"},
    {"name": "Orb of Alchemy", "mode": "random",
     "effect": "Normal -> Rare with 4 random mods"},
    {"name": "Exalted Orb", "mode": "random",
     "effect": "adds 1 random mod to a Rare that has an open slot",
     "risk": "none to existing mods — it only ADDS, so it can't brick a good item; "
             "which mod you get is random"},
    {"name": "Chaos Orb", "mode": "random",
     "effect": "removes 1 RANDOM mod and adds 1 RANDOM mod (not the PoE1 full reroll)",
     "risk": "high — can destroy the very mod you wanted to keep"},
    {"name": "Orb of Annulment", "mode": "random",
     "effect": "removes 1 RANDOM mod",
     "risk": "high — you don't choose what is removed"},
    {"name": "Divine Orb", "mode": "reroll",
     "effect": "rerolls the numeric VALUES of existing mods; never changes which "
               "mods are present",
     "risk": "none — the safe way to push an existing roll higher"},
    {"name": "Vaal Orb", "mode": "random",
     "effect": "corrupts: one unpredictable change, after which the item can no "
               "longer be modified normally",
     "risk": "very high — permanent, can brick"},
    {"name": "Orb of Chance", "mode": "random",
     "effect": "Normal base -> maybe Unique, or destroys the item",
     "risk": "very high"},
]

# The only levers that let you influence WHICH mod you get.
TARGETED_TOOLS = [
    {"tool": "Essence (Lesser / Greater)", "kind": "guarantee one mod",
     "effect": "applied to a Normal/Magic item, upgrades its rarity and GUARANTEES "
               "one specific mod type; the rest of the item is still random",
     "use": "the standard way to lock in ONE wanted mod — start from a clean base, "
            "not from your finished item"},
    {"tool": "Perfect Essence", "kind": "guaranteed add, random remove",
     "effect": "removes a RANDOM existing mod from a Rare and adds the essence's "
               "guaranteed mod",
     "use": "the closest thing to a swap — but you don't choose WHICH mod it removes"},
    {"tool": "Rune / Soul Core (socketed via Artificer's Orb)", "kind": "no-risk add",
     "effect": "grants a fixed mod from an open socket with ZERO risk to rolled mods",
     "use": "the cleanest targeted add — but limited to what runes offer (mostly "
            "resistances, flat damage, life/mana) and to the item's open sockets"},
    {"tool": "Omens (from Ritual)", "kind": "bias a category",
     "effect": "change HOW the next currency behaves — see omens",
     "use": "turn a random add/remove into a category-targeted one (prefix vs "
            "suffix, or the lowest mod), never an exact-mod pick"},
]

# Omens bias the next matching currency. They target a CATEGORY, not a specific mod.
OMENS = [
    {"omen": "Omen of Whittling", "effect": "next Chaos Orb removes the lowest-level modifier"},
    {"omen": "Omen of Sinistral Erasure", "effect": "next Chaos Orb removes only a PREFIX"},
    {"omen": "Omen of Dextral Erasure", "effect": "next Chaos Orb removes only a SUFFIX"},
    {"omen": "Omen of Sinistral Exaltation", "effect": "next Exalted Orb adds only a PREFIX"},
    {"omen": "Omen of Dextral Exaltation", "effect": "next Exalted Orb adds only a SUFFIX"},
    {"omen": "Omen of Greater Exaltation", "effect": "next Exalted Orb adds two random mods"},
    {"omen": "Omen of Sinistral / Dextral Annulment",
     "effect": "next Orb of Annulment removes only a prefix / only a suffix"},
    {"omen": "Omen of Greater Annulment", "effect": "next Orb of Annulment removes two mods"},
]

# Ranked, practical routes to actually end up with a wanted mod — safest first.
ROUTES_TO_ADD_A_MOD = [
    "Rune grants it AND the item has an open socket -> socket the rune. No risk.",
    "Item has an open prefix/suffix slot -> Exalt into it (optionally an Omen of "
    "Sinistral/Dextral Exaltation to force the right side). Only adds, never bricks "
    "— but which mod you land is random.",
    "Need the mod guaranteed -> craft a FRESH base with the matching essence, then "
    "fill the rest. You rebuild the item; you do not edit the finished one.",
    "Finished Rare, no open slot -> there is no clean targeted route. Perfect "
    "Essence (random removal + guaranteed add) or Chaos + Omen of Whittling/Erasure "
    "are gambles that can destroy good mods.",
    "Often cheapest and safest -> BUY an item that already has the combination via "
    "trade rather than crafting it yourself.",
]

CAVEATS = [
    "No Orb of Scouring exists — you cannot reset an item to re-roll it from scratch.",
    "Magic items cap at 1 prefix + 1 suffix; Rares at 3 prefixes + 3 suffixes.",
    "You cannot have two mods from the same mod group on one item (e.g. two "
    "'increased Spell Damage' lines).",
    "Higher mod tiers need higher item level; a low-ilvl base cannot roll the top "
    "tiers even with the right currency.",
    f"Patch-sensitive: reflects {PATCH}. Recombinators were removed in 0.5. Verify "
    "against the live patch before quoting specifics.",
]


def acquisition_model() -> dict:
    """The full durable model — currencies, targeted tools, omens, routes, caveats."""
    return {
        "patch": PATCH,
        "core_principle": CORE_PRINCIPLE,
        "currencies": CURRENCIES,
        "targeted_tools": TARGETED_TOOLS,
        "omens": OMENS,
        "routes_to_add_a_mod": ROUTES_TO_ADD_A_MOD,
        "caveats": CAVEATS,
    }


def acquisition_brief() -> dict:
    """Compact ride-along for tool outputs: the principle + the ranked routes.

    Kept small so it can travel on every craft_advisor response without bloating
    it; the full model is one how_crafting_works call away.
    """
    return {
        "core_principle": CORE_PRINCIPLE,
        "routes_to_add_a_mod": ROUTES_TO_ADD_A_MOD,
        "patch": PATCH,
        "full_model": "call how_crafting_works for currencies, omens, and caveats",
    }
