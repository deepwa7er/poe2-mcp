from poe2_mcp.community import archetype

# A fake gem database: name (lowercased) -> {skill_types, is_support}.
_GEMS = {
    "twister": {"skill_types": ["Attack", "Projectile", "Spear", "Area"], "is_support": False},
    "barrage": {"skill_types": ["Attack", "Projectile"], "is_support": False},
    "whirling slash": {"skill_types": ["Attack", "Melee", "Area"], "is_support": False},
    "herald of ice": {"skill_types": ["Herald", "Spell", "Cold"], "is_support": False},
    "vivid stampede": {"skill_types": ["Attack"], "is_support": False},
    "lightning arrow": {"skill_types": ["Attack", "Projectile"], "is_support": False},
    "martial tempo": {"skill_types": [], "is_support": True},
    "pinpoint critical": {"skill_types": [], "is_support": True},
}


def _gem_info(name):
    return _GEMS.get(name.lower())


def _cohort_rows():
    # Four Twister builds + one unrelated build that must be excluded.
    return [
        {"class": "Spirit Walker", "skills": ["Twister", "Barrage", "Whirling Slash", "Herald of Ice", "Martial Tempo"], "keypassives": ["Dance with Death"]},
        {"class": "Spirit Walker", "skills": ["Twister", "Barrage", "Whirling Slash", "Herald of Ice", "Martial Tempo"], "keypassives": ["Dance with Death"]},
        {"class": "Martial Artist", "skills": ["Twister", "Barrage", "Whirling Slash"], "keypassives": ["Dance with Death", "Resonance"]},
        {"class": "Deadeye", "skills": ["Twister", "Barrage", "Vivid Stampede"], "keypassives": ["Resonance"]},
        {"class": "Stormweaver", "skills": ["Lightning Arrow"], "keypassives": ["Resonance"]},
    ]


def test_cohort_excludes_non_users_and_drops_the_target_skill():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info)
    assert rep["cohort_size"] == 4  # the Lightning Arrow build is excluded
    all_skill_names = {i["name"] for i in rep["core_skills"] + rep["tech_skills"]}
    assert "Twister" not in all_skill_names  # the premise is not a finding


def test_core_vs_tech_split_by_recurrence():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info)
    core = {i["name"] for i in rep["core_skills"]}
    tech = {i["name"] for i in rep["tech_skills"]}
    assert "Barrage" in core            # 4/4
    assert "Whirling Slash" in core     # 3/4
    assert "Herald of Ice" in tech      # 2/4 -> tech
    assert "Vivid Stampede" in tech     # 1/4 -> tech
    # key passives
    assert any(i["name"] == "Dance with Death" for i in rep["core_passives"])  # 3/4
    assert any(i["name"] == "Resonance" for i in rep["tech_passives"])         # 2/4


def test_supports_classified_separately_from_active_skills():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info)
    active = {i["name"] for i in rep["core_skills"] + rep["tech_skills"]}
    supports = {i["name"] for i in rep["core_supports"] + rep["tech_supports"]}
    assert "Martial Tempo" in supports
    assert "Martial Tempo" not in active


def test_ascendancy_spread():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info)
    top = rep["ascendancies"][0]
    assert top["name"] == "Spirit Walker"
    assert top["count"] == 2 and top["pct"] == 50


def test_scaling_profile_and_gear_for_attack_build():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info)
    prof = rep["scaling_profile"]
    assert "cold" in prof["damage_elements"]       # from Herald of Ice
    assert "physical" in prof["damage_elements"]   # martial-attack default
    assert prof["crit_is_core"] is False
    stats = [g["stat"] for g in rep["gear_priorities"]]
    assert any("spear" in s.lower() for s in stats)            # Spear tag -> weapon
    assert any("Attack Speed" in s for s in stats)
    assert any("Cold Damage" in s for s in stats)
    assert not any("Cast Speed" in s for s in stats)           # attack, not spell
    crit = next(g for g in rep["gear_priorities"] if "Critical" in g["stat"])
    assert crit["priority"] == "tech"                          # crit not core here


def test_crit_becomes_core_when_a_crit_support_recurs():
    rows = _cohort_rows()
    for r in rows[:3]:  # 3/4 builds run a crit support -> core
        r["skills"].append("Pinpoint Critical")
    rep = archetype.analyze("Twister", rows, _gem_info)
    assert rep["scaling_profile"]["crit_is_core"] is True
    crit = next(g for g in rep["gear_priorities"] if "Critical" in g["stat"])
    assert crit["priority"] == "high"


def test_case_insensitive_skill_match():
    rep = archetype.analyze("twister", _cohort_rows(), _gem_info)
    assert rep["cohort_size"] == 4


def test_empty_cohort_returns_note():
    rep = archetype.analyze("Nonexistent Skill", _cohort_rows(), _gem_info)
    assert rep["cohort_size"] == 0
    assert "note" in rep


def _build_groups():
    # Three builds' socket groups: {active_skill, supports}.
    return [
        [{"active_skill": "Twister", "supports": ["Elemental Armament II", "Projectile Acceleration III", "Pinpoint Critical"]},
         {"active_skill": "Barrage", "supports": ["Cooldown Recovery II"]}],
        [{"active_skill": "Twister", "supports": ["Elemental Armament II", "Projectile Acceleration III", "Rakiata's Flow"]},
         {"active_skill": "Barrage", "supports": ["Cooldown Recovery II"]}],
        [{"active_skill": "Twister", "supports": ["Elemental Armament II", "Armour Break III"]}],
    ]


def test_support_breakdown_core_vs_tech_per_skill():
    bd = archetype.support_breakdown(["Twister", "Barrage"], _build_groups())
    tw = bd["Twister"]
    assert tw["builds_seen"] == 3
    core = {i["name"] for i in tw["core_supports"]}
    tech = {i["name"] for i in tw["tech_supports"]}
    assert "Elemental Armament II" in core            # 3/3
    assert "Projectile Acceleration III" in core      # 2/3
    assert "Pinpoint Critical" in tech                # 1/3
    assert "Rakiata's Flow" in tech                   # 1/3
    # Barrage seen in only 2 builds; denominator is builds_seen, not the cohort.
    assert bd["Barrage"]["builds_seen"] == 2
    assert any(i["name"] == "Cooldown Recovery II" and i["pct"] == 100
               for i in bd["Barrage"]["core_supports"])


def test_support_breakdown_skill_absent_from_all_builds():
    bd = archetype.support_breakdown(["Comet"], _build_groups())
    assert bd["Comet"] == {"builds_seen": 0, "core_supports": [], "tech_supports": []}


def _build_passives():
    return [
        [{"name": "Dance with Death", "type": "keystone", "id": 1},
         {"name": "Precise Point", "type": "notable", "id": 2},
         {"name": "Blur", "type": "notable", "id": 3}],
        [{"name": "Dance with Death", "type": "keystone", "id": 1},
         {"name": "Precise Point", "type": "notable", "id": 2}],
        [{"name": "Dance with Death", "type": "keystone", "id": 1},
         {"name": "Catlike Agility", "type": "notable", "id": 4}],
    ]


def test_tree_breakdown_core_vs_tech_nodes():
    bd = archetype.tree_breakdown(_build_passives())
    assert bd["builds_seen"] == 3
    core = {i["name"]: i for i in bd["core_nodes"]}
    tech = {i["name"]: i for i in bd["tech_nodes"]}
    assert "Dance with Death" in core and core["Dance with Death"]["type"] == "keystone"  # 3/3
    assert "Precise Point" in core            # 2/3
    assert "Blur" in tech                      # 1/3
    assert "Catlike Agility" in tech           # 1/3


def test_tree_breakdown_empty():
    assert archetype.tree_breakdown([]) == {"builds_seen": 0, "core_nodes": [], "tech_nodes": []}


def test_analyze_attaches_passive_tree_when_passives_given():
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info, build_passives=_build_passives())
    assert rep["passive_tree"] is not None
    assert rep["passive_tree"]["builds_seen"] == 3
    # without build_passives it stays None
    assert archetype.analyze("Twister", _cohort_rows(), _gem_info)["passive_tree"] is None


def _class_builds():
    return [
        {"ascendancy": "Spirit Walker", "nodes": [
            {"name": "Dance with Death", "type": "keystone", "id": 1},
            {"name": "Roll and Strike", "type": "notable", "id": 2},
            {"name": "Acceleration", "type": "notable", "id": 3}]},
        {"ascendancy": "Spirit Walker", "nodes": [
            {"name": "Dance with Death", "type": "keystone", "id": 1},
            {"name": "Roll and Strike", "type": "notable", "id": 2}]},
        {"ascendancy": "Ritualist", "nodes": [
            {"name": "Roll and Strike", "type": "notable", "id": 2},
            {"name": "Primal Instinct", "type": "notable", "id": 4}]},
    ]


def test_analyze_class_tree_core_vs_tech():
    rep = archetype.analyze_class_tree("Huntress", _class_builds())
    assert rep["class"] == "Huntress"
    assert rep["cohort_size"] == 3
    core = {i["name"] for i in rep["core_nodes"]}
    tech = {i["name"] for i in rep["tech_nodes"]}
    assert "Roll and Strike" in core          # 3/3
    assert "Dance with Death" in core          # 2/3 keystone
    assert "Acceleration" in tech              # 1/3
    assert "Primal Instinct" in tech           # 1/3
    # ascendancy spread, most common first
    assert rep["ascendancies"][0] == {"name": "Spirit Walker", "count": 2, "pct": 67}


def test_analyze_class_tree_empty():
    rep = archetype.analyze_class_tree("Nobody", [])
    assert rep["cohort_size"] == 0 and "note" in rep


def test_analyze_attaches_support_breakdown_when_groups_given():
    groups = [
        [{"active_skill": "Twister", "supports": ["Elemental Armament II"]},
         {"active_skill": "Barrage", "supports": ["Cooldown Recovery II"]}]
        for _ in range(4)
    ]
    rep = archetype.analyze("Twister", _cohort_rows(), _gem_info, build_groups=groups)
    assert rep["support_breakdown"] is not None
    assert "Twister" in rep["support_breakdown"]          # target skill included
    assert "Barrage" in rep["support_breakdown"]          # a core skill included
    # without build_groups it stays None
    assert archetype.analyze("Twister", _cohort_rows(), _gem_info)["support_breakdown"] is None
