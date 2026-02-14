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
        downstream.append({
            "node_id": desc_id,
            "label": desc_node.label,
            "type": desc_node.type,
            "distance": dist,
            "severity": _compute_severity(dist),
            "path": paths.get(desc_id, []),
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

    result: dict[str, Any] = {
        "target_node": target_info,
        "downstream": downstream,
        "total_impact_count": len(downstream) + len(contract_impact),
        "contract_impact": contract_impact,
        "cycles": relevant_cycles,
        "critical_paths": critical_paths,
    }
    if include_upstream:
        result["upstream"] = upstream

    return result


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

    # Group downstream by severity
    direct = [n for n in downstream if n["severity"] == "direct"]
    transitive = [n for n in downstream if n["severity"] == "transitive"]
    indirect = [n for n in downstream if n["severity"] == "indirect"]

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
