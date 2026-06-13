from poe2_mcp.crafting.runes import RuneData, _candidate_classes


def test_candidate_classes_resolution():
    assert _candidate_classes("Gloves") == ["gloves", "armour"]
    assert _candidate_classes("Body Armour") == ["body armour", "armour"]
    assert _candidate_classes("Wand") == ["wand", "caster", "weapon"]
    assert _candidate_classes("Bow") == ["bow", "weapon"]
    assert _candidate_classes("Focus") == ["focus", "caster", "armour"]
    assert _candidate_classes("Amulet") == ["amulet", "talisman"]
    assert _candidate_classes("Ring") == ["ring"]   # no rune socket → no fallback


_DATA = RuneData({
    "Glacial Rune": {
        "armour": {"type": "Rune", "mods": ["+14% to Cold Resistance"],
                   "bonded": ["+20 to maximum Life"], "rank": 15},
        "weapon": {"type": "Rune", "mods": ["Adds 5 to 9 Cold Damage"], "rank": 15},
    },
    "Greater Glacial Rune": {
        "armour": {"type": "Rune", "mods": ["+18% to Cold Resistance"], "rank": 30},
    },
    "Body Rune": {
        "armour": {"type": "Rune", "mods": ["+20 to maximum Life"], "rank": 15},
    },
})


def test_grants_matches_and_ranks_by_tier():
    out = _DATA.grants("cold resistance", "Gloves")
    # both cold-res runes resolve via the armour fallback, higher rank first
    assert [r["rune"] for r in out] == ["Greater Glacial Rune", "Glacial Rune"]
    assert out[0]["grants"] == ["+18% to Cold Resistance"]
    assert out[1]["item_class"] == "armour"
    assert out[1]["bonded"] == ["+20 to maximum Life"]


def test_grants_picks_slot_specific_value():
    # a weapon gets the weapon line, not the armour resistance line
    out = _DATA.grants("cold", "Bow")
    assert out == [{"rune": "Glacial Rune", "type": "Rune", "item_class": "weapon",
                    "grants": ["Adds 5 to 9 Cold Damage"], "bonded": [], "rank": 15}]


def test_grants_all_words_must_match():
    assert _DATA.grants("maximum life", "Gloves")[0]["rune"] == "Body Rune"
    assert _DATA.grants("fire resistance", "Gloves") == []


def test_grants_empty_for_socketless_class():
    assert _DATA.grants("cold resistance", "Ring") == []


def test_grants_limit():
    assert len(_DATA.grants("cold resistance", "Gloves", limit=1)) == 1
