---
name: poe2-engine-setup
description: Set up the headless Path of Building engine that powers the poe2-mcp recompute tools (recompute_stats, compare_dps, list_skill_groups). Use when those tools report the engine is "not available / not set up", or when the user asks to enable DPS recomputation. One-time per machine.
---

# Set up the headless PoB recompute engine

This enables `recompute_stats`, `compare_dps`, and `list_skill_groups` in the poe2-mcp
server by cloning Path of Building 2 and verifying it runs headless. It is one-time per
machine — the checkout persists in `~/.cache/poe2-mcp/pob` (override with `POB_FORK_PATH`).

## Steps

1. **Check the Lua runtime.** Run `command -v luajit`. If missing, tell the user to
   install it (`sudo dnf install luajit`, `brew install luajit`, or `apt install luajit`)
   and stop — the engine cannot run without it.

2. **Run the setup** from the repo root. It does a slim clone of PoB2 (~50 MB — code and
   data only, no textures) and self-tests by booting headless and computing a build,
   taking only a few seconds. Run it and report the result:

   ```
   uv run python scripts/setup_pob.py --selftest
   ```

3. **On success** (the self-test prints a computed `Life`/`TotalDPS`), tell the user the
   recompute tools are ready. No server restart is needed — the engine checks
   availability per call, so the next `recompute_stats` / `compare_dps` will just work.

4. **On failure**, surface the actual error and the fix:
   - clone failed → check network / `git` / disk space;
   - `luajit` not found → install it (step 1);
   - self-test failed to compute → re-run with `--force` to re-clone.

## Notes

- **Idempotent.** Re-running skips the clone if PoB is already present. Pass `--force`
  to re-clone from scratch.
- **Ref.** `POB_REF` selects the git ref (default `dev`, which has the PoE2 data — the
  `v2.x` release tags are legacy PoE1 data, so don't use those). If a build's tree
  version differs from the bundled data, recompute results carry a `note`.
- This is the only manual step; everything else (gear, gem data, config tools) works
  with no setup.
