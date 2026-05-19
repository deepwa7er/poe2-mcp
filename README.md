# poe2-mcp

An MCP server for Path of Exile 2 build analysis. Load a build from a [Path of Building](https://github.com/PathOfBuildingCommunity/PathOfBuilding) export code and interrogate it with natural language via any MCP-compatible client (Claude Desktop, Claude Code, etc.).

## What it does

- Decodes PoB export codes (the long base64 string from *File → Share → Copy code*) or `pobb.in` share links
- Exposes stats, passives, items, and skills as MCP tools
- Searches the full PoE2 passive skill tree, including nodes not yet allocated
- Filters tree searches to a specific class region using a Voronoi partition — so `search_tree("life", classes=["Monk"])` returns only nodes in the Monk area rather than all 4,700 nodes in the tree

## Installation

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/deepwa7er/poe2-mcp.git
cd poe2-mcp
uv sync
```

## Claude Desktop setup

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "poe2": {
      "command": "uv",
      "args": ["--directory", "/path/to/poe2-mcp", "run", "poe2-mcp"]
    }
  }
}
```

## Claude Code setup

```bash
claude mcp add poe2 -- uv --directory /path/to/poe2-mcp run poe2-mcp
```

## Tools

| Tool | Description |
|---|---|
| `load_build` | Load a PoB export code or `pobb.in` URL |
| `get_stats` | Character stats — life, mana, DPS, resistances, etc. |
| `get_passives` | Allocated passive nodes with names and stat descriptions |
| `get_items` | Equipped items and their mods |
| `get_skills` | Skill socket groups and gem links |
| `search_passives` | Keyword search within allocated passives |
| `search_tree` | Keyword search across the full passive tree |
| `get_reachable_nodes` | Unallocated nodes reachable within N steps from the current build |

### Class region filtering

`search_tree` and `get_reachable_nodes` accept a `classes` parameter that restricts results to nodes in the specified class territories. This dramatically reduces noise when exploring the tree.

Valid class names: `Druid`, `Huntress`, `Mercenary`, `Monk`, `Sorceress`, `Warrior`

```
search_tree("life", classes=["Monk"])
search_tree("lightning", classes=["Monk", "Sorceress"])
get_reachable_nodes(max_distance=5, classes=["Monk"])
```

The partition is computed at startup via a simultaneous multi-source BFS from all six class starting nodes. Each node is assigned to whichever class start is fewest steps away in the tree graph.

## Tree data

The passive tree data is sourced from the community-maintained [passive-skill-tree-json](https://github.com/poe-tool-dev/passive-skill-tree-json) repository, which mirrors the format published by Grinding Gear Games. The bundled `data/poe2_tree.json` can be replaced with a newer version by dropping a fresh file in the same location, or by pointing the `TREE_DATA_PATH` environment variable at an alternative path.
