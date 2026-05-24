from dataclasses import dataclass, field


@dataclass
class Stat:
    name: str
    value: str


@dataclass
class PassiveNode:
    id: int
    name: str
    stats: list[str] = field(default_factory=list)
    is_keystone: bool = False
    is_notable: bool = False
    is_mastery: bool = False


@dataclass
class Item:
    slot: str
    rarity: str
    name: str
    base_type: str
    item_level: int
    mods: list[str] = field(default_factory=list)
    corrupted: bool = False
    raw_text: str = ""
    quality: int = 0
    runes: list[str] = field(default_factory=list)
    # Number of leading entries in `mods` that are implicit (incl. enchants/runes);
    # the rest are explicit. 0 when the source format does not declare implicits.
    implicit_count: int = 0


@dataclass
class SkillGem:
    name: str
    level: int
    quality: int
    is_active: bool
    enabled: bool = True
    skill_id: str = ""
    gem_id: str = ""


@dataclass
class SocketGroup:
    slot: str
    active_skill: str
    gems: list[SkillGem] = field(default_factory=list)
    enabled: bool = True


@dataclass
class Build:
    class_name: str
    ascendancy: str
    level: int
    allocated_node_ids: list[int]
    items: list[Item]
    socket_groups: list[SocketGroup]
    stats: list[Stat]
    notes: str = ""
    # Resolved after loading tree data
    passive_nodes: list[PassiveNode] = field(default_factory=list)
