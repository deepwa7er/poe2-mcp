from dataclasses import dataclass, field


@dataclass
class Stat:
    name: str
    value: str


def _stat_to_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


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
    # Heuristic from the export's ids (skillId "Support..." / gemId "...SupportGem...").
    # False for gems with no ids at all, so a nameSpec-only support can slip through.
    is_support: bool = False


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
    # The PoB <Config> behind `stats`: {"inputs": {...}, "placeholders": {...}}.
    config: dict = field(default_factory=dict)
    # Resolved after loading tree data
    passive_nodes: list[PassiveNode] = field(default_factory=list)

    def stat_float(self, *names: str) -> float | None:
        """First matching stat (exact case-insensitive name) as a float, else None.

        PoB stat names vary between versions, so callers pass candidates in
        preference order; values like "75%" or "1,234" are normalised.
        """
        lookup = {s.name.lower(): s.value for s in self.stats}
        for name in names:
            if name.lower() in lookup:
                v = _stat_to_float(lookup[name.lower()])
                if v is not None:
                    return v
        return None
