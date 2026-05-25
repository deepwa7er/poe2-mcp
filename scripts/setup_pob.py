#!/usr/bin/env python3
"""
Manually fetch + prepare the headless Path of Building 2 environment.

This is OPTIONAL: the MCP server auto-sets-up on first use of a recompute tool
(the fetch is a slim ~50 MB / few seconds). Use this script to pre-fetch (e.g.
before going offline), to re-clone after a PoB update (--force), or to verify the
install boots and computes (--selftest). The actual fetch logic lives in
poe2_mcp.pob_engine.setup and is shared with the server.

Usage:
  uv run python scripts/setup_pob.py             # fetch if missing
  uv run python scripts/setup_pob.py --selftest  # also boot headless and assert a build computes
  uv run python scripts/setup_pob.py --force      # re-clone even if present

Environment:
  POB_FORK_PATH  clone root (default: ~/.cache/poe2-mcp/pob)
  POB_REF        git ref (default: dev — the PoE2 data; v2.x tags are legacy PoE1)
  POB_CMD        Lua interpreter (default: luajit)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from poe2_mcp.pob_engine.setup import (  # noqa: E402
    DEFAULT_REF, SetupError, default_root, ensure_pob, is_set_up,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def pob_cmd() -> str:
    return os.environ.get("POB_CMD") or "luajit"


def pob_ref() -> str:
    return os.environ.get("POB_REF") or DEFAULT_REF


_SELFTEST_LUA = """\
io.stdout:setvbuf("no")
local root = arg[1]
package.path = root.."/runtime/lua/?.lua;"..root.."/runtime/lua/?/init.lua;"..package.path
dofile("HeadlessWrapper.lua")
if mainObject and mainObject.promptMsg then print("PROMPT="..tostring(mainObject.promptMsg)); os.exit(3) end
local f = assert(io.open(arg[2], "r")); local xml = f:read("*a"); f:close()
loadBuildFromXML(xml, "selftest")
local out = build and build.calcsTab and build.calcsTab.mainOutput
print("LIFE="..tostring(out and out.Life))
print("TOTALDPS="..tostring(out and out.TotalDPS))
"""


def selftest(root: Path) -> None:
    from poe2_mcp.pob.decoder import decode_build_code

    fixture = _REPO_ROOT / "tests" / "fixtures" / "poeninja_pob_export.txt"
    xml = decode_build_code(fixture.read_text())
    with tempfile.TemporaryDirectory() as td:
        xml_path = Path(td) / "build.xml"
        xml_path.write_text(xml)
        boot = Path(td) / "selftest.lua"
        boot.write_text(_SELFTEST_LUA)
        r = subprocess.run(
            [pob_cmd(), str(boot), str(root), str(xml_path)],
            cwd=root / "src", env={**os.environ, "CI": "true"}, text=True,
            capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
        )
    life = _grep(r.stdout, "LIFE=")
    if not life or life in ("nil", "None"):
        sys.exit(f"SELFTEST FAILED — no Life computed.\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    print(f"SELFTEST OK — headless PoB computed Life={life}, TotalDPS={_grep(r.stdout, 'TOTALDPS=')}")


def _grep(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch/prepare headless PoB2 for the recompute engine.")
    ap.add_argument("--selftest", action="store_true", help="boot headless and assert a build computes")
    ap.add_argument("--force", action="store_true", help="re-clone even if already present")
    args = ap.parse_args()

    root = default_root()
    ref = pob_ref()
    try:
        if is_set_up(root) and not args.force:
            print(f"PoB2 already present at {root} (use --force to re-clone)")
            ensure_pob(root, ref=ref, cmd=pob_cmd())  # ensures the utf8 fallback too
        else:
            print(f"Fetching PoB2 @ {ref} (slim, code+data only) -> {root}")
            ensure_pob(root, ref=ref, cmd=pob_cmd(), force=args.force)
            print("Done.")
    except SetupError as e:
        sys.exit(f"setup failed: {e}")

    if args.selftest:
        selftest(root)
    print(f"\nReady. POB_FORK_PATH={root}")


if __name__ == "__main__":
    main()
