# Crafting advisor — affix pool + build-aware craft advice

## Why

The poe.ninja / PoB export carries an item's *rolled* mods, but not the *pool* behind
them: what else could roll on that base, whether a stat is a prefix or suffix, its
tiers and item-level gating, and how likely it is. Without that, the server can't
answer the question that actually matters when gearing in PoE2 — *"can I add this stat,
and how do I do it without nuking the mods already on the item?"* PoE2 crafting is
largely additive and random, so the open-slot question is the whole game.

This feature adds that pool and a build-aware advisor on top of it.

## Data source

GGG ships no PoE2 data export, and poe2db has no data API (only a PoB build-generation
endpoint). The usable source is the **RePoE-fork PoE2 export**
(<https://repoe-fork.github.io/poe2/>) — static JSON extracted from the client, no
scraping required.

`scripts/build_craft_data.py` fetches two files and slims them to what the advisor
needs, vendoring the result as `data/poe2_crafting.json` (same offline-at-runtime
approach as `poe2_tree.json` / `poe2_skills.json`):

- **mods.json** → kept only `domain: "item"` prefixes/suffixes with a positive spawn
  weight (1,398 mods). Each keeps its type/group, prefix-vs-suffix, required level,
  cleaned tooltip `text`, and its **ordered** spawn-weight list.
- **base_items.json** → equippable bases only (967), as name → tags/class/level.

The spawn-weight order is preserved verbatim because PoE resolves a mod's weight on a
base by the **first** entry whose tag the base has (a `0` on a specific tag excludes
that base even if a broader later tag would match).

### Refreshing after a patch

```sh
uv run python scripts/build_craft_data.py
```

The affix pool drifts between patches/leagues; re-run to regenerate the vendored JSON.
Override the load path at runtime with `CRAFT_DATA_PATH`.

> The runtime MCP server must be restarted (new session) to expose the two tools after
> first adding them.

## Tools

### `list_mods_for_base(base, keyword=None, kind=None)`

The raw crafting pool for a base — independent of any loaded build.

- `base` — a base type name, e.g. `"Sapphire Ring"`, `"Adorned Gloves"`. Works best on
  Rare/Unique bases (Magic items fold the base into the name).
- `keyword` — case-insensitive filter on mod text/type/group, e.g. `"cold resistance"`.
- `kind` — `"prefix"` or `"suffix"`.

Returns `{base, item_class, groups: [...]}`; each group has its `gen`, base `spawn_weight`,
and every `tier` (`name`, `text`, `lvl`).

### `craft_advisor(target, slot=None, base=None)`

Build-aware advice for adding one stat to one item.

- `target` — a stat keyword, e.g. `"cold resistance"`, `"maximum life"`, `"attack speed"`.
- `slot` — a slot on the loaded build (`get_items`), e.g. `"Gloves"`, `"Ring 1"`.
- `base` — a base name directly, when no build is loaded (assumes a clean Rare, ilvl 100).

Returns, for the resolved item:

- `can_roll` — whether the target can roll on this base at all.
- `target_mods` — the matching mod groups with tiers, each flagged `rollable_at_ilvl`
  against the item's level, plus the `best_tier_at_ilvl`.
- `slots` — `used_prefix`/`used_suffix`, `open_prefix`/`open_suffix`, `cap_per_type`.
- `already_present` — target mod types already on the item (→ a Divine-to-improve case).
- `methods` — a ranked, risk-rated list (`none`/`low`/`medium`/`high`): rune-in-socket,
  Exalt-to-open-slot (with an approximate hit chance), essence/omen, remove-and-add,
  replace.
- `caveats` — confidence notes (see below).

#### Example

`craft_advisor(target="cold resistance", slot="Gloves")` on a Rare with no open suffix:

```
can_roll: true   target_affix_type: suffix   already_present: []
slots: prefix 3/3 (open 0), suffix 3/3 (open 0)
methods:
  [none]   Glacial Rune in an open rune socket   — grants +14% to Cold Resistance, no risk
  [high]   Remove-and-add (e.g. Chaos Orb)       — no open suffix; removal is random
  [medium] Replace the item                      — find/craft one that already rolls it
```

## How slot inference works (and its limits)

The advisor doesn't get prefix/suffix labels from the export — the game tooltip doesn't
carry them. It **classifies each rolled mod line back to the pool**: every mod's `text`
template (e.g. `+(16-20)% to Cold Resistance`) is compiled to a regex that matches a
rolled instance (`+38% to Cold Resistance`), mapping the line to its `gen` and `type`.

Consequences, surfaced in `caveats` rather than hidden:

- A mod whose wording matches no template, or matches both a prefix and a suffix, is
  left **unclassified** — open-slot counts are then approximate.
- Hybrid/exotic mods occasionally push a count past the 3-per-type cap (`overflow`);
  the item is clearly full, but the prefix/suffix split is approximate.

## Known gaps

- RePoE's PoE2 export has **no `essences.json`** — essence→mod mappings aren't available,
  so essence/omen methods are described generically.
- **Runes / soul cores** carry no granted values in the RePoE export, so they're sourced
  separately from PoB2's `ModRunes.lua` (vendored as `data/poe2_runes.json` by
  `scripts/build_rune_data.py`). The advisor quotes the **real granted line for the item's
  slot** (e.g. "+14% to Cold Resistance"), tier-ranked, with any conditional "Bonded"
  bonus — values differ by class (a Desert Rune adds Fire damage to a weapon but +Fire
  Resistance to armour), and jewellery has no rune socket so none are offered. It still
  can't see whether a specific item has a *free* socket (socket counts aren't parsed).
- Currency behaviour (how Exalt/Chaos/Divine/omens add/remove mods) is game *logic*,
  encoded in the advisor's method descriptions — not data.
