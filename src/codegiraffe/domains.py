"""Domain model abstraction — cluster nodes by business domains.

Provides functions to infer domain groupings from directory structure or
node ID prefixes, and to manage manual domain definitions that survive
rescans via the manual=True flag.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from codegiraffe.graph import ArchGraph, Edge, Node
from codegiraffe.schema import NodeType, EdgeType


def _domain_node_id(name: str) -> str:
    """Return the canonical domain node ID for a given domain name."""
    return f"domain:{name}"


def infer_domains(graph: ArchGraph) -> list[dict[str, Any]]:
    """Infer domains from directory structure or node ID prefixes.

    Examines all non-domain nodes in the graph and clusters them:

    1. If a node has a ``file_path``, it is grouped by the first meaningful
       directory component of that path (e.g. ``src/payments/service.py``
       → ``payments``).
    2. If no ``file_path`` is present, the node is grouped by the prefix
       before the first ``:`` in its ID (e.g. ``service:PaymentService``
       → ``service``).

    Groups with only one member are considered non-meaningful and excluded
    from the result.

    Returns
    -------
    list[dict]
        Each entry has:
        - ``name``: str — inferred domain name
        - ``node_count``: int — number of member nodes
        - ``node_ids``: list[str] — IDs of member nodes
    """
    # Collect non-domain nodes only
    candidates: list[Node] = []
    for _, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is not None and node.type != NodeType.DOMAIN:
            candidates.append(node)

    if not candidates:
        return []

    # Try directory-based clustering first
    dir_clusters: dict[str, list[str]] = defaultdict(list)
    prefix_clusters: dict[str, list[str]] = defaultdict(list)

    for node in candidates:
        fp = node.file_path or node.metadata.get("file_path", "")
        if fp:
            # Normalise path and find the first meaningful directory component.
            # Strategy: strip any leading common path segment (e.g. "src/") by
            # picking the first directory component that is not "src", "lib",
            # "app", "pkg", or the root.
            parts = [p for p in fp.replace("\\", "/").split("/") if p]
            # Find the first non-trivial directory component
            domain_name: str | None = None
            skip_prefixes = {"src", "lib", "app", "pkg", "source", "sources"}
            for i, part in enumerate(parts[:-1]):  # exclude file name
                if part.lower() not in skip_prefixes:
                    domain_name = part
                    break
            if domain_name is None and len(parts) > 1:
                # Fall back to the second-to-last part before the filename
                domain_name = parts[-2]
            if domain_name:
                dir_clusters[domain_name].append(node.id)
        else:
            # Prefix-based: split on first ":"
            colon_idx = node.id.find(":")
            if colon_idx > 0:
                prefix = node.id[:colon_idx]
                prefix_clusters[prefix].append(node.id)
            else:
                prefix_clusters["default"].append(node.id)

    # Decide which clustering to use:
    # - If any node had a file_path, use dir_clusters
    # - If no node had a file_path, use prefix_clusters
    has_dir_clusters = bool(dir_clusters)

    clusters = dir_clusters if has_dir_clusters else prefix_clusters

    if not clusters:
        return []

    # Only return results if at least one cluster has 2+ members (meaningful grouping).
    # When every cluster is a singleton (every directory has exactly 1 node), there is
    # no useful grouping information, so return an empty list.
    max_cluster_size = max(len(v) for v in clusters.values())
    if max_cluster_size < 2:
        return []

    result: list[dict[str, Any]] = []
    for name, node_ids in sorted(clusters.items()):
        result.append({
            "name": name,
            "node_count": len(node_ids),
            "node_ids": sorted(node_ids),
        })

    return result


def add_domain(graph: ArchGraph, name: str, node_ids: list[str]) -> None:
    """Create a domain node with ``belongs_to`` edges from each member.

    The domain node and all its edges are marked ``manual=True`` so they
    survive automated rescans via ``ArchGraph.merge_manual_annotations``.

    Parameters
    ----------
    graph:
        The architecture graph to modify in-place.
    name:
        Human-readable domain name (e.g. ``"payments"``).
    node_ids:
        List of node IDs that belong to this domain.
    """
    domain_id = _domain_node_id(name)

    # Create or update the domain node
    domain_node = Node(
        id=domain_id,
        type=NodeType.DOMAIN,
        label=name,
        metadata={
            "domain_name": name,
            "member_count": len(node_ids),
        },
        manual=True,
    )
    graph.add_node(domain_node)

    # Add belongs_to edges from each member to the domain node
    for member_id in node_ids:
        edge = Edge(
            source=member_id,
            target=domain_id,
            type=EdgeType.BELONGS_TO,
            metadata={},
            manual=True,
        )
        graph.add_edge(edge)


def remove_domain(graph: ArchGraph, name: str) -> None:
    """Remove a domain node and all its ``belongs_to`` edges.

    If the domain does not exist in the graph, this is a no-op.

    Parameters
    ----------
    graph:
        The architecture graph to modify in-place.
    name:
        The domain name to remove.
    """
    domain_id = _domain_node_id(name)

    if domain_id not in graph.graph:
        return

    # Remove the node (NetworkX also removes incident edges automatically)
    graph.remove_node(domain_id)


def list_domains(graph: ArchGraph) -> list[dict[str, Any]]:
    """List all domain nodes currently in the graph with member counts.

    Counts members by looking at how many nodes have a ``belongs_to`` edge
    pointing at each domain node.

    Returns
    -------
    list[dict]
        Each entry has:
        - ``name``: str — domain label
        - ``node_id``: str — domain node ID
        - ``node_count``: int — number of ``belongs_to`` edges pointing here
        - ``manual``: bool — whether the domain was manually defined
    """
    result: list[dict[str, Any]] = []

    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None or node.type != NodeType.DOMAIN:
            continue

        # Count predecessors connected via belongs_to
        # MultiDiGraph.get_edge_data(u, v) returns {key: {attrs}} so we
        # check for key membership rather than a "key" attribute.
        member_count = 0
        member_ids: list[str] = []
        for predecessor in graph.graph.predecessors(nid):
            # MultiDiGraph: use key= to check for the specific edge type
            edge_data = graph.graph.get_edge_data(predecessor, nid, key=EdgeType.BELONGS_TO)
            if edge_data is not None:
                member_count += 1
                member_ids.append(predecessor)

        result.append({
            "name": node.label,
            "node_id": nid,
            "node_count": member_count,
            "node_ids": sorted(member_ids),
            "manual": node.manual,
        })

    result.sort(key=lambda d: d["name"])
    return result


def get_domain_membership(graph: ArchGraph) -> dict[str, str]:
    """Return a mapping of node_id → domain_name for all domain members.

    Parameters
    ----------
    graph:
        The architecture graph to query.

    Returns
    -------
    dict[str, str]
        Maps member node IDs to their domain's label.
    """
    membership: dict[str, str] = {}

    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None or node.type != NodeType.DOMAIN:
            continue

        for predecessor in graph.graph.predecessors(nid):
            # MultiDiGraph: use key= to check for the specific edge type
            edge_data = graph.graph.get_edge_data(predecessor, nid, key=EdgeType.BELONGS_TO)
            if edge_data is not None:
                membership[predecessor] = node.label

    return membership
