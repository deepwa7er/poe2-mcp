from types import SimpleNamespace

from poe2_mcp.crafting.data import CraftData
from poe2_mcp.crafting.item_fit import (
    analyze_build_items,
    classify_relevance,
    derive_build_profile,
)
from poe2_mcp.pob.models import Item


def _mod(type_, gen, name, lvl, text, sw):
    return {"id": f"{type_}{lvl}", "type": type_, "group": type_, "gen": gen,
            "name": name, "lvl": lvl, "text": text, "sw": sw}


_DEF = [["default", 1]]
# Three-tier life ladder, two-tier cold-res ladder, a gloves-only attack-speed mod,
# and a ring-excluded local mod (0 weight on ring before the default catch-all).
MODS = [
    _mod("IncreasedLife", "prefix", "Hale", 1, "+(10-19) to maximum Life", _DEF),
    _mod("IncreasedLife", "prefix", "Healthy", 16, "+(30-39) to maximum Life", _DEF),
    _mod("IncreasedLife", "prefix", "Robust", 54, "+(100-119) to maximum Life", _DEF),
    _mod("ColdResistance", "suffix", "of the Seal", 1, "+(6-10)% to Cold Resistance", _DEF),
    _mod("ColdResistance", "suffix", "of the Yeti", 38, "+(21-25)% to Cold Resistance", _DEF),
    _mod("AttackSpeed", "suffix", "of Skill", 1, "(8-10)% increased Attack Speed",
         [["gloves", 1], ["default", 0]]),
    _mod("LocalThorns", "prefix", "Barbed", 1, "(5-8) to (9-12) Physical Thorns damage",
         [["ring", 0], ["default", 1]]),
]
BASES = {
    "sapphire ring": {"name": "Sapphire Ring", "cls": "Ring", "tags": ["ring", "default"], "lvl": 1},
    "leather gloves": {"name": "Leather Gloves", "cls": "Gloves",
                       "tags": ["gloves", "armour", "default"], "lvl": 1},
}


def _cd() -> CraftData:
    return CraftData([dict(m) for m in MODS], {k: dict(v) for k, v in BASES.items()})


# -- match_rolled_line -------------------------------------------------------

def test_match_picks_tier_by_value_and_roll_pct():
    cd = _cd()
    m = cd.match_rolled_line("+35 to maximum Life", ilvl=80)
    assert m["type"] == "IncreasedLife"
    assert m["tier_count"] == 3
    assert m["tier"] == 2                       # middle tier (30-39), T1 = best
    assert m["roll_pct"] == 55.6               # (35-30)/(39-30)
    assert m["value_range"] == (30.0, 39.0)
    assert m["best_tier_at_ilvl"] == 1         # lvl-54 tier reachable at ilvl 80
    assert m["at_best_for_ilvl"] is False      # a better tier is reachable now


def test_match_best_tier_for_ilvl_when_capped_low():
    cd = _cd()
    # At ilvl 20 the top life tier (lvl 54) is out of reach, so the lvl-16 tier is
    # the best available and a +35 roll already sits on it.
    m = cd.match_rolled_line("+35 to maximum Life", ilvl=20)
    assert m["best_tier_at_ilvl"] == 2
    assert m["at_best_for_ilvl"] is True
    assert m["next_better_tier_lvl"] == 54     # the next tier up unlocks at ilvl 54


def test_match_value_above_top_tier_clamps():
    cd = _cd()
    m = cd.match_rolled_line("+200 to maximum Life", ilvl=80)
    assert m["tier"] == 1                       # snaps to the top tier
    assert m["roll_pct"] == 100.0              # clamped, not >100


def test_match_excludes_tiers_not_on_base():
    cd = _cd()
    # Local thorns has 0 weight on a ring, so it has no ladder there.
    assert cd.match_rolled_line("6 to 10 Physical Thorns damage",
                                base_tags={"ring", "default"}) is None
    # …but it matches on a base where it can roll.
    m = cd.match_rolled_line("6 to 10 Physical Thorns damage", base_tags={"default"})
    assert m["type"] == "LocalThorns"


def test_match_unclassifiable_returns_none():
    assert _cd().match_rolled_line("Grants Skill: Level 12 Firebolt") is None


# -- build profile -----------------------------------------------------------

def _build(stats: dict, skill_types):
    stat_objs = [SimpleNamespace(name=k, value=v) for k, v in stats.items()]
    gem = SimpleNamespace(is_active=True, enabled=True, skill_id="MainSkill", name="Firebolt")
    group = SimpleNamespace(enabled=True, active_skill="Firebolt", gems=[gem])
    items = []
    b = SimpleNamespace(stats=stat_objs, socket_groups=[group], items=items)
    gems = SimpleNamespace(get=lambda q: {"skill_types": skill_types})
    return b, gems


def test_profile_detects_es_caster_and_resist_gaps():
    b, gems = _build(
        {"Life": "1000", "EnergyShield": "3000",
         "FireResist": "60", "ColdResist": "75", "LightningResist": "58", "ChaosResist": "12"},
        ["Spell", "Fire", "Projectile"],
    )
    p = derive_build_profile(b, gems)
    assert p["defense"] == "energy shield"
    assert p["caster"] is True
    assert "fire" in p["elements"]
    assert p["resist_gaps"] == {"fire": 15.0, "lightning": 17.0, "chaos": 63.0}
    assert "cold" not in p["resist_gaps"]      # capped


# -- relevance classification ------------------------------------------------

def _profile(**over):
    base = {"defense": "energy shield", "caster": True,
            "dims": ["spell", "fire", "elemental", "generic", "projectile"],
            "elements": ["fire"], "resist_gaps": {"fire": 15.0}, "priorities": []}
    base.update(over)
    return base


def test_relevance_buckets():
    p = _profile()
    assert classify_relevance("+30% to Fire Resistance", p)["bucket"] == "priority"
    assert classify_relevance("+30% to Cold Resistance", p)["bucket"] == "generic"
    assert classify_relevance("+100 to maximum Energy Shield", p)["bucket"] == "fit"
    assert classify_relevance("120% increased Spell Damage", p)["bucket"] == "fit"
    assert classify_relevance("+50 to maximum Life", p)["bucket"] == "generic"
    assert classify_relevance("15% increased Attack Speed", p)["bucket"] == "off_build"
    assert classify_relevance("Adds 7 to 9 Physical Damage to Attacks", p)["bucket"] == "off_build"


def test_relevance_energy_shield_off_build_on_life_builds():
    p = _profile(defense="life")
    assert classify_relevance("+100 to maximum Energy Shield", p)["bucket"] == "off_build"


def test_relevance_priorities_override():
    p = _profile(priorities=["attack speed"])
    # A user-stated priority forces an otherwise off-build mod to count.
    assert classify_relevance("15% increased Attack Speed", p)["bucket"] == "fit"


# -- end-to-end analyze_item -------------------------------------------------

def test_analyze_flags_weak_on_build_roll_as_next_item_criteria():
    cd = _cd()
    b, gems = _build(
        {"Life": "1000", "EnergyShield": "3000", "ColdResist": "40"},
        ["Spell", "Cold"],
    )
    b.items = [Item(slot="Ring 1", rarity="Rare", name="Test Ring",
                    base_type="Sapphire Ring", item_level=80,
                    mods=["+12 to maximum Life", "+22% to Cold Resistance"],
                    implicit_count=0)]
    res = analyze_build_items(b, cd, gems)
    item = res["items"][0]
    assert item["open_prefix"] == 2 and item["open_suffix"] == 2   # rare slot accounting
    life = next(m for m in item["mods"] if "Life" in m["text"])
    assert life["tier"] == "T3 of 3"          # bottom life tier on an ilvl-80 ring
    # Cold res fills a gap (priority) and rolled poorly (22 of the 21-25 tier) →
    # surfaced as a criterion for the NEXT ring, never as an edit to this one.
    cold = next(m for m in item["mods"] if "Cold Resistance" in m["text"])
    assert cold["relevance"] == "priority" and cold["roll_pct"] == 25.0
    assert any("Cold Resistance" in c for c in item["next_item_criteria"])


def test_analyze_suppresses_open_slots_on_uniques():
    cd = _cd()
    b, gems = _build({"Life": "1000", "EnergyShield": "100"}, ["Spell", "Fire"])
    b.items = [Item(slot="Gloves", rarity="Unique", name="Doedre's Tenure",
                    base_type="Leather Gloves", item_level=67,
                    mods=["+50 to maximum Life"], implicit_count=0)]
    item = analyze_build_items(b, cd, gems)["items"][0]
    assert "open_prefix" not in item and "open_suffix" not in item
