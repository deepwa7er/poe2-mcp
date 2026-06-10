"""
Load the PoE2 passive skill tree JSON and resolve node IDs to names/stats.

The tree JSON ships with the game client and is also maintained by the
community at https://github.com/poe-tool-dev/passive-skill-tree-json.

To use passive name/stat resolution, point TREE_DATA_PATH at a local copy
of the PoE2 tree JSON (e.g. data/poe2_tree.json), or call load_tree() with
an explicit path. The server works without tree data — passive queries will
return node IDs only.
"""

import json
import os
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path

from .._resources import resource_path


@dataclass
class TreeNode:
    id: int
    name: str
    stats: list[str] = field(default_factory=list)
    is_keystone: bool = False
    is_notable: bool = False
    is_mastery: bool = False
    ascendancy_name: str = ""
    neighbors: list[int] = field(default_factory=list)
    # Per-class node overrides: class/ascendancy name -> {"name", "stats"}.
    # Two PoE2 classes share each attribute start (e.g. Witch+Sorceress), and the
    # nodes near that start differ per class — the same node id renders as a
    # different name/stats depending on which of the pair you are. Empty for the
    # ~99% of nodes that are class-agnostic.
    options: dict[str, dict] = field(default_factory=dict)


class PassiveTree:
    def __init__(
        self,
        nodes: dict[int, TreeNode],
        voronoi: dict[int, str] | None = None,
        class_start_ids: dict[str, int] | None = None,
        class_aliases: dict[str, set[str]] | None = None,
    ):
        self._nodes = nodes
        self._voronoi: dict[int, str] = voronoi or {}
        self.class_start_ids: dict[str, int] = class_start_ids or {}
        # class name -> all classes sharing its start node (incl. itself). Paired
        # classes (Witch/Sorceress, Ranger/Huntress) occupy the same tree region,
        # so a region filter for one must also accept the other.
        self._class_aliases: dict[str, set[str]] = class_aliases or {}

    def get(self, node_id: int) -> TreeNode | None:
        return self._nodes.get(node_id)

    def view(
        self,
        node: TreeNode | int | None,
        class_name: str | None = None,
        ascendancy: str | None = None,
    ) -> TreeNode | None:
        """Resolve a node's name/stats for a given class.

        Most nodes are class-agnostic and are returned unchanged. For the handful
        of switchable start-area nodes, the variant for `ascendancy` (e.g. Abyssal
        Lich) takes priority, then `class_name` (e.g. Witch); otherwise the default
        (which serves the paired class, e.g. Sorceress) is returned.
        """
        if isinstance(node, int):
            node = self._nodes.get(node)
        if node is None or not node.options:
            return node
        for key in (ascendancy, class_name):
            if key and key in node.options:
                ov = node.options[key]
                return replace(node, name=ov["name"], stats=ov["stats"])
        return node

    def resolve_ids(
        self,
        ids: list[int],
        class_name: str | None = None,
        ascendancy: str | None = None,
    ) -> list[TreeNode]:
        return [
            self.view(self._nodes[i], class_name, ascendancy)
            for i in ids
            if i in self._nodes
        ]

    def region_of(self, node_id: int) -> str:
        """Return the class name this node belongs to in the Voronoi partition, or '' if unknown."""
        return self._voronoi.get(node_id, "")

    def expand_classes(self, classes: list[str]) -> set[str]:
        """Expand requested class names to include classes sharing the same start.

        Filtering by "Sorceress" should also match the "Witch" Voronoi label (they
        share a region), and vice versa.
        """
        out: set[str] = set()
        for c in classes:
            out |= self._class_aliases.get(c, {c})
        return out

    def class_names(self) -> list[str]:
        """Return all PoE2 class names derived from the tree data."""
        return sorted(self.class_start_ids.keys())

    def search(
        self,
        query: str,
        classes: list[str] | None = None,
        class_name: str | None = None,
        ascendancy: str | None = None,
    ) -> list[TreeNode]:
        """Return all nodes whose name or stats contain the query string (case-insensitive).

        Matching is done against each node's class-resolved content (so a Witch
        search for "chaos" matches the Witch variant, not the default). If classes
        is provided, only nodes in those Voronoi regions (alias-expanded) are returned.
        """
        q = query.lower()
        region_filter = self.expand_classes(classes) if classes else None
        results: list[TreeNode] = []
        for node in self._nodes.values():
            if region_filter is not None and self._voronoi.get(node.id, "") not in region_filter:
                continue
            v = self.view(node, class_name, ascendancy)
            if q in v.name.lower() or any(q in s.lower() for s in v.stats):
                results.append(v)
        return results

    def neighbor_nodes(self, node_id: int) -> list[TreeNode]:
        """Return the resolved neighbor nodes of node_id (skipping any unknown ids)."""
        node = self._nodes.get(node_id)
        if node is None:
            return []
        return [self._nodes[n] for n in node.neighbors if n in self._nodes]

    def shortest_path(
        self, allocated_ids: set[int], target_id: int
    ) -> list[TreeNode] | None:
        """
        Shortest sequence of nodes to allocate to reach target_id from the build.

        Multi-source BFS seeded from every allocated node, tracking parents so the
        path can be reconstructed. Returns the unallocated nodes that must be taken,
        ordered from the build outward to the target. Returns:
          - []   if target_id is already allocated
          - None if target_id is unknown, unreachable, or no nodes are allocated
        The number of passive points required is len(result).
        """
        if target_id not in self._nodes:
            return None
        if target_id in allocated_ids:
            return []

        parent: dict[int, int | None] = {}
        queue: deque[int] = deque()
        for sid in allocated_ids:
            if sid in self._nodes:
                parent[sid] = None
                queue.append(sid)
        if not queue:
            return None

        found = False
        while queue:
            node_id = queue.popleft()
            if node_id == target_id:
                found = True
                break
            node = self._nodes.get(node_id)
            if node is None:
                continue
            for neighbor_id in node.neighbors:
                if neighbor_id not in parent and neighbor_id in self._nodes:
                    parent[neighbor_id] = node_id
                    queue.append(neighbor_id)

        if not found:
            return None

        path: list[int] = []
        cur: int | None = target_id
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()  # source (allocated) ... target

        return [self._nodes[i] for i in path if i not in allocated_ids]

    def nodes_within_distance(
        self, allocated_ids: set[int], max_distance: int
    ) -> list[tuple[TreeNode, int]]:
        """
        Multi-source BFS from all allocated nodes.

        Returns (node, distance) pairs for every unallocated node reachable
        within max_distance steps. Distance is the minimum number of passive
        points required to reach that node from the current build.
        """
        visited: dict[int, int] = {}
        queue: deque[tuple[int, int]] = deque()

        for sid in allocated_ids:
            if sid in self._nodes:
                visited[sid] = 0
                queue.append((sid, 0))

        results: list[tuple[TreeNode, int]] = []

        while queue:
            node_id, dist = queue.popleft()
            node = self._nodes.get(node_id)
            if node is None:
                continue

            if node_id not in allocated_ids:
                results.append((node, dist))

            if dist < max_distance:
                for neighbor_id in node.neighbors:
                    if neighbor_id not in visited:
                        visited[neighbor_id] = dist + 1
                        queue.append((neighbor_id, dist + 1))

        return sorted(results, key=lambda t: t[1])

    def __len__(self) -> int:
        return len(self._nodes)


def _compute_voronoi(
    nodes: dict[int, TreeNode], class_start_ids: dict[str, int]
) -> dict[int, str]:
    """
    Assign each node to a class region via simultaneous multi-source BFS.

    All class starting nodes are seeded at once. Each node is claimed by
    whichever starting node reaches it first — i.e. the class whose start
    is fewest graph steps away. Ties go to whichever source was enqueued
    first (insertion order of class_start_ids).
    """
    voronoi: dict[int, str] = {}
    queue: deque[tuple[int, str]] = deque()

    for class_name, start_id in class_start_ids.items():
        if start_id in nodes:
            voronoi[start_id] = class_name
            queue.append((start_id, class_name))

    while queue:
        node_id, class_name = queue.popleft()
        node = nodes.get(node_id)
        if node is None:
            continue
        for neighbor_id in node.neighbors:
            if neighbor_id not in voronoi:
                voronoi[neighbor_id] = class_name
                queue.append((neighbor_id, class_name))

    return voronoi


def load_tree(path: str | Path) -> PassiveTree:
    """
    Parse a PoE2 passive tree JSON file into a PassiveTree.

    The JSON format follows the structure published by GGG (same schema as PoE1):
      { "nodes": { "<id>": { "name": "...", "stats": [...], "connections": [...] } } }

    Connections in the raw JSON are directed edges; we build a bidirectional
    adjacency list so BFS can traverse the graph in either direction.

    Class starting nodes are identified via the classesStart field, which lists the
    classes that share that start (e.g. ["Witch", "Sorceress"]). Every entry that
    is a real PoE2 class (per the top-level "classes" table) is registered, so all
    8 classes are recognised — not just one per attribute corner. Legacy PoE1 names
    (Shadow, Marauder, Duelist, Templar) are skipped. A Voronoi partition is computed
    after adjacency is built, assigning every node to the class whose starting node
    is closest in graph distance.

    Per-class node variants are read from each node's "options": when it is a dict
    keyed by class/ascendancy name, that class sees a different name/stats for the
    same node id (e.g. Witch sees "Entropy" where others see "Principal Infusion").
    List-typed "options" are the +5-attribute choice nodes and are left as-is.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Real PoE2 class names, used to filter legacy aliases out of classesStart.
    real_classes = {c["name"] for c in data.get("classes", []) if c.get("name")}

    nodes_raw = data.get("nodes", {})
    nodes: dict[int, TreeNode] = {}
    class_start_ids: dict[str, int] = {}

    # First pass: create all nodes without adjacency.
    for key, val in nodes_raw.items():
        try:
            node_id = int(key)
        except ValueError:
            continue

        # Skip the root node (id 0) which is a virtual origin
        if node_id == 0:
            continue

        name = val.get("name", "")
        stats = val.get("stats", [])
        is_keystone = val.get("isKeystone", False)
        is_notable = val.get("isNotable", False)
        is_mastery = val.get("isMastery", False)
        ascendancy_name = val.get("ascendancyName", "")

        # Per-class overrides: only the dict form (class name -> {name, stats}).
        options: dict[str, dict] = {}
        raw_opts = val.get("options")
        if isinstance(raw_opts, dict):
            for cname, ov in raw_opts.items():
                if isinstance(ov, dict) and "name" in ov:
                    options[cname] = {
                        "name": ov.get("name", name),
                        "stats": ov.get("stats", stats),
                    }

        nodes[node_id] = TreeNode(
            id=node_id,
            name=name,
            stats=stats,
            is_keystone=is_keystone,
            is_notable=is_notable,
            is_mastery=is_mastery,
            ascendancy_name=ascendancy_name,
            options=options,
        )

        # Register every real PoE2 class that starts here. Fall back to the legacy
        # "[-1] is the PoE2 class" rule when no classes table is present.
        classes_start = val.get("classesStart", [])
        if classes_start:
            if real_classes:
                for cname in classes_start:
                    if cname in real_classes:
                        class_start_ids[cname] = node_id
            else:
                class_start_ids[classes_start[-1]] = node_id

    # Second pass: build bidirectional adjacency from the directed connection list.
    for key, val in nodes_raw.items():
        try:
            src_id = int(key)
        except ValueError:
            continue

        if src_id == 0 or src_id not in nodes:
            continue

        for conn in val.get("connections", []):
            dst_id = conn.get("id")
            if dst_id is None or dst_id not in nodes:
                continue
            if dst_id not in nodes[src_id].neighbors:
                nodes[src_id].neighbors.append(dst_id)
            if src_id not in nodes[dst_id].neighbors:
                nodes[dst_id].neighbors.append(src_id)

    voronoi = _compute_voronoi(nodes, class_start_ids)
    class_aliases = _compute_class_aliases(class_start_ids)
    return PassiveTree(
        nodes,
        voronoi=voronoi,
        class_start_ids=class_start_ids,
        class_aliases=class_aliases,
    )


def _compute_class_aliases(class_start_ids: dict[str, int]) -> dict[str, set[str]]:
    """Group classes that share a start node (e.g. {Witch, Sorceress}).

    Returns each class -> the full set sharing its start, so a region filter for
    one paired class also matches its partner's Voronoi label.
    """
    by_start: dict[int, set[str]] = {}
    for cname, start_id in class_start_ids.items():
        by_start.setdefault(start_id, set()).add(cname)
    aliases: dict[str, set[str]] = {}
    for names in by_start.values():
        for n in names:
            aliases[n] = set(names)
    return aliases


def load_default_tree() -> PassiveTree | None:
    """
    Load the tree from the default data path, returning None if not present.
    The TREE_DATA_PATH env var overrides the default location.
    """
    env_path = os.environ.get("TREE_DATA_PATH")
    path = Path(env_path) if env_path else resource_path("data", "poe2_tree.json")
    if not path.exists():
        return None
    return load_tree(path)
