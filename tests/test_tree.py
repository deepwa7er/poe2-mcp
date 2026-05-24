from poe2_mcp.tree.loader import PassiveTree, TreeNode, _compute_voronoi


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
