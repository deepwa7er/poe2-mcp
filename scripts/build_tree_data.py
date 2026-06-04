#!/usr/bin/env python3
"""
Generate data/poe2_tree.json from Path of Building 2's bundled tree data.

PoB2 ships the passive tree as a Lua table at src/TreeData/<version>/tree.lua —
the GGG export reshaped into Lua, carrying exactly the fields load_tree() reads
(nodes keyed by id, each with name/stats/connections[].id/ascendancyName/
isKeystone/isNotable/classesStart). GGG publishes no official PoE2 tree JSON and
the poe-tool-dev mirror is PoE1-only, so PoB2 is the practical source — and it is
the SAME repo (and ref) the skill DB and recompute engine already track, so the
tree stays version-aligned with them.

We can't just download tree.lua (the loader wants JSON), and hand-parsing 2 MB of
Lua is fragile, so we let Lua do it: luajit dofile()s the table and encodes it
with the dkjson that ships in the headless PoB clone. The result is the loader's
schema verbatim; we inject a top-level "_meta" block (which load_tree ignores) so
the file is version-stamped like data/poe2_skills.json and data/poe2_crafting.json.

Run from the repo root:

    uv run python scripts/build_tree_data.py

This is a build-time tool — the only part of the project that fetches tree.lua.
Re-run it to refresh the tree after a PoE2 patch; the result is vendored as JSON
so the server stays offline and fast at runtime. The PoB clone is fetched on
demand if missing (same ~50 MB slim clone the recompute engine uses).

Environment:
  POB_TREE_VERSION  pin a TreeData version dir (e.g. "0_5"); default: latest found
  POB_FORK_PATH     PoB clone root (default: ~/.cache/poe2-mcp/pob)
  POB_REF           git ref for the data (default: dev)
  POB_CMD           Lua interpreter (default: luajit)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from poe2_mcp.pob_engine.setup import (  # noqa: E402
    DEFAULT_REF, SetupError, default_root, ensure_pob,
)
from poe2_mcp.tree.loader import load_tree  # noqa: E402

REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
OUT = Path(__file__).resolve().parent.parent / "data" / "poe2_tree.json"

_VERSION_DIR = re.compile(r"^\d+_\d+$")  # "0_5" — a PoE2 patch tree, not "legion"

# luajit dofile()s the tree table and encodes it with the PoB clone's dkjson.
# tree.lua is a standalone `return {...}` literal, so no PoB runtime is needed
# beyond the JSON encoder on package.path.
_CONVERT_LUA = """\
local root, treefile = arg[1], arg[2]
package.path = root.."/runtime/lua/?.lua;"..package.path
local dkjson = require("dkjson")
local tree = dofile(treefile)
io.write(dkjson.encode(tree))
"""


def pob_cmd() -> str:
    return os.environ.get("POB_CMD") or "luajit"


def pob_ref() -> str:
    return os.environ.get("POB_REF") or DEFAULT_REF


def latest_version(client: httpx.Client, ref: str) -> str:
    """Return the highest N_M TreeData version dir (e.g. '0_5'), honoring POB_TREE_VERSION."""
    pinned = os.environ.get("POB_TREE_VERSION")
    if pinned:
        return pinned
    url = f"https://api.github.com/repos/{REPO}/contents/src/TreeData?ref={ref}"
    entries = client.get(url, headers={"Accept": "application/vnd.github+json"}).raise_for_status().json()
    versions = [e["name"] for e in entries if e["type"] == "dir" and _VERSION_DIR.match(e["name"])]
    if not versions:
        sys.exit("No N_M TreeData version dirs found — did the PoB repo layout change?")
    # Sort numerically by (major, minor) so 0_10 > 0_5.
    return max(versions, key=lambda v: tuple(int(p) for p in v.split("_")))


def convert(root: Path, tree_lua: Path) -> dict:
    """luajit-encode tree.lua to JSON via the clone's dkjson, returning the parsed dict."""
    with tempfile.TemporaryDirectory() as td:
        boot = Path(td) / "convert.lua"
        boot.write_text(_CONVERT_LUA)
        r = subprocess.run(
            [pob_cmd(), str(boot), str(root), str(tree_lua)],
            text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
        )
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"luajit conversion failed (exit {r.returncode}):\n{r.stderr}")
    return json.loads(r.stdout)


def main() -> None:
    ref = pob_ref()
    root = default_root()
    try:
        ensure_pob(root, ref=ref, cmd=pob_cmd())  # need the clone's dkjson + luajit runtime
    except SetupError as e:
        sys.exit(f"PoB setup failed: {e}")

    with httpx.Client(timeout=120, follow_redirects=True) as c:
        version = latest_version(c, ref)
        url = f"https://raw.githubusercontent.com/{REPO}/{ref}/src/TreeData/{version}/tree.lua"
        print(f"fetching TreeData/{version}/tree.lua …")
        tree_src = c.get(url).raise_for_status().text

    with tempfile.TemporaryDirectory() as td:
        tree_lua = Path(td) / "tree.lua"
        tree_lua.write_text(tree_src)
        tree = convert(root, tree_lua)

    nodes = tree.get("nodes") or {}
    if not nodes:
        sys.exit("Converted tree has no nodes — aborting before overwriting the good file.")
    tree["_meta"] = {
        "source": f"{REPO}@{ref}/src/TreeData/{version}/tree.lua",
        "tree_version": version.replace("_", "."),
        "generated": date.today().isoformat(),
        "node_count": len(nodes),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(tree, ensure_ascii=False, indent=0))

    # Validate through the real loader before declaring success.
    parsed = load_tree(OUT)
    classes = parsed.class_names()
    print(
        f"Wrote {len(nodes)} nodes (tree {version.replace('_', '.')}) to {OUT} "
        f"({OUT.stat().st_size // 1024} KB)\n"
        f"  loader parsed {len(parsed)} nodes, {len(classes)} classes: {', '.join(classes)}"
    )


if __name__ == "__main__":
    main()
