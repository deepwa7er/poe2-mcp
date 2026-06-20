"""Stateless analysis helpers for the web UI backend.

These wrap the existing poe2_mcp library so the web app can render the same data
the MCP tools expose — but per-request and JSON-serializable, with no reliance on
the MCP server's module-level "loaded build" state. The tree and gem databases
are loaded once (reused from the server module) and shared read-only.
"""

from __future__ import annotations

from poe2_mcp import server  # reuses its loaded _tree / _gems (no double load)
from poe2_mcp.community import archetype, poeninja
from poe2_mcp.diagnostics import analyze_defenses, summarize_points
from poe2_mcp.pob.decoder import decode_build_code
from poe2_mcp.pob.parser import parse_build_xml


def _item(it) -> dict:
    return {
        "slot": it.slot,
        "rarity": it.rarity,
        "name": it.name,
        "base_type": it.base_type,
        "item_level": it.item_level,
        "quality": it.quality,
        "corrupted": it.corrupted,
        "runes": it.runes,
        "implicit_count": it.implicit_count,
        "mods": it.mods,
    }


def _group(g) -> dict:
    return {
        "slot": g.slot,
        "active_skill": g.active_skill,
        "enabled": g.enabled,
        "gems": [
            {"name": gm.name, "is_support": gm.is_support,
             "level": gm.level, "quality": gm.quality}
            for gm in g.gems
        ],
    }


def _node(n) -> dict:
    return {
        "id": n.id,
        "name": n.name,
        "type": "keystone" if n.is_keystone else "notable",
        "stats": list(n.stats or []),
    }


def load_build(code: str) -> dict:
    """Decode a PoB code / pobb.in link / file path and return the full bundle."""
    xml = decode_build_code(code)
    b = parse_build_xml(xml, support_detector=server._gem_db_support_detector)
    if server._tree is not None:
        b.passive_nodes = server._tree.resolve_ids(
            b.allocated_node_ids, b.class_name or None, b.ascendancy or None
        )

    nodes = [_node(n) for n in b.passive_nodes if n.is_keystone or n.is_notable]
    return {
        "summary": {
            "class": b.class_name,
            "ascendancy": b.ascendancy,
            "level": b.level,
            "items": len(b.items),
            "skill_groups": len(b.socket_groups),
            "allocated_nodes": len(b.allocated_node_ids),
        },
        "stats": [{"stat": s.name, "value": s.value} for s in b.stats],
        "items": [_item(it) for it in b.items],
        "skills": [_group(g) for g in b.socket_groups],
        "passives": nodes,
        "defenses": analyze_defenses(b),
        "points": summarize_points(b, server._tree),
        "notes": b.notes,
    }


def analyze_archetype(skill: str, support_builds: int = 12, core_threshold: float = 0.6) -> dict:
    """Core/tech skills, supports, tree nodes, and gear priorities for a skill."""
    return server.analyze_archetype(
        skill, core_threshold=core_threshold, support_builds=support_builds
    )


def analyze_class_tree(class_name: str, scan_limit: int = 80, core_threshold: float = 0.6) -> dict:
    """Core/tech passive tree nodes for a character class."""
    return server.analyze_class_tree(
        class_name, core_threshold=core_threshold, scan_limit=scan_limit
    )


# Re-exported so the chat bridge and tests can reach them without importing poeninja directly.
__all__ = ["load_build", "analyze_archetype", "analyze_class_tree",
           "archetype", "poeninja"]
