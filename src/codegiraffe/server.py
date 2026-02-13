"""MCP server entry point for Code Giraffe.

Exposes architecture knowledge graph tools via the FastMCP protocol,
allowing MCP clients to initialize, query, annotate, and synchronize
architectural graphs for Python projects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from codegiraffe.graph import ArchGraph, Edge, GraphData, Node
from codegiraffe.query import context_for_task, detect_drift, query_by_node, query_by_type
from codegiraffe.scanner import scan_project
from codegiraffe.storage import JSONStorage

# ---------------------------------------------------------------------------
# Server and shared state
# ---------------------------------------------------------------------------

mcp = FastMCP("codegiraffe")

_storage = JSONStorage()
_graph: ArchGraph | None = None


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
def codegiraffe_init(project_path: str, rescan: bool = False) -> str:
    """Initialize or re-scan the architecture knowledge graph for a project.

    Scans the project directory for architectural patterns (endpoints,
    database tables, workers, env vars, external APIs, services) and builds
    a graph. When *rescan* is True and an existing graph is found, manually
    added annotations are preserved.

    Returns a summary of the initialized graph.
    """
    global _graph  # noqa: PLW0603

    try:
        # Preserve manual annotations when rescanning
        old_data: GraphData | None = None
        if rescan:
            old_data = _storage.load(project_path)

        # Scan the project
        result = scan_project(project_path)

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
) -> str:
    """Get the most relevant subgraph for a natural-language task description.

    Scores nodes by keyword overlap with the task text and returns the
    top-matching nodes with their immediate neighbors, capped at *max_nodes*.
    Useful for scoping what parts of the architecture are relevant before
    making changes.
    """
    try:
        graph = _ensure_graph(project_path)
        subgraph = context_for_task(graph, task, max_nodes)
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
def codegiraffe_sync(project_path: str) -> str:
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
        result = scan_project(project_path)

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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
