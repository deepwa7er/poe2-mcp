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
from typing import Callable

from .models import Build, Item, SkillGem, SocketGroup, Stat
from .item_parser import parse_item_text

# Resolves a gem NAME to is-it-a-support (True/False) or None for "unknown".
# Consulted only for gems whose export carries no ids; lets a caller with a gem
# database catch supports the id heuristic can't see (see _gem_is_support).
SupportDetector = Callable[[str], bool | None]


def parse_build_xml(xml: str, support_detector: SupportDetector | None = None) -> Build:
    root = ET.fromstring(xml)
    return Build(
        class_name=_parse_class(root),
        ascendancy=_parse_ascendancy(root),
        level=_parse_level(root),
        allocated_node_ids=_parse_node_ids(root),
        items=_parse_items(root),
        socket_groups=_parse_skills(root, support_detector),
        stats=_parse_stats(root),
        notes=_parse_notes(root),
        config=_parse_config(root),
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


def _gem_is_support(skill_id: str, gem_id: str) -> bool | None:
    """Support detection from the export's ids; None when the gem carries no ids.

    Supports carry skillId "Support..." (e.g. "SupportFirePenetrationPlayer") or a
    gemId containing "SupportGem". A gem with no ids at all (a name typed into PoB
    without resolving) can't be classified here — callers may resolve it by name
    via a SupportDetector (the server backs one with the gem database).
    """
    if not skill_id and not gem_id:
        return None
    return skill_id.startswith("Support") or "SupportGem" in gem_id


def _parse_skills(root: ET.Element,
                  support_detector: SupportDetector | None = None) -> list[SocketGroup]:
    skills_elem = root.find("Skills")
    if skills_elem is None:
        return []

    # PoB2 nests <Skill> elements inside <SkillSet> (honour activeSkillSet);
    # PoB1 lists <Skill> directly under <Skills>.
    skill_sets = skills_elem.findall("SkillSet")
    if skill_sets:
        active_set_id = skills_elem.get("activeSkillSet", "1")
        active_set = next(
            (s for s in skill_sets if s.get("id") == active_set_id),
            skill_sets[0],
        )
        skill_elems = active_set.findall("Skill")
    else:
        skill_elems = skills_elem.findall("Skill")

    groups: list[SocketGroup] = []
    for skill_elem in skill_elems:
        slot = skill_elem.get("slot", skill_elem.get("label", ""))
        enabled = skill_elem.get("enabled", "true").lower() == "true"
        # PoB1 uses mainActiveSpec, PoB2 uses mainActiveSkill (both 1-based).
        main_active = skill_elem.get("mainActiveSkill", skill_elem.get("mainActiveSpec", "1"))
        try:
            main_active_spec = int(main_active) - 1
        except ValueError:
            main_active_spec = 0

        gems: list[SkillGem] = []
        active_skill = ""
        # mainActiveSkill indexes PoB's displaySkillList, which holds only the
        # skills granted by ENABLED, NON-SUPPORT gems (CalcSetup.lua builds it
        # that way) — NOT the group's full gem list. Count matching gems as we
        # go so a support listed before the active gem doesn't shift the index.
        active_candidate = 0
        for gem_elem in skill_elem.findall("Gem"):
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
            skill_id = gem_elem.get("skillId", "")
            gem_id = gem_elem.get("gemId", "")
            is_support = _gem_is_support(skill_id, gem_id)
            if is_support is None:  # id-less gem — fall back to name resolution
                is_support = bool(support_detector and support_detector(name))
            is_active = False
            if gem_enabled and not is_support:
                is_active = active_candidate == main_active_spec
                active_candidate += 1
            if is_active:
                active_skill = name
            gems.append(SkillGem(
                name=name,
                level=level,
                quality=quality,
                is_active=is_active,
                enabled=gem_enabled,
                skill_id=skill_id,
                gem_id=gem_id,
                is_support=is_support,
            ))

        # Fall back to the first non-support gem (then any gem) so the group still
        # carries a label when mainActiveSkill is out of range or everything is
        # disabled. Empty groups are KEPT (active_skill "") — PoB keeps them in its
        # socket-group list, and dropping them would shift 1-based group indices
        # out of alignment with the headless engine's list_skills.
        if not active_skill and gems:
            active_skill = next((g.name for g in gems if not g.is_support), gems[0].name)

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


def _parse_config(root: ET.Element) -> dict:
    """Parse the PoB <Config> assumptions behind the computed stats.

    <Input> entries are the active config (conditions, multipliers, quest
    passives); <Placeholder> entries are default enemy/multiplier values. PoB2
    nests these under <ConfigSet> (honour activeConfigSet); older exports list
    them directly under <Config>.
    """
    cfg = root.find("Config")
    if cfg is None:
        return {}

    sets = cfg.findall("ConfigSet")
    if sets:
        active_id = cfg.get("activeConfigSet", "1")
        container = next((s for s in sets if s.get("id") == active_id), sets[0])
    else:
        container = cfg

    inputs: dict = {}
    for elem in container.findall("Input"):
        name = elem.get("name")
        if name:
            inputs[name] = _config_value(elem)

    placeholders: dict = {}
    for elem in container.findall("Placeholder"):
        name = elem.get("name")
        if name:
            placeholders[name] = _config_value(elem)

    if not inputs and not placeholders:
        return {}
    return {"inputs": inputs, "placeholders": placeholders}


def _config_value(elem: ET.Element):
    """A Config entry carries its value in a boolean/number/string attribute."""
    raw = elem.get("boolean")
    if raw is not None:
        return raw.strip().lower() == "true"
    raw = elem.get("number")
    if raw is not None:
        try:
            return int(raw) if "." not in raw else float(raw)
        except ValueError:
            return raw
    return elem.get("string")
