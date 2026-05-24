"""
PoE2 MCP server.

Tools:
  load_build      — decode a PoB export code or pobb.in URL
  get_stats       — computed character stats (life, mana, damage, resists, …)
  get_passives    — allocated passive nodes (with names/stats if tree data is loaded)
  get_items       — equipped items and their mods
  get_skills      — skill socket groups and gem links
  search_passives — find allocated passives matching a keyword
  search_tree     — find any node in the full passive tree (allocated or not)
  get_reachable_nodes — unallocated nodes within N steps of the build
  get_node        — inspect a single tree node and its neighbors
  path_to_node    — shortest allocate-sequence from the build to a target node
  get_point_budget — passive/ascendancy point usage summary
  analyze_defenses — defensive sanity checks (resists, health pool)
  get_meta_overview — poe.ninja ascendancy popularity for a league
  list_top_builds — top community builds on the poe.ninja ladder
  load_community_build — load a poe.ninja build by account + character name
  list_my_characters — your own characters from poe.ninja (any league)
  load_my_character — load one of your own characters by name
"""

import os

from mcp.server.fastmcp import FastMCP

from .pob import decode_build_code, parse_build_xml, Build
from .pob.models import Item, SkillGem, SocketGroup, Stat, PassiveNode
from .tree import PassiveTree, TreeNode, load_default_tree
from .diagnostics import analyze_defenses as _analyze_defenses, summarize_points
from .community import poeninja

mcp = FastMCP("poe2-mcp")

# Module-level state — single-user personal tool, single process
_build: Build | None = None
_tree: PassiveTree | None = load_default_tree()


def _require_build() -> Build:
    if _build is None:
        raise ValueError(
            "No build loaded. Call load_build() first with a PoB export code or pobb.in URL."
        )
    return _build


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def load_build(code: str) -> str:
    """
    Load a Path of Building export code or pobb.in share link.

    Accepts:
      - A raw PoB export code (the long base64 string from File > Share > Copy code)
      - A pobb.in URL (e.g. https://pobb.in/AbCdEfGh)

    Call this first before using any other tool.
    """
    _load_build_from_xml(decode_build_code(code))
    return _loaded_build_summary()


def _load_build_from_xml(xml: str) -> Build:
    """Parse XML into the module-level build, resolving passive names if tree data is present."""
    global _build, _tree
    if _tree is None:
        _tree = load_default_tree()
    _build = parse_build_xml(xml)
    if _tree is not None:
        _build.passive_nodes = _tree.resolve_ids(_build.allocated_node_ids)
    return _build


def _loaded_build_summary(source: str = "") -> str:
    b = _require_build()
    parts = [f"Loaded: {b.class_name}"]
    if b.ascendancy:
        parts.append(f"({b.ascendancy})")
    parts.append(f"level {b.level}")
    parts.append(f"— {len(b.allocated_node_ids)} passive nodes")
    parts.append(f"— {len(b.items)} items")
    parts.append(f"— {len(b.socket_groups)} skill groups")
    if source:
        parts.append(f"\nSource: {source}")
    if _tree is None:
        parts.append(
            "\n\nNote: passive tree data not found — passive names/stats unavailable. "
            "Place poe2_tree.json in the data/ directory or set TREE_DATA_PATH."
        )
    return " ".join(parts)


@mcp.tool()
def get_stats() -> list[dict]:
    """
    Return all computed character stats from the loaded build.

    These are the values Path of Building calculates: life, mana, energy shield,
    resistances, DPS for each skill, movement speed, etc.
    """
    build = _require_build()
    return [{"stat": s.name, "value": s.value} for s in build.stats]


@mcp.tool()
def get_passives(include_small_nodes: bool = False) -> list[dict]:
    """
    Return all allocated passive nodes in the loaded build.

    By default only keystones, notables, and masteries are returned —
    the nodes that meaningfully define the build. Set include_small_nodes=True
    to also include the generic small passives (+10 str, +5 life, etc.).

    If tree data is not loaded, returns the raw node IDs only.
    """
    build = _require_build()

    if build.passive_nodes:
        nodes = build.passive_nodes
        if not include_small_nodes:
            nodes = [n for n in nodes if n.is_keystone or n.is_notable or n.is_mastery]
        return [
            {
                "id": n.id,
                "name": n.name,
                "type": _node_type(n),
                "stats": n.stats,
            }
            for n in nodes
        ]
    else:
        # No tree data — return raw IDs
        return [{"id": node_id} for node_id in build.allocated_node_ids]


@mcp.tool()
def get_items() -> list[dict]:
    """
    Return all equipped items in the loaded build with their mods.

    Each item includes slot, rarity, name, base type, item level, quality, any
    socketed runes, and the list of mod lines exactly as they appear in the game
    tooltip. implicit_count is how many leading entries in mods are implicit
    (including enchants and rune-granted lines); the remainder are explicit.
    """
    build = _require_build()
    return [
        {
            "slot": item.slot,
            "rarity": item.rarity,
            "name": item.name,
            "base_type": item.base_type,
            "item_level": item.item_level,
            "quality": item.quality,
            "corrupted": item.corrupted,
            "runes": item.runes,
            "implicit_count": item.implicit_count,
            "mods": item.mods,
        }
        for item in build.items
    ]


@mcp.tool()
def get_skills() -> list[dict]:
    """
    Return all skill socket groups in the loaded build.

    Each group shows the active skill, its support gems, the slot it occupies,
    and whether it is enabled.
    """
    build = _require_build()
    return [
        {
            "slot": group.slot,
            "active_skill": group.active_skill,
            "enabled": group.enabled,
            "gems": [
                {
                    "name": gem.name,
                    "level": gem.level,
                    "quality": gem.quality,
                    "is_active": gem.is_active,
                    "enabled": gem.enabled,
                }
                for gem in group.gems
            ],
        }
        for group in build.socket_groups
    ]


@mcp.tool()
def search_passives(query: str) -> list[dict]:
    """
    Search the loaded build's allocated passives for nodes matching a keyword.

    Searches both node names and stat descriptions (case-insensitive).
    Requires tree data to be loaded; returns an error message otherwise.

    Examples:
      search_passives("life")      → all life-related nodes
      search_passives("fire")      → fire damage nodes
      search_passives("Acrobatics") → the Acrobatics keystone if allocated
    """
    build = _require_build()

    if not build.passive_nodes:
        return [{"error": "Tree data not loaded — passive search unavailable."}]

    q = query.lower()
    matches = [
        n for n in build.passive_nodes
        if q in n.name.lower() or any(q in s.lower() for s in n.stats)
    ]

    return [
        {
            "id": n.id,
            "name": n.name,
            "type": _node_type(n),
            "stats": n.stats,
        }
        for n in matches
    ]


@mcp.tool()
def search_tree(
    query: str,
    include_small_nodes: bool = False,
    classes: list[str] | None = None,
) -> list[dict]:
    """
    Search the full passive skill tree for nodes matching a keyword.

    Unlike search_passives, this searches ALL nodes in the tree — not just those
    allocated in the loaded build. Use this to discover nodes you haven't taken yet.

    Each result includes:
      - allocated: whether the node is already taken in the current build
      - ascendancy: the ascendancy class that unlocks this node, or "" for generic nodes
      - distance_from_build: minimum passive points needed to reach this node from the
        current build (null if no build is loaded or the node is unreachable)

    Use classes to restrict results to one or more class regions (Voronoi partition).
    This eliminates nodes from the opposite side of the tree that are never reachable
    in practice. Valid class names: Druid, Huntress, Mercenary, Monk, Sorceress, Warrior.

    A build does not need to be loaded. Tree data must be present.

    Examples:
      search_tree("life")                         → all life notables across the full tree
      search_tree("lightning", classes=["Monk"])  → lightning nodes near the Monk start
      search_tree("life", classes=["Monk", "Sorceress"])  → life nodes in two regions
      search_tree("Invoker")                      → all Invoker ascendancy nodes
    """
    if _tree is None:
        return [{"error": "Tree data not loaded — passive tree search unavailable."}]

    allocated_ids: set[int] = set(_build.allocated_node_ids) if _build is not None else set()

    distance_map = _build_distance_map(allocated_ids) if allocated_ids else {}

    matches = _tree.search(query, classes=classes)

    if not include_small_nodes:
        matches = [n for n in matches if n.is_keystone or n.is_notable or n.is_mastery]

    return [
        {
            "id": n.id,
            "name": n.name,
            "type": _node_type(n),
            "stats": n.stats,
            "ascendancy": n.ascendancy_name,
            "allocated": n.id in allocated_ids,
            "distance_from_build": distance_map.get(n.id),
        }
        for n in matches
    ]


@mcp.tool()
def get_reachable_nodes(
    max_distance: int = 3,
    include_small_nodes: bool = False,
    classes: list[str] | None = None,
) -> list[dict]:
    """
    Return all unallocated passive nodes reachable within max_distance steps from the current build.

    Distance 1 = adjacent to an allocated node (can be taken with the next point).
    Distance 2 = one unallocated pathing node away, and so on.

    Results are sorted by distance (closest first), then by type (keystones and
    notables before small nodes). Use this to find what is actually within reach
    before recommending passive picks.

    Use classes to restrict results to one or more class regions, filtering out nodes
    from unrelated parts of the tree. Valid class names: Druid, Huntress, Mercenary,
    Monk, Sorceress, Warrior.

    Requires both a loaded build and tree data.
    """
    if _tree is None:
        return [{"error": "Tree data not loaded."}]

    build = _require_build()
    allocated_ids = set(build.allocated_node_ids)

    reachable = _tree.nodes_within_distance(allocated_ids, max_distance)

    if not include_small_nodes:
        reachable = [(n, d) for n, d in reachable if n.is_keystone or n.is_notable or n.is_mastery]

    if classes:
        class_set = set(classes)
        reachable = [(n, d) for n, d in reachable if _tree.region_of(n.id) in class_set]

    return [
        {
            "id": n.id,
            "name": n.name,
            "type": _node_type(n),
            "stats": n.stats,
            "ascendancy": n.ascendancy_name,
            "distance_from_build": dist,
        }
        for n, dist in reachable
    ]


@mcp.tool()
def get_node(node_id: int) -> dict:
    """
    Inspect a single passive tree node by id, including its neighbors.

    Returns the node's name, type, stats, ascendancy, and class region, plus the
    list of directly connected nodes (id/name/type). Useful for navigating outward
    from a node found via search_tree. Tree data must be loaded; no build required.
    """
    if _tree is None:
        return {"error": "Tree data not loaded."}

    node = _tree.get(node_id)
    if node is None:
        return {"error": f"No node with id {node_id} in the tree."}

    allocated_ids: set[int] = set(_build.allocated_node_ids) if _build is not None else set()
    return {
        "id": node.id,
        "name": node.name,
        "type": _node_type(node),
        "stats": node.stats,
        "ascendancy": node.ascendancy_name,
        "region": _tree.region_of(node.id),
        "allocated": node.id in allocated_ids,
        "neighbors": [
            {"id": nb.id, "name": nb.name, "type": _node_type(nb)}
            for nb in _tree.neighbor_nodes(node.id)
        ],
    }


@mcp.tool()
def path_to_node(node_id: int) -> dict:
    """
    Find the shortest sequence of nodes to allocate to reach a target node.

    Computes the minimum-cost path from the current build's allocated nodes to the
    target via unallocated pathing nodes. Returns the ordered list of nodes you would
    need to take (build outward to target) and the passive-point cost (its length).

    Requires both a loaded build and tree data. If the node is already allocated the
    cost is 0; if it cannot be reached, points_required is null.
    """
    if _tree is None:
        return {"error": "Tree data not loaded."}

    build = _require_build()
    target = _tree.get(node_id)
    if target is None:
        return {"error": f"No node with id {node_id} in the tree."}

    path = _tree.shortest_path(set(build.allocated_node_ids), node_id)
    if path is None:
        return {
            "target": {"id": target.id, "name": target.name, "type": _node_type(target)},
            "points_required": None,
            "path": [],
            "message": "Target is unreachable from the current build.",
        }

    return {
        "target": {"id": target.id, "name": target.name, "type": _node_type(target)},
        "points_required": len(path),
        "path": [
            {"id": n.id, "name": n.name, "type": _node_type(n)}
            for n in path
        ],
    }


@mcp.tool()
def get_point_budget() -> dict:
    """
    Summarize how the loaded build spends its passive and ascendancy points.

    Breaks allocated nodes into normal tree points, ascendancy points, and the free
    class start node, and reports points granted by leveling (a lower bound on points
    available, since campaign quest points are not stored in the export).

    Requires a loaded build; classification needs tree data.
    """
    build = _require_build()
    return summarize_points(build, _tree)


@mcp.tool()
def analyze_defenses() -> list[dict]:
    """
    Run defensive sanity checks against the loaded build's computed stats.

    Flags uncapped or negative elemental resistances (against the build's max-resist
    stat, or the standard 75% cap), reports chaos resistance and the health pool, and
    raises a heuristic warning when Life+ES looks low for the build's level.

    Each finding has a severity (ok|warning|critical|info) and includes the underlying
    value. Findings are heuristic, not a substitute for in-game testing. Requires a
    loaded build.
    """
    build = _require_build()
    return _analyze_defenses(build)


@mcp.tool()
def get_meta_overview(league: str | None = None) -> dict:
    """
    Show the current PoE2 build meta from poe.ninja: ascendancy popularity for a league.

    Returns the league name, total tracked characters, and each ascendancy's share of
    the population with a trend indicator (1 rising, 0 flat, -1 falling). Defaults to the
    current indexed league; pass a league url (e.g. "vaal") or name to override.

    Data is from poe.ninja's public (undocumented) builds API and is cached briefly.
    No build needs to be loaded.
    """
    return poeninja.get_meta_overview(league)


@mcp.tool()
def list_top_builds(league: str | None = None, limit: int = 20) -> list[dict]:
    """
    List the top community builds on poe.ninja's ladder for a league.

    Each entry includes rank, character name, account, class/ascendancy, level, and
    headline stats (life, energy shield, effective HP, DPS — as poe.ninja displays them).
    Use the returned account + character name with load_community_build to pull the full
    build in for analysis.

    Defaults to the current indexed league; pass a league url (e.g. "vaal") to override.
    limit caps the number of rows (the ladder page holds ~100). No build needs to be loaded.
    """
    return poeninja.list_top_builds(league=league, limit=limit)


@mcp.tool()
def load_community_build(account: str, name: str, league: str | None = None) -> str:
    """
    Load a community build from poe.ninja by account and character name.

    Fetches that character's Path of Building export from poe.ninja and loads it as the
    active build, exactly as load_build would — afterwards every analysis tool (get_stats,
    get_passives, analyze_defenses, path_to_node, …) operates on it.

    Get the account and character name from list_top_builds. Pass the same league you
    listed from if it was not the default.
    """
    code = poeninja.fetch_pob_export(account, name, league=league)
    _load_build_from_xml(decode_build_code(code))
    return _loaded_build_summary(source=f"poe.ninja — {name} ({account})")


@mcp.tool()
def list_my_characters(account: str | None = None) -> list[dict]:
    """
    List your own characters from poe.ninja (across all leagues).

    Each entry has name, class/ascendancy, level, league, whether it is your current
    character, when it was last updated, and its main skills. Use a name with
    load_my_character to pull that build in for analysis.

    Pass account as "Name#1234", or set the POE2_ACCOUNT environment variable to default
    it. Your PoE profile must be public for poe.ninja to see your characters.
    """
    return poeninja.list_characters(_resolve_account(account))


@mcp.tool()
def load_my_character(name: str, account: str | None = None) -> str:
    """
    Load one of your own characters from poe.ninja by name, ready for analysis.

    No Path of Building export/paste needed — this pulls the build straight from
    poe.ninja and loads it as the active build, so every analysis tool then works on it.

    Pass account as "Name#1234" or set POE2_ACCOUNT. Note: poe.ninja can only provide a
    build for characters it has indexed on the current ladder; for others (Standard, SSF,
    fresh alts) it will say so and you'll need to export from PoB for that one.
    """
    code = poeninja.fetch_character_export(_resolve_account(account), name)
    _load_build_from_xml(decode_build_code(code))
    return _loaded_build_summary(source=f"poe.ninja — {name}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_account(account: str | None) -> str:
    acct = account or os.environ.get("POE2_ACCOUNT")
    if not acct:
        raise ValueError(
            "No PoE account configured. Pass account=\"Name#1234\", or set the "
            "POE2_ACCOUNT environment variable."
        )
    return acct

def _node_type(node: PassiveNode | TreeNode) -> str:
    if node.is_keystone:
        return "keystone"
    if node.is_notable:
        return "notable"
    if node.is_mastery:
        return "mastery"
    return "small"


def _build_distance_map(allocated_ids: set[int]) -> dict[int, int]:
    """Return a node_id → distance mapping for all nodes reachable from the build."""
    if _tree is None or not allocated_ids:
        return {}
    return {node.id: dist for node, dist in _tree.nodes_within_distance(allocated_ids, max_distance=999)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
