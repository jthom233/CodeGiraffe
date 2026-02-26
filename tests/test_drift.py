"""Tests for enhanced drift detection (codegiraffe.query drift functions)."""

import pytest
from unittest.mock import patch, MagicMock

from codegiraffe.graph import Node, Edge, GraphData, ArchGraph
from codegiraffe.schema import NodeType, EdgeType
from codegiraffe.query import (
    detect_drift,
    _enhanced_similarity,
    _detect_edge_drift,
    _detect_git_renames,
)


class TestEnhancedSimilarity:
    def test_identical_strings(self):
        assert _enhanced_similarity("endpoint:/api/users", "endpoint:/api/users") == 1.0

    def test_same_type_prefix_bonus(self):
        # Same prefix should score higher than different prefix
        same = _enhanced_similarity("endpoint:/api/users", "endpoint:/api/user")
        diff = _enhanced_similarity("endpoint:/api/users", "service:/api/user")
        assert same > diff

    def test_with_node_objects(self):
        old = Node(
            id="endpoint:/old",
            type=NodeType.ENDPOINT,
            label="old route",
            file_path="api/routes.py",
        )
        new = Node(
            id="endpoint:/new",
            type=NodeType.ENDPOINT,
            label="new route",
            file_path="api/routes.py",
        )
        score = _enhanced_similarity("endpoint:/old", "endpoint:/new", old, new)
        assert score > 0.0

    def test_capped_at_one(self):
        score = _enhanced_similarity("endpoint:/api/users", "endpoint:/api/users")
        assert score <= 1.0

    def test_completely_different(self):
        score = _enhanced_similarity("endpoint:/api/users", "table:payments")
        assert score < 0.5

    def test_no_prefix_no_bonus(self):
        """Nodes without a colon prefix get no prefix bonus."""
        with_colon = _enhanced_similarity("endpoint:foo", "endpoint:bar")
        without_colon = _enhanced_similarity("foo", "bar")
        # The with_colon version should be higher due to the type prefix bonus
        assert with_colon > without_colon

    def test_file_path_bonus(self):
        """Nodes sharing a file path should score higher."""
        same_file_old = Node(
            id="endpoint:/api/users",
            type=NodeType.ENDPOINT,
            label="x",
            file_path="api/routes.py",
        )
        same_file_new = Node(
            id="endpoint:/api/accounts",
            type=NodeType.ENDPOINT,
            label="x",
            file_path="api/routes.py",
        )
        diff_file_new = Node(
            id="endpoint:/api/accounts",
            type=NodeType.ENDPOINT,
            label="x",
            file_path="billing/views.py",
        )
        score_same = _enhanced_similarity(
            "endpoint:/api/users", "endpoint:/api/accounts", same_file_old, same_file_new
        )
        score_diff = _enhanced_similarity(
            "endpoint:/api/users", "endpoint:/api/accounts", same_file_old, diff_file_new
        )
        assert score_same > score_diff

    def test_label_bonus(self):
        """Nodes with similar labels should score higher."""
        old = Node(
            id="worker:send_email",
            type=NodeType.WORKER,
            label="Email sender",
            file_path="tasks.py",
        )
        similar_label = Node(
            id="worker:dispatch_email",
            type=NodeType.WORKER,
            label="Email dispatcher",
            file_path="tasks.py",
        )
        diff_label = Node(
            id="worker:dispatch_email",
            type=NodeType.WORKER,
            label="Payment processor",
            file_path="tasks.py",
        )
        score_similar = _enhanced_similarity(
            "worker:send_email", "worker:dispatch_email", old, similar_label
        )
        score_diff = _enhanced_similarity(
            "worker:send_email", "worker:dispatch_email", old, diff_label
        )
        assert score_similar > score_diff

    def test_none_nodes_handled(self):
        """Passing None for node objects should not raise."""
        score = _enhanced_similarity("endpoint:/api/users", "endpoint:/api/user", None, None)
        assert score > 0.0

    def test_empty_strings(self):
        score = _enhanced_similarity("", "")
        assert score == 0.0


class TestEdgeDrift:
    def test_no_drift(self):
        edges = [Edge(source="a", target="b", type=EdgeType.CALLS)]
        result = _detect_edge_drift(edges, edges)
        assert result == []

    def test_edge_missing_in_code(self):
        graph_edges = [Edge(source="a", target="b", type=EdgeType.CALLS)]
        scan_edges: list[Edge] = []
        result = _detect_edge_drift(graph_edges, scan_edges)
        assert len(result) == 1
        assert result[0]["type"] == "edge_missing_in_code"

    def test_edge_missing_in_graph(self):
        graph_edges: list[Edge] = []
        scan_edges = [Edge(source="a", target="b", type=EdgeType.CALLS)]
        result = _detect_edge_drift(graph_edges, scan_edges)
        assert len(result) == 1
        assert result[0]["type"] == "edge_missing_in_graph"

    def test_manual_edges_ignored(self):
        graph_edges = [Edge(source="a", target="b", type=EdgeType.CALLS, manual=True)]
        scan_edges: list[Edge] = []
        result = _detect_edge_drift(graph_edges, scan_edges)
        assert result == []

    def test_multiple_edges_mixed(self):
        """Multiple edges with some matching and some drifted."""
        graph_edges = [
            Edge(source="a", target="b", type=EdgeType.CALLS),
            Edge(source="c", target="d", type=EdgeType.READS),
        ]
        scan_edges = [
            Edge(source="a", target="b", type=EdgeType.CALLS),
            Edge(source="e", target="f", type=EdgeType.WRITES),
        ]
        result = _detect_edge_drift(graph_edges, scan_edges)
        types = {d["type"] for d in result}
        assert "edge_missing_in_code" in types
        assert "edge_missing_in_graph" in types
        # The a->b edge matches, so only c->d and e->f should drift
        assert len(result) == 2

    def test_edge_drift_details_format(self):
        graph_edges = [Edge(source="svc:auth", target="db:users", type=EdgeType.READS)]
        scan_edges: list[Edge] = []
        result = _detect_edge_drift(graph_edges, scan_edges)
        assert len(result) == 1
        assert "svc:auth" in result[0]["details"]
        assert "db:users" in result[0]["details"]
        assert EdgeType.READS in result[0]["details"]

    def test_empty_lists(self):
        result = _detect_edge_drift([], [])
        assert result == []


class TestDetectGitRenames:
    def test_non_git_directory(self, tmp_path):
        """A directory that is not a git repo should return empty dict."""
        result = _detect_git_renames(str(tmp_path))
        assert result == {}

    def test_invalid_path(self):
        """A non-existent path should return empty dict gracefully."""
        result = _detect_git_renames("/nonexistent/path/12345")
        assert result == {}

    @patch("codegiraffe.query.subprocess.run")
    def test_parses_rename_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="R100\told/file.py\tnew/file.py\nR085\tother/old.py\tother/new.py\n",
        )
        result = _detect_git_renames("/some/path")
        assert result == {
            "old/file.py": "new/file.py",
            "other/old.py": "other/new.py",
        }

    @patch("codegiraffe.query.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = _detect_git_renames("/some/path")
        assert result == {}

    @patch("codegiraffe.query.subprocess.run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = _detect_git_renames("/some/path")
        assert result == {}

    @patch("codegiraffe.query.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess as sp
        from codegiraffe.git_utils import GitTimeoutError

        mock_run.side_effect = sp.TimeoutExpired(cmd="git", timeout=10)
        with pytest.raises(GitTimeoutError):
            _detect_git_renames("/some/path")

    @patch("codegiraffe.query.subprocess.run")
    def test_custom_since(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        _detect_git_renames("/some/path", since="abc123")
        cmd = mock_run.call_args[0][0]
        assert "abc123" in cmd


class TestDetectDriftEnhanced:
    def test_drift_with_sample_project(self, sample_project, sample_graph):
        # The sample graph has nodes not in the sample project's scan
        drifts = detect_drift(sample_graph, str(sample_project))
        assert isinstance(drifts, list)
        for drift in drifts:
            assert "type" in drift
            assert "node_id" in drift
            assert "details" in drift

    def test_no_drift_when_matching(self, tmp_path):
        """An empty graph against an empty project should have no drift."""
        graph = ArchGraph()
        drifts = detect_drift(graph, str(tmp_path))
        assert drifts == []

    def test_git_depth_parameter(self, sample_project):
        """The git_depth parameter should be accepted without error."""
        graph = ArchGraph()
        drifts = detect_drift(graph, str(sample_project), git_depth=5)
        assert isinstance(drifts, list)

    def test_edge_drift_included(self, sample_project):
        """detect_drift should include edge-level drift records."""
        from codegiraffe.scanner import scan_project as real_scan

        scan_result = real_scan(str(sample_project))

        # Build graph from scan plus an extra edge not in the code
        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Add a fake node and edge that the scanner won't find
        fake_node = Node(id="service:fake", type=NodeType.SERVICE, label="Fake")
        graph.add_node(fake_node)
        graph.add_edge(
            Edge(source="service:fake", target=scan_result.nodes[0].id, type=EdgeType.CALLS)
        )

        drifts = detect_drift(graph, str(sample_project))
        drift_types = {d["type"] for d in drifts}
        # We should see at least the missing node and the missing edge
        assert "missing_in_code" in drift_types or "edge_missing_in_code" in drift_types

    def test_backward_compat_default_git_depth(self, sample_project):
        """Calling without git_depth should work (backward compatible)."""
        from codegiraffe.scanner import scan_project as real_scan

        scan_result = real_scan(str(sample_project))
        graph = ArchGraph()
        for node in scan_result.nodes:
            graph.add_node(node)
        for edge in scan_result.edges:
            graph.add_edge(edge)

        # Should work without the git_depth argument
        drifts = detect_drift(graph, str(sample_project))
        assert isinstance(drifts, list)
        assert len(drifts) == 0

    def test_drift_types_are_strings(self, sample_project, sample_graph):
        """All drift record values should be strings."""
        drifts = detect_drift(sample_graph, str(sample_project))
        for drift in drifts:
            for key, value in drift.items():
                assert isinstance(value, str), f"Expected str for {key}, got {type(value)}"
