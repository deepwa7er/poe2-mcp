from poe2_mcp.crafting.data import CraftData, _pattern_for
from poe2_mcp.crafting.advisor import advise
from poe2_mcp.pob.models import Item


def _mod(type_, gen, name, lvl, text, sw):
    return {"id": f"{type_}{lvl}", "type": type_, "group": type_, "gen": gen,
            "name": name, "lvl": lvl, "text": text, "sw": sw}


# A compact pool: cold-res suffix (two tiers), life prefix, an attack-speed suffix,
# and a local mod that a 0-weight on "ring" must exclude even though "default" is 1.
_ARMOUR_RING = [["armour", 1], ["ring", 1], ["default", 0]]
MODS = [
    _mod("ColdResistance", "suffix", "of the Seal", 1, "+(6-10)% to Cold Resistance", _ARMOUR_RING),
    _mod("ColdResistance", "suffix", "of the Yeti", 38, "+(21-25)% to Cold Resistance", _ARMOUR_RING),
    _mod("IncreasedLife", "prefix", "Hale", 1, "+(10-19) to maximum Life",
         [["body_armour", 1], ["ring", 1], ["default", 0]]),
    _mod("AttackSpeed", "suffix", "of Skill", 1, "(8-10)% increased Attack Speed",
         [["gloves", 1], ["default", 0]]),
    # Excluded on rings: ring weight 0 comes before the default catch-all of 1.
    _mod("LocalArmour", "prefix", "Plated", 1, "+(10-20) to Armour",
         [["ring", 0], ["armour", 1], ["default", 1]]),
]
BASES = {
    "sapphire ring": {"name": "Sapphire Ring", "cls": "Ring", "tags": ["ring", "default"], "lvl": 1},
    "leather gloves": {"name": "Leather Gloves", "cls": "Gloves",
                       "tags": ["gloves", "armour", "default"], "lvl": 1},
}


def _cd() -> CraftData:
    return CraftData([dict(m) for m in MODS], {k: dict(v) for k, v in BASES.items()})


# -- pattern / classification ------------------------------------------------

def test_pattern_matches_rolled_values_and_spacing():
    pat = _pattern_for("+(6-10)% to Cold Resistance")
    import re
    assert re.match(pat, "+38% to Cold Resistance", re.I)
    assert re.match(pat, "+8%  to  Cold Resistance", re.I)  # flexible whitespace
    assert not re.match(pat, "+38% to Fire Resistance", re.I)


def test_classify_mod_line():
    cd = _cd()
    assert cd.classify_mod_line("+38% to Cold Resistance") == ("suffix", "ColdResistance")
    assert cd.classify_mod_line("+45 to maximum Life") == ("prefix", "IncreasedLife")
    assert cd.classify_mod_line("Totally unknown mod") == (None, None)


def test_classify_ambiguous_returns_none():
    # Same wording rolling as both prefix and suffix can't be classified confidently.
    mods = [
        _mod("DmgA", "prefix", "a", 1, "(10-20)% increased Damage", [["default", 1]]),
        _mod("DmgB", "suffix", "b", 1, "(10-20)% increased Damage", [["default", 1]]),
    ]
    cd = CraftData(mods, {})
    assert cd.classify_mod_line("15% increased Damage") == (None, None)


# -- spawn-weight semantics --------------------------------------------------

def test_weight_for_base_first_match_wins():
    cd = _cd()
    local = next(m for m in cd.mods if m["type"] == "LocalArmour")
    # Ring: the 0 on "ring" precedes the catch-all default(1), so it's excluded.
    assert cd.weight_for_base(local, {"ring", "default"}) == 0
    # Plain armour (no ring tag): "armour" matches at weight 1.
    assert cd.weight_for_base(local, {"armour", "default"}) == 1


def test_resolve_base_exact_and_substring():
    cd = _cd()
    assert cd.resolve_base("Sapphire Ring")["name"] == "Sapphire Ring"
    # Magic item folds the base into the name → substring fallback still resolves it.
    assert cd.resolve_base("Hale Sapphire Ring of the Yeti")["name"] == "Sapphire Ring"
    assert cd.resolve_base("Nonexistent Base") is None


# -- mods_for_base -----------------------------------------------------------

def test_mods_for_base_filters_and_tiers():
    cd = _cd()
    res = cd.mods_for_base("Sapphire Ring")
    types = {g["type"] for g in res["groups"]}
    assert "ColdResistance" in types and "IncreasedLife" in types
    assert "AttackSpeed" not in types   # gloves-only
    assert "LocalArmour" not in types   # excluded by 0 weight on ring

    cold = next(g for g in res["groups"] if g["type"] == "ColdResistance")
    assert cold["gen"] == "suffix"
    assert [t["lvl"] for t in cold["tiers"]] == [1, 38]  # sorted ascending

    suff = cd.mods_for_base("Sapphire Ring", kind="suffix")
    assert all(g["gen"] == "suffix" for g in suff["groups"])

    kw = cd.mods_for_base("Sapphire Ring", keyword="cold")
    assert {g["type"] for g in kw["groups"]} == {"ColdResistance"}


def test_mods_for_base_unknown():
    assert "error" in _cd().mods_for_base("Some Unknown Base")


# -- advisor -----------------------------------------------------------------

def _item(base, mods, ilvl=80, rarity="Rare", implicit_count=0):
    return Item(slot="x", rarity=rarity, name="n", base_type=base,
                item_level=ilvl, mods=mods, implicit_count=implicit_count)


def test_advise_already_present_suggests_divine():
    cd = _cd()
    it = _item("Sapphire Ring", ["+12% to Cold Resistance", "+50 to maximum Life"])
    r = advise(it, "cold resistance", cd)
    assert r["can_roll"] is True
    assert "ColdResistance" in r["already_present"]
    assert r["methods"][0]["method"] == "Divine Orb"


def test_advise_open_slot_recommends_add():
    cd = _cd()
    # One suffix used (none cold) → an open suffix slot for cold res.
    it = _item("Sapphire Ring", ["+50 to maximum Life", "10% increased Attack Speed"])
    r = advise(it, "cold resistance", cd)
    assert r["slots"]["open_suffix"] >= 1
    methods = [m["method"] for m in r["methods"]]
    assert any("Exalted Orb" in m for m in methods)
    # Glacial Rune is a tracked cold-res rune, surfaced as a no-risk option.
    assert any("Glacial Rune" in m for m in methods)


def test_advise_full_item_warns_remove_or_replace():
    cd = _cd()
    # Three suffixes, none cold → no open suffix; cold res needs removal/replace.
    it = _item("Leather Gloves",
               ["10% increased Attack Speed", "+8% to Cold Resistance"], rarity="Rare")
    # Force "full": give it three classified suffixes by stacking attack speed lines
    it.mods = ["10% increased Attack Speed", "9% increased Attack Speed",
               "8% increased Attack Speed", "+100 to maximum Life"]
    r = advise(it, "cold resistance", cd)
    assert r["slots"]["open_suffix"] == 0
    risks = {m["risk"] for m in r["methods"]}
    assert "high" in risks  # remove-and-add flagged as risky


def test_advise_tier_gated_by_item_level():
    cd = _cd()
    it = _item("Sapphire Ring", ["+50 to maximum Life"], ilvl=20)
    r = advise(it, "cold resistance", cd)
    cold = r["target_mods"][0]
    by_name = {t["name"]: t["rollable_at_ilvl"] for t in cold["tiers"]}
    assert by_name["of the Seal"] is True      # lvl 1
    assert by_name["of the Yeti"] is False     # lvl 38 > ilvl 20


def test_advise_cannot_roll_here():
    cd = _cd()
    # Attack speed can't roll on a ring in this pool.
    it = _item("Sapphire Ring", ["+50 to maximum Life"])
    r = advise(it, "attack speed", cd)
    assert r["can_roll"] is False
