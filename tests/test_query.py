"""Tests for the query engine (codegiraffe.query)."""

import pytest
from unittest.mock import patch

from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.query import (
    query_by_node,
    query_by_text,
    query_by_type,
    context_for_task,
    detect_drift,
    _score_node,
    compute_risk_with_coverage,
    _NODE_TYPE_WEIGHTS,
)
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

        # Should produce a structured dict, not an error dict (or an error about no nodes)
        assert isinstance(result, dict)
        has_match = "target" in result
        no_match = "error" in result and "no nodes found" in result["error"].lower()
        assert has_match or no_match

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

        assert isinstance(result, dict)
        assert "error" in result
        assert "no nodes found" in result["error"].lower()

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

        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# Type-aware node scoring tests
# ---------------------------------------------------------------------------


def _make_node(node_id: str, node_type: str, label: str) -> Node:
    """Build a minimal Node for scoring tests."""
    return Node(id=node_id, type=node_type, label=label)


class TestNodeTypeWeights:
    """_score_node applies _NODE_TYPE_WEIGHTS after keyword counting."""

    def test_service_scores_higher_than_module_same_keywords(self):
        """A service node must outscore a module node with identical keyword matches."""
        keywords = ["auth"]
        service_node = _make_node("service:AuthHelper", NodeType.SERVICE, "AuthHelper")
        module_node = _make_node("mod:AuthHelper", NodeType.MODULE, "AuthHelper")

        service_score = _score_node(service_node, keywords)
        module_score = _score_node(module_node, keywords)

        assert service_score > module_score

    def test_endpoint_scores_higher_than_module_same_keywords(self):
        """An endpoint node must outscore a module node with identical keyword matches."""
        keywords = ["users"]
        endpoint_node = _make_node("endpoint:/api/users", NodeType.ENDPOINT, "users")
        module_node = _make_node("mod:users", NodeType.MODULE, "users")

        endpoint_score = _score_node(endpoint_node, keywords)
        module_score = _score_node(module_node, keywords)

        assert endpoint_score > module_score

    def test_database_table_scores_above_module_below_service(self):
        """A database_table node must score above a module but below a service."""
        keywords = ["payment"]
        service_node = _make_node("service:PaymentService", NodeType.SERVICE, "payment")
        table_node = _make_node("table:payment", NodeType.DATABASE_TABLE, "payment")
        module_node = _make_node("mod:payment", NodeType.MODULE, "payment")

        service_score = _score_node(service_node, keywords)
        table_score = _score_node(table_node, keywords)
        module_score = _score_node(module_node, keywords)

        assert service_score > table_score > module_score

    def test_zero_base_score_remains_zero_after_weight(self):
        """Nodes with no keyword matches stay at 0 regardless of type weight."""
        keywords = ["completely_unrelated_keyword"]
        service_node = _make_node("service:AuthService", NodeType.SERVICE, "AuthService")

        score = _score_node(service_node, keywords)

        assert score == 0.0

    def test_unlisted_type_uses_neutral_weight(self):
        """Node types not in _NODE_TYPE_WEIGHTS get a 1.0x multiplier."""
        keywords = ["queue"]
        queue_node = _make_node("queue:notifications", NodeType.QUEUE, "queue")

        # QUEUE is not in _NODE_TYPE_WEIGHTS, so weight should be 1.0
        assert NodeType.QUEUE not in _NODE_TYPE_WEIGHTS

        score = _score_node(queue_node, keywords)
        # 1 keyword match * 1.0 weight = 1.0
        assert score == pytest.approx(1.0)

    def test_env_var_scores_lower_than_neutral_type(self):
        """env_var type (weight 0.8) scores below unlisted types at same keyword count."""
        keywords = ["database"]
        env_node = _make_node("env:DATABASE_URL", NodeType.ENV_VAR, "database")
        # QUEUE is neutral (1.0x)
        queue_node = _make_node("queue:database_queue", NodeType.QUEUE, "database")

        env_score = _score_node(env_node, keywords)
        queue_score = _score_node(queue_node, keywords)

        assert queue_score > env_score

    def test_context_for_task_service_ranks_above_module(self):
        """Integration: context_for_task returns service nodes ranked above modules."""
        graph = ArchGraph()
        # Both nodes match the keyword "auth" equally on text; service should win
        graph.add_node(_make_node("service:AuthService", NodeType.SERVICE, "auth"))
        graph.add_node(_make_node("mod:auth_module", NodeType.MODULE, "auth"))

        result = context_for_task(graph, "auth", max_nodes=10)

        scores = {
            nid: n.metadata.get("_relevance_score", 0)
            for nid, n in result.nodes.items()
        }
        assert "service:AuthService" in scores
        assert "mod:auth_module" in scores
        assert scores["service:AuthService"] > scores["mod:auth_module"]


# ---------------------------------------------------------------------------
# compute_risk_with_coverage tests (updated semantics)
# ---------------------------------------------------------------------------


class TestRiskCoverageNeutralWhenAbsent:
    """compute_risk_with_coverage uses neutral 1.0x when coverage data is absent."""

    def test_no_coverage_key_returns_neutral(self):
        """When _test_coverage is not in metadata, no penalty is applied."""
        node = _make_node("service:Foo", NodeType.SERVICE, "Foo")
        # No _test_coverage key at all

        result = compute_risk_with_coverage(0.5, node)

        assert result == pytest.approx(0.5)

    def test_coverage_key_zero_applies_penalty(self):
        """When _test_coverage is present and 0.0, the 1.5x penalty is applied."""
        node = _make_node("service:Uncovered", NodeType.SERVICE, "Uncovered")
        node.metadata["_test_coverage"] = 0.0

        result = compute_risk_with_coverage(0.4, node)

        assert result == pytest.approx(0.4 * 1.5)

    def test_coverage_key_above_zero_no_penalty(self):
        """When _test_coverage is present and > 0, no penalty is applied."""
        node = _make_node("service:Covered", NodeType.SERVICE, "Covered")
        node.metadata["_test_coverage"] = 80.0

        result = compute_risk_with_coverage(0.3, node)

        assert result == pytest.approx(0.3)

    def test_multiple_nodes_no_coverage_no_inflation(self):
        """A batch of nodes without coverage keys all receive neutral multipliers."""
        nodes = [
            _make_node(f"service:Svc{i}", NodeType.SERVICE, f"Svc{i}")
            for i in range(5)
        ]
        base_risk = 0.2

        for node in nodes:
            result = compute_risk_with_coverage(base_risk, node)
            assert result == pytest.approx(base_risk), (
                f"Node {node.id} should not be penalised when coverage data is absent"
            )
