"""Graph comparison for PR review — compute architectural deltas between git refs.

Provides:
    compute_graph_diff  -- Compare two ArchGraph instances, returning a structured diff.
    build_graph_at_ref  -- Checkout a git ref into a temp worktree, scan it, return ArchGraph.
"""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any

from codegiraffe.graph import ArchGraph, GraphData, Node
from codegiraffe.scanner import scan_project
from codegiraffe.schema import NodeType


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_graph_diff(base_graph: ArchGraph, head_graph: ArchGraph) -> dict[str, Any]:
    """Compare two graphs and return structural diff.

    Parameters
    ----------
    base_graph:
        The "before" graph (e.g. the base branch of a PR).
    head_graph:
        The "after" graph (e.g. the PR head branch).

    Returns
    -------
    dict with keys:
        nodes_added       -- list of node IDs present in head but not base.
        nodes_removed     -- list of node IDs present in base but not head.
        nodes_modified    -- list of node IDs present in both but with changed type,
                             label, metadata, or file_path.
        edges_added       -- list of {"source", "target", "type"} dicts for new edges.
        edges_removed     -- list of {"source", "target", "type"} dicts for removed edges.
        contracts_affected -- list of contract node IDs that appeared or disappeared.
        new_cycles        -- list of cycles (each a list of node IDs) that exist in head
                             but not in base.
        summary           -- Human-readable markdown summary string.
    """
    base_data = base_graph.to_data()
    head_data = head_graph.to_data()

    base_nodes: dict[str, Node] = base_data.nodes
    head_nodes: dict[str, Node] = head_data.nodes

    # Node sets
    base_ids = set(base_nodes.keys())
    head_ids = set(head_nodes.keys())

    nodes_added = sorted(head_ids - base_ids)
    nodes_removed = sorted(base_ids - head_ids)
    nodes_modified = _compute_modified_nodes(base_nodes, head_nodes)

    # Edge sets: represent as frozensets of (source, target, type) triples
    base_edge_set = _edge_set(base_data)
    head_edge_set = _edge_set(head_data)

    edges_added = [
        {"source": s, "target": t, "type": tp}
        for s, t, tp in sorted(head_edge_set - base_edge_set)
    ]
    edges_removed = [
        {"source": s, "target": t, "type": tp}
        for s, t, tp in sorted(base_edge_set - head_edge_set)
    ]

    # Contracts affected: contract nodes that changed (added or removed)
    contracts_affected = _compute_contracts_affected(
        base_nodes, head_nodes, nodes_added, nodes_removed
    )

    # New cycles: cycles in head that were not present in base
    new_cycles = _compute_new_cycles(base_graph, head_graph)

    summary = _build_summary(
        nodes_added, nodes_removed, nodes_modified,
        edges_added, edges_removed, contracts_affected, new_cycles,
    )

    return {
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "nodes_modified": nodes_modified,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
        "contracts_affected": contracts_affected,
        "new_cycles": new_cycles,
        "summary": summary,
    }


def build_graph_at_ref(
    project_path: str,
    ref: str,
    scanner_mode: str = "regex",
) -> ArchGraph:
    """Create a temporary git worktree at *ref*, scan it, and return the ArchGraph.

    The worktree is created with ``git worktree add``, the project is scanned,
    then the worktree is removed with ``git worktree remove``.

    Parameters
    ----------
    project_path:
        Root directory of the git repository.
    ref:
        A git ref (branch, tag, or commit SHA) to check out.
    scanner_mode:
        ``"regex"`` (default), ``"ast"``, or ``"hybrid"`` for tree-sitter scanning.

    Raises
    ------
    RuntimeError:
        When ``git worktree add`` fails (e.g., unknown ref).
    """
    with tempfile.TemporaryDirectory(prefix="codegiraffe-worktree-") as tmpdir:
        # Create the worktree at the given ref
        add_result = subprocess.run(
            ["git", "worktree", "add", tmpdir, ref],
            capture_output=True,
            text=True,
            cwd=project_path,
        )
        if add_result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed for ref {ref!r}: {add_result.stderr.strip()}"
            )

        try:
            # Select registry based on scanner mode
            registry = None
            if scanner_mode == "ast":
                from codegiraffe.ast_scanner import get_ast_registry
                registry = get_ast_registry()
            elif scanner_mode == "hybrid":
                from codegiraffe.ast_scanner import get_hybrid_registry
                registry = get_hybrid_registry()

            scan_result = scan_project(tmpdir, registry=registry)

            nodes: dict[str, Node] = {node.id: node for node in scan_result.nodes}
            edges = scan_result.edges

            data = GraphData(
                nodes=nodes,
                edges=edges,
                project_path=project_path,
                last_scan=datetime.now(timezone.utc).isoformat(),
            )
            graph = ArchGraph(data)
        finally:
            # Always clean up the worktree, even on scan failure
            subprocess.run(
                ["git", "worktree", "remove", "--force", tmpdir],
                capture_output=True,
                text=True,
                cwd=project_path,
            )

    return graph


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _edge_set(data: GraphData) -> set[tuple[str, str, str]]:
    """Return a set of (source, target, type) tuples for all edges in *data*."""
    return {(e.source, e.target, e.type) for e in data.edges}


def _compute_modified_nodes(
    base_nodes: dict[str, Node],
    head_nodes: dict[str, Node],
) -> list[str]:
    """Return IDs of nodes present in both graphs but with changed attributes."""
    modified: list[str] = []
    common_ids = set(base_nodes.keys()) & set(head_nodes.keys())
    for nid in sorted(common_ids):
        base_node = base_nodes[nid]
        head_node = head_nodes[nid]
        if _node_changed(base_node, head_node):
            modified.append(nid)
    return modified


def _node_changed(base: Node, head: Node) -> bool:
    """Return True if any meaningful attribute differs between two Node instances."""
    return (
        base.type != head.type
        or base.label != head.label
        or base.file_path != head.file_path
        or base.metadata != head.metadata
    )


def _compute_contracts_affected(
    base_nodes: dict[str, Node],
    head_nodes: dict[str, Node],
    nodes_added: list[str],
    nodes_removed: list[str],
) -> list[str]:
    """Return contract node IDs that were added or removed."""
    affected: list[str] = []
    for nid in nodes_added:
        node = head_nodes[nid]
        if node.type == NodeType.CONTRACT:
            affected.append(nid)
    for nid in nodes_removed:
        node = base_nodes[nid]
        if node.type == NodeType.CONTRACT:
            affected.append(nid)
    return sorted(affected)


def _cycles_as_frozensets(graph: ArchGraph) -> set[frozenset[str]]:
    """Return cycles as a set of frozensets for order-independent comparison."""
    return {frozenset(cycle) for cycle in graph.detect_cycles()}


def _compute_new_cycles(
    base_graph: ArchGraph,
    head_graph: ArchGraph,
) -> list[list[str]]:
    """Return cycles that exist in *head_graph* but not in *base_graph*.

    Comparison is done by node-set identity (order-independent), because the
    same cycle can be enumerated starting from different nodes.
    """
    base_cycle_sets = _cycles_as_frozensets(base_graph)
    head_cycles = head_graph.detect_cycles()

    new_cycles: list[list[str]] = []
    for cycle in head_cycles:
        if frozenset(cycle) not in base_cycle_sets:
            new_cycles.append(cycle)
    return new_cycles


def _build_summary(
    nodes_added: list[str],
    nodes_removed: list[str],
    nodes_modified: list[str],
    edges_added: list[dict[str, str]],
    edges_removed: list[dict[str, str]],
    contracts_affected: list[str],
    new_cycles: list[list[str]],
) -> str:
    """Build a human-readable summary string for the diff."""
    total_changes = (
        len(nodes_added)
        + len(nodes_removed)
        + len(nodes_modified)
        + len(edges_added)
        + len(edges_removed)
    )

    if total_changes == 0:
        return "No architectural changes detected between the two graphs."

    parts: list[str] = []

    if nodes_added:
        parts.append(f"{len(nodes_added)} node(s) added")
    if nodes_removed:
        parts.append(f"{len(nodes_removed)} node(s) removed")
    if nodes_modified:
        parts.append(f"{len(nodes_modified)} node(s) modified")
    if edges_added:
        parts.append(f"{len(edges_added)} edge(s) added")
    if edges_removed:
        parts.append(f"{len(edges_removed)} edge(s) removed")
    if contracts_affected:
        parts.append(f"{len(contracts_affected)} contract(s) affected")
    if new_cycles:
        parts.append(f"{len(new_cycles)} new cycle(s) introduced")

    return "Architectural diff: " + ", ".join(parts) + "."
