"""
Locate bundled resource files (the data/ JSON exports and the lua/ driver).

Two layouts exist:
  * repo checkout / editable install — resources live at <repo>/data and
    <repo>/lua, next to src/.
  * installed wheel — the hatch config force-includes them into the package as
    poe2_mcp/_bundled/data and poe2_mcp/_bundled/lua (see pyproject.toml).

Callers get whichever exists; the repo-layout path is returned as the fallback
even when absent so error messages name a sensible location to put the file.
"""

from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).resolve().parent
_REPO = _PKG.parent.parent  # src layout: src/poe2_mcp -> repo root


def resource_path(*parts: str) -> Path:
    """Resolve e.g. resource_path("data", "poe2_tree.json") in either layout."""
    bundled = _PKG / "_bundled" / Path(*parts)
    checkout = _REPO / Path(*parts)
    return bundled if bundled.exists() else checkout
