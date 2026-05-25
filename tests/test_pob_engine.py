import os
from pathlib import Path

import pytest

from poe2_mcp.pob.decoder import decode_build_code
from poe2_mcp.pob_engine import PobEngine, PobEngineError

FIXTURES = Path(__file__).parent / "fixtures"

_root = os.environ.get("POB_FORK_PATH")
_pob_available = bool(_root) and (Path(_root) / "src" / "HeadlessWrapper.lua").exists()


def test_unavailable_engine_reports_and_errors(tmp_path):
    eng = PobEngine(root=tmp_path)
    assert eng.available() is False
    with pytest.raises(PobEngineError):
        eng.recompute("<PathOfBuilding/>")


@pytest.mark.skipif(not _pob_available, reason="set POB_FORK_PATH to a PoB2 checkout to run")
def test_recompute_integration():
    xml = decode_build_code((FIXTURES / "poeninja_pob_export.txt").read_text())
    eng = PobEngine()
    try:
        base = eng.recompute(xml, stats=["TotalDPS", "Life"])
        assert base["Life"] > 0                      # correctness anchor
        buffed = eng.recompute(xml, overrides={"conditionEnemyShocked": True}, stats=["TotalDPS"])
        assert buffed["TotalDPS"] > base["TotalDPS"]  # shock raises damage taken
        assert eng.ping() is True                     # daemon stayed warm across calls
    finally:
        eng.close()


def _server_tool(name):
    from poe2_mcp import server
    tool = getattr(server, name)
    return server, getattr(tool, "fn", tool)  # unwrap the FastMCP tool object


def test_compare_dps_unknown_preset_no_engine_needed():
    # Preset validation and server import work without the headless engine.
    server, compare = _server_tool("compare_dps")
    server._load_build_from_xml(decode_build_code((FIXTURES / "poeninja_pob_export.txt").read_text()))
    res = compare(preset="definitely-not-a-preset")
    assert "available_presets" in res and "combat" in res["available_presets"]


@pytest.mark.skipif(not _pob_available, reason="set POB_FORK_PATH to a PoB2 checkout to run")
def test_server_compare_dps_integration():
    server, compare = _server_tool("compare_dps")
    server._load_build_from_xml(decode_build_code((FIXTURES / "poeninja_pob_export.txt").read_text()))
    res = compare(preset="shocked")
    assert res["available"] is True
    assert res["preset_dps"] >= res["baseline_dps"] > 0
