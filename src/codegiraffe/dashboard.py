"""Web dashboard for Code Giraffe architecture graphs.

Serves a single-page Sigma.js v3-based visualization of the architecture
knowledge graph.  All HTML, CSS, and JavaScript are embedded in this module
--- no external files are needed.

Usage::

    from codegiraffe.dashboard import register_dashboard_routes
    register_dashboard_routes(mcp, _ensure_graph, _storage)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from codegiraffe.export import to_d3_json
from codegiraffe.graph import ArchGraph, GraphData

# ---------------------------------------------------------------------------
# Logo helpers
# ---------------------------------------------------------------------------

_logo_cache: bytes | None = None
_logo_cache_loaded: bool = False


def _load_logo_bytes() -> bytes | None:
    global _logo_cache, _logo_cache_loaded
    if _logo_cache_loaded:
        return _logo_cache
    logo_path = Path(__file__).parent / "assets" / "logo.png"
    if logo_path.exists():
        _logo_cache = logo_path.read_bytes()
    _logo_cache_loaded = True
    return _logo_cache


# ---------------------------------------------------------------------------
# Pure data-fetching functions (testable without HTTP)
# ---------------------------------------------------------------------------


def get_graph_json(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    max_nodes: int = 20000,
    path_prefix: str = "",
    node_types: list[str] | None = None,
) -> dict:
    """Return graph data as a D3-style JSON dict.

    Parameters
    ----------
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for the given project path.
    project_path:
        Filesystem path to the project root.
    max_nodes:
        Maximum number of nodes to include in the response. When the filtered
        graph exceeds this limit the top nodes by degree centrality (hotspots)
        are kept. Pass ``0`` to disable truncation entirely.
    path_prefix:
        When non-empty, only nodes whose ``file_path`` starts with this string
        are included. Nodes with no ``file_path`` are excluded when a prefix is
        specified.
    node_types:
        When non-None and non-empty, only nodes whose ``type`` is in this list
        are included. ``None`` or ``[]`` means no type filtering.

    Raises ``RuntimeError`` when the project has not been initialized.
    """
    graph = ensure_graph_fn(project_path)
    data = graph.to_data()
    total_nodes = len(data.nodes)
    total_edges = len(data.edges)
    truncated = False

    # --- Step 1: Apply server-side filters ---
    filtered = False
    filtered_nodes = dict(data.nodes)

    if path_prefix:
        filtered_nodes = {
            nid: node
            for nid, node in filtered_nodes.items()
            if node.file_path and node.file_path.startswith(path_prefix)
        }
        filtered = True

    if node_types:
        type_set = set(node_types)
        filtered_nodes = {
            nid: node
            for nid, node in filtered_nodes.items()
            if node.type in type_set
        }
        filtered = True

    if filtered:
        kept_ids: set[str] = set(filtered_nodes)
        filtered_edges = [
            e for e in data.edges
            if e.source in kept_ids and e.target in kept_ids
        ]
        data = GraphData(
            nodes=filtered_nodes,
            edges=filtered_edges,
            project_path=data.project_path,
            last_scan=data.last_scan,
            schema_version=data.schema_version,
        )

    # --- Step 2: Apply max_nodes truncation on the (already-filtered) data ---
    if max_nodes > 0 and len(data.nodes) > max_nodes:
        temp_graph = ArchGraph(data)
        hotspots = temp_graph.get_hotspots(top_n=max_nodes)
        kept_ids = {node.id for node, _score in hotspots}
        trunc_nodes = {nid: node for nid, node in data.nodes.items() if nid in kept_ids}
        trunc_edges = [e for e in data.edges if e.source in kept_ids and e.target in kept_ids]
        data = GraphData(
            nodes=trunc_nodes,
            edges=trunc_edges,
            project_path=data.project_path,
            last_scan=data.last_scan,
            schema_version=data.schema_version,
        )
        truncated = True

    result = json.loads(to_d3_json(data))
    result["truncated"] = truncated
    if truncated:
        result["total_nodes"] = total_nodes
        result["total_edges"] = total_edges
    result["unfiltered_total_nodes"] = total_nodes
    result["unfiltered_total_edges"] = total_edges

    return result


def get_node_detail(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    node_id: str,
) -> dict:
    """Return detailed information about a single node and its connected edges."""
    graph = ensure_graph_fn(project_path)
    data = graph.to_data()

    node = data.nodes.get(node_id)
    if node is None:
        return {"error": f"Node '{node_id}' not found"}

    incoming = []
    outgoing = []
    for edge in data.edges:
        if edge.target == node_id:
            incoming.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            })
        if edge.source == node_id:
            outgoing.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "metadata": edge.metadata,
            })

    return {
        "id": node.id,
        "type": node.type,
        "label": node.label,
        "file_path": node.file_path,
        "manual": node.manual,
        "metadata": node.metadata,
        "incoming_edges": incoming,
        "outgoing_edges": outgoing,
    }


def get_subgraph_json(
    ensure_graph_fn: Callable[[str], ArchGraph],
    project_path: str,
    node_id: str,
    depth: int = 2,
) -> dict:
    """Return subgraph data centered on *node_id* up to *depth* hops."""
    graph = ensure_graph_fn(project_path)
    subgraph_data = graph.get_subgraph(node_id, depth=depth)
    return json.loads(to_d3_json(subgraph_data))


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_dashboard_html_cache: str | None = None
_dashboard_html_mtime: float | None = None


def _load_dashboard_html() -> str:
    global _dashboard_html_cache, _dashboard_html_mtime
    template_path = Path(__file__).parent / "dashboard_template.html"
    try:
        mtime = os.path.getmtime(template_path)
    except OSError:
        if _dashboard_html_cache is not None:
            return _dashboard_html_cache
        return "<html><body>Dashboard template not found</body></html>"
    if _dashboard_html_mtime != mtime or _dashboard_html_cache is None:
        _dashboard_html_cache = template_path.read_text(encoding="utf-8")
        _dashboard_html_mtime = mtime
    return _dashboard_html_cache


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_dashboard_routes(
    mcp: Any,
    ensure_graph_fn: Callable[[str], ArchGraph],
    storage: Any,
) -> None:
    """Register the web dashboard HTTP routes on the FastMCP server.

    Parameters
    ----------
    mcp:
        The FastMCP server instance.
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for a given project path.
    storage:
        The active ``StorageBackend`` instance (used to check project existence).
    """

    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard_page(request: Request) -> HTMLResponse:
        """Serve the main dashboard HTML page."""
        return HTMLResponse(_load_dashboard_html())

    @mcp.custom_route("/api/logo", methods=["GET"])
    async def logo_image(request: Request) -> Response:
        """Serve the Code Giraffe logo PNG, or 404 if the file is absent."""
        data = _load_logo_bytes()
        if data is None:
            return Response(content=b"Not Found", status_code=404)
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @mcp.custom_route("/api/init", methods=["POST"])
    async def init_graph(request: Request) -> JSONResponse:
        """Initialize/scan a project so the dashboard can display it."""
        from codegiraffe.scanner import scan_project
        from codegiraffe.graph import ArchGraph, GraphData, Node
        from datetime import datetime, timezone
        import codegiraffe.server as srv

        body = await request.json()
        project_path = body.get("project_path", "")
        if not project_path:
            return JSONResponse({"error": "project_path required"}, status_code=400)
        try:
            result = scan_project(project_path)
            nodes = {node.id: node for node in result.nodes}
            data = GraphData(
                nodes=nodes,
                edges=result.edges,
                project_path=project_path,
                last_scan=datetime.now(timezone.utc).isoformat(),
            )
            graph = ArchGraph(data)
            # Atomically replace _graph and _storage under the server's lock
            # so the MCP-tool thread never sees a torn state.
            with srv._graph_lock:
                storage.save(project_path, graph.to_data())
                srv._graph = graph
                srv._storage = storage
            final = graph.to_data()
            return JSONResponse({
                "status": "ok",
                "nodes": len(final.nodes),
                "edges": len(final.edges),
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/graph", methods=["GET"])
    async def graph_data(request: Request) -> JSONResponse:
        """Return graph data as D3-style JSON for the given project."""
        project_path = request.query_params.get("project_path", "")
        if not project_path:
            return JSONResponse({"error": "project_path query parameter required"}, status_code=400)
        try:
            max_nodes = int(request.query_params.get("max_nodes", "20000"))
        except ValueError:
            max_nodes = 20000

        path_prefix = request.query_params.get("path_prefix", "")
        node_types_raw = request.query_params.get("node_types", "")
        node_types = [t.strip() for t in node_types_raw.split(",") if t.strip()] if node_types_raw else None

        try:
            result = get_graph_json(
                ensure_graph_fn,
                project_path,
                max_nodes=max_nodes,
                path_prefix=path_prefix,
                node_types=node_types,
            )
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/node", methods=["GET"])
    async def node_detail(request: Request) -> JSONResponse:
        """Return detailed information about a single node."""
        project_path = request.query_params.get("project_path", "")
        node_id = request.query_params.get("node_id", "")
        if not project_path or not node_id:
            return JSONResponse({"error": "project_path and node_id query parameters required"}, status_code=400)
        try:
            result = get_node_detail(ensure_graph_fn, project_path, node_id)
            if "error" in result:
                return JSONResponse(result, status_code=404)
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @mcp.custom_route("/api/subgraph", methods=["GET"])
    async def subgraph_data(request: Request) -> JSONResponse:
        """Return a subgraph centered on *node_id*."""
        project_path = request.query_params.get("project_path", "")
        node_id = request.query_params.get("node_id", "")
        if not project_path or not node_id:
            return JSONResponse({"error": "project_path and node_id query parameters required"}, status_code=400)
        depth_str = request.query_params.get("depth", "2")
        try:
            depth = int(depth_str)
        except ValueError:
            depth = 2
        try:
            result = get_subgraph_json(ensure_graph_fn, project_path, node_id, depth)
            return JSONResponse(result)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
