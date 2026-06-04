import re

from poe2_mcp.pob.models import Build, SkillGem, SocketGroup, Stat
from poe2_mcp.skills.gemdata import GemData
from poe2_mcp.vendor_regex import FRAGMENTS, build_regex, derive_priorities, slot_key
from poe2_mcp.vendor_regex.profile import Priority


def _build(stats: list[Stat], groups: list[SocketGroup] | None = None, level: int = 85) -> Build:
    return Build(
        class_name="Monk", ascendancy="Invoker", level=level,
        allocated_node_ids=[], items=[], socket_groups=groups or [],
        stats=stats,
    )


def _gems(tags: list[str], name: str = "TestSkill") -> GemData:
    return GemData({name: {"name": name, "skill_types": tags}}, {})


def _group(name: str, gems: GemData | None = None) -> SocketGroup:
    return SocketGroup(
        slot="Weapon 1",
        active_skill=name,
        gems=[SkillGem(name=name, level=20, quality=0, is_active=True, skill_id=name)],
    )


# -- fragments -----------------------------------------------------------------

def test_every_fragment_compiles_and_is_short_enough():
    """Each fragment must be a valid regex and short enough to be useful."""
    for key, frag in FRAGMENTS.items():
        re.compile(frag, re.IGNORECASE)
        assert len(frag) <= 16, f"{key} fragment {frag!r} is too long for vendor budget"


def test_resistance_fragments_match_intended_text():
    """Sanity: each elemental res fragment matches its mod-tooltip wording."""
    for el in ("Fire", "Cold", "Lightning"):
        rx = re.compile(FRAGMENTS[f"{el.lower()}_res"], re.IGNORECASE)
        assert rx.search(f"+12% to {el} Resistance")


# -- slot key normalisation ----------------------------------------------------

def test_slot_key_handles_pob_slots():
    assert slot_key("Body Armour") == "body armour"
    assert slot_key("Ring 1") == "ring"
    assert slot_key("Ring 2") == "ring"
    assert slot_key("Weapon 1") == "weapon"
    assert slot_key("") is None
    assert slot_key("Asteroid Belt") == "belt"  # substring match — ok for our use


# -- profile -------------------------------------------------------------------

def test_capped_resists_are_dropped():
    build = _build([
        Stat("FireResist", "75"), Stat("ColdResist", "40"), Stat("LightningResist", "-10"),
    ])
    keys = {p.key for p in derive_priorities(build, "Boots")}
    assert "fire_res" not in keys
    assert "cold_res" in keys
    assert "lightning_res" in keys


def test_three_uncapped_resists_compress_to_any_res():
    """If every element is uncapped, the broad 'Res' fragment is cheaper than three."""
    build = _build([
        Stat("FireResist", "20"), Stat("ColdResist", "20"), Stat("LightningResist", "20"),
    ])
    keys = {p.key for p in derive_priorities(build, "Boots")}
    assert "any_res" in keys
    assert "fire_res" not in keys
    assert "cold_res" not in keys
    assert "lightning_res" not in keys


def test_life_is_always_first_when_resists_capped():
    # With all resists at cap they're dropped; life is then the top priority.
    build = _build([
        Stat("Life", "3000"),
        Stat("FireResist", "75"), Stat("ColdResist", "75"), Stat("LightningResist", "75"),
    ])
    priorities = derive_priorities(build, "Body Armour")
    assert priorities[0].key == "life"


def test_movement_only_on_boots():
    build = _build([Stat("Life", "3000")])
    boots = {p.key for p in derive_priorities(build, "Boots")}
    helmet = {p.key for p in derive_priorities(build, "Helmet")}
    assert "movement" in boots
    assert "movement" not in helmet


def test_damage_tags_drive_damage_fragments():
    gems = _gems(["Spell", "Cold"])
    build = _build([Stat("Life", "3000")], groups=[_group("TestSkill")])
    keys = {p.key for p in derive_priorities(build, "Amulet", gems=gems)}
    assert "cold_dmg" in keys
    assert "cast_speed" in keys
    assert "spell_dmg" in keys


def test_attack_skill_gets_attack_speed_not_cast_speed():
    gems = _gems(["Attack", "Melee", "Physical"])
    build = _build([Stat("Life", "3000")], groups=[_group("TestSkill")])
    keys = {p.key for p in derive_priorities(build, "Gloves", gems=gems)}
    assert "attack_speed" in keys
    assert "cast_speed" not in keys


def test_slot_allowlist_drops_inapplicable_keys():
    """A pure spell build doesn't put spell damage on boots — boots can't roll it."""
    gems = _gems(["Spell", "Fire"])
    build = _build([Stat("Life", "3000")], groups=[_group("TestSkill")])
    keys = {p.key for p in derive_priorities(build, "Boots", gems=gems)}
    assert "spell_dmg" not in keys
    assert "cast_speed" not in keys


def test_include_bypasses_slot_allowlist():
    build = _build([Stat("Life", "3000")])
    keys = {p.key for p in derive_priorities(build, "Boots", include=["minion"])}
    assert "minion" in keys


def test_exclude_drops_after_derivation():
    # Fire/lightning capped so only cold is uncapped → no res-compression to any_res.
    build = _build([
        Stat("Life", "3000"),
        Stat("FireResist", "75"), Stat("LightningResist", "75"),
        Stat("ColdResist", "30"),
    ])
    keys = {p.key for p in derive_priorities(build, "Boots", exclude=["life"])}
    assert "life" not in keys
    assert "cold_res" in keys  # other derivations still happen


# -- compiler ------------------------------------------------------------------

def test_build_regex_packs_under_budget():
    pris = [
        Priority(key="life", weight=100, label="Life", reason=""),
        Priority(key="movement", weight=90, label="Move", reason=""),
        Priority(key="any_res", weight=80, label="Res", reason=""),
    ]
    regex, included, dropped = build_regex(pris, budget=50)
    assert len(regex) <= 50
    assert {s.priority.key for s in included} == {"life", "movement", "any_res"}
    assert not dropped


def test_build_regex_drops_lowest_weight_first_under_tight_budget():
    pris = [
        Priority(key="life",        weight=100, label="Life",   reason=""),
        Priority(key="lightning_res", weight=90, label="LRes",  reason=""),
        Priority(key="movement",    weight=10,  label="Move",   reason=""),
    ]
    # 4 (Life) + 1 (|) + 9 (Light.*Res) = 14; movement (4 more chars + 1 |) won't fit at 15.
    regex, included, dropped = build_regex(pris, budget=15)
    keys_in = [s.priority.key for s in included]
    keys_out = [d.priority.key for d in dropped]
    assert "life" in keys_in
    assert "lightning_res" in keys_in
    assert keys_out == ["movement"]


def test_build_regex_skips_keys_with_no_fragment():
    pris = [
        Priority(key="life", weight=100, label="Life", reason=""),
        Priority(key="bogus_key", weight=50, label="?", reason=""),
    ]
    regex, included, dropped = build_regex(pris, budget=50)
    assert regex == "Life"
    assert [d.priority.key for d in dropped] == ["bogus_key"]
    assert "no fragment" in dropped[0].reason


def test_build_regex_output_is_valid_regex():
    pris = [Priority(key=k, weight=10, label=k, reason="") for k in
            ("life", "any_res", "movement", "attack_speed")]
    regex, _, _ = build_regex(pris, budget=50)
    # Must compile, and must actually match an item line.
    rx = re.compile(regex, re.IGNORECASE)
    assert rx.search("+50 to maximum Life")
    assert rx.search("+8% to Cold Resistance")
    assert rx.search("15% increased Movement Speed")
    assert rx.search("9% increased Attack Speed")
