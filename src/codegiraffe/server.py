"""MCP server entry point for Code Giraffe.

Exposes architecture knowledge graph tools via the FastMCP protocol,
allowing MCP clients to initialize, query, annotate, and synchronize
architectural graphs for Python projects.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as _url_quote

import networkx as nx
from mcp.server.fastmcp import FastMCP

from codegiraffe.coordination import CoordinationStore
from codegiraffe.federation import GraphFederation
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.query import (
    compute_blast_radius,
    compute_enhanced_blast_radius,
    context_for_task,
    detect_drift,
    file_coupling,
    generate_enhanced_impact_summary,
    generate_impact_summary,
    get_contracts,
    map_files_to_nodes,
    order_tasks,
    query_by_node,
    query_by_text,
    query_by_type,
    suggest_tests,
    validate_changes,
    validate_contracts,
)
from codegiraffe.diff_parser import parse_diff
from codegiraffe.git_utils import (
    get_changed_files,
    get_uncommitted_diff,
    is_git_repo,
    GitTimeoutError,
    NotAGitRepoError,
)
from codegiraffe.domains import (
    add_domain as _add_domain,
    infer_domains as _infer_domains,
    list_domains as _list_domains,
    remove_domain as _remove_domain,
)
from codegiraffe.migration import generate_migration_plan
from codegiraffe.patterns import extract_patterns as _extract_patterns
from codegiraffe.scanner import scan_project
from codegiraffe.storage import JSONStorage, StorageBackend
from codegiraffe.versioning import VersionStore

# ---------------------------------------------------------------------------
# Server and shared state
# ---------------------------------------------------------------------------

mcp = FastMCP("codegiraffe")

_storage: StorageBackend = JSONStorage()
_graph: ArchGraph | None = None
_coordinator = CoordinationStore()
_version_store = VersionStore()
_federation = GraphFederation()
# Reentrant lock protecting _graph and _storage from concurrent read/write races.
# RLock is used so that _ensure_graph (which acquires the lock) can be called
# safely from within other locked sections in write tools.
_graph_lock = threading.RLock()
# Set of project paths that have been successfully initialized via codegiraffe_init.
# The dashboard /api/init endpoint uses this allowlist to prevent unauthorized
# path traversal: only pre-approved paths may trigger a rescan via the dashboard.
_initialized_project_paths: set[str] = set()

# ---------------------------------------------------------------------------
# Parameter bound constants (US5)
# ---------------------------------------------------------------------------

MAX_QUERY_DEPTH = 20
MAX_COUPLING_DEPTH = 500
MAX_BLAST_DEPTH = 20


def _get_storage(backend: str = "json"):
    """Get a storage backend by name."""
    if backend == "sqlite":
        from codegiraffe.sqlite_storage import SQLiteStorage

        return SQLiteStorage()
    elif backend == "neo4j":
        from codegiraffe.neo4j_storage import Neo4jStorage

        return Neo4jStorage()
    return JSONStorage()


def _ensure_graph(project_path: str) -> ArchGraph:
    """Load the graph from storage, raising if no graph has been initialized.

    On the first call for a given project the graph is loaded from disk and
    cached in the module-level ``_graph`` variable.  Subsequent calls reuse
    the cached instance unless the project path changes.

    Thread-safe: acquires ``_graph_lock`` (RLock) for the entire body so that
    concurrent callers see a consistent ``_graph`` reference.
    """
    global _graph  # noqa: PLW0603

    with _graph_lock:
        if _graph is not None:
            data = _graph.to_data()
            if data.project_path == project_path:
                return _graph

        stored = _storage.load(project_path)
        if stored is None:
            raise RuntimeError(
                f"No architecture graph found for '{project_path}'. "
                "Run codegiraffe_init first."
            )

        _graph = ArchGraph(stored)
        return _graph


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_init(
    project_path: str,
    rescan: bool = False,
    backend: str = "json",
    scanner_mode: str = "hybrid",
    include_tests: bool = False,
) -> str:
    """Initialize or re-scan the architecture knowledge graph for a project.

    Scans the project directory for architectural patterns (endpoints,
    database tables, workers, env vars, external APIs, services) and builds
    a graph. When *rescan* is True and an existing graph is found, manually
    added annotations are preserved.

    Use *backend* to select the storage backend: ``"json"`` (default),
    ``"sqlite"`` for a SQLite database, or ``"neo4j"`` for Neo4j.

    Use *scanner_mode* to choose the scanning strategy: ``"hybrid"`` (default)
    for both regex and AST recognizers running together (falls back to regex if
    tree-sitter is unavailable), ``"regex"`` for regex-only pattern matching,
    or ``"ast"`` for tree-sitter AST-based scanning (requires tree-sitter
    packages).

    Returns a summary of the initialized graph.
    """
    global _graph, _storage, _initialized_project_paths  # noqa: PLW0603

    try:
        new_storage = _get_storage(backend)

        # Preserve manual annotations when rescanning (read outside lock — storage
        # load is idempotent and safe to do before acquiring the write lock).
        old_data: GraphData | None = None
        if rescan:
            old_data = new_storage.load(project_path)

        # Select scanner registry based on mode
        registry = None
        if scanner_mode == "ast":
            from codegiraffe.ast_scanner import get_ast_registry

            registry = get_ast_registry()
        elif scanner_mode == "hybrid":
            try:
                from codegiraffe.ast_scanner import get_hybrid_registry
                registry = get_hybrid_registry()
            except ImportError:
                registry = None  # falls back to default regex registry

        # Scan the project (slow — do NOT hold the lock during scanning)
        result = scan_project(project_path, registry=registry, include_tests=include_tests)

        # Build graph data from scan results
        nodes: dict[str, Node] = {node.id: node for node in result.nodes}
        edges = result.edges

        data = GraphData(
            nodes=nodes,
            edges=edges,
            project_path=project_path,
            last_scan=datetime.now(timezone.utc).isoformat(),
        )

        graph = ArchGraph(data)

        # Merge back manual annotations from previous graph
        if rescan and old_data is not None:
            graph.merge_manual_annotations(old_data)

        # Compute and attach layout before persisting
        data = graph.to_data()
        try:
            from codegiraffe.layout import compute_layout
            data.layout = compute_layout(data)
        except Exception:
            pass  # never fail init if layout computation errors

        # Atomically persist and replace the cached graph under the lock.
        with _graph_lock:
            new_storage.save(project_path, data)
            _storage = new_storage
            _graph = graph

        # Auto-version after init/rescan (outside lock — version store has its own safety)
        prev_data = old_data if old_data is not None else GraphData()
        _version_store.add_version(
            project_path, prev_data, graph.to_data(),
            "Rescan" if rescan else "Init",
        )

        final_data = graph.to_data()

        # Register path in the allowlist so the dashboard /api/init endpoint
        # may rescan it without triggering a 403 path-traversal guard.
        # Normalize via resolve() so symlinks and relative components don't bypass the check.
        _initialized_project_paths.add(str(Path(project_path).resolve()))

        # Lazily start the background dashboard server after a successful init.
        try:
            from codegiraffe.dashboard_server import get_or_start_server
            get_or_start_server(_ensure_graph, _storage)
        except Exception:
            pass  # Dashboard is optional; never let it break init.

        return (
            f"Initialized graph with {len(final_data.nodes)} nodes "
            f"and {len(final_data.edges)} edges"
        )
    except Exception as exc:
        return f"Error initializing graph: {exc}"


@mcp.tool()
def codegiraffe_query(
    project_path: str,
    node_id: str | None = None,
    node_type: str | None = None,
    query: str | None = None,
    depth: int = 2,
    max_results: int = 100,
) -> str:
    """Query the architecture graph by node ID, node type, or free-text search.

    Provide *node_id* to extract a subgraph centered on that node (up to
    *depth* hops), or *node_type* to retrieve all nodes of that type with
    their direct edges.

    Use *query* for case-insensitive substring search across node IDs, labels,
    and metadata values (e.g. class_name, kind).  You may combine *query* with
    *node_type* to search within a specific type.  Results are capped at 50
    nodes.

    *node_id* takes precedence over *query* which takes precedence over
    *node_type* alone.  Returns the subgraph as formatted JSON.

    Use *max_results* (default 100) to cap the number of nodes returned when
    querying by node_type or query.  A truncation notice is prepended to the
    output when results are capped.  Set to 0 to disable the cap (caution:
    large graphs may produce very large output).
    """
    try:
        # Clamp depth to the configured maximum to prevent excessive traversal.
        depth = min(depth, MAX_QUERY_DEPTH)

        graph = _ensure_graph(project_path)

        if node_id is not None:
            subgraph = query_by_node(graph, node_id, depth)
        elif query is not None:
            subgraph = query_by_text(graph, query, node_type=node_type)
        elif node_type is not None:
            subgraph = query_by_type(graph, node_type)
        else:
            return "Error: provide either node_id, node_type, or query"

        total_nodes = len(subgraph.nodes)
        truncated = False
        if max_results > 0 and total_nodes > max_results:
            # Trim to max_results nodes and retain only edges between kept nodes
            kept_ids = set(list(subgraph.nodes.keys())[:max_results])
            trimmed_nodes = {nid: n for nid, n in subgraph.nodes.items() if nid in kept_ids}
            trimmed_edges = [
                e for e in subgraph.edges
                if e.source in kept_ids and e.target in kept_ids
            ]
            subgraph.nodes = trimmed_nodes
            subgraph.edges = trimmed_edges
            truncated = True

        result_json = subgraph.model_dump_json(indent=2)
        if truncated:
            notice = (
                f"// Showing {max_results} of {total_nodes} nodes. "
                "Use query/node_type parameters to filter.\n"
            )
            return notice + result_json
        return result_json
    except Exception as exc:
        return f"Error querying graph: {exc}"


@mcp.tool()
def codegiraffe_add_relation(
    project_path: str,
    source: str,
    target: str,
    relation_type: str,
    source_type: str = "service",
    target_type: str = "service",
    metadata: str = "{}",
) -> str:
    """Add a manual relationship (edge) between two architectural nodes.

    If *source* or *target* nodes do not exist they are auto-created with
    the given types. The edge is marked as ``manual=True`` so it survives
    automated re-scans. *metadata* is a JSON string of extra key/value pairs.
    """
    try:
        # Parse metadata JSON before acquiring the lock (pure CPU, no shared state)
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return "Error: metadata is not valid JSON"

        with _graph_lock:
            graph = _ensure_graph(project_path)

            # Auto-create source node if missing
            if source not in graph.graph:
                graph.add_node(
                    Node(
                        id=source,
                        type=source_type,
                        label=source,
                        manual=True,
                    )
                )

            # Auto-create target node if missing
            if target not in graph.graph:
                graph.add_node(
                    Node(
                        id=target,
                        type=target_type,
                        label=target,
                        manual=True,
                    )
                )

            # Add the manual edge
            graph.add_edge(
                Edge(
                    source=source,
                    target=target,
                    type=relation_type,
                    metadata=meta,
                    manual=True,
                )
            )

            # Persist
            _storage.save(project_path, graph.to_data())

        return (
            f"Added manual relation: {source} --[{relation_type}]--> {target}"
        )
    except Exception as exc:
        return f"Error adding relation: {exc}"


@mcp.tool()
def codegiraffe_context_for(
    project_path: str,
    task: str,
    max_nodes: int = 20,
    use_embeddings: bool = True,
    include_impact: bool = False,
    include_changes: bool = False,
    token_budget: int = 0,
    detail_level: str = "standard",
    min_confidence: float = 0.0,
) -> str:
    """Get the most relevant subgraph for a natural-language task description.

    When sentence-transformers is installed and *use_embeddings* is True, uses
    embedding-based semantic similarity for scoring.  Otherwise falls back to
    keyword overlap scoring.  Returns the top-matching nodes with their
    immediate neighbors, capped at *max_nodes*.

    When *include_impact* is True, each node in the result is augmented with
    ``_blast_radius_count`` and ``_risk_score`` metadata fields.

    When *include_changes* is True, nodes affected by uncommitted git changes
    receive a score boost and ``_recently_changed`` / ``_in_change_blast_radius``
    metadata annotations.

    When *token_budget* > 0, the result is trimmed so that the total estimated
    token cost stays within the budget (highest-relevance nodes kept first).
    When both *token_budget* and *max_nodes* are set, the more restrictive
    constraint wins.

    *detail_level* controls how much metadata each node carries:
    - ``"summary"``  — id, type, label only (smallest token footprint)
    - ``"standard"`` — id, type, label + metadata (default)
    - ``"detailed"`` — full node data including file_path

    When *min_confidence* > 0, edges with confidence below this threshold are
    excluded from the result.  Useful for filtering out low-certainty inferred
    edges (e.g. contract inference at 0.5) and retaining only stronger signals.
    Confidence levels: contains=1.0, import/AST=0.9, call/inheritance=0.8,
    interface satisfaction=0.7, contract inference=0.5.

    The response includes ``_token_estimate`` showing total estimated tokens
    and ``_retrieval_strategy`` showing the classified task intent used to
    steer retrieval (one of: ``create``, ``debug``, ``refactor``, ``delete``,
    ``test``, ``modify``).

    Useful for scoping what parts of the architecture are relevant before
    making changes.
    """
    try:
        graph = _ensure_graph(project_path)
        subgraph = context_for_task(
            graph,
            task,
            max_nodes,
            use_embeddings=use_embeddings,
            token_budget=token_budget,
            detail_level=detail_level,
            min_confidence=min_confidence,
        )

        if include_impact:
            total_nodes = len(graph.graph)
            degree = nx.degree_centrality(graph.graph) if total_nodes > 0 else {}
            betweenness = graph.get_betweenness_centrality() if total_nodes > 0 else {}
            for nid, node in subgraph.nodes.items():
                desc_count = len(graph.get_all_descendants(nid))
                risk = (
                    degree.get(nid, 0.0) * 0.4
                    + betweenness.get(nid, 0.0) * 0.4
                    + (desc_count / total_nodes * 0.2 if total_nodes > 0 else 0.0)
                )
                node.metadata["_blast_radius_count"] = desc_count
                node.metadata["_risk_score"] = round(risk, 4)

        if include_changes:
            try:
                changed_files = get_changed_files(project_path)
                if changed_files:
                    file_node_map = map_files_to_nodes(graph, changed_files)
                    changed_node_ids: set[str] = set()
                    for node_ids in file_node_map.values():
                        changed_node_ids.update(node_ids)

                    # Compute blast radius for changed nodes
                    blast_node_ids: set[str] = set()
                    for nid in changed_node_ids:
                        if nid in graph.graph:
                            descendants = graph.get_all_descendants(nid)
                            blast_node_ids.update(descendants)
                    # Remove the changed nodes themselves from blast set
                    blast_node_ids -= changed_node_ids

                    # Apply score boosts and metadata annotations
                    for nid, node in subgraph.nodes.items():
                        if nid in changed_node_ids:
                            current_score = node.metadata.get("_relevance_score", 0.0)
                            node.metadata["_relevance_score"] = round(
                                current_score + 0.3, 4
                            )
                            node.metadata["_recently_changed"] = True
                        elif nid in blast_node_ids:
                            current_score = node.metadata.get("_relevance_score", 0.0)
                            node.metadata["_relevance_score"] = round(
                                current_score + 0.15, 4
                            )
                            node.metadata["_in_change_blast_radius"] = True
            except Exception:
                # Silent fallback — don't break existing behavior
                pass

        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error computing context: {exc}"


@mcp.tool()
def codegiraffe_detect_drift(project_path: str, scanner_mode: str = "hybrid") -> str:
    """Detect drift between the architecture graph and the actual codebase.

    Re-scans the project and compares the results against the stored graph.
    Reports nodes that exist in the graph but not in code, nodes found in
    code but missing from the graph, and potential renames.

    Parameters
    ----------
    project_path:
        Filesystem path to the project root.
    scanner_mode:
        Scanner registry to use: ``"hybrid"`` (default), ``"ast"``, or
        ``"regex"``.  Should match the mode used when the graph was built
        with ``codegiraffe_init`` so that AST-discovered nodes are not
        falsely reported as drift.

    Returns a JSON array of drift records.
    """
    try:
        graph = _ensure_graph(project_path)
        drifts = detect_drift(graph, project_path, scanner_mode=scanner_mode)
        return json.dumps(drifts, indent=2)
    except Exception as exc:
        return f"Error detecting drift: {exc}"


@mcp.tool()
def codegiraffe_hotspots(
    project_path: str, top_n: int = 10, metrics: str = "degree"
) -> str:
    """Find the most connected nodes (architectural hotspots) in the graph.

    Ranks nodes by degree centrality -- highly connected nodes are likely
    architectural hotspots that deserve extra attention during changes.

    Use *metrics* to select the ranking strategy:
    - ``"degree"`` (default): rank by degree centrality
    - ``"betweenness"``: rank by betweenness centrality (bottleneck nodes)
    - ``"combined"``: rank by 0.5*degree + 0.5*betweenness

    Returns a JSON array of {node_id, label, type, score} objects.
    """
    try:
        graph = _ensure_graph(project_path)

        if metrics == "betweenness":
            betweenness = graph.get_betweenness_centrality()
            scored_pairs = sorted(
                betweenness.items(), key=lambda x: x[1], reverse=True
            )[:top_n]
            result = []
            for nid, score in scored_pairs:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data is None:
                    continue
                result.append({
                    "node_id": nid,
                    "label": node_data.label,
                    "type": node_data.type,
                    "score": round(score, 4),
                })
            return json.dumps(result, indent=2)

        elif metrics == "combined":
            degree = nx.degree_centrality(graph.graph)
            betweenness = graph.get_betweenness_centrality()
            combined = {
                nid: degree.get(nid, 0.0) * 0.5 + betweenness.get(nid, 0.0) * 0.5
                for nid in graph.graph.nodes
            }
            scored_pairs = sorted(
                combined.items(), key=lambda x: x[1], reverse=True
            )[:top_n]
            result = []
            for nid, score in scored_pairs:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data is None:
                    continue
                result.append({
                    "node_id": nid,
                    "label": node_data.label,
                    "type": node_data.type,
                    "score": round(score, 4),
                })
            return json.dumps(result, indent=2)

        else:
            # Default: degree centrality (original behavior)
            hotspots = graph.get_hotspots(top_n)
            result = [
                {
                    "node_id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "score": round(score, 4),
                }
                for node, score in hotspots
            ]
            return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error computing hotspots: {exc}"


# ---------------------------------------------------------------------------
# Actionable intelligence tools (v0.7.0)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_blast_radius(
    project_path: str,
    node_id: str | None = None,
    query: str | None = None,
    include_upstream: bool = False,
    max_depth: int | None = None,
) -> dict:
    """Analyze the blast radius of changing a specific node.

    Shows what breaks if you change this node -- interface contracts, sibling
    implementations, interface consumers, cross-repo consumers, data layer
    dependencies, downstream dependencies ranked by severity (direct,
    transitive, indirect), upstream dependencies, circular dependencies, and
    hotspots in the impact zone.

    Provide *node_id* for an exact lookup, or *query* to find a matching node.
    When *query* is provided two strategies are tried and the best result is
    selected:

    - **Substring match** (good for partial class/symbol names)
    - **Semantic match** via context_for_task (good for natural-language phrases
      such as "SSH password changer" or "unix account changer")

    The best candidate is chosen by preferring exact label matches first, then
    high-relevance semantic results for service/module/table nodes.  All other
    matches are listed so you can refine with a more specific query or node_id.

    The *include_upstream* parameter is accepted for backwards compatibility
    but is now a no-op -- upstream is always included in the report.

    Returns structured impact data as a dict.
    """
    try:
        # Clamp max_depth to the configured maximum to prevent excessive traversal.
        if max_depth is None:
            max_depth = MAX_BLAST_DEPTH
        else:
            max_depth = min(max_depth, MAX_BLAST_DEPTH)

        graph = _ensure_graph(project_path)

        if node_id is not None:
            target_id = node_id
            other_matches: list[str] = []
        elif query is not None:
            # Strategy A: substring / label match
            text_matches = query_by_text(graph, query)
            text_ids = list(text_matches.nodes.keys())

            # Strategy B: semantic match via context_for_task
            context_matches = context_for_task(graph, query, max_nodes=10, use_embeddings=True)
            context_ids = sorted(
                context_matches.nodes.keys(),
                key=lambda nid: context_matches.nodes[nid].metadata.get("_relevance_score", 0),
                reverse=True,
            )

            preferred_types = {"service", "module", "database_table", "endpoint"}

            target_id = None

            # Prefer an exact label match from the substring strategy
            for nid in text_ids:
                node = text_matches.nodes[nid]
                if node.label.lower() == query.lower():
                    target_id = nid
                    break

            if target_id is None:
                # Use semantic results, preferring architecturally meaningful node types
                for nid in context_ids:
                    node = context_matches.nodes[nid]
                    if node.type in preferred_types:
                        target_id = nid
                        break
                if target_id is None and context_ids:
                    target_id = context_ids[0]

            # Fall back to the best substring match if semantic returned nothing
            if target_id is None and text_ids:
                target_id = text_ids[0]

            if target_id is None:
                return {"error": f"No nodes found matching query '{query}'."}

            # Collect other candidates from both strategies (deduplicated)
            all_ids = list(dict.fromkeys(text_ids + context_ids))
            other_matches = [nid for nid in all_ids if nid != target_id][:50]
        else:
            return {"error": "provide either node_id or query"}

        blast = compute_enhanced_blast_radius(
            graph, target_id, max_depth=max_depth
        )

        # Compute total affected nodes (unique across all sections)
        all_impacted: set[str] = set()
        for section_key in ("siblings", "interface_consumers", "cross_repo_consumers", "data_layer", "downstream", "upstream"):
            for item in blast.get(section_key, []):
                all_impacted.add(item["node_id"])
        total_affected = len(all_impacted)

        # Classify downstream by severity
        downstream = blast.get("downstream", [])
        direct_impact = [n for n in downstream if n["severity"] in ("direct", "uncertain_direct")]
        transitive_impact = [n for n in downstream if n["severity"] in ("transitive", "uncertain_transitive")]

        result: dict = {
            "target": blast["target_node"],
            "total_affected": total_affected,
            "interfaces": blast.get("interfaces", []),
            "siblings": blast.get("siblings", []),
            "interface_consumers": blast.get("interface_consumers", []),
            "cross_repo_consumers": blast.get("cross_repo_consumers", []),
            "data_layer": blast.get("data_layer", []),
            "direct_impact": direct_impact,
            "transitive_impact": transitive_impact,
            "downstream": downstream,
            "upstream": blast.get("upstream", []),
            "cycles": blast.get("cycles", []),
            "critical_paths": blast.get("critical_paths", []),
            "contract_impact": blast.get("contract_impact", []),
        }

        if other_matches:
            result["other_matches"] = other_matches

        return result
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"Error computing blast radius: {exc}"}


@mcp.tool()
def codegiraffe_risk_assessment(
    project_path: str,
    node_ids: list[str] | None = None,
) -> dict:
    """Assess architectural risk for specific nodes or the entire graph.

    Risk score = (degree_centrality * 0.4) + (betweenness_centrality * 0.4)
                 + (descendant_count / total_nodes * 0.2)

    If node_ids provided: assess those nodes. If None: top-10 riskiest nodes.
    Returns structured risk data ranked by risk score.
    """
    try:
        graph = _ensure_graph(project_path)
        total_nodes = len(graph.graph)
        if total_nodes == 0:
            return {"error": "Graph is empty -- no nodes to assess.", "nodes": [], "total_graph_nodes": 0}

        degree = nx.degree_centrality(graph.graph)
        betweenness = graph.get_betweenness_centrality()

        target_ids = node_ids if node_ids is not None else list(graph.graph.nodes)

        scored: list[dict] = []
        for nid in target_ids:
            if nid not in graph.graph:
                continue
            node_data = graph.graph.nodes[nid].get("node")
            if node_data is None:
                continue
            desc_count = len(graph.get_all_descendants(nid))
            risk = (
                degree.get(nid, 0.0) * 0.4
                + betweenness.get(nid, 0.0) * 0.4
                + (desc_count / total_nodes) * 0.2
            )
            scored.append({
                "node_id": nid,
                "label": node_data.label,
                "type": node_data.type,
                "risk_score": round(risk, 4),
                "degree_centrality": round(degree.get(nid, 0.0), 4),
                "betweenness_centrality": round(betweenness.get(nid, 0.0), 4),
                "blast_radius_count": desc_count,
                "file_path": node_data.file_path,
                "risk_explanation": _risk_explanation({
                    "degree_centrality": round(degree.get(nid, 0.0), 4),
                    "betweenness_centrality": round(betweenness.get(nid, 0.0), 4),
                    "blast_radius_count": desc_count,
                }),
            })

        scored.sort(key=lambda x: x["risk_score"], reverse=True)
        if node_ids is None:
            scored = scored[:10]

        return {
            "total_graph_nodes": total_nodes,
            "nodes_assessed": len(scored),
            "nodes": scored,
        }
    except Exception as exc:
        return {"error": f"Error computing risk assessment: {exc}", "nodes": [], "total_graph_nodes": 0}


@mcp.tool()
def codegiraffe_cycles(project_path: str, max_cycles: int = 20) -> str:
    """Detect circular dependencies in the architecture graph.

    Returns markdown-formatted list of cycles with path, edge types,
    severity (shorter cycles are more severe), and files involved.
    """
    try:
        graph = _ensure_graph(project_path)
        cycles = graph.detect_cycles(max_cycles=max_cycles)
        if not cycles:
            return "No circular dependencies detected."
        lines = ["## Circular Dependencies", ""]
        lines.append(f"**{len(cycles)} cycle(s) detected**")
        lines.append("")
        for i, cycle in enumerate(cycles, 1):
            display_path = cycle + [cycle[0]]
            path_str = " -> ".join(display_path)
            severity = (
                "high" if len(cycle) <= 2
                else "medium" if len(cycle) <= 4
                else "low"
            )
            lines.append(
                f"### Cycle {i} (length {len(cycle)}, severity: {severity})"
            )
            lines.append("```")
            lines.append(path_str)
            lines.append("```")
            edge_types: list[str] = []
            for j in range(len(cycle)):
                src = cycle[j]
                tgt = cycle[(j + 1) % len(cycle)]
                # MultiDiGraph: get_edge_data returns {key: data_dict}; pick first edge found
                all_edges = graph.graph.get_edge_data(src, tgt) or {}
                edge_obj = next(
                    (d.get("edge") for d in all_edges.values() if d.get("edge") is not None),
                    None,
                )
                if edge_obj:
                    edge_types.append(f"{src} --[{edge_obj.type}]--> {tgt}")
            if edge_types:
                lines.append("**Edges:**")
                for et in edge_types:
                    lines.append(f"- {et}")
            files: list[str] = []
            for nid in cycle:
                node_data = graph.graph.nodes[nid].get("node")
                if node_data and node_data.file_path:
                    files.append(f"{nid}: {node_data.file_path}")
            if files:
                lines.append("**Files:**")
                for f in files:
                    lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error detecting cycles: {exc}"


# ---------------------------------------------------------------------------
# Contract tools
# ---------------------------------------------------------------------------

VALID_CONTRACT_TYPES = {"api", "event", "data", "config"}


@mcp.tool()
def codegiraffe_contracts(
    project_path: str,
    contract_type: str | None = None,
    status: str | None = None,
    node_id: str | None = None,
) -> str:
    """List all contracts in the architecture graph.

    Contracts represent agreements between components (APIs, events, data
    schemas, config). Optionally filter by contract_type, status, or a
    specific producer/consumer node_id.
    """
    try:
        graph = _ensure_graph(project_path)
        contracts = get_contracts(
            graph,
            contract_type=contract_type,
            status=status,
            node_id=node_id,
        )
        if not contracts:
            return (
                "No contracts found. Use `codegiraffe_add_contract` to register "
                "a contract between components."
            )
        lines = ["## Contracts", ""]
        lines.append(f"**{len(contracts)} contract(s) found**")
        lines.append("")
        for c in contracts:
            lines.append(f"### {c['label']}")
            lines.append(f"- **Type:** {c['contract_type']}")
            lines.append(f"- **Status:** {c['status']}")
            if c.get("version"):
                lines.append(f"- **Version:** {c['version']}")
            prod = c["producer"]
            lines.append(
                f"- **Producer:** {prod['label']}"
                + (f" ({prod.get('type', '')})" if prod.get("type") else "")
            )
            if c["consumers"]:
                lines.append("- **Consumers:**")
                for consumer in c["consumers"]:
                    lines.append(
                        f"  - {consumer['label']}"
                        + (f" ({consumer.get('type', '')})" if consumer.get("type") else "")
                    )
            else:
                lines.append("- **Consumers:** none")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing contracts: {exc}"


@mcp.tool()
def codegiraffe_validate_contracts(project_path: str) -> str:
    """Validate all contracts in the architecture graph.

    Checks whether producer and consumer nodes referenced by each contract
    still exist in the graph. Reports valid, broken, orphaned, and
    deprecated-with-active-consumers contracts.
    """
    try:
        graph = _ensure_graph(project_path)
        result = validate_contracts(graph)
        total = result["total_contracts"]
        if total == 0:
            return (
                "No contracts found to validate. Use `codegiraffe_add_contract` "
                "to register contracts first."
            )
        lines = ["## Contract Validation Report", ""]
        lines.append(f"**Total contracts:** {total}")
        lines.append("")

        if result["valid"]:
            lines.append(f"### Valid ({len(result['valid'])})")
            lines.append("")
            for c in result["valid"]:
                lines.append(f"- **{c['label']}** ({c['contract_type']})")
            lines.append("")

        if result["broken"]:
            lines.append(f"### Broken -- Producer Missing ({len(result['broken'])})")
            lines.append("")
            for c in result["broken"]:
                lines.append(
                    f"- **{c['label']}** -- producer `{c['producer']}` not in graph"
                )
            lines.append("")

        if result["orphaned"]:
            lines.append(f"### Orphaned -- All Consumers Missing ({len(result['orphaned'])})")
            lines.append("")
            for c in result["orphaned"]:
                lines.append(
                    f"- **{c['label']}** -- consumers {c['consumers']} not in graph"
                )
            lines.append("")

        if result["deprecated_with_consumers"]:
            lines.append(
                f"### Deprecated With Active Consumers "
                f"({len(result['deprecated_with_consumers'])})"
            )
            lines.append("")
            for c in result["deprecated_with_consumers"]:
                lines.append(
                    f"- **{c['label']}** -- deprecated but still consumed by "
                    f"{c['consumers_existing']}"
                )
            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error validating contracts: {exc}"


@mcp.tool()
def codegiraffe_add_contract(
    project_path: str,
    name: str,
    contract_type: str,
    producer: str,
    consumers: str,
    version: str = "",
    metadata: str = "{}",
) -> str:
    """Add a contract to the architecture graph.

    A contract represents an agreement between a producer and one or more
    consumers (e.g. an API contract, event schema, data format, config).

    *consumers* is a comma-separated string of node IDs.
    *contract_type* must be one of: api, event, data, config.
    *metadata* is a JSON string of extra key/value pairs.
    """
    try:
        if contract_type not in VALID_CONTRACT_TYPES:
            return (
                f"Error: invalid contract_type '{contract_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_CONTRACT_TYPES))}"
            )

        # Parse metadata JSON before acquiring lock (pure CPU, no shared state)
        try:
            extra_meta = json.loads(metadata)
        except json.JSONDecodeError:
            return "Error: metadata is not valid JSON"

        consumer_list = [c.strip() for c in consumers.split(",") if c.strip()]
        contract_id = f"contract:{name}"

        # Build contract metadata
        contract_meta: dict = {
            "contract_type": contract_type,
            "producer": producer,
            "consumers": consumer_list,
            "version": version,
            "status": "active",
            **extra_meta,
        }

        warnings: list[str] = []

        with _graph_lock:
            graph = _ensure_graph(project_path)

            # Create contract node
            graph.add_node(
                Node(
                    id=contract_id,
                    type="contract",
                    label=name,
                    metadata=contract_meta,
                    manual=True,
                )
            )

            # Collect warnings for missing nodes

            # Create produces edge: producer -> contract
            if producer not in graph.graph:
                warnings.append(f"Warning: producer '{producer}' not found in graph")
            graph.add_edge(
                Edge(
                    source=producer,
                    target=contract_id,
                    type="produces",
                    manual=True,
                )
            )

            # Create consumes_contract edges: consumer -> contract
            for cid in consumer_list:
                if cid not in graph.graph:
                    warnings.append(f"Warning: consumer '{cid}' not found in graph")
                graph.add_edge(
                    Edge(
                        source=cid,
                        target=contract_id,
                        type="consumes_contract",
                        manual=True,
                    )
                )

            # Persist
            _storage.save(project_path, graph.to_data())

        result_lines = [
            f"Added contract '{name}' ({contract_type}): "
            f"{producer} --[produces]--> {contract_id}"
        ]
        for cid in consumer_list:
            result_lines.append(
                f"  {cid} --[consumes_contract]--> {contract_id}"
            )
        if warnings:
            result_lines.append("")
            result_lines.extend(warnings)

        return "\n".join(result_lines)
    except Exception as exc:
        return f"Error adding contract: {exc}"


# ---------------------------------------------------------------------------
# Ownership and annotation tools (v0.12.0)
# ---------------------------------------------------------------------------

_VALID_STABILITY_VALUES = {"stable", "experimental", "deprecated", "legacy"}


@mcp.tool()
def codegiraffe_annotate(
    project_path: str,
    node_id: str,
    owner: str | None = None,
    stability: str | None = None,
    notes: str | None = None,
) -> str:
    """Annotate a graph node with ownership and stability information.

    Sets one or more of the following metadata fields on the target node:

    - *owner*: Team or person responsible for this component (e.g. ``"@auth-team"``).
    - *stability*: Stability classification — one of ``"stable"``,
      ``"experimental"``, ``"deprecated"``, or ``"legacy"``.
    - *notes*: Free-form text notes about this component.

    Annotations are preserved across rescans and persist in graph storage.
    At least one of *owner*, *stability*, or *notes* must be provided.

    Parameters
    ----------
    project_path:
        Root directory of the project.
    node_id:
        ID of the node to annotate.
    owner:
        Team or individual owner string (e.g. ``"@auth-team"``).
    stability:
        Stability level: ``"stable"``, ``"experimental"``, ``"deprecated"``, or ``"legacy"``.
    notes:
        Free-form notes about this node.
    """
    try:
        if stability is not None and stability not in _VALID_STABILITY_VALUES:
            return (
                f"Error: invalid stability '{stability}'. "
                f"Must be one of: {', '.join(sorted(_VALID_STABILITY_VALUES))}"
            )

        with _graph_lock:
            graph = _ensure_graph(project_path)

            if node_id not in graph.graph:
                return f"Error: node '{node_id}' not found in graph."

            node = graph.graph.nodes[node_id].get("node")
            if node is None:
                return f"Error: node '{node_id}' has no data."

            # Apply annotations — only update fields that were provided
            if owner is not None:
                node.metadata["owner"] = owner
            if stability is not None:
                node.metadata["stability"] = stability
            if notes is not None:
                node.metadata["notes"] = notes

            # Persist updated graph
            _storage.save(project_path, graph.to_data())

        updated_fields = [
            f
            for f, v in [("owner", owner), ("stability", stability), ("notes", notes)]
            if v is not None
        ]
        if not updated_fields:
            return f"No fields provided to annotate on '{node_id}'."

        return (
            f"Annotated node '{node_id}' with: {', '.join(updated_fields)}"
        )
    except Exception as exc:
        return f"Error annotating node: {exc}"


# ---------------------------------------------------------------------------
# Domain model abstraction (v0.13.0 / US11, split into 4 tools in v0.16.0)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_list_domains(project_path: str) -> str:
    """List all business domain groupings defined in the architecture graph.

    Shows all domains with member counts and whether they were manually created
    or auto-inferred. Domains cluster related nodes (services, modules,
    endpoints, etc.) by business capability.

    Parameters
    ----------
    project_path:
        Root directory of the project (must be initialised with
        codegiraffe_init first).
    """
    try:
        with _graph_lock:
            graph = _ensure_graph(project_path)
            domains = _list_domains(graph)
            if not domains:
                return (
                    "No domains defined. Use codegiraffe_infer_domains or "
                    "codegiraffe_add_domain to create domains."
                )
            lines = ["Domains:"]
            for d in domains:
                manual_tag = " [manual]" if d.get("manual") else ""
                lines.append(f"  {d['name']}{manual_tag}: {d['node_count']} member(s)")
            return "\n".join(lines)
    except Exception as exc:
        return f"Error listing domains: {exc}"


@mcp.tool()
def codegiraffe_infer_domains(project_path: str) -> str:
    """Auto-infer business domain groupings from graph structure.

    Clusters nodes by directory structure or ID prefix, then adds the
    inferred domains to the graph. Only clusters with 2+ members are added.
    Manual domains already in the graph are preserved.

    Parameters
    ----------
    project_path:
        Root directory of the project (must be initialised with
        codegiraffe_init first).
    """
    try:
        with _graph_lock:
            graph = _ensure_graph(project_path)
            inferred = _infer_domains(graph)
            if not inferred:
                return (
                    "No meaningful domain clusters found. "
                    "Ensure the project has been scanned (codegiraffe_init) and "
                    "nodes have file_path metadata or typed IDs."
                )
            added: list[str] = []
            for domain in inferred:
                _add_domain(graph, domain["name"], domain["node_ids"])
                added.append(f"  {domain['name']}: {domain['node_count']} member(s)")
            _storage.save(project_path, graph.to_data())
            return "Inferred and added domains:\n" + "\n".join(added)
    except Exception as exc:
        return f"Error inferring domains: {exc}"


@mcp.tool()
def codegiraffe_add_domain(
    project_path: str,
    name: str,
    node_ids: str,
) -> str:
    """Create a named business domain with specified member nodes.

    Manual domains survive rescans and can be used to group any nodes
    (services, modules, endpoints, etc.) by business capability.

    Parameters
    ----------
    project_path:
        Root directory of the project (must be initialised with
        codegiraffe_init first).
    name:
        Domain name (e.g. 'payments', 'auth', 'notifications').
    node_ids:
        Comma-separated node IDs to include in the domain.
    """
    try:
        if not name:
            return "Error: 'name' is required"
        member_ids = [n.strip() for n in node_ids.split(",") if n.strip()]
        if not member_ids:
            return "Error: 'node_ids' must be a non-empty comma-separated list"
        with _graph_lock:
            graph = _ensure_graph(project_path)
            warnings: list[str] = []
            for nid in member_ids:
                if nid not in graph.graph:
                    warnings.append(f"Warning: node '{nid}' not found in graph")
            _add_domain(graph, name, member_ids)
            _storage.save(project_path, graph.to_data())
            lines = [f"Added domain '{name}' with {len(member_ids)} member(s)."]
            if warnings:
                lines.append("")
                lines.extend(warnings)
            return "\n".join(lines)
    except Exception as exc:
        return f"Error adding domain: {exc}"


@mcp.tool()
def codegiraffe_remove_domain(project_path: str, name: str) -> str:
    """Remove a business domain and its membership edges from the graph.

    Deletes the domain node and all ``belongs_to`` edges connecting members
    to the domain. Member nodes themselves are not deleted.

    Parameters
    ----------
    project_path:
        Root directory of the project (must be initialised with
        codegiraffe_init first).
    name:
        Name of the domain to remove.
    """
    try:
        if not name:
            return "Error: 'name' is required"
        with _graph_lock:
            graph = _ensure_graph(project_path)
            domain_id = f"domain:{name}"
            if domain_id not in graph.graph:
                return f"Domain '{name}' not found in graph."
            _remove_domain(graph, name)
            _storage.save(project_path, graph.to_data())
            return f"Removed domain '{name}'."
    except Exception as exc:
        return f"Error removing domain: {exc}"


# ---------------------------------------------------------------------------
# Change impact validation tools (v0.10.0)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_validate_changes(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
) -> dict:
    """Analyze uncommitted (or arbitrary) changes against the architecture graph to detect incomplete modifications.

    Parses a diff, maps changed files to graph nodes, computes blast radius,
    and reports potentially missing changes and contract violations.

    When auto=True and diff is not provided, reads uncommitted changes from git.
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return {"error": str(exc)}

    # Obtain the diff text
    raw_diff: str | None = diff
    if raw_diff is None:
        if not auto:
            return {"error": "no diff provided and auto=False. Pass a diff string or set auto=True."}
        try:
            raw_diff = get_uncommitted_diff(project_path)
        except NotAGitRepoError:
            return {"error": f"'{project_path}' is not a git repository."}

    if not raw_diff or not raw_diff.strip():
        return {"status": "no_changes", "message": "No uncommitted changes found."}

    diff_files = parse_diff(raw_diff)
    if not diff_files:
        return {"status": "no_changes", "message": "No uncommitted changes found."}

    report = validate_changes(graph, diff_files)
    return {
        "changed_files": [
            {"path": df.path, "status": df.status}
            for df in report.changed_files
        ],
        "changed_nodes": report.changed_nodes,
        "total_blast_radius": report.total_blast_radius,
        "covered_nodes": report.covered_nodes,
        "uncovered_nodes": report.uncovered_nodes,
        "contract_violations": report.contract_violations,
        "recommendations": report.recommendations,
    }


@mcp.tool()
def codegiraffe_suggest_tests(
    project_path: str,
    diff: str | None = None,
    auto: bool = True,
    max_suggestions: int = 20,
) -> dict:
    """Suggest test files to run based on uncommitted (or arbitrary) changes.

    Uses graph relationships, naming conventions, and blast radius analysis
    to identify the most relevant tests for a given change set.

    When auto=True and diff is not provided, reads uncommitted changes from git.
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return {"error": str(exc), "suggestions": []}

    # Obtain the diff text
    raw_diff: str | None = diff
    if raw_diff is None:
        if not auto:
            return {"error": "no diff provided and auto=False. Pass a diff string or set auto=True.", "suggestions": []}
        try:
            raw_diff = get_uncommitted_diff(project_path)
        except NotAGitRepoError:
            return {"error": f"'{project_path}' is not a git repository.", "suggestions": []}

    if not raw_diff or not raw_diff.strip():
        return {"status": "no_changes", "message": "No uncommitted changes found.", "suggestions": []}

    diff_files = parse_diff(raw_diff)
    if not diff_files:
        return {"status": "no_changes", "message": "No uncommitted changes found.", "suggestions": []}

    suggestions = suggest_tests(graph, diff_files, max_suggestions=max_suggestions)
    suggestion_dicts = [
        {
            "file_path": s.file_path,
            "score": round(s.score, 3),
            "reason": s.reason,
            "strategy": s.strategy,
            "relevance": "high" if s.score >= 0.7 else ("medium" if s.score >= 0.3 else "low"),
        }
        for s in suggestions
    ]
    return {
        "total_suggestions": len(suggestion_dicts),
        "suggestions": suggestion_dicts,
    }


@mcp.tool()
def codegiraffe_file_coupling(
    project_path: str,
    file_path: str | None = None,
    depth: int = 100,
    min_commits: int = 3,
    min_coupling: float = 0.1,
) -> str:
    """Analyze file coupling from git co-change history.

    Mines recent commit history to find files that frequently change
    together, then cross-references with the architecture graph to detect
    implicit coupling not yet captured in the graph.
    """
    # Clamp depth to the configured maximum to prevent excessive git-log traversal.
    depth = min(depth, MAX_COUPLING_DEPTH)

    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return f"Error: {exc}"

    if not is_git_repo(project_path):
        return f"Error: '{project_path}' is not a git repository."

    pairs = file_coupling(
        graph,
        project_path,
        file_path=file_path,
        depth=depth,
        min_commits=min_commits,
        min_coupling=min_coupling,
    )
    return _format_coupling_report(pairs, file_path)


@mcp.tool()
def codegiraffe_order_tasks(
    project_path: str,
    tasks: str,
) -> str:
    """Order a list of tasks based on graph dependencies to minimize integration conflicts.

    Analyses the architecture graph to determine which tasks must run before
    others (because of import/dependency relationships), groups independent
    tasks as parallelisable, and flags same-file conflict zones.

    Parameters
    ----------
    project_path:
        Absolute path to the project whose graph to query.
    tasks:
        JSON array of task objects.  Each object must have:
        - ``"name"`` (str) -- human-readable task name
        - ``"target_files"`` (list[str]) -- file paths the task touches

    Returns a markdown report with:
    - Ordered execution plan with parallelisable groups
    - Dependency edges (why one task precedes another)
    - Conflict zones (files touched by multiple tasks)
    - Cycle warnings when circular dependencies are detected
    """
    try:
        graph = _ensure_graph(project_path)
    except Exception as exc:
        return f"Error: {exc}"

    try:
        task_list = json.loads(tasks)
    except (json.JSONDecodeError, ValueError) as exc:
        return f"Error: invalid JSON for tasks parameter -- {exc}"

    if not isinstance(task_list, list):
        return "Error: tasks must be a JSON array of task objects."

    result = order_tasks(graph, task_list)
    return _format_order_tasks_report(result)


def _format_order_tasks_report(result: dict) -> str:
    """Format the order_tasks() result as a markdown report."""
    lines = ["## Dependency-Aware Task Execution Plan", ""]

    ordered_tasks = result.get("ordered_tasks", [])
    parallel_groups = result.get("parallel_groups", [])
    conflict_zones = result.get("conflict_zones", [])
    dependency_edges = result.get("dependency_edges", [])
    cycle = result.get("cycle")

    if cycle:
        lines.append(f"> **Warning:** {cycle}")
        lines.append("")

    if not ordered_tasks:
        lines.append("No tasks provided.")
        return "\n".join(lines)

    total_groups = len(parallel_groups)
    lines.append(f"### Execution Plan ({total_groups} group(s))")
    lines.append("")
    for group_idx, group in enumerate(parallel_groups, start=1):
        if len(group) == 1:
            task = ordered_tasks[group[0]] if group[0] < len(ordered_tasks) else None
            if task:
                note = " *(cycle -- ordering approximate)*" if task.get("note") else ""
                lines.append(f"**Step {group_idx} -- sequential group:** {task['name']}{note}")
                if task["target_files"]:
                    lines.append(f"  - Files: {', '.join(f'`{f}`' for f in task['target_files'])}")
        else:
            lines.append(f"**Step {group_idx} -- parallel group ({len(group)} tasks):**")
            for idx in group:
                if idx < len(ordered_tasks):
                    task = ordered_tasks[idx]
                    note = " *(cycle -- ordering approximate)*" if task.get("note") else ""
                    lines.append(f"  - {task['name']}{note}")
                    if task["target_files"]:
                        lines.append(f"    - Files: {', '.join(f'`{f}`' for f in task['target_files'])}")
        lines.append("")

    if dependency_edges:
        lines.append("### Dependency Edges")
        lines.append("")
        for edge in dependency_edges:
            lines.append(f"- **{edge['from']}** -> **{edge['to']}** ({edge['reason']})")
        lines.append("")

    if conflict_zones:
        lines.append("### Conflict Zones")
        lines.append("")
        lines.append("The following files are touched by multiple tasks and may cause merge conflicts:")
        lines.append("")
        for zone in conflict_zones:
            task_list_str = ", ".join(f"*{t}*" for t in zone["tasks"])
            lines.append(f"- `{zone['file']}`: {task_list_str}")
        lines.append("")
    else:
        lines.append("### Conflict Zones")
        lines.append("")
        lines.append("No conflict zones detected -- each file is touched by at most one task.")
        lines.append("")

    return "\n".join(lines)





@mcp.tool()
def codegiraffe_coverage(
    project_path: str,
    coverage_path: str,
    format: str = "auto",  # noqa: A002
) -> str:
    """Load a coverage report and annotate graph nodes with test coverage data.

    Parses the given coverage file and sets ``_test_coverage`` metadata (0-100)
    on every graph node whose ``file_path`` matches an entry in the coverage
    report.  If a node has no coverage data its metadata is left unchanged.

    Supported formats (auto-detected by default):

    - ``"coverage_py"`` -- coverage.py JSON output (``coverage json``)
    - ``"istanbul"``    -- Istanbul/NYC JSON output (JavaScript)
    - ``"lcov"``        -- LCOV line coverage format

    Returns a markdown summary of annotated nodes.
    """
    from codegiraffe.coverage_mapper import (  # noqa: PLC0415
        auto_detect_format,
        map_coverage_to_nodes,
        parse_coverage_py,
        parse_istanbul,
        parse_lcov,
    )

    import os as _os  # noqa: PLC0415

    if not _os.path.exists(coverage_path):
        return f"Error: coverage file not found: {coverage_path}"

    try:
        fmt = format if format != "auto" else auto_detect_format(coverage_path)
    except Exception as exc:
        return f"Error detecting coverage format: {exc}"

    parsers = {
        "coverage_py": parse_coverage_py,
        "istanbul": parse_istanbul,
        "lcov": parse_lcov,
    }
    if fmt not in parsers:
        valid_formats = ", ".join(parsers)
        return f"Error: unsupported format '{fmt}'. Use one of: {valid_formats}."
    try:
        coverage_data = parsers[fmt](coverage_path)
    except Exception as exc:
        return f"Error parsing coverage file: {exc}"

    try:
        with _graph_lock:
            graph = _ensure_graph(project_path)
            map_coverage_to_nodes(graph, coverage_data)
            _storage.save(project_path, graph.to_data())

            lines = ["## Coverage Mapping Report", ""]
            lines.append(f"**Format:** {fmt}")
            lines.append(f"**Coverage file:** {coverage_path}")
            lines.append(f"**Files in coverage data:** {len(coverage_data)}")
            lines.append("")

            annotated_nodes: list[tuple[str, str, float]] = []
            for nid, attrs in graph.graph.nodes(data=True):
                node = attrs.get("node")
                if node is None:
                    continue
                cov = node.metadata.get("_test_coverage")
                if cov is not None:
                    annotated_nodes.append((nid, node.file_path or "", cov))
    except Exception as exc:
        return f"Error: {exc}"

    if not annotated_nodes:
        lines.append("No graph nodes matched coverage data.")
    else:
        lines.append(f"**Annotated nodes:** {len(annotated_nodes)}")
        lines.append("")
        lines.append("| Node | File | Coverage |")
        lines.append("|---|---|---|")
        for nid, fp, cov in sorted(annotated_nodes, key=lambda x: x[0]):
            lines.append(f"| `{nid}` | `{fp}` | {cov:.1f}% |")

    lines.append("")
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# Change impact report helpers (private, not MCP tools)
# ---------------------------------------------------------------------------


def _format_validation_report(report) -> str:
    """Format a ChangeReport as a markdown report."""
    lines = ["## Change Impact Validation", ""]

    # Changes Detected
    lines.append("### Changes Detected")
    if report.changed_files:
        for df in report.changed_files:
            lines.append(f"- `{df.path}` ({df.status})")
    else:
        lines.append("- No files changed")
    lines.append("")

    # Impact Analysis
    lines.append("### Impact Analysis")
    lines.append(f"- **Total blast radius:** {report.total_blast_radius} node(s)")
    lines.append("")

    # Covered Impact
    if report.covered_nodes:
        lines.append(f"### Covered Impact ({len(report.covered_nodes)})")
        for nid in report.covered_nodes:
            lines.append(f"- `{nid}` (covered in diff)")
        lines.append("")

    # Potentially Missing Changes
    if report.uncovered_nodes:
        lines.append(f"### Potentially Missing Changes ({len(report.uncovered_nodes)})")
        for nid in report.uncovered_nodes:
            lines.append(f"- `{nid}`")
        lines.append("")

    # Contract Violations
    if report.contract_violations:
        lines.append(f"### Contract Violations ({len(report.contract_violations)})")
        for violation in report.contract_violations:
            lines.append(f"- {violation}")
        lines.append("")

    # Recommendations
    if report.recommendations:
        lines.append(f"### Recommendations ({len(report.recommendations)})")
        for rec in report.recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    return "\n".join(lines)


def _format_test_suggestions(suggestions) -> str:
    """Format a list of TestSuggestion as a markdown report."""
    if not suggestions:
        return "## Test Suggestions\n\nNo test suggestions found for the given changes."

    lines = ["## Test Suggestions", ""]
    lines.append(f"**{len(suggestions)} test(s) suggested**")
    lines.append("")

    # Group by score range
    high = [s for s in suggestions if s.score >= 0.7]
    medium = [s for s in suggestions if 0.3 <= s.score < 0.7]
    low = [s for s in suggestions if s.score < 0.3]

    if high:
        lines.append("### High Relevance")
        for s in high:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    if medium:
        lines.append("### Medium Relevance")
        for s in medium:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    if low:
        lines.append("### Low Relevance")
        for s in low:
            lines.append(
                f"- **{s.file_path}** (score: {s.score:.1f}) — {s.reason} [{s.strategy}]"
            )
        lines.append("")

    return "\n".join(lines)


def _format_coupling_report(pairs, file_path: str | None = None) -> str:
    """Format a list of CouplingPair as a markdown report."""
    lines = ["## File Coupling Analysis", ""]

    if file_path:
        lines.append(f"**Focus file:** `{file_path}`")
        lines.append("")

    if not pairs:
        lines.append("No file coupling pairs found above the threshold.")
        return "\n".join(lines)

    lines.append(f"**{len(pairs)} coupled pair(s) found**")
    lines.append("")

    # Markdown table
    lines.append("| Coupled File | Co-Changes | Coupling | In Graph? |")
    lines.append("|---|---|---|---|")
    for p in pairs:
        # Show the "other" file when a focus file is given
        if file_path:
            other = p.file_b if p.file_a == file_path else p.file_a
        else:
            other = f"{p.file_a} <-> {p.file_b}"
        in_graph = "Yes" if p.in_graph else "No"
        lines.append(
            f"| `{other}` | {p.co_change_count} | {p.coupling:.2f} | {in_graph} |"
        )
    lines.append("")

    # Implicit coupling section
    implicit = [p for p in pairs if not p.in_graph and p.coupling >= 0.5]
    if implicit:
        lines.append(f"### Implicit Coupling ({len(implicit)} pair(s) not in graph)")
        lines.append("")
        for p in implicit:
            lines.append(
                f"- `{p.file_a}` <-> `{p.file_b}` (coupling: {p.coupling:.2f}, "
                f"co-changes: {p.co_change_count}) — consider adding a graph edge"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risk report helpers (private, not MCP tools)
# ---------------------------------------------------------------------------


def _format_risk_report(scored: list[dict], total_nodes: int) -> str:
    """Format a list of risk-scored nodes as a markdown report."""
    lines = ["## Risk Assessment Report", ""]
    lines.append(f"**Graph size:** {total_nodes} nodes")
    lines.append(f"**Nodes assessed:** {len(scored)}")
    lines.append("")
    for i, item in enumerate(scored, 1):
        lines.append(f"### {i}. {item['label']} (`{item['node_id']}`)")
        lines.append(f"- **Risk score:** {item['risk_score']}")
        lines.append(f"- **Type:** {item['type']}")
        lines.append(f"- **Degree centrality:** {item['degree_centrality']}")
        lines.append(f"- **Betweenness centrality:** {item['betweenness_centrality']}")
        lines.append(f"- **Blast radius:** {item['blast_radius_count']} downstream nodes")
        if item.get("file_path"):
            lines.append(f"- **File:** {item['file_path']}")
        why = _risk_explanation(item)
        lines.append(f"- **Why this matters:** {why}")
        lines.append("")
    return "\n".join(lines)


def _risk_explanation(item: dict) -> str:
    """Produce a brief human-readable explanation of a node's risk score."""
    reasons: list[str] = []
    if item["degree_centrality"] > 0.3:
        reasons.append("highly connected hub")
    if item["betweenness_centrality"] > 0.2:
        reasons.append("critical bottleneck on many paths")
    if item["blast_radius_count"] > 5:
        reasons.append(
            f"changes propagate to {item['blast_radius_count']} downstream nodes"
        )
    if not reasons:
        reasons.append("moderate connectivity")
    return "; ".join(reasons)


@mcp.tool()
def codegiraffe_sync(
    project_path: str,
    include_tests: bool = False,
    scanner_mode: str = "hybrid",
) -> str:
    """Re-scan the project and synchronize the architecture graph.

    Performs a fresh scan, replaces all auto-discovered nodes and edges,
    while preserving any manually added annotations. Returns a summary
    of what changed.

    Parameters
    ----------
    project_path:
        Absolute path to the project root (must already be initialized with
        ``codegiraffe_init``).
    include_tests:
        When ``True``, test files are included in the scan.
    scanner_mode:
        Scanner strategy — ``"hybrid"`` (default, falls back to regex if
        tree-sitter is unavailable), ``"regex"``, or ``"ast"``.
    """
    global _graph  # noqa: PLW0603

    try:
        # Read old graph data under lock so the snapshot is consistent
        with _graph_lock:
            graph = _ensure_graph(project_path)
            old_data = graph.to_data()

        old_node_count = len(old_data.nodes)
        old_edge_count = len(old_data.edges)

        # Select scanner registry based on mode
        registry = None
        if scanner_mode == "ast":
            from codegiraffe.ast_scanner import get_ast_registry

            registry = get_ast_registry()
        elif scanner_mode == "hybrid":
            try:
                from codegiraffe.ast_scanner import get_hybrid_registry
                registry = get_hybrid_registry()
            except ImportError:
                registry = None  # falls back to default regex registry

        # Re-scan (slow — do NOT hold the lock during scanning)
        result = scan_project(project_path, registry=registry, include_tests=include_tests)

        # Build new graph from scan results
        nodes: dict[str, Node] = {node.id: node for node in result.nodes}
        edges = result.edges

        new_data = GraphData(
            nodes=nodes,
            edges=edges,
            project_path=project_path,
            last_scan=datetime.now(timezone.utc).isoformat(),
        )

        new_graph = ArchGraph(new_data)

        # Merge back manual annotations from the old graph
        new_graph.merge_manual_annotations(old_data)

        # Compute and attach layout before persisting
        data = new_graph.to_data()
        try:
            from codegiraffe.layout import compute_layout
            data.layout = compute_layout(data)
        except Exception:
            pass  # never fail sync if layout computation errors

        # Atomically persist and replace the cached graph under the lock
        with _graph_lock:
            _storage.save(project_path, data)
            _graph = new_graph

        # Auto-version after sync (outside lock — version store has its own safety)
        _version_store.add_version(
            project_path, old_data, new_graph.to_data(), "Sync",
        )

        final_data = new_graph.to_data()
        new_node_count = len(final_data.nodes)
        new_edge_count = len(final_data.edges)

        return (
            f"Sync complete. "
            f"Nodes: {old_node_count} -> {new_node_count} "
            f"(delta {new_node_count - old_node_count:+d}). "
            f"Edges: {old_edge_count} -> {new_edge_count} "
            f"(delta {new_edge_count - old_edge_count:+d})."
        )
    except Exception as exc:
        return f"Error syncing graph: {exc}"


@mcp.tool()
def codegiraffe_sync_files(
    project_path: str,
    file_paths: str,
    scanner_mode: str = "hybrid",
) -> str:
    """Incrementally sync specific changed files in the architecture graph.

    Instead of re-scanning the entire project, only rescans the files listed
    in *file_paths*.  Non-manual nodes and outgoing edges from each listed
    file are removed and replaced with freshly scanned content.  Manual
    annotations survive the sync.  Files that no longer exist are handled
    as deletions (their nodes/edges are removed).

    Parameters
    ----------
    project_path:
        Absolute path to the project root (must already be initialized with
        ``codegiraffe_init``).
    file_paths:
        Files to re-scan.  Accepts either a JSON array of absolute paths
        (e.g. ``["path/a.py","path/b.py"]``) or a comma-separated string
        (e.g. ``"path/a.py,path/b.py"``).
    scanner_mode:
        Scanner strategy — ``"hybrid"`` (default, falls back to regex if
        tree-sitter is unavailable), ``"regex"``, or ``"ast"``.

    Returns
    -------
    str
        JSON string with keys ``added``, ``removed``, and ``preserved``,
        each containing ``nodes`` and ``edges`` counts.
    """
    global _graph  # noqa: PLW0603

    try:
        from codegiraffe.scanner import sync_files

        # Parse file_paths: accept JSON array or comma-separated string (no shared state)
        if file_paths.strip().startswith("["):
            paths = json.loads(file_paths)
        else:
            paths = [p.strip() for p in file_paths.split(",") if p.strip()]

        with _graph_lock:
            graph = _ensure_graph(project_path)

            summary = sync_files(
                graph=graph,
                project_path=project_path,
                file_paths=paths,
                scanner_mode=scanner_mode,
            )

            # Persist updated graph
            _storage.save(project_path, graph.to_data())

        return json.dumps(summary)

    except Exception as exc:
        return f"Error in incremental sync: {exc}"


@mcp.tool()
def codegiraffe_export(
    project_path: str,
    format: str = "mermaid",
    direction: str = "TD",
    subgraph_by_type: bool = True,
    node_id: str | None = None,
    depth: int = 2,
) -> str:
    """Export the architecture graph as a visualization.

    Supported formats:
    - "mermaid": Mermaid flowchart diagram
    - "d3": D3.js-compatible JSON for force-directed graphs

    Optionally scope the export to a subgraph around a specific node.
    """
    try:
        graph = _ensure_graph(project_path)

        if node_id:
            data = graph.get_subgraph(node_id, depth=depth)
        else:
            data = graph.to_data()

        from codegiraffe.export import to_d3_json, to_mermaid

        if format.lower() == "mermaid":
            return to_mermaid(
                data, direction=direction, subgraph_by_type=subgraph_by_type
            )
        elif format.lower() == "d3":
            return to_d3_json(data)
        else:
            return f"Unsupported format: {format}. Use 'mermaid' or 'd3'."
    except Exception as exc:
        return f"Error exporting graph: {exc}"


# ---------------------------------------------------------------------------
# Multi-agent coordination tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_claim(
    project_path: str,
    agent_id: str,
    node_ids: list[str],
    task: str,
    ttl: int = 1800,
) -> str:
    """Claim graph nodes for an agent to prevent conflicts during concurrent development.

    Before modifying nodes, agents should claim them. If another agent has already
    claimed overlapping nodes, the claim fails with conflict details.

    Claims automatically expire after `ttl` seconds (default 30 minutes).
    """
    try:
        result = _coordinator.claim(project_path, agent_id, node_ids, task, ttl)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error claiming nodes: {exc}"


@mcp.tool()
def codegiraffe_release(project_path: str, agent_id: str) -> str:
    """Release an agent's claim on graph nodes.

    Removes the agent's active claim, freeing all claimed nodes so other
    agents can work on them. Agents should call this when they finish their
    task or when they need to abandon a claim.

    Parameters
    ----------
    project_path:
        Root directory of the project.
    agent_id:
        The agent releasing its claim.
    """
    try:
        result = _coordinator.release(project_path, agent_id)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error releasing claim: {exc}"


@mcp.tool()
def codegiraffe_update_agent_status(
    project_path: str,
    agent_id: str,
    status: str,
    task: str | None = None,
) -> str:
    """Update an agent's status. Status can be 'active', 'done', or 'blocked'.

    Also refreshes the claim's TTL so it doesn't expire while the agent is
    actively working.
    """
    try:
        result = _coordinator.update_status(project_path, agent_id, status, task)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error updating status: {exc}"


@mcp.tool()
def codegiraffe_agents(project_path: str) -> str:
    """List all active agents and their claimed nodes/status.

    Shows which agents are working on which parts of the architecture graph,
    enabling coordination and conflict avoidance.
    """
    try:
        agents = _coordinator.list_agents(project_path)
        if not agents:
            return "No active agents."
        return json.dumps(agents, indent=2)
    except Exception as exc:
        return f"Error listing agents: {exc}"


# ---------------------------------------------------------------------------
# Status tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_status(project_path: str) -> str:
    """Get the initialization status and health of a project's architecture graph.

    Returns a JSON object with graph statistics, staleness, and active agents.
    Does not require the graph to be loaded into memory — reads directly from storage.
    """
    try:
        if not _storage.exists(project_path):
            return json.dumps({"initialized": False, "project_path": project_path}, indent=2)

        graph_data = _storage.load(project_path)
        metadata = graph_data.metadata or {}

        last_scan_raw = metadata.get("scanned_at")
        if last_scan_raw:
            try:
                last_scan_dt = datetime.fromisoformat(last_scan_raw)
                if last_scan_dt.tzinfo is None:
                    last_scan_dt = last_scan_dt.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last_scan_dt
                total_seconds = delta.total_seconds()
                if total_seconds < 3600:
                    staleness = "fresh"
                elif total_seconds < 86400:
                    staleness = "stale"
                else:
                    staleness = "very_stale"
            except (ValueError, TypeError):
                staleness = "unknown"
        else:
            last_scan_raw = None
            staleness = "unknown"

        try:
            active_agents = _coordinator.list_agents(project_path)
        except Exception:
            active_agents = []

        return json.dumps(
            {
                "initialized": True,
                "project_path": project_path,
                "node_count": len(graph_data.nodes),
                "edge_count": len(graph_data.edges),
                "last_scan": last_scan_raw,
                "staleness": staleness,
                "storage_backend": type(_storage).__name__,
                "active_agents": active_agents,
                "schema_version": metadata.get("schema_version"),
            },
            indent=2,
        )
    except Exception as e:
        return f"Error getting status: {e}"


# ---------------------------------------------------------------------------
# Versioning tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_history(project_path: str, limit: int = 20) -> str:
    """List version history for a project's architecture graph.

    Returns timestamped version entries with diff summaries showing what
    changed in each version (nodes/edges added/removed).
    """
    try:
        history = _version_store.get_history(project_path)
        return json.dumps(history[:limit], indent=2)
    except Exception as exc:
        return f"Error getting history: {exc}"


@mcp.tool()
def codegiraffe_diff(project_path: str, version_a: int, version_b: int | None = None) -> str:
    """Compare two versions of the architecture graph.

    If only *version_a* is given, returns the diff stored with that version
    (i.e. changes introduced by that version). When both *version_a* and
    *version_b* are given, computes a fresh diff between those two versions'
    graph snapshots using the stored diffs.

    Returns a detailed diff showing nodes/edges added, removed, and
    attributes changed.
    """
    try:
        if version_b is not None:
            va = _version_store.get_version(project_path, version_a)
            vb = _version_store.get_version(project_path, version_b)
            if va is None or vb is None:
                return "Error: version not found"
            # Return the diff from the later version
            later = vb if version_b > version_a else va
            return json.dumps(
                {"version_a": version_a, "version_b": version_b, "diff": later.diff.to_dict()},
                indent=2,
            )
        else:
            version = _version_store.get_version(project_path, version_a)
            if version is None:
                return "Error: version not found"
            return json.dumps(version.diff.to_dict(), indent=2)
    except Exception as exc:
        return f"Error computing diff: {exc}"


@mcp.tool()
def codegiraffe_snapshot(project_path: str, message: str = "Manual snapshot") -> str:
    """Create a named snapshot of the current architecture graph state.

    Use this to bookmark the graph state before making significant changes.
    The snapshot is stored in the version history with the given message.
    The diff recorded is empty since the snapshot captures the current state
    without any changes.
    """
    try:
        graph = _ensure_graph(project_path)
        current_data = graph.to_data()
        # Snapshot: diff against itself produces an empty diff
        version = _version_store.add_version(
            project_path, current_data, current_data, message,
        )
        return json.dumps(
            {"version_id": version.version_id, "message": message, "timestamp": version.timestamp},
            indent=2,
        )
    except Exception as exc:
        return f"Error creating snapshot: {exc}"


# ---------------------------------------------------------------------------
# Federation tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_federate(project_paths: list[str]) -> str:
    """Register multiple repositories and build a unified federated graph.

    Each repository must have been initialized with ``codegiraffe_init``
    first. Returns a summary of the federated graph with namespace-isolated
    node IDs (prefixed with ``repo:{name}::``).
    """
    try:
        registered: list[str] = []
        errors: list[str] = []

        for path in project_paths:
            try:
                name = _federation.register_repo(path)
                registered.append(name)
            except FileNotFoundError as exc:
                errors.append(str(exc))

        if not registered:
            return json.dumps({"error": "No repos registered", "details": errors}, indent=2)

        unified = _federation.get_unified_graph()
        _federation.save_federation()

        result = {
            "registered_repos": registered,
            "total_nodes": len(unified.nodes),
            "total_edges": len(unified.edges),
        }
        if errors:
            result["errors"] = errors

        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error federating graphs: {exc}"


@mcp.tool()
def codegiraffe_cross_query(node_id: str, depth: int = 2) -> str:
    """Query across all federated graphs for a specific node.

    The *node_id* must be a namespaced ID in the format
    ``repo:{name}::{node_id}``. Extracts a subgraph up to *depth* hops
    around that node, spanning across repository boundaries.
    """
    try:
        subgraph = _federation.query_federated(node_id, depth)
        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error querying federated graph: {exc}"


@mcp.tool()
def codegiraffe_cross_edges() -> str:
    """List all edges that cross repository boundaries in the federation.

    An edge is considered cross-repo if its source and target belong to
    different repository namespaces. Useful for understanding inter-service
    dependencies.
    """
    try:
        cross_edges = _federation.get_cross_repo_edges()
        result = [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            }
            for edge in cross_edges
        ]
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error getting cross-repo edges: {exc}"


# ---------------------------------------------------------------------------
# Neo4j tools
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_cypher(project_path: str, query: str) -> str:
    """Run a read-only Cypher query against the Neo4j-stored architecture graph.

    Requires Neo4j storage backend and the ``neo4j`` Python driver.
    Connection is configured via environment variables ``NEO4J_URI``,
    ``NEO4J_USER``, and ``NEO4J_PASSWORD``.

    Write operations are rejected: queries containing the keywords CREATE,
    MERGE, DELETE, SET, REMOVE, DROP, DETACH, or CALL will raise a
    ``ValueError`` before reaching the database.

    Returns query results as a JSON array of row objects.
    """
    try:
        from codegiraffe.neo4j_storage import Neo4jStorage

        if isinstance(_storage, Neo4jStorage):
            storage = _storage
        else:
            storage = Neo4jStorage()
        results = storage.run_cypher(query, project_path=project_path)
        return json.dumps(results, indent=2, default=str)
    except ImportError:
        return "Error: Neo4j driver not installed. Install with: pip install codegiraffe[neo4j]"
    except Exception as exc:
        return f"Error running Cypher query: {exc}"


# ---------------------------------------------------------------------------
# Convention Mining
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_patterns(
    project_path: str,
    node_type: str,
    min_cluster: int = 3,
) -> str:
    """Mine naming conventions and detect anti-patterns from a cluster of same-type nodes.

    Analyzes all nodes of the given *node_type* in the graph to surface:
    - **Naming pattern**: common prefix/suffix in node IDs (e.g. ``service:*Service``)
    - **Common attributes**: metadata keys present in >66% of nodes
    - **Outliers**: node IDs that deviate from the majority convention
    - **Exemplar**: the node most representative of the cluster

    Requires at least *min_cluster* nodes of the given type (default 3).

    Examples::

        codegiraffe_patterns(project_path=".", node_type="service")
        codegiraffe_patterns(project_path=".", node_type="endpoint", min_cluster=5)
    """
    try:
        graph = _ensure_graph(project_path)
        result = _extract_patterns(graph, node_type, min_cluster=min_cluster)
    except Exception as exc:
        return f"Error extracting patterns: {exc}"

    return _format_pattern_report(result)


def _format_pattern_report(result: dict) -> str:
    """Format an extract_patterns result dict as a markdown report."""
    node_type = result.get("node_type", "unknown")
    sample_size = result.get("sample_size", 0)

    lines = [f"## Convention Mining: `{node_type}`", ""]
    lines.append(f"**Nodes analysed:** {sample_size}")
    lines.append("")

    if "message" in result:
        lines.append(f"_{result['message']}_")
        return "\n".join(lines)

    naming_pattern = result.get("naming_pattern", "")
    common_attributes = result.get("common_attributes", {})
    outliers = result.get("outliers", [])
    exemplar = result.get("exemplar", "")

    # Naming pattern
    lines.append(f"**Naming pattern:** `{naming_pattern}`")
    lines.append("")

    # Exemplar
    if exemplar:
        lines.append(f"**Exemplar node:** `{exemplar}`")
        lines.append("")

    # Common attributes
    if common_attributes:
        lines.append("**Common attributes** (present in >66% of nodes):")
        for key, value in sorted(common_attributes.items()):
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    else:
        lines.append("**Common attributes:** none detected")
        lines.append("")

    # Outliers
    if outliers:
        lines.append(f"**Outliers** ({len(outliers)} node(s) deviating from the pattern):")
        for nid in outliers:
            lines.append(f"- `{nid}`")
        lines.append("")
    else:
        lines.append("**Outliers:** none — all nodes conform to the pattern")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PR Diff tool (v0.11.0 -- Graph Intelligence)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_pr_diff(
    project_path: str,
    base_ref: str,
    head_ref: str = "HEAD",
    scanner_mode: str = "hybrid",
) -> str:
    """Compare the architectural graph between two git refs for PR review.

    Builds a temporary git worktree for *base_ref* and *head_ref*, scans each
    one, and computes the architectural diff between them.  Returns a markdown
    report showing nodes added/removed/modified, edges added/removed, contracts
    affected, and any new circular dependencies introduced by the PR.

    Parameters
    ----------
    project_path:
        Root of the git repository to analyse.
    base_ref:
        The base branch / commit SHA (e.g. ``"main"`` or ``"abc1234"``).
    head_ref:
        The head branch / commit SHA (default ``"HEAD"`` -- the current branch tip).
    scanner_mode:
        ``"hybrid"`` (default, falls back to regex if tree-sitter is
        unavailable), ``"regex"``, or ``"ast"`` for tree-sitter scanning.
    """
    from codegiraffe.graph_diff import build_graph_at_ref, compute_graph_diff

    try:
        base_graph = build_graph_at_ref(project_path, base_ref, scanner_mode=scanner_mode)
    except Exception as exc:
        return f"Error building graph at base ref {base_ref!r}: {exc}"

    try:
        head_graph = build_graph_at_ref(project_path, head_ref, scanner_mode=scanner_mode)
    except Exception as exc:
        return f"Error building graph at head ref {head_ref!r}: {exc}"

    try:
        diff = compute_graph_diff(base_graph, head_graph)
    except Exception as exc:
        return f"Error computing graph diff: {exc}"

    return _format_pr_diff_report(diff, base_ref, head_ref)


def _format_pr_diff_report(diff: dict, base_ref: str, head_ref: str) -> str:
    """Format a compute_graph_diff result as a markdown PR review report."""
    lines = [
        f"## PR Architectural Diff: `{base_ref}` -> `{head_ref}`",
        "",
        diff["summary"],
        "",
    ]

    # Nodes
    if diff["nodes_added"]:
        lines.append(f"### Nodes Added ({len(diff['nodes_added'])})")
        for nid in diff["nodes_added"]:
            lines.append(f"- `{nid}`")
        lines.append("")

    if diff["nodes_removed"]:
        lines.append(f"### Nodes Removed ({len(diff['nodes_removed'])})")
        for nid in diff["nodes_removed"]:
            lines.append(f"- `{nid}`")
        lines.append("")

    if diff["nodes_modified"]:
        lines.append(f"### Nodes Modified ({len(diff['nodes_modified'])})")
        for nid in diff["nodes_modified"]:
            lines.append(f"- `{nid}`")
        lines.append("")

    # Edges
    if diff["edges_added"]:
        lines.append(f"### Edges Added ({len(diff['edges_added'])})")
        for e in diff["edges_added"]:
            lines.append(f"- `{e['source']}` --[{e['type']}]--> `{e['target']}`")
        lines.append("")

    if diff["edges_removed"]:
        lines.append(f"### Edges Removed ({len(diff['edges_removed'])})")
        for e in diff["edges_removed"]:
            lines.append(f"- `{e['source']}` --[{e['type']}]--> `{e['target']}`")
        lines.append("")

    # Contracts
    if diff["contracts_affected"]:
        lines.append(f"### Contracts Affected ({len(diff['contracts_affected'])})")
        for cid in diff["contracts_affected"]:
            lines.append(f"- `{cid}`")
        lines.append("")

    # New cycles
    if diff["new_cycles"]:
        lines.append(f"### New Cycles Introduced ({len(diff['new_cycles'])})")
        lines.append(
            "> **Warning:** The following circular dependencies were introduced by this PR."
        )
        for i, cycle in enumerate(diff["new_cycles"], 1):
            display = cycle + [cycle[0]]
            lines.append(f"**Cycle {i}:** " + " -> ".join(f"`{n}`" for n in display))
        lines.append("")
    else:
        lines.append("### Cycles")
        lines.append("No new circular dependencies introduced.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Migration planner tool (v0.11.0 -- Graph Intelligence)
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_migration_plan(
    project_path: str,
    description: str,
    target_nodes: str | None = None,
) -> str:
    """Generate an ordered migration plan for a refactor or architectural change.

    Resolves affected nodes (from *target_nodes* or keyword-matched from
    *description*), sorts them by dependency order (leaves first), identifies
    safe rollback checkpoints, and surfaces any contract implications.

    Parameters
    ----------
    project_path:
        Root of the project whose graph to use.
    description:
        Human-readable description of the migration (e.g. "migrate auth
        service to JWT tokens").  Used for keyword-matching when
        *target_nodes* is not supplied.
    target_nodes:
        Optional JSON array of explicit node IDs to include in the plan
        (e.g. ``'["auth.service", "auth.middleware"]'``).  When omitted,
        affected nodes are inferred from *description*.
    """
    try:
        graph = _ensure_graph(project_path)
    except RuntimeError as exc:
        return f"Error: {exc}"

    parsed_targets: list[str] | None = None
    if target_nodes is not None:
        try:
            parsed_targets = json.loads(target_nodes)
        except (json.JSONDecodeError, TypeError) as exc:
            return f"Error: target_nodes must be a valid JSON array — {exc}"

    plan = generate_migration_plan(graph, description, parsed_targets)

    if not plan["steps"]:
        return (
            f"No nodes matched for migration plan.\n"
            f"Description: {description!r}\n"
            f"Tip: pass target_nodes as a JSON array of node IDs, or use "
            f"codegiraffe_query to discover relevant node IDs first."
        )

    lines: list[str] = [
        f"## Migration Plan: {description}",
        "",
        f"**Steps:** {len(plan['steps'])}  |  "
        f"**Files affected:** {plan['estimated_files']}  |  "
        f"**Checkpoints:** {len(plan['checkpoints'])}",
        "",
    ]

    if plan["cycles"]:
        lines.append(
            f"> **Warning:** {len(plan['cycles'])} cycle(s) detected among target "
            f"nodes — dependency order may not be optimal."
        )
        for cycle in plan["cycles"]:
            lines.append("  - " + " -> ".join(f"`{n}`" for n in cycle))
        lines.append("")

    lines.append("### Steps")
    checkpoint_set = set(plan["checkpoints"])
    for step in plan["steps"]:
        marker = " ✓ checkpoint" if step["order"] in checkpoint_set else ""
        file_hint = f" (`{step['file']}`)" if step["file"] else ""
        lines.append(
            f"{step['order']}. **{step['node_id']}**{file_hint} — {step['description']}{marker}"
        )
    lines.append("")

    if plan["contract_implications"]:
        lines.append(f"### Contract Implications ({len(plan['contract_implications'])})")
        for ci in plan["contract_implications"]:
            lines.append(f"- **{ci['contract']}**: {ci['impact']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dashboard launch tool
# ---------------------------------------------------------------------------


@mcp.tool()
def codegiraffe_dashboard(project_path: str, port: int = 8251) -> str:
    """Launch the Code Giraffe web dashboard for the given project.

    Starts a background HTTP server (if not already running) serving the
    interactive Sigma.js v3 dashboard and opens the user's default browser.

    The project must be initialized first (run *codegiraffe_init* if you
    haven't already).

    Parameters
    ----------
    project_path:
        Absolute path to the project root whose graph should be displayed.
    port:
        Preferred local port for the dashboard HTTP server (default 8251).
        If the port is occupied, the next free port up to 8255 is used.
    """
    import webbrowser
    from codegiraffe.dashboard_server import get_or_start_server

    if not _storage.exists(project_path):
        return (
            f"No architecture graph found for '{project_path}'. "
            "Run codegiraffe_init first, then launch the dashboard."
        )

    try:
        server = get_or_start_server(_ensure_graph, _storage, port=port)
    except Exception as exc:
        return f"Failed to start dashboard server: {exc}"

    if not server.is_running:
        return f"Dashboard server failed to start on port {server.port}. Check stderr for details."

    url = server.url(project_path)
    webbrowser.open(url)

    return f"Dashboard running at {url}\nOpened browser to the dashboard."


# ---------------------------------------------------------------------------
# Web dashboard
# ---------------------------------------------------------------------------

from codegiraffe.dashboard import register_dashboard_routes

register_dashboard_routes(mcp, _ensure_graph, _storage)

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    transport = "stdio"
    port = 8000
    for arg in sys.argv[1:]:
        if arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg in ("--transport", "--port"):
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                val = sys.argv[idx + 1]
                if arg == "--transport":
                    transport = val
                else:
                    port = int(val)

    if transport in ("sse", "streamable-http"):
        mcp.settings.port = port

    # When running under stdio transport, auto-launch the background dashboard
    # server if the working directory has already been initialized.
    if transport == "stdio" and _storage.exists(os.getcwd()):
        try:
            from codegiraffe.dashboard_server import get_or_start_server
            get_or_start_server(_ensure_graph, _storage)
        except Exception:
            pass  # Dashboard is optional; never let it break the MCP server.

    mcp.run(transport=transport)
