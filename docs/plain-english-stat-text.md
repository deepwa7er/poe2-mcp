# Plain-English stat text for gems

**Status:** Built — all phases (2026-06-13). Single- and multi-stat lines render
with value transforms, and quality_stats render at the 20% cap. The prerequisite
gem enrichment landed earlier on `gem-data-enrichment`.

## What shipped

- `skills/statdesc.py` — a recursive-descent parser for PoB2's stat-description
  Lua (`parse_stat_descriptions` → `{single, multi}`), plus the runtime
  `StatDescriptions` (`render`, `render_multi`, `render_stats`) that turns a stat
  id+value into the in-game line.
- `scripts/build_stat_data.py` — fetches the three StatDescriptions files, keeps
  single- and multi-stat lines (with their value transforms), and vendors
  `data/poe2_stat_descriptions.json` slimmed to the ids `poe2_skills.json`
  references, in two scopes (`support` / `skill`), each holding `single` + `multi`.
- `GemData._enrich` calls `render_stats` over each `stats` / `quality_stats` /
  `family_tiers` list and attaches a `text` per entry; `id`/`value` are untouched,
  so existing consumers are unaffected. `get_skill_details` and `recommend_supports`
  surface it.

Coverage: ~1,135 of the ~1,138 referenced ids that have any tooltip line now render
— effectively complete on describable lines; the rest are internal/no-display stats
that correctly stay raw, plus a few lines gated on hash/index handlers we can't
resolve (omitted rather than rendered wrong).

**Phase 2 specifics:**
- *Multi-stat lines* — entries keyed by several ids (e.g. min+max damage on "Adds X
  to Y Damage"). Vendored as `multi` lists; `render_stats` keys them by member id,
  renders once when all sibling values are present, attaches the line to the first
  member, and marks the siblings consumed (their entries keep raw id/value).
- *Value transforms* — the real GGG index-handlers (`k`/`v` on each variant), not a
  heuristic: `negate` (shows "less"/"reduced" as a positive number),
  `milliseconds_to_seconds`, `per_minute_to_per_second`, `divide_by_one_hundred`,
  and the divide/double/offset family, with `_Ndp` decimal-place rounding. The old
  `*_ms`-suffix ÷1000 guess is kept only as a fallback when a line carries no handler.
  Non-numeric handlers (passive/skill/hash indices) mark a line unrenderable.

## Problem

`get_skill_details` returns a gem's mechanics as raw PoB stat ids + bare numbers:

```json
{"id": "base_reduce_enemy_fire_resistance_%", "value": 30}
```

These are correct and machine-readable, but a reader has to know PoB conventions
to interpret them (the `_final` = multiplicative "more" vs plain `_+%` = additive
"increased" trap is documented in the `get_skill_details` docstring). We want the
tool to *also* emit the in-game line so advice can quote it directly:

```json
{"id": "base_reduce_enemy_fire_resistance_%", "value": 30,
 "text": "Supported Skills Penetrate 30% Fire Resistance"}
```

This is the natural follow-on to the gem-mechanics enrichment (see
`data/poe2_skills.json`, `skills/luaparse.py`, `skills/gemdata.py`).

## Source

PoB2 ships the descriptions as **parseable Lua tables** (not the raw GGG
`.txt` format) under `src/Data/StatDescriptions/` on the `dev` branch:

| File | Size | Use |
|------|------|-----|
| `gem_stat_descriptions.lua` | ~597 KB | Primary — the scope gems declare (`statDescriptionScope = "gem_stat_descriptions"`) |
| `skill_stat_descriptions.lua` | ~705 KB | Fallback for active-skill stat ids that aren't in the gem scope |
| `stat_descriptions.lua` | ~4 MB | Last-resort master table |

Each gem's `statSets[*]` carries a `statDescriptionScope`; honor it, then fall
back down the chain above.

### Format

Each entry maps one or more `stats` ids to a set of conditional variants. Real
example (Fire Penetration I, entry `[82]`):

```lua
[82]={
  [1]={ [1]={ limit={ {1,"#"} }, text="Supported Skills Penetrate {0}% Fire Resistance" } },
  stats={ [1]="base_reduce_enemy_fire_resistance_%" }
}
```

- `stats` — the id(s) this line renders. **Most are single-id** (the easy case);
  some lines need several ids together (e.g. min+max damage on one line).
- each variant has:
  - `limit` — per-stat value gates: `{1,"#"}` = ≥1, `{"#",-1}` = ≤-1, `{"#","#"}`
    = any. Pick the first variant whose limits all match the value(s).
  - `text` — template with `{0}`, `{1}`, … placeholders, optionally with a format
    spec, e.g. `{0:+d}` = force sign ("Chain +6 times"). The template encodes the
    wording ("Penetrate" / "more" / "increased"), so rendering it *also* resolves
    the `_final`-vs-`_+%` distinction for free.

## Implementation sketch

**Build-time**
- New `skills/statdesc.py`: parse the description `.lua` into
  `{stat_id: [{stats, variants:[{limit, text}]}]}` (reuse `luaparse.py`'s
  string-aware brace matching).
- New build step (extend `scripts/build_skill_data.py` or add
  `scripts/build_stat_data.py`): fetch the description files, parse, and vendor
  `data/poe2_stat_descriptions.json` **slimmed to only the stat ids actually
  referenced by `poe2_skills.json`** (intersect) to keep size down.

**Runtime**
- `render(stat_id, value, scope) -> str | None`: select the variant by `limit`,
  substitute placeholders honoring format specs.
- `GemData._enrich`: attach `text` to every `stats` / `quality_stats` entry and to
  the entries inside `family_tiers`. Keep `id`/`value` untouched so nothing that
  consumes the current shape breaks.
- Document coverage limits in the `get_skill_details` docstring; keep the existing
  `_final` legend as the fallback for unrendered ids.

## Coverage & known limits

| Case | Handling |
|------|----------|
| Single-stat lines (most supports: penetration, more-multipliers, added stats) | **Full** — Phase 1 |
| Value transforms (ms→s, ÷100, negate wording) | Phase 2; until then render the raw number and flag it |
| Multi-stat lines (siblings share one line, e.g. min+max damage) | We don't always have all sibling values together → fall back to `id`; partial |
| `quality_stats` (value is per point of quality) | Phrase as "per 20% quality" or render the gradient — Phase 3 |
| Dummy/internal ids (`dummy_stat_display_nothing`) | No entry → omit `text` |

## Phasing

- **Phase 1** — single-stat rendering (+ the ms→s transform). DONE.
- **Phase 2** — full value transforms (GGG `k`/`v` index-handlers) + multi-stat
  lines (siblings sharing one line, e.g. min+max damage). DONE.
- **Phase 3** — quality-gradient phrasing. DONE. `render_stats(..., quality=True)`
  scales a per-1%-quality value to the 20% cap and tags the line "(at 20% quality)"
  (e.g. `number_of_chains` 0.1 → "Chain +2 times (at 20% quality)"). The raw
  per-point `value` is preserved; only `text` shows the at-cap payoff. Runtime-only —
  no data regeneration needed.

## Related

- `data-gaps-roadmap` memory — the broader map of what the tools can/can't answer.
- `poe2-gem-mechanics` memory — how to interpret the raw stat ids today (the
  fallback this feature would supersede for rendered lines).
- The crafting side has the analogous gap: RePoE ships no `stat_translations.json`
  for PoE2, so `craft_advisor` rune values are name-only. A PoE2 stat-id→text
  renderer built here could later help there too.
