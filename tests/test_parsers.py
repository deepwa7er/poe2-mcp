from pathlib import Path

from poe2_mcp.pob.decoder import decode_build_code
from poe2_mcp.pob.item_parser import parse_item_text
from poe2_mcp.pob.parser import parse_build_xml

FIXTURES = Path(__file__).parent / "fixtures"

RARE_ITEM = """Rarity: Rare
Doom Bane
Vaal Regalia
--------
Quality: 20
--------
Item Level: 86
--------
+50 to maximum Life
+30% to Fire Resistance
--------
Corrupted
"""


def test_parse_rare_item():
    item = parse_item_text(RARE_ITEM, "Body Armour")
    assert item["rarity"] == "Rare"
    assert item["name"] == "Doom Bane"
    assert item["base_type"] == "Vaal Regalia"
    assert item["item_level"] == 86
    assert item["corrupted"] is True
    assert "+50 to maximum Life" in item["mods"]
    assert "+30% to Fire Resistance" in item["mods"]
    # Metadata lines must not leak into mods.
    assert not any("Quality" in m for m in item["mods"])
    assert not any("Item Level" in m for m in item["mods"])


def test_parse_magic_item_uses_name_as_base():
    raw = "Rarity: Magic\nSturdy Iron Greaves of Haste\n--------\nItem Level: 40\n--------\n+12% increased Movement Speed\n"
    item = parse_item_text(raw, "Boots")
    assert item["rarity"] == "Magic"
    assert item["base_type"] == "Sturdy Iron Greaves of Haste"


# poe.ninja / PoB2 export format: no "--------" dividers, field markers instead,
# affix tags on mod lines, and an explicit "Implicits: N" count. This layout is
# what silently produced empty mods before the parser was made marker-driven.
PB2_ITEM = """Rarity: RARE
Hate Brow
Imperial Greathelm
Armour: 531
Unique ID: 9d5fbaa2536b1daefb4ae29aea5c02276ea7ba1e9ec7a0a7e62acade1ebd4361
Item Level: 82
Quality: 21
Sockets: S S
Rune: Idol of Eeshta
Rune: Tzamoto's Soul Core of Ferocity
LevelReq: 80
Implicits: 4
{enchant}{rune}12% increased Cost Efficiency
{enchant}{rune}+4 to Maximum Rage
{enchant}{rune}Bonded: Meta Skills have 12% increased Reservation Efficiency
{enchant}+29 to Spirit
{fractured}19% increased Rarity of Items found
{desecrated}+45% to Lightning Resistance
39% increased Armour
+211 to maximum Life
18% increased Rarity of Items found
34% increased Critical Hit Chance
Corrupted"""


def test_parse_pob2_fieldmarker_item():
    item = parse_item_text(PB2_ITEM, "Helmet")
    assert item["rarity"] == "Rare"            # normalised from "RARE"
    assert item["name"] == "Hate Brow"
    assert item["base_type"] == "Imperial Greathelm"
    assert item["item_level"] == 82
    assert item["quality"] == 21
    assert item["corrupted"] is True
    assert item["runes"] == ["Idol of Eeshta", "Tzamoto's Soul Core of Ferocity"]
    # Affix tags are stripped; metadata never leaks into mods.
    assert "+211 to maximum Life" in item["mods"]
    assert "+45% to Lightning Resistance" in item["mods"]
    assert "Bonded: Meta Skills have 12% increased Reservation Efficiency" in item["mods"]
    assert not any(m.startswith("{") for m in item["mods"])
    assert not any("Unique ID" in m or "Sockets" in m or "Armour:" in m for m in item["mods"])
    # First 4 mods are the declared implicits.
    assert item["implicit_count"] == 4
    assert item["mods"][item["implicit_count"]] == "19% increased Rarity of Items found"


CONFIG_XML = """<PathOfBuilding2>
  <Build level="68" className="Monk" ascendClassName="Invoker"/>
  <Config activeConfigSet="2">
    <ConfigSet title="Wrong" id="1">
      <Input name="conditionEnemyChilled" boolean="true"/>
    </ConfigSet>
    <ConfigSet title="Default" id="2">
      <Input name="conditionEnemyShocked" boolean="true"/>
      <Input name="conditionCritRecently" boolean="false"/>
      <Input name="multiplierNearbyEnemies" number="3"/>
      <Input name="questReward" string="+5% to Fire Resistance"/>
      <Placeholder name="enemyLevel" number="82"/>
      <Placeholder name="enemyLightningResist" number="50"/>
    </ConfigSet>
  </Config>
</PathOfBuilding2>"""


def test_parse_config_honours_active_set_and_types():
    build = parse_build_xml(CONFIG_XML)
    inputs = build.config["inputs"]
    placeholders = build.config["placeholders"]
    # activeConfigSet=2 is used, not set 1.
    assert inputs["conditionEnemyShocked"] is True
    assert inputs["conditionCritRecently"] is False
    assert "conditionEnemyChilled" not in inputs   # that was only in set 1
    assert inputs["multiplierNearbyEnemies"] == 3   # number -> int
    assert inputs["questReward"] == "+5% to Fire Resistance"
    assert placeholders["enemyLevel"] == 82


def test_parse_config_absent_is_empty():
    build = parse_build_xml(BUILD_XML)  # no <Config>
    assert build.config == {}


def test_poeninja_export_items_parse_with_mods():
    """Regression: the real poe.ninja export must yield items with mods and ilvl."""
    code = (FIXTURES / "poeninja_pob_export.txt").read_text()
    build = parse_build_xml(decode_build_code(code))
    assert build.items, "expected the fixture build to have items"
    enriched = [it for it in build.items if it.mods]
    # Most rare/unique gear should now carry parsed mods (was 0 across the board).
    assert len(enriched) >= len(build.items) // 2
    assert any(it.item_level > 0 for it in build.items)


BUILD_XML = """<PathOfBuilding>
  <Build level="92" className="Monk" ascendClassName="Invoker">
    <PlayerStat stat="Life" value="3000"/>
    <PlayerStat stat="FireResist" value="75"/>
  </Build>
  <Tree activeSpec="1">
    <Spec><nodes>100,101,102</nodes></Spec>
  </Tree>
  <Skills>
    <Skill slot="Weapon 1" enabled="true" mainActiveSpec="1">
      <Gem nameSpec="Ice Strike" level="20" quality="20" enabled="true"/>
      <Gem nameSpec="Added Cold Damage" level="20" quality="0" enabled="true"/>
    </Skill>
  </Skills>
  <Items activeItemSet="1">
    <Item id="1">Rarity: Rare
Thing
Vaal Regalia
--------
Item Level: 80
--------
+50 to maximum Life</Item>
    <Slot name="Body Armour" itemId="1"/>
  </Items>
</PathOfBuilding>"""


def test_parse_build_xml():
    build = parse_build_xml(BUILD_XML)
    assert build.class_name == "Monk"
    assert build.ascendancy == "Invoker"
    assert build.level == 92
    assert build.allocated_node_ids == [100, 101, 102]
    assert len(build.stats) == 2
    assert len(build.socket_groups) == 1
    assert build.socket_groups[0].active_skill == "Ice Strike"
    assert len(build.socket_groups[0].gems) == 2
    assert len(build.items) == 1
    assert build.items[0].slot == "Body Armour"


def test_parse_build_xml_nodes_attribute_form():
    xml = '<PathOfBuilding><Build level="1" className="Warrior"/>' \
          '<Tree activeSpec="1"><Spec nodes="5,6,7"/></Tree></PathOfBuilding>'
    build = parse_build_xml(xml)
    assert build.allocated_node_ids == [5, 6, 7]


PB2_SKILLS = """<PathOfBuilding2>
  <Build level="100" className="Warrior" ascendClassName="Titan"/>
  <Skills activeSkillSet="2">
    <SkillSet id="1">
      <Skill mainActiveSkill="1" enabled="true"><Gem nameSpec="Wrong Set" level="1" quality="0"/></Skill>
    </SkillSet>
    <SkillSet id="2">
      <Skill mainActiveSkill="1" enabled="true">
        <Gem nameSpec="Walking Calamity" level="21" quality="23" skillId="WalkingCalamityPlayer"/>
        <Gem nameSpec="Ambrosia II" level="1" quality="0"/>
      </Skill>
    </SkillSet>
  </Skills>
</PathOfBuilding2>"""


def test_parse_pob2_skillset_nesting():
    # PoB2 nests <Skill> under <SkillSet>; the active set is honoured.
    build = parse_build_xml(PB2_SKILLS)
    assert len(build.socket_groups) == 1
    group = build.socket_groups[0]
    assert group.active_skill == "Walking Calamity"   # from activeSkillSet=2, mainActiveSkill=1
    assert len(group.gems) == 2
    assert group.gems[0].skill_id == "WalkingCalamityPlayer"   # skillId flows through


# mainActiveSkill indexes PoB's displaySkillList — enabled, non-support gems only —
# not the group's full gem list. Supports before the active gem must not shift it.
MAIN_ACTIVE_XML = """<PathOfBuilding2>
  <Build level="50" className="Witch"/>
  <Skills>
    <Skill mainActiveSkill="1" enabled="true">
      <Gem nameSpec="Fire Penetration I" skillId="SupportFirePenetrationPlayer"
           gemId="Metadata/Items/Gems/SupportGemFirePenetration" level="1" quality="0"/>
      <Gem nameSpec="Firebolt" skillId="FireboltPlayer"
           gemId="Metadata/Items/Gems/SkillGemFirebolt" level="12" quality="0"/>
    </Skill>
    <Skill mainActiveSkill="2" enabled="true">
      <Gem nameSpec="Cast on Ignite" skillId="MetaCastOnIgnitePlayer"
           gemId="Metadata/Items/Gems/SkillGemCastOnIgnite" level="8" quality="0"/>
      <Gem nameSpec="Magnified Area I" skillId="SupportMagnifiedAreaPlayer"
           gemId="Metadata/Items/Gems/SupportGemMagnifiedEffect" level="1" quality="0"/>
      <Gem nameSpec="Firestorm" skillId="FirestormPlayer"
           gemId="Metadata/Items/Gems/SkillGemFirestorm" level="9" quality="0"/>
    </Skill>
    <Skill mainActiveSkill="1" enabled="true">
      <Gem nameSpec="Disabled Nuke" skillId="DisabledNukePlayer" enabled="false" level="1" quality="0"/>
      <Gem nameSpec="Spark" skillId="SparkPlayer" level="1" quality="0"/>
    </Skill>
    <Skill enabled="true"/>
    <Skill mainActiveSkill="1" enabled="true">
      <Gem nameSpec="Last Group" skillId="LastGroupPlayer" level="1" quality="0"/>
    </Skill>
  </Skills>
</PathOfBuilding2>"""


def test_main_active_skill_skips_supports():
    build = parse_build_xml(MAIN_ACTIVE_XML)
    g1 = build.socket_groups[0]
    # mainActiveSkill=1 means the first NON-SUPPORT gem, not gems[0] (a support).
    assert g1.active_skill == "Firebolt"
    assert [g.name for g in g1.gems if g.is_active] == ["Firebolt"]
    assert g1.gems[0].is_support is True and g1.gems[1].is_support is False

    # mainActiveSkill=2 counts only the actives: Cast on Ignite (1), Firestorm (2).
    g2 = build.socket_groups[1]
    assert g2.active_skill == "Firestorm"
    assert [g.name for g in g2.gems if g.is_active] == ["Firestorm"]


def test_main_active_skill_skips_disabled_gems():
    build = parse_build_xml(MAIN_ACTIVE_XML)
    g3 = build.socket_groups[2]
    # The disabled gem doesn't occupy an index in PoB's display list.
    assert g3.active_skill == "Spark"
    assert [g.name for g in g3.gems if g.is_active] == ["Spark"]


def test_support_detector_classifies_idless_gems():
    # An id-less support (a bare nameSpec, like "Unleash" in real exports) can't be
    # classified from ids; a SupportDetector backed by a gem database can. Without
    # it the gem counts as an active candidate and shifts mainActiveSkill.
    xml = """<PathOfBuilding2>
      <Build level="50" className="Witch"/>
      <Skills>
        <Skill mainActiveSkill="1" enabled="true">
          <Gem nameSpec="Unleash" level="1" quality="0"/>
          <Gem nameSpec="Fireball" skillId="FireballPlayer"
               gemId="Metadata/Items/Gem/SkillGemFireball" level="10" quality="0"/>
        </Skill>
      </Skills>
    </PathOfBuilding2>"""

    def detector(name):
        return True if name == "Unleash" else None

    build = parse_build_xml(xml, support_detector=detector)
    group = build.socket_groups[0]
    assert group.active_skill == "Fireball"
    assert group.gems[0].is_support is True and group.gems[1].is_active is True

    # Without a detector the id-less gem stays unknown → non-support (documented
    # fallback), and takes the mainActiveSkill=1 slot.
    fallback = parse_build_xml(xml).socket_groups[0]
    assert fallback.gems[0].is_support is False
    assert fallback.active_skill == "Unleash"


def test_empty_socket_groups_are_kept_for_index_alignment():
    build = parse_build_xml(MAIN_ACTIVE_XML)
    # PoB keeps gem-less groups in its socket-group list; dropping them would shift
    # the 1-based indices shared with the headless engine.
    assert len(build.socket_groups) == 5
    assert build.socket_groups[3].gems == [] and build.socket_groups[3].active_skill == ""
    assert build.socket_groups[4].active_skill == "Last Group"
