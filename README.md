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
| `get_node` | Inspect a single tree node and its directly connected neighbors |
| `path_to_node` | Shortest sequence of nodes to allocate to reach a target node, with point cost |
| `get_point_budget` | Passive/ascendancy point usage summary for the loaded build |
| `analyze_defenses` | Defensive sanity checks — uncapped/negative resistances, health pool |
| `list_mods_for_base` | The affix pool that can roll on a base — prefix/suffix, tiers, item level, spawn weight |
| `craft_advisor` | Build-aware advice for adding a stat to an item — open slots, tiers, risk-rated methods |
| `get_meta_overview` | Current build meta (ascendancy popularity) for a league, from poe.ninja |
| `list_top_builds` | Top community builds on the poe.ninja ladder |
| `load_community_build` | Load a poe.ninja ladder build by account + character name |
| `list_my_characters` | Your own characters from poe.ninja (any league) |
| `load_my_character` | Load one of your own characters by name — no PoB export needed |

### Class region filtering

`search_tree` and `get_reachable_nodes` accept a `classes` parameter that restricts results to nodes in the specified class territories. This dramatically reduces noise when exploring the tree.

Valid class names: `Druid`, `Huntress`, `Mercenary`, `Monk`, `Sorceress`, `Warrior`

```
search_tree("life", classes=["Monk"])
search_tree("lightning", classes=["Monk", "Sorceress"])
get_reachable_nodes(max_distance=5, classes=["Monk"])
```

The partition is computed at startup via a simultaneous multi-source BFS from all six class starting nodes. Each node is assigned to whichever class start is fewest steps away in the tree graph.

### Community builds

`get_meta_overview`, `list_top_builds`, and `load_community_build` surface what the
PoE2 ladder is playing, sourced from [poe.ninja](https://poe.ninja/poe2/builds). A
typical flow:

```
get_meta_overview()                              → which ascendancies are popular now
list_top_builds(limit=20)                        → the top ladder builds + headline stats
load_community_build(account="…", name="…")      → pull one in; then analyze it like any build
```

Once a community build is loaded, every analysis tool (`get_stats`, `get_passives`,
`analyze_defenses`, `path_to_node`, …) works on it.

### Your own characters

Skip the Path of Building export/paste entirely for your own builds:

```
list_my_characters()              → all your characters (name, class, level, league)
load_my_character("MyChar")       → load one straight in for analysis
```

Set the `POE2_ACCOUNT` environment variable to your account (`Name#1234`) so you don't
pass it every time, e.g. in the MCP server config:

```json
{
  "mcpServers": {
    "poe2": {
      "command": "uv",
      "args": ["--directory", "/path/to/poe2-mcp", "run", "poe2-mcp"],
      "env": { "POE2_ACCOUNT": "YourName#1234" }
    }
  }
}
```

Your PoE profile must be public. poe.ninja can only load characters it has indexed on
the current ladder; for Standard/SSF/fresh alts it lists them but asks you to export from
PoB for that one.

These tools use poe.ninja's public but **undocumented** API, so it may change without
notice. Responses are cached briefly to stay fast and to be a polite client.

### Crafting advice

The export shows an item's *rolled* mods but not the *pool* behind them. `list_mods_for_base`
and `craft_advisor` add that: which affixes can roll on a base (prefix/suffix, tiers, item
level, weight), and — for an equipped item — whether a target stat can be added, which slots
are free, and the lowest-risk way to do it. PoE2 crafting is largely additive and random, so
the open-slot question is the whole point.

```
list_mods_for_base("Sapphire Ring", keyword="cold resistance")   → the cold-res tiers a ring can roll
craft_advisor(target="cold resistance", slot="Gloves")           → can I add it to my gloves, and how?
```

`craft_advisor` ranks methods by risk (rune-in-socket, Exalt-to-open-slot with an approximate
hit chance, essence/omen, remove-and-add, replace) and is honest about its limits — slot counts
are inferred by classifying rolled mods, and it never invents rune/essence values that aren't in
the data. See [docs/crafting-advisor.md](docs/crafting-advisor.md) for details.

## Tree data

The passive tree data is sourced from the community-maintained [passive-skill-tree-json](https://github.com/poe-tool-dev/passive-skill-tree-json) repository, which mirrors the format published by Grinding Gear Games. The bundled `data/poe2_tree.json` can be replaced with a newer version by dropping a fresh file in the same location, or by pointing the `TREE_DATA_PATH` environment variable at an alternative path.

## Crafting data

The affix pool and base types are sourced from the [RePoE-fork PoE2 export](https://repoe-fork.github.io/poe2/) — static JSON extracted from the client (GGG ships no PoE2 data export, and poe2db has no data API). `scripts/build_craft_data.py` fetches and slims it to the bundled `data/poe2_crafting.json`. The pool drifts between patches; regenerate with `uv run python scripts/build_craft_data.py`, or point `CRAFT_DATA_PATH` at an alternative file.

The passive tree data is sourced from the community-maintained [passive-skill-tree-json](https://github.com/poe-tool-dev/passive-skill-tree-json) repository, which mirrors the format published by Grinding Gear Games. The bundled `data/poe2_tree.json` can be replaced with a newer version by dropping a fresh file in the same location, or by pointing the `TREE_DATA_PATH` environment variable at an alternative path.

## Development

```bash
uv sync          # install dependencies (including dev)
uv run pytest    # run the test suite
```
