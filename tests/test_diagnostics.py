from poe2_mcp.diagnostics import analyze_defenses, summarize_points
from poe2_mcp.pob.models import Build, Stat
from poe2_mcp.tree.loader import PassiveTree, TreeNode


def make_build(stats: list[Stat], level: int = 90, **kwargs) -> Build:
    return Build(
        class_name=kwargs.get("class_name", "Monk"),
        ascendancy=kwargs.get("ascendancy", "Invoker"),
        level=level,
        allocated_node_ids=kwargs.get("allocated_node_ids", []),
        items=[],
        socket_groups=[],
        stats=stats,
    )


def _by_stat(findings, stat):
    return next(f for f in findings if f["stat"] == stat)


def test_resistance_severities():
    build = make_build([
        Stat("FireResist", "75"),
        Stat("ColdResist", "40"),
        Stat("LightningResist", "-10"),
    ])
    findings = analyze_defenses(build)
    assert _by_stat(findings, "Fire")["severity"] == "ok"
    assert _by_stat(findings, "Cold")["severity"] == "warning"
    assert _by_stat(findings, "Lightning")["severity"] == "critical"


def test_missing_resistance_is_info_not_zero():
    build = make_build([Stat("FireResist", "75")])
    cold = _by_stat(analyze_defenses(build), "Cold")
    assert cold["severity"] == "info"
    assert cold["value"] is None  # absent != 0


def test_max_resist_override():
    build = make_build([Stat("FireResist", "80"), Stat("FireResistMax", "80")])
    fire = _by_stat(analyze_defenses(build), "Fire")
    assert fire["severity"] == "ok"


def test_overcap_reported():
    build = make_build([Stat("FireResist", "75"), Stat("FireResistOverCap", "23")])
    fire = _by_stat(analyze_defenses(build), "Fire")
    assert fire["severity"] == "ok"
    assert "overcap" in fire["message"].lower()


def test_chaos_warning_threshold():
    deep = _by_stat(analyze_defenses(make_build([Stat("ChaosResist", "-75")])), "Chaos")
    mild = _by_stat(analyze_defenses(make_build([Stat("ChaosResist", "-30")])), "Chaos")
    assert deep["severity"] == "warning"
    assert mild["severity"] == "info"


def test_low_health_pool_heuristic():
    low = make_build([Stat("Life", "1000")], level=90)
    warnings = [f for f in analyze_defenses(low) if f["stat"] == "HealthPool"]
    assert warnings and warnings[0]["severity"] == "warning"

    healthy = make_build([Stat("Life", "5000")], level=90)
    assert not [f for f in analyze_defenses(healthy) if f["stat"] == "HealthPool"]


def test_value_parsing_handles_percent_and_commas():
    build = make_build([Stat("Life", "5,200"), Stat("FireResist", "76%")])
    findings = analyze_defenses(build)
    assert _by_stat(findings, "Life")["value"] == 5200.0
    assert _by_stat(findings, "Fire")["severity"] == "ok"


def _points_tree() -> PassiveTree:
    nodes = {
        100: TreeNode(id=100, name="Monk start"),
        101: TreeNode(id=101, name="Life node"),
        102: TreeNode(id=102, name="Invoker notable", ascendancy_name="Invoker"),
    }
    return PassiveTree(nodes, class_start_ids={"Monk": 100})


def test_summarize_points_classifies_nodes():
    build = make_build([], level=92, allocated_node_ids=[100, 101, 102, 999])
    summary = summarize_points(build, _points_tree())
    assert summary["passive_points_spent"] == 1     # node 101
    assert summary["ascendancy_points_spent"] == 1   # node 102
    assert summary["class_start_nodes"] == 1         # node 100
    assert summary["unresolved_nodes"] == 1          # node 999 (not in tree)
    assert summary["points_from_levels"] == 91       # level - 1
    assert summary["allocated_total"] == 4


def test_summarize_points_without_tree():
    build = make_build([], level=10, allocated_node_ids=[1, 2, 3])
    summary = summarize_points(build, None)
    assert summary["passive_points_spent"] is None
    assert summary["allocated_total"] == 3
