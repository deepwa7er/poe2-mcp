# P3 — Headless Path of Building for recomputed DPS

## Why

`get_stats` reads the `<PlayerStat>` values baked into the poe.ninja export, computed
under that export's saved `<Config>` (see `get_config`). For a charge/ailment build
those assumptions are usually "unbuffed" — power charges off, enemy not shocked — so
the DPS looks far lower than real combat. We cannot *recompute* under different
assumptions without running Path of Building's calculation engine.

P3 runs PoB2 headless so we can load a build, flip config inputs (charges, enemy
shocked, Charged Staff active, …), and read back the recomputed stats.

## Proven feasible (smoke test, 2026-05-24)

A real build ran end-to-end on this machine:

- `luajit` + a depth-1 clone of `PathOfBuilding-PoE2@dev` (~574 MB, data-heavy)
- `dofile("src/HeadlessWrapper.lua")` → `loadBuildFromXML(xml)` (takes our decoder's
  XML directly — the `Deflate`/`Inflate` stubs never matter)
- read `build.calcsTab.mainOutput.TotalDPS`

Result: `TotalDPS 360308`, `Life 3627` — and the Life **matched poe.ninja's published
value** for that build, confirming the engine computes correct numbers. Init ~1 s.

### Bootstrap recipe / gotchas

- Run from inside `src/` (relative `dofile`/`LoadModule`).
- `package.path` must include both `runtime/lua/?.lua` **and** `runtime/lua/?/init.lua`
  (`sha1` is a directory module).
- Feed stdin from `/dev/null`: the wrapper blocks on `io.read` if `mainObject.promptMsg`
  is set.
- Native deps: `lcurl` is already stubbed by the wrapper; `sha1` is pure-Lua in the
  runtime; **`lua-utf8` needs `luautf8.so`** — the only real native dependency to
  package (smoke test used an ASCII shim; production must vendor/install it).
- Config recompute path (verified in source): set `build.configTab.input[name]` →
  `build.configTab:BuildModList()` → `build.buildFlag = true` → `runCallback("OnFrame")`
  → read `build.calcsTab.mainOutput`.

## Architecture

```
MCP server (Python)                    warm LuaJIT process
┌─────────────────────┐   stdio JSON   ┌──────────────────────┐
│ PobEngine client    │◀──────────────▶│ pob_driver.lua       │
│  spawn/restart/timeout│  {cmd,args}   │  HeadlessWrapper +   │
│  recompute_stats()  │   {ok,output}  │  load/set_config/calc│
└─────────────────────┘                └──────────────────────┘
```

One long-lived daemon pays the ~1 s init once; each request loads XML, applies config
overrides, recomputes, returns stats. Requests are serialized (single process).

### Principles

- **Opt-in & non-fatal**: the server works without the engine. Recompute tools report
  "engine not configured" when `PobEngine.available()` is false; P0/P1/P1.5 are
  unaffected.
- **Out-of-repo dependency**: the 574 MB PoB2 checkout is fetched by a setup script to
  `POB_FORK_PATH` (default `~/.cache/poe2-mcp/pob`), never committed.
- **Correctness anchor**: tests assert recomputed `Life` ≈ the build's stored `Life`.

### Env vars

| Var | Meaning | Default |
|---|---|---|
| `POB_FORK_PATH` | PoB2 clone root (contains `src/` and `runtime/`) | `~/.cache/poe2-mcp/pob` |
| `POB_REF` | git ref to clone (the PoE2 data is on `dev`; v2.x tags are legacy PoE1) | `dev` |
| `POB_CMD` | Lua interpreter | `luajit` |
| `POB_TIMEOUT_MS` | per-request timeout | `10000` |
| `POB_DRIVER` | override path to `pob_driver.lua` | repo `lua/pob_driver.lua` |

## Usage

**No manual setup is needed.** On the first call to a recompute tool, the engine
auto-fetches PoB if it's missing — a slim ~50 MB clone (code and data only, no
textures) that takes a few seconds, cached in `~/.cache/poe2-mcp/pob`. The only host
requirement is **LuaJIT** on `PATH`; if it's missing the tools say so. Disable
auto-fetch with `POB_AUTOSETUP=0`.

The script is optional — for pre-fetching (e.g. before going offline), re-cloning after
a PoB update (`--force`), or verifying the install boots:

```bash
uv run python scripts/setup_pob.py --selftest
```

With a build loaded, the MCP tools recompute against it:

- `list_skill_groups()` — the build's skill groups as PoB indexes them (index, skill
  name, is_main); use it to find the `skill` argument below.
- `recompute_stats(config_overrides, stats, skill)` — run PoB under arbitrary `<Config>`
  overrides (keys from `get_config`), e.g. `{"usePowerCharges": true,
  "conditionEnemyShocked": true}`. `skill` (1-based index or name, e.g. "Falling
  Thunder") targets a specific skill group; defaults to the build's main skill.
- `compare_dps(preset, skill)` — `unbuffed` vs a preset (`charges` / `shocked` /
  `combat`), returning both DPS values and the delta, for the chosen skill.

If `POB_FORK_PATH` is unset/missing, these tools return `{available: false}` with
setup instructions; the rest of the server is unaffected.

Results are cached per `(build, overrides, stats, skill_group)`, so repeated calls
skip the round-trip. When a build's tree version differs from the bundled PoB data,
responses include a `note` flagging that some passives may not map (pin `POB_REF` to
the matching league to remove it).

## Milestones

Each is independently shippable; the riskiest unknown is killed first.

### M0 — De-risk config override (spike) ✅ DONE (2026-05-24)
Prove that flipping a config input moves the number. Find the recompute trigger and the
active-skill selection (`build.mainSocketGroup`).
**Acceptance:** same build yields different DPS for charges/shock on vs off. *If this
fails, stop and reassess.*
**Result — PASSED.** Same build: baseline `TotalDPS 360309`; with `conditionEnemyShocked
= true` (via `configTab.input` → `BuildModList` → `buildFlag` → `OnFrame`) → `464798`
(**+29%**). The recomputed output responds to config overrides as designed.

### M1 — Reproducible environment (`scripts/setup_pob.py`) ✅ DONE
Clone PoB2 pinned to a commit to `POB_FORK_PATH`; resolve `lua-utf8` (luarocks, with a
documented prebuilt-`.so` fallback); self-test that loads a sample build and asserts Life.
**Acceptance:** `setup_pob.py --selftest` exits 0 on a clean machine; version recorded.

### M2 — Lua stdio driver (`lua/pob_driver.lua`) ✅ DONE
Owns the bootstrap; line-delimited JSON protocol: `ping`, `load{xml}`,
`set_config{overrides}`, `select_skill{group}`, `get_output{stats}`, `shutdown`. Every
command wrapped in `pcall` so a bad build can't kill the daemon.
**Acceptance:** piping JSON lines returns correct stats; malformed build → error
response, not a crash.

### M3 — Python engine client (`src/poe2_mcp/pob_engine/`) ✅ DONE
`PobEngine`: spawn, request/response with timeout, auto-restart on crash/timeout, lazy
start, `available()` probe, clean shutdown.
**Acceptance:** unit tests (framing/timeout/restart, fake subprocess) + one integration
test gated on `POB_FORK_PATH` asserting recomputed Life ≈ stored Life.

### M4 — MCP tools + presets ✅ DONE
`recompute_stats(config_overrides)` and `compare_dps(preset)` (e.g. `combat` = power
charges max + enemy shocked + crit recently). Preset knob names come from P1.5's
`get_config` vocabulary. Tools no-op gracefully when the engine is unavailable.
**Acceptance:** `compare_dps("combat")` returns two DPS values differing in the expected
direction.

### M5 — Robustness, caching, docs ✅ DONE
Cache by `(build, overrides, stats, skill_group)`; surface tree-version drift by
comparing the build's `spec.treeVersion` with PoB's `latestTreeVersion`; usage docs
above.
**Acceptance:** repeated identical calls hit cache (return the same object); a build
whose tree version differs from the bundled data gets a `note`.

## Risks

| Risk | Mitigation |
|---|---|
| Config override doesn't recalc | M0 kills it first |
| `luautf8` native build on user machines | setup script + documented prebuilt `.so` |
| 574 MB dependency | out of repo; setup script to cache path |
| PoB data vs league drift | pin PoB version; surface "missing node" notes |
| Daemon hang/crash | timeout + auto-restart; failure ≠ server failure |
| Config input names shift across PoB versions | validate overrides against `get_config` keys |

## Sequencing

M0 → M1 → M2 → M3 → M4 → M5. M0 is the gate; M2+M3 are the bulk. Rough total ~1–1.5
weeks part-time, front-loaded by the M0 spike.
