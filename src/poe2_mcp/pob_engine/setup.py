"""
Fetch and prepare a headless Path of Building 2 environment.

Shared by the engine (auto-setup on first use) and scripts/setup_pob.py (manual CLI).

The fetch is deliberately slim: a blobless partial clone plus a sparse-checkout that
drops everything headless calc never touches — textures (.zst/.dds/...), fonts, platform
binaries, and zips. Image loads are no-ops under HeadlessWrapper, so none of it is
needed. This takes the working tree from ~574 MB to ~50 MB (a few seconds).

The PoE2 data lives on the `dev` branch; the v2.x release tags carry legacy PoE1 tree
data, so `dev` is the default ref.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git"
DEFAULT_REF = "dev"
DEFAULT_PATH = Path.home() / ".cache" / "poe2-mcp" / "pob"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UTF8_FALLBACK = _REPO_ROOT / "lua" / "compat" / "lua-utf8.lua"

# Take everything except files headless calc never uses (see module docstring).
_SPARSE_PATTERNS = [
    "/**",
    "!**/*.dds", "!**/*.png", "!**/*.jpg", "!**/*.jpeg", "!**/*.gif",
    "!**/*.ico", "!**/*.bmp", "!**/*.ttf",
    "!**/*.dll", "!**/*.dylib", "!**/*.so", "!**/*.zip",
    "!**/*.zst",  # zstd-compressed .dds tree/ascendancy textures (the bulk of TreeData)
]


class SetupError(RuntimeError):
    """Raised when fetching/preparing the PoB checkout fails."""


def default_root() -> Path:
    return Path(os.environ.get("POB_FORK_PATH") or DEFAULT_PATH)


def is_set_up(root: str | Path) -> bool:
    return (Path(root) / "src" / "HeadlessWrapper.lua").exists()


def _git(args: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], text=True, capture_output=True)
    if r.returncode != 0:
        raise SetupError(f"git {' '.join(args[:3])} failed:\n{r.stderr.strip()}")
    return r


def clone(root: str | Path, ref: str = DEFAULT_REF, force: bool = False) -> bool:
    """Slim-clone PoB to `root`. Returns True if a clone happened, False if already
    present (and not forced)."""
    root = Path(root)
    if is_set_up(root) and not force:
        return False
    if root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    # Blobless, no working tree yet — fast and fetches no file contents.
    _git(["clone", "--filter=blob:none", "--depth", "1", "--single-branch",
          "--branch", ref, "--no-checkout", REPO_URL, str(root)])
    # Restrict to non-binary files, then check out (fetches only those blobs).
    _git(["-C", str(root), "sparse-checkout", "set", "--no-cone", *_SPARSE_PATTERNS])
    _git(["-C", str(root), "checkout"])
    if not is_set_up(root):
        raise SetupError(f"clone did not produce src/HeadlessWrapper.lua in {root}")
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         text=True, capture_output=True).stdout.strip()
    (root / "pob_version.txt").write_text(f"{ref}\n{sha}\n")
    return True


def ensure_utf8(root: str | Path, cmd: str = "luajit") -> None:
    """Install the bundled pure-Lua lua-utf8 fallback unless a real one is available."""
    target = Path(root) / "runtime" / "lua" / "lua-utf8.lua"
    if target.exists():
        return
    rt = Path(root) / "runtime" / "lua"
    probe = (f'package.path="{rt}/?.lua;{rt}/?/init.lua;"..package.path;'
             'os.exit(pcall(require,"lua-utf8") and 0 or 1)')
    if shutil.which(cmd) and subprocess.run([cmd, "-e", probe], capture_output=True).returncode == 0:
        return  # host already provides a real lua-utf8
    if not _UTF8_FALLBACK.exists():
        raise SetupError(f"bundled lua-utf8 fallback missing: {_UTF8_FALLBACK}")
    shutil.copyfile(_UTF8_FALLBACK, target)


def ensure_pob(root: str | Path | None = None, ref: str = DEFAULT_REF,
               cmd: str = "luajit", force: bool = False) -> bool:
    """Make `root` a ready headless-PoB checkout (clone if needed + utf8 fallback).
    Returns True if a clone was performed. Raises SetupError on failure."""
    root = Path(root) if root is not None else default_root()
    did_clone = clone(root, ref=ref, force=force)
    ensure_utf8(root, cmd)
    return did_clone
