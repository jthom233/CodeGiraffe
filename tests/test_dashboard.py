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
        assert "cdn.jsdelivr.net/npm/sigma@3.0.2" in DASHBOARD_HTML

    def test_uses_sigma_layouts(self):
        assert "'original'" in DASHBOARD_HTML or '"original"' in DASHBOARD_HTML

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
        assert "d3ToGraphology" in DASHBOARD_HTML

    def test_no_external_css(self):
        """All styles should be inline -- no <link rel='stylesheet'> tags."""
        assert '<link rel="stylesheet"' not in DASHBOARD_HTML
        assert "<link rel='stylesheet'" not in DASHBOARD_HTML

    # --- New layout tests ---
    def test_contains_seven_sigma_layouts(self):
        """Dashboard should support 7 Sigma-compatible layout names."""
        for layout in ['original', 'force', 'circular', 'grid', 'concentric', 'breadthfirst', 'random']:
            assert f"'{layout}'" in DASHBOARD_HTML or f'"{layout}"' in DASHBOARD_HTML, f"Missing layout: {layout}"

    def test_contains_layouts_array(self):
        """LAYOUTS array should be defined."""
        assert "LAYOUTS" in DASHBOARD_HTML

    def test_layout_cycle_handler(self):
        """Layout button should cycle through layouts and call Sigma layout functions."""
        assert "LAYOUTS.length" in DASHBOARD_HTML
        assert "applyForceLayout" in DASHBOARD_HTML
        assert "applyCircularLayout" in DASHBOARD_HTML
        assert "applyGridLayout" in DASHBOARD_HTML
        assert "applyConcentricLayout" in DASHBOARD_HTML
        assert "applyBreadthfirstLayout" in DASHBOARD_HTML
        assert "applyRandomLayout" in DASHBOARD_HTML
        assert "applyOriginalLayout" in DASHBOARD_HTML

    # --- Edge tooltip tests ---
    def test_contains_edge_tooltip(self):
        """Edge tooltip div should exist."""
        assert 'id="edge-tooltip"' in DASHBOARD_HTML

    def test_edge_tooltip_mouseover(self):
        """Edge mouseover handler should be defined."""
        assert "mouseover" in DASHBOARD_HTML
        assert "edge-tooltip" in DASHBOARD_HTML

    def test_edge_highlighted_style(self):
        """Highlighted edge style should be defined."""
        assert "highlighted" in DASHBOARD_HTML

    # --- Legend tests ---
    def test_contains_legend_section(self):
        """Legend section should exist in sidebar."""
        assert 'id="legend"' in DASHBOARD_HTML

    def test_contains_build_legend(self):
        """buildLegend function should be defined."""
        assert "buildLegend" in DASHBOARD_HTML

    def test_legend_has_swatch_styles(self):
        """Legend CSS classes should be defined."""
        assert "legend-swatch" in DASHBOARD_HTML
        assert "legend-line" in DASHBOARD_HTML

    # --- Enhanced stats tests ---
    def test_contains_avg_degree_stat(self):
        """Average degree stat should exist."""
        assert 'id="stat-avg-degree"' in DASHBOARD_HTML

    def test_contains_components_stat(self):
        """Connected components stat should exist."""
        assert 'id="stat-components"' in DASHBOARD_HTML

    def test_contains_type_distribution(self):
        """Type distribution chart container should exist."""
        assert 'id="type-distribution"' in DASHBOARD_HTML

    # --- Color palette tests ---
    def test_module_color_differentiated(self):
        """Module color should be #D35400 (differentiated from queue)."""
        assert "#D35400" in DASHBOARD_HTML

    def test_config_color_differentiated(self):
        """Config color should be #D4AC0D (differentiated from env_var)."""
        assert "#D4AC0D" in DASHBOARD_HTML

    def test_contains_server_filters_section(self):
        assert 'id="path-prefix-input"' in DASHBOARD_HTML

    def test_contains_path_prefix_input(self):
        assert 'id="path-prefix-input"' in DASHBOARD_HTML

    def test_contains_max_nodes_input(self):
        assert 'id="max-nodes-input"' in DASHBOARD_HTML

    def test_contains_apply_server_filters_button(self):
        assert 'id="apply-server-filters"' in DASHBOARD_HTML

    def test_contains_truncation_banner(self):
        assert 'id="truncation-banner"' in DASHBOARD_HTML

    def test_api_url_includes_max_nodes(self):
        assert "max_nodes" in DASHBOARD_HTML

    def test_api_url_includes_path_prefix(self):
        assert "path_prefix" in DASHBOARD_HTML


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

    def test_no_truncation_flag_when_under_limit(self, arch_graph):
        """truncated=False is present when node count is within max_nodes."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=500)
        assert result["truncated"] is False

    def test_truncation_reduces_node_count(self, arch_graph):
        """When max_nodes < total nodes, only max_nodes nodes are returned."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=2)
        assert len(result["nodes"]) <= 2

    def test_truncation_flag_set_true(self, arch_graph):
        """truncated=True is present when graph is truncated."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=2)
        assert result["truncated"] is True

    def test_truncation_preserves_total_counts(self, arch_graph):
        """total_nodes and total_edges reflect the original untruncated graph."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=2)
        assert result["total_nodes"] == 5
        assert result["total_edges"] == 5

    def test_truncation_drops_dangling_edges(self, arch_graph):
        """Edges referencing dropped nodes are removed."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=2)
        kept_ids = {n["id"] for n in result["nodes"]}
        for link in result["links"]:
            assert link["source"] in kept_ids
            assert link["target"] in kept_ids

    def test_max_nodes_zero_disables_truncation(self, arch_graph):
        """max_nodes=0 disables truncation regardless of graph size."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=0)
        assert result["truncated"] is False
        assert len(result["nodes"]) == 5
        assert len(result["links"]) == 5

    def test_no_truncation_when_exactly_at_limit(self, arch_graph):
        """max_nodes equal to node count causes no truncation."""
        result = get_graph_json(_make_ensure_fn(arch_graph), "/tmp/test-project", max_nodes=5)
        assert result["truncated"] is False
        assert len(result["nodes"]) == 5


# ---------------------------------------------------------------------------
# get_graph_json filtering tests
# ---------------------------------------------------------------------------


class TestGetGraphJsonFiltering:
    """Test path_prefix and node_types filtering in get_graph_json."""

    def _make_ensure_fn(self, graph):
        def ensure(path):
            return graph
        return ensure

    def _make_graph(self):
        """Build a small test graph with nodes across different paths and types."""
        from codegiraffe.graph import ArchGraph, GraphData, Node, Edge
        nodes = {
            "svc:auth": Node(id="svc:auth", type="service", label="AuthService", file_path="auth/service.py"),
            "ep:login": Node(id="ep:login", type="endpoint", label="/login", file_path="auth/routes.py"),
            "db:users": Node(id="db:users", type="database_table", label="users", file_path="auth/models.py"),
            "svc:billing": Node(id="svc:billing", type="service", label="BillingService", file_path="billing/service.py"),
            "q:emails": Node(id="q:emails", type="queue", label="emails", file_path=None),
        }
        edges = [
            Edge(source="ep:login", target="svc:auth", type="calls"),
            Edge(source="svc:auth", target="db:users", type="calls"),
            Edge(source="svc:billing", target="q:emails", type="calls"),
        ]
        data = GraphData(nodes=nodes, edges=edges, project_path="/tmp/test-project")
        return ArchGraph(data)

    def test_path_prefix_filters_nodes(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", path_prefix="auth/")
        for node in result["nodes"]:
            assert node["file_path"] is not None
            assert node["file_path"].startswith("auth/")

    def test_path_prefix_excludes_none_file_path(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", path_prefix="auth/")
        node_ids = {n["id"] for n in result["nodes"]}
        assert "q:emails" not in node_ids

    def test_path_prefix_drops_dangling_edges(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", path_prefix="auth/")
        kept_ids = {n["id"] for n in result["nodes"]}
        for link in result["links"]:
            assert link["source"] in kept_ids
            assert link["target"] in kept_ids

    def test_node_types_filter(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", node_types=["service", "endpoint"])
        for node in result["nodes"]:
            assert node["type"] in {"service", "endpoint"}

    def test_node_types_empty_list_no_filter(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", node_types=[])
        assert len(result["nodes"]) == 5

    def test_node_types_none_no_filter(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project", node_types=None)
        assert len(result["nodes"]) == 5

    def test_combined_path_prefix_and_node_types(self):
        graph = self._make_graph()
        result = get_graph_json(
            self._make_ensure_fn(graph), "/tmp/test-project",
            path_prefix="auth/", node_types=["endpoint"]
        )
        for node in result["nodes"]:
            assert node["file_path"] is not None
            assert node["file_path"].startswith("auth/")
            assert node["type"] == "endpoint"

    def test_filter_then_truncation(self):
        graph = self._make_graph()
        # auth/ has 3 nodes; cap at 2
        result = get_graph_json(
            self._make_ensure_fn(graph), "/tmp/test-project",
            path_prefix="auth/", max_nodes=2
        )
        assert len(result["nodes"]) <= 2
        assert result["truncated"] is True

    def test_unfiltered_total_always_present(self):
        graph = self._make_graph()
        result = get_graph_json(self._make_ensure_fn(graph), "/tmp/test-project")
        assert "unfiltered_total_nodes" in result
        assert result["unfiltered_total_nodes"] == 5

    def test_unfiltered_total_reflects_full_graph(self):
        graph = self._make_graph()
        result = get_graph_json(
            self._make_ensure_fn(graph), "/tmp/test-project", path_prefix="auth/"
        )
        assert result["unfiltered_total_nodes"] == 5
        assert len(result["nodes"]) < 5

    def test_no_match_returns_empty(self):
        graph = self._make_graph()
        result = get_graph_json(
            self._make_ensure_fn(graph), "/tmp/test-project",
            path_prefix="nonexistent/path/"
        )
        assert len(result["nodes"]) == 0
        assert len(result["links"]) == 0
        assert result["truncated"] is False


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


# ---------------------------------------------------------------------------
# Sigma.js dashboard HTML assertions (TDD RED phase — T013)
# These tests define the EXPECTED Sigma.js implementation. They will FAIL
# until T014 replaces the Cytoscape.js template with Sigma.js.
# ---------------------------------------------------------------------------


class TestSigmaDashboardHTML:
    """Assert that DASHBOARD_HTML uses Sigma.js instead of Cytoscape.js."""

    # --- CDN presence / absence ---

    def test_sigma_cdn_present(self):
        """Sigma v3.0.2 CDN script tag must be included."""
        assert "cdn.jsdelivr.net/npm/sigma@3.0.2" in DASHBOARD_HTML

    def test_graphology_cdn_present(self):
        """graphology v0.26.0 CDN script tag must be included."""
        assert "cdn.jsdelivr.net/npm/graphology@0.26.0" in DASHBOARD_HTML

    def test_cytoscape_cdn_absent(self):
        """Cytoscape CDN must be removed when migrating to Sigma.js."""
        assert "cytoscape" not in DASHBOARD_HTML.lower()

    # --- Sigma.js API usage ---

    def test_sigma_instantiation_present(self):
        """Dashboard must instantiate a Sigma renderer with `new Sigma(`."""
        assert "new Sigma(" in DASHBOARD_HTML

    def test_graphology_graph_instantiation_present(self):
        """Dashboard must create a graphology graph with `new graphology.Graph(`."""
        assert "new graphology.Graph(" in DASHBOARD_HTML

    def test_node_reducer_present(self):
        """Sigma nodeReducer must be configured for node styling."""
        assert "nodeReducer" in DASHBOARD_HTML

    def test_edge_reducer_present(self):
        """Sigma edgeReducer must be configured for edge styling."""
        assert "edgeReducer" in DASHBOARD_HTML

    # --- Event handlers ---

    def test_click_node_event_present(self):
        """clickNode event handler must be registered on the Sigma instance."""
        assert "clickNode" in DASHBOARD_HTML

    def test_enter_edge_event_present(self):
        """enterEdge event handler must be registered for edge tooltips."""
        assert "enterEdge" in DASHBOARD_HTML

    # --- URL / auto-load ---

    def test_url_search_params_present(self):
        """URLSearchParams usage must be present for auto-loading from URL."""
        assert "URLSearchParams" in DASHBOARD_HTML

    # --- UI elements ---

    def test_search_box_present(self):
        """Search box element must exist in the HTML."""
        assert 'id="search-box"' in DASHBOARD_HTML

    def test_path_prefix_input_present(self):
        """Path prefix input element must exist in the HTML."""
        assert 'id="path-prefix-input"' in DASHBOARD_HTML

    def test_detail_panel_present(self):
        """Detail panel element must exist in the HTML."""
        assert 'id="detail-panel"' in DASHBOARD_HTML

    def test_apply_server_filters_button_present(self):
        """Apply server filters button must exist in the HTML."""
        assert 'id="apply-server-filters"' in DASHBOARD_HTML

    def test_escape_html_function_present(self):
        """escapeHtml function must be present for XSS protection."""
        assert "escapeHtml" in DASHBOARD_HTML

    def test_export_button_present(self):
        """Export button must exist in the HTML."""
        assert 'id="btn-export"' in DASHBOARD_HTML

    def test_png_export_api_present(self):
        """PNG export must use toDataURL or getCanvas from the Sigma renderer."""
        assert "toDataURL" in DASHBOARD_HTML or "getCanvas" in DASHBOARD_HTML
