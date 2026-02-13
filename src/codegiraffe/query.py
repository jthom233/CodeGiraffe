"""Query engine for the Code Giraffe architecture knowledge graph.

Provides functions for extracting relevant subgraphs, finding contextually
relevant nodes via keyword matching, and detecting drift between the graph
and the actual codebase.
"""

from __future__ import annotations

import re
import string
from typing import Any

from codegiraffe.graph import ArchGraph, GraphData, Node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_node_ids(graph: ArchGraph) -> list[str]:
    """Return all node ids present in the graph."""
    return list(graph.graph.nodes)


def _fuzzy_suggestions(query: str, candidates: list[str], max_results: int = 5) -> list[str]:
    """Return candidate ids that contain *query* as a substring (case-insensitive).

    Falls back to candidates that share a substantial common substring with
    the query so that minor typos still surface useful suggestions.
    """
    query_lower = query.lower()

    # First pass: substring containment in either direction
    exact: list[str] = []
    for cid in candidates:
        cid_lower = cid.lower()
        if query_lower in cid_lower or cid_lower in query_lower:
            exact.append(cid)

    if exact:
        return exact[:max_results]

    # Second pass: score by longest common substring ratio
    scored: list[tuple[str, float]] = []
    for cid in candidates:
        sim = _similarity(query_lower, cid.lower())
        if sim > 0.3:
            scored.append((cid, sim))
    scored.sort(key=lambda t: t[1], reverse=True)
    return [cid for cid, _ in scored[:max_results]]


def _similarity(a: str, b: str) -> float:
    """Compute a simple similarity ratio between two strings.

    Uses longest-common-substring length divided by the length of the longer
    string.  This is cheap and good enough for suggestion ranking without
    pulling in external libraries.
    """
    if not a or not b:
        return 0.0
    n, m = len(a), len(b)
    # DP for longest common substring
    max_len = 0
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        curr = [0] * (m + 1)
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > max_len:
                    max_len = curr[j]
        prev = curr
    return max_len / max(n, m)


def _tokenize(text: str) -> list[str]:
    """Tokenize a string into lowercase keywords, stripping punctuation."""
    # Replace punctuation with spaces, then split
    cleaned = text.lower()
    cleaned = cleaned.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
    tokens = cleaned.split()
    # Filter out very short tokens that are unlikely to be meaningful
    return [t for t in tokens if len(t) > 1]


def _score_node(node: Node, keywords: list[str]) -> int:
    """Score a node by counting how many keywords appear in its searchable text."""
    searchable_parts: list[str] = [
        node.id.lower(),
        node.label.lower(),
        node.type.lower(),
    ]
    # Include metadata values (stringified)
    for value in node.metadata.values():
        searchable_parts.append(str(value).lower())
    if node.file_path:
        searchable_parts.append(node.file_path.lower())

    combined = " ".join(searchable_parts)
    score = 0
    for kw in keywords:
        if kw in combined:
            score += 1
    return score


def _merge_graph_data(parts: list[GraphData], base_data: GraphData) -> GraphData:
    """Merge multiple GraphData instances into a single one, deduplicating."""
    merged_nodes: dict[str, Node] = {}
    seen_edges: set[tuple[str, str, str]] = set()
    merged_edges: list[Any] = []

    for part in parts:
        for nid, node in part.nodes.items():
            if nid not in merged_nodes:
                merged_nodes[nid] = node
        for edge in part.edges:
            key = (edge.source, edge.target, edge.type)
            if key not in seen_edges:
                seen_edges.add(key)
                merged_edges.append(edge)

    return GraphData(
        nodes=merged_nodes,
        edges=merged_edges,
        project_path=base_data.project_path,
        last_scan=base_data.last_scan,
        schema_version=base_data.schema_version,
    )


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------

def query_by_node(graph: ArchGraph, node_id: str, depth: int = 2) -> GraphData:
    """Extract a subgraph centered on *node_id* up to *depth* hops.

    Delegates to ``graph.get_subgraph``.  Raises :class:`ValueError` with
    fuzzy-match suggestions if the requested node does not exist.
    """
    if node_id not in graph.graph:
        candidates = _all_node_ids(graph)
        suggestions = _fuzzy_suggestions(node_id, candidates)
        msg = f"Node '{node_id}' not found in graph."
        if suggestions:
            suggestion_str = ", ".join(f"'{s}'" for s in suggestions)
            msg += f" Did you mean one of: {suggestion_str}?"
        raise ValueError(msg)

    return graph.get_subgraph(node_id, depth)


def query_by_type(graph: ArchGraph, node_type: str) -> GraphData:
    """Return all nodes of *node_type* together with their direct edges.

    For each matching node a depth-1 subgraph is extracted; all subgraphs
    are then merged into a single :class:`GraphData`.
    """
    matching_nodes = graph.get_nodes_by_type(node_type)
    if not matching_nodes:
        return GraphData(
            project_path=graph.to_data().project_path,
            last_scan=graph.to_data().last_scan,
            schema_version=graph.to_data().schema_version,
        )

    base_data = graph.to_data()
    parts: list[GraphData] = []
    for node in matching_nodes:
        sub = graph.get_subgraph(node.id, depth=1)
        parts.append(sub)

    return _merge_graph_data(parts, base_data)


def context_for_task(
    graph: ArchGraph,
    task: str,
    max_nodes: int = 20,
) -> GraphData:
    """Return the subgraph most relevant to a natural-language *task* description.

    Relevance is determined by simple keyword matching (no embeddings or NLP).

    Algorithm:
    1. Tokenize the task into keywords.
    2. Score every node by keyword overlap with its id, label, type, and
       metadata values.
    3. Select the top-scoring nodes (up to ``max_nodes``).
    4. Expand each selected node to include direct neighbors (depth=1).
    5. Cap the total node count at ``max_nodes``.
    6. Annotate each returned node's metadata with ``_relevance_score``.

    Returns an empty :class:`GraphData` when no node scores above zero.
    """
    keywords = _tokenize(task)
    if not keywords:
        return GraphData(
            project_path=graph.to_data().project_path,
            last_scan=graph.to_data().last_scan,
            schema_version=graph.to_data().schema_version,
        )

    # Score all nodes
    scored: list[tuple[Node, int]] = []
    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None:
            continue
        score = _score_node(node, keywords)
        if score > 0:
            scored.append((node, score))

    if not scored:
        return GraphData(
            project_path=graph.to_data().project_path,
            last_scan=graph.to_data().last_scan,
            schema_version=graph.to_data().schema_version,
        )

    # Sort by score descending, then by id for stable ordering
    scored.sort(key=lambda t: (-t[1], t[0].id))

    # Take top seeds (at most max_nodes, but likely fewer to leave room for
    # neighbors)
    seed_limit = max(1, max_nodes // 2)
    seeds = scored[:seed_limit]

    # Build a score lookup so we can annotate nodes later
    score_map: dict[str, int] = {node.id: score for node, score in scored}

    # Expand each seed to depth=1 and merge
    base_data = graph.to_data()
    parts: list[GraphData] = []
    for node, _ in seeds:
        sub = graph.get_subgraph(node.id, depth=1)
        parts.append(sub)

    merged = _merge_graph_data(parts, base_data)

    # Cap at max_nodes.  Prefer nodes with higher scores; neighbors that were
    # not scored get score 0.
    if len(merged.nodes) > max_nodes:
        node_list = list(merged.nodes.values())
        node_list.sort(key=lambda n: (-score_map.get(n.id, 0), n.id))
        kept_ids = {n.id for n in node_list[:max_nodes]}
        merged.nodes = {nid: n for nid, n in merged.nodes.items() if nid in kept_ids}
        merged.edges = [
            e for e in merged.edges
            if e.source in kept_ids and e.target in kept_ids
        ]

    # Annotate nodes with relevance scores (as metadata, prefixed with _ to
    # indicate it is system-generated)
    for nid, node in merged.nodes.items():
        node.metadata["_relevance_score"] = score_map.get(nid, 0)

    # Sort nodes dict by relevance score descending for presentation
    merged.nodes = dict(
        sorted(
            merged.nodes.items(),
            key=lambda item: (-item[1].metadata.get("_relevance_score", 0), item[0]),
        )
    )

    return merged


def detect_drift(graph: ArchGraph, project_path: str) -> list[dict[str, str]]:
    """Compare the current graph against a fresh scan of *project_path*.

    Re-runs the scanner to discover what the codebase currently contains,
    then compares against the non-manual nodes in the existing graph.

    Returns a list of drift records, each a dict with:
    - ``type``: one of ``"missing_in_code"``, ``"missing_in_graph"``, or
      ``"potential_rename"``
    - ``node_id``: the relevant node id
    - ``details``: human-readable explanation

    An empty list means no drift was detected.
    """
    # Import scanner lazily to avoid circular imports and to allow the
    # scanner module to be developed independently.
    from codegiraffe.scanner import scan_project  # type: ignore[import-untyped]

    scanned_result = scan_project(project_path)
    scanned_ids: set[str] = {node.id for node in scanned_result.nodes}

    # Collect non-manual node ids from the existing graph
    graph_data = graph.to_data()
    graph_auto_ids: set[str] = set()
    for nid, node in graph_data.nodes.items():
        if not node.manual:
            graph_auto_ids.add(nid)

    missing_in_code = graph_auto_ids - scanned_ids  # in graph but not in scan
    missing_in_graph = scanned_ids - graph_auto_ids  # in scan but not in graph

    drifts: list[dict[str, str]] = []

    # Check for potential renames: a node missing from code has a similar id
    # to one missing from the graph (i.e., new in the scan).
    rename_threshold = 0.5
    matched_code: set[str] = set()
    matched_graph: set[str] = set()

    for old_id in sorted(missing_in_code):
        best_match: str | None = None
        best_score: float = 0.0
        for new_id in sorted(missing_in_graph):
            if new_id in matched_code:
                continue
            sim = _similarity(old_id.lower(), new_id.lower())
            if sim > best_score:
                best_score = sim
                best_match = new_id
        if best_match is not None and best_score >= rename_threshold:
            drifts.append({
                "type": "potential_rename",
                "node_id": old_id,
                "details": (
                    f"Node '{old_id}' was not found in code but '{best_match}' "
                    f"is new (similarity {best_score:.0%}). Possible rename."
                ),
            })
            matched_code.add(best_match)
            matched_graph.add(old_id)

    # Remaining unmatched nodes
    for nid in sorted(missing_in_code - matched_graph):
        drifts.append({
            "type": "missing_in_code",
            "node_id": nid,
            "details": (
                f"Node '{nid}' exists in the graph but was not found by "
                f"scanning the codebase. It may have been removed or renamed."
            ),
        })

    for nid in sorted(missing_in_graph - matched_code):
        drifts.append({
            "type": "missing_in_graph",
            "node_id": nid,
            "details": (
                f"Node '{nid}' was discovered by scanning the codebase but "
                f"is not in the graph. It may be newly added."
            ),
        })

    return drifts
