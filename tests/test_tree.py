import json

from poe2_mcp.tree.loader import (
    PassiveTree,
    TreeNode,
    _compute_class_aliases,
    _compute_voronoi,
    load_tree,
)


def make_tree(edges: list[tuple[int, int]], **node_flags) -> PassiveTree:
    """Build a PassiveTree from an undirected edge list, with bidirectional adjacency."""
    ids = {i for edge in edges for i in edge}
    nodes = {i: TreeNode(id=i, name=f"Node{i}") for i in ids}
    for a, b in edges:
        if b not in nodes[a].neighbors:
            nodes[a].neighbors.append(b)
        if a not in nodes[b].neighbors:
            nodes[b].neighbors.append(a)
    return PassiveTree(nodes)


# Graph:  1 - 2 - 3 - 4
#                 |
#                 5
EDGES = [(1, 2), (2, 3), (3, 4), (3, 5)]


def test_shortest_path_basic():
    tree = make_tree(EDGES)
    path = tree.shortest_path({1}, 4)
    assert [n.id for n in path] == [2, 3, 4]


def test_shortest_path_branch():
    tree = make_tree(EDGES)
    path = tree.shortest_path({1}, 5)
    assert [n.id for n in path] == [2, 3, 5]


def test_shortest_path_already_allocated_is_empty():
    tree = make_tree(EDGES)
    assert tree.shortest_path({1, 2}, 2) == []


def test_shortest_path_starts_from_nearest_source():
    # With both 1 and 4 allocated, node 5 is reached via 4's side (3,5) not 1's side.
    tree = make_tree(EDGES)
    path = tree.shortest_path({1, 4}, 5)
    assert [n.id for n in path] == [3, 5]


def test_shortest_path_unknown_node_is_none():
    tree = make_tree(EDGES)
    assert tree.shortest_path({1}, 999) is None


def test_shortest_path_no_sources_is_none():
    tree = make_tree(EDGES)
    assert tree.shortest_path(set(), 4) is None


def test_nodes_within_distance():
    tree = make_tree(EDGES)
    reachable = {n.id: d for n, d in tree.nodes_within_distance({1}, 2)}
    assert reachable == {2: 1, 3: 2}  # 4 and 5 are distance 3, excluded


def test_neighbor_nodes():
    tree = make_tree(EDGES)
    assert sorted(n.id for n in tree.neighbor_nodes(3)) == [2, 4, 5]
    assert tree.neighbor_nodes(999) == []


def test_voronoi_partition_assigns_nearest_start():
    # 10(X) - 1 - 2 - 3 - 20(Y): midpoint splits toward the nearer start.
    edges = [(10, 1), (1, 2), (2, 3), (3, 20)]
    ids = {i for e in edges for i in e}
    nodes = {i: TreeNode(id=i, name=f"N{i}") for i in ids}
    for a, b in edges:
        nodes[a].neighbors.append(b)
        nodes[b].neighbors.append(a)
    voronoi = _compute_voronoi(nodes, {"X": 10, "Y": 20})
    assert voronoi == {10: "X", 1: "X", 2: "X", 3: "Y", 20: "Y"}


# --- Per-class node variants (Witch/Sorceress-style start divergence) ---------

def _switchable_node() -> TreeNode:
    """A notable that renders differently for Witch (the paired class)."""
    return TreeNode(
        id=64046,
        name="Principal Infusion",
        stats=["20% increased Elemental Infusion duration"],
        is_notable=True,
        options={
            "Witch": {"name": "Entropy", "stats": ["20% increased Chaos Damage"]},
            "Abyssal Lich": {"name": "Void Infusion", "stats": ["Gain Void"]},
        },
    )


def test_view_returns_default_when_no_class():
    tree = PassiveTree({64046: _switchable_node()})
    assert tree.view(64046).name == "Principal Infusion"


def test_view_applies_base_class_override():
    tree = PassiveTree({64046: _switchable_node()})
    v = tree.view(64046, class_name="Witch", ascendancy="Infernalist")
    assert v.name == "Entropy"
    assert v.stats == ["20% increased Chaos Damage"]
    # Override must not mutate the stored node.
    assert tree.get(64046).name == "Principal Infusion"


def test_view_default_for_paired_class_without_override():
    tree = PassiveTree({64046: _switchable_node()})
    assert tree.view(64046, class_name="Sorceress").name == "Principal Infusion"


def test_view_ascendancy_takes_priority_over_base_class():
    tree = PassiveTree({64046: _switchable_node()})
    v = tree.view(64046, class_name="Witch", ascendancy="Abyssal Lich")
    assert v.name == "Void Infusion"


def test_resolve_ids_is_class_aware():
    tree = PassiveTree({64046: _switchable_node()})
    resolved = tree.resolve_ids([64046], class_name="Witch")
    assert [n.name for n in resolved] == ["Entropy"]


def test_search_matches_resolved_class_variant():
    tree = PassiveTree({64046: _switchable_node()})
    # As a Witch, the node is "Entropy" — the default name no longer matches.
    assert [n.id for n in tree.search("Entropy", class_name="Witch")] == [64046]
    assert tree.search("Principal Infusion", class_name="Witch") == []
    # Default / paired class still sees the original.
    assert [n.id for n in tree.search("Principal Infusion")] == [64046]
    assert tree.search("Entropy") == []


def test_compute_class_aliases_groups_shared_starts():
    aliases = _compute_class_aliases(
        {"Witch": 1, "Sorceress": 1, "Ranger": 2, "Huntress": 2, "Monk": 3}
    )
    assert aliases["Witch"] == {"Witch", "Sorceress"}
    assert aliases["Sorceress"] == {"Witch", "Sorceress"}
    assert aliases["Monk"] == {"Monk"}


def test_expand_classes_includes_paired_partner():
    tree = PassiveTree(
        {1: TreeNode(id=1, name="n")},
        class_aliases={"Witch": {"Witch", "Sorceress"}, "Sorceress": {"Witch", "Sorceress"}},
    )
    assert tree.expand_classes(["Sorceress"]) == {"Witch", "Sorceress"}
    assert tree.expand_classes(["Monk"]) == {"Monk"}  # unknown -> itself


def test_load_tree_registers_paired_classes_and_parses_options(tmp_path):
    """load_tree should register both classes at a shared start, skip legacy names,
    parse dict-typed options as class overrides, and ignore list-typed options."""
    raw = {
        "classes": [{"name": "Witch"}, {"name": "Sorceress"}, {"name": "Monk"}],
        "nodes": {
            "100": {
                "name": "WITCH",
                "classesStart": ["Witch", "Sorceress"],
                "connections": [{"id": 200}],
            },
            "200": {
                "name": "Principal Infusion",
                "isNotable": True,
                "stats": ["20% increased Elemental Infusion duration"],
                "options": {"Witch": {"id": 10941, "name": "Entropy", "stats": ["20% increased Chaos Damage"]}},
                "connections": [],
            },
            "300": {
                "name": "Attribute",
                "stats": ["+5 to any Attribute"],
                "options": [
                    {"id": 1, "name": "Strength", "stats": ["+5 to Strength"]},
                    {"id": 2, "name": "Dexterity", "stats": ["+5 to Dexterity"]},
                ],
                "connections": [{"id": 200}],
            },
            "400": {"name": "SHADOW", "classesStart": ["Shadow", "Monk"], "connections": []},
        },
    }
    path = tmp_path / "tree.json"
    path.write_text(json.dumps(raw))
    tree = load_tree(path)

    # Both real classes at the shared start are registered; legacy "Shadow" is not.
    assert tree.class_start_ids["Witch"] == 100
    assert tree.class_start_ids["Sorceress"] == 100
    assert tree.class_start_ids["Monk"] == 400
    assert "Shadow" not in tree.class_start_ids

    # dict-typed options parsed as a class override; list-typed options ignored.
    assert tree.get(200).options == {
        "Witch": {"name": "Entropy", "stats": ["20% increased Chaos Damage"]}
    }
    assert tree.get(300).options == {}
    assert tree.view(200, class_name="Witch").name == "Entropy"
    assert tree.view(200, class_name="Sorceress").name == "Principal Infusion"
