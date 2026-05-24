from poe2_mcp.pob.item_parser import parse_item_text
from poe2_mcp.pob.parser import parse_build_xml

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
        <Gem nameSpec="Walking Calamity" level="21" quality="23"/>
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
