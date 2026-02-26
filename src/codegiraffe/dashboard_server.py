"""Standalone dashboard server for Code Giraffe.

Runs a Starlette/uvicorn HTTP server in a daemon background thread, isolated
from the main thread's anyio event loop used by the MCP stdio transport.
The server exposes the same dashboard routes as ``dashboard.py`` but runs
independently so it persists for the lifetime of the MCP process.

Usage::

    from codegiraffe.dashboard_server import get_or_start_server
    server = get_or_start_server(ensure_graph_fn, storage)
    print(server.url("/path/to/project"))
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Port probe helper
# ---------------------------------------------------------------------------


def _is_port_free(port: int) -> bool:
    """Return True if *port* is not currently bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _find_free_port(start: int = 8251, attempts: int = 5) -> int:
    """Return the first free port in [start, start+attempts)."""
    for port in range(start, start + attempts):
        if _is_port_free(port):
            return port
    raise OSError(
        f"No free port found in range {start}-{start + attempts - 1}. "
        "Kill any existing dashboard processes and try again."
    )


# ---------------------------------------------------------------------------
# DashboardServer
# ---------------------------------------------------------------------------


class DashboardServer:
    """A Starlette/uvicorn HTTP server running on a daemon background thread.

    Parameters
    ----------
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for a given project path.
    storage:
        The active ``StorageBackend`` instance.
    port:
        Local port to bind the HTTP server on (default 8251).
    """

    def __init__(
        self,
        ensure_graph_fn: Callable[[str], Any],
        storage: Any,
        port: int = 8251,
    ) -> None:
        self._ensure_graph_fn = ensure_graph_fn
        self._storage = storage
        self._port = port
        self._thread: threading.Thread | None = None
        self._uvicorn_server: Any = None  # uvicorn.Server instance
        self._ready_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def url(self, project_path: str) -> str:
        """Return the full dashboard URL for *project_path*."""
        from urllib.parse import quote as _url_quote

        encoded = _url_quote(project_path, safe="")
        return f"http://localhost:{self._port}/dashboard?project_path={encoded}"

    def start(self, timeout: float = 5.0) -> None:
        """Start the uvicorn server in a daemon thread.

        Blocks until the server is ready to accept connections or *timeout*
        seconds have elapsed.

        Raises
        ------
        RuntimeError
            If the server fails to start within *timeout* seconds.
        """
        if self.is_running:
            return

        self._ready_event.clear()

        app = self._build_app()

        import uvicorn

        # Configure uvicorn to be completely silent on stdout.
        # All log output goes to stderr via the logging module.
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self._port,
            access_log=False,
            log_level="warning",
        )

        # Redirect uvicorn loggers to stderr only (never stdout).
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uv_logger = logging.getLogger(name)
            uv_logger.handlers = []
            handler = logging.StreamHandler()  # defaults to sys.stderr
            handler.setLevel(logging.WARNING)
            uv_logger.addHandler(handler)
            uv_logger.propagate = False

        server = uvicorn.Server(config)
        self._uvicorn_server = server

        ready_event = self._ready_event

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _serve() -> None:
                # Install the startup hook to signal readiness.
                original_startup = server.startup

                async def _startup_with_signal(sockets=None) -> None:  # type: ignore[override]
                    await original_startup(sockets=sockets)
                    ready_event.set()

                server.startup = _startup_with_signal  # type: ignore[method-assign]
                await server.serve()

            try:
                loop.run_until_complete(_serve())
            except Exception as exc:
                logger.warning("Dashboard server error: %s", exc)
                ready_event.set()  # unblock caller even on failure
            finally:
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True, name="codegiraffe-dashboard")
        self._thread.start()

        if not self._ready_event.wait(timeout=timeout):
            raise RuntimeError(
                f"Dashboard server did not start within {timeout}s on port {self._port}."
            )

        if not self.is_running:
            raise RuntimeError(
                f"Dashboard server thread died unexpectedly on port {self._port}."
            )

    def stop(self) -> None:
        """Gracefully stop the server and join the thread."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
            self._uvicorn_server = None

    # ------------------------------------------------------------------
    # Starlette app construction
    # ------------------------------------------------------------------

    def _build_app(self) -> Any:
        """Build and return a Starlette ASGI application with dashboard routes."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import HTMLResponse, JSONResponse, Response
        from starlette.routing import Route

        from codegiraffe.dashboard import (
            DASHBOARD_HTML,
            _load_logo_bytes,
            get_graph_json,
            get_node_detail,
            get_subgraph_json,
        )

        ensure_graph_fn = self._ensure_graph_fn
        storage = self._storage

        async def dashboard_page(request: Request) -> HTMLResponse:
            return HTMLResponse(DASHBOARD_HTML)

        async def init_graph(request: Request) -> JSONResponse:
            """Initialize/scan a project so the dashboard can display it.

            Security: only paths that have previously been initialized via the
            MCP tool ``codegiraffe_init`` are permitted.  Unknown paths receive
            a 403 to prevent arbitrary filesystem traversal via the dashboard.
            """
            import codegiraffe.server as srv
            from codegiraffe.graph import ArchGraph, GraphData, Node  # noqa: F401
            from codegiraffe.scanner import scan_project

            body = await request.json()
            project_path = body.get("project_path", "")
            if not project_path:
                return JSONResponse({"error": "project_path required"}, status_code=400)

            # Path allowlist check — reject paths not approved by codegiraffe_init.
            # Normalize via resolve() to prevent symlink/relative-path bypasses.
            normalized_path = str(Path(project_path).resolve())
            if normalized_path not in srv._initialized_project_paths:
                return JSONResponse(
                    {"error": (
                        f"Path '{project_path}' is not in the initialized project allowlist. "
                        "Run codegiraffe_init first via the MCP tool."
                    )},
                    status_code=403,
                )

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

        # NOTE: This handler mirrors the graph_data handler in dashboard.py.
        # Any changes to parameters or logic must be applied to both files.
        async def graph_data(request: Request) -> JSONResponse:
            project_path = request.query_params.get("project_path", "")
            if not project_path:
                return JSONResponse(
                    {"error": "project_path query parameter required"}, status_code=400
                )
            try:
                max_nodes = int(request.query_params.get("max_nodes", "500"))
            except ValueError:
                max_nodes = 500

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

        async def node_detail(request: Request) -> JSONResponse:
            project_path = request.query_params.get("project_path", "")
            node_id = request.query_params.get("node_id", "")
            if not project_path or not node_id:
                return JSONResponse(
                    {"error": "project_path and node_id query parameters required"},
                    status_code=400,
                )
            try:
                result = get_node_detail(ensure_graph_fn, project_path, node_id)
                if "error" in result:
                    return JSONResponse(result, status_code=404)
                return JSONResponse(result)
            except RuntimeError as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)
            except Exception as exc:
                return JSONResponse({"error": str(exc)}, status_code=500)

        async def subgraph_data(request: Request) -> JSONResponse:
            project_path = request.query_params.get("project_path", "")
            node_id = request.query_params.get("node_id", "")
            if not project_path or not node_id:
                return JSONResponse(
                    {"error": "project_path and node_id query parameters required"},
                    status_code=400,
                )
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

        async def logo_image(request: Request) -> Response:
            data = _load_logo_bytes()
            if data is None:
                return Response(content=b"Not Found", status_code=404)
            return Response(
                content=data,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )

        routes = [
            Route("/dashboard", endpoint=dashboard_page, methods=["GET"]),
            Route("/api/logo", endpoint=logo_image, methods=["GET"]),
            Route("/api/init", endpoint=init_graph, methods=["POST"]),
            Route("/api/graph", endpoint=graph_data, methods=["GET"]),
            Route("/api/node", endpoint=node_detail, methods=["GET"]),
            Route("/api/subgraph", endpoint=subgraph_data, methods=["GET"]),
        ]

        return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_server: DashboardServer | None = None
_server_lock = threading.Lock()


def get_or_start_server(
    ensure_graph_fn: Callable[[str], Any],
    storage: Any,
    port: int = 8251,
) -> DashboardServer:
    """Return the running singleton server, starting it if necessary.

    If the requested *port* is already bound by another process, the next
    free port in the range 8251-8255 is tried automatically.

    Parameters
    ----------
    ensure_graph_fn:
        Callable that loads/returns an ``ArchGraph`` for a given project path.
    storage:
        The active ``StorageBackend`` instance.
    port:
        Preferred port for the dashboard HTTP server (default 8251).

    Returns
    -------
    DashboardServer
        The running server instance.
    """
    global _server  # noqa: PLW0603

    with _server_lock:
        if _server is not None and _server.is_running:
            return _server

        try:
            # Find a free port starting from the requested one.
            actual_port = _find_free_port(start=port, attempts=5)
            server = DashboardServer(
                ensure_graph_fn=ensure_graph_fn,
                storage=storage,
                port=actual_port,
            )
            server.start(timeout=5.0)
        except Exception as exc:
            logger.warning("Failed to start dashboard server: %s", exc)
            # Return the (non-running) server object so callers can still
            # call server.url() for informational purposes.
            if 'server' not in locals():
                server = DashboardServer(
                    ensure_graph_fn=ensure_graph_fn,
                    storage=storage,
                    port=port,
                )
            _server = server
            return _server

        _server = server
        logger.debug("Dashboard server started on port %d", actual_port)
        return _server
