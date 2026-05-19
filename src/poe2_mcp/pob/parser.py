"""
Parse a PoB build XML into our domain models.

PoB XML structure:
  <PathOfBuilding>
    <Build level="..." className="..." ascendClassName="...">
      <PlayerStat stat="..." value="..."/>
      ...
    </Build>
    <Tree activeSpec="1">
      <Spec ...>
        <nodes>id,id,id,...</nodes>   (PoE2 format)
        OR nodes="id,id,id,..."       (attribute form used in some versions)
      </Spec>
    </Tree>
    <Skills ...>
      <Skill slot="..." enabled="...">
        <Gem nameSpec="..." level="..." quality="..." enabled="..." skillId="..."/>
        ...
      </Skill>
    </Skills>
    <Items ...>
      <Item id="..." >raw item text</Item>
      <Slot name="..." itemId="..."/>
    </Items>
    <Notes>...</Notes>
  </PathOfBuilding>
"""

import xml.etree.ElementTree as ET

from .models import Build, Item, PassiveNode, SkillGem, SocketGroup, Stat
from .item_parser import parse_item_text


def parse_build_xml(xml: str) -> Build:
    root = ET.fromstring(xml)
    return Build(
        class_name=_parse_class(root),
        ascendancy=_parse_ascendancy(root),
        level=_parse_level(root),
        allocated_node_ids=_parse_node_ids(root),
        items=_parse_items(root),
        socket_groups=_parse_skills(root),
        stats=_parse_stats(root),
        notes=_parse_notes(root),
    )


def _parse_class(root: ET.Element) -> str:
    build = root.find("Build")
    if build is None:
        return "Unknown"
    return build.get("className", "Unknown")


def _parse_ascendancy(root: ET.Element) -> str:
    build = root.find("Build")
    if build is None:
        return ""
    return build.get("ascendClassName", "")


def _parse_level(root: ET.Element) -> int:
    build = root.find("Build")
    if build is None:
        return 0
    try:
        return int(build.get("level", "0"))
    except ValueError:
        return 0


def _parse_stats(root: ET.Element) -> list[Stat]:
    build = root.find("Build")
    if build is None:
        return []
    stats = []
    for elem in build.findall("PlayerStat"):
        name = elem.get("stat", "")
        value = elem.get("value", "")
        if name and value:
            stats.append(Stat(name=name, value=value))
    return stats


def _parse_node_ids(root: ET.Element) -> list[int]:
    tree = root.find("Tree")
    if tree is None:
        return []

    active_spec_index = int(tree.get("activeSpec", "1")) - 1  # 1-based in XML

    specs = tree.findall("Spec")
    if not specs:
        return []

    spec = specs[active_spec_index] if active_spec_index < len(specs) else specs[0]

    # Node IDs can be in a <nodes> child element (PoE2 format) or a "nodes" attribute
    nodes_elem = spec.find("nodes")
    if nodes_elem is not None and nodes_elem.text:
        raw = nodes_elem.text.strip()
    else:
        raw = spec.get("nodes", "")

    if not raw:
        return []

    ids = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            try:
                ids.append(int(token))
            except ValueError:
                pass
    return ids


def _parse_items(root: ET.Element) -> list[Item]:
    items_elem = root.find("Items")
    if items_elem is None:
        return []

    # Build a map from item id → raw item text
    id_to_raw: dict[str, str] = {}
    for item_elem in items_elem.findall("Item"):
        item_id = item_elem.get("id", "")
        raw = (item_elem.text or "").strip()
        if item_id and raw:
            id_to_raw[item_id] = raw

    # Slots can be direct children of <Items> or nested inside <ItemSet> elements.
    # When ItemSets are present, honour the activeItemSet attribute.
    active_set_id = items_elem.get("activeItemSet", "1")
    item_sets = items_elem.findall("ItemSet")
    if item_sets:
        active_set = next(
            (s for s in item_sets if s.get("id") == active_set_id),
            item_sets[0],
        )
        slot_elems = active_set.findall("Slot")
    else:
        slot_elems = items_elem.findall("Slot")

    items: list[Item] = []
    for slot_elem in slot_elems:
        slot_name = slot_elem.get("name", "")
        item_id = slot_elem.get("itemId", "")
        if not item_id or item_id == "0":
            continue
        raw = id_to_raw.get(item_id, "")
        if not raw:
            continue
        parsed = parse_item_text(raw, slot_name)
        items.append(Item(**parsed))

    return items


def _parse_skills(root: ET.Element) -> list[SocketGroup]:
    skills_elem = root.find("Skills")
    if skills_elem is None:
        return []

    groups: list[SocketGroup] = []
    for skill_elem in skills_elem.findall("Skill"):
        slot = skill_elem.get("slot", "")
        enabled = skill_elem.get("enabled", "true").lower() == "true"
        main_active_spec = int(skill_elem.get("mainActiveSpec", "1")) - 1

        gems: list[SkillGem] = []
        active_skill = ""
        for i, gem_elem in enumerate(skill_elem.findall("Gem")):
            name = gem_elem.get("nameSpec", gem_elem.get("skillId", ""))
            try:
                level = int(gem_elem.get("level", "1"))
            except ValueError:
                level = 1
            try:
                quality = int(gem_elem.get("quality", "0"))
            except ValueError:
                quality = 0
            gem_enabled = gem_elem.get("enabled", "true").lower() == "true"
            # The gem at mainActiveSpec index is the active skill
            is_active = i == main_active_spec
            if is_active:
                active_skill = name
            gems.append(SkillGem(
                name=name,
                level=level,
                quality=quality,
                is_active=is_active,
                enabled=gem_enabled,
            ))

        if not gems:
            continue

        if not active_skill and gems:
            active_skill = gems[0].name

        groups.append(SocketGroup(
            slot=slot,
            active_skill=active_skill,
            gems=gems,
            enabled=enabled,
        ))

    return groups


def _parse_notes(root: ET.Element) -> str:
    notes_elem = root.find("Notes")
    if notes_elem is None:
        return ""
    return (notes_elem.text or "").strip()


def _empty(slot: str, raw: str) -> dict:
    return {
        "slot": slot,
        "rarity": "Normal",
        "name": "",
        "base_type": "",
        "item_level": 0,
        "mods": [],
        "corrupted": False,
        "raw_text": raw,
    }
