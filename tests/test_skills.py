from poe2_mcp.skills.gemdata import GemData
from poe2_mcp.skills.luaparse import parse_skills_lua

# Two skills in PoB2's Lua shape: a reservation buff and an attack that consumes
# charges. Includes nested skillTypes/levels braces and an escaped quote in a
# description to exercise the string-aware brace matcher and field unescaping.
LUA = r'''
skills["CombatFrenzyPlayer"] = {
	name = "Combat Frenzy",
	baseTypeName = "Combat Frenzy",
	color = 2,
	description = "While active, grants you a Frenzy Charge when you Freeze, Electrocute or Pin an enemy.",
	skillTypes = { [SkillType.OngoingSkill] = true, [SkillType.HasReservation] = true, [SkillType.Buff] = true, [SkillType.GeneratesCharges] = true, },
	castTime = 1,
	levels = {
		[1] = { levelRequirement = 0, spiritReservationFlat = 30, },
		[2] = { levelRequirement = 3, spiritReservationFlat = 30, },
	},
}
skills["FallingThunderPlayer"] = {
	name = "Falling Thunder",
	baseTypeName = "Falling Thunder",
	description = "Slam the ground, \"consuming\" Power Charges to fire Lightning projectiles.",
	skillTypes = { [SkillType.Attack] = true, [SkillType.Melee] = true, },
	castTime = 1,
	levels = { [1] = { levelRequirement = 1, }, },
}
skills["SupportFirePenetrationPlayer"] = {
	name = "Fire Penetration I",
	description = "Supports any skill that Hits enemies, making those Hits Penetrate enemy Fire resistance.",
	support = true,
	requireSkillTypes = { SkillType.Damage, SkillType.Attack, },
	addSkillTypes = { SkillType.Triggered, },
	excludeSkillTypes = { SkillType.InbuiltTrigger, },
	gemFamily = { "FirePenetration", },
	levels = { [1] = { levelRequirement = 0, manaMultiplier = 20, }, },
	statSets = { [1] = {
		constantStats = { { "base_reduce_enemy_fire_resistance_%", 30 }, },
		qualityStats = { { "number_of_chains", 0.1 }, },
	}, },
}
skills["SupportFirePenetrationPlayerTwo"] = {
	name = "Fire Penetration II",
	description = "Supports any skill that Hits enemies.",
	support = true,
	requireSkillTypes = { SkillType.Damage, },
	gemFamily = { "FirePenetration", },
	levels = { [1] = { levelRequirement = 0, manaMultiplier = 25, }, },
	statSets = { [1] = { constantStats = { { "base_reduce_enemy_fire_resistance_%", 40 }, }, }, },
}
'''


def test_parse_skills_lua_fields_and_braces():
    skills = parse_skills_lua(LUA)
    assert {"CombatFrenzyPlayer", "FallingThunderPlayer"} <= set(skills)

    cf = skills["CombatFrenzyPlayer"]
    assert cf["name"] == "Combat Frenzy"
    assert cf["spirit_reservation"] == 30
    assert "HasReservation" in cf["skill_types"]
    assert "GeneratesCharges" in cf["skill_types"]

    ft = skills["FallingThunderPlayer"]
    assert ft["spirit_reservation"] == 0
    assert "Attack" in ft["skill_types"]
    # Escaped quotes in the description are unescaped, and the matcher didn't stop early.
    assert '"consuming"' in ft["description"]
    # Active skills carry no support metadata.
    assert ft["is_support"] is False
    assert ft["stats"] == []


def test_parse_support_mechanics():
    skills = parse_skills_lua(LUA)
    fp = skills["SupportFirePenetrationPlayer"]
    assert fp["is_support"] is True
    assert fp["gem_family"] == ["FirePenetration"]
    assert fp["requires"] == ["Damage", "Attack"]
    assert fp["adds_skill_types"] == ["Triggered"]
    assert fp["excludes_skill_types"] == ["InbuiltTrigger"]
    assert fp["mana_multiplier"] == 20
    # The actual numeric effect — a support's real strength, not its level.
    assert {"id": "base_reduce_enemy_fire_resistance_%", "value": 30} in fp["stats"]
    # constantStats and qualityStats must not be conflated: the per-quality-point
    # number_of_chains belongs in quality_stats, never in stats.
    assert {"id": "number_of_chains", "value": 0.1} in fp["quality_stats"]
    assert all(s["id"] != "number_of_chains" for s in fp["stats"])


def _gem_data() -> GemData:
    return GemData(parse_skills_lua(LUA) | {
        # Charged Staff: a Buff that consumes charges but reserves nothing —
        # the case that must NOT be flagged as reserving Spirit.
        "ChargedStaffPlayer": {
            "name": "Charged Staff",
            "base_type": "Charged Staff",
            "description": "Consume all Power Charges to charge your Quarterstaff.",
            "skill_types": ["Buff", "Persistent"],
            "spirit_reservation": 0,
            "cast_time": 1,
        },
    })


def test_lookup_by_id_and_name():
    g = _gem_data()
    assert g.get("CombatFrenzyPlayer")["name"] == "Combat Frenzy"
    assert g.get("combat frenzy")["name"] == "Combat Frenzy"   # by display name
    assert g.get("Nonexistent Skill") is None


def test_lookup_strips_tier_numeral():
    g = _gem_data()
    # A bare name resolves to a tier ("Fire Penetration" → the lowest, I).
    assert g.get("Fire Penetration")["name"] == "Fire Penetration I"
    assert g.get("Fire Penetration II")["name"] == "Fire Penetration II"


def test_family_tiers():
    g = _gem_data()
    fp1 = g.get("Fire Penetration I")
    tiers = fp1["family_tiers"]
    # Lists the OTHER tier, with its numbers, and excludes itself.
    assert [t["name"] for t in tiers] == ["Fire Penetration II"]
    assert tiers[0]["stats"] == [{"id": "base_reduce_enemy_fire_resistance_%", "value": 40}]
    assert g.get("Falling Thunder")["family_tiers"] == []


def test_derived_flags():
    g = _gem_data()
    cf = g.get("Combat Frenzy")
    assert cf["reserves_spirit"] is True
    assert cf["generates_charges"] is True
    assert cf["consumes_power_charges"] is False

    ft = g.get("Falling Thunder")
    assert ft["consumes_power_charges"] is True
    assert ft["reserves_spirit"] is False

    # Buff/Persistent tags alone must not imply a Spirit reservation.
    cs = g.get("Charged Staff")
    assert cs["reserves_spirit"] is False
    assert cs["consumes_power_charges"] is True
