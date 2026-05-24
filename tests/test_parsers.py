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
