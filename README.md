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
| `explain_mechanic` | Durable model of a PoE2 game system (ailments, defenses, spirit, gems, …) — corrects PoE1 assumptions |
| `generate_vendor_regex` | Build-aware vendor-search regex for one slot, packed under a 50-char budget |
| `get_meta_overview` | Current build meta (ascendancy popularity) for a league, from poe.ninja |
| `list_top_builds` | Top community builds on the poe.ninja ladder |
| `load_community_build` | Load a poe.ninja ladder build by account + character name |
| `list_my_characters` | Your own characters from poe.ninja (any league) |
| `load_my_character` | Load one of your own characters by name — no PoB export needed |
| `lookup_item` | Live unique/base item lookup from the community wiki (current patch) |
| `lookup_skill` | Live active-skill lookup from the community wiki |
| `lookup_mechanic` | Live wiki page text for a mechanic — verify/refresh `explain_mechanic` |
| `wiki_search` | Resolve a name to community-wiki page titles |

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

### Mechanics knowledge

An agent reviewing a build supplies most of its mechanics reasoning from training — and that
training is contaminated with PoE1 assumptions that are *wrong* in PoE2 (armour blocks only
physical, chaos bypasses energy shield, evasion only dodges attacks, support gems are a scarce
shared pool, gems gain XP, auras reserve mana — all false today). `explain_mechanic` is the
antidote: a curated, patch-stamped model of each core system, so the agent reasons from how the
game actually behaves instead of reciting PoE1.

```
explain_mechanic()             → the index: headline PoE1 traps + every topic
explain_mechanic("defenses")   → how armour/evasion/ES/block/resists really work in PoE2
explain_mechanic("armour")     → lenient matching resolves synonyms to the right topic
```

Topics: `gems`, `spirit`, `spirit-skills`, `ailments`, `defenses`, `resistances`,
`damage-conversion`, `crit`, `charges`, `attributes`, `ascendancy`, `support-scaling`. It's
deliberately conceptual — durable rules and the PoE1 traps lead, and exact numbers (which churn
per patch) are flagged as patch-sensitive rather than asserted.

### Live wiki lookups

The vendored data and `explain_mechanic` are durable but patch-stamped and bounded to what's
shipped. `lookup_item`, `lookup_skill`, `lookup_mechanic`, and `wiki_search` close the gap with
live, current-patch data from the community wiki ([poe2wiki.net](https://www.poe2wiki.net)),
queried through its MediaWiki/Cargo API as structured JSON — no scraping, no extra dependencies.

```
lookup_item("Headhunter")      → a unique's rolled stat ranges and flavour, current patch
lookup_item("Heavy Belt")      → a base type's implicit and item class
lookup_skill("Spark")          → a skill's base stat lines, infusions, description
lookup_mechanic("Shock")       → the wiki's prose on a mechanic — verify explain_mechanic's numbers
wiki_search("energy shield")   → resolve a name to wiki page titles
```

These are the one part of the server that reaches the network per call (results are cached for an
hour); each returns an `{"error": …}` dict rather than raising if the wiki is unreachable.
`lookup_mechanic` is the deliberate complement to `explain_mechanic`: the latter gives the durable
PoE1-vs-PoE2 corrections offline, the former the live numbers to verify them against.

### Vendor regex

`generate_vendor_regex` turns the loaded build into a short alternation regex you can paste into
a vendor's search bar. Uncapped resistances, life, slot intent (movement on boots), and the active
skill's damage-type / speed scaling drive what gets included; the result is packed under a 50-char
budget (the vendor bar limit). Capped resistances are dropped automatically — fix them in-game and
the next call's regex shrinks.

```
generate_vendor_regex(slot="Gloves")    → {"regex": "Life|Fire Dam|tta.*Sp", ...}
generate_vendor_regex(slot="Boots")     → {"regex": "Life|Move|Res", ...}
generate_vendor_regex(slot="Boots", include=["minion"])  → forces a key past the slot allowlist
```

Each call also returns what was included, what was dropped (and why), and a per-entry reason so
you can see which fragment came from which need.

## Tree data

The passive tree is generated from Path of Building 2's bundled tree data (`src/TreeData/<version>/tree.lua` in the PoB2 repo) by `scripts/build_tree_data.py` — GGG publishes no official PoE2 tree JSON, and the community [passive-skill-tree-json](https://github.com/poe-tool-dev/passive-skill-tree-json) mirror is PoE1-only. Sourcing from PoB2 keeps the tree version-aligned with the gem database and the recompute engine, which track the same repo. Regenerate the bundled `data/poe2_tree.json` after a patch with `uv run python scripts/build_tree_data.py`, or point the `TREE_DATA_PATH` environment variable at an alternative file.

## Crafting data

The affix pool and base types are sourced from the [RePoE-fork PoE2 export](https://repoe-fork.github.io/poe2/) — static JSON extracted from the client (GGG ships no PoE2 data export, and poe2db has no data API). `scripts/build_craft_data.py` fetches and slims it to the bundled `data/poe2_crafting.json`. The pool drifts between patches; regenerate with `uv run python scripts/build_craft_data.py`, or point `CRAFT_DATA_PATH` at an alternative file.

## Skill & stat data

The gem database (`data/poe2_skills.json`) is generated from PoB2's `src/Data/Skills/*.lua` by `scripts/build_skill_data.py` — the same data PoB uses for its own calculations, so it carries skill tags, Spirit reservation, and each gem's flat/quality stat ids. Override with `SKILL_DATA_PATH`.

The stat-description map (`data/poe2_stat_descriptions.json`) turns those raw stat ids into the in-game line a player reads — `base_reduce_enemy_fire_resistance_% = 30` becomes "Penetrate 30% Fire Resistance". It's generated by `scripts/build_stat_data.py` from PoB2's `src/Data/StatDescriptions/*.lua`, slimmed to the ids the gem database references and split into `support`/`skill` wording scopes. `get_skill_details` and `recommend_supports` attach the rendered `text` alongside the raw `id`/`value`. It renders single- and multi-stat lines (e.g. "Adds X to Y Damage") with the game's own value transforms — milliseconds→seconds, per-minute→per-second, negate ("30% less"), and the rest (see [docs/plain-english-stat-text.md](docs/plain-english-stat-text.md)); quality stats render at the 20% cap ("Chain +2 times (at 20% quality)"); only a long tail of internal/no-display stats stays raw. Regenerate with `uv run python scripts/build_skill_data.py && uv run python scripts/build_stat_data.py` (skills first), or override with `STAT_DESC_PATH`.

## Development

```bash
uv sync          # install dependencies (including dev)
uv run pytest    # run the test suite
```
