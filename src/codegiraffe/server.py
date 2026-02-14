"""MCP server entry point for Code Giraffe.

Exposes architecture knowledge graph tools via the FastMCP protocol,
allowing MCP clients to initialize, query, annotate, and synchronize
architectural graphs for Python projects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from codegiraffe.coordination import CoordinationStore
from codegiraffe.federation import GraphFederation
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.query import context_for_task, detect_drift, query_by_node, query_by_type
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
    """
    global _graph  # noqa: PLW0603

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
    scanner_mode: str = "regex",
    include_tests: bool = False,
) -> str:
    """Initialize or re-scan the architecture knowledge graph for a project.

    Scans the project directory for architectural patterns (endpoints,
    database tables, workers, env vars, external APIs, services) and builds
    a graph. When *rescan* is True and an existing graph is found, manually
    added annotations are preserved.

    Use *backend* to select the storage backend: ``"json"`` (default),
    ``"sqlite"`` for a SQLite database, or ``"neo4j"`` for Neo4j.

    Use *scanner_mode* to choose the scanning strategy: ``"regex"`` (default)
    for regex-based pattern matching, or ``"ast"`` for tree-sitter AST-based
    scanning (requires tree-sitter packages).

    Returns a summary of the initialized graph.
    """
    global _graph, _storage  # noqa: PLW0603

    try:
        _storage = _get_storage(backend)
        # Preserve manual annotations when rescanning
        old_data: GraphData | None = None
        if rescan:
            old_data = _storage.load(project_path)

        # Select scanner registry based on mode
        registry = None
        if scanner_mode == "ast":
            from codegiraffe.ast_scanner import get_ast_registry

            registry = get_ast_registry()

        # Scan the project
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

        # Persist and cache
        _storage.save(project_path, graph.to_data())
        _graph = graph

        # Auto-version after init/rescan
        prev_data = old_data if old_data is not None else GraphData()
        _version_store.add_version(
            project_path, prev_data, graph.to_data(),
            "Rescan" if rescan else "Init",
        )

        final_data = graph.to_data()
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
    depth: int = 2,
) -> str:
    """Query the architecture graph by node ID or node type.

    Provide *node_id* to extract a subgraph centered on that node (up to
    *depth* hops), or *node_type* to retrieve all nodes of that type with
    their direct edges. Returns the subgraph as formatted JSON.
    """
    try:
        graph = _ensure_graph(project_path)

        if node_id is not None:
            subgraph = query_by_node(graph, node_id, depth)
        elif node_type is not None:
            subgraph = query_by_type(graph, node_type)
        else:
            return "Error: provide either node_id or node_type"

        return subgraph.model_dump_json(indent=2)
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
        graph = _ensure_graph(project_path)

        # Parse metadata JSON
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return "Error: metadata is not valid JSON"

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
) -> str:
    """Get the most relevant subgraph for a natural-language task description.

    When sentence-transformers is installed and *use_embeddings* is True, uses
    embedding-based semantic similarity for scoring.  Otherwise falls back to
    keyword overlap scoring.  Returns the top-matching nodes with their
    immediate neighbors, capped at *max_nodes*.

    Useful for scoping what parts of the architecture are relevant before
    making changes.
    """
    try:
        graph = _ensure_graph(project_path)
        subgraph = context_for_task(graph, task, max_nodes, use_embeddings=use_embeddings)
        return subgraph.model_dump_json(indent=2)
    except Exception as exc:
        return f"Error computing context: {exc}"


@mcp.tool()
def codegiraffe_detect_drift(project_path: str) -> str:
    """Detect drift between the architecture graph and the actual codebase.

    Re-scans the project and compares the results against the stored graph.
    Reports nodes that exist in the graph but not in code, nodes found in
    code but missing from the graph, and potential renames.

    Returns a JSON array of drift records.
    """
    try:
        graph = _ensure_graph(project_path)
        drifts = detect_drift(graph, project_path)
        return json.dumps(drifts, indent=2)
    except Exception as exc:
        return f"Error detecting drift: {exc}"


@mcp.tool()
def codegiraffe_hotspots(project_path: str, top_n: int = 10) -> str:
    """Find the most connected nodes (architectural hotspots) in the graph.

    Ranks nodes by degree centrality -- highly connected nodes are likely
    architectural hotspots that deserve extra attention during changes.

    Returns a JSON array of {node_id, label, type, score} objects.
    """
    try:
        graph = _ensure_graph(project_path)
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


@mcp.tool()
def codegiraffe_sync(project_path: str, include_tests: bool = False) -> str:
    """Re-scan the project and synchronize the architecture graph.

    Performs a fresh scan, replaces all auto-discovered nodes and edges,
    while preserving any manually added annotations. Returns a summary
    of what changed.
    """
    global _graph  # noqa: PLW0603

    try:
        graph = _ensure_graph(project_path)
        old_data = graph.to_data()
        old_node_count = len(old_data.nodes)
        old_edge_count = len(old_data.edges)

        # Re-scan
        result = scan_project(project_path, include_tests=include_tests)

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

        # Persist and cache
        _storage.save(project_path, new_graph.to_data())
        _graph = new_graph

        # Auto-version after sync
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
def codegiraffe_status(
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


@mcp.tool()
def codegiraffe_restore(project_path: str, version_id: int) -> str:
    """Restore the architecture graph to a specific version.

    Warning: This operation is currently limited because only diffs (not
    full snapshots) are stored. A pre-restore backup snapshot is created
    automatically before attempting the restore.
    """
    try:
        # Snapshot current state before restore attempt
        graph = _ensure_graph(project_path)
        current_data = graph.to_data()
        _version_store.add_version(
            project_path, current_data, current_data,
            f"Pre-restore backup (before restoring to v{version_id})",
        )

        version = _version_store.get_version(project_path, version_id)
        if version is None:
            return f"Error: version {version_id} not found"

        return (
            "Error: restore requires full snapshot storage (not yet supported "
            "— only diffs are stored). A backup snapshot of the current state "
            "has been saved."
        )
    except Exception as exc:
        return f"Error restoring version: {exc}"


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
    mcp.run(transport=transport)
