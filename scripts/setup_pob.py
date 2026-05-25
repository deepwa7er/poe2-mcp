#!/usr/bin/env python3
"""
Set up a headless Path of Building 2 environment for the P3 recompute engine.

What it does:
  1. Clones PoB2 (pinned, depth-1) to POB_FORK_PATH.
  2. Ensures a usable `lua-utf8`: if the host has the real native module it is left
     alone; otherwise the bundled pure-Lua fallback (lua/compat/lua-utf8.lua) is
     installed into the checkout's runtime/lua/ so PoB can boot. Our headless path
     never edits text, so the fallback is sufficient (see docs/p3-headless-pob.md).
  3. With --selftest, boots PoB headless, loads a sample build, and asserts it
     computes a Life value — the same correctness anchor used in the smoke test.

Usage:
  uv run python scripts/setup_pob.py             # clone + prepare
  uv run python scripts/setup_pob.py --selftest  # also run the boot/calc check
  uv run python scripts/setup_pob.py --force      # re-clone even if present

Environment:
  POB_FORK_PATH  clone root (default: ~/.cache/poe2-mcp/pob)
  POB_REF        git ref to pin (default: v2.49.3)
  POB_CMD        Lua interpreter (default: luajit)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git"
DEFAULT_REF = "v2.49.3"
DEFAULT_PATH = Path.home() / ".cache" / "poe2-mcp" / "pob"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UTF8_FALLBACK = _REPO_ROOT / "lua" / "compat" / "lua-utf8.lua"


def pob_root() -> Path:
    return Path(os.environ.get("POB_FORK_PATH") or DEFAULT_PATH)


def pob_ref() -> str:
    return os.environ.get("POB_REF") or DEFAULT_REF


def pob_cmd() -> str:
    return os.environ.get("POB_CMD") or "luajit"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def clone(force: bool) -> Path:
    root = pob_root()
    wrapper = root / "src" / "HeadlessWrapper.lua"
    if wrapper.exists() and not force:
        print(f"PoB2 already present at {root} (use --force to re-clone)")
        return root
    if root.exists():
        print(f"Removing existing {root}")
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    ref = pob_ref()
    print(f"Cloning {REPO_URL} @ {ref} (depth 1) -> {root}")
    r = _run(["git", "clone", "--depth", "1", "--single-branch", "--branch", ref, REPO_URL, str(root)])
    if r.returncode != 0:
        sys.exit(f"git clone failed:\n{r.stderr}")
    if not wrapper.exists():
        sys.exit(f"clone did not produce {wrapper}")
    sha = _run(["git", "-C", str(root), "rev-parse", "HEAD"]).stdout.strip()
    (root / "pob_version.txt").write_text(f"{ref}\n{sha}\n")
    print(f"Checked out {ref} ({sha[:12]})")
    return root


def _luajit_can_require_utf8(root: Path) -> bool:
    """True if the host already provides a real lua-utf8 (native or otherwise)."""
    rt = root / "runtime" / "lua"
    probe = (
        f'package.path="{rt}/?.lua;{rt}/?/init.lua;"..package.path;'
        'local ok=pcall(require,"lua-utf8"); os.exit(ok and 0 or 1)'
    )
    return _run([pob_cmd(), "-e", probe]).returncode == 0


def ensure_utf8(root: Path) -> None:
    target = root / "runtime" / "lua" / "lua-utf8.lua"
    if target.exists():
        print("lua-utf8 fallback already installed")
        return
    if _luajit_can_require_utf8(root):
        print("Host provides a real lua-utf8 — no fallback needed")
        return
    if not _UTF8_FALLBACK.exists():
        sys.exit(f"bundled fallback missing: {_UTF8_FALLBACK}")
    shutil.copyfile(_UTF8_FALLBACK, target)
    print(f"Installed bundled pure-Lua lua-utf8 fallback -> {target}")
    print("  (byte-oriented; fine for headless calc. Install real luautf8 for multibyte text.)")


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
    # Decode the bundled fixture into build XML using the project's own decoder.
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from poe2_mcp.pob.decoder import decode_build_code

    fixture = _REPO_ROOT / "tests" / "fixtures" / "poeninja_pob_export.txt"
    xml = decode_build_code(fixture.read_text())

    with tempfile.TemporaryDirectory() as td:
        xml_path = Path(td) / "build.xml"
        xml_path.write_text(xml)
        boot = Path(td) / "selftest.lua"
        boot.write_text(_SELFTEST_LUA)

        env = {**os.environ, "CI": "true"}
        r = subprocess.run(
            [pob_cmd(), str(boot), str(root), str(xml_path)],
            cwd=root / "src", env=env, text=True, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=120,
        )
    out = r.stdout
    life = _grep(out, "LIFE=")
    dps = _grep(out, "TOTALDPS=")
    if not life or life in ("nil", "None"):
        sys.exit(f"SELFTEST FAILED — no Life computed.\nstdout:\n{out}\nstderr:\n{r.stderr}")
    print(f"SELFTEST OK — headless PoB computed Life={life}, TotalDPS={dps}")


def _grep(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Set up headless PoB2 for the P3 engine.")
    ap.add_argument("--selftest", action="store_true", help="boot headless and assert a build computes")
    ap.add_argument("--force", action="store_true", help="re-clone even if already present")
    args = ap.parse_args()

    root = clone(args.force)
    ensure_utf8(root)
    if args.selftest:
        selftest(root)
    print(f"\nReady. Point the engine at POB_FORK_PATH={root}")


if __name__ == "__main__":
    main()
