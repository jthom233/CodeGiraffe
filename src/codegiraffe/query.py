"""Query engine for the Code Giraffe architecture knowledge graph.

Provides functions for extracting relevant subgraphs, finding contextually
relevant nodes via keyword matching, and detecting drift between the graph
and the actual codebase.
"""

from __future__ import annotations

import json as _json
import os
import re
import string
import subprocess
from typing import Any

from codegiraffe.diff_parser import (
    ChangeReport,
    CouplingPair,
    DiffFile,
    TestSuggestion,
)
from codegiraffe.git_utils import get_commit_file_history, is_git_repo

import networkx as nx

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe import embeddings as _embeddings_mod


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


def _compute_severity(distance: int) -> str:
    """Map hop distance to a severity tier.

    - ``"direct"`` for distance 1 (immediate neighbors)
    - ``"transitive"`` for distances 2-3 (short propagation chains)
    - ``"indirect"`` for distance > 3 (long propagation chains)
    """
    if distance == 1:
        return "direct"
    elif distance <= 3:
        return "transitive"
    else:
        return "indirect"


def _compute_severity_with_confidence(distance: int, path_confidence: float) -> str:
    """Map hop distance to a severity tier, downgraded for low-confidence paths.

    When the minimum edge confidence along the path to a downstream node is
    below 0.6, the severity is prefixed with ``"uncertain_"`` to indicate the
    impact is plausible but not strongly supported by evidence.

    - ``"direct"`` / ``"uncertain_direct"`` for distance 1
    - ``"transitive"`` / ``"uncertain_transitive"`` for distances 2-3
    - ``"indirect"`` / ``"uncertain_indirect"`` for distance > 3
    """
    base = _compute_severity(distance)
    if path_confidence < 0.6:
        return f"uncertain_{base}"
    return base


def _path_min_confidence(graph_nx: Any, path: list[str]) -> float:
    """Return the minimum edge confidence along a path of node IDs.

    Walks consecutive pairs in *path*, looks up the edge data in *graph_nx*,
    and returns the minimum confidence found.  Returns 1.0 for empty paths
    or single-node paths (no edges to traverse).
    """
    if len(path) < 2:
        return 1.0
    min_conf = 1.0
    for i in range(len(path) - 1):
        src, tgt = path[i], path[i + 1]
        edge_data = graph_nx.edges.get((src, tgt), {})
        edge_obj = edge_data.get("edge")
        if edge_obj is not None:
            min_conf = min(min_conf, edge_obj.confidence)
    return min_conf


def _detect_git_renames(project_path: str, since: str | None = None) -> dict[str, str]:
    """Use git diff to find renamed files since the last scan.

    Returns a mapping of old_path -> new_path for renamed files.
    Falls back to empty dict if git is not available or project is not a git repo.
    """
    try:
        cmd = ["git", "-C", project_path, "diff", "--name-status", "--diff-filter=R", "-M"]
        if since:
            cmd.append(since)
        else:
            cmd.append("HEAD~10")  # Default: check last 10 commits

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {}

        renames: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0].startswith("R"):
                renames[parts[1]] = parts[2]
        return renames
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}


def _enhanced_similarity(
    old_id: str,
    new_id: str,
    old_node: Node | None = None,
    new_node: Node | None = None,
) -> float:
    """Enhanced similarity scoring that considers node structure.

    Factors:
    1. String similarity of node IDs (base score)
    2. Bonus if same node type prefix (e.g., both "endpoint:...")
    3. Bonus if file paths are similar (suggesting a file rename)
    4. Bonus if labels are similar
    """
    base = _similarity(old_id.lower(), new_id.lower())

    # Same type prefix bonus
    old_prefix = old_id.split(":")[0] if ":" in old_id else ""
    new_prefix = new_id.split(":")[0] if ":" in new_id else ""
    if old_prefix and old_prefix == new_prefix:
        base += 0.15

    # File path similarity bonus
    if old_node and new_node and old_node.file_path and new_node.file_path:
        path_sim = _similarity(old_node.file_path.lower(), new_node.file_path.lower())
        base += path_sim * 0.1

    # Label similarity bonus
    if old_node and new_node and old_node.label and new_node.label:
        label_sim = _similarity(old_node.label.lower(), new_node.label.lower())
        base += label_sim * 0.1

    return min(base, 1.0)  # Cap at 1.0


def _detect_edge_drift(
    graph_edges: list[Edge], scanned_edges: list[Edge]
) -> list[dict[str, str]]:
    """Detect edges that exist in the graph but not in the rescan, and vice versa.

    Only considers non-manual edges.
    """
    graph_edge_keys = {(e.source, e.target, e.type) for e in graph_edges if not e.manual}
    scan_edge_keys = {(e.source, e.target, e.type) for e in scanned_edges}

    drifts: list[dict[str, str]] = []

    for src, tgt, etype in sorted(graph_edge_keys - scan_edge_keys):
        drifts.append({
            "type": "edge_missing_in_code",
            "node_id": f"{src} -> {tgt}",
            "details": (
                f"Edge '{src}' --[{etype}]--> '{tgt}' exists in the graph "
                f"but was not found by scanning."
            ),
        })

    for src, tgt, etype in sorted(scan_edge_keys - graph_edge_keys):
        drifts.append({
            "type": "edge_missing_in_graph",
            "node_id": f"{src} -> {tgt}",
            "details": (
                f"Edge '{src}' --[{etype}]--> '{tgt}' was discovered by "
                f"scanning but is not in the graph."
            ),
        })

    return drifts


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


def _include_constraining_decisions(subgraph_nodes: set, graph: ArchGraph) -> set:
    """Given nodes in a subgraph, find all decision nodes connected via
    ``constrains`` edges and add them to the returned node-ID set.

    Parameters
    ----------
    subgraph_nodes:
        Set of node IDs already selected for the subgraph.
    graph:
        The full :class:`ArchGraph` to search.

    Returns
    -------
    set
        An extended set of node IDs that includes the original nodes plus any
        decision nodes that govern them.
    """
    from codegiraffe.schema import EdgeType, NodeType

    result = set(subgraph_nodes)

    # Iterate over all edges in the graph looking for constrains edges whose
    # target is already in the subgraph
    for src, tgt, data in graph.graph.edges(data=True):
        edge: Edge | None = data.get("edge")
        if edge is None:
            continue
        if edge.type != EdgeType.CONSTRAINS.value:
            continue
        # Source is the decision node; target is the governed node
        if tgt in subgraph_nodes:
            # Verify source is actually a decision node
            src_attrs = graph.graph.nodes.get(src, {})
            src_node: Node | None = src_attrs.get("node")
            if src_node is not None and src_node.type == NodeType.DECISION.value:
                result.add(src)

    return result


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


def _format_node_for_detail_level(node_data: dict, detail_level: str) -> dict:
    """Format a node dict based on detail level.

    - summary: only id, type, label
    - standard: id, type, label + key metadata (no raw content)
    - detailed: full metadata
    """
    if detail_level == "summary":
        return {
            "id": node_data.get("id", ""),
            "type": node_data.get("type", ""),
            "label": node_data.get("label", ""),
        }
    elif detail_level == "detailed":
        return dict(node_data)
    else:
        # standard: id, type, label + metadata (no file_path or other bulk fields)
        result: dict = {
            "id": node_data.get("id", ""),
            "type": node_data.get("type", ""),
            "label": node_data.get("label", ""),
        }
        if "metadata" in node_data:
            result["metadata"] = node_data["metadata"]
        return result


def _estimate_tokens(node_data: dict, detail_level: str = "standard") -> int:
    """Estimate tokens for a node at given detail level.

    Returns ``len(json.dumps(formatted_node)) // 4``.
    """
    formatted = _format_node_for_detail_level(node_data, detail_level)
    return len(_json.dumps(formatted)) // 4


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

#: Priority-ordered intent keyword table.  First match wins.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("create",  ["create", "add", "new", "build", "implement"]),
    ("debug",   ["debug", "fix", "bug", "error", "broken", "issue", "troubleshoot"]),
    ("refactor", ["refactor", "restructure", "reorganize", "move", "extract", "split"]),
    ("delete",  ["delete", "remove", "deprecate", "drop"]),
    ("test",    ["test", "spec", "verify", "coverage", "assert"]),
]


def _classify_intent(task: str) -> str:
    """Classify task intent from a natural-language description.

    Uses priority-ordered keyword matching.  The first matching intent wins.
    Unmatched tasks return ``"modify"`` (the default).

    Priority order: create > debug > refactor > delete > test > modify
    """
    task_lower = task.lower()
    # Tokenize to avoid partial word matches (e.g. "error" in "errorless")
    tokens = set(re.findall(r"[a-z]+", task_lower))
    for intent, keywords in _INTENT_KEYWORDS:
        for kw in keywords:
            if kw in tokens:
                return intent
    return "modify"


def context_for_task(
    graph: ArchGraph,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    token_budget: int = 0,
    detail_level: str = "standard",
    min_confidence: float = 0.0,
) -> GraphData:
    """Return the subgraph most relevant to a natural-language *task* description.

    When sentence-transformers is installed and *use_embeddings* is True, uses
    embedding-based semantic similarity.  Otherwise falls back to keyword matching.

    Algorithm (keyword mode):
    1. Tokenize the task into keywords.
    2. Score every node by keyword overlap with its id, label, type, and
       metadata values.
    3. Select the top-scoring nodes (up to ``max_nodes``).
    4. Expand each selected node to include direct neighbors (depth=1).
    5. Cap the total node count at ``max_nodes``.
    6. Annotate each returned node's metadata with ``_relevance_score``.
    7. If ``token_budget > 0``, greedily add nodes (highest relevance first)
       until the token budget would be exceeded.  When both ``token_budget``
       and ``max_nodes`` are set, the more restrictive constraint wins.
    8. Annotate the returned :class:`GraphData` with ``_token_estimate``
       (total estimated tokens for the result).
    9. Classify task intent and apply intent-specific retrieval boosting.
    10. Annotate the returned :class:`GraphData` with ``_retrieval_strategy``.
    11. If ``min_confidence > 0``, edges below the threshold are excluded.

    Returns an empty :class:`GraphData` when no node scores above zero.
    """
    # Classify intent before retrieval so we can steer the scoring
    intent = _classify_intent(task)

    # Try embedding-based scoring
    if use_embeddings and _embeddings_mod.is_available():
        result = _context_for_task_embeddings(graph, task, max_nodes)
    else:
        # Fall back to keyword scoring (existing implementation)
        result = _context_for_task_keywords(graph, task, max_nodes)

    # Apply intent-specific retrieval strategy on top of base scoring
    result = _apply_intent_strategy(graph, result, task, intent, max_nodes)

    # Apply domain boosting: if any domain name appears in the task, boost members
    result = _apply_domain_boosting(graph, result, task, max_nodes)

    # Apply confidence filtering if requested
    if min_confidence > 0.0:
        result.edges = [e for e in result.edges if e.confidence >= min_confidence]

    # Apply token_budget constraint if requested
    if token_budget > 0 and result.nodes:
        kept: dict[str, "Node"] = {}
        total_tokens = 0
        for nid, node in result.nodes.items():
            node_dict = node.model_dump()
            node_tokens = _estimate_tokens(node_dict, detail_level)
            if total_tokens + node_tokens <= token_budget:
                kept[nid] = node
                total_tokens += node_tokens
            # Nodes are already sorted by descending relevance; stop when budget exceeded
        kept_ids = set(kept.keys())
        result.nodes = kept
        result.edges = [
            e for e in result.edges
            if e.source in kept_ids and e.target in kept_ids
        ]
        result.token_estimate = total_tokens
    else:
        # Compute token estimate for the full result
        total_tokens = sum(
            _estimate_tokens(node.model_dump(), detail_level)
            for node in result.nodes.values()
        )
        result.token_estimate = total_tokens

    # Annotate with retrieval strategy
    result.retrieval_strategy = intent

    return result


def _apply_intent_strategy(
    graph: ArchGraph,
    result: GraphData,
    task: str,
    intent: str,
    max_nodes: int,
) -> GraphData:
    """Apply intent-specific retrieval boosting/expansion to the base result.

    This function augments *result* (already scored by keyword/embedding logic)
    with additional nodes or score boosts based on the classified *intent*.

    Strategies
    ----------
    create  — Boost exemplar nodes of the same type as the highest-scoring node.
    debug   — Include upstream dependency chain (reverse BFS on imports/calls edges).
    refactor — Include coupled nodes (sharing edges with target) + cycle members.
    delete  — Include blast radius (downstream dependents) + contract-violating nodes.
    test    — Include associated test files (nodes with ``source: test`` metadata).
    modify  — No change (default behavior).
    """
    if intent == "modify" or not graph.graph.nodes:
        return result

    # Identify seed node ids (highest-scored nodes from base result)
    seed_ids: set[str] = set(result.nodes.keys())
    # Top seed: the first node in result (sorted by descending relevance)
    top_seeds = list(result.nodes.keys())[:max(1, len(result.nodes) // 2)]

    extra_nodes: dict[str, Node] = {}

    if intent == "create":
        # Boost exemplar nodes: find nodes of the same type as the top seed
        if top_seeds:
            top_node = result.nodes[top_seeds[0]]
            target_type = top_node.type
            for nid, attrs in graph.graph.nodes(data=True):
                node = attrs.get("node")
                if node is None or nid in seed_ids:
                    continue
                if node.type == target_type:
                    # Add as exemplar with a modest relevance boost
                    exemplar = Node(
                        id=node.id,
                        type=node.type,
                        label=node.label,
                        metadata=dict(node.metadata),
                        file_path=node.file_path,
                        manual=node.manual,
                    )
                    exemplar.metadata["_relevance_score"] = 0.5
                    extra_nodes[nid] = exemplar

    elif intent == "debug":
        # Include upstream dependency chain: BFS on reversed graph
        # (nodes that the seeds DEPEND ON — i.e., they import/call the dependencies)
        dependency_edge_types = {"imports", "calls", "depends_on"}
        # We walk outgoing edges (A imports B means A depends on B)
        visited: set[str] = set()
        queue: list[str] = list(top_seeds)
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for _, neighbor, data in graph.graph.out_edges(current, data=True):
                edge_obj = data.get("edge")
                if edge_obj is None:
                    continue
                if edge_obj.type in dependency_edge_types and neighbor not in seed_ids:
                    neighbor_attrs = graph.graph.nodes.get(neighbor, {})
                    neighbor_node = neighbor_attrs.get("node")
                    if neighbor_node is not None and neighbor not in extra_nodes:
                        dep_node = Node(
                            id=neighbor_node.id,
                            type=neighbor_node.type,
                            label=neighbor_node.label,
                            metadata=dict(neighbor_node.metadata),
                            file_path=neighbor_node.file_path,
                            manual=neighbor_node.manual,
                        )
                        dep_node.metadata.setdefault("_relevance_score", 0)
                        extra_nodes[neighbor] = dep_node
                    if neighbor not in visited:
                        queue.append(neighbor)

    elif intent == "refactor":
        # Include coupled nodes (neighbors) + any nodes that are part of cycles
        # involving the target nodes
        cycles = graph.detect_cycles()
        cycle_node_ids: set[str] = set()
        for cycle in cycles:
            if any(nid in seed_ids for nid in cycle):
                cycle_node_ids.update(cycle)

        for nid in cycle_node_ids - seed_ids:
            attrs = graph.graph.nodes.get(nid, {})
            node = attrs.get("node")
            if node is not None:
                cycle_node = Node(
                    id=node.id,
                    type=node.type,
                    label=node.label,
                    metadata=dict(node.metadata),
                    file_path=node.file_path,
                    manual=node.manual,
                )
                cycle_node.metadata.setdefault("_relevance_score", 0)
                extra_nodes[nid] = cycle_node

        # Also include direct neighbors of top seeds not already in result
        for seed_id in top_seeds:
            for _, neighbor in graph.graph.out_edges(seed_id):
                if neighbor not in seed_ids and neighbor not in extra_nodes:
                    neighbor_attrs = graph.graph.nodes.get(neighbor, {})
                    neighbor_node = neighbor_attrs.get("node")
                    if neighbor_node is not None:
                        coupled = Node(
                            id=neighbor_node.id,
                            type=neighbor_node.type,
                            label=neighbor_node.label,
                            metadata=dict(neighbor_node.metadata),
                            file_path=neighbor_node.file_path,
                            manual=neighbor_node.manual,
                        )
                        coupled.metadata.setdefault("_relevance_score", 0)
                        extra_nodes[neighbor] = coupled
            for neighbor, _ in graph.graph.in_edges(seed_id):
                if neighbor not in seed_ids and neighbor not in extra_nodes:
                    neighbor_attrs = graph.graph.nodes.get(neighbor, {})
                    neighbor_node = neighbor_attrs.get("node")
                    if neighbor_node is not None:
                        coupled = Node(
                            id=neighbor_node.id,
                            type=neighbor_node.type,
                            label=neighbor_node.label,
                            metadata=dict(neighbor_node.metadata),
                            file_path=neighbor_node.file_path,
                            manual=neighbor_node.manual,
                        )
                        coupled.metadata.setdefault("_relevance_score", 0)
                        extra_nodes[neighbor] = coupled

    elif intent == "delete":
        # Include blast radius: nodes that DEPEND ON the seeds (incoming callers/importers)
        blast_ids: set[str] = set()
        for seed_id in top_seeds:
            if seed_id in graph.graph:
                blast_ids.update(graph.get_all_ancestors(seed_id))
        for nid in blast_ids - seed_ids:
            attrs = graph.graph.nodes.get(nid, {})
            node = attrs.get("node")
            if node is not None:
                blast_node = Node(
                    id=node.id,
                    type=node.type,
                    label=node.label,
                    metadata=dict(node.metadata),
                    file_path=node.file_path,
                    manual=node.manual,
                )
                blast_node.metadata.setdefault("_relevance_score", 0)
                blast_node.metadata["_in_blast_radius"] = True
                extra_nodes[nid] = blast_node

        # Also include any contract-violation nodes (nodes with violates edges to seeds)
        for seed_id in seed_ids:
            for src, _, data in graph.graph.in_edges(seed_id, data=True):
                edge_obj = data.get("edge")
                if edge_obj is not None and edge_obj.type == "violates":
                    if src not in seed_ids and src not in extra_nodes:
                        attrs = graph.graph.nodes.get(src, {})
                        node = attrs.get("node")
                        if node is not None:
                            viol_node = Node(
                                id=node.id,
                                type=node.type,
                                label=node.label,
                                metadata=dict(node.metadata),
                                file_path=node.file_path,
                                manual=node.manual,
                            )
                            viol_node.metadata.setdefault("_relevance_score", 0)
                            extra_nodes[src] = viol_node

    elif intent == "test":
        # Include target node dependencies + test file nodes (source: test)
        for nid, attrs in graph.graph.nodes(data=True):
            node = attrs.get("node")
            if node is None or nid in seed_ids:
                continue
            if node.metadata.get("source") == "test":
                test_node = Node(
                    id=node.id,
                    type=node.type,
                    label=node.label,
                    metadata=dict(node.metadata),
                    file_path=node.file_path,
                    manual=node.manual,
                )
                test_node.metadata.setdefault("_relevance_score", 0)
                extra_nodes[nid] = test_node

    # Merge extra nodes into result (cap at max_nodes)
    if extra_nodes:
        all_nodes = dict(result.nodes)
        for nid, node in extra_nodes.items():
            if len(all_nodes) >= max_nodes:
                break
            all_nodes[nid] = node

        # Re-sort all nodes by descending relevance score
        result.nodes = dict(
            sorted(
                all_nodes.items(),
                key=lambda item: (-item[1].metadata.get("_relevance_score", 0), item[0]),
            )
        )

        # Add edges connecting newly added nodes
        all_node_ids = set(result.nodes.keys())
        existing_edge_keys = {(e.source, e.target, e.type) for e in result.edges}
        for src, tgt, data in graph.graph.edges(data=True):
            if src in all_node_ids and tgt in all_node_ids:
                edge_obj = data.get("edge")
                if edge_obj is not None:
                    key = (src, tgt, edge_obj.type)
                    if key not in existing_edge_keys:
                        result.edges.append(edge_obj)
                        existing_edge_keys.add(key)

    return result


def _apply_domain_boosting(
    graph: ArchGraph,
    result: GraphData,
    task: str,
    max_nodes: int,
) -> GraphData:
    """Boost domain-member nodes when the task mentions a known domain name.

    For each domain node in the graph, if the domain's label appears in *task*,
    all members of that domain are:
    1. Added to the result (if not already present and within *max_nodes*).
    2. Given a boosted ``_relevance_score`` so they rank higher.
    """
    from codegiraffe.domains import get_domain_membership
    from codegiraffe.schema import NodeType as _NodeType

    # Collect domain nodes
    domain_nodes: list = []
    for _, attrs in graph.graph.nodes(data=True):
        node = attrs.get("node")
        if node is not None and node.type == _NodeType.DOMAIN:
            domain_nodes.append(node)

    if not domain_nodes:
        return result

    task_lower = task.lower()

    # Build membership map: node_id -> domain_label
    membership = get_domain_membership(graph)

    # Determine which domains are mentioned in the task
    matched_domains: set[str] = set()
    for domain_node in domain_nodes:
        if domain_node.label.lower() in task_lower:
            matched_domains.add(domain_node.label)

    if not matched_domains:
        return result

    _DOMAIN_BOOST = 100
    for node_id, domain_label in membership.items():
        if domain_label not in matched_domains:
            continue

        node_attrs = graph.graph.nodes.get(node_id, {})
        member_node = node_attrs.get("node")
        if member_node is None:
            continue

        if node_id in result.nodes:
            existing_score = result.nodes[node_id].metadata.get("_relevance_score", 0)
            result.nodes[node_id].metadata["_relevance_score"] = existing_score + _DOMAIN_BOOST
        elif len(result.nodes) < max_nodes:
            member_node.metadata["_relevance_score"] = _DOMAIN_BOOST
            result.nodes[node_id] = member_node

    # Re-sort by descending relevance score
    if result.nodes:
        result.nodes = dict(
            sorted(
                result.nodes.items(),
                key=lambda item: (-item[1].metadata.get("_relevance_score", 0), item[0]),
            )
        )

    return result


def _context_for_task_embeddings(
    graph: ArchGraph, task: str, max_nodes: int
) -> GraphData:
    """Embedding-based context scoring."""
    from codegiraffe.embeddings import node_to_text, score_nodes_by_embedding

    # Build text representations for all nodes
    node_texts = []
    for nid, attrs in graph.graph.nodes(data=True):
        node = attrs.get("node")
        if node is None:
            continue
        text = node_to_text(node.id, node.type, node.label, node.file_path, node.metadata)
        node_texts.append((node.id, text))

    if not node_texts:
        return GraphData(
            project_path=graph.to_data().project_path,
            last_scan=graph.to_data().last_scan,
            schema_version=graph.to_data().schema_version,
        )

    project_path = graph.to_data().project_path
    scored = score_nodes_by_embedding(task, node_texts, project_path)

    # Filter out very low scores
    scored = [(nid, score) for nid, score in scored if score > 0.1]

    if not scored:
        return GraphData(
            project_path=graph.to_data().project_path,
            last_scan=graph.to_data().last_scan,
            schema_version=graph.to_data().schema_version,
        )

    # Build score map
    score_map = {nid: score for nid, score in scored}

    # Take top seeds
    seed_limit = max(1, max_nodes // 2)
    seeds = scored[:seed_limit]

    # Expand each seed to depth=1
    base_data = graph.to_data()
    parts = []
    for nid, _ in seeds:
        sub = graph.get_subgraph(nid, depth=1)
        parts.append(sub)

    merged = _merge_graph_data(parts, base_data)

    # Cap at max_nodes
    if len(merged.nodes) > max_nodes:
        node_list = list(merged.nodes.values())
        node_list.sort(key=lambda n: (-score_map.get(n.id, 0), n.id))
        kept_ids = {n.id for n in node_list[:max_nodes]}
        merged.nodes = {nid: n for nid, n in merged.nodes.items() if nid in kept_ids}
        merged.edges = [e for e in merged.edges if e.source in kept_ids and e.target in kept_ids]

    # Annotate with scores
    for nid, node in merged.nodes.items():
        node.metadata["_relevance_score"] = round(score_map.get(nid, 0), 4)

    # Sort by score
    merged.nodes = dict(
        sorted(merged.nodes.items(), key=lambda item: (-item[1].metadata.get("_relevance_score", 0), item[0]))
    )

    # Include decision nodes that constrain any node in the subgraph
    extended_ids = _include_constraining_decisions(set(merged.nodes.keys()), graph)
    for nid in extended_ids - set(merged.nodes.keys()):
        node_attrs = graph.graph.nodes.get(nid, {})
        node_obj = node_attrs.get("node")
        if node_obj is not None:
            merged.nodes[nid] = node_obj
            # Include constrains edges for the newly added decision nodes
            for src, tgt, data in graph.graph.edges(data=True):
                if src == nid and tgt in merged.nodes:
                    edge_obj = data.get("edge")
                    if edge_obj is not None:
                        existing_edge_keys = {(e.source, e.target, e.type) for e in merged.edges}
                        edge_key = (src, tgt, edge_obj.type)
                        if edge_key not in existing_edge_keys:
                            merged.edges.append(edge_obj)

    return merged


def _context_for_task_keywords(
    graph: ArchGraph, task: str, max_nodes: int
) -> GraphData:
    """Keyword-based context scoring (original implementation)."""
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

    # Include decision nodes that constrain any node in the subgraph
    extended_ids = _include_constraining_decisions(set(merged.nodes.keys()), graph)
    for nid in extended_ids - set(merged.nodes.keys()):
        node_attrs = graph.graph.nodes.get(nid, {})
        node_obj = node_attrs.get("node")
        if node_obj is not None:
            merged.nodes[nid] = node_obj
            # Include constrains edges for the newly added decision nodes
            for src, tgt, data in graph.graph.edges(data=True):
                if src == nid and tgt in merged.nodes:
                    edge_obj = data.get("edge")
                    if edge_obj is not None:
                        existing_edge_keys = {(e.source, e.target, e.type) for e in merged.edges}
                        edge_key = (src, tgt, edge_obj.type)
                        if edge_key not in existing_edge_keys:
                            merged.edges.append(edge_obj)

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



# ---------------------------------------------------------------------------
# Blast radius & impact analysis
# ---------------------------------------------------------------------------


def _compute_contract_impact(graph: ArchGraph, node_id: str) -> list[dict[str, Any]]:
    """Find consumers of contracts produced by *node_id*.

    Walks all ``contract`` nodes whose ``metadata["producer"]`` equals
    *node_id*, then collects every consumer listed in
    ``metadata["consumers"]`` that exists in the graph.

    Returns a list of impact entries with ``severity="critical"`` and
    ``distance="contract"``.
    """
    impact: list[dict[str, Any]] = []

    # If the target node IS a contract, report its consumers directly
    target_data = graph.graph.nodes.get(node_id, {}).get("node")
    if target_data is not None and target_data.type == "contract":
        consumers = target_data.metadata.get("consumers", [])
        for consumer_id in consumers:
            if consumer_id not in graph.graph:
                continue
            consumer_data = graph.graph.nodes[consumer_id].get("node")
            if consumer_data is None:
                continue
            impact.append({
                "node_id": consumer_id,
                "label": consumer_data.label,
                "type": consumer_data.type,
                "distance": "contract",
                "severity": "critical",
                "path": [node_id, consumer_id],
                "contract_name": target_data.label,
                "contract_type": target_data.metadata.get("contract_type", "unknown"),
            })
        return impact

    for nid, data in graph.graph.nodes(data=True):
        node_obj = data.get("node")
        if node_obj is None:
            continue
        if node_obj.type != "contract":
            continue
        if node_obj.metadata.get("producer") != node_id:
            continue
        contract_id = nid
        consumers = node_obj.metadata.get("consumers", [])
        for consumer_id in consumers:
            if consumer_id not in graph.graph:
                continue
            consumer_data = graph.graph.nodes[consumer_id].get("node")
            if consumer_data is None:
                continue
            impact.append({
                "node_id": consumer_id,
                "label": consumer_data.label,
                "type": consumer_data.type,
                "distance": "contract",
                "severity": "critical",
                "path": [node_id, contract_id, consumer_id],
                "contract_name": node_obj.label,
                "contract_type": node_obj.metadata.get("contract_type", "unknown"),
            })
    return impact


def _compute_cross_team_impact(
    graph: ArchGraph,
    node_id: str,
    downstream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify downstream nodes owned by a different team than *node_id*.

    Compares the ``owner`` metadata field of *node_id* against each node in
    *downstream*.  Only nodes that have an explicit ``owner`` annotation that
    differs from the changed node's owner are flagged.

    Nodes without an owner annotation (on either side) are NOT included.

    Parameters
    ----------
    graph:
        The architecture graph.
    node_id:
        The ID of the changed node.
    downstream:
        The downstream impact list from :func:`compute_blast_radius`.

    Returns
    -------
    list[dict[str, Any]]
        List of cross-team impact entries, each with ``node_id``, ``owner``,
        ``changed_node_owner``, ``label``, ``type``, and ``distance``.
    """
    changed_node_data = graph.graph.nodes.get(node_id, {}).get("node")
    if changed_node_data is None:
        return []

    changed_owner = changed_node_data.metadata.get("owner")
    # If the changed node has no owner, we cannot detect cross-team impact
    if not changed_owner:
        return []

    cross_team: list[dict[str, Any]] = []
    for item in downstream:
        desc_id = item["node_id"]
        desc_node = graph.graph.nodes.get(desc_id, {}).get("node")
        if desc_node is None:
            continue
        desc_owner = desc_node.metadata.get("owner")
        # Only flag if the downstream node has an owner that differs
        if desc_owner and desc_owner != changed_owner:
            cross_team.append({
                "node_id": desc_id,
                "label": desc_node.label,
                "type": desc_node.type,
                "distance": item["distance"],
                "owner": desc_owner,
                "changed_node_owner": changed_owner,
            })

    return cross_team


def _compute_domain_groups(
    graph: ArchGraph,
    downstream: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Group downstream node IDs by their domain membership.

    Parameters
    ----------
    graph:
        The architecture graph (used to read domain membership).
    downstream:
        The list of downstream impact entries from ``compute_blast_radius``.

    Returns
    -------
    dict[str, list[str]]
        Maps domain name to sorted list of downstream node IDs in that domain.
        Returns an empty dict when no domains are defined.
    """
    from codegiraffe.domains import get_domain_membership

    membership = get_domain_membership(graph)
    if not membership:
        return {}

    groups: dict[str, list[str]] = {}
    for entry in downstream:
        nid = entry["node_id"]
        domain_name = membership.get(nid)
        if domain_name is not None:
            groups.setdefault(domain_name, []).append(nid)

    for name in groups:
        groups[name].sort()

    return groups


def compute_blast_radius(
    graph: ArchGraph,
    node_id: str,
    include_upstream: bool = False,
    max_depth: int | None = None,
) -> dict[str, Any]:
    """Compute the blast radius of changing *node_id*.

    Returns a dict describing all downstream (and optionally upstream) nodes
    affected by a change to the target node, along with cycle information
    and critical-path hotspots within the impact zone.

    Parameters
    ----------
    graph:
        The architecture graph to analyze.
    node_id:
        The node whose blast radius should be computed.
    include_upstream:
        If ``True``, also compute upstream (ancestor) impact.
    max_depth:
        If set, limit the blast radius to nodes within this many hops.

    Raises
    ------
    ValueError
        If *node_id* is not present in the graph (includes fuzzy suggestions).
    """
    # Validate node exists
    if node_id not in graph.graph:
        candidates = _all_node_ids(graph)
        suggestions = _fuzzy_suggestions(node_id, candidates)
        msg = f"Node '{node_id}' not found in graph."
        if suggestions:
            suggestion_str = ", ".join(f"'{s}'" for s in suggestions)
            msg += f" Did you mean one of: {suggestion_str}?"
        raise ValueError(msg)

    # Target node data
    target_node_data = graph.graph.nodes[node_id].get("node")
    target_info: dict[str, Any] = {
        "id": node_id,
        "label": target_node_data.label if target_node_data else node_id,
        "type": target_node_data.type if target_node_data else "unknown",
        "file_path": target_node_data.file_path if target_node_data else None,
    }

    # --- Downstream impact ---
    all_descendants = graph.get_all_descendants(node_id)

    # Efficient single-BFS for all distances and paths
    distances = dict(nx.single_source_shortest_path_length(graph.graph, node_id))
    paths = dict(nx.single_source_shortest_path(graph.graph, node_id))

    downstream: list[dict[str, Any]] = []
    for desc_id in sorted(all_descendants):
        dist = distances.get(desc_id)
        if dist is None:
            continue
        if max_depth is not None and dist > max_depth:
            continue
        desc_node = graph.graph.nodes[desc_id].get("node")
        if desc_node is None:
            continue
        path = paths.get(desc_id, [])
        path_conf = _path_min_confidence(graph.graph, path)
        downstream.append({
            "node_id": desc_id,
            "label": desc_node.label,
            "type": desc_node.type,
            "distance": dist,
            "severity": _compute_severity_with_confidence(dist, path_conf),
            "confidence": path_conf,
            "path": path,
            "file_path": desc_node.file_path,
        })

    downstream.sort(key=lambda x: (x["distance"], x["node_id"]))

    # --- Upstream impact (optional) ---
    upstream: list[dict[str, Any]] = []
    if include_upstream:
        all_ancestors = graph.get_all_ancestors(node_id)
        rev = graph.graph.reverse()
        up_distances = dict(nx.single_source_shortest_path_length(rev, node_id))
        up_paths = dict(nx.single_source_shortest_path(rev, node_id))

        for anc_id in sorted(all_ancestors):
            dist = up_distances.get(anc_id)
            if dist is None:
                continue
            if max_depth is not None and dist > max_depth:
                continue
            anc_node = graph.graph.nodes[anc_id].get("node")
            if anc_node is None:
                continue
            upstream.append({
                "node_id": anc_id,
                "label": anc_node.label,
                "type": anc_node.type,
                "distance": dist,
                "severity": _compute_severity(dist),
                "path": up_paths.get(anc_id, []),
                "file_path": anc_node.file_path,
            })

        upstream.sort(key=lambda x: (x["distance"], x["node_id"]))

    # --- Cycle detection ---
    all_cycles = graph.detect_cycles(max_cycles=50)
    relevant_cycles = [c for c in all_cycles if node_id in c]

    # --- Critical paths (betweenness in impact subgraph) ---
    impact_ids = all_descendants | {node_id}
    # Filter to nodes actually in downstream (respecting max_depth)
    if max_depth is not None:
        downstream_ids = {item["node_id"] for item in downstream}
        impact_ids = downstream_ids | {node_id}
    sub = graph.graph.subgraph(impact_ids)
    critical_paths: list[dict[str, Any]] = []
    if len(sub) > 1:
        betweenness = nx.betweenness_centrality(sub)
        critical = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:5]
        for nid, score in critical:
            cp_node = graph.graph.nodes[nid].get("node")
            if cp_node is not None:
                critical_paths.append({
                    "node_id": nid,
                    "label": cp_node.label,
                    "centrality": round(score, 4),
                })

    # Contract impact — consumers of contracts produced by this node
    contract_impact = _compute_contract_impact(graph, node_id)

    # Cross-team impact — downstream nodes owned by a different team
    cross_team_impact = _compute_cross_team_impact(graph, node_id, downstream)

    # Domain groups — group impacted downstream nodes by domain membership
    domain_groups = _compute_domain_groups(graph, downstream)

    result: dict[str, Any] = {
        "target_node": target_info,
        "downstream": downstream,
        "total_impact_count": len(downstream) + len(contract_impact),
        "contract_impact": contract_impact,
        "cycles": relevant_cycles,
        "critical_paths": critical_paths,
        "cross_team_impact": cross_team_impact,
        "domain_groups": domain_groups,
    }
    if include_upstream:
        result["upstream"] = upstream

    return result


def compute_risk_with_coverage(base_risk: float, node: "Node") -> float:
    """Apply a 1.5x risk multiplier for nodes with no test coverage.

    A node is considered uncovered when its ``_test_coverage`` metadata key is
    present and equals ``0.0``, or when the key is absent entirely (unknown
    coverage).  A node is considered covered when ``_test_coverage`` is present
    and greater than zero.

    Parameters
    ----------
    base_risk:
        The raw risk score for the node.
    node:
        The graph node whose metadata is inspected for ``_test_coverage``.

    Returns
    -------
    float
        ``base_risk * 1.5`` if uncovered/unknown, ``base_risk`` otherwise.
    """
    coverage = node.metadata.get("_test_coverage")
    if coverage is None or coverage == 0.0:
        return base_risk * 1.5
    return base_risk


def generate_impact_summary(blast_radius: dict[str, Any], graph: ArchGraph) -> str:
    """Generate a human-readable markdown impact report from *blast_radius* data.

    Sections are omitted when they contain no items.

    Parameters
    ----------
    blast_radius:
        The dict returned by :func:`compute_blast_radius`.
    graph:
        The architecture graph (used to look up edge types for direct deps).
    """
    target = blast_radius["target_node"]
    downstream = blast_radius["downstream"]
    upstream = blast_radius.get("upstream", [])
    cycles = blast_radius.get("cycles", [])
    critical_paths = blast_radius.get("critical_paths", [])
    total = blast_radius["total_impact_count"]

    lines: list[str] = []
    lines.append(f"## Impact Analysis: {target['label']}")
    lines.append("")
    lines.append(f"**Total blast radius:** {total} nodes affected")
    lines.append("")

    # Group downstream by severity (handles both normal and uncertain_ prefixed values)
    direct = [n for n in downstream if n["severity"] in ("direct", "uncertain_direct")]
    transitive = [n for n in downstream if n["severity"] in ("transitive", "uncertain_transitive")]
    indirect = [n for n in downstream if n["severity"] in ("indirect", "uncertain_indirect")]

    target_id = target["id"]

    # --- Direct Dependencies ---
    if direct:
        lines.append(f"### Direct Dependencies ({len(direct)})")
        lines.append("")
        for item in direct:
            edge_data = graph.graph.edges.get((target_id, item["node_id"]), {})
            edge_obj = edge_data.get("edge")
            edge_type = edge_obj.type if edge_obj else "unknown"
            fp = f" [{item['file_path']}]" if item.get("file_path") else ""
            lines.append(
                f"- **{item['label']}** ({item['type']}) -- via {edge_type} edge{fp}"
            )
        lines.append("")

    # --- Transitive Impact ---
    if transitive:
        lines.append(f"### Transitive Impact ({len(transitive)})")
        lines.append("")
        for item in transitive:
            path_summary = " -> ".join(item["path"])
            fp = f" [{item['file_path']}]" if item.get("file_path") else ""
            lines.append(
                f"- **{item['label']}** ({item['type']}) -- "
                f"{item['distance']} hops via {path_summary}{fp}"
            )
        lines.append("")

    # --- Indirect Impact ---
    if indirect:
        lines.append(f"### Indirect Impact ({len(indirect)})")
        lines.append("")
        for item in indirect:
            fp = f" [{item['file_path']}]" if item.get("file_path") else ""
            lines.append(
                f"- **{item['label']}** ({item['type']}) -- "
                f"{item['distance']} hops{fp}"
            )
        lines.append("")

    # --- Upstream Dependencies ---
    if upstream:
        lines.append(f"### Upstream Dependencies ({len(upstream)})")
        lines.append("")
        for item in upstream:
            fp = f" [{item['file_path']}]" if item.get("file_path") else ""
            lines.append(
                f"- **{item['label']}** ({item['type']}) -- "
                f"{item['distance']} hops upstream{fp}"
            )
        lines.append("")

    # --- Circular Dependencies ---
    if cycles:
        lines.append(f"### Circular Dependencies")
        lines.append("")
        for cycle in cycles:
            display = cycle + [cycle[0]]
            lines.append(f"- {' -> '.join(display)}")
        lines.append("")

    # --- Hotspots in Impact Zone ---
    if critical_paths:
        lines.append("### Hotspots in Impact Zone")
        lines.append("")
        for cp in critical_paths:
            lines.append(
                f"- **{cp['label']}** (centrality: {cp['centrality']:.4f})"
            )
        lines.append("")

    # --- Contract Impact ---
    contract_impact = blast_radius.get("contract_impact", [])
    if contract_impact:
        lines.append(f"\n### Contract Impact ({len(contract_impact)} consumers at risk)")
        lines.append("")
        for item in contract_impact:
            contract_name = item.get("contract_name", "unknown")
            contract_type = item.get("contract_type", "unknown")
            lines.append(f"- **{item['label']}** ({item['type']}) — CRITICAL: consumes {contract_type} contract \"{contract_name}\"")
        lines.append("")

    # --- Recommendations ---
    recommendations: list[str] = []
    if contract_impact:
        recommendations.append(
            f"**CRITICAL:** Changing this node breaks {len(contract_impact)} contract consumer(s). Coordinate with dependent teams before proceeding."
        )
    if direct:
        # Recommend testing the direct dep with the highest downstream reach
        most_connected = max(
            direct,
            key=lambda d: len(graph.get_all_descendants(d["node_id"])),
        )
        desc_count = len(graph.get_all_descendants(most_connected["node_id"]))
        if desc_count > 0:
            recommendations.append(
                f"Consider testing **{most_connected['label']}** -- it is a direct "
                f"dependency with {desc_count} downstream dependents"
            )
    if cycles:
        for cycle in cycles:
            display = cycle + [cycle[0]]
            recommendations.append(
                f"Warning: circular dependency detected: {' -> '.join(display)}"
            )
    if critical_paths:
        top_hotspot = critical_paths[0]
        if top_hotspot["centrality"] > 0:
            recommendations.append(
                f"**{top_hotspot['label']}** is the highest-centrality node in the "
                f"impact zone -- changes here amplify blast radius"
            )

    if recommendations:
        lines.append("### Recommendations")
        lines.append("")
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contract queries
# ---------------------------------------------------------------------------


def get_contracts(
    graph: ArchGraph,
    contract_type: str | None = None,
    status: str | None = None,
    node_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get all contract nodes from the graph, with optional filtering.

    Parameters
    ----------
    graph:
        The architecture graph to query.
    contract_type:
        Filter by contract type (e.g. "api", "event", "data", "config").
    status:
        Filter by contract status (e.g. "active", "deprecated").
    node_id:
        Filter to contracts where *node_id* is the producer or a consumer.

    Returns
    -------
    list[dict[str, Any]]
        List of enriched contract dicts with producer/consumer details.
    """
    contracts: list[dict[str, Any]] = []

    for nid in graph.graph.nodes:
        node_data = graph.graph.nodes[nid].get("node")
        if node_data is None or node_data.type != "contract":
            continue

        meta = node_data.metadata

        # Filter by contract_type
        if contract_type is not None and meta.get("contract_type") != contract_type:
            continue

        # Filter by status
        if status is not None and meta.get("status") != status:
            continue

        # Filter by node_id (producer or consumer)
        if node_id is not None:
            producer_id = meta.get("producer", "")
            consumer_ids = meta.get("consumers", [])
            if node_id != producer_id and node_id not in consumer_ids:
                continue

        # Resolve producer details
        producer_id = meta.get("producer", "")
        producer_info: dict[str, Any] = {"id": producer_id, "label": producer_id}
        if producer_id and producer_id in graph.graph:
            p_node = graph.graph.nodes[producer_id].get("node")
            if p_node is not None:
                producer_info = {
                    "id": producer_id,
                    "label": p_node.label,
                    "file_path": p_node.file_path,
                    "type": p_node.type,
                }

        # Resolve consumer details
        consumer_ids = meta.get("consumers", [])
        consumers_info: list[dict[str, Any]] = []
        for cid in consumer_ids:
            c_info: dict[str, Any] = {"id": cid, "label": cid}
            if cid in graph.graph:
                c_node = graph.graph.nodes[cid].get("node")
                if c_node is not None:
                    c_info = {
                        "id": cid,
                        "label": c_node.label,
                        "file_path": c_node.file_path,
                        "type": c_node.type,
                    }
            consumers_info.append(c_info)

        contracts.append({
            "id": nid,
            "label": node_data.label,
            "contract_type": meta.get("contract_type", "unknown"),
            "status": meta.get("status", "unknown"),
            "producer": producer_info,
            "consumers": consumers_info,
            "version": meta.get("version", ""),
        })

    return contracts


def validate_contracts(graph: ArchGraph) -> dict[str, Any]:
    """Validate all contract nodes in the graph.

    Checks that producer and consumer nodes referenced by each contract
    actually exist in the graph.

    Returns
    -------
    dict[str, Any]
        Classification of contracts into valid, broken, orphaned, and
        deprecated_with_consumers, plus total_contracts count.
    """
    valid: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    deprecated_with_consumers: list[dict[str, Any]] = []

    for nid in graph.graph.nodes:
        node_data = graph.graph.nodes[nid].get("node")
        if node_data is None or node_data.type != "contract":
            continue

        meta = node_data.metadata
        producer_id = meta.get("producer", "")
        consumer_ids = meta.get("consumers", [])

        producer_exists = producer_id != "" and producer_id in graph.graph
        consumers_exist = [cid for cid in consumer_ids if cid in graph.graph]
        all_consumers_missing = len(consumer_ids) > 0 and len(consumers_exist) == 0

        entry = {
            "id": nid,
            "label": node_data.label,
            "contract_type": meta.get("contract_type", "unknown"),
            "status": meta.get("status", "unknown"),
            "producer": producer_id,
            "consumers": consumer_ids,
            "producer_exists": producer_exists,
            "consumers_existing": consumers_exist,
        }

        # Check for deprecated with active consumers
        if meta.get("status") == "deprecated" and len(consumers_exist) > 0:
            deprecated_with_consumers.append(entry)
        # Check for broken (producer missing)
        elif not producer_exists:
            broken.append(entry)
        # Check for orphaned (all consumers missing)
        elif all_consumers_missing:
            orphaned.append(entry)
        # Otherwise valid
        else:
            valid.append(entry)

    return {
        "valid": valid,
        "broken": broken,
        "orphaned": orphaned,
        "deprecated_with_consumers": deprecated_with_consumers,
        "total_contracts": len(valid) + len(broken) + len(orphaned) + len(deprecated_with_consumers),
    }


def detect_drift(
    graph: ArchGraph, project_path: str, git_depth: int = 10
) -> list[dict[str, str]]:
    """Compare the current graph against a fresh scan of *project_path*.

    Re-runs the scanner to discover what the codebase currently contains,
    then compares against the non-manual nodes in the existing graph.

    Parameters
    ----------
    graph:
        The existing architecture graph.
    project_path:
        Filesystem path to the project root.
    git_depth:
        How many recent commits to check for git-detected file renames.
        Defaults to 10.

    Returns a list of drift records, each a dict with:
    - ``type``: one of ``"missing_in_code"``, ``"missing_in_graph"``,
      ``"potential_rename"``, ``"file_renamed"``, ``"edge_missing_in_code"``,
      or ``"edge_missing_in_graph"``
    - ``node_id``: the relevant node id (or edge description)
    - ``details``: human-readable explanation

    An empty list means no drift was detected.
    """
    # Import scanner lazily to avoid circular imports and to allow the
    # scanner module to be developed independently.
    from codegiraffe.scanner import scan_project  # type: ignore[import-untyped]

    scanned_result = scan_project(project_path)
    scanned_ids: set[str] = {node.id for node in scanned_result.nodes}

    # Build lookup maps for node objects (used by _enhanced_similarity)
    scanned_node_map: dict[str, Node] = {n.id: n for n in scanned_result.nodes}

    # Collect non-manual node ids from the existing graph
    graph_data = graph.to_data()
    graph_auto_ids: set[str] = set()
    graph_node_map: dict[str, Node] = {}
    for nid, node in graph_data.nodes.items():
        if not node.manual:
            graph_auto_ids.add(nid)
            graph_node_map[nid] = node

    missing_in_code = graph_auto_ids - scanned_ids  # in graph but not in scan
    missing_in_graph = scanned_ids - graph_auto_ids  # in scan but not in graph

    drifts: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Git-aware file rename detection
    # ------------------------------------------------------------------
    git_renames = _detect_git_renames(project_path, since=f"HEAD~{git_depth}")
    if git_renames:
        # Check if any missing nodes have file_paths that match git renames
        git_matched_code: set[str] = set()
        git_matched_graph: set[str] = set()

        for old_id in sorted(missing_in_code):
            old_node = graph_node_map.get(old_id)
            if not old_node or not old_node.file_path:
                continue
            for old_path, new_path in git_renames.items():
                if old_node.file_path == old_path or old_node.file_path.endswith(
                    "/" + old_path
                ):
                    # Find a new node whose file_path matches the rename target
                    for new_id in sorted(missing_in_graph):
                        if new_id in git_matched_code:
                            continue
                        new_node = scanned_node_map.get(new_id)
                        if not new_node or not new_node.file_path:
                            continue
                        if new_node.file_path == new_path or new_node.file_path.endswith(
                            "/" + new_path
                        ):
                            drifts.append({
                                "type": "file_renamed",
                                "node_id": old_id,
                                "details": (
                                    f"File '{old_path}' was renamed to "
                                    f"'{new_path}' (git). Node '{old_id}' "
                                    f"likely moved to '{new_id}'."
                                ),
                            })
                            git_matched_code.add(new_id)
                            git_matched_graph.add(old_id)
                            break
                    break

        # Remove git-matched nodes from the pools so they aren't double-reported
        missing_in_code = missing_in_code - git_matched_graph
        missing_in_graph = missing_in_graph - git_matched_code

    # ------------------------------------------------------------------
    # Similarity-based rename detection (enhanced)
    # ------------------------------------------------------------------
    rename_threshold = 0.5
    matched_code: set[str] = set()
    matched_graph: set[str] = set()

    for old_id in sorted(missing_in_code):
        best_match: str | None = None
        best_score: float = 0.0
        old_node = graph_node_map.get(old_id)
        for new_id in sorted(missing_in_graph):
            if new_id in matched_code:
                continue
            new_node = scanned_node_map.get(new_id)
            sim = _enhanced_similarity(old_id, new_id, old_node, new_node)
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

    # ------------------------------------------------------------------
    # Edge drift detection
    # ------------------------------------------------------------------
    graph_edges_auto = [e for e in graph_data.edges]
    drifts.extend(_detect_edge_drift(graph_edges_auto, scanned_result.edges))

    return drifts


# ---------------------------------------------------------------------------
# Change impact validation
# ---------------------------------------------------------------------------


def map_files_to_nodes(
    graph: ArchGraph, file_paths: list[str]
) -> dict[str, list[str]]:
    """Map file paths to graph node IDs.

    For each file path the following matching strategies are tried:

    1. **Exact match** -- the node's ``file_path`` attribute equals the query
       path exactly.
    2. **Suffix match** -- the node's ``file_path`` ends with the query path
       (handles absolute vs. relative differences).
    3. **Module ID match** -- the query path is converted to a dotted module
       name and compared against node IDs prefixed with ``mod:``.

    Returns
    -------
    dict[str, list[str]]
        Mapping of each input *file_path* to the list of matching node IDs.
        Unmatched paths map to empty lists.
    """
    result: dict[str, list[str]] = {fp: [] for fp in file_paths}

    # Pre-compute module-style names for each query path.
    # e.g. "src/codegiraffe/scanner.py" -> "codegiraffe.scanner"
    path_to_module: dict[str, str] = {}
    for fp in file_paths:
        # Strip leading directories like "src/" and the extension
        base = fp
        # Remove common prefixes
        for prefix in ("src/", "lib/", "pkg/"):
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        # Strip extension
        if "." in os.path.basename(base):
            base = base.rsplit(".", 1)[0]
        # Convert path separators to dots
        module_name = base.replace("/", ".").replace("\\", ".")
        path_to_module[fp] = module_name

    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None:
            continue

        for fp in file_paths:
            matched = False
            # Strategy 1: exact match on file_path
            if node.file_path and node.file_path == fp:
                matched = True
            # Strategy 2: suffix match
            elif node.file_path and (
                node.file_path.endswith("/" + fp)
                or fp.endswith("/" + node.file_path)
            ):
                matched = True
            # Strategy 3: module ID match
            elif nid.startswith("mod:") and path_to_module.get(fp):
                mod_name = path_to_module[fp]
                node_mod = nid[4:]  # strip "mod:" prefix
                if node_mod == mod_name or node_mod.endswith("." + mod_name.split(".")[-1]):
                    # More precise: check if the module name matches
                    if mod_name == node_mod or mod_name.endswith(node_mod) or node_mod.endswith(mod_name):
                        matched = True

            if matched and nid not in result[fp]:
                result[fp].append(nid)

    return result


def validate_changes(
    graph: ArchGraph, diff_files: list[DiffFile]
) -> ChangeReport:
    """Validate whether a set of file changes adequately covers the blast radius.

    Identifies graph nodes affected by the change, computes the combined
    blast radius of all changed nodes, and partitions impacted nodes into
    *covered* (also changed) and *uncovered* (potentially missing changes).
    Contract violations are flagged when a contract producer is changed but
    its consumers are not.

    Parameters
    ----------
    graph:
        The architecture graph to analyze.
    diff_files:
        Parsed diff files representing the change set.

    Returns
    -------
    ChangeReport
        Aggregate report with changed/covered/uncovered nodes,
        contract violations, and recommendations.
    """
    if not diff_files:
        return ChangeReport()

    # Extract file paths from diff
    file_paths = [df.path for df in diff_files]

    # Map files to graph nodes
    file_node_map = map_files_to_nodes(graph, file_paths)

    # Collect all changed node IDs
    changed_node_ids: set[str] = set()
    for fp, node_ids in file_node_map.items():
        changed_node_ids.update(node_ids)

    if not changed_node_ids:
        return ChangeReport(
            changed_files=diff_files,
            changed_nodes=[],
            covered_nodes=[],
            uncovered_nodes=[],
        )

    # Compute combined blast radius for all changed nodes
    all_impacted: dict[str, dict[str, Any]] = {}
    for node_id in changed_node_ids:
        if node_id not in graph.graph:
            continue
        try:
            blast = compute_blast_radius(graph, node_id)
        except ValueError:
            continue
        for item in blast.get("downstream", []):
            imp_id = item["node_id"]
            if imp_id not in all_impacted:
                all_impacted[imp_id] = item
        for item in blast.get("contract_impact", []):
            imp_id = item["node_id"]
            if imp_id not in all_impacted:
                all_impacted[imp_id] = item

    # Partition into covered / uncovered
    covered: list[str] = []
    uncovered: list[str] = []
    for imp_id in sorted(all_impacted.keys()):
        if imp_id in changed_node_ids:
            covered.append(imp_id)
        else:
            uncovered.append(imp_id)

    # Check contract violations: changed producer but unchanged consumers
    contract_violations: list[str] = []
    for nid in graph.graph.nodes:
        node_data = graph.graph.nodes[nid].get("node")
        if node_data is None or node_data.type != "contract":
            continue
        producer = node_data.metadata.get("producer", "")
        consumers = node_data.metadata.get("consumers", [])
        if producer in changed_node_ids:
            for consumer_id in consumers:
                if consumer_id not in changed_node_ids:
                    contract_violations.append(
                        f"Contract '{node_data.label}': producer '{producer}' "
                        f"changed but consumer '{consumer_id}' not updated"
                    )

    # Generate recommendations for uncovered nodes
    recommendations: list[str] = []
    for imp_id in uncovered:
        item = all_impacted[imp_id]
        severity = item.get("severity", "unknown")
        label = item.get("label", imp_id)
        node_type = item.get("type", "unknown")
        # Find the edge type from a changed node to this impacted node
        edge_info = ""
        for changed_id in changed_node_ids:
            edge_data = graph.graph.edges.get((changed_id, imp_id), {})
            edge_obj = edge_data.get("edge")
            if edge_obj:
                edge_info = f" (via {edge_obj.type} edge)"
                break
        if severity == "critical":
            recommendations.append(
                f"CRITICAL: '{label}' ({node_type}) is a contract consumer "
                f"that may need updating{edge_info}"
            )
        else:
            recommendations.append(
                f"Consider updating '{label}' ({node_type}), "
                f"severity: {severity}{edge_info}"
            )

    return ChangeReport(
        changed_files=diff_files,
        changed_nodes=sorted(changed_node_ids),
        covered_nodes=covered,
        uncovered_nodes=uncovered,
        contract_violations=contract_violations,
        recommendations=recommendations,
        total_blast_radius=len(all_impacted),
    )


# ---------------------------------------------------------------------------
# Test suggestion
# ---------------------------------------------------------------------------

_TEST_PATTERNS: dict[str, list[str]] = {
    ".py": ["test_{name}.py", "tests/test_{name}.py", "{name}_test.py"],
    ".go": ["{name}_test.go"],
    ".ts": ["{name}.test.ts", "{name}.spec.ts", "__tests__/{name}.test.ts"],
    ".tsx": ["{name}.test.tsx", "{name}.spec.tsx"],
    ".js": ["{name}.test.js", "{name}.spec.js", "__tests__/{name}.test.js"],
    ".jsx": ["{name}.test.jsx", "{name}.spec.jsx"],
    ".rs": ["tests/{name}.rs", "{name}_test.rs"],
    ".java": ["{name}Test.java", "test/{name}Test.java"],
    ".cs": ["{name}Tests.cs", "{name}Test.cs"],
    ".php": ["{name}Test.php", "tests/{name}Test.php"],
    ".rb": ["{name}_spec.rb", "spec/{name}_spec.rb", "test_{name}.rb"],
}


def suggest_tests(
    graph: ArchGraph,
    diff_files: list[DiffFile],
    max_suggestions: int = 20,
) -> list[TestSuggestion]:
    """Suggest test files that should be run to validate a change.

    Uses three complementary strategies:

    1. **Graph-based** (score 0.9): Test nodes that have import edges
       to/from any changed node.
    2. **Naming convention** (score 0.6): Test files whose names match
       common naming patterns for the changed source files.
    3. **Blast radius** (score 0.3): Test nodes that appear in the
       transitive dependency set of changed nodes.

    Results are deduplicated (keeping the highest score), sorted by score
    descending, and truncated to *max_suggestions*.

    Parameters
    ----------
    graph:
        The architecture graph.
    diff_files:
        Parsed diff files representing the change set.
    max_suggestions:
        Maximum number of suggestions to return.

    Returns
    -------
    list[TestSuggestion]
        Suggested test files, scored and ordered by relevance.
    """
    if not diff_files:
        return []

    file_paths = [df.path for df in diff_files]
    file_node_map = map_files_to_nodes(graph, file_paths)

    changed_node_ids: set[str] = set()
    for fp, node_ids in file_node_map.items():
        changed_node_ids.update(node_ids)

    # Collect all test nodes (nodes with source: test metadata)
    test_nodes: dict[str, Node] = {}
    for nid, attrs in graph.graph.nodes(data=True):
        node: Node | None = attrs.get("node")
        if node is None:
            continue
        if node.metadata.get("source") == "test":
            test_nodes[nid] = node

    # Also collect all node IDs mapped by their file_path for naming strategy
    file_path_to_node_ids: dict[str, list[str]] = {}
    for nid, attrs in graph.graph.nodes(data=True):
        node = attrs.get("node")
        if node is None or not node.file_path:
            continue
        fp = node.file_path
        if fp not in file_path_to_node_ids:
            file_path_to_node_ids[fp] = []
        file_path_to_node_ids[fp].append(nid)

    suggestions: dict[str, TestSuggestion] = {}  # keyed by file_path or node_id

    # --- Strategy 1: Graph-based (score 0.9) ---
    for changed_id in changed_node_ids:
        if changed_id not in graph.graph:
            continue
        # Check all neighbors (both directions)
        neighbors = set(graph.graph.successors(changed_id)) | set(
            graph.graph.predecessors(changed_id)
        )
        for neighbor_id in neighbors:
            if neighbor_id in test_nodes:
                test_node = test_nodes[neighbor_id]
                key = test_node.file_path or neighbor_id
                if key not in suggestions or suggestions[key].score < 0.9:
                    suggestions[key] = TestSuggestion(
                        file_path=test_node.file_path or neighbor_id,
                        score=0.9,
                        reason=f"Test imports/is imported by changed node '{changed_id}'",
                        strategy="graph",
                    )

    # --- Strategy 2: Naming convention (score 0.6) ---
    for fp in file_paths:
        basename = os.path.basename(fp)
        # Find the extension
        ext = ""
        for e in _TEST_PATTERNS:
            if basename.endswith(e):
                ext = e
                break
        if not ext:
            continue
        # Extract name without extension
        name = basename[: -len(ext)]
        patterns = _TEST_PATTERNS[ext]

        for pattern in patterns:
            test_filename = pattern.format(name=name)
            # Check if any node in the graph has a matching file_path
            for node_fp, node_ids in file_path_to_node_ids.items():
                if node_fp.endswith(test_filename) or os.path.basename(node_fp) == test_filename:
                    key = node_fp
                    if key not in suggestions or suggestions[key].score < 0.6:
                        suggestions[key] = TestSuggestion(
                            file_path=node_fp,
                            score=0.6,
                            reason=f"Naming convention: '{test_filename}' matches changed '{basename}'",
                            strategy="naming",
                        )

    # --- Strategy 3: Blast radius (score 0.3) ---
    for changed_id in changed_node_ids:
        if changed_id not in graph.graph:
            continue
        try:
            blast = compute_blast_radius(graph, changed_id)
        except ValueError:
            continue
        for item in blast.get("downstream", []):
            imp_id = item["node_id"]
            if imp_id in test_nodes:
                test_node = test_nodes[imp_id]
                key = test_node.file_path or imp_id
                if key not in suggestions or suggestions[key].score < 0.3:
                    suggestions[key] = TestSuggestion(
                        file_path=test_node.file_path or imp_id,
                        score=0.3,
                        reason=f"In blast radius of changed node '{changed_id}'",
                        strategy="blast_radius",
                    )

    # Annotate all suggestions with coverage_status based on test node metadata
    annotated: dict[str, TestSuggestion] = {}
    for key, suggestion in suggestions.items():
        cov_status = "unknown"
        for _nid, attrs in graph.graph.nodes(data=True):
            n: Node | None = attrs.get("node")
            if n is None:
                continue
            if n.file_path == suggestion.file_path or _nid == suggestion.file_path:
                cov = n.metadata.get("_test_coverage")
                if cov is None:
                    cov_status = "unknown"
                elif cov > 0.0:
                    cov_status = "covered"
                else:
                    cov_status = "uncovered"
                break
        annotated[key] = suggestion.model_copy(update={"coverage_status": cov_status})

    # Sort by score descending, truncate
    sorted_suggestions = sorted(
        annotated.values(), key=lambda s: (-s.score, s.file_path)
    )
    return sorted_suggestions[:max_suggestions]


# ---------------------------------------------------------------------------
# File coupling analysis
# ---------------------------------------------------------------------------


def file_coupling(
    graph: ArchGraph,
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> list[CouplingPair]:
    """Analyze file coupling from git co-change history.

    Mines the recent commit history to find files that frequently change
    together, then cross-references with the architecture graph to check
    whether an explicit edge exists between the co-changing files.

    Parameters
    ----------
    graph:
        The architecture graph (used for cross-referencing).
    project_path:
        Filesystem path to the git repository.
    file_path:
        If provided, only return pairs involving this file.
    depth:
        Number of recent commits to analyze.
    min_commits:
        Minimum co-change count for a pair to be included.
    min_coupling:
        Minimum coupling ratio (0.0 to 1.0) for inclusion.

    Returns
    -------
    list[CouplingPair]
        Co-changing file pairs sorted by coupling descending, limited to
        the top 20.  Returns an empty list for non-git directories.
    """
    if not is_git_repo(project_path):
        return []

    history = get_commit_file_history(project_path, depth)
    if not history:
        return []

    # Count individual file changes
    file_change_count: dict[str, int] = {}
    # Count co-changes for each pair
    co_change_count: dict[tuple[str, str], int] = {}

    for commit_files in history:
        unique_files = sorted(set(commit_files))
        for f in unique_files:
            file_change_count[f] = file_change_count.get(f, 0) + 1
        # Generate all pairs in this commit
        for i in range(len(unique_files)):
            for j in range(i + 1, len(unique_files)):
                pair = (unique_files[i], unique_files[j])
                co_change_count[pair] = co_change_count.get(pair, 0) + 1

    # Compute coupling and filter
    pairs: list[CouplingPair] = []
    for (fa, fb), co_count in co_change_count.items():
        if co_count < min_commits:
            continue
        count_a = file_change_count.get(fa, 0)
        count_b = file_change_count.get(fb, 0)
        coupling = co_count / max(count_a, count_b) if max(count_a, count_b) > 0 else 0.0
        if coupling < min_coupling:
            continue

        # Filter by file_path if specified
        if file_path is not None and fa != file_path and fb != file_path:
            continue

        # Cross-reference with graph
        file_node_map = map_files_to_nodes(graph, [fa, fb])
        nodes_a = file_node_map.get(fa, [])
        nodes_b = file_node_map.get(fb, [])

        in_graph = False
        edge_type = ""
        for na in nodes_a:
            for nb in nodes_b:
                edge_data = graph.graph.edges.get((na, nb), {})
                edge_obj = edge_data.get("edge")
                if edge_obj:
                    in_graph = True
                    edge_type = edge_obj.type
                    break
                # Check reverse direction too
                edge_data = graph.graph.edges.get((nb, na), {})
                edge_obj = edge_data.get("edge")
                if edge_obj:
                    in_graph = True
                    edge_type = edge_obj.type
                    break
            if in_graph:
                break

        pairs.append(
            CouplingPair(
                file_a=fa,
                file_b=fb,
                co_change_count=co_count,
                change_count_a=count_a,
                change_count_b=count_b,
                coupling=round(coupling, 4),
                in_graph=in_graph,
                edge_type=edge_type,
            )
        )

    # Sort by coupling descending, limit to top 20
    pairs.sort(key=lambda p: (-p.coupling, p.file_a, p.file_b))
    return pairs[:20]


# ---------------------------------------------------------------------------
# Dependency-aware task ordering
# ---------------------------------------------------------------------------


def order_tasks(graph: ArchGraph, tasks: list[dict]) -> dict:
    """Order tasks based on graph dependencies.

    Each task is a dict with ``name`` (str) and ``target_files`` (list[str]).

    Algorithm
    ---------
    1. Map each task's target files to module nodes in the graph.
    2. Build a directed task-dependency subgraph: task A must precede task B
       when a file touched by A is imported by a file touched by B (i.e. B's
       module has an ``imports`` edge pointing at A's module).
    3. Attempt a topological sort on the task dependency graph.  If a cycle is
       detected, fall back to the original order and surface cycle information.
    4. Group tasks at the same topological level into parallel groups.
    5. Detect same-file conflicts (multiple tasks targeting the same file).

    Parameters
    ----------
    graph:
        The loaded ``ArchGraph`` for the project.
    tasks:
        List of task dicts, each with ``"name"`` and ``"target_files"`` keys.

    Returns
    -------
    dict with keys:

    ``ordered_tasks``
        List of task dicts enriched with an ``"order"`` integer (0-based
        topological level).

    ``parallel_groups``
        List of lists of task indices that can run concurrently.  Tasks in the
        same group have no mutual dependency.

    ``conflict_zones``
        List of ``{"file": str, "tasks": [task_name, ...]}`` dicts for files
        touched by more than one task.

    ``dependency_edges``
        List of ``{"from": task_name, "to": task_name, "reason": str}`` dicts
        describing why one task must precede another.

    When cycles are detected a top-level ``"cycle"`` key is also present with a
    human-readable description.
    """
    if not tasks:
        return {
            "ordered_tasks": [],
            "parallel_groups": [],
            "conflict_zones": [],
            "dependency_edges": [],
        }

    n = len(tasks)

    # Step 1: Map each task's target files to graph node IDs
    task_node_map: list[list[str]] = []  # index -> list of node IDs
    for task in tasks:
        files = task.get("target_files", [])
        file_node_mapping = map_files_to_nodes(graph, files)
        node_ids: list[str] = []
        for nids in file_node_mapping.values():
            node_ids.extend(nids)
        task_node_map.append(node_ids)

    # Step 2: Detect conflict zones (multiple tasks share the same file)
    file_to_task_names: dict[str, list[str]] = {}
    for task, files in zip(tasks, [t.get("target_files", []) for t in tasks]):
        for fp in files:
            file_to_task_names.setdefault(fp, []).append(task["name"])

    conflict_zones = [
        {"file": fp, "tasks": task_names}
        for fp, task_names in file_to_task_names.items()
        if len(task_names) > 1
    ]

    # Step 3: Build task dependency graph
    from codegiraffe.schema import EdgeType  # local import to avoid circular deps
    from collections import defaultdict

    task_dep_graph: nx.DiGraph = nx.DiGraph()
    task_dep_graph.add_nodes_from(range(n))

    dependency_edges: list[dict] = []

    for j in range(n):
        for i in range(n):
            if i == j:
                continue
            nodes_i = set(task_node_map[i])
            nodes_j = set(task_node_map[j])
            if not nodes_i or not nodes_j:
                continue
            for nj in nodes_j:
                for ni in nodes_i:
                    edge_data = graph.graph.edges.get((nj, ni), {})
                    edge_obj = edge_data.get("edge")
                    if edge_obj is not None and edge_obj.type == EdgeType.IMPORTS:
                        if not task_dep_graph.has_edge(i, j):
                            task_dep_graph.add_edge(i, j)
                            dependency_edges.append({
                                "from": tasks[i]["name"],
                                "to": tasks[j]["name"],
                                "reason": (
                                    f"imports ({tasks[j]['name']} imports "
                                    f"from {tasks[i]['name']})"
                                ),
                            })

    # Step 4: Topological sort & level assignment
    cycle_info: str | None = None
    try:
        topo_order = list(nx.topological_sort(task_dep_graph))
    except nx.NetworkXUnfeasible:
        cycles = list(nx.simple_cycles(task_dep_graph))
        cycle_desc = "; ".join(
            " -> ".join(tasks[idx]["name"] for idx in c) for c in cycles
        )
        cycle_info = f"Circular dependency detected: {cycle_desc}"
        topo_order = list(range(n))

    level: dict[int, int] = {idx: 0 for idx in range(n)}
    for idx in topo_order:
        for pred in task_dep_graph.predecessors(idx):
            level[idx] = max(level[idx], level[pred] + 1)

    # Step 5: Build parallel groups
    level_to_indices: dict[int, list[int]] = defaultdict(list)
    for idx in topo_order:
        level_to_indices[level[idx]].append(idx)

    parallel_groups = [
        level_to_indices[lvl]
        for lvl in sorted(level_to_indices.keys())
    ]

    # Step 6: Assemble ordered_tasks
    ordered_tasks = []
    for idx in topo_order:
        task = tasks[idx]
        entry = {
            "name": task["name"],
            "target_files": task.get("target_files", []),
            "order": level[idx],
        }
        if cycle_info:
            entry["note"] = "cycle detected -- ordering may be approximate"
        ordered_tasks.append(entry)

    result: dict = {
        "ordered_tasks": ordered_tasks,
        "parallel_groups": parallel_groups,
        "conflict_zones": conflict_zones,
        "dependency_edges": dependency_edges,
    }
    if cycle_info:
        result["cycle"] = cycle_info
    return result
