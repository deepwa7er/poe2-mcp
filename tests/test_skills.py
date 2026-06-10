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
	description = "Supports any skill that Hits enemies, making those Hits ignore enemy Fire resistance.",
	support = true,
	requireSkillTypes = { SkillType.Damage, },
	gemFamily = { "FirePenetration", },
	levels = { [1] = { levelRequirement = 0, manaMultiplier = 25, }, },
	statSets = { [1] = {
		constantStats = { },
		stats = { "hits_ignore_enemy_fire_resistance", },
	}, },
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
    # Tier II's effect is a boolean flag-stat (ignore fire res), not a number.
    assert tiers[0]["stats"] == [{"id": "hits_ignore_enemy_fire_resistance", "value": True}]
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


def test_supports_for_or_semantics():
    g = _gem_data()
    # Fire Penetration I requires {Damage, Attack} (OR): a skill with only Attack
    # still matches. Fire Penetration II requires {Damage} only, so it does not.
    names = {s["name"] for s in g.supports_for({"Attack", "Melee"})}
    assert "Fire Penetration I" in names
    assert "Fire Penetration II" not in names
    # A skill with Damage matches both.
    names2 = {s["name"] for s in g.supports_for({"Damage"})}
    assert {"Fire Penetration I", "Fire Penetration II"} <= names2


def test_flag_stats_parsed_as_boolean():
    g = _gem_data()
    # Fire Penetration II's effect is a flag-stat (no number) — it must survive
    # extraction as a boolean, not get dropped with the empty constantStats.
    fp2 = g.get("Fire Penetration II")
    assert {"id": "hits_ignore_enemy_fire_resistance", "value": True} in fp2["stats"]
    # The numeric tier is untouched.
    assert g.get("Fire Penetration I")["stats"] == [
        {"id": "base_reduce_enemy_fire_resistance_%", "value": 30}]


def test_classify_penetration_matches_element():
    from poe2_mcp.skills.recommend import classify_support, skill_damage_dims
    g = _gem_data()
    pen = g.get("Fire Penetration I")
    fire_tags = {"Spell", "Fire", "Area"}
    dims = skill_damage_dims(fire_tags)
    fire = classify_support(pen, dims, {"fire"}, fire_tags)
    assert fire["bucket"] == "penetration" and fire["applicable"] is True
    # Same gem on a cold-only skill: fire pen does nothing.
    cold_tags = {"Spell", "Cold"}
    cold = classify_support(pen, skill_damage_dims(cold_tags), {"cold"}, cold_tags)
    assert cold["bucket"] == "penetration" and cold["applicable"] is False


def test_classify_ignore_resistance_flag():
    from poe2_mcp.skills.recommend import classify_support, skill_damage_dims
    g = _gem_data()
    fp2 = g.get("Fire Penetration II")
    fire_tags = {"Spell", "Fire", "Area"}
    res = classify_support(fp2, skill_damage_dims(fire_tags), {"fire"}, fire_tags)
    # The flag is recognised as penetration and outscores any % reduction.
    assert res["bucket"] == "penetration" and res["applicable"] is True
    assert res["score"] > 100 and "IGNORE" in res["note"]


def test_top_support_hint_prioritises_pen_and_skips_equipped():
    from poe2_mcp.skills.recommend import top_support_hint
    rec = {"buckets": {
        "penetration": [
            {"name": "Fire Penetration II", "score": 999, "note": "ignore fire res",
             "bucket": "penetration", "already_equipped": False},
        ],
        "generic_more": [
            {"name": "Considered Casting", "score": 35, "note": "more spell",
             "bucket": "generic_more", "already_equipped": True},   # equipped → skip
            {"name": "Concentrated Area", "score": 30, "note": "more area",
             "bucket": "generic_more", "already_equipped": False},
            {"name": "Controlled Destruction", "score": 25, "note": "more spell",
             "bucket": "generic_more", "already_equipped": False},
            {"name": "Elemental Focus", "score": 25, "note": "more ele",
             "bucket": "generic_more", "already_equipped": False},
        ],
        "conditional": [{"name": "Ignite III", "score": 200, "note": "x",
                         "bucket": "conditional", "already_equipped": False}],
        "utility": [],
    }}
    hint = top_support_hint(rec)
    # Penetration first, equipped skipped, conditional/utility never included, capped at 3.
    assert hint == [
        "Fire Penetration II — ignore fire res",
        "Concentrated Area — more area",
        "Controlled Destruction — more spell",
    ]


def test_classify_buckets_and_scope():
    from poe2_mcp.skills.recommend import classify_support, skill_damage_dims
    fire_tags = {"Spell", "Fire", "Area"}
    dims = skill_damage_dims(fire_tags)

    def classify(stats, requires=None):
        gem = {"stats": [{"id": i, "value": v} for i, v in stats],
               "requires": requires or []}
        return classify_support(gem, dims, {"fire"}, fire_tags)

    # Typed multiplier the skill scales → generic_more, applicable.
    area = classify([("support_x_area_damage_+%_final", 30)])
    assert area["bucket"] == "generic_more" and area["applicable"] is True
    # Physical multiplier on a fire skill → applicable False.
    phys = classify([("support_x_physical_damage_+%_final", 30)])
    assert phys["applicable"] is False
    # Ignite payload → conditional (skill deals fire, so it *could* apply).
    ign = classify([("support_x_chance_to_ignite_+%_final", 200)])
    assert ign["bucket"] == "conditional"
    # Untyped "damage" but DoT-scoped via requires → not a hit multiplier here.
    dot = classify([("support_x_damage_+%_final", 30)], requires=["DamageOverTime"])
    assert dot["applicable"] is False
    # A pure utility final (speed) → utility bucket.
    util = classify([("support_x_cast_speed_+%_final", 20)])
    assert util["bucket"] == "utility"
