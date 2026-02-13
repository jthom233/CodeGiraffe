"""Tests for the Code Giraffe web dashboard module.

Verifies the pure data-fetching functions, route registration, and HTML
template integrity without requiring a running HTTP server.
"""

from __future__ import annotations

import json

import pytest

from codegiraffe.dashboard import (
    DASHBOARD_HTML,
    get_graph_json,
    get_node_detail,
    get_subgraph_json,
    register_dashboard_routes,
)
from codegiraffe.graph import ArchGraph, Edge, GraphData, Node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_graph_data() -> GraphData:
    """Build a small but realistic architecture graph for testing."""
    return GraphData(
        project_path="/tmp/test-project",
        last_scan="2025-01-01T00:00:00Z",
        schema_version="1.0",
        nodes={
            "svc:auth": Node(
                id="svc:auth", type="service", label="Auth Service",
                file_path="auth/main.py", metadata={"port": 8080},
            ),
            "ep:login": Node(
                id="ep:login", type="endpoint", label="POST /login",
                file_path="auth/routes.py",
            ),
            "db:users": Node(
                id="db:users", type="database_table", label="users",
                file_path="auth/models.py",
            ),
            "q:emails": Node(
                id="q:emails", type="queue", label="email-queue",
                metadata={"broker": "rabbitmq"},
            ),
            "ev:user_created": Node(
                id="ev:user_created", type="event", label="UserCreated",
            ),
        },
        edges=[
            Edge(source="svc:auth", target="ep:login", type="exposes"),
            Edge(source="ep:login", target="db:users", type="reads"),
            Edge(source="ep:login", target="q:emails", type="publishes_to"),
            Edge(source="q:emails", target="ev:user_created", type="emits"),
            Edge(source="svc:auth", target="db:users", type="owns"),
        ],
    )


@pytest.fixture()
def arch_graph(sample_graph_data: GraphData) -> ArchGraph:
    """Create an ArchGraph from sample data."""
    return ArchGraph(sample_graph_data)


def _make_ensure_fn(graph: ArchGraph):
    """Return an ensure_graph function that always returns *graph*."""
    def ensure(project_path: str) -> ArchGraph:
        return graph
    return ensure


def _make_failing_ensure_fn():
    """Return an ensure_graph function that always raises RuntimeError."""
    def ensure(project_path: str) -> ArchGraph:
        raise RuntimeError(f"No architecture graph found for '{project_path}'.")
    return ensure


# ---------------------------------------------------------------------------
# HTML template tests
# ---------------------------------------------------------------------------


class TestDashboardHTML:
    """Verify the embedded HTML template contains required elements."""

    def test_html_is_nonempty_string(self):
        assert isinstance(DASHBOARD_HTML, str)
        assert len(DASHBOARD_HTML) > 1000

    def test_contains_doctype(self):
        assert "<!DOCTYPE html>" in DASHBOARD_HTML

    def test_contains_cytoscape_cdn(self):
        assert "cytoscape/3.30.4/cytoscape.min.js" in DASHBOARD_HTML

    def test_contains_cose_bilkent_cdn(self):
        assert "cytoscape-cose-bilkent/4.1.0/cytoscape-cose-bilkent.min.js" in DASHBOARD_HTML

    def test_contains_sidebar(self):
        assert 'id="sidebar"' in DASHBOARD_HTML

    def test_contains_cytoscape_container(self):
        assert 'id="cy"' in DASHBOARD_HTML

    def test_contains_detail_panel(self):
        assert 'id="detail-panel"' in DASHBOARD_HTML

    def test_contains_search_box(self):
        assert 'id="search-box"' in DASHBOARD_HTML

    def test_contains_project_path_input(self):
        assert 'id="project-path"' in DASHBOARD_HTML

    def test_contains_toolbar_buttons(self):
        assert 'id="btn-fit"' in DASHBOARD_HTML
        assert 'id="btn-export"' in DASHBOARD_HTML
        assert 'id="btn-layout"' in DASHBOARD_HTML

    def test_contains_dark_theme(self):
        assert "#1a1a2e" in DASHBOARD_HTML

    def test_contains_d3_to_cytoscape_converter(self):
        assert "d3ToCytoscape" in DASHBOARD_HTML

    def test_no_external_css(self):
        """All styles should be inline -- no <link rel='stylesheet'> tags."""
        assert '<link rel="stylesheet"' not in DASHBOARD_HTML
        assert "<link rel='stylesheet'" not in DASHBOARD_HTML


# ---------------------------------------------------------------------------
# get_graph_json tests
# ---------------------------------------------------------------------------


class TestGetGraphJson:
    """Test the get_graph_json pure function."""

    def test_returns_dict_with_nodes_links_metadata(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        assert "nodes" in result
        assert "links" in result
        assert "metadata" in result

    def test_node_count_matches(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        assert len(result["nodes"]) == 5

    def test_edge_count_matches(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        assert len(result["links"]) == 5

    def test_node_structure(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        node = next(n for n in result["nodes"] if n["id"] == "svc:auth")
        assert node["type"] == "service"
        assert node["label"] == "Auth Service"
        assert node["file_path"] == "auth/main.py"
        assert node["metadata"] == {"port": 8080}

    def test_link_structure(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        link = next(l for l in result["links"] if l["source"] == "svc:auth" and l["target"] == "ep:login")
        assert link["type"] == "exposes"

    def test_metadata_section(self, arch_graph):
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project")
        assert result["metadata"]["node_count"] == 5
        assert result["metadata"]["edge_count"] == 5
        assert result["metadata"]["project_path"] == "/tmp/test-project"

    def test_raises_on_missing_project(self):
        with pytest.raises(RuntimeError, match="No architecture graph"):
            get_graph_json(_make_failing_ensure_fn(), "/nonexistent")


# ---------------------------------------------------------------------------
# get_node_detail tests
# ---------------------------------------------------------------------------


class TestGetNodeDetail:
    """Test the get_node_detail pure function."""

    def test_returns_node_info(self, arch_graph):
        result = get_node_detail(_make_ensure_fn(arch_graph), "/tmp/test", "svc:auth")
        assert result["id"] == "svc:auth"
        assert result["type"] == "service"
        assert result["label"] == "Auth Service"
        assert result["file_path"] == "auth/main.py"

    def test_includes_metadata(self, arch_graph):
        result = get_node_detail(_make_ensure_fn(arch_graph), "/tmp/test", "svc:auth")
        assert result["metadata"] == {"port": 8080}

    def test_includes_outgoing_edges(self, arch_graph):
        result = get_node_detail(_make_ensure_fn(arch_graph), "/tmp/test", "svc:auth")
        assert len(result["outgoing_edges"]) == 2  # exposes + owns
        out_types = {e["type"] for e in result["outgoing_edges"]}
        assert "exposes" in out_types
        assert "owns" in out_types

    def test_includes_incoming_edges(self, arch_graph):
        result = get_node_detail(_make_ensure_fn(arch_graph), "/tmp/test", "ep:login")
        assert len(result["incoming_edges"]) == 1
        assert result["incoming_edges"][0]["source"] == "svc:auth"
        assert result["incoming_edges"][0]["type"] == "exposes"

    def test_node_with_no_edges(self):
        """A node with no connections should return empty edge lists."""
        data = GraphData(
            project_path="/tmp/p",
            nodes={"lonely": Node(id="lonely", type="service", label="Alone")},
            edges=[],
        )
        graph = ArchGraph(data)
        result = get_node_detail(_make_ensure_fn(graph), "/tmp/p", "lonely")
        assert result["incoming_edges"] == []
        assert result["outgoing_edges"] == []

    def test_missing_node_returns_error(self, arch_graph):
        result = get_node_detail(_make_ensure_fn(arch_graph), "/tmp/test", "nonexistent")
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_manual_flag(self):
        data = GraphData(
            project_path="/tmp/p",
            nodes={"m": Node(id="m", type="service", label="Manual", manual=True)},
            edges=[],
        )
        graph = ArchGraph(data)
        result = get_node_detail(_make_ensure_fn(graph), "/tmp/p", "m")
        assert result["manual"] is True


# ---------------------------------------------------------------------------
# get_subgraph_json tests
# ---------------------------------------------------------------------------


class TestGetSubgraphJson:
    """Test the get_subgraph_json pure function."""

    def test_returns_subgraph_centered_on_node(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "ep:login", depth=1)
        node_ids = {n["id"] for n in result["nodes"]}
        # ep:login at depth 0, neighbors at depth 1
        assert "ep:login" in node_ids
        assert "svc:auth" in node_ids  # connected via 'exposes'
        assert "db:users" in node_ids  # connected via 'reads'
        assert "q:emails" in node_ids  # connected via 'publishes_to'

    def test_depth_zero_returns_only_center(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "ep:login", depth=0)
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"ep:login"}

    def test_depth_limits_reach(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "svc:auth", depth=1)
        node_ids = {n["id"] for n in result["nodes"]}
        # svc:auth -> ep:login, svc:auth -> db:users (depth 1)
        assert "svc:auth" in node_ids
        assert "ep:login" in node_ids
        assert "db:users" in node_ids
        # q:emails is 2 hops away from svc:auth, should NOT be included
        assert "q:emails" not in node_ids

    def test_large_depth_returns_full_graph(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "svc:auth", depth=10)
        assert len(result["nodes"]) == 5  # all nodes reachable

    def test_nonexistent_center_returns_empty(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "ghost", depth=2)
        assert len(result["nodes"]) == 0

    def test_includes_edges_within_subgraph(self, arch_graph):
        result = get_subgraph_json(_make_ensure_fn(arch_graph), "/tmp/test", "ep:login", depth=1)
        link_pairs = {(l["source"], l["target"]) for l in result["links"]}
        assert ("svc:auth", "ep:login") in link_pairs
        assert ("ep:login", "db:users") in link_pairs

    def test_raises_on_missing_project(self):
        with pytest.raises(RuntimeError, match="No architecture graph"):
            get_subgraph_json(_make_failing_ensure_fn(), "/nonexistent", "x", depth=2)


# ---------------------------------------------------------------------------
# register_dashboard_routes tests
# ---------------------------------------------------------------------------


class TestRegisterRoutes:
    """Test that route registration succeeds without errors."""

    def test_register_does_not_crash(self):
        from mcp.server.fastmcp import FastMCP
        test_mcp = FastMCP("test-dashboard")
        ensure_fn = _make_failing_ensure_fn()
        # Should not raise
        register_dashboard_routes(test_mcp, ensure_fn, None)

    def test_routes_registered(self):
        from mcp.server.fastmcp import FastMCP
        test_mcp = FastMCP("test-dashboard-routes")
        register_dashboard_routes(test_mcp, _make_failing_ensure_fn(), None)
        route_paths = [r.path for r in test_mcp._custom_starlette_routes]
        assert "/dashboard" in route_paths
        assert "/api/graph" in route_paths
        assert "/api/node" in route_paths
        assert "/api/subgraph" in route_paths
