"""Query engine for the Code Giraffe architecture knowledge graph.

Provides functions for extracting relevant subgraphs, finding contextually
relevant nodes via keyword matching, and detecting drift between the graph
and the actual codebase.
"""

from __future__ import annotations

import re
import string
import subprocess
from typing import Any

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
    use_embeddings: bool = True,
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

    Returns an empty :class:`GraphData` when no node scores above zero.
    """
    # Try embedding-based scoring
    if use_embeddings and _embeddings_mod.is_available():
        return _context_for_task_embeddings(graph, task, max_nodes)

    # Fall back to keyword scoring (existing implementation)
    return _context_for_task_keywords(graph, task, max_nodes)


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
