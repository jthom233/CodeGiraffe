"""Tests for the query engine (codegiraffe.query)."""

import pytest
from unittest.mock import patch

from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.query import query_by_node, query_by_text, query_by_type, context_for_task, detect_drift
from codegiraffe.scanner import ScanResult
from codegiraffe.schema import NodeType, EdgeType


class TestQueryByNode:
    """test_query_by_node -- query a specific node, verify subgraph returned."""

    def test_query_by_node(self, sample_graph):
        result = query_by_node(sample_graph, "endpoint:/api/users", depth=1)

        assert isinstance(result, GraphData)
        assert "endpoint:/api/users" in result.nodes

        # Should include direct neighbors
        assert "table:users" in result.nodes
        assert "service:AuthService" in result.nodes

    def test_query_by_node_with_depth(self, sample_graph):
        result = query_by_node(sample_graph, "endpoint:/api/users", depth=2)

        # Should include 2-hop neighbors
        assert "env:DATABASE_URL" in result.nodes

    def test_query_by_node_includes_edges(self, sample_graph):
        result = query_by_node(sample_graph, "endpoint:/api/users", depth=1)

        edge_keys = {(e.source, e.target, e.type) for e in result.edges}
        assert ("endpoint:/api/users", "table:users", EdgeType.READS) in edge_keys


class TestQueryByNodeNotFound:
    """test_query_by_node_not_found -- query nonexistent node,
    verify ValueError with suggestions."""

    def test_query_by_node_not_found(self, sample_graph):
        with pytest.raises(ValueError) as exc_info:
            query_by_node(sample_graph, "endpoint:/api/nonexistent")

        error_msg = str(exc_info.value)
        assert "not found" in error_msg.lower()

    def test_query_by_node_not_found_has_suggestions(self, sample_graph):
        with pytest.raises(ValueError) as exc_info:
            query_by_node(sample_graph, "endpoint:/api/user")

        error_msg = str(exc_info.value)
        # Should suggest the similar node "endpoint:/api/users"
        assert "endpoint:/api/users" in error_msg

    def test_query_by_node_completely_unrelated(self, sample_graph):
        with pytest.raises(ValueError) as exc_info:
            query_by_node(sample_graph, "zzzzzzzzz")

        error_msg = str(exc_info.value)
        assert "not found" in error_msg.lower()


class TestQueryByType:
    """test_query_by_type -- query by type, verify all matching nodes returned."""

    def test_query_by_type_endpoints(self, sample_graph):
        result = query_by_type(sample_graph, NodeType.ENDPOINT)

        assert isinstance(result, GraphData)
        assert "endpoint:/api/users" in result.nodes
        assert "endpoint:/api/payments" in result.nodes

    def test_query_by_type_includes_neighbors(self, sample_graph):
        """Each matching node is expanded to depth=1, so neighbors are included."""
        result = query_by_type(sample_graph, NodeType.ENDPOINT)

        # Neighbors of endpoints should be included
        assert "table:users" in result.nodes
        assert "table:payments" in result.nodes

    def test_query_by_type_no_match(self, sample_graph):
        result = query_by_type(sample_graph, NodeType.CONFIG)

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_query_by_type_single_match(self, sample_graph):
        result = query_by_type(sample_graph, NodeType.WORKER)

        assert "worker:send_email" in result.nodes


class TestContextForTask:
    """test_context_for_task -- give a task string, verify relevant nodes
    are scored and returned."""

    def test_context_for_task_relevant_nodes(self, sample_graph):
        result = context_for_task(sample_graph, "fix the users API endpoint")

        assert isinstance(result, GraphData)
        # "users" and "endpoint" should match nodes
        assert "endpoint:/api/users" in result.nodes

    def test_context_for_task_has_relevance_scores(self, sample_graph):
        result = context_for_task(sample_graph, "fix the users API endpoint")

        for nid, node in result.nodes.items():
            assert "_relevance_score" in node.metadata

    def test_context_for_task_scores_ordered_descending(self, sample_graph):
        result = context_for_task(sample_graph, "fix the users API endpoint")

        scores = [n.metadata["_relevance_score"] for n in result.nodes.values()]
        assert scores == sorted(scores, reverse=True)

    def test_context_for_task_payments_query(self, sample_graph):
        result = context_for_task(sample_graph, "debug the payments processing worker")

        # Should find payments-related and worker-related nodes
        found_ids = set(result.nodes.keys())
        assert "endpoint:/api/payments" in found_ids or "worker:send_email" in found_ids

    def test_context_for_task_empty_query(self, sample_graph):
        result = context_for_task(sample_graph, "")

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 0


class TestContextForTaskMaxNodes:
    """test_context_for_task_max_nodes -- verify max_nodes cap is respected."""

    def test_context_for_task_max_nodes(self, sample_graph):
        result = context_for_task(sample_graph, "users payments email database", max_nodes=3)

        assert isinstance(result, GraphData)
        assert len(result.nodes) <= 3

    def test_context_for_task_max_nodes_one(self, sample_graph):
        result = context_for_task(sample_graph, "users API endpoint", max_nodes=1)

        assert len(result.nodes) <= 1


class TestDetectDriftNoChanges:
    """test_detect_drift_no_changes -- graph matches code, no drift."""

    def test_detect_drift_no_changes(self, sample_project):
        """When the graph exactly matches the scan output, no drift is detected."""
        from codegiraffe.scanner import scan_project as real_scan

        # First, scan the project to get the baseline
        scan_result = real_scan(str(sample_project))

        # Build a graph from the scan result
        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Detect drift -- should find no differences
        drifts = detect_drift(graph, str(sample_project))

        assert isinstance(drifts, list)
        assert len(drifts) == 0


class TestDetectDriftMissingInCode:
    """test_detect_drift_missing_in_code -- delete a file, drift shows missing."""

    def test_detect_drift_missing_in_code(self, sample_project):
        """When a file is removed, its nodes show up as missing_in_code drift."""
        from codegiraffe.scanner import scan_project as real_scan

        # Scan the full project first
        scan_result = real_scan(str(sample_project))

        # Build a graph from the full scan
        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Now delete the tasks file (contains worker:send_email and api:sendgrid)
        tasks_file = sample_project / "tasks.py"
        tasks_file.unlink()

        # Detect drift
        drifts = detect_drift(graph, str(sample_project))

        assert isinstance(drifts, list)
        assert len(drifts) > 0

        drift_types = {d["type"] for d in drifts}
        drift_node_ids = {d["node_id"] for d in drifts}

        # The worker node should be reported as missing in code
        assert "missing_in_code" in drift_types

        # At least the worker node should be flagged
        missing_in_code_ids = {
            d["node_id"] for d in drifts if d["type"] == "missing_in_code"
        }
        assert "worker:send_email" in missing_in_code_ids

    def test_drift_records_have_details(self, sample_project):
        from codegiraffe.scanner import scan_project as real_scan

        scan_result = real_scan(str(sample_project))

        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Delete a file to create drift
        (sample_project / "tasks.py").unlink()

        drifts = detect_drift(graph, str(sample_project))

        for drift in drifts:
            assert "type" in drift
            assert "node_id" in drift
            assert "details" in drift
            assert isinstance(drift["details"], str)
            assert len(drift["details"]) > 0


class TestQueryByText:
    """test_query_by_text -- free-text substring search across node IDs, labels, metadata."""

    def test_query_by_text_matches_label(self, sample_graph):
        result = query_by_text(sample_graph, "users")

        assert isinstance(result, GraphData)
        assert "endpoint:/api/users" in result.nodes
        assert "table:users" in result.nodes

    def test_query_by_text_matches_node_id(self, sample_graph):
        result = query_by_text(sample_graph, "send_email")

        assert "worker:send_email" in result.nodes

    def test_query_by_text_case_insensitive(self, sample_graph):
        result_lower = query_by_text(sample_graph, "auth service")
        result_upper = query_by_text(sample_graph, "AUTH SERVICE")
        result_mixed = query_by_text(sample_graph, "Auth Service")

        for result in (result_lower, result_upper, result_mixed):
            assert "service:AuthService" in result.nodes

    def test_query_by_text_includes_immediate_edges(self, sample_graph):
        result = query_by_text(sample_graph, "send_email")

        # Expand to depth=1 means queue:notifications should appear
        assert "queue:notifications" in result.nodes

    def test_query_by_text_no_match_returns_empty(self, sample_graph):
        result = query_by_text(sample_graph, "zzznomatchzzz")

        assert isinstance(result, GraphData)
        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_query_by_text_with_node_type_filter(self, sample_graph):
        # "users" matches both the endpoint and the table; filtering by ENDPOINT
        # should return only the endpoint node (plus its depth-1 neighbours)
        result = query_by_text(sample_graph, "users", node_type=NodeType.ENDPOINT)

        assert "endpoint:/api/users" in result.nodes
        # The *table* node itself was NOT a query match under this type filter,
        # but it will appear as a depth-1 neighbour of the endpoint
        assert "table:users" in result.nodes
        # The payments endpoint should NOT appear since it doesn't contain "users"
        assert "endpoint:/api/payments" not in result.nodes

    def test_query_by_text_with_node_type_no_overlap(self, sample_graph):
        # Searching for "users" within WORKER type should find nothing
        result = query_by_text(sample_graph, "users", node_type=NodeType.WORKER)

        assert len(result.nodes) == 0

    def test_query_by_text_limit_caps_matched_nodes(self, sample_graph):
        # "a" matches many nodes in the sample graph (at least 4).
        # With limit=2, only 2 nodes are selected as *match roots* before depth-1
        # expansion.  The final graph may be larger (neighbours are included), but
        # querying with limit=2 vs limit=1 must return different (smaller) sets.
        result_limit2 = query_by_text(sample_graph, "a", limit=2)
        result_limit1 = query_by_text(sample_graph, "a", limit=1)

        # Fewer match roots with limit=1 means the result graph should be
        # no larger than with limit=2
        assert len(result_limit1.nodes) <= len(result_limit2.nodes)

    def test_query_by_text_returns_graph_data(self, sample_graph):
        result = query_by_text(sample_graph, "payment")

        assert isinstance(result, GraphData)
        assert "endpoint:/api/payments" in result.nodes

    def test_query_by_text_matches_metadata_value(self, sample_graph):
        # Add a node whose metadata value contains the search term as a substring
        node_with_meta = Node(
            id="service:SecretService",
            type=NodeType.SERVICE,
            label="SecretService",
            metadata={"kind": "ActiveDirectorySecretTemplate"},
        )
        sample_graph.add_node(node_with_meta)

        # "ActiveDirectory" is a substring of the metadata value
        result = query_by_text(sample_graph, "ActiveDirectory")

        assert "service:SecretService" in result.nodes

    def test_query_by_text_matches_metadata_value_case_insensitive(self, sample_graph):
        node_with_meta = Node(
            id="service:SecretService",
            type=NodeType.SERVICE,
            label="SecretService",
            metadata={"kind": "ActiveDirectorySecretTemplate"},
        )
        sample_graph.add_node(node_with_meta)

        result = query_by_text(sample_graph, "activedirectory")

        assert "service:SecretService" in result.nodes


class TestQueryByTextServerIntegration:
    """test_query_by_text_server -- verify codegiraffe_query routes to text search."""

    def test_server_query_routes_to_text_search(self, tmp_path):
        import codegiraffe.server as server_module
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation
        from codegiraffe.server import codegiraffe_init, codegiraffe_query

        # Reset server state
        server_module._graph = None
        server_module._storage = JSONStorage()
        server_module._version_store = VersionStore()
        server_module._federation = GraphFederation()

        # Create a minimal scannable project
        (tmp_path / "app.py").write_text(
            "@app.route('/api/users')\ndef get_users(): pass\n"
        )
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_query(project_path=str(tmp_path), query="users")

        # Result should be JSON (not an error string)
        assert result.startswith("{"), f"Expected JSON, got: {result[:120]}"

    def test_server_query_returns_error_with_no_params(self, tmp_path):
        import codegiraffe.server as server_module
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation
        from codegiraffe.server import codegiraffe_init, codegiraffe_query

        server_module._graph = None
        server_module._storage = JSONStorage()
        server_module._version_store = VersionStore()
        server_module._federation = GraphFederation()

        (tmp_path / "app.py").write_text("pass\n")
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_query(project_path=str(tmp_path))

        assert "error" in result.lower()

    def test_server_blast_radius_with_query(self, tmp_path):
        import codegiraffe.server as server_module
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation
        from codegiraffe.server import codegiraffe_init, codegiraffe_blast_radius

        server_module._graph = None
        server_module._storage = JSONStorage()
        server_module._version_store = VersionStore()
        server_module._federation = GraphFederation()

        (tmp_path / "app.py").write_text(
            "@app.route('/api/users')\ndef get_users(): pass\n"
        )
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_blast_radius(project_path=str(tmp_path), query="users")

        # Should produce a report string, not an error
        assert isinstance(result, str)
        assert "Error" not in result or "no nodes" in result.lower()

    def test_server_blast_radius_no_match_returns_message(self, tmp_path):
        import codegiraffe.server as server_module
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation
        from codegiraffe.server import codegiraffe_init, codegiraffe_blast_radius

        server_module._graph = None
        server_module._storage = JSONStorage()
        server_module._version_store = VersionStore()
        server_module._federation = GraphFederation()

        (tmp_path / "app.py").write_text("pass\n")
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_blast_radius(
            project_path=str(tmp_path), query="zzznomatchzzz"
        )

        assert "no nodes found" in result.lower()

    def test_server_blast_radius_no_params_returns_error(self, tmp_path):
        import codegiraffe.server as server_module
        from codegiraffe.storage import JSONStorage
        from codegiraffe.versioning import VersionStore
        from codegiraffe.federation import GraphFederation
        from codegiraffe.server import codegiraffe_init, codegiraffe_blast_radius

        server_module._graph = None
        server_module._storage = JSONStorage()
        server_module._version_store = VersionStore()
        server_module._federation = GraphFederation()

        (tmp_path / "app.py").write_text("pass\n")
        codegiraffe_init(project_path=str(tmp_path))

        result = codegiraffe_blast_radius(project_path=str(tmp_path))

        assert "error" in result.lower()
