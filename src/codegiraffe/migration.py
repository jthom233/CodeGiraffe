"""Migration planning — generate ordered transformation plans for refactors.

Produces step-by-step migration plans from an ArchGraph, respecting
dependency order, surfacing cycles, and reporting contract implications.
"""

from __future__ import annotations

import networkx as nx

from codegiraffe.graph import ArchGraph
from codegiraffe.schema import NodeType


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_migration_plan(
    graph: ArchGraph,
    description: str,
    target_nodes: list[str] | None = None,
) -> dict:
    """Generate an ordered migration plan.

    Algorithm:
    1. Resolve affected nodes from ``target_nodes`` (explicit) or keyword-match
       from ``description`` against node ids / labels.
    2. Build a subgraph of the affected nodes restricted to their mutual edges.
    3. Attempt a topological sort; if cycles exist, record them and fall back
       to an arbitrary-but-deterministic ordering (alphabetical by node id).
    4. Assign a sequential ``order`` to each step, leaf dependencies first.
    5. Identify rollback checkpoints — steps after which no unresolved
       intra-subgraph dependency remains (i.e. all targets of completed steps
       have themselves been completed).
    6. Collect contract implications for any CONTRACT node adjacent to the
       affected set.

    Returns::

        {
            "steps": [
                {
                    "order": int,          # 1-based, sequential
                    "action": str,         # e.g. "migrate"
                    "node_id": str,
                    "file": str,           # file_path or ""
                    "description": str,    # human-readable description
                }
            ],
            "checkpoints": list[int],      # step orders that are safe rollback points
            "contract_implications": [
                {"contract": str, "impact": str}
            ],
            "estimated_files": int,        # distinct file count across steps
            "cycles": list[list[str]],     # any cycles among the target nodes
        }
    """
    # --- 1. Resolve affected nodes -------------------------------------------
    if target_nodes is not None:
        # Explicit list — use it verbatim (filter to nodes that exist)
        affected: list[str] = [n for n in target_nodes if n in graph.graph]
    else:
        # Keyword match against description
        affected = _keyword_match(graph, description)

    if not affected:
        return {
            "steps": [],
            "checkpoints": [],
            "contract_implications": [],
            "estimated_files": 0,
            "cycles": [],
        }

    # --- 2. Build subgraph of affected nodes ---------------------------------
    subgraph: nx.DiGraph = graph.graph.subgraph(affected).copy()

    # --- 3. Topological sort / cycle detection --------------------------------
    cycles: list[list[str]] = list(nx.simple_cycles(subgraph))

    if cycles:
        # Fall back to alphabetical ordering so results are deterministic
        ordered_nodes: list[str] = sorted(affected)
    else:
        try:
            # Leaf dependencies first → reverse topological order of the
            # *subgraph* (nodes with no outgoing subgraph-edges come last
            # in topo sort, but we want them migrated first).
            topo = list(nx.topological_sort(subgraph))
            # In a dependency graph A→B→C, topo order is [A, B, C].
            # We want leaves first (C then B then A) so we reverse.
            ordered_nodes = list(reversed(topo))
        except nx.NetworkXUnfeasible:
            # Should not happen since we caught cycles above, but guard anyway
            ordered_nodes = sorted(affected)

    # --- 4. Build step list --------------------------------------------------
    steps: list[dict] = []
    for i, node_id in enumerate(ordered_nodes, start=1):
        node_data = graph.graph.nodes.get(node_id, {}).get("node")
        file_path: str = ""
        if node_data is not None:
            file_path = node_data.file_path or node_data.metadata.get("file_path", "")
        label = node_data.label if node_data is not None else node_id

        steps.append(
            {
                "order": i,
                "action": "migrate",
                "node_id": node_id,
                "file": file_path,
                "description": f"Migrate {label} ({node_id}) — {description}",
            }
        )

    # --- 5. Identify rollback checkpoints ------------------------------------
    # A checkpoint is a step after which the set of completed nodes has no
    # pending outgoing edge into the *remaining* affected nodes within the
    # subgraph.  In other words, after step N, none of the nodes processed
    # so far have an un-migrated intra-subgraph dependency.
    checkpoints: list[int] = _compute_checkpoints(steps, subgraph, affected)

    # --- 6. Contract implications --------------------------------------------
    contract_implications = _collect_contract_implications(graph, affected)

    # --- 7. Estimated files --------------------------------------------------
    estimated_files = len({s["file"] for s in steps if s["file"]})

    return {
        "steps": steps,
        "checkpoints": checkpoints,
        "contract_implications": contract_implications,
        "estimated_files": estimated_files,
        "cycles": cycles,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _keyword_match(graph: ArchGraph, description: str) -> list[str]:
    """Return node ids whose label or id contains keywords from *description*.

    Keywords are lowercased words with punctuation stripped.
    """
    words = set(_tokenize(description))
    if not words:
        return []

    matched: list[str] = []
    for node_id in graph.graph.nodes:
        node_data = graph.graph.nodes[node_id].get("node")
        label: str = node_data.label if node_data is not None else ""
        # Match if any keyword appears in the node id or label
        haystack = (node_id + " " + label).lower()
        if any(w in haystack for w in words):
            matched.append(node_id)

    return matched


def _tokenize(text: str) -> list[str]:
    """Return lowercase, punctuation-stripped tokens from *text*."""
    import re

    return [t for t in re.split(r"[\s\-_/]+", text.lower()) if len(t) > 1]


def _compute_checkpoints(
    steps: list[dict],
    subgraph: nx.DiGraph,
    affected: list[str],
) -> list[int]:
    """Identify safe rollback points in the migration sequence.

    A step is a checkpoint when, after completing it, no node that has been
    migrated so far has an outgoing subgraph edge pointing at a node that has
    NOT yet been migrated.  This means the partial migration is self-consistent.
    """
    affected_set = set(affected)
    checkpoints: list[int] = []

    completed: set[str] = set()
    for step in steps:
        completed.add(step["node_id"])
        remaining = affected_set - completed

        is_safe = True
        for done_node in completed:
            for _, target in subgraph.out_edges(done_node):
                if target in remaining:
                    is_safe = False
                    break
            if not is_safe:
                break

        if is_safe:
            checkpoints.append(step["order"])

    return checkpoints


def _collect_contract_implications(
    graph: ArchGraph,
    affected: list[str],
) -> list[dict]:
    """Find CONTRACT nodes adjacent (in or out) to any affected node.

    Returns a list of ``{"contract": node_id, "impact": str}`` dicts.
    """
    affected_set = set(affected)
    seen_contracts: set[str] = set()
    implications: list[dict] = []

    for node_id in affected_set:
        # Walk outgoing edges from the affected node
        for _, target in graph.graph.out_edges(node_id):
            _maybe_add_contract(graph, target, node_id, seen_contracts, implications)

        # Walk incoming edges into the affected node
        for source, _ in graph.graph.in_edges(node_id):
            _maybe_add_contract(graph, source, node_id, seen_contracts, implications)

    return implications


def _maybe_add_contract(
    graph: ArchGraph,
    candidate: str,
    affecting_node: str,
    seen: set[str],
    results: list[dict],
) -> None:
    """Append a contract implication if *candidate* is a CONTRACT node."""
    if candidate in seen:
        return
    node_data = graph.graph.nodes.get(candidate, {}).get("node")
    if node_data is not None and node_data.type == NodeType.CONTRACT:
        seen.add(candidate)
        results.append(
            {
                "contract": candidate,
                "impact": (
                    f"Contract '{node_data.label}' is connected to affected node "
                    f"'{affecting_node}' — review producers and consumers before migrating."
                ),
            }
        )
